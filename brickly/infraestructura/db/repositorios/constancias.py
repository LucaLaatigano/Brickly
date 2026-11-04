"""Repositorio SQLite de Constancias de pago — implementa `RepositorioConstancias` (H8 — ADR-0004).

Una consulta SQL por operación (anti N+1), uniendo `cuotas`, `contratos`,
`departamentos`, `inquilinos`, `imputaciones` y `pagos`. El inquilino leído es
siempre el del contrato que generó la cuota, incluso si ese contrato ya cerró.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from brickly.aplicacion.constancias import (
    CuotaPagadaDisponible,
    RegistroConstanciaCuota,
    RegistroPagoConstancia,
)
from brickly.dominio.departamento import nombre_unidad

_SQL_PAGADAS_DEL_MES = """
SELECT cu.id                               AS cuota_id,
       d.id                                AS departamento_id,
       d.direccion                         AS direccion,
       d.piso                              AS piso,
       d.depto                             AS depto,
       i.nombre                            AS inquilino,
       cu.anio                             AS anio,
       cu.mes                              AS mes,
       COALESCE(SUM(im.monto_centavos), 0) AS capital_centavos,
       COALESCE(SUM(im.mora_centavos), 0)  AS mora_centavos
  FROM cuotas cu
  JOIN contratos     c  ON c.id = cu.contrato_id
  JOIN departamentos d  ON d.id = c.departamento_id
  JOIN inquilinos    i  ON i.id = c.inquilino_id
  LEFT JOIN imputaciones im ON im.cuota_id = cu.id
 WHERE cu.anio = ? AND cu.mes = ?
 GROUP BY cu.id
HAVING COALESCE(SUM(im.monto_centavos), 0) >= cu.monto_centavos
 ORDER BY d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, ''), cu.id
"""

_SQL_OBTENER_CONSTANCIA = """
SELECT cu.id                AS cuota_id,
       c.id                 AS contrato_id,
       d.id                 AS departamento_id,
       d.direccion          AS direccion,
       d.piso               AS piso,
       d.depto              AS depto,
       d.propietario        AS propietario,
       i.nombre             AS inquilino,
       cu.anio              AS anio,
       cu.mes               AS mes,
       cu.fecha_vencimiento AS fecha_vencimiento,
       cu.monto_centavos    AS monto_centavos,
       c.dias_gracia        AS dias_gracia,
       c.tasa_mora_bp       AS tasa_mora_bp,
       p.id                 AS pago_id,
       p.fecha              AS pago_fecha,
       p.medio              AS pago_medio,
       p.nota               AS pago_nota,
       im.monto_centavos    AS im_capital_centavos,
       im.mora_centavos     AS im_mora_centavos
  FROM cuotas cu
  JOIN contratos     c  ON c.id = cu.contrato_id
  JOIN departamentos d  ON d.id = c.departamento_id
  JOIN inquilinos    i  ON i.id = c.inquilino_id
  LEFT JOIN imputaciones im ON im.cuota_id = cu.id
  LEFT JOIN pagos        p  ON p.id = im.pago_id
 WHERE cu.id = ?
 ORDER BY p.fecha ASC, p.id ASC, im.id ASC
"""


class RepositorioConstanciasSQLite:
    """Lectura de cuotas y sus pagos imputados para emitir constancias de pago."""

    def __init__(self, conexion: sqlite3.Connection):
        self._conn = conexion

    def listar_pagadas_del_mes(
        self, anio: int, mes: int
    ) -> list[CuotaPagadaDisponible]:
        filas = self._conn.execute(
            _SQL_PAGADAS_DEL_MES, (int(anio), int(mes))
        ).fetchall()
        resultado: list[CuotaPagadaDisponible] = []
        for f in filas:
            capital = int(f["capital_centavos"])
            mora = int(f["mora_centavos"])
            resultado.append(
                CuotaPagadaDisponible(
                    cuota_id=int(f["cuota_id"]),
                    departamento_id=int(f["departamento_id"]),
                    unidad=nombre_unidad(
                        str(f["direccion"]), f["piso"], f["depto"]
                    ),
                    inquilino=str(f["inquilino"]),
                    anio=int(f["anio"]),
                    mes=int(f["mes"]),
                    capital_centavos=capital,
                    mora_centavos=mora,
                    total_centavos=capital + mora,
                )
            )
        return resultado

    def obtener_constancia(self, cuota_id: int) -> RegistroConstanciaCuota | None:
        filas = self._conn.execute(
            _SQL_OBTENER_CONSTANCIA, (int(cuota_id),)
        ).fetchall()
        if not filas:
            return None

        primera = filas[0]
        pagos: list[RegistroPagoConstancia] = []
        pagado_centavos = 0
        mora_pagada_centavos = 0

        for f in filas:
            if f["pago_id"] is None:
                continue
            cap = int(f["im_capital_centavos"])
            mora = int(f["im_mora_centavos"])
            pagado_centavos += cap
            mora_pagada_centavos += mora
            pagos.append(
                RegistroPagoConstancia(
                    pago_id=int(f["pago_id"]),
                    fecha=date.fromisoformat(str(f["pago_fecha"])),
                    medio=str(f["pago_medio"]),
                    capital_centavos=cap,
                    mora_centavos=mora,
                    nota=str(f["pago_nota"]) if f["pago_nota"] is not None else None,
                )
            )

        return RegistroConstanciaCuota(
            cuota_id=int(primera["cuota_id"]),
            contrato_id=int(primera["contrato_id"]),
            departamento_id=int(primera["departamento_id"]),
            direccion=str(primera["direccion"]),
            piso=primera["piso"],
            depto=primera["depto"],
            propietario=primera["propietario"],
            inquilino=str(primera["inquilino"]),
            anio=int(primera["anio"]),
            mes=int(primera["mes"]),
            fecha_vencimiento=date.fromisoformat(str(primera["fecha_vencimiento"])),
            monto_centavos=int(primera["monto_centavos"]),
            pagado_centavos=pagado_centavos,
            mora_pagada_centavos=mora_pagada_centavos,
            dias_gracia=int(primera["dias_gracia"]),
            tasa_mora_bp=int(primera["tasa_mora_bp"]),
            pagos=tuple(pagos),
        )
