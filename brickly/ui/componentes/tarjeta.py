"""Card (spec §2.1): superficie con borde, radio 10, padding 16."""

import customtkinter as ctk

from brickly.ui import estilo


class Tarjeta(ctk.CTkFrame):
    """Contenedor de sección. El contenido va en `self.cuerpo`."""

    def __init__(self, master, titulo: str | None = None, **kwargs):
        super().__init__(
            master,
            fg_color=estilo.SUPERFICIE,
            corner_radius=estilo.RADIO_CARD,
            border_width=1,
            border_color=estilo.BORDE,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)

        fila = 0
        if titulo:
            ctk.CTkLabel(
                self,
                text=titulo,
                font=estilo.FUENTE_SECCION,
                text_color=estilo.TEXTO,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=estilo.PADDING_CARD, pady=(estilo.PADDING_CARD, 0))
            fila = 1

        self.cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        self.cuerpo.grid(
            row=fila, column=0, sticky="nsew",
            padx=estilo.PADDING_CARD, pady=estilo.PADDING_CARD,
        )
        self.cuerpo.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(fila, weight=1)
