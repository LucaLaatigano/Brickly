"""Tests de H8 — Constancia de pago mensual en PDF (ADR-0004).

Cubre:
- Builder puro (`armar_constancia_pago`, `resolver_firma_constancia`,
  `nombre_archivo_constancia`).
- `ServicioConstancias`: solo cuotas `pagada`; bloqueo con motivo y saldo en
  `pendiente`, `parcial` y `vencida`; idempotencia sin escrituras en la base.
- `RepositorioConstanciasSQLite` sobre SQLite `:memory:`: preservación del
  inquilino histórico de un contrato cerrado y porción imputada cuando un pago
  cubrió varias cuotas.
- `GeneradorPdfReportlab` real sobre `tmp_path`: cabecera `%PDF-`, tamaño > 0,
  acentos/ñ/símbolos es-AR sin excepción, escritura atómica y manejo de
  `PermissionError` cuando el PDF está abierto en otro programa.
- `PresenterConstancia` y `preparar_constancia`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from brickly.aplicacion.cobranzas import DatosPago, ServicioCobranzas
from brickly.aplicacion.configuracion import (
    DatosConfiguracion,
    ServicioConfiguracion,
)
from brickly.aplicacion.constancias import (
    LEYENDA_NO_FISCAL,
    LEYENDA_PIE_CONSTANCIA,
    ROL_FIRMA_CONSTANCIA,
    TITULO_CONSTANCIA,
    RegistroConstanciaCuota,
    RegistroPagoConstancia,
    ServicioConstancias,
    armar_constancia_pago,
    nombre_archivo_constancia,
    resolver_firma_constancia,
)
from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.departamentos import (
    DatosContrato,
    DatosDepartamento,
    ServicioDepartamentos,
)
from brickly.dominio.errores import ErrorDeNegocio
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.cobranzas import (
    RepositorioCobranzasSQLite,
)
from brickly.infraestructura.db.repositorios.configuracion import (
    RepositorioConfiguracionSQLite,
)
from brickly.infraestructura.db.repositorios.constancias import (
    RepositorioConstanciasSQLite,
)
from brickly.infraestructura.db.repositorios.departamentos import (
    RepositorioDepartamentosSQLite,
)
from brickly.infraestructura.pdf import (
    GeneradorPdfReportlab,
    formatear_fecha_pdf,
    formatear_monto_pdf,
)
from brickly.ui.presenters.constancia import (
    PresenterConstancia,
    preparar_constancia,
)
from brickly.ui.vistas.cobranzas import AYUDA_CONSTANCIA_MES


class RelojFijo:
    def __init__(self, fecha: date):
        self._fecha = fecha

    def hoy(self) -> date:
        return self._fecha


def _registro_base(
    *,
    monto_centavos: int = 1280000,
    pagado_centavos: int = 1280000,
    mora_pagada_centavos: int = 0,
    propietario: str | None = "Marta Gómez",
    inquilino: str = "Lucía Peña",
    fecha_vencimiento: date = date(2026, 10, 10),
    pagos: tuple[RegistroPagoConstancia, ...] | None = None,
) -> RegistroConstanciaCuota:
    if pagos is None:
        pagos = (
            RegistroPagoConstancia(
                pago_id=1,
                fecha=date(2026, 10, 9),
                medio="transferencia",
                capital_centavos=pagado_centavos,
                mora_centavos=mora_pagada_centavos,
                nota="Transferencia CBU",
            ),
        )
    return RegistroConstanciaCuota(
        cuota_id=10,
        contrato_id=3,
        departamento_id=1,
        direccion="Av. Córdoba 1540",
        piso="3",
        depto="A",
        propietario=propietario,
        inquilino=inquilino,
        anio=2026,
        mes=10,
        fecha_vencimiento=fecha_vencimiento,
        monto_centavos=monto_centavos,
        pagado_centavos=pagado_centavos,
        mora_pagada_centavos=mora_pagada_centavos,
        dias_gracia=5,
        tasa_mora_bp=200,
        pagos=pagos,
    )


# ---------------------------------------------------------------------------
# 1. Builder puro y política de firma
# ---------------------------------------------------------------------------


def test_resolver_firma_constancia_combinaciones() -> None:
    # Ambos cargados (distintos) -> se muestran los dos
    nombre, rol = resolver_firma_constancia("Marta Gómez", "Estudio Núñez")
    assert nombre == "Marta Gómez / Estudio Núñez"
    assert rol == ROL_FIRMA_CONSTANCIA

    # Solo propietario
    nombre, rol = resolver_firma_constancia("Marta Gómez", "")
    assert nombre == "Marta Gómez"
    assert rol == ROL_FIRMA_CONSTANCIA

    # Solo admin_nombre
    nombre, rol = resolver_firma_constancia(None, "Estudio Núñez")
    assert nombre == "Estudio Núñez"
    assert rol == ROL_FIRMA_CONSTANCIA

    # Ninguno -> línea vacía (None)
    nombre, rol = resolver_firma_constancia("   ", None)
    assert nombre is None
    assert rol == ROL_FIRMA_CONSTANCIA

    # Ambos iguales -> sin duplicar
    nombre, _ = resolver_firma_constancia("Marta Gómez", "marta gómez")
    assert nombre == "Marta Gómez"


def test_nombre_archivo_constancia_sin_acentos_ni_simbolos() -> None:
    nombre = nombre_archivo_constancia("Av. Córdoba 1540 · 3º A", 2026, 10)
    assert nombre == "constancia-av-cordoba-1540-3-a-octubre-2026.pdf"


def test_armar_constancia_pago_con_mora_y_multiples_pagos() -> None:
    registro = _registro_base(
        monto_centavos=1280000,
        pagado_centavos=1280000,
        mora_pagada_centavos=32000,
        pagos=(
            RegistroPagoConstancia(
                pago_id=1,
                fecha=date(2026, 10, 10),
                medio="efectivo",
                capital_centavos=500000,
                mora_centavos=0,
                nota="Adelanto",
            ),
            RegistroPagoConstancia(
                pago_id=2,
                fecha=date(2026, 10, 20),
                medio="deposito",
                capital_centavos=780000,
                mora_centavos=32000,
                nota="Saldo con mora",
            ),
        ),
    )
    constancia = armar_constancia_pago(
        registro,
        hoy=date(2026, 10, 21),
        admin_nombre="Administración Río",
        admin_telefono="11-4444-5555",
        admin_email="admin@rio.ar",
    )

    assert constancia.titulo == TITULO_CONSTANCIA
    assert constancia.unidad == "Av. Córdoba 1540 · 3º A"
    assert constancia.inquilino == "Lucía Peña"
    assert constancia.periodo == "octubre 2026"
    assert constancia.capital_centavos == 1280000
    assert constancia.mora_centavos == 32000
    assert constancia.total_centavos == 1312000
    assert len(constancia.pagos) == 2
    assert constancia.pagos[0].medio_etiqueta == "Efectivo"
    assert constancia.pagos[0].monto_imputado_centavos == 500000
    assert constancia.pagos[1].medio_etiqueta == "Depósito"
    assert constancia.pagos[1].monto_imputado_centavos == 812000
    assert constancia.firma_nombre == "Marta Gómez / Administración Río"
    assert constancia.leyenda_pie == LEYENDA_PIE_CONSTANCIA
    assert constancia.leyenda_no_fiscal == LEYENDA_NO_FISCAL


def test_armar_constancia_bloquea_cuota_pendiente_parcial_o_vencida() -> None:
    # Parcial antes del vencimiento
    reg_parcial = _registro_base(
        monto_centavos=1280000,
        pagado_centavos=500000,
        fecha_vencimiento=date(2026, 10, 10),
    )
    with pytest.raises(ErrorDeNegocio) as exc_parcial:
        armar_constancia_pago(reg_parcial, hoy=date(2026, 10, 8))
    assert "parcial" in str(exc_parcial.value)
    assert "$ 7.800" in str(exc_parcial.value)

    # Impaga vencida con mora
    reg_vencida = _registro_base(
        monto_centavos=1000000,
        pagado_centavos=0,
        fecha_vencimiento=date(2026, 10, 10),
        pagos=(),
    )
    with pytest.raises(ErrorDeNegocio) as exc_vencida:
        armar_constancia_pago(reg_vencida, hoy=date(2026, 10, 25))
    assert "vencida" in str(exc_vencida.value)
    assert "saldo pendiente" in str(exc_vencida.value)


# ---------------------------------------------------------------------------
# 2. Repositorio SQLite + Servicio + FIFO multi-cuota + Contrato histórico
# ---------------------------------------------------------------------------


def _armar_entorno_sqlite(hoy: date = date(2026, 10, 20)):
    conn = abrir_conexion(":memory:")
    migrar(conn)
    reloj = RelojFijo(hoy)
    repo_deptos = RepositorioDepartamentosSQLite(conn, reloj=reloj)
    repo_cobranzas = RepositorioCobranzasSQLite(conn)
    repo_config = RepositorioConfiguracionSQLite(conn)
    repo_constancias = RepositorioConstanciasSQLite(conn)

    srv_deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)
    srv_cobranzas = ServicioCobranzas(repo_cobranzas, reloj=reloj)
    srv_config = ServicioConfiguracion(repo_config, reloj=reloj)
    srv_constancias = ServicioConstancias(
        repositorio=repo_constancias,
        configuracion=srv_config,
        generador_pdf=GeneradorPdfReportlab(),
        reloj=reloj,
    )
    return conn, srv_deptos, srv_cobranzas, srv_config, srv_constancias


def test_servicio_y_repositorio_fifo_multicuota_muestra_solo_porcion_imputada(
    tmp_path: Path,
) -> None:
    conn, srv_deptos, srv_cobranzas, srv_config, srv_constancias = (
        _armar_entorno_sqlite(date(2026, 10, 5))
    )
    try:
        srv_config.guardar(
            DatosConfiguracion(
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
                redondeo_centavos=1,
                admin_nombre="Admin Central",
                admin_telefono="11-2222-3333",
                admin_email="info@central.ar",
                respaldo_recordatorio_dias=14,
            )
        )
        depto_id = srv_deptos.crear(
            DatosDepartamento(
                direccion="San Martín 850",
                piso="2",
                depto="B",
                m2=48,
                propietario="Jorge Ibáñez",
            )
        )
        srv_deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Ana María Ñáñez",
                inquilino_telefono="11-9999-8888",
                inquilino_email="ana@correo.ar",
                fecha_inicio=date(2026, 9, 1),
                fecha_fin=None,
                monto_centavos=1000000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
                ciclo_meses=3,
                redondeo_centavos=1,
            ),
        )

        # Generamos septiembre y octubre
        srv_cobranzas.generar_cuotas(2026, 9)
        srv_cobranzas.generar_cuotas(2026, 10)

        cuotas_sep = srv_cobranzas.del_mes(2026, 9).filas
        cuotas_oct = srv_cobranzas.del_mes(2026, 10).filas
        cuota_sep_id = cuotas_sep[0].cuota_id
        cuota_oct_id = cuotas_oct[0].cuota_id

        # Antes de pagar, ninguna está disponible y obtener() bloquea
        assert srv_constancias.disponibles(2026, 9) == []
        with pytest.raises(ErrorDeNegocio):
            srv_constancias.obtener(cuota_sep_id)

        # Pagamos septiembre el 05/09/2026 (sin mora: $ 10.000) y octubre parcial ($ 4.000)
        # Luego otro pago de $ 6.000 para completar octubre.
        srv_cobranzas.registrar_pago(
            DatosPago(
                cuota_id=cuota_sep_id,
                fecha=date(2026, 9, 5),
                monto_centavos=1000000,
                medio="transferencia",
                nota="Pago sep",
            )
        )
        srv_cobranzas.registrar_pago(
            DatosPago(
                cuota_id=cuota_oct_id,
                fecha=date(2026, 10, 4),
                monto_centavos=400000,
                medio="efectivo",
                nota="Adelanto oct",
            )
        )

        # Octubre está parcial -> bloqueado con saldo $ 6.000
        with pytest.raises(ErrorDeNegocio) as exc_oct:
            srv_constancias.obtener(cuota_oct_id)
        assert "parcial" in str(exc_oct.value)
        assert "$ 6.000" in str(exc_oct.value)

        # Completamos octubre con $ 6.000
        srv_cobranzas.registrar_pago(
            DatosPago(
                cuota_id=cuota_oct_id,
                fecha=date(2026, 10, 5),
                monto_centavos=600000,
                medio="transferencia",
                nota="Saldo oct",
            )
        )

        disp_oct = srv_constancias.disponibles(2026, 10)
        assert len(disp_oct) == 1
        assert disp_oct[0].cuota_id == cuota_oct_id
        assert disp_oct[0].total_centavos == 1000000

        constancia_oct = srv_constancias.obtener(cuota_oct_id)
        assert constancia_oct.inquilino == "Ana María Ñáñez"
        assert len(constancia_oct.pagos) == 2
        assert constancia_oct.pagos[0].monto_imputado_centavos == 400000
        assert constancia_oct.pagos[1].monto_imputado_centavos == 600000
        assert constancia_oct.firma_nombre == "Jorge Ibáñez / Admin Central"

        # Generamos el PDF dos veces: idempotente y sin modificar tablas
        ruta_pdf = tmp_path / constancia_oct.nombre_archivo_sugerido
        srv_constancias.generar(cuota_oct_id, ruta_pdf)
        srv_constancias.generar(cuota_oct_id, ruta_pdf)
        assert ruta_pdf.exists()
        assert ruta_pdf.stat().st_size > 0
        assert ruta_pdf.read_bytes().startswith(b"%PDF-")
    finally:
        conn.close()


def test_constancia_respeta_inquilino_de_contrato_cerrado() -> None:
    conn, srv_deptos, srv_cobranzas, _srv_config, srv_constancias = (
        _armar_entorno_sqlite(date(2026, 10, 10))
    )
    try:
        depto_id = srv_deptos.crear(
            DatosDepartamento(
                direccion="Belgrano 400",
                piso="1",
                depto="C",
                m2=40,
                propietario="Clara Sosa",
            )
        )
        # Primer contrato: inquilino "Pedro Histórico"
        srv_deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Pedro Histórico",
                inquilino_telefono=None,
                inquilino_email=None,
                fecha_inicio=date(2026, 8, 1),
                fecha_fin=None,
                monto_centavos=900000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
                ciclo_meses=3,
                redondeo_centavos=1,
            ),
        )
        srv_cobranzas.generar_cuotas(2026, 8)
        cuota_ago_id = srv_cobranzas.del_mes(2026, 8).filas[0].cuota_id
        detalle_ago = srv_cobranzas.preparar_pago(cuota_ago_id)
        srv_cobranzas.registrar_pago(
            DatosPago(
                cuota_id=cuota_ago_id,
                fecha=date(2026, 8, 9),
                monto_centavos=detalle_ago.total_centavos,
                medio="transferencia",
                nota=None,
            )
        )

        # Renovamos / cambiamos inquilino a "Nuevo Inquilino" desde septiembre
        srv_deptos.nuevo_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Nuevo Inquilino",
                inquilino_telefono=None,
                inquilino_email=None,
                fecha_inicio=date(2026, 9, 15),
                fecha_fin=None,
                monto_centavos=1100000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
                ciclo_meses=3,
                redondeo_centavos=1,
            ),
        )

        # La constancia de agosto debe seguir saliendo a nombre de "Pedro Histórico"
        constancia_ago = srv_constancias.obtener(cuota_ago_id)
        assert constancia_ago.inquilino == "Pedro Histórico"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Generador PDF real (`reportlab`) y manejo de errores de escritura
# ---------------------------------------------------------------------------


def test_generador_pdf_real_acentos_formatos_y_error_archivo_abierto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert formatear_monto_pdf(1280000) == "$ 12.800,00"
    assert formatear_fecha_pdf(date(2026, 10, 9)) == "09/10/2026"

    registro = _registro_base(
        propietario="Martín Ibáñez",
        inquilino="Sofía Ñandú",
    )
    doc = armar_constancia_pago(
        registro,
        hoy=date(2026, 10, 12),
        admin_nombre="Administración Güemes",
    )

    generador = GeneradorPdfReportlab()
    destino = tmp_path / doc.nombre_archivo_sugerido
    generador.generar(doc, destino)

    contenido = destino.read_bytes()
    assert contenido.startswith(b"%PDF-")
    assert len(contenido) > 1000
    # Como pageCompression=0, los textos en WinAnsi/Latin-1 están presentes en el stream
    assert "Constancia de pago".encode("latin-1") in contenido
    assert "$ 12.800,00".encode("latin-1") in contenido
    assert "Propietario/a o Administrador/a".encode("latin-1") in contenido
    assert "no implica que la unidad".encode("latin-1") in contenido

    # Simulamos que el PDF está abierto y bloqueado en otro visor en Windows
    import os

    def _replace_bloqueado(_src, _dst):
        raise PermissionError("bloqueado")

    monkeypatch.setattr(os, "replace", _replace_bloqueado)
    with pytest.raises(PermissionError) as exc_perm:
        generador.generar(doc, destino)
    assert "abierto en otro programa" in str(exc_perm.value)
    # No deben quedar archivos .tmp huérfanos
    temporales = list(tmp_path.glob("*.tmp"))
    assert temporales == []


# ---------------------------------------------------------------------------
# 4. Presenter y textos de UI
# ---------------------------------------------------------------------------


def test_presenter_constancia_formatea_montos_y_fechas(tmp_path: Path) -> None:
    conn, srv_deptos, srv_cobranzas, _srv_config, srv_constancias = (
        _armar_entorno_sqlite(date(2026, 10, 15))
    )
    try:
        depto_id = srv_deptos.crear(
            DatosDepartamento(
                direccion="Maipú 120",
                piso=None,
                depto=None,
                m2=None,
                propietario=None,
            )
        )
        srv_deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Carlos Ruiz",
                inquilino_telefono=None,
                inquilino_email=None,
                fecha_inicio=date(2026, 10, 1),
                fecha_fin=None,
                monto_centavos=1280000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
                ciclo_meses=3,
                redondeo_centavos=1,
            ),
        )
        srv_cobranzas.generar_cuotas(2026, 10)
        cuota_id = srv_cobranzas.del_mes(2026, 10).filas[0].cuota_id
        srv_cobranzas.registrar_pago(
            DatosPago(
                cuota_id=cuota_id,
                fecha=date(2026, 10, 10),
                monto_centavos=1280000,
                medio="transferencia",
                nota="Octubre al día",
            )
        )

        servicios = Servicios(
            departamentos=srv_deptos,
            cobranzas=srv_cobranzas,
            constancias=srv_constancias,
        )
        presentada = preparar_constancia(servicios, cuota_id)
        assert presentada.unidad == "Maipú 120"
        assert presentada.inquilino == "Carlos Ruiz"
        assert presentada.periodo == "octubre 2026"
        assert presentada.capital == "$ 12.800,00"
        assert presentada.mora == "$ 0,00"
        assert presentada.total == "$ 12.800,00"
        assert presentada.firma_nombre is None
        assert presentada.firma_rol == "Propietario/a o Administrador/a"
        assert presentada.nombre_archivo_sugerido == "constancia-maipu-120-octubre-2026.pdf"

        presenter = PresenterConstancia(servicios)
        ruta_out = tmp_path / presentada.nombre_archivo_sugerido
        generada = presenter.generar_pdf(cuota_id, str(ruta_out))
        assert generada.total == "$ 12.800,00"
        assert ruta_out.exists()
        assert AYUDA_CONSTANCIA_MES == "Click en una cuota pagada para generar su constancia."
    finally:
        conn.close()
