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
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.worksheet import Worksheet

from brickly.aplicacion.informes import (
    ColumnaExcel,
    HojaExportable,
    LibroExportable,
    ValorCeldaExcel,
    sanitizar_texto_excel,
)
from brickly.aplicacion.puertos import (
    FilaCrudaExcel,
    HojaCrudaExcel,
    ValorCeldaCruda,
)
from brickly.dominio.errores import ErrorDeNegocio

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


def _convertir_valor_celda_openpyxl(
    val: Any, number_format: str | None
) -> ValorCeldaCruda:
    if val is None:
        return None
    if val == "__FORMULA_SIN_VALOR__":
        return "__FORMULA_SIN_VALOR__"
    # bool es subclase de int, chequear antes
    if isinstance(val, bool):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    es_porcentaje = isinstance(number_format, str) and "%" in number_format
    if isinstance(val, float):
        if es_porcentaje:
            porcentaje_dec = Decimal(str(round(val * 100, 4)))
            texto_pct = (
                f"{porcentaje_dec:f}".rstrip("0").rstrip(".")
                if "." in f"{porcentaje_dec:f}"
                else f"{porcentaje_dec}"
            )
            return f"{texto_pct}%"
        return Decimal(str(round(val, 6)))
    if isinstance(val, int):
        if es_porcentaje:
            return f"{val * 100}%"
        return val
    if isinstance(val, Decimal):
        return val
    if isinstance(val, str):
        texto = val.strip()
        return texto or None
    return str(val)


def _validar_ruta_excel(ruta_archivo: Path | str) -> Path:
    ruta = Path(ruta_archivo)
    sufijo = ruta.suffix.lower()
    if sufijo == ".xls":
        raise ErrorDeNegocio(
            "El formato .xls no es compatible. Abrí el archivo en Excel y guardalo como .xlsx para importarlo."
        )
    if sufijo != ".xlsx":
        raise ErrorDeNegocio("El archivo debe ser un libro de Excel (.xlsx).")
    if not ruta.is_file():
        raise ErrorDeNegocio(f"El archivo «{ruta.name}» no existe.")
    return ruta


class LectorExcelOpenpyxl:
    """Lee libros `.xlsx` y entrega datos crudos limpios sin `float`."""

    def listar_hojas(self, ruta: str) -> list[str]:
        archivo = _validar_ruta_excel(ruta)
        try:
            wb = load_workbook(archivo, read_only=True)
            try:
                return list(wb.sheetnames)
            finally:
                wb.close()
        except PermissionError as exc:
            raise ErrorDeNegocio(
                f"El archivo «{archivo.name}» está abierto en Excel u otro programa. Cerralo y volvé a intentar."
            ) from exc
        except (zipfile.BadZipFile, InvalidFileException) as exc:
            raise ErrorDeNegocio(
                f"El archivo «{archivo.name}» está dañado o no es un archivo .xlsx válido."
            ) from exc

    def leer_hoja(
        self, ruta: str, nombre_hoja: str | None = None
    ) -> HojaCrudaExcel:
        archivo = _validar_ruta_excel(ruta)
        wb_data = None
        wb_formula = None
        try:
            try:
                wb_data = load_workbook(archivo, data_only=True)
                wb_formula = load_workbook(archivo, data_only=False)
            except PermissionError as exc:
                raise ErrorDeNegocio(
                    f"El archivo «{archivo.name}» está abierto en Excel u otro programa. Cerralo y volvé a intentar."
                ) from exc
            except (zipfile.BadZipFile, InvalidFileException) as exc:
                raise ErrorDeNegocio(
                    f"El archivo «{archivo.name}» está dañado o no es un archivo .xlsx válido."
                ) from exc

            if nombre_hoja is None:
                hoja_nombre = wb_data.sheetnames[0]
            else:
                if nombre_hoja not in wb_data.sheetnames:
                    raise ErrorDeNegocio(
                        f"La hoja «{nombre_hoja}» no existe en el archivo «{archivo.name}»."
                    )
                hoja_nombre = nombre_hoja

            ws_data = wb_data[hoja_nombre]
            ws_formula = wb_formula[hoja_nombre]

            mapa_combinadas: dict[tuple[int, int], Any] = {}
            filas_con_combinadas: set[int] = set()

            for rango in ws_data.merged_cells.ranges:
                min_col, min_row, max_col, max_row = (
                    rango.min_col,
                    rango.min_row,
                    rango.max_col,
                    rango.max_row,
                )
                for r in range(min_row, max_row + 1):
                    filas_con_combinadas.add(r)
                val_origen = ws_data.cell(row=min_row, column=min_col).value
                for r in range(min_row, max_row + 1):
                    for c in range(min_col, max_col + 1):
                        if (r, c) != (min_row, min_col):
                            mapa_combinadas[(r, c)] = val_origen

            max_row = ws_data.max_row or 0
            max_col = ws_data.max_column or 0

            filas_crudas: list[FilaCrudaExcel] = []
            for r in range(1, max_row + 1):
                valores_fila: list[ValorCeldaCruda] = []
                for c in range(1, max_col + 1):
                    cell_d = ws_data.cell(row=r, column=c)
                    val = cell_d.value
                    if val is None and (r, c) in mapa_combinadas:
                        val = mapa_combinadas[(r, c)]
                    if val is None:
                        cell_f = ws_formula.cell(row=r, column=c)
                        if cell_f.value is not None and str(cell_f.value).startswith("="):
                            val = "__FORMULA_SIN_VALOR__"
                    valores_fila.append(
                        _convertir_valor_celda_openpyxl(val, cell_d.number_format)
                    )

                filas_crudas.append(
                    FilaCrudaExcel(
                        numero_fila=r,
                        valores=tuple(valores_fila),
                        tiene_celdas_combinadas=(r in filas_con_combinadas),
                    )
                )

            filas_no_vacias = [
                f for f in filas_crudas if any(v is not None for v in f.valores)
            ]
            if len(filas_no_vacias) > 501:
                raise ErrorDeNegocio(
                    f"El archivo supera el límite máximo de 500 filas de datos ({len(filas_no_vacias) - 1} filas encontradas)."
                )

            return HojaCrudaExcel(
                nombre=hoja_nombre,
                filas=tuple(filas_crudas),
            )
        finally:
            if wb_data is not None:
                wb_data.close()
            if wb_formula is not None:
                wb_formula.close()

