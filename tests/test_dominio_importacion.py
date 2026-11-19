"""Tests de funciones puras de dominio para importación de unidades."""

from brickly.dominio.departamento import (
    clave_unidad_normalizada,
    desglosar_unidad_compuesta,
    limpiar_espacios,
)


def test_limpiar_espacios():
    assert limpiar_espacios(None) == ""
    assert limpiar_espacios("") == ""
    assert limpiar_espacios("   ") == ""
    assert limpiar_espacios("  Av.  Rivadavia   3421  \t\n ") == "Av. Rivadavia 3421"


def test_clave_unidad_normalizada():
    c1 = clave_unidad_normalizada("Rivadavia 3421", "3º", "B")
    c2 = clave_unidad_normalizada("rivadavia  3421", "3°", "b")
    c3 = clave_unidad_normalizada("  Rivadavia 3421  ", "3", "B  ")
    assert c1 == ("rivadavia 3421", "3", "b")
    assert c1 == c2 == c3

    # Piso no numérico conserva su texto en minúsculas
    assert clave_unidad_normalizada("Sarmiento 890", "PB", None) == (
        "sarmiento 890",
        "pb",
        "",
    )


def test_desglosar_unidad_compuesta():
    # Formato export H7: "Rivadavia 3421 · 3º B"
    dir1, piso1, depto1 = desglosar_unidad_compuesta("Rivadavia 3421 · 3º B")
    assert dir1 == "Rivadavia 3421"
    assert piso1 == "3"
    assert depto1 == "B"

    # Con símbolo de grado alternativo "°"
    dir2, piso2, depto2 = desglosar_unidad_compuesta("Rivadavia 3421 · 3° B")
    assert dir2 == "Rivadavia 3421"
    assert piso2 == "3"
    assert depto2 == "B"

    # Solo piso (PB)
    dir3, piso3, depto3 = desglosar_unidad_compuesta("Sarmiento 890 · PB")
    assert dir3 == "Sarmiento 890"
    assert piso3 == "PB"
    assert depto3 is None

    # Solo dirección sin separador
    dir4, piso4, depto4 = desglosar_unidad_compuesta("Mitre 1180")
    assert dir4 == "Mitre 1180"
    assert piso4 is None
    assert depto4 is None

    # Si ya se provee piso o depto explícito, no desglosa
    dir5, piso5, depto5 = desglosar_unidad_compuesta(
        "Rivadavia 3421 · 3º B", piso="4", depto="C"
    )
    assert dir5 == "Rivadavia 3421 · 3º B"
    assert piso5 == "4"
    assert depto5 == "C"
