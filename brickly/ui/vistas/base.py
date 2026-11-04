"""Base de las vistas: header (§1.2) + franja de banners + cuerpo.

Filas en orden: volver (opcional) · título + acciones · banners · cuerpo.
Las filas sin griddear colapsan solas, así que el índice queda fijo.
"""

from typing import Callable

import customtkinter as ctk

from brickly.ui import estilo
from brickly.ui.componentes.banner import Banner


class VistaBase(ctk.CTkFrame):
    def __init__(
        self,
        master,
        titulo: str,
        al_volver: Callable[[], None] | None = None,
        texto_volver: str = "‹ Volver",
    ):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        fila = 0
        if al_volver is not None:
            ctk.CTkButton(
                self,
                text=texto_volver,
                command=al_volver,
                anchor="w",
                height=24,
                fg_color="transparent",
                hover_color=estilo.SUPERFICIE_2,
                text_color=estilo.TEXTO_2,
                font=estilo.FUENTE_CHICO,
            ).grid(row=fila, column=0, sticky="w")
            fila += 1

        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.grid(row=fila, column=0, sticky="ew")
        cabecera.grid_columnconfigure(0, weight=1)
        fila += 1

        self._titulo = ctk.CTkLabel(
            cabecera,
            text=titulo,
            font=estilo.FUENTE_TITULO,
            text_color=estilo.TEXTO,
            anchor="w",
            justify="left",
        )
        self._titulo.grid(row=0, column=0, sticky="w")

        self._acciones = ctk.CTkFrame(cabecera, fg_color="transparent")
        self._acciones.grid(row=0, column=1, sticky="e")

        self._fila_banners = fila
        fila += 1
        self._franja = ctk.CTkFrame(self, fg_color="transparent")
        self._banner: Banner | None = None

        self.cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        self.cuerpo.grid(row=fila, column=0, sticky="nsew", pady=(estilo.GAP, 0))
        self.cuerpo.grid_columnconfigure(0, weight=1)
        self.cuerpo.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(fila, weight=1)

    # --- API para las subclases ----------------------------------------------

    def agregar_accion(self, widget: ctk.CTkButton) -> ctk.CTkButton:
        widget.pack(side="left", padx=(8, 0))
        return widget

    def poner_titulo(self, texto: str) -> None:
        self._titulo.configure(text=texto)

    def mostrar_banner(
        self,
        tipo: str,
        texto: str,
        accion: tuple[str, Callable[[], None]] | None = None,
    ) -> None:
        self.limpiar_banner()
        self._banner = Banner(
            self._franja,
            tipo=tipo,
            texto=texto,
            al_cerrar=self.limpiar_banner,
            accion=accion,
        )
        self._banner.pack(fill="x")
        self._franja.grid(row=self._fila_banners, column=0, sticky="ew", pady=(estilo.GAP, 0))

    def limpiar_banner(self) -> None:
        if self._banner is not None:
            self._banner.destroy()
            self._banner = None
        self._franja.grid_forget()
