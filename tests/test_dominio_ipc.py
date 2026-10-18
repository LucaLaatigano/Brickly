"""Dominio IPC (H3): acumulado compuesto, ventana base, redondeo y override."""

from datetime import date

import pytest

from gestion.dominio.errores import ErrorDeValidacion
from gestion.dominio.ipc import (
    AjusteCalculado,
    IpcMensual,
    acumular_variaciones_bp,
    aplicar_variacion,
    meses_base,
    variacion_promedio_bp,
)


class TestMesesBase:
    def test_trimestre_anterior_al_mes_del_ajuste(self):
        assert meses_base(date(2026, 10, 1), 3) == [(2026, 7), (2026, 8), (2026, 9)]

    def test_cruza_fin_de_anio(self):
        assert meses_base(date(2027, 1, 15), 3) == [(2026, 10), (2026, 11), (2026, 12)]

    def test_ciclo_mensual_y_semestral(self):
        assert meses_base(date(2026, 3, 1), 1) == [(2026, 2)]
        assert len(meses_base(date(2026, 7, 1), 6)) == 6


class TestAcumulado:
    def test_compuesto_no_suma_simple(self):
        # 1,021 × 1,034 × 1,037 = 1,094775… → 9,48 % (la suma simple daría 9,20 %)
        assert acumular_variaciones_bp([210, 340, 370]) == 948

    def test_un_solo_mes_es_identidad(self):
        assert acumular_variaciones_bp([250]) == 250

    def test_deflacion_y_ceros(self):
        assert acumular_variaciones_bp([0, 0, 0]) == 0
        # 0,99 × 1,01 = 0,9999 → -1 bp
        assert acumular_variaciones_bp([-100, 100]) == -1

    def test_redondeo_half_up_a_un_bp(self):
        # 1,0001 × 0,9999 = 0,99999999 → 9999,9999 bp → redondea a 10000 → 0
        assert acumular_variaciones_bp([1, -1]) == 0
        # 1,0015 × 1,0015 = 1,00300225 → 30,0225 bp → 30
        assert acumular_variaciones_bp([15, 15]) == 30

    def test_sin_meses_es_error(self):
        with pytest.raises(ErrorDeValidacion):
            acumular_variaciones_bp([])


class TestAplicarVariacion:
    def test_redondeo_a_centavos(self):
        # $ 12.800 × 1,0948 = $ 14.013,44
        assert aplicar_variacion(1_280_000, 948, 1) == 1_401_344

    def test_redondeo_a_cien_pesos_half_up(self):
        # $ 14.013,44 → $ 14.000 ; $ 14.050 exacto → $ 14.100
        assert aplicar_variacion(1_280_000, 948, 10_000) == 1_400_000
        assert aplicar_variacion(1_405_000, 0, 10_000) == 1_410_000

    def test_deflacion_baja_la_cuota(self):
        assert aplicar_variacion(1_000_000, -50, 1) == 995_000

    def test_variacion_fuera_de_rango(self):
        with pytest.raises(ErrorDeValidacion):
            aplicar_variacion(1_000_000, -10_000, 1)
        with pytest.raises(ErrorDeValidacion):
            aplicar_variacion(1_000_000, 10_001, 1)

    def test_no_acepta_float(self):
        with pytest.raises(ErrorDeValidacion):
            aplicar_variacion(1_000_000, 9.48, 1)  # type: ignore[arg-type]


class TestPromedioYEntidades:
    def test_promedio_ponderado(self):
        assert variacion_promedio_bp(2_000_000, 2_189_600) == 948
        assert variacion_promedio_bp(1_000_000, 995_000) == -50

    def test_ipc_mensual_valida_rango(self):
        IpcMensual(2026, 7, -150)
        with pytest.raises(ErrorDeValidacion):
            IpcMensual(2026, 13, 100)
        with pytest.raises(ErrorDeValidacion):
            IpcMensual(2026, 7, 10_001)

    def _ajuste(self, **extra):
        base = dict(
            contrato_id=1,
            fecha_ajuste=date(2026, 10, 1),
            anio_base=2026,
            mes_base=7,
            meses_ciclo=3,
            variacion_bp=948,
            cuota_antes_centavos=1_280_000,
            cuota_despues_centavos=1_401_344,
        )
        base.update(extra)
        return AjusteCalculado(**base)

    def test_override_sin_motivo_no_se_puede_construir(self):
        with pytest.raises(ErrorDeValidacion, match="motivo"):
            self._ajuste(es_override=True, motivo_override="   ")

    def test_override_con_motivo_y_motivo_descartado_sin_override(self):
        assert self._ajuste(es_override=True, motivo_override=" Pactado 8 % ").motivo_override == "Pactado 8 %"
        assert self._ajuste(motivo_override="ignorado").motivo_override is None
