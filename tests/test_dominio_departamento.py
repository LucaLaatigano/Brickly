"""Reglas puras de departamentos (entidad, nombre visible, validación)."""

import pytest

from gestion.dominio.departamento import Departamento, nombre_unidad
from gestion.dominio.errores import ErrorDeValidacion


class TestValidacion:
    def test_exige_direccion(self):
        with pytest.raises(ErrorDeValidacion) as error:
            Departamento(direccion="   ")
        assert error.value.campo == "direccion"

    def test_m2_debe_ser_positivo(self):
        for valor in (0, -3):
            with pytest.raises(ErrorDeValidacion) as error:
                Departamento(direccion="Rivadavia 3421", m2=valor)
            assert error.value.campo == "m2"

    def test_normaliza_vacios_y_espacios(self):
        departamento = Departamento(
            direccion="  Rivadavia 3421  ", piso=" 3 ", depto=" ", m2=62, propietario=""
        )
        assert departamento.direccion == "Rivadavia 3421"
        assert departamento.piso == "3"
        assert departamento.depto is None
        assert departamento.propietario is None


class TestNombreUnidad:
    @pytest.mark.parametrize(
        ("piso", "depto", "esperado"),
        [
            ("3", "B", "Rivadavia 3421 · 3º B"),
            ("1", "A", "Rivadavia 3421 · 1º A"),
            ("PB", None, "Rivadavia 3421 · PB"),
            (None, None, "Rivadavia 3421"),
            ("PB", "C", "Rivadavia 3421 · PB C"),
        ],
    )
    def test_compone(self, piso, depto, esperado):
        assert nombre_unidad("Rivadavia 3421", piso, depto) == esperado

    def test_la_entidad_expone_el_mismo_nombre(self):
        departamento = Departamento(direccion="Mitre 1180", piso="1", depto="A")
        assert departamento.unidad == "Mitre 1180 · 1º A"
