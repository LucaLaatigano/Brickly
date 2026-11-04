"""Reglas puras de contratos, inquilinos, cuotas, mora y pagos (ADR-0002)."""

from datetime import date

import pytest

from brickly.dominio.contrato import Contrato, Inquilino, sumar_meses
from brickly.dominio.cuota import (
    Cuota,
    calcular_mora_cuota,
    dias_atraso_cuota,
    estado_cuota,
    fecha_vencimiento_cuota,
    saldo_capital_cuota,
)
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.dominio.pago import (
    CuotaImputable,
    Pago,
    imputar_pago_a_cuota,
    imputar_pago_fifo,
)


class TestInquilino:
    def test_exige_nombre(self):
        with pytest.raises(ErrorDeValidacion) as error:
            Inquilino(nombre="   ")
        assert error.value.campo == "inquilino_nombre"

    def test_normaliza_vacios(self):
        inquilino = Inquilino(nombre="  Laura Giménez ", telefono=" ", email="laura@mail.com ")
        assert inquilino.nombre == "Laura Giménez"
        assert inquilino.telefono is None
        assert inquilino.email == "laura@mail.com"


class TestContrato:
    def test_rechaza_monto_no_positivo_o_float(self):
        for invalido in (0, -100, 12800.5, True):
            with pytest.raises(ErrorDeValidacion) as error:
                Contrato(
                    departamento_id=1,
                    fecha_inicio=date(2026, 3, 1),
                    monto_centavos=invalido,
                )
            assert error.value.campo == "monto"

    def test_rechaza_dia_vencimiento_fuera_de_1_a_28(self):
        for dia in (0, 29, 31):
            with pytest.raises(ErrorDeValidacion) as error:
                Contrato(
                    departamento_id=1,
                    fecha_inicio=date(2026, 3, 1),
                    monto_centavos=1_000_000,
                    dia_vencimiento=dia,
                )
            assert error.value.campo == "dia_vencimiento"

    def test_rechaza_fecha_fin_anterior_a_inicio(self):
        with pytest.raises(ErrorDeValidacion) as error:
            Contrato(
                departamento_id=1,
                fecha_inicio=date(2026, 3, 10),
                fecha_fin=date(2026, 3, 1),
                monto_centavos=1_000_000,
            )
        assert error.value.campo == "fecha_fin"

    def test_esta_vencido_segun_reloj(self):
        contrato = Contrato(
            departamento_id=1,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 9, 30),
            monto_centavos=1_000_000,
        )
        assert not contrato.esta_vencido(date(2026, 9, 30))
        assert contrato.esta_vencido(date(2026, 10, 1))

    def test_proxima_fecha_ajuste_respeta_ciclo_y_ultimo_ajuste(self):
        contrato = Contrato(
            departamento_id=1,
            fecha_inicio=date(2026, 7, 1),
            monto_centavos=1_280_000,
            ciclo_meses=3,
        )
        # En octubre 2026 todavía no se aplicó el ajuste del trimestre jul–sep.
        assert contrato.proxima_fecha_ajuste(date(2026, 10, 15)) == date(2026, 10, 1)
        # Una vez aplicado en octubre, salta al siguiente trimestre (enero 2027).
        assert contrato.proxima_fecha_ajuste(
            date(2026, 10, 15), ultimo_ajuste=date(2026, 10, 15)
        ) == date(2027, 1, 1)

    def test_proxima_fecha_ajuste_es_none_si_supera_fecha_fin(self):
        contrato = Contrato(
            departamento_id=1,
            fecha_inicio=date(2026, 7, 1),
            fecha_fin=date(2026, 9, 30),
            monto_centavos=1_280_000,
            ciclo_meses=3,
        )
        assert contrato.proxima_fecha_ajuste(date(2026, 8, 15)) is None


class TestSumarMeses:
    def test_acota_al_ultimo_dia_del_mes(self):
        assert sumar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
        assert sumar_meses(date(2026, 11, 10), 3) == date(2027, 2, 10)


