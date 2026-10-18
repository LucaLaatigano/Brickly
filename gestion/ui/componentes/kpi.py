"""Tarjeta KPI (spec §2.2): caption → valor → sub-línea → progreso opcional."""

from typing import Callable

import customtkinter as ctk

from gestion.ui import estilo


class TarjetaKPI(ctk.CTkFrame):
    def __init__(
        self,
        master,
        caption: str,
        valor: str = "—",
        sublinea: str | None = None,
        tono: str = "normal",
        progreso: float | None = None,
        al_click: Callable[[], None] | None = None,
    ):
        super().__init__(
            master,
            fg_color=estilo.SUPERFICIE,
            corner_radius=estilo.RADIO_CARD,
            border_width=1,
            border_color=estilo.BORDE,
        )
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text=caption, font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2, anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=estilo.PADDING_CARD, pady=(estilo.PADDING_CARD, 0))

        self._valor = ctk.CTkLabel(
            self,
            text=valor,
            font=estilo.FUENTE_KPI,
            text_color=estilo.PELIGRO if tono == "peligro" else estilo.TEXTO,
            anchor="w",
        )
        self._valor.grid(row=1, column=0, sticky="ew", padx=estilo.PADDING_CARD)

        fila = 2
        if sublinea:
            ctk.CTkLabel(
                self, text=sublinea, font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_3, anchor="w",
            ).grid(row=fila, column=0, sticky="ew", padx=estilo.PADDING_CARD)
            fila += 1

        if progreso is not None:
            barra = ctk.CTkProgressBar(
                self, height=6, progress_color=estilo.ACENTO, fg_color=estilo.SUPERFICIE_2,
            )
            barra.set(progreso)
            barra.grid(row=fila, column=0, sticky="ew", padx=estilo.PADDING_CARD)
            fila += 1

        self.grid_rowconfigure(fila, minsize=estilo.PADDING_CARD)

        if al_click is not None:
            self.configure(cursor="hand2")
            self._vincular_click(self, al_click)

    def _vincular_click(self, widget, al_click: Callable[[], None]) -> None:
        """La card entera es clickeable (KPI «Ajustes este mes» → Ajustes, §3.1)."""
        widget.bind("<Button-1>", lambda _evento: al_click())
        for hijo in widget.winfo_children():
            self._vincular_click(hijo, al_click)

    def actualizar(self, valor: str, sublinea: str | None = None) -> None:
        self._valor.configure(text=valor)
