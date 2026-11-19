"""Tests unitarios y de integración de ServicioImportacionDepartamentos y parsers."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from brickly.aplicacion.departamentos import PredeterminadosContrato
from brickly.aplicacion.importacion import (
    EdicionManualFilaImportacion,
    ServicioImportacionDepartamentos,
    detectar_fila_encabezado,
    es_fila_vacia_o_totales,
    parsear_ciclo_importacion,
    parsear_fecha_importacion,
    parsear_monto_importacion,
    parsear_redondeo_importacion,
    parsear_tasa_mora_importacion,
    sugerir_mapeo_columnas,
)
from brickly.aplicacion.puertos import (
    FilaCrudaExcel,
    HojaCrudaExcel,
    ItemImportacionPersistible,
)
from brickly.dominio.departamento import Departamento
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion


class RelojFijo:
    def __init__(self, fecha: date):
        self._fecha = fecha

    def hoy(self) -> date:
        return self._fecha


# --- 1. Tests de Parsers ----------------------------------------------------


def test_parsear_monto_importacion_exitoso():
    # Entero en pesos -> centavos
    assert parsear_monto_importacion(380000) == 38000000
    # Decimal
    assert parsear_monto_importacion(Decimal("380000.50")) == 38000050
    # Texto es-AR con signo pesos y miles
    assert parsear_monto_importacion("$ 380.000,50") == 38000050
    assert parsear_monto_importacion("380000,50") == 38000050
    assert parsear_monto_importacion("380.000") == 38000000
    assert parsear_monto_importacion(None) is None
    assert parsear_monto_importacion("") is None


def test_parsear_monto_importacion_rechaza_invalidos():
    # float y bool prohibidos
    with pytest.raises(ErrorDeValidacion, match="float ni booleano"):
        parsear_monto_importacion(380000.5)
    with pytest.raises(ErrorDeValidacion, match="float ni booleano"):
        parsear_monto_importacion(True)

    # Moneda extranjera
    with pytest.raises(ErrorDeValidacion, match="Solo se admiten montos en pesos"):
        parsear_monto_importacion("USD 1200")

    # Formato anglosajón con coma de miles
    with pytest.raises(ErrorDeValidacion, match="Formato de monto ambiguo"):
        parsear_monto_importacion("380,000.00")

    # Más de 2 decimales
    with pytest.raises(ErrorDeValidacion, match="más de 2 decimales"):
        parsear_monto_importacion("380000,123")

    # Monto <= 0
    with pytest.raises(ErrorDeValidacion, match="mayor a 0"):
        parsear_monto_importacion(0)


def test_parsear_fecha_importacion():
    assert parsear_fecha_importacion(date(2026, 3, 1)) == date(2026, 3, 1)
    res_dt = parsear_fecha_importacion(datetime(2026, 3, 1, 14, 30, 0))
    assert res_dt == date(2026, 3, 1)
    assert type(res_dt) is date
    assert parsear_fecha_importacion("01/03/2026") == date(2026, 3, 1)
    assert parsear_fecha_importacion("1/3/2026") == date(2026, 3, 1)
    assert parsear_fecha_importacion("2026-03-01") == date(2026, 3, 1)
    assert parsear_fecha_importacion(None) is None

    # Año de 2 dígitos rechazado
    with pytest.raises(ErrorDeValidacion, match="4 dígitos"):
        parsear_fecha_importacion("01/03/26")

    # Formato numérico serial rechazado
    with pytest.raises(ErrorDeValidacion, match="formato numérico"):
        parsear_fecha_importacion(45323)

    # Año fuera de 2000..2100
    with pytest.raises(ErrorDeValidacion, match="entre 2000 y 2100"):
        parsear_fecha_importacion("01/03/1990")


def test_parsear_tasa_mora_importacion():
    assert parsear_tasa_mora_importacion("0,15%") == 15
    assert parsear_tasa_mora_importacion("0.15%") == 15
    assert parsear_tasa_mora_importacion("2%") == 200
    assert parsear_tasa_mora_importacion("200 bp") == 200
    assert parsear_tasa_mora_importacion(200) == 200
    assert parsear_tasa_mora_importacion(None) is None

    with pytest.raises(ErrorDeValidacion, match="float ni booleano"):
        parsear_tasa_mora_importacion(0.15)


def test_parsear_ciclo_y_redondeo():
    assert parsear_ciclo_importacion("Trimestral") == 3
    assert parsear_ciclo_importacion("semestral") == 6
    assert parsear_ciclo_importacion("3") == 3
    assert parsear_ciclo_importacion(3) == 3

    assert parsear_redondeo_importacion("Centavos") == 1
    assert parsear_redondeo_importacion("1") == 1
    assert parsear_redondeo_importacion("$ 100") == 100
    assert parsear_redondeo_importacion("100") == 100


# --- 2. Tests de Detección y Mapeo de Columnas ------------------------------


def test_detectar_fila_encabezado_y_sugerir_mapeo():
    filas = (
        FilaCrudaExcel(1, ("Planilla general de alquileres", None, None)),
        FilaCrudaExcel(2, (None, None, None)),
        FilaCrudaExcel(3, ("Dirección", "Piso", "Depto", "Inquilino", "Cuota mensual", "Inicio")),
        FilaCrudaExcel(4, ("Rivadavia 3421", "3", "B", "Lucía Gómez", 380000, "01/01/2026")),
    )

    fila_enc = detectar_fila_encabezado(filas)
    assert fila_enc == 3

    cols = sugerir_mapeo_columnas(filas[2], filas[3])
    mapeo = {c.campo_mapeado: c.indice for c in cols if c.campo_mapeado}

    assert mapeo["direccion"] == 0
    assert mapeo["piso"] == 1
    assert mapeo["depto"] == 2
    assert mapeo["nombre_inquilino"] == 3
    assert mapeo["monto_inicial_centavos"] == 4
    assert mapeo["fecha_inicio"] == 5


def test_sugerir_mapeo_export_h7():
    # Encabezados de la hoja Contratos del export H7
    encabezados = FilaCrudaExcel(
        1,
        (
            "Unidad",
            "Inquilino",
            "Inicio",
            "Fin",
            "Cuota inicial",
            "Cuota vigente",
            "Ciclo IPC (meses)",
            "Vence día",
            "Gracia (días)",
            "Mora diaria (%)",
            "Redondeo",
            "Estado",
        ),
    )
    datos = FilaCrudaExcel(
        2,
        (
            "Rivadavia 3421 · 3º B",
            "Lucía Gómez",
            date(2026, 1, 1),
            None,
            380000,
            420000,
            3,
            10,
            5,
            "0.15%",
            "Centavos",
            "Vigente",
        ),
    )

    cols = sugerir_mapeo_columnas(encabezados, datos)
    mapeo = {c.campo_mapeado: c.indice for c in cols if c.campo_mapeado}

    # Unidad se asigna a dirección
    assert mapeo["direccion"] == 0
    assert mapeo["nombre_inquilino"] == 1
    assert mapeo["fecha_inicio"] == 2
    assert mapeo["fecha_fin"] == 3
    # Cuota vigente tiene prioridad sobre cuota inicial
    assert mapeo["monto_inicial_centavos"] == 5
    assert mapeo["ciclo_ipc_meses"] == 6
    assert mapeo["dia_vencimiento"] == 7
    assert mapeo["dias_gracia"] == 8
    assert mapeo["tasa_diaria_bp"] == 9
    assert mapeo["redondeo"] == 10
    # Estado no se mapea
    assert "estado" not in mapeo


# --- 3. Tests de Previsualización y Deduplicación ---------------------------


@pytest.fixture()
def repo_mock():
    repo = MagicMock()
    repo.predeterminados_contrato.return_value = PredeterminadosContrato(
        dia_vencimiento=10,
        dias_gracia=5,
        tasa_mora_bp=200,
        ciclo_meses=3,
        redondeo_centavos=1,
    )
    repo.listar.return_value = []
    return repo


@pytest.fixture()
def lector_mock():
    return MagicMock()


def test_previsualizar_clasificacion_estados(repo_mock, lector_mock):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # 3 filas:
    # 1. Contrato vigente (fin > hoy)
    # 2. Contrato vencido (fin < hoy) -> queda nuevo_contrato_vencido (vacante)
    # 3. Sin contrato -> nuevo_vacante
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Fin", "Cuota")),
        FilaCrudaExcel(2, ("Rivadavia 3421", "Juan Pérez", "01/01/2026", "01/12/2026", "380000")),
        FilaCrudaExcel(3, ("Mitre 1180", "Carlos Ruiz", "01/01/2025", "01/05/2026", "300000")),
        FilaCrudaExcel(4, ("Belgrano 500", None, None, None, None)),
    )
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_mock, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "fecha_fin": 3,
        "monto_inicial_centavos": 4,
    }

    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.total_filas == 3
    assert prev.filas_listas == 3
    assert prev.filas_con_errores == 0

    f1 = prev.filas[0]
    assert f1.estado == "nuevo_con_contrato"
    assert f1.fecha_fin_informativa == date(2026, 12, 1)
    assert f1.es_importable is True

    f2 = prev.filas[1]
    assert f2.estado == "nuevo_contrato_vencido"
    assert f2.es_importable is True
    assert "Contrato vencido" in f2.advertencias[0]

    f3 = prev.filas[2]
    assert f3.estado == "nuevo_vacante"
    assert f3.es_importable is True


def test_previsualizar_dedupe_contra_db(repo_mock, lector_mock):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # Simular que Rivadavia 3421 3 B ya existe en la DB
    depto_existente = MagicMock()
    depto_existente.direccion = "Rivadavia 3421"
    depto_existente.piso = "3"
    depto_existente.depto = "B"
    repo_mock.listar.return_value = [depto_existente]

    filas = (
        FilaCrudaExcel(1, ("Unidad", "Inquilino", "Inicio", "Cuota")),
        # Coincide por desglose con Rivadavia 3421 3 B
        FilaCrudaExcel(2, ("Rivadavia 3421 · 3º B", "Juan", "01/01/2026", "380000")),
        # Nueva unidad
        FilaCrudaExcel(3, ("San Martín 100", "Pedro", "01/01/2026", "250000")),
    )
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_mock, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "monto_inicial_centavos": 3,
    }

    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.total_filas == 2
    assert prev.filas_listas == 1
    assert prev.filas_omitidas == 1

    f1 = prev.filas[0]
    assert f1.estado == "omitido_existente"
    assert f1.es_importable is False

    f2 = prev.filas[1]
    assert f2.estado == "nuevo_con_contrato"
    assert f2.es_importable is True


def test_previsualizar_dedupe_intra_archivo(repo_mock, lector_mock):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # Dos filas para la misma unidad en el mismo Excel:
    # Fila 2: contrato vigente más reciente (inicia 01/03/2026)
    # Fila 3: contrato anterior (inicia 01/01/2025 y terminó 28/02/2026)
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Fin", "Cuota")),
        FilaCrudaExcel(2, ("Mitre 500", "Nuevo Inquilino", "01/03/2026", None, "400000")),
        FilaCrudaExcel(3, ("Mitre 500", "Viejo Inquilino", "01/01/2025", "28/02/2026", "200000")),
    )
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_mock, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "fecha_fin": 3,
        "monto_inicial_centavos": 4,
    }

    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.total_filas == 2
    assert prev.filas_listas == 1
    assert prev.filas_omitidas == 1

    f_ganadora = prev.filas[0]
    assert f_ganadora.estado == "nuevo_con_contrato"
    assert f_ganadora.es_importable is True
    assert "múltiples filas" in f_ganadora.advertencias[0]

    f_perdedora = prev.filas[1]
    assert f_perdedora.estado == "omitido_contrato_anterior"
    assert f_perdedora.es_importable is False


def test_previsualizar_con_errores_y_edicion_manual(repo_mock, lector_mock):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # Fila 2: cuota inválida
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Cuota")),
        FilaCrudaExcel(2, ("Rivadavia 3421", "Juan", "01/01/2026", "monto_invalido")),
    )
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_mock, lector_mock, reloj)
    mapeo = {"direccion": 0, "nombre_inquilino": 1, "fecha_inicio": 2, "monto_inicial_centavos": 3}

    # Sin edición: error
    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.filas_con_errores == 1
    assert prev.filas[0].estado == "error"

    # Con edición manual que corrige el monto: pasa a lista
    ediciones = {2: EdicionManualFilaImportacion(2, {"monto_inicial_centavos": "350000"})}
    prev_corregida = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo, ediciones)
    assert prev_corregida.filas_con_errores == 0
    assert prev_corregida.filas[0].estado == "nuevo_con_contrato"
    assert prev_corregida.filas[0].monto_inicial_centavos == 35000000

    # Con edición manual que desmarca la fila: pasa a omitida
    ediciones_omitir = {2: EdicionManualFilaImportacion(2, {}, omitir=True)}
    prev_omitida = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo, ediciones_omitir)
    assert prev_omitida.filas_con_errores == 0
    assert prev_omitida.filas_omitidas == 1
    assert prev_omitida.filas[0].estado == "omitido_manual"


def test_importar_bloquea_si_hay_errores(repo_mock, lector_mock):
    reloj = RelojFijo(date(2026, 6, 1))
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Cuota")),
        FilaCrudaExcel(2, ("Rivadavia 3421", "Juan", "01/01/2026", "invalido")),
    )
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_mock, lector_mock, reloj)
    mapeo = {"direccion": 0, "nombre_inquilino": 1, "fecha_inicio": 2, "monto_inicial_centavos": 3}

    with pytest.raises(ErrorDeNegocio, match="hay 1 fila\\(s\\) con errores"):
        servicio.importar("archivo.xlsx", "Hoja1", 1, mapeo)


def test_importar_exitoso_envia_items_al_repositorio(repo_mock, lector_mock):
    reloj = RelojFijo(date(2026, 6, 1))
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Cuota")),
        FilaCrudaExcel(2, ("Rivadavia 3421", "Lucía", "01/01/2026", "380000")),
        FilaCrudaExcel(3, ("Mitre 100", None, None, None)),
    )
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)
    repo_mock.guardar_lote_importacion.return_value = (2, 1)

    servicio = ServicioImportacionDepartamentos(repo_mock, lector_mock, reloj)
    mapeo = {"direccion": 0, "nombre_inquilino": 1, "fecha_inicio": 2, "monto_inicial_centavos": 3}

    res = servicio.importar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert res.departamentos_creados == 2
    assert res.contratos_creados == 1

    # Verificamos los items pasados a guardar_lote_importacion
    assert repo_mock.guardar_lote_importacion.called
    items = repo_mock.guardar_lote_importacion.call_args[0][0]
    assert len(items) == 2

    # Item 1: con contrato
    assert items[0].departamento.direccion == "Rivadavia 3421"
    assert items[0].inquilino.nombre == "Lucía"
    assert items[0].contrato.fecha_fin is None  # Invariante ADR-0005 §1

    # Item 2: vacante
    assert items[1].departamento.direccion == "Mitre 100"
    assert items[1].inquilino is None
    assert items[1].contrato is None


def test_generar_plantilla(repo_mock, lector_mock):
    escritor_mock = MagicMock()
    servicio = ServicioImportacionDepartamentos(
        repo_mock, lector_mock, RelojFijo(date(2026, 6, 1)), escritor_mock
    )

    ruta = servicio.generar_plantilla("plantilla.xlsx")
    assert ruta == "plantilla.xlsx"
    assert escritor_mock.escribir.called
    libro = escritor_mock.escribir.call_args[0][1]
    assert len(libro.hojas) == 1
    hoja = libro.hojas[0]
    assert hoja.nombre == "Departamentos y Contratos"
    assert len(hoja.columnas) == 16
    assert len(hoja.filas) == 2
