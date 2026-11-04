"""Helpers puros de la tabla (spec §2.4)."""

from brickly.ui.componentes.tabla import truncar


def test_no_trunca_cuando_entra():
    assert truncar("corto") == "corto"
    assert truncar("x" * 40) == "x" * 40


def test_trunca_nombres_largos_con_elipsis():
    assert truncar("x" * 41) == "x" * 39 + "…"
    assert len(truncar("y" * 100)) == 40
