"""Tests del lector de Excel openpyxl (infraestructura) para importación."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from brickly.dominio.errores import ErrorDeNegocio
from brickly.infraestructura.excel import LectorExcelOpenpyxl


def test_lector_rechaza_xls_legacy(tmp_path: Path):
    archivo_xls = tmp_path / "datos.xls"
    archivo_xls.write_bytes(b"dummy")

    lector = LectorExcelOpenpyxl()
    with pytest.raises(ErrorDeNegocio, match=r"\.xls no es compatible"):
        lector.listar_hojas(str(archivo_xls))


def test_lector_rechaza_archivo_inexistente(tmp_path: Path):
    lector = LectorExcelOpenpyxl()
    with pytest.raises(ErrorDeNegocio, match="no existe"):
        lector.listar_hojas(str(tmp_path / "inexistente.xlsx"))


def test_lector_lee_hoja_con_tipos_sin_float(tmp_path: Path):
    ruta = tmp_path / "prueba.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datos"

    # Fila 1: Encabezados
    ws.append(["Dirección", "Piso", "Monto", "Fecha", "Mora", "Fórmula"])

    # Fila 2: Datos
    ws.append([
        "Av. Rivadavia 3421",
        "3",
        380000.50,  # float en openpyxl
        date(2026, 1, 15),
        0.0015,  # 0.15% con formato porcentaje
        "=A2",
    ])
    ws.cell(row=2, column=5).number_format = "0.00%"

    wb.save(ruta)
    wb.close()

    lector = LectorExcelOpenpyxl()
    hojas = lector.listar_hojas(str(ruta))
    assert hojas == ["Datos"]

    hoja = lector.leer_hoja(str(ruta), "Datos")
    assert hoja.nombre == "Datos"
    assert len(hoja.filas) == 2

    fila_datos = hoja.filas[1]
    valores = fila_datos.valores

    assert valores[0] == "Av. Rivadavia 3421"
    assert valores[1] == "3"
    # Monto: se convirtió float a Decimal sin float en dominio/aplicación
    assert isinstance(valores[2], Decimal)
    assert valores[2] == Decimal("380000.5")
    # Fecha: date
    assert valores[3] == date(2026, 1, 15)
    # Mora: con formato %, se entregó como string porcentual
    assert valores[4] == "0.15%"


def test_lector_propaga_celdas_combinadas_verticalmente(tmp_path: Path):
    ruta = tmp_path / "combinadas.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active

    # Encabezados
    ws.append(["Dirección", "Depto", "Monto"])
    # Fila 2 y 3: Dirección combinada
    ws.append(["Mitre 500", "A", 100000])
    ws.append([None, "B", 120000])

    ws.merge_cells("A2:A3")
    wb.save(ruta)
    wb.close()

    lector = LectorExcelOpenpyxl()
    hoja = lector.leer_hoja(str(ruta))

    # Fila 2 y 3 deben tener "Mitre 500" en col 1
    assert hoja.filas[1].valores[0] == "Mitre 500"
    assert hoja.filas[1].tiene_celdas_combinadas is True

    assert hoja.filas[2].valores[0] == "Mitre 500"
    assert hoja.filas[2].tiene_celdas_combinadas is True
    assert hoja.filas[2].valores[1] == "B"
