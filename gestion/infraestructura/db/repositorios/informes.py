"""Repositorio SQLite de Informes — implementa `RepositorioInformes` (§3.6).

Una consulta por informe (anti N+1): el estado de cuenta sale de una sola
pasada sobre `cuotas` con sus imputaciones agregadas; la UI nunca ve SQL.
"""

import sqlite3
from datetime import date

from gestion.aplicacion.informes import RegistroEstadoCuenta

_SQL_CONTAR_DEPARTAMENTOS = "SELECT COUNT(*) AS cantidad FROM departamentos"

_SQL_CONTAR_CUOTAS = "SELECT COUNT(*) AS cantidad FROM cuotas"

_SQL_ESTADO_CUENTA = """
SELECT d.id                 AS departamento_id,
       d.direccion          AS direccion,
       d.piso               AS piso,
       d.depto              AS depto,
       i.nombre             AS inquilino,
       cu.anio              AS anio,
       cu.mes               AS mes,
       cu.fecha_vencimiento AS fecha_vencimiento,
       cu.monto_centavos    AS monto_centavos,
       c.dias_gracia        AS dias_gracia,
       c.tasa_mora_bp       AS tasa_mora_bp,
       COALESCE(SUM(im.monto_centavos), 0) AS pagado_centavos,
       COALESCE(SUM(im.mora_centavos), 0)  AS mora_pagada_centavos
  FROM cuotas cu
  JOIN contratos     c  ON c.id = cu.contrato_id
  JOIN departamentos d  ON d.id = c.departamento_id
  JOIN inquilinos    i  ON i.id = c.inquilino_id
  LEFT JOIN imputaciones im ON im.cuota_id = cu.id
 WHERE (? IS NULL OR d.id = ?)
 GROUP BY cu.id
 ORDER BY d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, ''),
          cu.anio, cu.mes, cu.id
"""


class RepositorioInformesSQLite:
    def __init__(self, conexion: sqlite3.Connection):
        self._conexion = conexion

    def contar_departamentos(self) -> int:
        return int(self._conexion.execute(_SQL_CONTAR_DEPARTAMENTOS).fetchone()["cantidad"])

    def contar_cuotas(self) -> int:
        return int(self._conexion.execute(_SQL_CONTAR_CUOTAS).fetchone()["cantidad"])

    def listar_estado_cuenta(
        self, departamento_id: int | None = None
    ) -> list[RegistroEstadoCuenta]:
        filas = self._conexion.execute(
            _SQL_ESTADO_CUENTA, (departamento_id, departamento_id)
        ).fetchall()
        return [
            RegistroEstadoCuenta(
                departamento_id=fila["departamento_id"],
                direccion=fila["direccion"],
                piso=fila["piso"],
                depto=fila["depto"],
                inquilino=fila["inquilino"],
                anio=fila["anio"],
                mes=fila["mes"],
                fecha_vencimiento=date.fromisoformat(fila["fecha_vencimiento"]),
                monto_centavos=fila["monto_centavos"],
                pagado_centavos=fila["pagado_centavos"],
                mora_pagada_centavos=fila["mora_pagada_centavos"],
                dias_gracia=fila["dias_gracia"],
                tasa_mora_bp=fila["tasa_mora_bp"],
            )
            for fila in filas
        ]
