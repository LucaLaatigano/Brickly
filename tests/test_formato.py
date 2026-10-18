"""Tests de formato y parseo argentinos (spec §1.4)."""

from datetime import date

import pytest

from gestion.ui.formato import (
    formatear_dias,
    formatear_fecha,
    formatear_mes_abreviado,
    formatear_monto,
    formatear_monto_con_signo,
    formatear_periodo,
    formatear_porcentaje,
    formatear_rango_meses,
    parsear_fecha,
    parsear_monto,
    parsear_porcentaje,
)


class TestMontos:
    def test_formatea_con_miles_y_sin_decimales_en_cero(self):
        assert formatear_monto(1_280_000) == "$ 12.800"
        assert formatear_monto(1_433_600) == "$ 14.336"
        assert formatear_monto(0) == "$ 0"

    def test_formatea_con_decimales(self):
        assert formatear_monto(1_234_567) == "$ 12.345,67"
        assert formatear_monto(50) == "$ 0,50"

    def test_formatea_negativos(self):
        assert formatear_monto(-100_000) == "-$ 1.000"

    def test_monto_con_signo_para_delta(self):
        assert formatear_monto_con_signo(121_344) == "+$ 1.213,44"
        assert formatear_monto_con_signo(-100_000) == "-$ 1.000"
        assert formatear_monto_con_signo(0) == "$ 0"

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("12800", 1_280_000),
            ("12.800", 1_280_000),
            ("12.800,50", 1_280_050),
            ("12.800,5", 1_280_050),
            ("$ 12.800", 1_280_000),
            (" 12800 ", 1_280_000),
        ],
    )
    def test_parsea_variantes(self, texto, esperado):
        assert parsear_monto(texto) == esperado

    @pytest.mark.parametrize("texto", ["", "abc", "12.34", "12,345", "12.800,123", "-5"])
    def test_parseo_invalido(self, texto):
        with pytest.raises(ValueError):
            parsear_monto(texto)


class TestFechas:
    def test_formatea_dd_mm_aaaa(self):
        assert formatear_fecha(date(2026, 10, 15)) == "15/10/2026"

    def test_parsea_dd_mm_aaaa(self):
        assert parsear_fecha("15/10/2026") == date(2026, 10, 15)

    @pytest.mark.parametrize("texto", ["2026-10-15", "15-10-2026", "32/13/2026", ""])
    def test_parseo_invalido(self, texto):
        with pytest.raises(ValueError):
            parsear_fecha(texto)


class TestPeriodosYPorcentajes:
    def test_periodo_en_minuscula(self):
        assert formatear_periodo(2026, 10) == "octubre 2026"
        assert formatear_periodo(2026, 1) == "enero 2026"

    def test_mes_abreviado_y_rangos(self):
        assert formatear_mes_abreviado(2026, 7) == "jul 2026"
        assert formatear_rango_meses(2026, 7, 2026, 9) == "jul–sep 2026"
        assert formatear_rango_meses(2026, 7, 2026, 7) == "jul 2026"
        assert formatear_rango_meses(2026, 11, 2027, 1) == "nov 2026–ene 2027"

    def test_porcentaje_dos_decimales_con_coma(self):
        assert formatear_porcentaje(942) == "9,42 %"
        assert formatear_porcentaje(200) == "2,00 %"

    def test_porcentaje_con_signo_para_promedios_y_delta(self):
        assert formatear_porcentaje(942, con_signo=True) == "+9,42 %"
        assert formatear_porcentaje(-50, con_signo=True) == "-0,50 %"
        assert formatear_porcentaje(0, con_signo=True) == "0,00 %"

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [("9,42", 942), ("9.42", 942), ("2", 200), ("9,4", 940), ("9,42 %", 942)],
    )
    def test_parsea_porcentaje(self, texto, esperado):
        assert parsear_porcentaje(texto) == esperado

    @pytest.mark.parametrize("texto", ["", "abc", "9,429", "-2", "1.234,5"])
    def test_parseo_invalido(self, texto):
        with pytest.raises(ValueError):
            parsear_porcentaje(texto)

    def test_dias(self):
        assert formatear_dias(1) == "1 día"
        assert formatear_dias(12) == "12 días"
