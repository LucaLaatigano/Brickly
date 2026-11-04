"""Errores de negocio — mensaje en castellano, listo para mostrar en la UI.

La UI los muestra (banner o inline junto al campo); no son bugs: son reglas.
"""


class ErrorDeNegocio(Exception):
    """Base de los errores esperados de dominio/aplicación."""


class ErrorDeValidacion(ErrorDeNegocio):
    """Error de validación atado a un campo del formulario (si aplica).

    `campo` es el nombre lógico del campo (`direccion`, `m2`, …) para que la UI
    muestre el mensaje junto al control; `None` = error general.
    """

    def __init__(self, mensaje: str, campo: str | None = None):
        super().__init__(mensaje)
        self.campo = campo
