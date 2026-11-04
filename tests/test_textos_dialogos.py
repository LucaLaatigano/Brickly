"""Textos del diálogo de borrado (§2.7: la consecuencia, explícita)."""

from brickly.aplicacion.departamentos import DependenciasDepartamento
from brickly.ui.vistas.departamentos import consecuencia_de_borrado


def test_sin_movimientos_no_agrega_frase():
    assert consecuencia_de_borrado(DependenciasDepartamento(0, 0, 0)) == ""


def test_contrato_unico_en_singular():
    frase = consecuencia_de_borrado(DependenciasDepartamento(1, 14, 32))
    assert frase == " Se borran también su contrato, 14 cuotas y 32 pagos."


def test_varios_contratos_y_plurales():
    frase = consecuencia_de_borrado(DependenciasDepartamento(2, 24, 18))
    assert frase == " Se borran también sus 2 contratos, 24 cuotas y 18 pagos."


def test_cantidades_de_uno():
    frase = consecuencia_de_borrado(DependenciasDepartamento(1, 1, 1))
    assert frase == " Se borran también su contrato, 1 cuota y 1 pago."


def test_una_sola_dependencia_se_enumera_sola():
    frase = consecuencia_de_borrado(DependenciasDepartamento(0, 3, 0))
    assert frase == " Se borran también 3 cuotas."
