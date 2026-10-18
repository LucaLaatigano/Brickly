"""Repositorio SQLite de Ajustes IPC — implementa `RepositorioAjustes`.

Todo el SQL de `ipc_valores` y `ajustes` vive acá (ADR-0001). `guardar_ajustes`
inserta el historial y actualiza la cuota vigente en UNA transacción.
"""

import sqlite3
from datetime import date

from gestion.aplicacion.ajustes import (
    ContratoParaAjuste,
    FilaHistorialAjuste,
    RegistroIpc,
)
from gestion.dominio.errores import ErrorDeNegocio
from gestion.dominio.ipc import AjusteCalculado, IpcMensual

_SQL_CONTRATOS_VIGENTES = """
SELECT c.id                AS contrato_id,
       d.id                AS departamento_id,
       d.direccion         AS direccion,
       d.piso              AS piso,
       d.depto             AS depto,
       i.nombre            AS inquilino,
       c.fecha_inicio      AS fecha_inicio,
       c.monto_centavos    AS monto_centavos,
       c.ciclo_meses       AS ciclo_meses,
       c.redondeo_centavos AS redondeo_centavos,
       (SELECT MAX(aj.fecha_aplicacion)
          FROM ajustes aj
         WHERE aj.contrato_id = c.id) AS ultimo_ajuste
  FROM contratos c
  JOIN departamentos d ON d.id = c.departamento_id
  JOIN inquilinos    i ON i.id = c.inquilino_id
 WHERE c.fecha_fin IS NULL
 ORDER BY d.direccion COLLATE NOCASE, COALESCE(d.piso, ''), COALESCE(d.depto, '')
"""

_SQL_HISTORIAL = """
SELECT aj.id                     AS id,
       aj.contrato_id            AS contrato_id,
       d.direccion               AS direccion,
       d.piso                    AS piso,
       d.depto                   AS depto,
       i.nombre                  AS inquilino,
       aj.fecha_aplicacion       AS fecha_aplicacion,
       aj.anio_base              AS anio_base,
       aj.mes_base               AS mes_base,
       aj.meses_ciclo            AS meses_ciclo,
       aj.variacion_bp           AS variacion_bp,
       aj.cuota_antes_centavos   AS cuota_antes_centavos,
       aj.cuota_despues_centavos AS cuota_despues_centavos,
       aj.es_override            AS es_override,
       aj.motivo_override        AS motivo_override
  FROM ajustes aj
  JOIN contratos     c ON c.id = aj.contrato_id
  JOIN departamentos d ON d.id = c.departamento_id
  JOIN inquilinos    i ON i.id = c.inquilino_id
 ORDER BY aj.fecha_aplicacion DESC, aj.id DESC
"""

_SQL_IPC = """
SELECT id, anio, mes, variacion_bp, origen, cargado_en
  FROM ipc_valores
"""


def _fecha(texto: str | None) -> date | None:
    return date.fromisoformat(texto[:10]) if texto else None


