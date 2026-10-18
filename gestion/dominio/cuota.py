"""Cuota mensual — generación, vencimiento fijo, estado y mora diaria (ADR-0002).

La cuota no persiste estado, saldo ni mora viva: se derivan de lo imputado y de
la fecha actual provista por el `Reloj`.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from gestion.dominio.errores import ErrorDeValidacion

EstadoCuota = Literal["pagada", "parcial", "pendiente", "vencida"]


def fecha_vencimiento_cuota(anio: int, mes: int, dia_vencimiento: int) -> date:
    """Vencimiento fijo mes a mes sin corrimiento por fin de semana (ADR-0002 #3)."""
    if not (2000 <= anio <= 2100):
        raise ErrorDeValidacion("El año del período debe estar entre 2000 y 2100.", campo="anio")
    if not (1 <= mes <= 12):
        raise ErrorDeValidacion("El mes del período debe estar entre 1 y 12.", campo="mes")
    if not (1 <= dia_vencimiento <= 28):
        raise ErrorDeValidacion(
            "El día de vencimiento debe estar entre 1 y 28.", campo="dia_vencimiento"
        )
    return date(anio, mes, dia_vencimiento)


def saldo_capital_cuota(monto_centavos: int, pagado_centavos: int) -> int:
    """Capital pendiente de cobro (nunca negativo)."""
    return max(0, monto_centavos - pagado_centavos)


def estado_cuota(
    monto_centavos: int,
    pagado_centavos: int,
    fecha_vencimiento: date,
    hoy: date,
) -> EstadoCuota:
    """Estado derivado a hoy: pagada, vencida, parcial o pendiente."""
    if saldo_capital_cuota(monto_centavos, pagado_centavos) == 0:
        return "pagada"
    if hoy > fecha_vencimiento:
        return "vencida"
    if pagado_centavos > 0:
        return "parcial"
    return "pendiente"


def dias_atraso_cuota(
    monto_centavos: int,
    pagado_centavos: int,
    fecha_vencimiento: date,
    hoy: date,
) -> int:
    """Días corridos desde el vencimiento si la cuota sigue impaga."""
    if saldo_capital_cuota(monto_centavos, pagado_centavos) == 0:
        return 0
    if hoy <= fecha_vencimiento:
        return 0
    return (hoy - fecha_vencimiento).days


def calcular_mora_cuota(
    monto_centavos: int,
    pagado_centavos: int,
    fecha_vencimiento: date,
    hoy: date,
    dias_gracia: int,
    tasa_mora_bp: int,
) -> int:
    """Interés simple diario sobre el saldo impago tras los días de gracia (ADR-0002 #4).

    `tasa_mora_bp` es mensual en puntos básicos (10.000 bp = 100 % en 30 días,
    por lo que la tasa diaria es `tasa_mora_bp / 300_000`). Todo el cálculo es
    entero con redondeo half-up al centavo más cercano (ADR-0001: cero floats).
    """
    saldo = saldo_capital_cuota(monto_centavos, pagado_centavos)
    if saldo == 0 or tasa_mora_bp <= 0:
        return 0
    atraso = dias_atraso_cuota(monto_centavos, pagado_centavos, fecha_vencimiento, hoy)
    if atraso <= dias_gracia:
        return 0
    numerador = saldo * tasa_mora_bp * atraso
    return (numerador + 150_000) // 300_000


@dataclass(frozen=True)
class Cuota:
    """Obligación mensual de un contrato para un período `(anio, mes)`."""

    contrato_id: int
    anio: int
    mes: int
    fecha_vencimiento: date
    monto_centavos: int
    id: int | None = None

    def __post_init__(self):
        if not (2000 <= self.anio <= 2100):
            raise ErrorDeValidacion(
                "El año del período debe estar entre 2000 y 2100.", campo="anio"
            )
        if not (1 <= self.mes <= 12):
            raise ErrorDeValidacion("El mes del período debe estar entre 1 y 12.", campo="mes")
        if not isinstance(self.monto_centavos, int) or isinstance(self.monto_centavos, bool):
            raise ErrorDeValidacion("El monto debe expresarse en centavos enteros.", campo="monto")
        if self.monto_centavos <= 0:
            raise ErrorDeValidacion("El monto de la cuota debe ser mayor a 0.", campo="monto")
