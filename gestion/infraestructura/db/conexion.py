"""Conexión SQLite: ruta de la base y PRAGMAs obligatorios.

La base vive en %APPDATA%\\GestionDepartamentos\\datos.sqlite3 — por usuario y
escribible, funciona igual si el exe corre desde Program Files o como onefile
(el temp del unpack es volátil y se pierde entre arranques).
"""

import os
import sqlite3
from pathlib import Path

CARPETA_DATOS = "GestionDepartamentos"
NOMBRE_BASE = "datos.sqlite3"


def ruta_base_datos() -> Path:
    """Ruta de la base dentro del perfil del usuario (Windows: %APPDATA%)."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / CARPETA_DATOS / NOMBRE_BASE


def abrir_conexion(ruta: Path | str) -> sqlite3.Connection:
    """Abre la base creando la carpeta si hace falta.

    `foreign_keys = ON` no es opcional: el esquema depende de las FK (las
    violaciones de `tests/test_esquema_inicial.py` se apoyan en eso).
    """
    if str(ruta) != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con
