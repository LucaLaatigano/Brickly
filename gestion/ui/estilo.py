"""Tokens de estilo (spec §1.3) y fuentes compartidas.

Los colores son tuplas `(claro, oscuro)` — con appearance mode fijo en claro
por v1, el segundo valor queda listo para un dark mode futuro sin rediseño.
Las fuentes se crean una sola vez (`inicializar()`), después de que exista la
ventana raíz: `tkinter.font` no admite crearlas antes.

Ajustes vs. la tabla de §1.3 (autorizados ahí: "oscurecer texto, no aclarar
fondo"): `TEXTO_3` claro pasó de #6B7280 a #63707E (sobre FONDO_APP daba 4,39)
y `ACENTO` claro de #2563EB a #1D4ED8 (sobre INFO_BG daba 4,24). El contraste
se verifica en `tests/test_contraste.py`.
"""

import customtkinter as ctk

# --- Colores semánticos (rol, no valor) -------------------------------------

FONDO_APP = ("#F3F4F6", "#18181B")
SUPERFICIE = ("#FFFFFF", "#232326")
SUPERFICIE_2 = ("#F9FAFB", "#2A2A2E")
BORDE = ("#E5E7EB", "#3A3A40")
TEXTO = ("#111827", "#F4F4F5")
TEXTO_2 = ("#4B5563", "#A1A1AA")
TEXTO_3 = ("#63707E", "#71717A")
ACENTO = ("#1D4ED8", "#3B82F6")
ACENTO_HOVER = ("#1E40AF", "#2563EB")
BLANCO = ("#FFFFFF", "#FFFFFF")
EXITO = ("#15803D", "#4ADE80")
EXITO_BG = ("#DCFCE7", "#0E2A1B")
ALERTA = ("#B45309", "#FBBF24")
ALERTA_BG = ("#FEF3C7", "#332503")
PELIGRO = ("#B91C1C", "#F87171")
PELIGRO_BG = ("#FEE2E2", "#3A0F0F")
INFO_BG = ("#DBEAFE", "#1E2A4A")

# --- Métricas (§1.3) --------------------------------------------------------

RADIO_BOTON = 8
RADIO_CARD = 10
RADIO_CHIP = 12
ALTO_BOTON = 36
ALTO_BOTON_FILA = 32
ALTO_NAV = 40
ALTO_FILA = 44
ALTO_ENCABEZADO_TABLA = 36
PADDING_PAGINA = 24
PADDING_CARD = 16
GAP = 16

# --- Fuentes (§1.3) — se pueblan en `inicializar()` --------------------------

FAMILIA = "Segoe UI"

FUENTE_TITULO: ctk.CTkFont
FUENTE_SECCION: ctk.CTkFont
FUENTE_CUERPO: ctk.CTkFont
FUENTE_CUERPO_NEGRITA: ctk.CTkFont
FUENTE_CHICO: ctk.CTkFont
FUENTE_CHICO_NEGRITA: ctk.CTkFont
FUENTE_MICRO: ctk.CTkFont
FUENTE_KPI: ctk.CTkFont


def inicializar() -> None:
    """Fija appearance/theme y crea las fuentes. Requiere ventana raíz creada."""
    global FUENTE_TITULO, FUENTE_SECCION, FUENTE_CUERPO, FUENTE_CUERPO_NEGRITA
    global FUENTE_CHICO, FUENTE_CHICO_NEGRITA, FUENTE_MICRO, FUENTE_KPI

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    FUENTE_TITULO = ctk.CTkFont(family=FAMILIA, size=22, weight="bold")
    FUENTE_SECCION = ctk.CTkFont(family=FAMILIA, size=15, weight="bold")
    FUENTE_CUERPO = ctk.CTkFont(family=FAMILIA, size=13)
    FUENTE_CUERPO_NEGRITA = ctk.CTkFont(family=FAMILIA, size=13, weight="bold")
    FUENTE_CHICO = ctk.CTkFont(family=FAMILIA, size=12)
    FUENTE_CHICO_NEGRITA = ctk.CTkFont(family=FAMILIA, size=12, weight="bold")
    FUENTE_MICRO = ctk.CTkFont(family=FAMILIA, size=11, weight="bold")
    FUENTE_KPI = ctk.CTkFont(family=FAMILIA, size=30, weight="bold")


def boton_primario(master, texto: str, command=None, **kwargs) -> ctk.CTkButton:
    """Botón de la acción principal: uno por pantalla (§1.3).

    `height` y el resto de kwargs se pueden pisar (botones en filas usan
    `ALTO_BOTON_FILA`).
    """
    return ctk.CTkButton(
        master,
        text=texto,
        command=command,
        height=kwargs.pop("height", ALTO_BOTON),
        corner_radius=RADIO_BOTON,
        fg_color=ACENTO,
        hover_color=ACENTO_HOVER,
        text_color=BLANCO,
        font=FUENTE_CUERPO,
        **kwargs,
    )


def boton_secundario(master, texto: str, command=None, **kwargs) -> ctk.CTkButton:
    return ctk.CTkButton(
        master,
        text=texto,
        command=command,
        height=kwargs.pop("height", ALTO_BOTON),
        corner_radius=RADIO_BOTON,
        fg_color=SUPERFICIE,
        hover_color=SUPERFICIE_2,
        text_color=TEXTO,
        border_width=1,
        border_color=BORDE,
        font=FUENTE_CUERPO,
        **kwargs,
    )
