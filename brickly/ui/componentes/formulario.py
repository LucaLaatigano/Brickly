"""Campo de formulario (spec §2.6): label arriba, control, ayuda y error debajo.

Nada de validación silenciosa: el error aparece al confirmar, junto al campo,
con texto (no solo color).
"""

import customtkinter as ctk

from brickly.ui import estilo

ALTO_CONTROL = estilo.ALTO_BOTON


class Campo(ctk.CTkFrame):
    """Campo tipado: `texto` (CTkEntry) u `opciones` (CTkOptionMenu).

    `etiqueta=None` omite el label: el wizard de ajustes usa el control sin
    etiqueta dentro de una celda de grilla (§3.5 paso 2).
    """

    def __init__(
        self,
        master,
        etiqueta: str | None = None,
        ayuda: str | None = None,
        tipo: str = "texto",
        valores: list[str] | None = None,
        placeholder: str | None = None,
        justificar: str = "left",
        mostrar: str | None = None,
    ):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        fila = 0
        if etiqueta:
            ctk.CTkLabel(
                self, text=etiqueta, font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_2, anchor="w",
            ).grid(row=fila, column=0, sticky="w")
            fila += 1

        if tipo == "opciones":
            self._control = ctk.CTkOptionMenu(
                self,
                values=valores or [],
                height=ALTO_CONTROL,
                fg_color=estilo.SUPERFICIE,
                button_color=estilo.SUPERFICIE,
                button_hover_color=estilo.SUPERFICIE_2,
                text_color=estilo.TEXTO,
                dropdown_fg_color=estilo.SUPERFICIE,
                dropdown_text_color=estilo.TEXTO,
                dropdown_hover_color=estilo.SUPERFICIE_2,
                font=estilo.FUENTE_CUERPO,
                dropdown_font=estilo.FUENTE_CUERPO,
                anchor="w",
            )
        else:
            kwargs_entry = {}
            if mostrar is not None:
                kwargs_entry["show"] = mostrar
            self._control = ctk.CTkEntry(
                self,
                height=ALTO_CONTROL,
                border_color=estilo.BORDE,
                fg_color=estilo.SUPERFICIE,
                text_color=estilo.TEXTO,
                font=estilo.FUENTE_CUERPO,
                placeholder_text=placeholder or "",
                justify=justificar,
                **kwargs_entry,
            )
            self._control.bind("<FocusIn>", lambda _e: self._control.configure(border_color=estilo.ACENTO))
            self._control.bind("<FocusOut>", lambda _e: self._control.configure(border_color=estilo.BORDE))

        self._control.grid(row=fila, column=0, sticky="ew", pady=(4 if fila else 0, 0))
        fila += 1

        if ayuda:
            ctk.CTkLabel(
                self, text=ayuda, font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_3, anchor="w", justify="left",
            ).grid(row=fila, column=0, sticky="w", pady=(4, 0))
            fila += 1

        self._error = ctk.CTkLabel(
            self, text="", font=estilo.FUENTE_CHICO,
            text_color=estilo.PELIGRO, anchor="w", justify="left",
        )
        self._fila_error = fila

    # --- API para las vistas -------------------------------------------------

    def valor(self) -> str:
        return self._control.get()

    def poner_valor(self, texto: str) -> None:
        if isinstance(self._control, ctk.CTkEntry):
            self._control.delete(0, "end")
            self._control.insert(0, texto)
        else:
            self._control.set(texto)

    def mostrar_error(self, mensaje: str) -> None:
        self._error.configure(text=mensaje, text_color=estilo.PELIGRO)
        self._error.grid(row=self._fila_error, column=0, sticky="w", pady=(4, 0))

    def mostrar_aviso(self, mensaje: str) -> None:
        self._error.configure(text=mensaje, text_color=estilo.ALERTA)
        self._error.grid(row=self._fila_error, column=0, sticky="w", pady=(4, 0))

    def limpiar_error(self) -> None:
        self._error.configure(text="")
        self._error.grid_forget()

    def enfocar(self) -> None:
        self._control.focus_set()

    def atajo(self, secuencia: str, accion) -> None:
        """Atajo sobre el control (Enter guarda, Esc cierra — §1.5)."""
        self._control.bind(secuencia, lambda _evento: accion())

    def al_cambiar(self, accion) -> None:
        """Dispara `accion()` al editar el campo (validación en vivo — §3.4)."""
        self._control.bind("<KeyRelease>", lambda _evento: accion())
