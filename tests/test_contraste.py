"""Contraste WCAG ≥ 4.5:1 de los pares texto/fondo usados (spec §1.3).

El modo oscuro no se envía en v1: sus pares quedan definidos pero se validan
cuando exista un dark mode real.
"""

import pytest

from brickly.ui import estilo

# (nombre, token texto, token fondo) — todos en modo claro.
PARES = [
    ("TEXTO sobre FONDO_APP", estilo.TEXTO, estilo.FONDO_APP),
    ("TEXTO sobre SUPERFICIE", estilo.TEXTO, estilo.SUPERFICIE),
    ("TEXTO_2 sobre SUPERFICIE", estilo.TEXTO_2, estilo.SUPERFICIE),
    ("TEXTO_2 sobre SUPERFICIE_2", estilo.TEXTO_2, estilo.SUPERFICIE_2),
    ("TEXTO_2 sobre FONDO_APP", estilo.TEXTO_2, estilo.FONDO_APP),
    ("TEXTO_3 sobre SUPERFICIE", estilo.TEXTO_3, estilo.SUPERFICIE),
    ("TEXTO_3 sobre FONDO_APP", estilo.TEXTO_3, estilo.FONDO_APP),
    ("ACENTO sobre SUPERFICIE", estilo.ACENTO, estilo.SUPERFICIE),
    ("blanco sobre ACENTO", estilo.BLANCO, estilo.ACENTO),
    ("blanco sobre ACENTO_HOVER", estilo.BLANCO, estilo.ACENTO_HOVER),
    ("EXITO sobre EXITO_BG", estilo.EXITO, estilo.EXITO_BG),
    ("ALERTA sobre ALERTA_BG", estilo.ALERTA, estilo.ALERTA_BG),
    ("PELIGRO sobre PELIGRO_BG", estilo.PELIGRO, estilo.PELIGRO_BG),
    ("PELIGRO sobre SUPERFICIE", estilo.PELIGRO, estilo.SUPERFICIE),
    ("ACENTO sobre INFO_BG", estilo.ACENTO, estilo.INFO_BG),
]


def _luminancia(color_hex: str) -> float:
    color_hex = color_hex.lstrip("#")
    canales = []
    for indice in (0, 2, 4):
        canal = int(color_hex[indice : indice + 2], 16) / 255
        canales.append(canal / 12.92 if canal <= 0.03928 else ((canal + 0.055) / 1.055) ** 2.4)
    rojo, verde, azul = canales
    return 0.2126 * rojo + 0.7152 * verde + 0.0722 * azul


def _contraste(fg_hex: str, bg_hex: str) -> float:
    l1, l2 = _luminancia(fg_hex), _luminancia(bg_hex)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


@pytest.mark.parametrize(
    "fg,bg",
    [(fg[0], bg[0]) for _, fg, bg in PARES],
    ids=[nombre for nombre, _, _ in PARES],
)
def test_contraste_suficiente(fg, bg):
    assert _contraste(fg, bg) >= 4.5
