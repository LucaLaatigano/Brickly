"""Repositorio SQLite de departamentos — implementa `RepositorioDepartamentos`.

Incluye persistencia de contratos vigentes/históricos, lectura de cuotas por
unidad, estado del mes corriente (`estado_mes`), `proximo_vencimiento` y
`deuda_centavos` (suma de saldos + mora a hoy cuando la unidad tiene cuotas).
"""

import sqlite3
from datetime import date

from gestion.aplicacion.departamentos import (
    ContratoEnDetalle,
    DependenciasDepartamento,
    DetalleDepartamento,
    FilaCuotaDepartamento,
    FilaDepartamento,
    InquilinoEnDetalle,
    PagoImputadoCuota,
    PredeterminadosContrato,
)
from gestion.aplicacion.puertos import Reloj
from gestion.dominio.contrato import Contrato, Inquilino
from gestion.dominio.cuota import (
    calcular_mora_cuota,
    estado_cuota,
    saldo_capital_cuota,
)
from gestion.dominio.departamento import Departamento
from gestion.dominio.errores import ErrorDeNegocio
from gestion.infraestructura.reloj import RelojSistema

_SQL_LISTAR = """
SELECT d.id, d.direccion, d.piso, d.depto,
       i.nombre              AS inquilino,
       c.monto_centavos      AS cuota_vigente_centavos,
       (SELECT MAX(p.fecha)
          FROM pagos p
          JOIN contratos pc ON pc.id = p.contrato_id
         WHERE pc.departamento_id = d.id) AS ultimo_pago,
       (SELECT MAX(cv.fecha_fin)
          FROM contratos cv
         WHERE cv.departamento_id = d.id
           AND cv.fecha_fin IS NOT NULL) AS ultima_fecha_fin,
       cu.monto_centavos     AS cuota_mes_monto,
       cu.fecha_vencimiento  AS cuota_mes_vencimiento,
       COALESCE(
           (SELECT SUM(im.monto_centavos) FROM imputaciones im WHERE im.cuota_id = cu.id),
           0
       ) AS cuota_mes_pagado
  FROM departamentos d
  LEFT JOIN contratos  c  ON c.departamento_id = d.id AND c.fecha_fin IS NULL
  LEFT JOIN inquilinos i  ON i.id = c.inquilino_id
  LEFT JOIN cuotas     cu ON cu.contrato_id = c.id AND cu.anio = :anio AND cu.mes = :mes
 ORDER BY d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, '')
"""

_SQL_DETALLE = """
SELECT d.id, d.direccion, d.piso, d.depto, d.m2, d.propietario,
       c.id                AS contrato_id,
       c.inquilino_id      AS inquilino_id,
       c.fecha_inicio      AS fecha_inicio,
       c.fecha_fin         AS fecha_fin,
       c.monto_centavos    AS cuota_vigente_centavos,
       c.dia_vencimiento   AS dia_vencimiento,
       c.dias_gracia       AS dias_gracia,
       c.tasa_mora_bp      AS tasa_mora_bp,
       c.ciclo_meses       AS ciclo_meses,
       c.redondeo_centavos AS redondeo_centavos,
       i.nombre            AS inquilino_nombre,
       i.telefono          AS inquilino_telefono,
       i.email             AS inquilino_email,
       (SELECT MAX(aj.fecha_aplicacion)
          FROM ajustes aj
         WHERE aj.contrato_id = c.id) AS ultimo_ajuste,
       (SELECT MIN(cu.fecha_vencimiento)
          FROM cuotas cu
          JOIN contratos co ON co.id = cu.contrato_id
         WHERE co.departamento_id = d.id
           AND cu.monto_centavos > COALESCE(
               (SELECT SUM(im.monto_centavos) FROM imputaciones im WHERE im.cuota_id = cu.id),
               0
           )) AS proximo_vencimiento,
       (SELECT MAX(cv.fecha_fin)
          FROM contratos cv
         WHERE cv.departamento_id = d.id
           AND cv.fecha_fin IS NOT NULL) AS ultima_fecha_fin,
       cm.monto_centavos    AS cuota_mes_monto,
       cm.fecha_vencimiento AS cuota_mes_vencimiento,
       COALESCE(
           (SELECT SUM(im.monto_centavos) FROM imputaciones im WHERE im.cuota_id = cm.id),
           0
       ) AS cuota_mes_pagado
  FROM departamentos d
  LEFT JOIN contratos  c  ON c.departamento_id = d.id AND c.fecha_fin IS NULL
  LEFT JOIN inquilinos i  ON i.id = c.inquilino_id
  LEFT JOIN cuotas     cm ON cm.contrato_id = c.id AND cm.anio = :anio AND cm.mes = :mes
 WHERE d.id = :id
"""