class TestCuota:
    def test_fecha_vencimiento_fija_incluso_en_febrero_o_fin_de_semana(self):
        # 10/10/2026 es sábado: no se corre a día hábil (ADR-0002 #3).
        assert fecha_vencimiento_cuota(2026, 10, 10) == date(2026, 10, 10)
        assert fecha_vencimiento_cuota(2026, 2, 28) == date(2026, 2, 28)

    @pytest.mark.parametrize(
        ("monto", "pagado", "vence", "hoy", "esperado"),
        [
            (1_280_000, 1_280_000, date(2026, 10, 10), date(2026, 10, 15), "pagada"),
            (1_280_000, 0, date(2026, 10, 10), date(2026, 10, 10), "pendiente"),
            (1_280_000, 500_000, date(2026, 10, 10), date(2026, 10, 10), "parcial"),
            (1_280_000, 0, date(2026, 10, 10), date(2026, 10, 11), "vencida"),
            (1_280_000, 500_000, date(2026, 10, 10), date(2026, 10, 15), "vencida"),
        ],
    )
    def test_estado_cuota(self, monto, pagado, vence, hoy, esperado):
        assert estado_cuota(monto, pagado, vence, hoy) == esperado

    def test_saldo_y_dias_atraso(self):
        assert saldo_capital_cuota(1_280_000, 300_000) == 980_000
        assert saldo_capital_cuota(1_280_000, 1_280_000) == 0
        assert dias_atraso_cuota(1_280_000, 0, date(2026, 10, 10), date(2026, 10, 15)) == 5
        assert dias_atraso_cuota(1_280_000, 1_280_000, date(2026, 10, 10), date(2026, 10, 15)) == 0

    def test_cuota_valida_periodo_y_monto(self):
        cuota = Cuota(
            contrato_id=1,
            anio=2026,
            mes=10,
            fecha_vencimiento=date(2026, 10, 10),
            monto_centavos=1_280_000,
        )
        assert cuota.monto_centavos == 1_280_000
        with pytest.raises(ErrorDeValidacion):
            Cuota(
                contrato_id=1,
                anio=2026,
                mes=13,
                fecha_vencimiento=date(2026, 10, 10),
                monto_centavos=1_280_000,
            )


class TestMoraYPagos:
    def test_mora_es_cero_dentro_de_dias_de_gracia(self):
        # 5 días de atraso == 5 días de gracia → mora = 0.
        assert (
            calcular_mora_cuota(
                monto_centavos=1_280_000,
                pagado_centavos=0,
                fecha_vencimiento=date(2026, 10, 10),
                hoy=date(2026, 10, 15),
                dias_gracia=5,
                tasa_mora_bp=200,
            )
            == 0
        )

    def test_mora_diaria_simple_sobre_saldo_impago_tras_gracia(self):
        # 30 días de atraso al 2,00 % mensual (200 bp) sobre $ 12.800 → $ 256 (25.600 centavos).
        assert (
            calcular_mora_cuota(
                monto_centavos=1_280_000,
                pagado_centavos=0,
                fecha_vencimiento=date(2026, 9, 15),
                hoy=date(2026, 10, 15),
                dias_gracia=5,
                tasa_mora_bp=200,
            )
            == 25_600
        )
        # Con pago parcial previo ($ 2.800 pagados → saldo $ 10.000), mora de 30 días al 2 % = $ 200.
        assert (
            calcular_mora_cuota(
                monto_centavos=1_280_000,
                pagado_centavos=280_000,
                fecha_vencimiento=date(2026, 9, 15),
                hoy=date(2026, 10, 15),
                dias_gracia=5,
                tasa_mora_bp=200,
            )
            == 20_000
        )

    def test_imputar_pago_total_y_parcial_conserva_invariante(self):
        cuota = CuotaImputable(
            cuota_id=1, saldo_capital_centavos=1_280_000, mora_centavos=153_600
        )
        # Pago total ($ 14.336): cubre toda la mora y todo el capital.
        total = imputar_pago_a_cuota(cuota, 1_433_600)
        assert total.mora_centavos == 153_600
        assert total.monto_centavos == 1_280_000
        assert total.total_aplicado_centavos == 1_433_600

        # Pago parcial ($ 500.000): cubre mora ($ 153.600) y el resto reduce capital.
        parcial = imputar_pago_a_cuota(cuota, 500_000)
        assert parcial.mora_centavos == 153_600
        assert parcial.monto_centavos == 346_400
        assert parcial.total_aplicado_centavos == 500_000

    def test_imputar_rechaza_monto_mayor_al_total(self):
        cuota = CuotaImputable(
            cuota_id=1, saldo_capital_centavos=1_280_000, mora_centavos=153_600
        )
        with pytest.raises(ErrorDeNegocio):
            imputar_pago_a_cuota(cuota, 1_433_601)

    def test_imputacion_fifo_entre_varias_cuotas(self):
        cuotas = [
            CuotaImputable(cuota_id=10, saldo_capital_centavos=1_000_000, mora_centavos=50_000),
            CuotaImputable(cuota_id=11, saldo_capital_centavos=1_000_000, mora_centavos=0),
        ]
        imputaciones = imputar_pago_fifo(cuotas, 1_300_000)
        assert len(imputaciones) == 2
        assert imputaciones[0].cuota_id == 10
        assert imputaciones[0].total_aplicado_centavos == 1_050_000
        assert imputaciones[1].cuota_id == 11
        assert imputaciones[1].monto_centavos == 250_000
        assert sum(i.total_aplicado_centavos for i in imputaciones) == 1_300_000

    def test_entidad_pago_valida_medio_y_monto(self):
        pago = Pago(
            contrato_id=1,
            fecha=date(2026, 10, 15),
            monto_centavos=1_433_600,
            medio="transferencia",
            nota="  Comprobante 441  ",
        )
        assert pago.nota == "Comprobante 441"
        with pytest.raises(ErrorDeValidacion):
            Pago(
                contrato_id=1,
                fecha=date(2026, 10, 15),
                monto_centavos=1_000,
                medio="bitcoin",
            )
