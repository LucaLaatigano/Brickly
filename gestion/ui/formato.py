"""Formatos y parseo argentinos (spec §1.4).

Solo presentación: acá no se calcula plata — los montos llegan en centavos
enteros desde `aplicacion` y se convierten a texto (y viceversa para inputs).
"""

import re
from datetime import date, datetime

MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

MESES_ABREV = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

# Acepta "12800", "12.800", "12.800,50" y el prefijo "$".
_PATRON_MONTO = re.compile(r"^\$?\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?$")
_PATRON_PORCENTAJE = re.compile(r"^(\d+)(?:[.,](\d{1,2}))?$")


def formatear_monto(centavos: int) -> str:
    """`$ 123.456,78`; sin decimales cuando son 0."""
    signo = "-" if centavos < 0 else ""
    enteros, resto = divmod(abs(centavos), 100)
    miles = f"{enteros:,}".replace(",", ".")
    return f"{signo}$ {miles},{resto:02d}" if resto else f"{signo}$ {miles}"


def formatear_monto_con_signo(centavos: int) -> str:
    """Como `formatear_monto` pero el positivo lleva `+` (Δ del ajuste, §3.5)."""
    texto = formatear_monto(centavos)
    return f"+{texto}" if centavos > 0 else texto


def parsear_monto(texto: str) -> int:
    """Texto del usuario → centavos. `ValueError` si no es un monto válido."""
    coincidencia = _PATRON_MONTO.match(texto.strip())
    if not coincidencia:
        raise ValueError("Monto inválido")
    enteros = int(coincidencia.group(1).replace(".", ""))
    decimales = (coincidencia.group(2) or "").ljust(2, "0")
    return enteros * 100 + int(decimales)


def formatear_fecha(fecha: date) -> str:
    return fecha.strftime("%d/%m/%Y")


def parsear_fecha(texto: str) -> date:
    """`dd/mm/aaaa` → date. `ValueError` si no parsea."""
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def formatear_periodo(anio: int, mes: int) -> str:
    """`octubre 2026` (minúscula, como en prosa y tablas)."""
    return f"{MESES[mes - 1]} {anio}"


def formatear_mes_abreviado(anio: int, mes: int) -> str:
    """`jul 2026` — meses base y vencimientos en tablas densas (§3.5)."""
    return f"{MESES_ABREV[mes - 1]} {anio}"


def formatear_rango_meses(anio_ini: int, mes_ini: int, anio_fin: int, mes_fin: int) -> str:
    """Rango de meses como los muestra §3.5: `jul–sep 2026`, `nov 2026–ene 2027`."""
    if (anio_ini, mes_ini) == (anio_fin, mes_fin):
        return formatear_mes_abreviado(anio_ini, mes_ini)
    if anio_ini == anio_fin:
        return f"{MESES_ABREV[mes_ini - 1]}–{MESES_ABREV[mes_fin - 1]} {anio_ini}"
    return (
        f"{formatear_mes_abreviado(anio_ini, mes_ini)}"
        f"–{formatear_mes_abreviado(anio_fin, mes_fin)}"
    )


def formatear_porcentaje(bp: int, con_signo: bool = False) -> str:
    """Puntos básicos → `9,42 %` (100 bp = 1 %); `con_signo` agrega `+` (Δ, §3.5)."""
    signo = "-" if bp < 0 else ("+" if con_signo and bp > 0 else "")
    enteros, centesimas = divmod(abs(bp), 100)
    return f"{signo}{enteros},{centesimas:02d} %"


def parsear_porcentaje(texto: str) -> int:
    """`9,42` / `9.42` → puntos básicos. `ValueError` si no parsea."""
    limpio = texto.strip().rstrip("%").strip()
    coincidencia = _PATRON_PORCENTAJE.match(limpio)
    if not coincidencia:
        raise ValueError("Porcentaje inválido")
    decimales = (coincidencia.group(2) or "").ljust(2, "0")
    return int(coincidencia.group(1)) * 100 + int(decimales)


def formatear_dias(dias: int) -> str:
    return "1 día" if dias == 1 else f"{dias} días"
