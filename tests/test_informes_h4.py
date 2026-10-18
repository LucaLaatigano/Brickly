"""Integración de H4: CSV reales, respaldo SQLite y contrato vencido (§3.1/§3.6).

Cablea repositorios reales sobre una base en memoria y el escritor/backup de
verdad sobre `tmp_path`: es el mismo camino que usa `main.py`.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from gestion.aplicacion.cobranzas import ServicioCobranzas
from gestion.aplicacion.configuracion import ServicioConfiguracion
from gestion.aplicacion.departamentos import (
    DatosContrato,
    DatosDepartamento,
    ServicioDepartamentos,
)
from gestion.aplicacion.informes import ServicioInformes
from gestion.dominio.errores import ErrorDeNegocio
from gestion.infraestructura.archivos import EscritorArchivosSistema, RespaldadorSQLite
from gestion.infraestructura.db.conexion import abrir_conexion
from gestion.infraestructura.db.migrador import migrar
from gestion.infraestructura.db.repositorios.cobranzas import RepositorioCobranzasSQLite
from gestion.infraestructura.db.repositorios.configuracion import (
    RepositorioConfiguracionSQLite,
)
from gestion.infraestructura.db.repositorios.departamentos import (
    RepositorioDepartamentosSQLite,
)
from gestion.infraestructura.db.repositorios.informes import RepositorioInformesSQLite

HOY = date(2026, 10, 15)


class RelojFijo:
    def __init__(self, fecha: date = HOY):
        self.fecha = fecha

    def hoy(self) -> date:
        return self.fecha


@pytest.fixture()
def entorno(tmp_path: Path):
    con = abrir_conexion(":memory:")
    migrar(con)
    reloj = RelojFijo()
    repo_deptos = RepositorioDepartamentosSQLite(con, reloj=reloj)
    deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)
    cobranzas = ServicioCobranzas(RepositorioCobranzasSQLite(con), reloj=reloj)
    configuracion = ServicioConfiguracion(RepositorioConfiguracionSQLite(con), reloj)
    informes = ServicioInformes(
        repositorio=RepositorioInformesSQLite(con),
        cobranzas=cobranzas,
        configuracion=configuracion,
        respaldador=RespaldadorSQLite(con),
        escritor=EscritorArchivosSistema(),
        reloj=reloj,
    )
    yield con, deptos, cobranzas, configuracion, informes, tmp_path
    con.close()


def _unidad(deptos: ServicioDepartamentos, direccion: str = "Rivadavia 3421") -> int:
    depto_id = deptos.crear(DatosDepartamento(direccion=direccion))
    deptos.cargar_contrato(
        depto_id,
        DatosContrato(
            inquilino_nombre="Laura Giménez",
            fecha_inicio=date(2026, 1, 1),
            monto_centavos=1_280_000,
            dia_vencimiento=10,
        ),
    )
    return depto_id


def _leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8-sig")


class TestExportaciones:
    def test_estado_cuenta_con_datos_reales(self, entorno):
        _con, deptos, cobranzas, _cfg, informes, tmp_path = entorno
        _unidad(deptos)
        cobranzas.generar_cuotas(2026, 10)

        estado = informes.estado()
        assert estado.hay_departamentos is True
        assert estado.hay_cuotas is True
        assert estado.cobranzas_generadas is True

        ruta = tmp_path / "estado-de-cuenta.csv"
        informes.exportar_estado_cuenta(ruta)

        crudo = ruta.read_bytes()
        assert crudo.startswith(b"\xef\xbb\xbf")  # BOM para Excel
        texto = crudo.decode("utf-8-sig")
        lineas = texto.split("\r\n")
        assert lineas[0] == "Unidad;Inquilino;Período;Vence;Cuota;Pagado;Mora;Saldo;Estado"
        # Vence 10/10, hoy 15/10, gracia 5 → mora 0; saldo $ 12.800.
        assert (
            lineas[1]
            == "Rivadavia 3421;Laura Giménez;octubre 2026;10/10/2026;"
            "12800,00;0,00;0,00;12800,00;Vencida"
        )

    def test_cobranzas_y_morosos_del_periodo(self, entorno):
        _con, _deptos, cobranzas, _cfg, informes, tmp_path = entorno
        _unidad(_deptos)
        cobranzas.generar_cuotas(2026, 10)

        ruta_cobranzas = tmp_path / "cobranzas.csv"
        informes.exportar_cobranzas_del_mes(ruta_cobranzas)
        assert "Rivadavia 3421" in _leer(ruta_cobranzas)
        assert "10/10/2026" in _leer(ruta_cobranzas)

        ruta_morosos = tmp_path / "morosos.csv"
        informes.exportar_morosos(ruta_morosos)
        assert (
            "Rivadavia 3421;Laura Giménez;octubre 2026;10/10/2026;5;12800,00;0,00;12800,00"
            in _leer(ruta_morosos)
        )

    def test_export_por_departamento_filtra(self, entorno):
        _con, deptos, cobranzas, _cfg, informes, tmp_path = entorno
        depto_a = _unidad(deptos, "Rivadavia 3421")
        _unidad(deptos, "Mitre 1180")
        cobranzas.generar_cuotas(2026, 10)

        ruta = tmp_path / "solo-a.csv"
        informes.exportar_estado_cuenta(ruta, departamento_id=depto_a)
        texto = _leer(ruta)
        assert "Rivadavia 3421" in texto
        assert "Mitre 1180" not in texto

    def test_sin_cuotas_nada_se_exporta(self, entorno):
        *_resto, informes, _tmp = entorno
        with pytest.raises(ErrorDeNegocio):
            informes.exportar_estado_cuenta("ec.csv")
        with pytest.raises(ErrorDeNegocio):
            informes.exportar_cobranzas_del_mes("c.csv")
        with pytest.raises(ErrorDeNegocio):
            informes.exportar_morosos("m.csv")


class TestRespaldo:
    def test_copia_valida_y_registra_fecha(self, entorno):
        _con, deptos, cobranzas, configuracion, informes, tmp_path = entorno
        _unidad(deptos)
        cobranzas.generar_cuotas(2026, 10)

        destino = tmp_path / "copia.sqlite3"
        informes.respaldar(destino)

        assert destino.exists()
        copia = sqlite3.connect(destino)
        try:
            filas = copia.execute("SELECT direccion FROM departamentos").fetchall()
        finally:
            copia.close()
        assert filas == [("Rivadavia 3421",)]
        assert configuracion.ultimo_respaldo() == HOY
        # La base original sigue operativa después del backup.
        assert len(deptos.listar()) == 1


class TestContratoVencido:
    def test_listado_marca_el_cierre_sin_renovar(self, entorno):
        _con, deptos, _cob, _cfg, _informes, _tmp = entorno
        depto_id = deptos.crear(DatosDepartamento(direccion="Sarmiento 890"))
        deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Ana Pérez",
                fecha_inicio=date(2026, 1, 1),
                monto_centavos=800_000,
                fecha_fin=date(2026, 9, 30),
            ),
        )

        (fila,) = deptos.listar()
        assert fila.inquilino is None
        assert fila.fecha_contrato_vencido == date(2026, 9, 30)

    def test_sin_vencimiento_no_marca(self, entorno):
        _con, deptos, _cob, _cfg, _informes, _tmp = entorno
        depto_id = deptos.crear(DatosDepartamento(direccion="Mitre 1180"))
        deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Diego Ferreyra",
                fecha_inicio=date(2026, 8, 1),
                monto_centavos=960_000,
            ),
        )
        (fila,) = deptos.listar()
        assert fila.fecha_contrato_vencido is None
