"""Migración de datos de la identidad anterior (GestionDepartamentos → Brickly).

La copia se hace una sola vez, al arrancar, antes de abrir la base nueva:

- Si `%APPDATA%\\Brickly\\datos.sqlite3` ya existe, no se toca nada.
- Si no existe y `%APPDATA%\\GestionDepartamentos\\datos.sqlite3` sí, se copia
  con la API de backup de SQLite (incluye WAL), se verifica con
  `PRAGMA integrity_check` y recién ahí se publica el archivo definitivo.
- La base vieja **nunca** se borra: queda como respaldo.

La UI no conoce SQLite: esta función vive en infraestructura y `main.py` es el
único que la invoca.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from brickly.infraestructura.db.conexion import (
    ruta_base_datos,
    ruta_base_datos_legacy,
)

_SUFIJO_TEMPORAL = ".migrando"


def migrar_datos_si_hace_falta(
    origen: Path | None = None,
    destino: Path | None = None,
) -> bool:
    """Copia la base vieja a la nueva si corresponde.

    Devuelve `True` si copió y `False` si no había nada que hacer. Si falla la
    copia o la verificación, lanza `OSError` y no deja una base nueva a medias.
    """
    origen = origen or ruta_base_datos_legacy()
    destino = destino or ruta_base_datos()

    if destino.exists() or not origen.is_file():
        return False

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + _SUFIJO_TEMPORAL)
    temporal.unlink(missing_ok=True)

    try:
        _copiar_con_backup(origen, temporal)
        _verificar_integridad(temporal)
        os.replace(temporal, destino)
    except (OSError, sqlite3.Error) as exc:
        try:
            temporal.unlink(missing_ok=True)
        except OSError:
            pass
        raise OSError(
            "No se pudo migrar la base de datos de GestionDepartamentos a "
            f"Brickly. La base vieja quedó intacta en {origen}. Detalle: {exc}"
        ) from exc

    return True


def _copiar_con_backup(origen: Path, destino: Path) -> None:
    """Copia consistente: SQLite backup lee también el WAL pendiente."""
    with closing(sqlite3.connect(origen)) as con_origen, closing(
        sqlite3.connect(destino)
    ) as con_destino:
        con_origen.backup(con_destino)


def _verificar_integridad(ruta: Path) -> None:
    with closing(sqlite3.connect(ruta)) as con:
        resultados = [fila[0] for fila in con.execute("PRAGMA integrity_check")]
    if resultados != ["ok"]:
        raise OSError(
            "La copia de la base no pasó la verificación de integridad: "
            + "; ".join(str(resultado) for resultado in resultados)
        )
