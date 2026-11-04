"""Adaptador `openpyxl` — implementa `EscritorExcel` (H7).

Recibe un `LibroExportable` ya calculado en centavos enteros desde `aplicacion`
y solo formatea las hojas `.xlsx`: encabezados en negrita, autofiltro, panel
congelado (`A2`), fechas `dd/mm/aaaa`, montos en pesos (`Decimal(centavos)/100`
sin floats), fila de totales en negrita y filas vencidas resaltadas.

La escritura es atómica (archivo temporal + `os.replace`) para no dejar un
`.xlsx` truncado si falla a mitad de camino, y traduce `PermissionError` a un
mensaje claro en castellano cuando el archivo está abierto en Excel.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from brickly.aplicacion.informes import (
    ColumnaExcel,
    HojaExportable,
    LibroExportable,
    ValorCeldaExcel,
    sanitizar_texto_excel,
)

FORMATO_MONEDA_EXCEL = '$ #,##0.00;-$ #,##0.00;"$ 0.00"'
FORMATO_FECHA_EXCEL = "dd/mm/yyyy"
FORMATO_ENTERO_EXCEL = "#,##0"

COLOR_ENCABEZADO_FONDO = "F3F4F6"
COLOR_TOTALES_FONDO = "F9FAFB"
COLOR_VENCIDA_FONDO = "FEE2E2"
COLOR_VENCIDA_TEXTO = "991B1B"
COLOR_TEXTO = "111827"
COLOR_BORDE = "D1D5DB"

_FUENTE_ENCABEZADO = Font(bold=True, color=COLOR_TEXTO)
_FUENTE_NORMAL = Font(bold=False, color=COLOR_TEXTO)
_FUENTE_VENCIDA = Font(bold=False, color=COLOR_VENCIDA_TEXTO)
_FUENTE_TOTALES = Font(bold=True, color=COLOR_TEXTO)

_RELLENO_ENCABEZADO = PatternFill(
    fill_type="solid",
    start_color=COLOR_ENCABEZADO_FONDO,
    end_color=COLOR_ENCABEZADO_FONDO,
)
_RELLENO_VENCIDA = PatternFill(
    fill_type="solid",
    start_color=COLOR_VENCIDA_FONDO,
    end_color=COLOR_VENCIDA_FONDO,
)
_RELLENO_TOTALES = PatternFill(
    fill_type="solid",
    start_color=COLOR_TOTALES_FONDO,
    end_color=COLOR_TOTALES_FONDO,
)

_BORDE_ENCABEZADO = Border(
    bottom=Side(style="thin", color=COLOR_BORDE),
)
_BORDE_TOTALES = Border(
    top=Side(style="thin", color=COLOR_BORDE),
    bottom=Side(style="double", color=COLOR_TEXTO),
)

_ALINEACION_POR_TIPO = {
    "texto": Alignment(horizontal="left", vertical="center"),
    "fecha": Alignment(horizontal="center", vertical="center"),
    "moneda": Alignment(horizontal="right", vertical="center"),
    "entero": Alignment(horizontal="right", vertical="center"),
}

_CIEN = Decimal(100)


def construir_workbook(libro: LibroExportable) -> Workbook:
    """Convierte un `LibroExportable` puro en un `openpyxl.Workbook`."""
    wb = Workbook()
    hoja_inicial = wb.active

    for indice, hoja in enumerate(libro.hojas):
        if indice == 0 and hoja_inicial is not None:
            ws = hoja_inicial
            ws.title = hoja.nombre
        else:
            ws = wb.create_sheet(title=hoja.nombre)
        _poblar_hoja(ws, hoja)

    return wb


def _poblar_hoja(ws: Worksheet, hoja: HojaExportable) -> None:
    anchos = [len(col.titulo) for col in hoja.columnas]

    # 1. Encabezados en fila 1
    for col_idx, columna in enumerate(hoja.columnas, start=1):
        celda = ws.cell(row=1, column=col_idx, value=columna.titulo)
        celda.font = _FUENTE_ENCABEZADO
        celda.fill = _RELLENO_ENCABEZADO
        celda.border = _BORDE_ENCABEZADO
        celda.alignment = _ALINEACION_POR_TIPO.get(
            columna.tipo, _ALINEACION_POR_TIPO["texto"]
        )

    # 2. Panel congelado y autofiltro (sobre encabezados + datos, sin fila de totales)
    ws.freeze_panes = "A2"
    ultima_columna = get_column_letter(max(1, len(hoja.columnas)))
    ultima_fila_datos = 1 + len(hoja.filas)
    ws.auto_filter.ref = f"A1:{ultima_columna}{ultima_fila_datos}"

    # 3. Filas de datos
    for offset_fila, fila in enumerate(hoja.filas, start=2):
        for col_idx, (columna, valor) in enumerate(
            zip(hoja.columnas, fila.valores), start=1
        ):
            celda = ws.cell(row=offset_fila, column=col_idx)
            largo = _escribir_celda(celda, columna, valor)
            if largo > anchos[col_idx - 1]:
                anchos[col_idx - 1] = largo
            if fila.resaltada:
                celda.fill = _RELLENO_VENCIDA
                celda.font = _FUENTE_VENCIDA
            else:
                celda.font = _FUENTE_NORMAL

    # 4. Fila de totales (en centavos ya sumados por `aplicacion`; acá solo se formatea)
    if hoja.totales is not None:
        fila_totales = 2 + len(hoja.filas)
        for col_idx, (columna, valor) in enumerate(
            zip(hoja.columnas, hoja.totales), start=1
        ):
            celda = ws.cell(row=fila_totales, column=col_idx)
            if col_idx == 1 and isinstance(valor, str):
                celda.value = sanitizar_texto_excel(valor)
                celda.data_type = "s"
                celda.alignment = _ALINEACION_POR_TIPO["texto"]
                largo = len(valor)
            else:
                largo = _escribir_celda(celda, columna, valor)
            if largo > anchos[col_idx - 1]:
                anchos[col_idx - 1] = largo
            celda.font = _FUENTE_TOTALES
            celda.fill = _RELLENO_TOTALES
            celda.border = _BORDE_TOTALES

    # 5. Ancho automático acotado para evitar `###` en fechas y montos
    for col_idx, ancho in enumerate(anchos, start=1):
        letra = get_column_letter(col_idx)
        ws.column_dimensions[letra].width = max(12, min(44, ancho + 4))


def _escribir_celda(celda, columna: ColumnaExcel, valor: ValorCeldaExcel) -> int:
    celda.alignment = _ALINEACION_POR_TIPO.get(
        columna.tipo, _ALINEACION_POR_TIPO["texto"]
    )
    if valor is None:
        celda.value = None
        return 0

    if columna.tipo == "moneda":
        pesos = Decimal(int(valor)) / _CIEN
        celda.value = pesos
        celda.number_format = FORMATO_MONEDA_EXCEL
        return len(f"$ {pesos:,.2f}")

    if columna.tipo == "fecha":
        if isinstance(valor, date):
            celda.value = valor
            celda.number_format = FORMATO_FECHA_EXCEL
            return 10
        texto_fecha = sanitizar_texto_excel(str(valor))
        celda.value = texto_fecha
        celda.data_type = "s"
        return len(texto_fecha)

    if columna.tipo == "entero":
        entero = int(valor)
        celda.value = entero
        celda.number_format = FORMATO_ENTERO_EXCEL
        return len(str(entero))

    texto = sanitizar_texto_excel(str(valor))
    celda.value = texto
    celda.data_type = "s"
    return len(texto)


class EscritorExcelOpenpyxl:
    """Escribe un `LibroExportable` en disco de forma atómica con `openpyxl`."""

    def escribir(self, ruta: Path | str, libro: LibroExportable) -> None:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
        wb = construir_workbook(libro)
        try:
            wb.save(temporal)
            os.replace(temporal, destino)
        except PermissionError as exc:
            temporal.unlink(missing_ok=True)
            raise PermissionError(
                f"El archivo «{destino.name}» está abierto en Excel u otro programa. "
                "Cerralo y volvé a intentar."
            ) from exc
        except OSError:
            temporal.unlink(missing_ok=True)
            raise
        finally:
            wb.close()
