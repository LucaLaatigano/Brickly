"""Presentador de Cobranzas (spec §6.3).

Agrupa en una sola llamada por refresco lo que necesita `VistaCobranzas`.
"""

from dataclasses import dataclass
from datetime import date

from brickly.aplicacion.cobranzas import (
    CobranzasDelMes,
    DetalleCuotaParaPago,
    FilaAtraso,
    FiltroCobranzas,
)
from brickly.aplicacion.contenedor import Servicios
from brickly.ui.formato import formatear_periodo


@dataclass(frozen=True)
class FilaAtrasoPresentada:
    """Fila de la tabla de Atrasos en Cobranzas (§3.4)."""

    id: int
    cuota_id: int
    departamento_id: int
    unidad: str
    inquilino: str
    periodo: str
    fecha_vencimiento: date
    dias_atraso: int
    cuota_centavos: int
    mora_centavos: int | None
    total_centavos: int


class PresenterCobranzas:
    def __init__(self, servicios: Servicios):
        self._cobranzas = servicios.cobranzas

    def periodo_inicial(self) -> tuple[int, int]:
        return self._cobranzas.periodo_actual()

    def del_mes(
        self,
        anio: int,
        mes: int,
        busqueda: str = "",
        filtro: FiltroCobranzas = "todas",
    ) -> CobranzasDelMes:
        return self._cobranzas.del_mes(
            anio=anio, mes=mes, busqueda=busqueda, filtro=filtro
        )

    def atrasos(self) -> list[FilaAtrasoPresentada]:
        filas: list[FilaAtraso] = self._cobranzas.atrasos()
        return [
            FilaAtrasoPresentada(
                id=fila.cuota_id,
                cuota_id=fila.cuota_id,
                departamento_id=fila.departamento_id,
                unidad=fila.unidad,
                inquilino=fila.inquilino,
                periodo=formatear_periodo(fila.anio, fila.mes),
                fecha_vencimiento=fila.fecha_vencimiento,
                dias_atraso=fila.dias_atraso,
                cuota_centavos=fila.cuota_centavos,
                mora_centavos=fila.mora_centavos,
                total_centavos=fila.total_centavos,
            )
            for fila in filas
        ]

    def preparar_pago(self, cuota_id: int) -> DetalleCuotaParaPago:
        return self._cobranzas.preparar_pago(cuota_id)

    def preparar_pago_departamento(self, departamento_id: int) -> DetalleCuotaParaPago:
        return self._cobranzas.preparar_pago_departamento(departamento_id)
