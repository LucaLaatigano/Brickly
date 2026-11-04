"""Pago e imputación FIFO — reglas puras de cobro y congelamiento de mora (ADR-0002).

Invariante contable (0001_inicial.sql): la suma de `monto_centavos + mora_centavos`
de todas las imputaciones de un pago es exactamente igual al monto del pago.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion

MedioPago = Literal["efectivo", "transferencia", "deposito", "otro"]
MEDIOS_PAGO: tuple[MedioPago, ...] = ("efectivo", "transferencia", "deposito", "otro")


def _limpiar(texto: str | None) -> str | None:
    if texto is None:
        return None
    texto = texto.strip()
    return texto or None


@dataclass(frozen=True)
class CuotaImputable:
    """Estado de una cuota impaga al momento de imputar un pago."""

    cuota_id: int
    saldo_capital_centavos: int
    mora_centavos: int

    def __post_init__(self):
        if self.saldo_capital_centavos < 0 or self.mora_centavos < 0:
            raise ErrorDeValidacion("Los saldos de la cuota no pueden ser negativos.")

    @property
    def total_centavos(self) -> int:
        return self.saldo_capital_centavos + self.mora_centavos


@dataclass(frozen=True)
class ImputacionPago:
    """Aplicación de un pago (o fracción) sobre una cuota."""

    cuota_id: int
    monto_centavos: int
    mora_centavos: int = 0

    def __post_init__(self):
        if self.monto_centavos < 0 or self.mora_centavos < 0:
            raise ErrorDeValidacion("Los montos imputados no pueden ser negativos.")
        if self.monto_centavos + self.mora_centavos <= 0:
            raise ErrorDeValidacion("La imputación debe aplicar un monto mayor a 0.")

    @property
    def total_aplicado_centavos(self) -> int:
        return self.monto_centavos + self.mora_centavos


@dataclass(frozen=True)
class Pago:
    """Cobro recibido de un inquilino para un contrato."""

    contrato_id: int
    fecha: date
    monto_centavos: int
    medio: MedioPago
    nota: str | None = None
    id: int | None = None

    def __post_init__(self):
        if not isinstance(self.monto_centavos, int) or isinstance(self.monto_centavos, bool):
            raise ErrorDeValidacion(
                "El monto del pago debe expresarse en centavos enteros.", campo="monto"
            )
        if self.monto_centavos <= 0:
            raise ErrorDeValidacion(
                "El monto del pago debe ser mayor a 0.", campo="monto"
            )
        if self.medio not in MEDIOS_PAGO:
            raise ErrorDeValidacion("El medio de pago no es válido.", campo="medio")
        object.__setattr__(self, "nota", _limpiar(self.nota))


def imputar_pago_a_cuota(cuota: CuotaImputable, monto_centavos: int) -> ImputacionPago:
    """Imputa `monto_centavos` a una cuota (primero mora exigible, luego capital)."""
    if not isinstance(monto_centavos, int) or isinstance(monto_centavos, bool) or monto_centavos <= 0:
        raise ErrorDeValidacion("El monto del pago debe ser mayor a 0.", campo="monto")
    if cuota.total_centavos <= 0:
        raise ErrorDeNegocio("La cuota seleccionada ya está pagada.")
    if monto_centavos > cuota.total_centavos:
        raise ErrorDeNegocio("El monto supera el total exigible de la cuota.")

    mora_aplicada = min(monto_centavos, cuota.mora_centavos)
    capital_aplicado = monto_centavos - mora_aplicada
    return ImputacionPago(
        cuota_id=cuota.cuota_id,
        monto_centavos=capital_aplicado,
        mora_centavos=mora_aplicada,
    )


def imputar_pago_fifo(
    cuotas: list[CuotaImputable], monto_centavos: int
) -> list[ImputacionPago]:
    """Reparte `monto_centavos` en orden FIFO sobre las cuotas impagas provistas."""
    if not isinstance(monto_centavos, int) or isinstance(monto_centavos, bool) or monto_centavos <= 0:
        raise ErrorDeValidacion("El monto del pago debe ser mayor a 0.", campo="monto")
    pendientes = [cuota for cuota in cuotas if cuota.total_centavos > 0]
    if not pendientes:
        raise ErrorDeNegocio("No hay cuotas pendientes para imputar el pago.")

    total_disponible = sum(cuota.total_centavos for cuota in pendientes)
    if monto_centavos > total_disponible:
        raise ErrorDeNegocio("El monto supera la deuda total exigible.")

    restante = monto_centavos
    imputaciones: list[ImputacionPago] = []
    for cuota in pendientes:
        if restante == 0:
            break
        aplicar = min(restante, cuota.total_centavos)
        imputaciones.append(imputar_pago_a_cuota(cuota, aplicar))
        restante -= aplicar

    return imputaciones
