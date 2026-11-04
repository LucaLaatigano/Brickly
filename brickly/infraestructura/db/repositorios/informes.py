"""Repositorio SQLite de Informes — implementa `RepositorioInformes` (§3.6 — H4 y H7).

Una consulta por informe/hoja (anti N+1): el estado de cuenta y cada hoja del
Excel salen de una sola pasada SQL; la UI nunca ve SQL.
"""

import sqlite3
from datetime import date

from brickly.aplicacion.informes import (
    RegistroAjusteInforme,
    RegistroContratoInforme,
    RegistroDepartamentoInforme,
    RegistroEstadoCuenta,
    RegistroPagoInforme,
)

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

_SQL_DEPARTAMENTOS_RESUMEN = """
SELECT d.id             AS departamento_id,
       d.direccion      AS direccion,
       d.piso           AS piso,
       d.depto          AS depto,
       i.nombre         AS inquilino,
       c.fecha_inicio   AS fecha_inicio_vigente,
       c.monto_centavos AS cuota_vigente_centavos,
       (SELECT MAX(cv.fecha_fin)
          FROM contratos cv
         WHERE cv.departamento_id = d.id
           AND cv.fecha_fin IS NOT NULL) AS ultima_fecha_fin,
       (SELECT MAX(p.fecha)
          FROM pagos p
          JOIN contratos pc ON pc.id = p.contrato_id
         WHERE pc.departamento_id = d.id) AS ultimo_pago
  FROM departamentos d
  LEFT JOIN contratos  c ON c.departamento_id = d.id AND c.fecha_fin IS NULL
  LEFT JOIN inquilinos i ON i.id = c.inquilino_id
 ORDER BY d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, '')
"""

_SQL_PAGOS_INFORME = """
SELECT p.id                           AS pago_id,
       p.fecha                        AS fecha,
       d.direccion                    AS direccion,
       d.piso                         AS piso,
       d.depto                        AS depto,
       i.nombre                       AS inquilino,
       p.medio                        AS medio,
       p.nota                         AS nota,
       p.monto_centavos               AS monto_pago_centavos,
       cu.anio                        AS anio_cuota,
       cu.mes                         AS mes_cuota,
       COALESCE(im.monto_centavos, 0) AS capital_imputado_centavos,
       COALESCE(im.mora_centavos, 0)  AS mora_imputada_centavos
  FROM pagos p
  JOIN contratos     c  ON c.id = p.contrato_id
  JOIN departamentos d  ON d.id = c.departamento_id
  JOIN inquilinos    i  ON i.id = c.inquilino_id
  LEFT JOIN imputaciones im ON im.pago_id = p.id
  LEFT JOIN cuotas       cu ON cu.id = im.cuota_id
 ORDER BY p.fecha DESC, p.id DESC, cu.anio ASC, cu.mes ASC, im.id ASC
"""

_SQL_CONTRATOS_INFORME = """
SELECT c.id                AS contrato_id,
       d.direccion         AS direccion,
       d.piso              AS piso,
       d.depto             AS depto,
       i.nombre            AS inquilino,
       c.fecha_inicio      AS fecha_inicio,
       c.fecha_fin         AS fecha_fin,
       c.monto_centavos    AS monto_centavos,
       c.dia_vencimiento   AS dia_vencimiento,
       c.dias_gracia       AS dias_gracia,
       c.tasa_mora_bp      AS tasa_mora_bp,
       c.ciclo_meses       AS ciclo_meses,
       c.redondeo_centavos AS redondeo_centavos
  FROM contratos c
  JOIN departamentos d ON d.id = c.departamento_id
  JOIN inquilinos    i ON i.id = c.inquilino_id
 ORDER BY (c.fecha_fin IS NOT NULL) ASC,
          d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, ''),
          c.fecha_inicio DESC, c.id DESC
"""