class RepositorioAjustesSQLite:
    def __init__(self, conexion: sqlite3.Connection):
        self._conexion = conexion

    # --- IPC ----------------------------------------------------------------

    def listar_ipc(self) -> list[RegistroIpc]:
        filas = self._conexion.execute(_SQL_IPC + " ORDER BY anio DESC, mes DESC").fetchall()
        return [self._a_ipc(fila) for fila in filas]

    def obtener_ipc(self, ipc_id: int) -> RegistroIpc | None:
        fila = self._conexion.execute(_SQL_IPC + " WHERE id = ?", (ipc_id,)).fetchone()
        return self._a_ipc(fila) if fila is not None else None

    def existe_ipc(self, anio: int, mes: int) -> bool:
        fila = self._conexion.execute(
            "SELECT 1 FROM ipc_valores WHERE anio = ? AND mes = ?", (anio, mes)
        ).fetchone()
        return fila is not None

    def guardar_ipc(self, ipc: IpcMensual) -> int:
        with self._conexion:
            cursor = self._conexion.execute(
                "INSERT INTO ipc_valores (anio, mes, variacion_bp, origen) VALUES (?, ?, ?, 'manual')",
                (ipc.anio, ipc.mes, ipc.variacion_bp),
            )
        return int(cursor.lastrowid)

    def actualizar_ipc(self, ipc_id: int, variacion_bp: int) -> None:
        with self._conexion:
            self._conexion.execute(
                "UPDATE ipc_valores SET variacion_bp = ? WHERE id = ?", (variacion_bp, ipc_id)
            )

    def eliminar_ipc(self, ipc_id: int) -> None:
        with self._conexion:
            self._conexion.execute("DELETE FROM ipc_valores WHERE id = ?", (ipc_id,))

    # --- ajustes ------------------------------------------------------------

    def listar_contratos_para_ajuste(self) -> list[ContratoParaAjuste]:
        filas = self._conexion.execute(_SQL_CONTRATOS_VIGENTES).fetchall()
        return [
            ContratoParaAjuste(
                contrato_id=fila["contrato_id"],
                departamento_id=fila["departamento_id"],
                direccion=fila["direccion"],
                piso=fila["piso"],
                depto=fila["depto"],
                inquilino=fila["inquilino"],
                fecha_inicio=date.fromisoformat(fila["fecha_inicio"]),
                monto_centavos=fila["monto_centavos"],
                ciclo_meses=fila["ciclo_meses"],
                redondeo_centavos=fila["redondeo_centavos"],
                ultimo_ajuste=_fecha(fila["ultimo_ajuste"]),
            )
            for fila in filas
        ]

    def guardar_ajustes(self, ajustes: list[AjusteCalculado]) -> None:
        """Historial + cuota vigente, todo o nada.

        El UPDATE exige que la cuota siga siendo la que el usuario revisó: si
        otro cambio la tocó en el medio, se aborta todo en lugar de pisarla.
        """
        try:
            with self._conexion:
                for ajuste in ajustes:
                    self._conexion.execute(
                        "INSERT INTO ajustes (contrato_id, fecha_aplicacion, anio_base, mes_base,"
                        " meses_ciclo, variacion_bp, cuota_antes_centavos, cuota_despues_centavos,"
                        " es_override, motivo_override)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            ajuste.contrato_id,
                            ajuste.fecha_ajuste.isoformat(),
                            ajuste.anio_base,
                            ajuste.mes_base,
                            ajuste.meses_ciclo,
                            ajuste.variacion_bp,
                            ajuste.cuota_antes_centavos,
                            ajuste.cuota_despues_centavos,
                            1 if ajuste.es_override else 0,
                            ajuste.motivo_override,
                        ),
                    )
                    cursor = self._conexion.execute(
                        "UPDATE contratos SET monto_centavos = ?"
                        " WHERE id = ? AND monto_centavos = ? AND fecha_fin IS NULL",
                        (
                            ajuste.cuota_despues_centavos,
                            ajuste.contrato_id,
                            ajuste.cuota_antes_centavos,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ErrorDeNegocio(
                            "La cuota de un contrato cambió mientras revisabas el ajuste."
                        )
        except sqlite3.IntegrityError as error:
            raise ErrorDeNegocio(
                "Uno de los contratos ya tenía aplicado el ajuste de este ciclo."
            ) from error

    def listar_historial(self) -> list[FilaHistorialAjuste]:
        filas = self._conexion.execute(_SQL_HISTORIAL).fetchall()
        return [
            FilaHistorialAjuste(
                id=fila["id"],
                contrato_id=fila["contrato_id"],
                direccion=fila["direccion"],
                piso=fila["piso"],
                depto=fila["depto"],
                inquilino=fila["inquilino"],
                fecha_aplicacion=date.fromisoformat(fila["fecha_aplicacion"]),
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

    @staticmethod
    def _a_ipc(fila: sqlite3.Row) -> RegistroIpc:
        return RegistroIpc(
            id=fila["id"],
            anio=fila["anio"],
            mes=fila["mes"],
            variacion_bp=fila["variacion_bp"],
            origen=fila["origen"],
            cargado_en=date.fromisoformat(fila["cargado_en"][:10]),
        )
