"""Migración y conexión: esquema desde cero, una sola vez, FK activas (H0)."""

import sqlite3

import pytest

from brickly.infraestructura.db.conexion import abrir_conexion, ruta_base_datos
from brickly.infraestructura.db.migrador import migrar

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
    return tmp_path / "Brickly" / "datos.sqlite3"


def test_crea_la_base_desde_cero(ruta):
    con = abrir_conexion(ruta)
    assert migrar(con) == 2
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
    assert migrar(con2) == 2
    assert con2.execute("SELECT COUNT(*) FROM departamentos").fetchone()[0] == 1
    con2.close()


def test_migracion_0001_a_0002_conserva_datos_y_agrega_columnas(ruta):
    from pathlib import Path

    sql_0001 = (
        Path(__file__).resolve().parents[1]
        / "brickly"
        / "infraestructura"
        / "db"
        / "migraciones"
        / "0001_inicial.sql"
    ).read_text(encoding="utf-8")

    con = abrir_conexion(ruta)
    con.executescript(sql_0001)
    con.execute("PRAGMA user_version = 1")
    con.execute(
        "INSERT INTO ipc_valores (anio, mes, variacion_bp, origen, cargado_en)"
        " VALUES (2026, 7, 210, 'manual', '2026-08-15 10:00:00')"
    )
    con.commit()

    assert migrar(con) == 2
    fila = con.execute(
        "SELECT anio, mes, variacion_bp, origen, cargado_en, indice_milesimos, actualizado_en"
        " FROM ipc_valores WHERE anio = 2026 AND mes = 7"
    ).fetchone()
    assert fila["variacion_bp"] == 210
    assert fila["origen"] == "manual"
    assert fila["indice_milesimos"] is None
    assert fila["actualizado_en"] == "2026-08-15 10:00:00"

    # CHECK sobre indice_milesimos (> 0 o NULL)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO ipc_valores (anio, mes, variacion_bp, origen, indice_milesimos)"
            " VALUES (2026, 8, 166, 'api', 0)"
        )
    con.close()


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
    assert ruta.parent.name == "Brickly"

