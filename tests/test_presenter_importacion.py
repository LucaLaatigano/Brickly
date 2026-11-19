"""Tests unitarios del presentador de importación."""

from datetime import date

from brickly.aplicacion.importacion import (
    FilaPrevisualizacionImportacion,
    PrevisualizacionImportacion,
)
from brickly.ui.presenters.importacion import (
    presentar_fila_importacion,
    presentar_previsualizacion,
    presentar_resumen_importacion,
)


def test_presentar_fila_con_contrato_vigente():
    fila = FilaPrevisualizacionImportacion(
        numero_fila=2,
        unidad_texto="Rivadavia 3421 · 3º B",
        direccion="Rivadavia 3421",
        piso="3",
        depto="B",
        m2=48,
        propietario="Carlos",
        inquilino_nombre="Lucía Gómez",
        inquilino_telefono="11-4567-8901",
        inquilino_email="lucia@mail.com",
        fecha_inicio=date(2026, 1, 1),
        fecha_fin_informativa=date(2027, 1, 1),
        monto_inicial_centavos=38000000,
        dia_vencimiento=10,
        dias_gracia=5,
        tasa_diaria_bp=200,
        ciclo_ipc_meses=3,
        redondeo=1,
        estado="nuevo_con_contrato",
        errores=(),
        advertencias=(),
        defaults_aplicados=(),
        es_importable=True,
    )

    p = presentar_fila_importacion(fila)
    assert p.unidad == "Rivadavia 3421 · 3º B"
    assert p.inquilino == "Lucía Gómez"
    assert p.vigencia == "01/01/2026 al 01/01/2027"
    assert p.cuota_mensual == "$ 380.000"
    assert p.estado_texto == "Listo"
    assert p.variante_chip == "listo"
    assert p.es_importable is True
    assert p.tiene_errores is False


def test_presentar_fila_con_error():
    fila = FilaPrevisualizacionImportacion(
        numero_fila=3,
        unidad_texto="Mitre 1180",
        direccion="Mitre 1180",
        piso=None,
        depto=None,
        m2=None,
        propietario=None,
        inquilino_nombre="Carlos",
        inquilino_telefono=None,
        inquilino_email=None,
        fecha_inicio=None,
        fecha_fin_informativa=None,
        monto_inicial_centavos=None,
        dia_vencimiento=10,
        dias_gracia=5,
        tasa_diaria_bp=200,
        ciclo_ipc_meses=3,
        redondeo=1,
        estado="error",
        errores=("La fecha de inicio de contrato es obligatoria.",),
        advertencias=(),
        defaults_aplicados=(),
        es_importable=False,
    )

    p = presentar_fila_importacion(fila)
    assert p.estado_texto == "Con errores"
    assert p.variante_chip == "vencida"
    assert p.tiene_errores is True
    assert p.es_importable is False
    assert "fecha de inicio" in p.motivo_o_detalle


def test_presentar_resumen_y_habilitacion_boton():
    prev_con_errores = PrevisualizacionImportacion(
        total_filas=3,
        filas_listas=2,
        filas_con_errores=1,
        filas_omitidas=0,
        filas=(),
    )
    r1 = presentar_resumen_importacion(prev_con_errores)
    assert r1.puede_importar is False
    assert "2 listas · 1 con error" in r1.texto_resumen

    prev_limpia = PrevisualizacionImportacion(
        total_filas=3,
        filas_listas=2,
        filas_con_errores=0,
        filas_omitidas=1,
        filas=(),
    )
    r2 = presentar_resumen_importacion(prev_limpia)
    assert r2.puede_importar is True
    assert r2.texto_boton_importar == "Importar 2 departamentos"
    assert "2 listas · 1 se omitirá" in r2.texto_resumen
