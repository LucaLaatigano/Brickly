"""Textos exactos de la pantalla Cobranzas (spec §3.4 y §4 F2)."""

from gestion.aplicacion.cobranzas import (
    PreviewGeneracionCuotas,
    ResultadoGeneracionCuotas,
    ResumenCobranzasMes,
)
from gestion.ui.vistas.cobranzas import (
    avanzar_periodo,
    texto_mes_al_dia,
    texto_preview_generacion,
    texto_resultado_generacion,
    texto_resumen_mes,
)


def test_texto_preview_plural_exacto_de_la_spec():
    preview = PreviewGeneracionCuotas(
        anio=2026,
        mes=10,
        cuotas_a_generar=36,
        total_centavos=54_000_000,
        unidades_sin_contrato=3,
        cuotas_existentes=0,
    )
    assert (
        texto_preview_generacion(preview)
        == "Se generarán 36 cuotas por $ 540.000 · 3 unidades sin contrato quedarán afuera"
    )


def test_texto_preview_singular_y_sin_contratos():
    singular = PreviewGeneracionCuotas(
        anio=2026,
        mes=10,
        cuotas_a_generar=1,
        total_centavos=1_280_000,
        unidades_sin_contrato=1,
        cuotas_existentes=0,
    )
    assert (
        texto_preview_generacion(singular)
        == "Se generarán 1 cuota por $ 12.800 · 1 unidad sin contrato quedará afuera"
    )

    vacio = PreviewGeneracionCuotas(
        anio=2026,
        mes=10,
        cuotas_a_generar=0,
        total_centavos=0,
        unidades_sin_contrato=2,
        cuotas_existentes=0,
    )
    assert (
        texto_preview_generacion(vacio)
        == "No hay contratos vigentes para generar cuotas · 2 unidades sin contrato quedarán afuera"
    )


def test_texto_resultado_exacto_de_la_spec():
    resultado = ResultadoGeneracionCuotas(
        anio=2026,
        mes=10,
        cuotas_generadas=36,
        total_centavos=54_000_000,
        unidades_sin_contrato=3,
    )
    assert (
        texto_resultado_generacion(resultado)
        == "36 cuotas generadas · $ 540.000 · 3 unidades sin contrato quedaron afuera"
    )


def test_texto_resultado_idempotente_sin_nuevas():
    resultado = ResultadoGeneracionCuotas(
        anio=2026,
        mes=10,
        cuotas_generadas=0,
        total_centavos=0,
        unidades_sin_contrato=3,
    )
    assert (
        texto_resultado_generacion(resultado)
        == "Las cuotas de octubre 2026 ya estaban generadas (0 nuevas)."
    )


def test_texto_resumen_mes_con_y_sin_vencidas():
    con_vencidas = ResumenCobranzasMes(
        cobrado_centavos=41_250_000,
        esperado_centavos=54_000_000,
        cantidad_vencidas=4,
        monto_vencidas_centavos=3_840_000,
        cantidad_pendientes=6,
        cantidad_pagadas=26,
        total_cuotas=36,
    )
    assert (
        texto_resumen_mes(con_vencidas)
        == "Cobrado $ 412.500 de $ 540.000 · Vencidas 4 ($ 38.400) · Pendientes 6"
    )

    sin_vencidas = ResumenCobranzasMes(
        cobrado_centavos=54_000_000,
        esperado_centavos=54_000_000,
        cantidad_vencidas=0,
        monto_vencidas_centavos=0,
        cantidad_pendientes=0,
        cantidad_pagadas=36,
        total_cuotas=36,
    )
    assert (
        texto_resumen_mes(sin_vencidas)
        == "Cobrado $ 540.000 de $ 540.000 · Vencidas 0 · Pendientes 0"
    )


def test_texto_mes_al_dia():
    assert texto_mes_al_dia(10, 36) == "Octubre al día: 36 de 36 cobradas."


def test_avanzar_periodo_cruza_fin_de_anio():
    assert avanzar_periodo(2026, 1, -1) == (2025, 12)
    assert avanzar_periodo(2026, 12, 1) == (2027, 1)
    assert avanzar_periodo(2026, 10, 1) == (2026, 11)


def test_evaluar_monto_pago_en_vivo():
    from gestion.ui.vistas.cobranzas import evaluar_monto_pago

    total = 1_433_600  # $ 14.336

    assert evaluar_monto_pago("14.336", total) == ("ok", "", True)
    assert evaluar_monto_pago("10.000", total) == (
        "alerta",
        "Quedará un saldo de $ 4.336",
        True,
    )
    assert evaluar_monto_pago("15.000", total) == (
        "error",
        "El monto supera el total ($ 14.336)",
        False,
    )
    assert evaluar_monto_pago("0", total) == (
        "error",
        "El monto del pago debe ser mayor a cero.",
        False,
    )
    assert evaluar_monto_pago("abc", total) == (
        "error",
        "El monto del pago debe ser mayor a cero.",
        False,
    )


def test_textos_panel_pago_y_banners():
    from datetime import date

    from gestion.aplicacion.cobranzas import DetalleCuotaParaPago, ResultadoPago
    from gestion.ui.vistas.cobranzas import (
        texto_error_pago,
        texto_exito_pago,
        texto_vencimiento_pago,
    )

    detalle_vencida = DetalleCuotaParaPago(
        cuota_id=1,
        contrato_id=1,
        departamento_id=1,
        unidad="Rivadavia 3421 · 3º B",
        inquilino="Laura Giménez",
        anio=2026,
        mes=10,
        fecha_vencimiento=date(2026, 10, 10),
        dias_atraso=5,
        saldo_capital_centavos=1_280_000,
        mora_centavos=0,
        total_centavos=1_280_000,
        fecha_sugerida=date(2026, 10, 15),
        medio_sugerido="transferencia",
    )
    assert (
        texto_vencimiento_pago(detalle_vencida)
        == "Vence 10/10/2026 (vencida: 5 días)"
    )

    resultado = ResultadoPago(
        pago_id=1,
        cuota_id=1,
        departamento_id=1,
        unidad="Rivadavia 3421 · 3º B",
        monto_centavos=1_433_600,
        capital_aplicado_centavos=1_280_000,
        mora_aplicada_centavos=153_600,
        saldo_restante_centavos=0,
    )
    assert (
        texto_exito_pago(resultado)
        == "Pago registrado: $ 14.336 · Rivadavia 3421 · 3º B"
    )
    assert (
        texto_error_pago("El monto supera el total")
        == "No se pudo registrar: El monto supera el total. No se modificó nada."
    )
