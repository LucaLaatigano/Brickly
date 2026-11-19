"""Repositorio SQLite de configuración — implementa `RepositorioConfiguracion`.

Lectura completa de la tabla `configuracion`, escritura por lote en una sola
transacción y persistencia transaccional de la imagen de firma en `firma_admin`.
"""

import sqlite3

from brickly.aplicacion.puertos import FirmaAdminGuardada

_SQL_CARGAR = "SELECT clave, valor FROM configuracion"
_SQL_OBTENER_FIRMA = (
    "SELECT nombre_archivo, contenido, actualizado_en "
    "FROM firma_admin WHERE id = 1"
)
_SQL_GUARDAR_FIRMA = (
    "INSERT INTO firma_admin (id, nombre_archivo, contenido, actualizado_en)"
    " VALUES (1, ?, ?, COALESCE(?, datetime('now')))"
    " ON CONFLICT (id) DO UPDATE SET"
    " nombre_archivo = excluded.nombre_archivo,"
    " contenido = excluded.contenido,"
    " actualizado_en = excluded.actualizado_en"
)
_SQL_BORRAR_FIRMA = "DELETE FROM firma_admin WHERE id = 1"


class RepositorioConfiguracionSQLite:
    def __init__(self, conexion: sqlite3.Connection):
        self._conexion = conexion
        self._asegurar_esquema_firma()

    def _asegurar_esquema_firma(self) -> None:
        columnas = {
            fila[1]
            for fila in self._conexion.execute(
                "PRAGMA table_info(firma_admin)"
            ).fetchall()
        }
        if not columnas:
            return
        if "contenido_pdf" in columnas and "contenido" not in columnas:
            with self._conexion:
                self._conexion.execute(
                    "ALTER TABLE firma_admin RENAME COLUMN contenido_pdf TO contenido"
                )
                self._conexion.execute(
                    "DELETE FROM firma_admin WHERE substr(contenido, 1, 5) = ?",
                    (b"%PDF-",),
                )

    def cargar(self) -> dict[str, str]:
        filas = self._conexion.execute(_SQL_CARGAR).fetchall()
        return {fila["clave"]: fila["valor"] for fila in filas}

    def actualizar(self, valores: dict[str, str]) -> None:
        with self._conexion:
            for clave, valor in valores.items():
                self._conexion.execute(
                    "INSERT INTO configuracion (clave, valor) VALUES (?, ?)"
                    " ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
                    (clave, valor),
                )

    def obtener_firma(self) -> FirmaAdminGuardada | None:
        fila = self._conexion.execute(_SQL_OBTENER_FIRMA).fetchone()
        if fila is None:
            return None
        return FirmaAdminGuardada(
            nombre_archivo=str(fila["nombre_archivo"]),
            contenido=bytes(fila["contenido"]),
            actualizado_en=str(fila["actualizado_en"]),
        )

    def guardar_firma(
        self,
        nombre_archivo: str,
        contenido: bytes,
        actualizado_en: str | None = None,
    ) -> None:
        with self._conexion:
            self._conexion.execute(
                _SQL_GUARDAR_FIRMA,
                (nombre_archivo, contenido, actualizado_en),
            )

    def borrar_firma(self) -> None:
        with self._conexion:
            self._conexion.execute(_SQL_BORRAR_FIRMA)
