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
