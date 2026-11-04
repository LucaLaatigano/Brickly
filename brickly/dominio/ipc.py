"""IPC y ajuste N-mensual de cuotas — reglas puras (ADR-0002 §1 y §2).

Convenciones:
- Variaciones en puntos básicos (bp): 100 bp = 1 %. Negativas = deflación.
- El acumulado de la ventana base es compuesto: Π(1 + vᵢ) − 1, calculado con
  enteros y redondeado half-up a 1 bp. Ese bp redondeado es el que se muestra,
  se guarda en el historial y se usa para la cuota nueva: así el ajuste es
  reproducible desde su propio snapshot.
- La cuota nueva se redondea half-up al múltiplo de `redondeo_centavos`
  (1 = centavos, 100 = $ 100). Nunca floats.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from brickly.dominio.errores import ErrorDeValidacion

BP_UNIDAD = 10_000  # 100 % en puntos básicos
MILESIMOS_UNIDAD = 1_000  # 1 punto de índice = 1.000 milésimos


def validar_variacion_bp(variacion_bp: int) -> None:
    """Rango admitido: (-100 %, 100 %]. -100 % dejaría la cuota en cero."""
    if not isinstance(variacion_bp, int) or isinstance(variacion_bp, bool):
        raise ErrorDeValidacion(
            "La variación debe expresarse en puntos básicos enteros.", campo="variacion"
        )
    if not (-BP_UNIDAD < variacion_bp <= BP_UNIDAD):
        raise ErrorDeValidacion(
            "La variación debe estar entre -100 % y 100 %.", campo="variacion"
        )


def _a_decimal_indice(valor: Decimal | int | str) -> Decimal:
    """Convierte un índice de IPC a Decimal exacto rechazando floats y booleanos."""
    if isinstance(valor, (float, bool)) or not isinstance(valor, (Decimal, int, str)):
        raise ErrorDeValidacion(
            "El índice de IPC debe ser Decimal, entero o texto numérico (no float).",
            campo="indice",
        )
    try:
        decimal = valor if isinstance(valor, Decimal) else Decimal(str(valor).strip())
    except (InvalidOperation, ValueError) as error:
        raise ErrorDeValidacion(
            "El índice de IPC no tiene un formato numérico válido.", campo="indice"
        ) from error
    if not decimal.is_finite() or decimal <= 0:
        raise ErrorDeValidacion(
            "El índice de IPC debe ser mayor a 0.", campo="indice"
        )
    return decimal


def indice_a_milesimos(indice: Decimal | int | str) -> int:
    """Convierte el índice del INDEC a milésimos enteros (half-up) para persistencia."""
    decimal = _a_decimal_indice(indice)
    milesimos = int(
        (decimal * Decimal(MILESIMOS_UNIDAD)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    if milesimos <= 0:
        raise ErrorDeValidacion(
            "El índice de IPC debe ser mayor a 0.", campo="indice"
        )
    return milesimos


def variacion_bp_desde_indices(
    indice_anterior: Decimal | int | str,
    indice_actual: Decimal | int | str,
) -> int:
    """Variación mensual ((I_t / I_{t-1}) − 1) en bp, redondeada half-up a 1 bp (ADR-0003)."""
    anterior = _a_decimal_indice(indice_anterior)
    actual = _a_decimal_indice(indice_actual)
    variacion_exacta_bp = ((actual - anterior) * Decimal(BP_UNIDAD)) / anterior
    variacion_bp = int(
        variacion_exacta_bp.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    validar_variacion_bp(variacion_bp)
    return variacion_bp


@dataclass(frozen=True)
class IpcMensual:
    """Variación mensual del IPC cargada para un período."""

    anio: int
    mes: int
    variacion_bp: int
    id: int | None = None
    indice_milesimos: int | None = None

    def __post_init__(self):
        if not (2000 <= self.anio <= 2100):
            raise ErrorDeValidacion("El año debe estar entre 2000 y 2100.", campo="anio")
        if not (1 <= self.mes <= 12):
            raise ErrorDeValidacion("El mes debe estar entre 1 y 12.", campo="mes")
        validar_variacion_bp(self.variacion_bp)
        if self.indice_milesimos is not None:
            if (
                not isinstance(self.indice_milesimos, int)
                or isinstance(self.indice_milesimos, bool)
                or self.indice_milesimos <= 0
            ):
                raise ErrorDeValidacion(
                    "El índice debe expresarse en milésimos enteros mayores a 0.",
                    campo="indice",
                )



def meses_base(fecha_ajuste: date, ciclo_meses: int) -> list[tuple[int, int]]:
    """Los `ciclo_meses` meses inmediatamente anteriores al mes del ajuste.

    Ajuste en octubre 2026 con ciclo 3 → [(2026, 7), (2026, 8), (2026, 9)].
    """
    if ciclo_meses <= 0:
        raise ErrorDeValidacion("El ciclo de ajuste debe ser mayor a 0.", campo="ciclo_meses")
    indice_ajuste = fecha_ajuste.year * 12 + (fecha_ajuste.month - 1)
    resultado = []
    for desplazamiento in range(ciclo_meses, 0, -1):
        anio, mes_0 = divmod(indice_ajuste - desplazamiento, 12)
        resultado.append((anio, mes_0 + 1))
    return resultado


def acumular_variaciones_bp(variaciones_bp: list[int]) -> int:
    """Π(1 + vᵢ) − 1 en bp, half-up a 1 bp, solo con enteros."""
    if not variaciones_bp:
        raise ErrorDeValidacion("No hay variaciones para acumular.", campo="variacion")
    numerador = 1
    for variacion in variaciones_bp:
        validar_variacion_bp(variacion)
        numerador *= BP_UNIDAD + variacion
    denominador = BP_UNIDAD ** len(variaciones_bp)
    # numerador > 0 siempre (cada factor > 0), así que half-up es + denominador // 2.
    factor_bp = (numerador * BP_UNIDAD + denominador // 2) // denominador
    return factor_bp - BP_UNIDAD


def aplicar_variacion(monto_centavos: int, variacion_bp: int, redondeo_centavos: int) -> int:
    """Cuota ajustada: monto × (1 + v), half-up al múltiplo de `redondeo_centavos`."""
    validar_variacion_bp(variacion_bp)
    if monto_centavos <= 0:
        raise ErrorDeValidacion("El monto de la cuota debe ser mayor a 0.", campo="monto")
    if redondeo_centavos <= 0:
        raise ErrorDeValidacion("El redondeo debe ser mayor a 0.", campo="redondeo_centavos")
    exacto = monto_centavos * (BP_UNIDAD + variacion_bp)  # en centavos × 10.000
    unidad = BP_UNIDAD * redondeo_centavos
    resultado = ((2 * exacto + unidad) // (2 * unidad)) * redondeo_centavos
    if resultado <= 0:
        raise ErrorDeValidacion(
            "El ajuste dejaría la cuota en $ 0; revisá el porcentaje.", campo="variacion"
        )
    return resultado


def variacion_promedio_bp(total_antes_centavos: int, total_despues_centavos: int) -> int:
    """Cuánto subió en promedio la cuota del conjunto (ponderado por monto), en bp."""
    if total_antes_centavos <= 0:
        raise ErrorDeValidacion("El total previo debe ser mayor a 0.")
    diferencia = (total_despues_centavos - total_antes_centavos) * BP_UNIDAD
    # half-up simétrico para soportar deflación (diferencia negativa)
    signo = -1 if diferencia < 0 else 1
    return signo * ((2 * abs(diferencia) + total_antes_centavos) // (2 * total_antes_centavos))


@dataclass(frozen=True)
class AjusteCalculado:
    """Ajuste listo para persistir en el historial inmutable (`ajustes`).

    `fecha_ajuste` es el hito del ciclo del contrato (no el día del clic): junto
    con UNIQUE(contrato_id, fecha_aplicacion) impide aplicar dos veces el mismo
    ciclo. Un override sin motivo no se puede construir.
    """

    contrato_id: int
    fecha_ajuste: date
    anio_base: int
    mes_base: int
    meses_ciclo: int
    variacion_bp: int
    cuota_antes_centavos: int
    cuota_despues_centavos: int
    es_override: bool = False
    motivo_override: str | None = None

    def __post_init__(self):
        validar_variacion_bp(self.variacion_bp)
        if self.meses_ciclo <= 0:
            raise ErrorDeValidacion("El ciclo de ajuste debe ser mayor a 0.", campo="ciclo_meses")
        if self.cuota_antes_centavos <= 0 or self.cuota_despues_centavos <= 0:
            raise ErrorDeValidacion("Las cuotas del ajuste deben ser mayores a 0.")
        motivo = (self.motivo_override or "").strip() or None
        object.__setattr__(self, "motivo_override", motivo)
        if self.es_override and motivo is None:
            raise ErrorDeValidacion(
                "Indicá el motivo del ajuste a mano.", campo="motivo_override"
            )
        if not self.es_override:
            object.__setattr__(self, "motivo_override", None)
