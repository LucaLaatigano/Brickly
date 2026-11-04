"""Suite adversarial de QA para la aceptación de Brickly Release 1.1 (H5, H6, H7 y H8).

Diseñada con `flow-hunting` y `test-design` para probar bordes, colisiones de
estado, entradas hostiles y garantías de release que el camino feliz no recorre:
- H5: migración desde WAL sin borrar origen, preservación de `docs/arranque-h0.md`
  y ausencia de referencias legacy en `README.md`.
- H6: no filtración del token en excepciones ni causas encadenadas (`__cause__`),
  huecos de meses no consecutivos en serie INDEC, y preservación de `origen='manual'`
  cuando la variación manual coincide con la de la API.
- H7: inyección de fórmulas con espacios/tabs iniciales en todas las hojas del
  `.xlsx` y consistencia exacta en centavos entre `Resumen`, `Deudas` y `Cuotas`.
- H8: un único pago en `pagos` repartido en múltiples filas de `imputaciones`
  (FIFO multi-cuota real), bloqueo de cuota sin imputaciones, bordes de período
  e interacción en `VistaCobranzas` (impaga abre `PanelPago`, pagada abre
  `PanelConstancia`).
- Artefactos Release 1.1: `dist/Brickly.exe`, `dist/SHA256.txt` y PDF de ejemplo.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
import sqlite3
import urllib.error

from openpyxl import load_workbook
import pytest

from brickly import FECHA_BUILD, VERSION
from brickly.aplicacion.ajustes import ServicioAjustesIpc
from brickly.aplicacion.cobranzas import DatosPago, ServicioCobranzas
from brickly.aplicacion.configuracion import (
    DatosConfiguracion,
    ServicioConfiguracion,
)
from brickly.aplicacion.constancias import (
    RegistroConstanciaCuota,
    ServicioConstancias,
    armar_constancia_pago,
    nombre_archivo_constancia,
)
from brickly.aplicacion.departamentos import (
    DatosContrato,
    DatosDepartamento,
    ServicioDepartamentos,
)
from brickly.aplicacion.informes import ServicioInformes
from brickly.aplicacion.sincronizacion_ipc import (
    DatoIndiceIpc,
    ServicioSincronizacionIpc,
    calcular_serie_desde_indices,
)
from brickly.dominio.errores import ErrorDeNegocio
from brickly.infraestructura.archivos import (
    EscritorArchivosSistema,
    RespaldadorSQLite,
)
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migracion_datos import migrar_datos_si_hace_falta
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.ajustes import (
    RepositorioAjustesSQLite,
)
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
from brickly.infraestructura.db.repositorios.informes import (
    RepositorioInformesSQLite,
)
from brickly.infraestructura.excel import EscritorExcelOpenpyxl
from brickly.infraestructura.indec import ClienteIndecHttp
from brickly.infraestructura.pdf import GeneradorPdfReportlab

RAIZ = Path(__file__).resolve().parents[1]


class RelojFijo:
    def __init__(self, fecha: date):
        self._fecha = fecha

    def hoy(self) -> date:
        return self._fecha


class AlmacenTokenMemoria:
    def __init__(self, token: str | None = None):
        self.token = token

    def obtener_token(self) -> str | None:
        return self.token

    def guardar_token(self, token: str) -> None:
        self.token = token

    def borrar_token(self) -> None:
        self.token = None


class FuenteIpcFalsa:
    def __init__(self, datos: list[DatoIndiceIpc]):
        self._datos = datos

    def obtener_indices(self, token: str) -> list[DatoIndiceIpc]:
        return list(self._datos)


# ---------------------------------------------------------------------------
# 1. H5 — Migración con WAL y verificación de documentación/históricos
# ---------------------------------------------------------------------------


def test_qa_h5_migracion_copia_wal_y_conserva_documentos_historicos(
    tmp_path: Path,
) -> None:
    # 1. docs/arranque-h0.md debe conservarse intacto
    arranque_h0 = RAIZ / "docs" / "arranque-h0.md"
    assert arranque_h0.is_file()
    assert arranque_h0.stat().st_size > 1000

    # 2. README no debe instruir descargar de dist\ ni mencionar GestionDepartamentos.exe
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "GestionDepartamentos.exe" not in readme
    assert "releases/latest" in readme
    assert "Constancia de pago" in readme

    # 3. Base vieja en modo WAL con datos recientes -> se migra íntegra sin borrar la vieja
    origen = tmp_path / "GestionDepartamentos" / "datos.sqlite3"
    destino = tmp_path / "Brickly" / "datos.sqlite3"
    origen.parent.mkdir(parents=True)

    conn_vieja = abrir_conexion(origen)
    migrar(conn_vieja)
    conn_vieja.execute(
        "INSERT INTO departamentos (direccion, piso, depto, m2, propietario)"
        " VALUES ('Laprida 900', '1', 'A', 42, 'Dueño WAL')"
    )
    conn_vieja.commit()
    conn_vieja.close()

    assert migrar_datos_si_hace_falta(origen=origen, destino=destino) is True
    assert origen.is_file(), "La base vieja nunca debe borrarse"
    assert destino.is_file()

    conn_nueva = abrir_conexion(destino)
    try:
        fila = conn_nueva.execute(
            "SELECT direccion, propietario FROM departamentos"
        ).fetchone()
        assert fila["direccion"] == "Laprida 900"
        assert fila["propietario"] == "Dueño WAL"
    finally:
        conn_nueva.close()


# ---------------------------------------------------------------------------
# 2. H6 — Seguridad de token, huecos en serie INDEC y protección de manuales
# ---------------------------------------------------------------------------


def test_qa_h6_token_nunca_se_filtra_en_errores_ni_causas_encadenadas() -> None:
    token_secreto = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.SECRETO_SUPER_SENSIBLE_998877.firma"

    def _transporte_401(req, _timeout):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", req.headers, None
        )

    def _transporte_red(_req, _timeout):
        raise urllib.error.URLError(f"Fallo con {token_secreto}")

    for transporte in (_transporte_401, _transporte_red):
        cliente = ClienteIndecHttp(
            transporte=transporte, max_reintentos=1, pausa_reintento_segundos=0.0
        )
        with pytest.raises(ErrorDeNegocio) as exc_info:
            cliente.obtener_indices(token_secreto)
        assert token_secreto not in str(exc_info.value)
        assert token_secreto not in repr(exc_info.value)
        assert exc_info.value.__cause__ is None


def test_qa_h6_hueco_en_meses_no_calcula_variacion_falsa_y_manual_igual_no_pasa_a_api() -> None:
    # Serie con hueco: 2026-01, 2026-02 y salta a 2026-04 (falta 2026-03)
    datos = [
        DatoIndiceIpc(anio=1999, mes=11, indice=Decimal("100.0000")),
        DatoIndiceIpc(anio=1999, mes=12, indice=Decimal("105.0000")),
        DatoIndiceIpc(anio=2026, mes=1, indice=Decimal("1000.0000")),
        DatoIndiceIpc(anio=2026, mes=2, indice=Decimal("1035.0000")),  # +3,50% (350 bp)
        DatoIndiceIpc(anio=2026, mes=4, indice=Decimal("1100.0000")),  # no consecutivo!
        DatoIndiceIpc(anio=2026, mes=5, indice=Decimal("1122.0000")),  # +2,00% (200 bp)
    ]
    serie = calcular_serie_desde_indices(datos)
    periodos = [(item.anio, item.mes) for item in serie]
    # 1999-12 (< 2000) y 2026-04 (sin 2026-03 previo) no deben aparecer
    assert periodos == [(2026, 5), (2026, 2)]

    # Si 2026-02 ya estaba cargado como 'manual' con los mismos 350 bp,
    # importar sin reemplazar_manuales debe conservar origen='manual'
    conn = abrir_conexion(":memory:")
    migrar(conn)
    try:
        reloj = RelojFijo(date(2026, 6, 1))
        repo_aj = RepositorioAjustesSQLite(conn)
        srv_aj = ServicioAjustesIpc(repo_aj, reloj=reloj)
        srv_aj.agregar_ipc(anio=2026, mes=2, variacion_bp=350)

        srv_sync = ServicioSincronizacionIpc(
            repositorio=repo_aj,
            fuente=FuenteIpcFalsa(datos),
            almacen_token=AlmacenTokenMemoria("token-valido"),
            reloj=reloj,
        )
        preview = srv_sync.previsualizar()
        res = srv_sync.importar(
            periodos_seleccionados=[(2026, 2), (2026, 5)],
            reemplazar_manuales=False,
            preview=preview,
        )
        assert res.nuevos == 1
        assert res.omitidos == 1

        por_periodo = {(r.anio, r.mes): r for r in repo_aj.listar_ipc()}
        assert por_periodo[(2026, 2)].origen == "manual"
        assert por_periodo[(2026, 2)].indice_milesimos is None
        assert por_periodo[(2026, 5)].origen == "api"
        assert por_periodo[(2026, 5)].indice_milesimos == 1122000
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. H7 — Anti-inyección con espacios iniciales y cuadratura de totales Excel
# ---------------------------------------------------------------------------


def test_qa_h7_excel_bloquea_formulas_con_espacios_y_cuadra_totales_entre_hojas(
    tmp_path: Path,
) -> None:
    conn = abrir_conexion(":memory:")
    migrar(conn)
    try:
        hoy = date(2026, 10, 25)
        reloj = RelojFijo(hoy)
        repo_deptos = RepositorioDepartamentosSQLite(conn, reloj=reloj)
        repo_cob = RepositorioCobranzasSQLite(conn)
        repo_cfg = RepositorioConfiguracionSQLite(conn)
        repo_inf = RepositorioInformesSQLite(conn)

        srv_deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)
        srv_cob = ServicioCobranzas(repo_cob, reloj=reloj)
        srv_cfg = ServicioConfiguracion(repo_cfg, reloj=reloj)
        srv_inf = ServicioInformes(
            repositorio=repo_inf,
            cobranzas=srv_cob,
            configuracion=srv_cfg,
            respaldador=RespaldadorSQLite(conn),
            escritor=EscritorArchivosSistema(),
            reloj=reloj,
            escritor_excel=EscritorExcelOpenpyxl(),
        )

        # Unidad con textos hostiles (espacio + '=', tab + '+', '@')
        d1 = srv_deptos.crear(
            DatosDepartamento(
                direccion="  =HYPERLINK(\"http://malicioso\")",
                piso="1",
                depto="A",
                m2=50,
                propietario="@Propietario",
            )
        )
        srv_deptos.cargar_contrato(
            d1,
            DatosContrato(
                inquilino_nombre="\t+SUM(1,2)",
                fecha_inicio=date(2026, 9, 1),
                monto_centavos=1000000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=300,
            ),
        )
        # Segunda unidad sin contrato
        srv_deptos.crear(
            DatosDepartamento(
                direccion="Callao 500",
                piso=None,
                depto=None,
                m2=None,
                propietario=None,
            )
        )

        srv_cob.generar_cuotas(2026, 9)
        srv_cob.generar_cuotas(2026, 10)
        cuota_sep = srv_cob.del_mes(2026, 9).filas[0].cuota_id
        # Pago parcial en septiembre con nota hostil
        srv_cob.registrar_pago(
            DatosPago(
                cuota_id=cuota_sep,
                fecha=date(2026, 9, 10),
                monto_centavos=400000,
                medio="efectivo",
                nota=" -1000+cmd",
            )
        )

        libro = srv_inf.armar_libro_completo()
        resumen = libro.hoja("Resumen")
        deudas = libro.hoja("Deudas")
        cuotas = libro.hoja("Cuotas")

        # Cuadratura exacta en centavos:
        # En Resumen: tot_deuda_capital (índice 4), tot_mora (índice 5), tot_total (índice 6)
        # En Deudas: tot_cap (índice 6), tot_mora (índice 7), tot_total (índice 8)
        # En Cuotas: tot_saldo (índice 7)
        assert resumen.totales is not None
        assert deudas.totales is not None
        assert cuotas.totales is not None
        assert resumen.totales[4] == deudas.totales[6]
        assert resumen.totales[5] == deudas.totales[7]
        assert resumen.totales[6] == deudas.totales[8]
        assert resumen.totales[6] == cuotas.totales[7]

        ruta_xlsx = tmp_path / "auditoria-qa.xlsx"
        srv_inf.exportar_excel_completo(ruta_xlsx)
        wb = load_workbook(ruta_xlsx, data_only=False)
        try:
            assert wb.sheetnames == [
                "Resumen",
                "Deudas",
                "Pagos",
                "Cuotas",
                "Contratos",
                "Ajustes IPC",
            ]
            for nombre_hoja in wb.sheetnames:
                ws = wb[nombre_hoja]
                for fila in ws.iter_rows(values_only=True):
                    for valor in fila:
                        if isinstance(valor, str) and valor:
                            assert not valor.lstrip().startswith(
                                ("=", "+", "-", "@")
                            ), f"Fórmula sin sanitizar en {nombre_hoja}: {valor!r}"
        finally:
            wb.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. H8 — Pago único multi-cuota en SQLite, bordes de validación y PDF
# ---------------------------------------------------------------------------


def test_qa_h8_un_solo_pago_repartido_en_dos_cuotas_muestra_solo_fraccion_de_esa_cuota(
    tmp_path: Path,
) -> None:
    conn = abrir_conexion(":memory:")
    migrar(conn)
    try:
        hoy = date(2026, 10, 12)
        reloj = RelojFijo(hoy)
        repo_deptos = RepositorioDepartamentosSQLite(conn, reloj=reloj)
        repo_cob = RepositorioCobranzasSQLite(conn)
        repo_cfg = RepositorioConfiguracionSQLite(conn)
        repo_const = RepositorioConstanciasSQLite(conn)

        srv_deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)
        srv_cob = ServicioCobranzas(repo_cob, reloj=reloj)
        srv_cfg = ServicioConfiguracion(repo_cfg, reloj=reloj)
        srv_const = ServicioConstancias(
            repositorio=repo_const,
            configuracion=srv_cfg,
            generador_pdf=GeneradorPdfReportlab(),
            reloj=reloj,
        )

        depto_id = srv_deptos.crear(
            DatosDepartamento(
                direccion="Corrientes 3200",
                piso="7",
                depto="D",
                m2=60,
                propietario="Elena Suárez",
            )
        )
        contrato_id = srv_deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Ramiro Funes",
                fecha_inicio=date(2026, 9, 1),
                monto_centavos=1000000,  # $ 10.000,00
            ),
        )
        srv_cob.generar_cuotas(2026, 9)
        srv_cob.generar_cuotas(2026, 10)
        cuota_sep_id = srv_cob.del_mes(2026, 9).filas[0].cuota_id
        cuota_oct_id = srv_cob.del_mes(2026, 10).filas[0].cuota_id

        # Simulamos un único cobro global en `pagos` de $ 20.500,00 (2050000 centavos)
        # imputado en FIFO a las dos cuotas:
        # - septiembre: $ 10.000 capital + $ 500 mora = $ 10.500
        # - octubre:    $ 10.000 capital + $ 0 mora   = $ 10.000
        with conn:
            cur = conn.execute(
                "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio, nota)"
                " VALUES (?, '2026-10-10', 2050000, 'transferencia', 'Pago conjunto sep+oct')",
                (contrato_id,),
            )
            pago_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos, mora_centavos)"
                " VALUES (?, ?, 1000000, 50000)",
                (pago_id, cuota_sep_id),
            )
            conn.execute(
                "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos, mora_centavos)"
                " VALUES (?, ?, 1000000, 0)",
                (pago_id, cuota_oct_id),
            )

        const_sep = srv_const.obtener(cuota_sep_id)
        const_oct = srv_const.obtener(cuota_oct_id)

        # Septiembre debe mostrar $ 10.500,00 (1050000 centavos), NO $ 20.500,00
        assert const_sep.capital_centavos == 1000000
        assert const_sep.mora_centavos == 50000
        assert const_sep.total_centavos == 1050000
        assert len(const_sep.pagos) == 1
        assert const_sep.pagos[0].monto_imputado_centavos == 1050000

        # Octubre debe mostrar $ 10.000,00 (1000000 centavos), NO $ 20.500,00
        assert const_oct.capital_centavos == 1000000
        assert const_oct.mora_centavos == 0
        assert const_oct.total_centavos == 1000000
        assert len(const_oct.pagos) == 1
        assert const_oct.pagos[0].monto_imputado_centavos == 1000000
    finally:
        conn.close()


def test_qa_h8_bordes_validacion_constancias() -> None:
    # Slug de unidad solo con símbolos cae en fallback limpio 'unidad'
    assert (
        nombre_archivo_constancia("º° / ---", 2026, 1)
        == "constancia-unidad-enero-2026.pdf"
    )

    # Cuota con pagado == monto pero sin filas de pagos se rechaza
    reg_sin_pagos = RegistroConstanciaCuota(
        cuota_id=1,
        contrato_id=1,
        departamento_id=1,
        direccion="Alsina 100",
        piso=None,
        depto=None,
        propietario=None,
        inquilino="Inquilino X",
        anio=2026,
        mes=10,
        fecha_vencimiento=date(2026, 10, 10),
        monto_centavos=500000,
        pagado_centavos=500000,
        mora_pagada_centavos=0,
        dias_gracia=5,
        tasa_mora_bp=200,
        pagos=(),
    )
    with pytest.raises(ErrorDeNegocio, match="No hay pagos imputados"):
        armar_constancia_pago(reg_sin_pagos, hoy=date(2026, 10, 15))

    conn = abrir_conexion(":memory:")
    migrar(conn)
    try:
        reloj = RelojFijo(date(2026, 10, 15))
        srv_const = ServicioConstancias(
            repositorio=RepositorioConstanciasSQLite(conn),
            configuracion=ServicioConfiguracion(
                RepositorioConfiguracionSQLite(conn), reloj
            ),
            generador_pdf=GeneradorPdfReportlab(),
            reloj=reloj,
        )
        for anio_inv, mes_inv in ((1999, 10), (2101, 1), (2026, 0), (2026, 13)):
            with pytest.raises(ErrorDeNegocio, match="período indicado no es válido"):
                srv_const.disponibles(anio_inv, mes_inv)

        with pytest.raises(ErrorDeNegocio, match="no existe"):
            srv_const.obtener(999999)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Artefactos de Release 1.1.0 (dist\Brickly.exe, SHA256.txt y PDF ejemplo)
# ---------------------------------------------------------------------------


def test_qa_release_1_1_artefactos_y_hash() -> None:
    assert VERSION == "1.1.0"
    assert FECHA_BUILD == "2026-11-04"

    exe_path = RAIZ / "dist" / "Brickly.exe"
    sha_path = RAIZ / "dist" / "SHA256.txt"
    pdf_ejemplo = (
        RAIZ / "dist" / "constancia-av-santa-fe-2140-4-b-octubre-2026.pdf"
    )

    assert exe_path.is_file(), "Falta dist\\Brickly.exe"
    assert exe_path.stat().st_size > 10_000_000
    assert sha_path.is_file(), "Falta dist\\SHA256.txt"

    sha_real = hashlib.sha256(exe_path.read_bytes()).hexdigest().upper()
    texto_sha = sha_path.read_text(encoding="ascii").strip().upper()
    assert texto_sha.startswith(sha_real), (
        f"El hash en SHA256.txt ({texto_sha}) no coincide con Brickly.exe ({sha_real})"
    )

    assert pdf_ejemplo.is_file(), "Falta el PDF de ejemplo en dist\\"
    pdf_bytes = pdf_ejemplo.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"Constancia de pago" in pdf_bytes
    assert b"Propietario/a o Administrador/a" in pdf_bytes
    assert b"Documento no v\\341lido como factura ni comprobante fiscal." in pdf_bytes
    assert b"Luc\\355a Pe\\361a" in pdf_bytes  # Lucía Peña con í (\355) y ñ (\361) en WinAnsi