_SQL_EXISTE_UNIDAD = """
SELECT 1
  FROM departamentos
 WHERE direccion        = ? COLLATE NOCASE
   AND COALESCE(piso, '')  = ? COLLATE NOCASE
   AND COALESCE(depto, '') = ? COLLATE NOCASE
"""

_SQL_CONTAR_DEPENDENCIAS = """
SELECT (SELECT COUNT(*) FROM contratos WHERE departamento_id = :id) AS contratos,
       (SELECT COUNT(*) FROM cuotas
         WHERE contrato_id IN (SELECT id FROM contratos WHERE departamento_id = :id)) AS cuotas,
       (SELECT COUNT(*) FROM pagos
         WHERE contrato_id IN (SELECT id FROM contratos WHERE departamento_id = :id)) AS pagos
"""

_SQL_CUOTAS_DEPARTAMENTO = """
SELECT cu.id, cu.anio, cu.mes, cu.fecha_vencimiento, cu.monto_centavos,
       co.dias_gracia, co.tasa_mora_bp,
       COALESCE(SUM(im.monto_centavos), 0) AS pagado_centavos,
       COALESCE(SUM(im.mora_centavos), 0)  AS mora_pagada_centavos
  FROM cuotas cu
  JOIN contratos co ON co.id = cu.contrato_id
  LEFT JOIN imputaciones im ON im.cuota_id = cu.id
 WHERE co.departamento_id = ?
 GROUP BY cu.id
 ORDER BY cu.anio DESC, cu.mes DESC, cu.id DESC
"""

_SQL_CUOTAS_TODAS_PARA_DEUDA = """
SELECT co.departamento_id AS departamento_id,
       cu.monto_centavos  AS monto_centavos,
       cu.fecha_vencimiento AS fecha_vencimiento,
       co.dias_gracia     AS dias_gracia,
       co.tasa_mora_bp    AS tasa_mora_bp,
       COALESCE(SUM(im.monto_centavos), 0) AS pagado_centavos
  FROM cuotas cu
  JOIN contratos co ON co.id = cu.contrato_id
  LEFT JOIN imputaciones im ON im.cuota_id = cu.id
 GROUP BY cu.id
"""

_SQL_PAGOS_CUOTA = """
SELECT p.id, p.fecha, im.monto_centavos, im.mora_centavos, p.medio, p.nota
  FROM imputaciones im
  JOIN pagos p ON p.id = im.pago_id
 WHERE im.cuota_id = ?
 ORDER BY p.fecha DESC, p.id DESC
"""


def _fecha(texto: str | None) -> date | None:
    return date.fromisoformat(texto) if texto else None


