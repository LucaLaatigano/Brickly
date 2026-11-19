"""Departamento — unidad administrada y su nombre visible.

Regla de composición del nombre (§3: «Rivadavia 3421 · 3º B»): un solo lugar
para firmas de la lista, cabeceras de detalle y textos de confirmación.
"""

from dataclasses import dataclass

from brickly.dominio.errores import ErrorDeValidacion


def nombre_unidad(direccion: str, piso: str | None, depto: str | None) -> str:
    """«Rivadavia 3421 · 3º B» · «Sarmiento 890 · PB» · «Mitre 1180»."""
    partes = []
    if piso:
        partes.append(f"{piso}º" if piso.isdigit() else piso)
    if depto:
        partes.append(depto)
    if partes:
        return f"{direccion} · {' '.join(partes)}"
    return direccion


def _limpiar(texto: str | None) -> str | None:
    """Trim y `None` para vacíos: en la base un dato no informado es NULL."""
    if texto is None:
        return None
    texto = texto.strip()
    return texto or None


def limpiar_espacios(texto: str | None) -> str:
    """Colapsa secuencias de espacios en uno solo y recorta extremos."""
    return " ".join((texto or "").split())


def clave_unidad_normalizada(
    direccion: str, piso: str | None = None, depto: str | None = None
) -> tuple[str, str, str]:
    """Clave canónica inmutable (direccion, piso, depto) en minúsculas para deduplicar.

    Normaliza pisos con sufijo ordinal ('3º' o '3°' -> '3') para que coincidan
    con el formato estándar de `nombre_unidad`.
    """
    dir_norm = limpiar_espacios(direccion).casefold()
    piso_limpio = limpiar_espacios(piso)
    if piso_limpio.endswith(("º", "°")):
        base = piso_limpio[:-1].rstrip()
        if base.isdigit():
            piso_limpio = base
    piso_norm = piso_limpio.casefold()
    depto_norm = limpiar_espacios(depto).casefold()
    return (dir_norm, piso_norm, depto_norm)


def desglosar_unidad_compuesta(
    texto_unidad: str, piso: str | None = None, depto: str | None = None
) -> tuple[str, str | None, str | None]:
    """Separa una unidad compuesta con ' · ' si no se especificaron piso ni depto.

    Ejemplos:
    - 'Rivadavia 3421 · 3º B' -> ('Rivadavia 3421', '3', 'B')
    - 'Sarmiento 890 · PB' -> ('Sarmiento 890', 'PB', None)
    - 'Mitre 1180' -> ('Mitre 1180', None, None)
    """
    piso_limpio = _limpiar(piso)
    depto_limpio = _limpiar(depto)
    texto = (texto_unidad or "").strip()

    if piso_limpio is None and depto_limpio is None and " · " in texto:
        direccion_res, resto = texto.split(" · ", 1)
        tokens = resto.strip().split(maxsplit=1)
        if not tokens:
            return (direccion_res.strip(), None, None)
        candidato_piso = tokens[0]
        if candidato_piso.endswith(("º", "°")):
            base = candidato_piso[:-1].rstrip()
            if base.isdigit():
                candidato_piso = base
        candidato_depto = tokens[1].strip() if len(tokens) > 1 else None
        return (
            direccion_res.strip(),
            candidato_piso or None,
            candidato_depto or None,
        )

    return (texto, piso_limpio, depto_limpio)


@dataclass(frozen=True)
class Departamento:
    """La validación vive acá: no se puede construir un departamento inválido."""

    direccion: str
    piso: str | None = None
    depto: str | None = None
    m2: int | None = None
    propietario: str | None = None
    id: int | None = None

    def __post_init__(self):
        direccion = (self.direccion or "").strip()
        if not direccion:
            raise ErrorDeValidacion("La dirección es obligatoria.", campo="direccion")
        if self.m2 is not None and self.m2 <= 0:
            raise ErrorDeValidacion("Los m² deben ser un número mayor a 0.", campo="m2")

        object.__setattr__(self, "direccion", direccion)
        object.__setattr__(self, "piso", _limpiar(self.piso))
        object.__setattr__(self, "depto", _limpiar(self.depto))
        object.__setattr__(self, "propietario", _limpiar(self.propietario))

    @property
    def unidad(self) -> str:
        return nombre_unidad(self.direccion, self.piso, self.depto)
