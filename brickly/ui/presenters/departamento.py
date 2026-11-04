"""Presentador de departamentos (spec §6.3).

La vista lee por acá y comanda por `servicios`: el presentador agrupa las
lecturas por pantalla (lista, detalle, cuotas de la unidad y pagos por cuota).
"""

from dataclasses import dataclass
from datetime import date

from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.departamentos import (
    DetalleDepartamento,
    EstadoMes,
    FilaCuotaDepartamento,
    FilaDepartamento,
    FiltroDepartamentos,
    PagoImputadoCuota,
)
from brickly.ui.formato import formatear_periodo


@dataclass(frozen=True)
class FilaCuotaPresentada:
    """Fila de la tabla de cuotas en Detalle de departamento (§3.3)."""

    id: int
    periodo: str
    fecha_vencimiento: date
    monto_centavos: int
    pagado_centavos: int | None
    mora_centavos: int | None
    saldo_centavos: int | None
    estado: EstadoMes


class PresenterDepartamentos:
    def __init__(self, servicios: Servicios):
        self._departamentos = servicios.departamentos

    def filas(self, busqueda: str, filtro: FiltroDepartamentos) -> list[FilaDepartamento]:
        return self._departamentos.listar(busqueda=busqueda, filtro=filtro)

    def detalle(self, departamento_id: int) -> DetalleDepartamento:
        return self._departamentos.detalle(departamento_id)

    def cuotas(self, departamento_id: int) -> list[FilaCuotaPresentada]:
        filas: list[FilaCuotaDepartamento] = self._departamentos.listar_cuotas(
            departamento_id
        )
        return [
            FilaCuotaPresentada(
                id=fila.id,
                periodo=formatear_periodo(fila.anio, fila.mes),
                fecha_vencimiento=fila.fecha_vencimiento,
                monto_centavos=fila.monto_centavos,
                pagado_centavos=fila.pagado_centavos if fila.pagado_centavos > 0 else None,
                mora_centavos=fila.mora_centavos,
                saldo_centavos=fila.saldo_centavos,
                estado=fila.estado,
            )
            for fila in filas
        ]

    def pagos_de_cuota(self, cuota_id: int) -> list[PagoImputadoCuota]:
        return self._departamentos.pagos_de_cuota(cuota_id)