class RepositorioDepartamentosSQLite:
    def __init__(self, conexion: sqlite3.Connection, reloj: Reloj | None = None):
        self._conexion = conexion
        self._reloj = reloj or RelojSistema()

    def listar(self) -> list[FilaDepartamento]:
        hoy = self._reloj.hoy()
        filas = self._conexion.execute(
            _SQL_LISTAR, {"anio": hoy.year, "mes": hoy.month}
        ).fetchall()
        deudas = self._deudas_por_departamento(hoy)
        return [self._a_fila(fila, hoy, deudas.get(fila["id"])) for fila in filas]

    def obtener(self, departamento_id: int) -> Departamento | None:
        fila = self._conexion.execute(
            "SELECT id, direccion, piso, depto, m2, propietario"
            "  FROM departamentos WHERE id = ?",
            (departamento_id,),
        ).fetchone()
        return self._a_departamento(fila) if fila else None

    def detalle(self, departamento_id: int) -> DetalleDepartamento | None:
        hoy = self._reloj.hoy()
        fila = self._conexion.execute(
            _SQL_DETALLE, {"id": departamento_id, "anio": hoy.year, "mes": hoy.month}
        ).fetchone()
        if fila is None:
            return None

        inquilino = None
        contrato_detalle = None
        if fila["contrato_id"] is not None:
            inquilino = InquilinoEnDetalle(
                nombre=fila["inquilino_nombre"],
                telefono=fila["inquilino_telefono"],
                email=fila["inquilino_email"],
            )
            entidad_contrato = Contrato(
                id=fila["contrato_id"],
                departamento_id=fila["id"],
                inquilino_id=fila["inquilino_id"],
                fecha_inicio=_fecha(fila["fecha_inicio"]),
                fecha_fin=_fecha(fila["fecha_fin"]),
                monto_centavos=fila["cuota_vigente_centavos"],
                dia_vencimiento=fila["dia_vencimiento"],
                dias_gracia=fila["dias_gracia"],
                tasa_mora_bp=fila["tasa_mora_bp"],
                ciclo_meses=fila["ciclo_meses"],
                redondeo_centavos=fila["redondeo_centavos"],
            )
            contrato_detalle = ContratoEnDetalle(
                id=entidad_contrato.id,
                inquilino_id=entidad_contrato.inquilino_id,
                inquilino_nombre=fila["inquilino_nombre"],
                inquilino_telefono=fila["inquilino_telefono"],
                inquilino_email=fila["inquilino_email"],
                fecha_inicio=entidad_contrato.fecha_inicio,
                fecha_fin=entidad_contrato.fecha_fin,
                monto_centavos=entidad_contrato.monto_centavos,
                dia_vencimiento=entidad_contrato.dia_vencimiento,
                dias_gracia=entidad_contrato.dias_gracia,
                tasa_mora_bp=entidad_contrato.tasa_mora_bp,
                ciclo_meses=entidad_contrato.ciclo_meses,
                redondeo_centavos=entidad_contrato.redondeo_centavos,
                proxima_fecha_ajuste=entidad_contrato.proxima_fecha_ajuste(
                    hoy, ultimo_ajuste=_fecha(fila["ultimo_ajuste"])
                ),
            )

        estado_mes = None
        if fila["cuota_mes_monto"] is not None:
            estado_mes = estado_cuota(
                monto_centavos=fila["cuota_mes_monto"],
                pagado_centavos=fila["cuota_mes_pagado"],
                fecha_vencimiento=_fecha(fila["cuota_mes_vencimiento"]),
                hoy=hoy,
            )

        fecha_vencido = None
        if contrato_detalle is None and fila["ultima_fecha_fin"] is not None:
            ultima = _fecha(fila["ultima_fecha_fin"])
            if ultima is not None and ultima < hoy:
                fecha_vencido = ultima

        deudas = self._deudas_por_departamento(hoy)

        return DetalleDepartamento(
            id=fila["id"],
            direccion=fila["direccion"],
            piso=fila["piso"],
            depto=fila["depto"],
            m2=fila["m2"],
            propietario=fila["propietario"],
            inquilino=inquilino,
            cuota_vigente_centavos=fila["cuota_vigente_centavos"],
            deuda_centavos=deudas.get(fila["id"]),
            proximo_vencimiento=_fecha(fila["proximo_vencimiento"]),
            contrato=contrato_detalle,
            estado_mes=estado_mes,
            fecha_contrato_vencido=fecha_vencido,
        )

    def guardar(self, departamento: Departamento) -> int:
        try:
            cursor = self._conexion.execute(
                "INSERT INTO departamentos (direccion, piso, depto, m2, propietario)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    departamento.direccion,
                    departamento.piso,
                    departamento.depto,
                    departamento.m2,
                    departamento.propietario,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ErrorDeNegocio(f"Ya existe un departamento en «{departamento.unidad}».") from error
        self._conexion.commit()
        return int(cursor.lastrowid)

    def actualizar(self, departamento: Departamento) -> None:
        try:
            self._conexion.execute(
                "UPDATE departamentos SET direccion = ?, piso = ?, depto = ?,"
                "       m2 = ?, propietario = ?"
                " WHERE id = ?",
                (
                    departamento.direccion,
                    departamento.piso,
                    departamento.depto,
                    departamento.m2,
                    departamento.propietario,
                    departamento.id,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ErrorDeNegocio(f"Ya existe un departamento en «{departamento.unidad}».") from error
        self._conexion.commit()

    def eliminar(self, departamento_id: int) -> None:
        self._conexion.execute("DELETE FROM departamentos WHERE id = ?", (departamento_id,))
        self._conexion.commit()

    def existe_unidad(
        self,
        direccion: str,
        piso: str | None,
        depto: str | None,
        excluyendo: int | None = None,
    ) -> bool:
        sql = _SQL_EXISTE_UNIDAD
        parametros = [direccion, piso or "", depto or ""]
        if excluyendo is not None:
            sql += " AND id <> ?"
            parametros.append(excluyendo)
        return self._conexion.execute(sql + " LIMIT 1", parametros).fetchone() is not None

    def contar_dependencias(self, departamento_id: int) -> DependenciasDepartamento:
        fila = self._conexion.execute(
            _SQL_CONTAR_DEPENDENCIAS, {"id": departamento_id}
        ).fetchone()
        return DependenciasDepartamento(
            contratos=fila["contratos"], cuotas=fila["cuotas"], pagos=fila["pagos"]
        )

    # --- contratos y cuotas de la unidad (§3.3) ------------------------------

    def predeterminados_contrato(self) -> PredeterminadosContrato:
        filas = self._conexion.execute(
            "SELECT clave, valor FROM configuracion"
            " WHERE clave IN ('vencimiento_dia', 'gracia_dias', 'mora_bp', 'redondeo_centavos')"
        ).fetchall()
        mapa = {fila["clave"]: fila["valor"] for fila in filas}
        return PredeterminadosContrato(
            dia_vencimiento=int(mapa.get("vencimiento_dia", 10)),
            dias_gracia=int(mapa.get("gracia_dias", 5)),
            tasa_mora_bp=int(mapa.get("mora_bp", 200)),
            ciclo_meses=3,
            redondeo_centavos=int(mapa.get("redondeo_centavos", 1)),
        )

    def guardar_contrato(
        self, departamento_id: int, inquilino: Inquilino, contrato: Contrato
    ) -> int:
        try:
            with self._conexion:
                inquilino_id = int(
                    self._conexion.execute(
                        "INSERT INTO inquilinos (nombre, telefono, email) VALUES (?, ?, ?)",
                        (inquilino.nombre, inquilino.telefono, inquilino.email),
                    ).lastrowid
                )
                contrato_id = int(
                    self._conexion.execute(
                        "INSERT INTO contratos ("
                        "    departamento_id, inquilino_id, fecha_inicio, fecha_fin,"
                        "    monto_centavos, dia_vencimiento, dias_gracia,"
                        "    tasa_mora_bp, ciclo_meses, redondeo_centavos"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            departamento_id,
                            inquilino_id,
                            contrato.fecha_inicio.isoformat(),
                            contrato.fecha_fin.isoformat() if contrato.fecha_fin else None,
                            contrato.monto_centavos,
                            contrato.dia_vencimiento,
                            contrato.dias_gracia,
                            contrato.tasa_mora_bp,
                            contrato.ciclo_meses,
                            contrato.redondeo_centavos,
                        ),
                    ).lastrowid
                )
        except sqlite3.IntegrityError as error:
            raise ErrorDeNegocio(
                "Esta unidad ya tiene un contrato vigente. Usá «Nuevo contrato» para renovarlo."
            ) from error
        return contrato_id

    def actualizar_contrato(
        self, contrato_id: int, inquilino: Inquilino, contrato: Contrato
    ) -> None:
        with self._conexion:
            self._conexion.execute(
                "UPDATE inquilinos SET nombre = ?, telefono = ?, email = ? WHERE id = ?",
                (inquilino.nombre, inquilino.telefono, inquilino.email, inquilino.id),
            )
            self._conexion.execute(
                "UPDATE contratos"
                "   SET fecha_inicio = ?, fecha_fin = ?, monto_centavos = ?,"
                "       dia_vencimiento = ?, dias_gracia = ?, tasa_mora_bp = ?,"
                "       ciclo_meses = ?, redondeo_centavos = ?"
                " WHERE id = ?",
                (
                    contrato.fecha_inicio.isoformat(),
                    contrato.fecha_fin.isoformat() if contrato.fecha_fin else None,
                    contrato.monto_centavos,
                    contrato.dia_vencimiento,
                    contrato.dias_gracia,
                    contrato.tasa_mora_bp,
                    contrato.ciclo_meses,
                    contrato.redondeo_centavos,
                    contrato_id,
                ),
            )

    def reemplazar_contrato(
        self,
        departamento_id: int,
        fecha_cierre: date,
        inquilino: Inquilino,
        contrato: Contrato,
    ) -> int:
        with self._conexion:
            vigente = self._conexion.execute(
                "SELECT id, fecha_inicio FROM contratos"
                " WHERE departamento_id = ? AND fecha_fin IS NULL",
                (departamento_id,),
            ).fetchone()
            if vigente is not None:
                inicio_anterior = _fecha(vigente["fecha_inicio"])
                cierre_efectivo = max(fecha_cierre, inicio_anterior)
                self._conexion.execute(
                    "UPDATE contratos SET fecha_fin = ? WHERE id = ?",
                    (cierre_efectivo.isoformat(), vigente["id"]),
                )
            inquilino_id = int(
                self._conexion.execute(
                    "INSERT INTO inquilinos (nombre, telefono, email) VALUES (?, ?, ?)",
                    (inquilino.nombre, inquilino.telefono, inquilino.email),
                ).lastrowid
            )
            contrato_id = int(
                self._conexion.execute(
                    "INSERT INTO contratos ("
                    "    departamento_id, inquilino_id, fecha_inicio, fecha_fin,"
                    "    monto_centavos, dia_vencimiento, dias_gracia,"
                    "    tasa_mora_bp, ciclo_meses, redondeo_centavos"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        departamento_id,
                        inquilino_id,
                        contrato.fecha_inicio.isoformat(),
                        contrato.fecha_fin.isoformat() if contrato.fecha_fin else None,
                        contrato.monto_centavos,
                        contrato.dia_vencimiento,
                        contrato.dias_gracia,
                        contrato.tasa_mora_bp,
                        contrato.ciclo_meses,
                        contrato.redondeo_centavos,
                    ),
                ).lastrowid
            )
        return contrato_id

    def listar_cuotas_departamento(
        self, departamento_id: int
    ) -> list[FilaCuotaDepartamento]:
        hoy = self._reloj.hoy()
        filas = self._conexion.execute(
            _SQL_CUOTAS_DEPARTAMENTO, (departamento_id,)
        ).fetchall()
        resultado = []
        for fila in filas:
            vencimiento = _fecha(fila["fecha_vencimiento"])
            monto = fila["monto_centavos"]
            pagado = fila["pagado_centavos"]
            mora_pagada = fila["mora_pagada_centavos"]
            estado = estado_cuota(monto, pagado, vencimiento, hoy)
            saldo = saldo_capital_cuota(monto, pagado)
            if estado == "pagada":
                mora_visible = mora_pagada if mora_pagada > 0 else None
                saldo_visible = None
            else:
                mora_viva = calcular_mora_cuota(
                    monto_centavos=monto,
                    pagado_centavos=pagado,
                    fecha_vencimiento=vencimiento,
                    hoy=hoy,
                    dias_gracia=fila["dias_gracia"],
                    tasa_mora_bp=fila["tasa_mora_bp"],
                )
                mora_visible = mora_viva if mora_viva > 0 else None
                saldo_visible = saldo + mora_viva
            resultado.append(
                FilaCuotaDepartamento(
                    id=fila["id"],
                    anio=fila["anio"],
                    mes=fila["mes"],
                    fecha_vencimiento=vencimiento,
                    monto_centavos=monto,
                    pagado_centavos=pagado,
                    mora_centavos=mora_visible,
                    saldo_centavos=saldo_visible,
                    estado=estado,
                )
            )
        return resultado

    def listar_pagos_cuota(self, cuota_id: int) -> list[PagoImputadoCuota]:
        filas = self._conexion.execute(_SQL_PAGOS_CUOTA, (cuota_id,)).fetchall()
        return [
            PagoImputadoCuota(
                id=fila["id"],
                fecha=_fecha(fila["fecha"]),
                monto_centavos=fila["monto_centavos"],
                mora_centavos=fila["mora_centavos"],
                medio=fila["medio"],
                nota=fila["nota"],
            )
            for fila in filas
        ]

    # --- mapeos internos -----------------------------------------------------

    def _deudas_por_departamento(self, hoy: date) -> dict[int, int]:
        """Suma de (saldo de capital + mora a hoy) por departamento con cuotas."""
        deudas: dict[int, int] = {}
        filas = self._conexion.execute(_SQL_CUOTAS_TODAS_PARA_DEUDA).fetchall()
        for fila in filas:
            depto_id = fila["departamento_id"]
            deudas.setdefault(depto_id, 0)
            monto = fila["monto_centavos"]
            pagado = fila["pagado_centavos"]
            saldo = saldo_capital_cuota(monto, pagado)
            if saldo > 0:
                mora = calcular_mora_cuota(
                    monto_centavos=monto,
                    pagado_centavos=pagado,
                    fecha_vencimiento=_fecha(fila["fecha_vencimiento"]),
                    hoy=hoy,
                    dias_gracia=fila["dias_gracia"],
                    tasa_mora_bp=fila["tasa_mora_bp"],
                )
                deudas[depto_id] += saldo + mora
        return deudas

    def _a_departamento(self, fila: sqlite3.Row) -> Departamento:
        return Departamento(
            id=fila["id"],
            direccion=fila["direccion"],
            piso=fila["piso"],
            depto=fila["depto"],
            m2=fila["m2"],
            propietario=fila["propietario"],
        )

    def _a_fila(
        self, fila: sqlite3.Row, hoy: date, deuda_centavos: int | None
    ) -> FilaDepartamento:
        estado_mes = None
        if fila["cuota_mes_monto"] is not None:
            estado_mes = estado_cuota(
                monto_centavos=fila["cuota_mes_monto"],
                pagado_centavos=fila["cuota_mes_pagado"],
                fecha_vencimiento=_fecha(fila["cuota_mes_vencimiento"]),
                hoy=hoy,
            )
        fecha_vencido = None
        if fila["inquilino"] is None and fila["ultima_fecha_fin"] is not None:
            ultima = _fecha(fila["ultima_fecha_fin"])
            if ultima is not None and ultima < hoy:
                fecha_vencido = ultima
        return FilaDepartamento(
            id=fila["id"],
            direccion=fila["direccion"],
            piso=fila["piso"],
            depto=fila["depto"],
            inquilino=fila["inquilino"],
            cuota_vigente_centavos=fila["cuota_vigente_centavos"],
            estado_mes=estado_mes,
            deuda_centavos=deuda_centavos,
            ultimo_pago=_fecha(fila["ultimo_pago"]),
            fecha_contrato_vencido=fecha_vencido,
        )
