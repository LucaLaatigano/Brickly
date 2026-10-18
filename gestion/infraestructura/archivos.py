"""Adaptadores de sistema de archivos — implementan `EscritorArchivos` y `Respaldador`.

- `EscritorArchivosSistema` graba texto con `utf-8-sig` (Excel abre los CSV con
  acentos correctos) y conserva los saltos `\\r\\n` que genera el módulo `csv`.
- `RespaldadorSQLite` usa el backup API de SQLite (`Connection.backup`): una
  copia consistente aunque haya una conexión abierta, sin bloquear la app.
"""

import sqlite3
from pathlib import Path


class EscritorArchivosSistema:
    def escribir(self, ruta: Path | str, contenido: str) -> None:
        Path(ruta).write_text(contenido, encoding="utf-8-sig", newline="")


class RespaldadorSQLite:
    def __init__(self, conexion: sqlite3.Connection):
        self._conexion = conexion

    def respaldar(self, destino: Path | str) -> None:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        copia = sqlite3.connect(destino)
        try:
            with copia:
                self._conexion.backup(copia)
        except sqlite3.Error as error:
            # La UI (que no conoce sqlite3) captura OSError; el detalle viaja igual.
            raise OSError(f"No se pudo copiar la base: {error}") from error
        finally:
            copia.close()
