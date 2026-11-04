"""Repositorio SQLite de Cobranzas — implementa `RepositorioCobranzas`.

Todo el SQL de generación idempotente, lectura de cuotas del mes/atrasos y
escritura transaccional de pagos + imputaciones vive acá (ADR-0001).
"""

import sqlite3
from datetime import date

from brickly.aplicacion.cobranzas import ContratoParaCuota, RegistroCuotaMes
from brickly.dominio.cuota import Cuota
from brickly.dominio.pago import ImputacionPago, MedioPago, Pago

_SQL_CONTRATOS_PENDIENTES = """
SELECT c.id              AS contrato_id,
       c.departamento_id AS departamento_id,
       c.monto_centavos  AS monto_centavos,
       c.dia_vencimiento AS dia_vencimiento
  FROM contratos c
  JOIN departamentos d ON d.id = c.departamento_id
 WHERE c.fecha_fin IS NULL
   AND NOT EXISTS (
       SELECT 1
         FROM cuotas cu
        WHERE cu.contrato_id = c.id
          AND cu.anio = ?
          AND cu.mes  = ?
   )
 ORDER BY d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, '')
"""

_SQL_UNIDADES_SIN_CONTRATO = """
SELECT COUNT(*) AS cantidad
  FROM departamentos d
 WHERE NOT EXISTS (
       SELECT 1
         FROM contratos c
        WHERE c.departamento_id = d.id
          AND c.fecha_fin IS NULL
 )
"""

_SQL_CUOTAS_EXISTENTES = """
SELECT COUNT(*) AS cantidad
  FROM cuotas
 WHERE anio = ? AND mes = ?
"""

_SQL_BASE_CUOTAS = """
SELECT cu.id                AS cuota_id,
       cu.contrato_id       AS contrato_id,
       d.id                 AS departamento_id,
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
"""

_SQL_LISTAR_MES = (
    _SQL_BASE_CUOTAS
    + """
 WHERE cu.anio = ? AND cu.mes = ?
 GROUP BY cu.id
 ORDER BY d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, '')
"""
)

_SQL_LISTAR_IMPAGAS = (
    _SQL_BASE_CUOTAS
    + """
 GROUP BY cu.id
HAVING cu.monto_centavos > COALESCE(SUM(im.monto_centavos), 0)
 ORDER BY cu.fecha_vencimiento ASC, cu.id ASC
"""
)

_SQL_OBTENER_CUOTA = (
    _SQL_BASE_CUOTAS
    + """
 WHERE cu.id = ?
 GROUP BY cu.id
"""
)


class RepositorioCobranzasSQLite:
    def __init__(self, conexion: sqlite3.Connection):
        self._conexion = conexion

    def contratos_para_generar(
        self, anio: int, mes: int
    ) -> tuple[list[ContratoParaCuota], int, int]:
        filas = self._conexion.execute(
            _SQL_CONTRATOS_PENDIENTES, (anio, mes)
        ).fetchall()
        pendientes = [
            ContratoParaCuota(
                contrato_id=fila["contrato_id"],
                departamento_id=fila["departamento_id"],
                monto_centavos=fila["monto_centavos"],
                dia_vencimiento=fila["dia_vencimiento"],
            )
            for fila in filas
        ]
        sin_contrato = int(
            self._conexion.execute(_SQL_UNIDADES_SIN_CONTRATO).fetchone()["cantidad"]
        )
        existentes = int(
            self._conexion.execute(_SQL_CUOTAS_EXISTENTES, (anio, mes)).fetchone()[
                "cantidad"
            ]
        )
        return pendientes, sin_contrato, existentes

    def guardar_cuotas(self, cuotas: list[Cuota]) -> int:
        insertadas = 0
        with self._conexion:
            for cuota in cuotas:
                cursor = self._conexion.execute(
                    "INSERT OR IGNORE INTO cuotas"
                    " (contrato_id, anio, mes, fecha_vencimiento, monto_centavos)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        cuota.contrato_id,
                        cuota.anio,
                        cuota.mes,
                        cuota.fecha_vencimiento.isoformat(),
                        cuota.monto_centavos,
                    ),
                )
                insertadas += cursor.rowcount
        return insertadas

    def listar_cuotas_del_mes(self, anio: int, mes: int) -> list[RegistroCuotaMes]:
        filas = self._conexion.execute(_SQL_LISTAR_MES, (anio, mes)).fetchall()
        return [self._a_registro(fila) for fila in filas]

    def listar_cuotas_impagas(self) -> list[RegistroCuotaMes]:
        filas = self._conexion.execute(_SQL_LISTAR_IMPAGAS).fetchall()
        return [self._a_registro(fila) for fila in filas]

    def obtener_cuota(self, cuota_id: int) -> RegistroCuotaMes | None:
        fila = self._conexion.execute(_SQL_OBTENER_CUOTA, (cuota_id,)).fetchone()
        return self._a_registro(fila) if fila is not None else None

    def ultimo_medio_pago(self) -> MedioPago | None:
        fila = self._conexion.execute(
            "SELECT medio FROM pagos ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return fila["medio"] if fila is not None else None

    def guardar_pago(
        self, pago: Pago, imputaciones: list[ImputacionPago]
    ) -> int:
        with self._conexion:
            cursor = self._conexion.execute(
                "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio, nota)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    pago.contrato_id,
                    pago.fecha.isoformat(),
                    pago.monto_centavos,
                    pago.medio,
                    pago.nota,
                ),
            )
            pago_id = int(cursor.lastrowid)
            for imputacion in imputaciones:
                self._conexion.execute(
                    "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos, mora_centavos)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        pago_id,
                        imputacion.cuota_id,
                        imputacion.monto_centavos,
                        imputacion.mora_centavos,
                    ),
                )
        return pago_id

    def _a_registro(self, fila: sqlite3.Row) -> RegistroCuotaMes:
        return RegistroCuotaMes(
            cuota_id=fila["cuota_id"],
            contrato_id=fila["contrato_id"],
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
            dias_gracia=fila["dias_gracia"],
            tasa_mora_bp=fila["tasa_mora_bp"],
            mora_pagada_centavos=fila["mora_pagada_centavos"],
        )
