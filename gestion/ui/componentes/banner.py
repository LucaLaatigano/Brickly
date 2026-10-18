"""Banner (spec §2.5): feedback de acciones, arriba del contenido, no bloquea."""

from typing import Callable

import customtkinter as ctk

from gestion.ui import estilo

_VARIANTES = {
    "exito": (estilo.EXITO_BG, estilo.EXITO),
    "alerta": (estilo.ALERTA_BG, estilo.ALERTA),
    "error": (estilo.PELIGRO_BG, estilo.PELIGRO),
}


class Banner(ctk.CTkFrame):
    """Franja de feedback con ✕ para cerrar. `al_cerrar` avisa al contenedor.

    `accion=(texto, callback)` agrega un botón inline (CTA del banner del Panel,
    p. ej. «Generar cuotas de octubre» o «Reintentar»).
    """

    def __init__(
        self,
        master,
        tipo: str,
        texto: str,
        al_cerrar=None,
        accion: tuple[str, Callable[[], None]] | None = None,
    ):
        fondo, color = _VARIANTES[tipo]
        super().__init__(master, fg_color=color, corner_radius=estilo.RADIO_CARD)
        self._al_cerrar = al_cerrar

        # El borde izquierdo de 3 px sale del marco exterior: el interior pisa
        # todo salvo esa franja.
        interior = ctk.CTkFrame(self, fg_color=fondo, corner_radius=estilo.RADIO_CARD)
        interior.pack(fill="both", expand=True, padx=(3, 0))
        interior.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            interior,
            text=texto,
            font=estilo.FUENTE_CHICO,
            text_color=color,
            anchor="w",
            justify="left",
            wraplength=680 if accion else 760,
        ).grid(row=0, column=0, sticky="ew", padx=(12, 4), pady=8)

        columna = 1
        if accion is not None:
            estilo.boton_secundario(
                interior,
                accion[0],
                command=accion[1],
                height=28,
            ).grid(row=0, column=columna, sticky="e", padx=(4, 4))
            columna += 1

        ctk.CTkButton(
            interior,
            text="✕",
            width=24,
            height=24,
            fg_color="transparent",
            hover_color=fondo,
            text_color=estilo.TEXTO_2,
            font=estilo.FUENTE_CHICO,
            command=self._cerrar,
        ).grid(row=0, column=columna, sticky="e", padx=(0, 8))

    def _cerrar(self) -> None:
        if self._al_cerrar:
            self._al_cerrar()
