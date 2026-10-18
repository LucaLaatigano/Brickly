"""Contrato e Inquilino — reglas puras de vigencia, validación y ciclo de ajuste.

El contrato une un departamento con un inquilino y fija las condiciones de las
cuotas que se generan mes a mes (ADR-0002).
"""

import calendar
from dataclasses import dataclass
from datetime import date

from gestion.dominio.errores import ErrorDeValidacion


def _limpiar(texto: str | None) -> str | None:
    if texto is None:
        return None
    texto = texto.strip()
    return texto or None


def sumar_meses(fecha: date, meses: int) -> date:
    """Avanza `meses` meses calendario acotando el día al fin del mes destino."""
    total_meses = (fecha.year * 12 + (fecha.month - 1)) + meses
    anio, mes_0 = divmod(total_meses, 12)
    mes = mes_0 + 1
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(fecha.day, ultimo_dia))


@dataclass(frozen=True)
class Inquilino:
    """Persona titular de uno o más contratos."""

    nombre: str
    telefono: str | None = None
    email: str | None = None
    id: int | None = None

    def __post_init__(self):
        nombre = (self.nombre or "").strip()
        if not nombre:
            raise ErrorDeValidacion(
                "El nombre del inquilino es obligatorio.", campo="inquilino_nombre"
            )
        object.__setattr__(self, "nombre", nombre)
        object.__setattr__(self, "telefono", _limpiar(self.telefono))
        object.__setattr__(self, "email", _limpiar(self.email))


@dataclass(frozen=True)
class Contrato:
    """Condiciones vigentes o históricas del alquiler de un departamento."""

    departamento_id: int
    fecha_inicio: date
    monto_centavos: int
    dia_vencimiento: int = 10
    dias_gracia: int = 5
    tasa_mora_bp: int = 200
    ciclo_meses: int = 3
    redondeo_centavos: int = 1
    fecha_fin: date | None = None
    inquilino_id: int | None = None
    id: int | None = None

    def __post_init__(self):
        if not isinstance(self.monto_centavos, int) or isinstance(self.monto_centavos, bool):
            raise ErrorDeValidacion("El monto debe expresarse en centavos enteros.", campo="monto")
        if self.monto_centavos <= 0:
            raise ErrorDeValidacion(
                "El monto de la cuota debe ser mayor a 0.", campo="monto"
            )
        if not (1 <= self.dia_vencimiento <= 28):
            raise ErrorDeValidacion(
                "El día de vencimiento debe estar entre 1 y 28.",
                campo="dia_vencimiento",
            )
        if self.dias_gracia < 0:
            raise ErrorDeValidacion(
                "Los días de gracia no pueden ser negativos.", campo="dias_gracia"
            )
        if not (0 <= self.tasa_mora_bp <= 10_000):
            raise ErrorDeValidacion(
                "La tasa de mora debe estar entre 0 % y 100 %.", campo="tasa_mora"
            )
        if self.ciclo_meses <= 0:
            raise ErrorDeValidacion(
                "El ciclo de ajuste debe ser mayor a 0.", campo="ciclo_meses"
            )
        if self.redondeo_centavos <= 0:
            raise ErrorDeValidacion(
                "El redondeo debe ser mayor a 0.", campo="redondeo_centavos"
            )
        if self.fecha_fin is not None and self.fecha_fin < self.fecha_inicio:
            raise ErrorDeValidacion(
                "La fecha de fin no puede ser anterior al inicio.", campo="fecha_fin"
            )

    def esta_vencido(self, hoy: date) -> bool:
        return self.fecha_fin is not None and self.fecha_fin < hoy

    def proxima_fecha_ajuste(
        self, hoy: date, ultimo_ajuste: date | None = None
    ) -> date | None:
        """Próximo hito del ciclo trimestral/N-mensual desde `fecha_inicio` (spec §3.3)."""
        paso = 1
        while True:
            candidata = sumar_meses(self.fecha_inicio, paso * self.ciclo_meses)
            if self.fecha_fin is not None and candidata > self.fecha_fin:
                return None
            periodo_candidato = (candidata.year, candidata.month)
            if periodo_candidato >= (hoy.year, hoy.month):
                if ultimo_ajuste is None or periodo_candidato > (
                    ultimo_ajuste.year,
                    ultimo_ajuste.month,
                ):
                    return candidata
            paso += 1
