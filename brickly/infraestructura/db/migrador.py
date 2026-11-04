"""Migraciones secuenciales con `PRAGMA user_version`.

Contrato del esquema (0001_inicial.sql): cada script corre **dentro de una
transacción** y el avance de versión va en la misma transacción, así un corte a
mitad de camino no deja esquema a medias ni versión mentida. Si el script corre
una vez, la siguiente apertura no lo vuelve a correr (la versión lo saltea).

Nombres: `NNNN_descripcion.sql`, con NNNN = versión que deja aplicado.
"""

import re
import sqlite3
import sys
from pathlib import Path

_PATRON = re.compile(r"^(\d{4})_.+\.sql$")


def migrar(con: sqlite3.Connection) -> int:
    """Aplica los scripts pendientes en orden y devuelve la versión final."""
    version = _version_actual(con)
    for numero, script in _pendientes(version):
        _aplicar(con, numero, script)
    return _version_actual(con)


def _version_actual(con: sqlite3.Connection) -> int:
    return con.execute("PRAGMA user_version").fetchone()[0]


def _dir_migraciones() -> Path:
    if getattr(sys, "frozen", False):  # exe PyInstaller: recursos en _MEIPASS
        return Path(sys._MEIPASS) / "brickly" / "infraestructura" / "db" / "migraciones"
    return Path(__file__).resolve().parent / "migraciones"


def _pendientes(version: int):
    for ruta in sorted(_dir_migraciones().glob("*.sql")):
        coincidencia = _PATRON.match(ruta.name)
        if coincidencia and int(coincidencia.group(1)) > version:
            yield int(coincidencia.group(1)), ruta


def _aplicar(con: sqlite3.Connection, numero: int, script: Path) -> None:
    sql = script.read_text(encoding="utf-8")
    try:
        # BEGIN/COMMIT propios: el DDL de SQLite es transaccional, y la versión
        # se setea en la misma transacción que crea el esquema.
        con.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {numero};\nCOMMIT;")
    except Exception:
        con.rollback()
        raise
