"""Migración y conexión: esquema desde cero, una sola vez, FK activas (H0)."""

import sqlite3

import pytest

from gestion.infraestructura.db.conexion import abrir_conexion, ruta_base_datos
from gestion.infraestructura.db.migrador import migrar

TABLAS = {
    "ajustes",
    "configuracion",
    "contratos",
    "cuotas",
    "departamentos",
    "imputaciones",
    "inquilinos",
    "ipc_valores",
    "pagos",
}


@pytest.fixture()
def ruta(tmp_path):
    return tmp_path / "GestionDepartamentos" / "datos.sqlite3"


def test_crea_la_base_desde_cero(ruta):
    con = abrir_conexion(ruta)
    assert migrar(con) == 1
    tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tablas == TABLAS
    con.close()


def test_segunda_apertura_no_re_migra(ruta):
    con = abrir_conexion(ruta)
    migrar(con)
    con.execute("INSERT INTO departamentos (direccion) VALUES ('Rivadavia 3421')")
    con.commit()
    con.close()

    con2 = abrir_conexion(ruta)
    # Si re-corriera el script, el CREATE TABLE fallaría: no re-migra.
    assert migrar(con2) == 1
    assert con2.execute("SELECT COUNT(*) FROM departamentos").fetchone()[0] == 1
    con2.close()


def test_foreign_keys_activas(ruta):
    con = abrir_conexion(ruta)
    migrar(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO contratos (departamento_id, inquilino_id, fecha_inicio, monto_centavos) "
            "VALUES (999, 999, '2026-01-01', 100)"
        )
    con.close()


def test_ruta_por_usuario_bajo_appdata():
    ruta = ruta_base_datos()
    assert ruta.name == "datos.sqlite3"
    assert ruta.parent.name == "GestionDepartamentos"
