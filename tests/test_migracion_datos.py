"""Migración de la base vieja de GestionDepartamentos a Brickly (H5)."""

import sqlite3
from contextlib import closing

import pytest

from brickly.infraestructura.db.conexion import (
    ruta_base_datos,
    ruta_base_datos_legacy,
)
from brickly.infraestructura.db.migracion_datos import migrar_datos_si_hace_falta


def _crear_base(ruta, direcciones):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ruta)) as con:
        con.execute(
            "CREATE TABLE departamentos ("
            "id INTEGER PRIMARY KEY, direccion TEXT NOT NULL)"
        )
        con.executemany(
            "INSERT INTO departamentos (direccion) VALUES (?)",
            [(direccion,) for direccion in direcciones],
        )
        con.commit()


def _direcciones(ruta):
    with closing(sqlite3.connect(ruta)) as con:
        return [fila[0] for fila in con.execute(
            "SELECT direccion FROM departamentos ORDER BY id"
        )]


def test_migra_la_base_vieja_y_conserva_el_origen(tmp_path):
    origen = tmp_path / "GestionDepartamentos" / "datos.sqlite3"
    destino = tmp_path / "Brickly" / "datos.sqlite3"
    _crear_base(origen, ["Rivadavia 3421", "San Martín 120"])

    assert migrar_datos_si_hace_falta(origen=origen, destino=destino) is True

    assert origen.is_file()
    assert _direcciones(destino) == ["Rivadavia 3421", "San Martín 120"]


def test_no_vuelve_a_copiar_si_la_base_nueva_ya_existe(tmp_path):
    origen = tmp_path / "GestionDepartamentos" / "datos.sqlite3"
    destino = tmp_path / "Brickly" / "datos.sqlite3"
    _crear_base(origen, ["Vieja 1"])
    _crear_base(destino, ["Nueva 1"])

    assert migrar_datos_si_hace_falta(origen=origen, destino=destino) is False
    assert _direcciones(destino) == ["Nueva 1"]


def test_sin_base_vieja_no_crea_nada(tmp_path):
    origen = tmp_path / "GestionDepartamentos" / "datos.sqlite3"
    destino = tmp_path / "Brickly" / "datos.sqlite3"

    assert migrar_datos_si_hace_falta(origen=origen, destino=destino) is False
    assert not destino.exists()


def test_base_vieja_corrupta_no_deja_una_base_nueva_a_medias(tmp_path):
    origen = tmp_path / "GestionDepartamentos" / "datos.sqlite3"
    destino = tmp_path / "Brickly" / "datos.sqlite3"
    origen.parent.mkdir(parents=True)
    origen.write_bytes(b"esto no es sqlite")

    with pytest.raises(OSError, match="No se pudo migrar"):
        migrar_datos_si_hace_falta(origen=origen, destino=destino)

    assert not destino.exists()
    assert not destino.with_name(destino.name + ".migrando").exists()
    assert origen.read_bytes() == b"esto no es sqlite"


def test_rutas_de_datos_actual_y_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    actual = ruta_base_datos()
    vieja = ruta_base_datos_legacy()

    assert actual == tmp_path / "Brickly" / "datos.sqlite3"
    assert vieja == tmp_path / "GestionDepartamentos" / "datos.sqlite3"
