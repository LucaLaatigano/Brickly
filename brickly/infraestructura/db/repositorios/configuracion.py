"""Repositorio SQLite de configuración — implementa `RepositorioConfiguracion`.

Lectura completa de la tabla `configuracion` y escritura por lote en una sola
transacción (el servicio valida antes; acá no hay reglas de negocio).
"""

import sqlite3

_SQL_CARGAR = "SELECT clave, valor FROM configuracion"


class RepositorioConfiguracionSQLite:
    def __init__(self, conexion: sqlite3.Connection):
        self._conexion = conexion

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
