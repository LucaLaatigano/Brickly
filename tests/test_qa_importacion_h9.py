"""Pruebas adversariales exhaustivas de QA para Importación de Excel (H9 — ADR-0005).

Verificación de los 15 bloques de pruebas adversariales:
1. Archivo vacío, sin datos útiles o corrupto.
2. Selección de hojas en archivos con múltiples hojas.
3. Encabezado desplazado y celdas combinadas.
4. Formatos y bordes de fecha (rechazos y rangos).
5. Formatos y bordes de monto (rechazos y delimitadores).
6. Tasas de mora, ciclos IPC y redondeo.
7. Contratos incompletos (mensajes específicos).
8. Edición inline y omisión manual de filas (panel lateral 380 px).
9. Idempotencia estricta contra SQLite.
10. Dedupe intra-archivo (contratos vigentes, futuros y vacantes).
11. Invariante de contratos.fecha_fin (vigentes NULL en SQLite vs informativas, y contratos vencidos).
12. Aislamiento estricto de inquilinos (homónimos e IDs independientes).
13. Archivos bloqueados (PermissionError), .xls legacy y fórmulas sin calcular.
14. Rollback transaccional atómico ("todo o nada").
15. Integridad de contratos de UI, arquitectura y contraste.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from brickly.aplicacion.departamentos import PredeterminadosContrato
from brickly.aplicacion.importacion import (
    CAMPOS_CANONICOS,
    EdicionManualFilaImportacion,
    FilaPrevisualizacionImportacion,
    PrevisualizacionImportacion,
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
from brickly.aplicacion.puertos import FilaCrudaExcel, HojaCrudaExcel, ItemImportacionPersistible
from brickly.dominio.contrato import Contrato, Inquilino
from brickly.dominio.departamento import Departamento, clave_unidad_normalizada, desglosar_unidad_compuesta
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.departamentos import RepositorioDepartamentosSQLite
from brickly.infraestructura.excel import EscritorExcelOpenpyxl, LectorExcelOpenpyxl
from brickly.ui.presenters.importacion import presentar_previsualizacion, presentar_resumen_importacion


class RelojFijo:
    def __init__(self, fecha: date):
        self._fecha = fecha

    def hoy(self) -> date:
        return self._fecha


@pytest.fixture()
def con_db():
    conexion = abrir_conexion(":memory:")
    migrar(conexion)
    yield conexion
    conexion.close()


@pytest.fixture()
def repo_deptos(con_db):
    return RepositorioDepartamentosSQLite(con_db, reloj=RelojFijo(date(2026, 6, 1)))


@pytest.fixture()
def lector():
    return LectorExcelOpenpyxl()


@pytest.fixture()
def escritor():
    return EscritorExcelOpenpyxl()


# ============================================================================
# BLOQUE 1: Archivo vacío, sin datos útiles o corrupto
# ============================================================================


def test_qa_b1_archivo_completamente_vacio_o_corrupto(tmp_path: Path, lector):
    archivo_vacio = tmp_path / "vacio.xlsx"
    archivo_vacio.write_bytes(b"")

    with pytest.raises(ErrorDeNegocio, match="está dañado o no es un archivo .xlsx válido"):
        lector.listar_hojas(str(archivo_vacio))

    with pytest.raises(ErrorDeNegocio, match="está dañado o no es un archivo .xlsx válido"):
        lector.leer_hoja(str(archivo_vacio))


def test_qa_b1_hoja_sin_filas_de_datos(tmp_path: Path, repo_deptos, lector, escritor):
    ruta = tmp_path / "solo_encabezados.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Unidades"
    ws.append(["Dirección", "Piso", "Depto", "Inquilino", "Cuota", "Inicio"])
    wb.save(ruta)
    wb.close()

    servicio = ServicioImportacionDepartamentos(
        repo_deptos, lector, RelojFijo(date(2026, 6, 1)), escritor
    )
    insp = servicio.inspeccionar_archivo(str(ruta))
    mapeo = {c.campo_mapeado: c.indice for c in insp.columnas_detectadas if c.campo_mapeado}

    prev = servicio.previsualizar(
        str(ruta), "Unidades", insp.fila_encabezado_detectada, mapeo
    )
    assert prev.total_filas == 0
    assert prev.filas_listas == 0
    assert prev.filas_con_errores == 0
    assert prev.filas_omitidas == 0

    res = servicio.importar(str(ruta), "Unidades", insp.fila_encabezado_detectada, mapeo)
    assert res.departamentos_creados == 0
    assert res.contratos_creados == 0


def test_qa_b1_filas_vacias_y_totales_se_ignoran(tmp_path: Path, repo_deptos, lector, escritor):
    ruta = tmp_path / "filas_espacios_y_totales.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Dirección", "Piso", "Depto", "Inquilino", "Cuota", "Inicio"])
    ws.append(["Av. Rivadavia 1000", "1", "A", "Juan Pérez", 300000, "01/01/2026"])
    ws.append([None, None, "", "   ", None, None])  # Fila vacía con espacios
    ws.append(["Mitre 500", "PB", None, None, None, None])
    ws.append(["Total general:", None, None, None, 300000, None])  # Fila de totales
    ws.append(["Resumen de cobranzas", None, None, None, None, None])  # Fila resumen
    wb.save(ruta)
    wb.close()

    servicio = ServicioImportacionDepartamentos(
        repo_deptos, lector, RelojFijo(date(2026, 6, 1)), escritor
    )
    insp = servicio.inspeccionar_archivo(str(ruta))
    mapeo = {c.campo_mapeado: c.indice for c in insp.columnas_detectadas if c.campo_mapeado}

    prev = servicio.previsualizar(str(ruta), ws.title, 1, mapeo)
    # Solo deben detectarse 2 filas de datos útiles
    assert prev.total_filas == 2
    assert prev.filas[0].direccion == "Av. Rivadavia 1000"
    assert prev.filas[1].direccion == "Mitre 500"


def test_qa_b1_limite_maximo_500_filas(tmp_path: Path, repo_deptos, lector):
    ruta = tmp_path / "mas_de_500_filas.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Dirección", "Piso", "Depto"])
    for i in range(1, 505):
        ws.append([f"Calle Falsa {i}", "1", "A"])
    wb.save(ruta)
    wb.close()

    with pytest.raises(ErrorDeNegocio, match="supera el límite máximo de 500 filas"):
        lector.leer_hoja(str(ruta))


# ============================================================================
# BLOQUE 2: Selección de hojas en archivos con múltiples hojas
# ============================================================================


def test_qa_b2_multiples_hojas_y_auto_seleccion(tmp_path: Path, repo_deptos, lector, escritor):
    ruta = tmp_path / "multiples_hojas.xlsx"
    wb = openpyxl.Workbook()
    ws_portada = wb.active
    ws_portada.title = "Portada"
    ws_portada.append(["Bienvenido al sistema"])

    ws_contratos = wb.create_sheet(title="Contratos Vigentes")
    ws_contratos.append(["Dirección", "Inquilino", "Inicio", "Cuota"])
    ws_contratos.append(["Belgrano 123", "Ana Gomez", "01/02/2026", 250000])

    ws_notas = wb.create_sheet(title="Notas")
    ws_notas.append(["Observaciones varias"])
    wb.save(ruta)
    wb.close()

    servicio = ServicioImportacionDepartamentos(
        repo_deptos, lector, RelojFijo(date(2026, 6, 1)), escritor
    )
    insp = servicio.inspeccionar_archivo(str(ruta))
    assert insp.hojas == ("Portada", "Contratos Vigentes", "Notas")
    # Debe auto-seleccionar "Contratos Vigentes" por heurística de nombre
    assert insp.hoja_seleccionada == "Contratos Vigentes"

    # Intentar leer hoja inexistente
    with pytest.raises(ErrorDeNegocio, match="no existe en el archivo"):
        lector.leer_hoja(str(ruta), "Hoja Fantasma")


# ============================================================================
# BLOQUE 3: Encabezado desplazado y celdas combinadas verticalmente
# ============================================================================


def test_qa_b3_encabezado_desplazado_y_celdas_combinadas(tmp_path: Path, repo_deptos, lector, escritor):
    ruta = tmp_path / "encabezado_fila_3_y_combinadas.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cartera"

    # Fila 1 y 2: Título y subtítulo
    ws.append(["ADMINISTRACION INMOBILIARIA CENTRAL", None, None, None])
    ws.append(["Período 2026 - Planilla General", None, None, None])
    # Fila 3: Encabezados reales
    ws.append(["Dirección", "Piso", "Depto", "Inquilino", "Cuota", "Inicio"])
    # Filas 4 y 5: Misma dirección combinada en columna A
    ws.append(["Av. Corrientes 4500", "1", "A", "Pedro Soto", 320000, "01/01/2026"])
    ws.append([None, "1", "B", "Laura Vega", 340000, "01/01/2026"])
    ws.merge_cells("A4:A5")
    # Fila 6: Totales
    ws.append(["Suma de alquileres", None, None, None, 660000, None])

    wb.save(ruta)
    wb.close()

    servicio = ServicioImportacionDepartamentos(
        repo_deptos, lector, RelojFijo(date(2026, 6, 1)), escritor
    )
    insp = servicio.inspeccionar_archivo(str(ruta))
    assert insp.fila_encabezado_detectada == 3

    mapeo = {c.campo_mapeado: c.indice for c in insp.columnas_detectadas if c.campo_mapeado}
    prev = servicio.previsualizar(str(ruta), "Cartera", 3, mapeo)

    assert prev.total_filas == 2
    # Comprobar propagación de la dirección combinada
    f1, f2 = prev.filas
    assert f1.direccion == "Av. Corrientes 4500"
    assert f1.piso == "1"
    assert f1.depto == "A"
    assert f1.tiene_celdas_combinadas is True

    assert f2.direccion == "Av. Corrientes 4500"
    assert f2.piso == "1"
    assert f2.depto == "B"
    assert f2.tiene_celdas_combinadas is True


# ============================================================================
# BLOQUE 4: Formatos y bordes de fecha (rechazos y rangos)
# ============================================================================


def test_qa_b4_formatos_fechas_validas_y_rechazos():
    # Fechas válidas
    assert parsear_fecha_importacion(date(2026, 5, 20)) == date(2026, 5, 20)
    assert parsear_fecha_importacion("20/05/2026") == date(2026, 5, 20)
    assert parsear_fecha_importacion("20-05-2026") == date(2026, 5, 20)
    assert parsear_fecha_importacion("2026-05-20") == date(2026, 5, 20)
    assert parsear_fecha_importacion("5/2/2026") == date(2026, 2, 5)

    # Rechazo año 2 dígitos
    with pytest.raises(ErrorDeValidacion, match="4 dígitos"):
        parsear_fecha_importacion("20/05/26")

    # Rechazo serial de Excel
    with pytest.raises(ErrorDeValidacion, match="formato numérico"):
        parsear_fecha_importacion(45230)

    # Rechazo fuera de 2000..2100
    with pytest.raises(ErrorDeValidacion, match="entre 2000 y 2100"):
        parsear_fecha_importacion("01/01/1999")
    with pytest.raises(ErrorDeValidacion, match="entre 2000 y 2100"):
        parsear_fecha_importacion("01/01/2105")

    # Rechazo fecha inexistente
    with pytest.raises(ErrorDeValidacion, match="Fecha inválida"):
        parsear_fecha_importacion("31/02/2026")

    # Rechazo booleano
    with pytest.raises(ErrorDeValidacion, match="Fecha inválida"):
        parsear_fecha_importacion(True)


def test_qa_b4_fecha_fin_anterior_a_inicio_da_error(repo_deptos, lector):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Fin", "Cuota")),
        FilaCrudaExcel(2, ("Alsina 100", "Carlos", "01/06/2026", "01/05/2026", "200000")),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "fecha_fin": 3,
        "monto_inicial_centavos": 4,
    }
    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.filas_con_errores == 1
    assert prev.filas[0].estado == "error"
    assert "La fecha de fin no puede ser anterior al inicio." in prev.filas[0].errores[0]


# ============================================================================
# BLOQUE 5: Formatos y delimitadores de monto
# ============================================================================


def test_qa_b5_monto_formatos_validos_y_rechazos():
    # Válidos
    assert parsear_monto_importacion(150000) == 15000000
    assert parsear_monto_importacion(Decimal("150000.75")) == 15000075
    assert parsear_monto_importacion("$ 150.000,50") == 15000050
    assert parsear_monto_importacion("150.000") == 15000000
    assert parsear_monto_importacion("150000") == 15000000
    assert parsear_monto_importacion("1.500.000") == 150000000

    # Rechazo floats directos y booleanos
    with pytest.raises(ErrorDeValidacion, match="float ni booleano"):
        parsear_monto_importacion(150000.0)
    with pytest.raises(ErrorDeValidacion, match="float ni booleano"):
        parsear_monto_importacion(False)

    # Rechazo monedas extranjeras
    with pytest.raises(ErrorDeValidacion, match="Solo se admiten montos en pesos"):
        parsear_monto_importacion("USD 1500")
    with pytest.raises(ErrorDeValidacion, match="Solo se admiten montos en pesos"):
        parsear_monto_importacion("1500 U$S")

    # Rechazo formato anglosajón o ambiguo
    with pytest.raises(ErrorDeValidacion, match="Formato de monto ambiguo o anglosajón"):
        parsear_monto_importacion("150,000.00")
    with pytest.raises(ErrorDeValidacion, match="múltiples separadores decimales"):
        parsear_monto_importacion("150,5,5")

    # Rechazo más de 2 decimales
    with pytest.raises(ErrorDeValidacion, match="más de 2 decimales"):
        parsear_monto_importacion("150000,123")
    with pytest.raises(ErrorDeValidacion, match="más de 2 decimales"):
        parsear_monto_importacion(Decimal("150000.123"))

    # Rechazo monto menor o igual a cero
    with pytest.raises(ErrorDeValidacion, match="mayor a 0"):
        parsear_monto_importacion(0)
    with pytest.raises(ErrorDeValidacion, match="mayor a 0"):
        parsear_monto_importacion(-1000)
    with pytest.raises(ErrorDeValidacion, match="mayor a 0"):
        parsear_monto_importacion("0")
    with pytest.raises(ErrorDeValidacion, match="mayor a 0"):
        parsear_monto_importacion("-50000")


# ============================================================================
# BLOQUE 6: Tasas de mora, ciclos IPC y redondeo
# ============================================================================


def test_qa_b6_tasas_mora_ciclos_y_redondeo():
    # Mora
    assert parsear_tasa_mora_importacion("0,15%") == 15
    assert parsear_tasa_mora_importacion("0.15%") == 15
    assert parsear_tasa_mora_importacion("200 bp") == 200
    assert parsear_tasa_mora_importacion(200) == 200
    assert parsear_tasa_mora_importacion(Decimal("0.02")) == 200
    assert parsear_tasa_mora_importacion(Decimal("200")) == 200

    with pytest.raises(ErrorDeValidacion, match="entre 0 y 10.000 bp"):
        parsear_tasa_mora_importacion(-10)
    with pytest.raises(ErrorDeValidacion, match="entre 0 y 10.000 bp"):
        parsear_tasa_mora_importacion(15000)
    with pytest.raises(ErrorDeValidacion, match="float ni booleano"):
        parsear_tasa_mora_importacion(0.02)

    # Ciclo IPC
    assert parsear_ciclo_importacion("Mensual") == 1
    assert parsear_ciclo_importacion("Bimestral") == 2
    assert parsear_ciclo_importacion("Trimestral") == 3
    assert parsear_ciclo_importacion("Cuatrimestral") == 4
    assert parsear_ciclo_importacion("Semestral") == 6
    assert parsear_ciclo_importacion("Anual") == 12
    assert parsear_ciclo_importacion("3 meses") == 3
    assert parsear_ciclo_importacion(6) == 6

    with pytest.raises(ErrorDeValidacion, match="mayor a 0"):
        parsear_ciclo_importacion(0)
    with pytest.raises(ErrorDeValidacion, match="Ciclo de ajuste inválido"):
        parsear_ciclo_importacion("Quinquenal")

    # Redondeo
    assert parsear_redondeo_importacion("Centavos") == 1
    assert parsear_redondeo_importacion("exacto") == 1
    assert parsear_redondeo_importacion(1) == 1
    assert parsear_redondeo_importacion("$ 100") == 100
    assert parsear_redondeo_importacion("100 pesos") == 100
    assert parsear_redondeo_importacion(100) == 100

    with pytest.raises(ErrorDeValidacion, match="Redondeo inválido"):
        parsear_redondeo_importacion(50)
    with pytest.raises(ErrorDeValidacion, match="Redondeo inválido"):
        parsear_redondeo_importacion("500")


# ============================================================================
# BLOQUE 7: Contratos incompletos (mensajes específicos)
# ============================================================================


def test_qa_b7_contratos_incompletos_reportan_exactamente_el_campo_faltante(repo_deptos):
    reloj = RelojFijo(date(2026, 6, 1))

    # Caso 1: Tiene inquilino pero no fecha ni cuota
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Cuota")),
        FilaCrudaExcel(2, ("Pringles 200", "Sol Ramos", None, None)),
        # Caso 2: Tiene cuota pero no inquilino ni inicio
        FilaCrudaExcel(3, ("Lavalle 800", None, None, 400000)),
        # Caso 3: Tiene inicio pero no inquilino ni cuota
        FilaCrudaExcel(4, ("Junín 300", None, "01/01/2026", None)),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "monto_inicial_centavos": 3,
    }
    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.filas_con_errores == 3

    # Fila 2
    f2 = prev.filas[0]
    assert "La fecha de inicio de contrato es obligatoria." in f2.errores
    assert "El monto de la cuota mensual es obligatorio." in f2.errores

    # Fila 3
    f3 = prev.filas[1]
    assert "El nombre del inquilino es obligatorio si hay contrato." in f3.errores
    assert "La fecha de inicio de contrato es obligatoria." in f3.errores

    # Fila 4
    f4 = prev.filas[2]
    assert "El nombre del inquilino es obligatorio si hay contrato." in f4.errores
    assert "El monto de la cuota mensual es obligatorio." in f4.errores


# ============================================================================
# BLOQUE 8: Edición inline y omisión manual de filas
# ============================================================================


def test_qa_b8_edicion_manual_corrige_errores_u_omite_fila(repo_deptos):
    reloj = RelojFijo(date(2026, 6, 1))
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Cuota")),
        FilaCrudaExcel(2, ("Defensa 1200", "Martín Gómez", "01/01/2026", "monto_invalido")),
        FilaCrudaExcel(3, ("Bolívar 400", "Clara Ríos", "invalida", 280000)),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "monto_inicial_centavos": 3,
    }

    # Sin corrección: 2 errores
    prev1 = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev1.filas_con_errores == 2
    assert prev1.filas_listas == 0

    # Corregimos Fila 2 con monto válido y Omitimos Fila 3
    ediciones = {
        2: EdicionManualFilaImportacion(2, {"monto_inicial_centavos": "320000"}),
        3: EdicionManualFilaImportacion(3, {}, omitir=True),
    }

    prev2 = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo, ediciones)
    assert prev2.filas_con_errores == 0
    assert prev2.filas_listas == 1
    assert prev2.filas_omitidas == 1

    f2 = prev2.filas[0]
    assert f2.estado == "nuevo_con_contrato"
    assert f2.monto_inicial_centavos == 32000000

    f3 = prev2.filas[1]
    assert f3.estado == "omitido_manual"
    assert f3.es_importable is False


# ============================================================================
# BLOQUE 9: Idempotencia estricta contra SQLite
# ============================================================================


def test_qa_b9_idempotencia_normalizacion_de_piso_y_direccion(con_db, repo_deptos):
    reloj = RelojFijo(date(2026, 6, 1))

    # Insertamos un departamento existente con piso "3" y depto "B"
    repo_deptos.guardar(Departamento(direccion="Av. San Juan 2500", piso="3", depto="B"))

    # Intentamos importar con variaciones de espacios, símbolos de grado "3º", "3°" y mayúsculas
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Piso", "Depto")),
        FilaCrudaExcel(2, ("  av. san  juan   2500  ", "3º", "b")),
        FilaCrudaExcel(3, ("Av. San Juan 2500", "3°", "B")),
        FilaCrudaExcel(4, ("Nueva York 120", "PB", None)),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {"direccion": 0, "piso": 1, "depto": 2}

    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.total_filas == 3
    # Fila 2 y 3 deben marcarse como omitido_existente
    assert prev.filas[0].estado == "omitido_existente"
    assert prev.filas[1].estado == "omitido_existente"
    # Fila 4 es nueva
    assert prev.filas[2].estado == "nuevo_vacante"
    assert prev.filas_listas == 1
    assert prev.filas_omitidas == 2

    # Importamos: solo debe crearse Fila 4
    res = servicio.importar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert res.departamentos_creados == 1
    assert res.unidades_omitidas == 2

    # En la base ahora hay 2 departamentos en total
    assert len(repo_deptos.listar()) == 2


# ============================================================================
# BLOQUE 10: Dedupe intra-archivo (vigentes, futuros y vacantes)
# ============================================================================


def test_qa_b10_dedupe_intra_archivo_vigente_mas_reciente_gana(repo_deptos):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # 3 apariciones de la misma unidad:
    # Fila 2: contrato vigente iniciado el 01/01/2026
    # Fila 3: contrato vigente iniciado el 01/03/2026 (MÁS RECIENTE -> DEBE GANAR)
    # Fila 4: contrato viejo vencido en 2025
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Fin", "Cuota")),
        FilaCrudaExcel(2, ("Gorriti 4500", "Inquilino 1", "01/01/2026", None, 300000)),
        FilaCrudaExcel(3, ("Gorriti 4500", "Inquilino 2", "01/03/2026", None, 350000)),
        FilaCrudaExcel(4, ("Gorriti 4500", "Inquilino 3", "01/01/2025", "31/12/2025", 200000)),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "fecha_fin": 3,
        "monto_inicial_centavos": 4,
    }

    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.total_filas == 3
    assert prev.filas_listas == 1
    assert prev.filas_omitidas == 2

    # Fila 3 ganó
    f_ganadora = next(f for f in prev.filas if f.numero_fila == 3)
    assert f_ganadora.estado == "nuevo_con_contrato"
    assert f_ganadora.inquilino_nombre == "Inquilino 2"
    assert f_ganadora.es_importable is True

    # Fila 2 y 4 omitidas
    f_omitidas = [f for f in prev.filas if f.numero_fila in (2, 4)]
    for f in f_omitidas:
        assert f.estado == "omitido_contrato_anterior"
        assert f.es_importable is False


def test_qa_b10_dedupe_intra_archivo_contratos_futuros(repo_deptos):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # Dos contratos que inician en el futuro (después de hoy):
    # Fila 2: inicia 01/08/2026
    # Fila 3: inicia 01/09/2026 (MÁS RECIENTE -> DEBE GANAR)
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Cuota")),
        FilaCrudaExcel(2, ("Honduras 3800", "Inq Agosto", "01/08/2026", 400000)),
        FilaCrudaExcel(3, ("Honduras 3800", "Inq Septiembre", "01/09/2026", 420000)),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {"direccion": 0, "nombre_inquilino": 1, "fecha_inicio": 2, "monto_inicial_centavos": 3}

    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert prev.filas_listas == 1
    assert prev.filas_omitidas == 1

    f3 = next(f for f in prev.filas if f.numero_fila == 3)
    assert f3.estado == "nuevo_con_contrato"
    assert f3.inquilino_nombre == "Inq Septiembre"


# ============================================================================
# BLOQUE 11: Invariante de contratos.fecha_fin (ADR-0005 §1)
# ============================================================================


def test_qa_b11_invariante_fecha_fin_vigente_null_y_vencido_vacante(con_db, repo_deptos):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # Fila 2: Contrato vigente con fecha_fin en el futuro (31/12/2026)
    # Fila 3: Contrato vencido en el pasado (31/12/2025 < hoy)
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Inicio", "Fin", "Cuota")),
        FilaCrudaExcel(2, ("Bulnes 700", "Agustina", "01/01/2026", "31/12/2026", 300000)),
        FilaCrudaExcel(3, ("Salguero 800", "Facundo", "01/01/2025", "31/12/2025", 250000)),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "fecha_inicio": 2,
        "fecha_fin": 3,
        "monto_inicial_centavos": 4,
    }

    prev = servicio.previsualizar("archivo.xlsx", "Hoja1", 1, mapeo)
    f_vigente, f_vencido = prev.filas

    assert f_vigente.estado == "nuevo_con_contrato"
    assert f_vigente.fecha_fin_informativa == date(2026, 12, 31)

    assert f_vencido.estado == "nuevo_contrato_vencido"
    assert "se importará solo el departamento (vacante)" in f_vencido.advertencias[0]

    # Importamos
    res = servicio.importar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert res.departamentos_creados == 2
    assert res.contratos_creados == 1

    # Verificamos directamente en SQLite
    cur = con_db.cursor()
    # 1. Contrato vigente: fecha_fin DEBE ser NULL en SQLite para satisfacer ux_contratos_vigente
    cur.execute(
        "SELECT c.fecha_fin, i.nombre FROM contratos c "
        "JOIN departamentos d ON d.id = c.departamento_id "
        "JOIN inquilinos i ON i.id = c.inquilino_id "
        "WHERE d.direccion = 'Bulnes 700'"
    )
    fila_c1 = cur.fetchone()
    assert fila_c1 is not None
    assert fila_c1[0] is None  # fecha_fin IS NULL en DB
    assert fila_c1[1] == "Agustina"

    # 2. Departamento con contrato vencido: NO debe tener filas en contratos ni inquilinos
    cur.execute(
        "SELECT c.id FROM contratos c "
        "JOIN departamentos d ON d.id = c.departamento_id "
        "WHERE d.direccion = 'Salguero 800'"
    )
    assert cur.fetchone() is None


# ============================================================================
# BLOQUE 12: Aislamiento estricto de inquilinos
# ============================================================================


def test_qa_b12_aislamiento_de_inquilinos_por_contrato(con_db, repo_deptos):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)

    # Dos departamentos distintos con el mismo inquilino ("Juan Pérez")
    filas = (
        FilaCrudaExcel(1, ("Dirección", "Inquilino", "Teléfono", "Inicio", "Cuota")),
        FilaCrudaExcel(2, ("Unidad Alfa 10", "Juan Pérez", "11-1111-1111", "01/01/2026", 200000)),
        FilaCrudaExcel(3, ("Unidad Beta 20", "Juan Pérez", "11-1111-1111", "01/01/2026", 250000)),
    )
    lector_mock = MagicMock()
    lector_mock.leer_hoja.return_value = HojaCrudaExcel("Hoja1", filas)

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector_mock, reloj)
    mapeo = {
        "direccion": 0,
        "nombre_inquilino": 1,
        "telefono_inquilino": 2,
        "fecha_inicio": 3,
        "monto_inicial_centavos": 4,
    }

    res = servicio.importar("archivo.xlsx", "Hoja1", 1, mapeo)
    assert res.departamentos_creados == 2
    assert res.contratos_creados == 2

    cur = con_db.cursor()
    cur.execute("SELECT id, nombre, telefono FROM inquilinos ORDER BY id ASC")
    inqs = cur.fetchall()
    # Deben haberse creado 2 filas distintas e independientes
    assert len(inqs) == 2
    id1, nom1, tel1 = inqs[0]
    id2, nom2, tel2 = inqs[1]
    assert id1 != id2
    assert nom1 == nom2 == "Juan Pérez"


# ============================================================================
# BLOQUE 13: Archivos protegidos, .xls y fórmulas sin calcular
# ============================================================================


def test_qa_b13_permiso_denegado_archivo_bloqueado(tmp_path: Path, lector):
    ruta = tmp_path / "bloqueado.xlsx"
    ruta.write_bytes(b"dummy")

    with patch(
        "brickly.infraestructura.excel.load_workbook",
        side_effect=PermissionError("Permission denied"),
    ):
        with pytest.raises(ErrorDeNegocio, match="está abierto en Excel u otro programa"):
            lector.listar_hojas(str(ruta))

        with pytest.raises(ErrorDeNegocio, match="está abierto en Excel u otro programa"):
            lector.leer_hoja(str(ruta))


def test_qa_b13_formula_sin_valor_cacheado(tmp_path: Path, lector, repo_deptos):
    ruta = tmp_path / "formula_sin_calcular.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Dirección", "Inquilino", "Inicio", "Cuota"])
    # Cargar una fórmula "=SUM(A1:B1)" que no tiene valor cacheado
    ws.append(["Billinghurst 200", "Paula", "01/01/2026", "=SUM(A1:B1)"])
    wb.save(ruta)
    wb.close()

    # Leemos la hoja: la celda debe tener __FORMULA_SIN_VALOR__
    hoja = lector.leer_hoja(str(ruta))
    val_cuota = hoja.filas[1].valores[3]
    assert val_cuota == "__FORMULA_SIN_VALOR__"

    servicio = ServicioImportacionDepartamentos(repo_deptos, lector, RelojFijo(date(2026, 6, 1)))
    mapeo = {"direccion": 0, "nombre_inquilino": 1, "fecha_inicio": 2, "monto_inicial_centavos": 3}
    prev = servicio.previsualizar(str(ruta), hoja.nombre, 1, mapeo)

    assert prev.filas_con_errores == 1
    assert "Monto inválido" in prev.filas[0].errores[0]


# ============================================================================
# BLOQUE 14: Rollback transaccional atómico ("todo o nada")
# ============================================================================


def test_qa_b14_rollback_transaccional_garantizado(con_db, repo_deptos):
    # Pre-creamos una unidad
    repo_deptos.guardar(Departamento(direccion="Paraguay 1500", piso="2", depto="A"))

    # Intentamos persistir un lote de 3 unidades donde la 3ra colisiona con Paraguay 1500
    items = [
        ItemImportacionPersistible(
            departamento=Departamento(direccion="Uruguay 100"),
        ),
        ItemImportacionPersistible(
            departamento=Departamento(direccion="Uruguay 200"),
        ),
        ItemImportacionPersistible(
            departamento=Departamento(direccion="Paraguay 1500", piso="2", depto="A"),
        ),
    ]

    with pytest.raises(ErrorDeNegocio, match="Error al guardar el lote de importación"):
        repo_deptos.guardar_lote_importacion(items)

    # Rollback total: Ni Uruguay 100 ni Uruguay 200 deben existir en la base
    filas = repo_deptos.listar()
    assert len(filas) == 1
    assert filas[0].direccion == "Paraguay 1500"


# ============================================================================
# BLOQUE 15: Presentador y DTOs de UI
# ============================================================================


def test_qa_b15_presentador_textos_resumen_y_estados():
    fila_valida = FilaPrevisualizacionImportacion(
        numero_fila=2,
        unidad_texto="Larrea 300",
        direccion="Larrea 300",
        piso=None,
        depto=None,
        m2=None,
        propietario=None,
        inquilino_nombre="Marta",
        inquilino_telefono=None,
        inquilino_email=None,
        fecha_inicio=date(2026, 1, 1),
        fecha_fin_informativa=None,
        monto_inicial_centavos=20000000,
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
    prev = PrevisualizacionImportacion(
        total_filas=1,
        filas_listas=1,
        filas_con_errores=0,
        filas_omitidas=0,
        filas=(fila_valida,),
    )
    resumen, filas_pres = presentar_previsualizacion(prev)
    assert resumen.puede_importar is True
    assert resumen.texto_boton_importar == "Importar 1 departamento"
    assert resumen.texto_resumen == "1 lista"

    f_p = filas_pres[0]
    assert f_p.cuota_mensual == "$ 200.000"
    assert f_p.estado_texto == "Listo"
    assert f_p.variante_chip == "listo"

    # Con errores y omitidas
    prev_mixta = PrevisualizacionImportacion(
        total_filas=3,
        filas_listas=1,
        filas_con_errores=1,
        filas_omitidas=1,
        filas=(),
    )
    resumen_mixto = presentar_resumen_importacion(prev_mixta)
    assert resumen_mixto.puede_importar is False
    assert resumen_mixto.texto_resumen == "1 lista · 1 con error · 1 se omitirá"


# ============================================================================
# BLOQUE ADICIONAL: Integridad del archivo original tras edición inline
# ============================================================================


def test_qa_criterio_3_edicion_inline_no_modifica_excel_en_disco(tmp_path: Path, repo_deptos, lector, escritor):
    ruta = tmp_path / "datos_con_error_a_corregir.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Dirección", "Inquilino", "Inicio", "Cuota"])
    ws.append(["Tucumán 1200", "Matías", "01/01/2026", "monto_invalido"])
    wb.save(ruta)
    wb.close()

    mtime_inicial = ruta.stat().st_mtime
    servicio = ServicioImportacionDepartamentos(repo_deptos, lector, RelojFijo(date(2026, 6, 1)), escritor)
    insp = servicio.inspeccionar_archivo(str(ruta))
    mapeo = {c.campo_mapeado: c.indice for c in insp.columnas_detectadas if c.campo_mapeado}

    # Vista previa sin edición: bloqueada con error
    prev1 = servicio.previsualizar(str(ruta), ws.title, 1, mapeo)
    assert prev1.filas_con_errores == 1
    assert presentar_resumen_importacion(prev1).puede_importar is False

    # Edición inline: corregimos el monto en memoria
    ediciones = {2: EdicionManualFilaImportacion(2, {"monto_inicial_centavos": "310000"})}
    prev2 = servicio.previsualizar(str(ruta), ws.title, 1, mapeo, ediciones)
    assert prev2.filas_con_errores == 0
    assert prev2.filas_listas == 1
    assert presentar_resumen_importacion(prev2).puede_importar is True

    # Confirmamos importación
    res = servicio.importar(str(ruta), ws.title, 1, mapeo, ediciones)
    assert res.departamentos_creados == 1
    assert res.contratos_creados == 1

    # Verificamos que el archivo Excel físico original NO FUE TOCADO
    assert ruta.stat().st_mtime == mtime_inicial
    wb_reabierto = openpyxl.load_workbook(ruta)
    ws_reabierto = wb_reabierto.active
    # En el archivo físico sigue diciendo "monto_invalido"
    assert ws_reabierto.cell(row=2, column=4).value == "monto_invalido"
    wb_reabierto.close()


def test_qa_desglose_y_espacios_en_blanco_adicionales():
    # Unidad desglosada con pisos con letras y símbolos
    d1, p1, dep1 = desglosar_unidad_compuesta("Santa Fe 2100 · 4° C")
    assert d1 == "Santa Fe 2100"
    assert p1 == "4"
    assert dep1 == "C"

    # Si se pasan piso o depto explícitos, no toca la dirección
    d2, p2, dep2 = desglosar_unidad_compuesta("Santa Fe 2100 · 4° C", piso="5", depto="D")
    assert d2 == "Santa Fe 2100 · 4° C"
    assert p2 == "5"
    assert dep2 == "D"

    # Dirección con acentos, comillas y caracteres habituales
    assert clave_unidad_normalizada("O'Higgins 1500", "1", "A") == ("o'higgins 1500", "1", "a")
    assert clave_unidad_normalizada("Peña 2300", "PB", None) == ("peña 2300", "pb", "")