_SQL_AJUSTES_INFORME = """
SELECT a.id                     AS ajuste_id,
       a.fecha_aplicacion       AS fecha_aplicacion,
       d.direccion              AS direccion,
       d.piso                   AS piso,
       d.depto                  AS depto,
       i.nombre                 AS inquilino,
       a.anio_base              AS anio_base,
       a.mes_base               AS mes_base,
       a.meses_ciclo            AS meses_ciclo,
       a.variacion_bp           AS variacion_bp,
       a.cuota_antes_centavos   AS cuota_antes_centavos,
       a.cuota_despues_centavos AS cuota_despues_centavos,
       a.es_override            AS es_override,
       a.motivo_override        AS motivo_override
  FROM ajustes a
  JOIN contratos     c ON c.id = a.contrato_id
  JOIN departamentos d ON d.id = c.departamento_id
  JOIN inquilinos    i ON i.id = c.inquilino_id
 ORDER BY a.fecha_aplicacion DESC, a.id DESC
"""


def _fecha_opcional(valor: str | None) -> date | None:
    return date.fromisoformat(valor) if valor else None


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

    def listar_departamentos_resumen(self) -> list[RegistroDepartamentoInforme]:
        filas = self._conexion.execute(_SQL_DEPARTAMENTOS_RESUMEN).fetchall()
        return [
            RegistroDepartamentoInforme(
                departamento_id=fila["departamento_id"],
                direccion=fila["direccion"],
                piso=fila["piso"],
                depto=fila["depto"],
                inquilino=fila["inquilino"],
                fecha_inicio_vigente=_fecha_opcional(fila["fecha_inicio_vigente"]),
                cuota_vigente_centavos=fila["cuota_vigente_centavos"],
                ultima_fecha_fin=_fecha_opcional(fila["ultima_fecha_fin"]),
                ultimo_pago=_fecha_opcional(fila["ultimo_pago"]),
            )
            for fila in filas
        ]

    def listar_pagos_informe(self) -> list[RegistroPagoInforme]:
        filas = self._conexion.execute(_SQL_PAGOS_INFORME).fetchall()
        return [
            RegistroPagoInforme(
                pago_id=fila["pago_id"],
                fecha=date.fromisoformat(fila["fecha"]),
                direccion=fila["direccion"],
                piso=fila["piso"],
                depto=fila["depto"],
                inquilino=fila["inquilino"],
                medio=fila["medio"],
                nota=fila["nota"],
                monto_pago_centavos=fila["monto_pago_centavos"],
                anio_cuota=fila["anio_cuota"],
                mes_cuota=fila["mes_cuota"],
                capital_imputado_centavos=fila["capital_imputado_centavos"],
                mora_imputada_centavos=fila["mora_imputada_centavos"],
            )
            for fila in filas
        ]

    def listar_contratos_informe(self) -> list[RegistroContratoInforme]:
        filas = self._conexion.execute(_SQL_CONTRATOS_INFORME).fetchall()
        return [
            RegistroContratoInforme(
                contrato_id=fila["contrato_id"],
                direccion=fila["direccion"],
                piso=fila["piso"],
                depto=fila["depto"],
                inquilino=fila["inquilino"],
                fecha_inicio=date.fromisoformat(fila["fecha_inicio"]),
                fecha_fin=_fecha_opcional(fila["fecha_fin"]),
                monto_centavos=fila["monto_centavos"],
                dia_vencimiento=fila["dia_vencimiento"],
                dias_gracia=fila["dias_gracia"],
                tasa_mora_bp=fila["tasa_mora_bp"],
                ciclo_meses=fila["ciclo_meses"],
                redondeo_centavos=fila["redondeo_centavos"],
            )
            for fila in filas
        ]

    def listar_ajustes_informe(self) -> list[RegistroAjusteInforme]:
        filas = self._conexion.execute(_SQL_AJUSTES_INFORME).fetchall()
        return [
            RegistroAjusteInforme(
                ajuste_id=fila["ajuste_id"],
                fecha_aplicacion=date.fromisoformat(fila["fecha_aplicacion"]),
                direccion=fila["direccion"],
                piso=fila["piso"],
                depto=fila["depto"],
                inquilino=fila["inquilino"],
                anio_base=fila["anio_base"],
                mes_base=fila["mes_base"],
                meses_ciclo=fila["meses_ciclo"],
                variacion_bp=fila["variacion_bp"],
                cuota_antes_centavos=fila["cuota_antes_centavos"],
                cuota_despues_centavos=fila["cuota_despues_centavos"],
                es_override=bool(fila["es_override"]),
                motivo_override=fila["motivo_override"],
            )
            for fila in filas
        ]

