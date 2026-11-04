"""Chip de estado (spec §2.3): el estado siempre se lee como texto, nunca solo color."""

import customtkinter as ctk

from brickly.ui import estilo

_VARIANTES = {
    # variante: (fondo, texto, etiqueta por defecto)
    "pagada": (estilo.EXITO_BG, estilo.EXITO, "Pagada"),
    "parcial": (estilo.ALERTA_BG, estilo.ALERTA, "Parcial"),
    "alerta": (estilo.ALERTA_BG, estilo.ALERTA, ""),
    "pendiente": (estilo.SUPERFICIE_2, estilo.TEXTO_2, "Pendiente"),
    "vencida": (estilo.PELIGRO_BG, estilo.PELIGRO, "Vencida"),
    "info": (estilo.INFO_BG, estilo.ACENTO, ""),
    # Ajustes IPC (§3.5): estado de cada contrato por aplicar.
    "listo": (estilo.EXITO_BG, estilo.EXITO, "Listo"),
    "faltan_datos": (estilo.ALERTA_BG, estilo.ALERTA, "Faltan datos"),
    # Sincronización INDEC (H6): estado de cada período en la vista previa.
    "nuevo": (estilo.EXITO_BG, estilo.EXITO, "Nuevo"),
    "actualizado": (estilo.INFO_BG, estilo.ACENTO, "Actualizado"),
    "sin_cambios": (estilo.SUPERFICIE_2, estilo.TEXTO_2, "Sin cambios"),
    "manual_protegido": (estilo.ALERTA_BG, estilo.ALERTA, "Manual protegido"),
}


class ChipEstado(ctk.CTkLabel):
    def __init__(self, master, variante: str, texto: str | None = None, dias: int | None = None):
        fondo, color, etiqueta = _VARIANTES[variante]
        if texto is not None:
            etiqueta = texto
        elif variante == "vencida" and dias is not None:
            etiqueta = f"Vencida · {dias} días"
        super().__init__(
            master,
            text=etiqueta,
            height=24,
            corner_radius=estilo.RADIO_CHIP,
            font=estilo.FUENTE_MICRO,
            fg_color=fondo,
            text_color=color,
            padx=10,
        )
