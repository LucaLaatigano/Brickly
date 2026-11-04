"""Adaptador PDF con `reportlab` — implementa `GeneradorPdf` (H8 — ADR-0004).

Diseño:
- Usa fuentes estándar PDF (`Helvetica` y `Helvetica-Bold`, codificación WinAnsi)
  que soportan todos los caracteres castellanos (`áéíóúÁÉÍÓÚñÑüÜº°$`) sin
  incrustar archivos `.ttf` externos.
- Formatos `es-AR`: fechas `dd/mm/aaaa` y montos `$ 12.800,00` calculados desde
  centavos enteros (`int`), sin `float`.
- Renderiza en memoria (`io.BytesIO`) y publica de forma atómica con
  `os.replace` sobre un temporal en la misma carpeta destino. Si el archivo
  está abierto en un visor que bloquea escritura en Windows (`PermissionError`),
  limpia el temporal y devuelve un mensaje claro en castellano.
"""

from __future__ import annotations

import io
import os
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from brickly.aplicacion.constancias import ConstanciaPago


def formatear_monto_pdf(centavos: int) -> str:
    """Formatea centavos enteros como `$ 12.800,00` (siempre con 2 decimales)."""
    if isinstance(centavos, bool) or not isinstance(centavos, int):
        raise TypeError("El monto en centavos debe ser int.")
    signo = "-" if centavos < 0 else ""
    enteros, resto = divmod(abs(centavos), 100)
    miles = f"{enteros:,}".replace(",", ".")
    return f"{signo}$ {miles},{resto:02d}"


def formatear_fecha_pdf(fecha: date) -> str:
    """Formatea `date` como `dd/mm/aaaa`."""
    return f"{fecha.day:02d}/{fecha.month:02d}/{fecha.year:04d}"


def _truncar_texto(texto: str, max_largo: int) -> str:
    limpio = " ".join(texto.split())
    if len(limpio) <= max_largo:
        return limpio
    return limpio[: max_largo - 1].rstrip() + "…"


class GeneradorPdfReportlab:
    """Genera el archivo PDF de una `ConstanciaPago` en una página A4."""

    def generar(self, documento: ConstanciaPago, ruta: Path | str) -> None:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        contenido = self._renderizar_en_memoria(documento)
        temporal = destino.with_name(f".{destino.stem}.{os.getpid()}.tmp")
        try:
            temporal.write_bytes(contenido)
            os.replace(temporal, destino)
        except PermissionError as exc:
            self._limpiar_temporal(temporal)
            raise PermissionError(
                f"El archivo «{destino.name}» está abierto en otro programa. "
                "Cerralo y volvé a intentar."
            ) from exc
        except OSError:
            self._limpiar_temporal(temporal)
            raise

    @staticmethod
    def _limpiar_temporal(temporal: Path) -> None:
        try:
            if temporal.exists():
                temporal.unlink()
        except OSError:
            pass

    def _renderizar_en_memoria(self, doc: ConstanciaPago) -> bytes:
        buffer = io.BytesIO()
        ancho, alto = A4
        margen_x = 48.0
        ancho_util = ancho - 2 * margen_x

        c = canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
        c.setTitle(f"{doc.titulo} - {doc.unidad} - {doc.periodo}")
        c.setAuthor(doc.admin_nombre or doc.propietario_nombre or "Brickly")
        c.setSubject(f"Constancia de pago {doc.periodo} ({doc.unidad})")

        y = alto - 52.0

        # ── Encabezado ──────────────────────────────────────────────────────
        c.setFillColor(colors.HexColor("#18181B"))
        c.setFont("Helvetica-Bold", 20)
        c.drawString(margen_x, y, doc.titulo)

        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#52525B"))
        c.drawRightString(
            ancho - margen_x,
            y + 2,
            f"Fecha de emisión: {formatear_fecha_pdf(doc.fecha_emision)}",
        )
        y -= 16.0

        partes_emisor: list[str] = []
        if doc.admin_nombre:
            partes_emisor.append(f"Administración: {doc.admin_nombre}")
        if doc.admin_telefono:
            partes_emisor.append(f"Tel.: {doc.admin_telefono}")
        if doc.admin_email:
            partes_emisor.append(doc.admin_email)
        if partes_emisor:
            c.setFont("Helvetica", 9.5)
            c.setFillColor(colors.HexColor("#52525B"))
            c.drawString(margen_x, y, _truncar_texto(" · ".join(partes_emisor), 95))
            y -= 14.0

        y -= 6.0
        c.setStrokeColor(colors.HexColor("#E4E4E7"))
        c.setLineWidth(1.0)
        c.line(margen_x, y, ancho - margen_x, y)
        y -= 24.0

        # ── Bloque: Unidad, Inquilino y Período ─────────────────────────────
        alto_caja_datos = 78.0
        c.setFillColor(colors.HexColor("#FAFAFA"))
        c.setStrokeColor(colors.HexColor("#E4E4E7"))
        c.roundRect(
            margen_x,
            y - alto_caja_datos,
            ancho_util,
            alto_caja_datos,
            6.0,
            stroke=1,
            fill=1,
        )

        col_izq = margen_x + 14.0
        col_der = margen_x + ancho_util * 0.58
        y_fila1 = y - 20.0
        y_fila2 = y - 54.0

        c.setFillColor(colors.HexColor("#71717A"))
        c.setFont("Helvetica", 8.5)
        c.drawString(col_izq, y_fila1 + 11, "UNIDAD")
        c.drawString(col_der, y_fila1 + 11, "PERÍODO ABONADO")
        c.drawString(col_izq, y_fila2 + 11, "INQUILINO/A")
        c.drawString(col_der, y_fila2 + 11, "VENCIMIENTO DE LA CUOTA")

        c.setFillColor(colors.HexColor("#18181B"))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(col_izq, y_fila1 - 2, _truncar_texto(doc.unidad, 48))
        c.drawString(col_der, y_fila1 - 2, doc.periodo.capitalize())

        c.setFont("Helvetica", 10.5)
        c.drawString(col_izq, y_fila2 - 2, _truncar_texto(doc.inquilino, 48))
        c.drawString(col_der, y_fila2 - 2, formatear_fecha_pdf(doc.fecha_vencimiento))

        y -= alto_caja_datos + 24.0

        # ── Bloque: Detalle imputado a esta cuota ───────────────────────────
        c.setFillColor(colors.HexColor("#18181B"))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margen_x, y, "Resumen imputado al período")
        y -= 10.0

        alto_resumen = 84.0
        c.setFillColor(colors.HexColor("#FFFFFF"))
        c.setStrokeColor(colors.HexColor("#E4E4E7"))
        c.roundRect(
            margen_x,
            y - alto_resumen,
            ancho_util,
            alto_resumen,
            6.0,
            stroke=1,
            fill=1,
        )

        x_etiqueta = margen_x + 14.0
        x_valor = ancho - margen_x - 14.0

        y_cap = y - 22.0
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#3F3F46"))
        c.drawString(x_etiqueta, y_cap, "Capital de la cuota")
        c.drawRightString(x_valor, y_cap, formatear_monto_pdf(doc.capital_centavos))

        y_mora = y - 42.0
        c.drawString(x_etiqueta, y_mora, "Mora cobrada")
        c.drawRightString(x_valor, y_mora, formatear_monto_pdf(doc.mora_centavos))

        c.setStrokeColor(colors.HexColor("#E4E4E7"))
        c.line(x_etiqueta, y - 54.0, x_valor, y - 54.0)

        y_tot = y - 71.0
        c.setFont("Helvetica-Bold", 11.5)
        c.setFillColor(colors.HexColor("#18181B"))
        c.drawString(x_etiqueta, y_tot, "Total abonado en este período")
        c.drawRightString(x_valor, y_tot, formatear_monto_pdf(doc.total_centavos))

        y -= alto_resumen + 26.0

        # ── Tabla de pagos imputados ────────────────────────────────────────
        c.setFillColor(colors.HexColor("#18181B"))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margen_x, y, "Pagos aplicados a esta cuota")
        y -= 12.0

        # Encabezado de tabla
        alto_enc = 22.0
        c.setFillColor(colors.HexColor("#F4F4F5"))
        c.setStrokeColor(colors.HexColor("#E4E4E7"))
        c.rect(margen_x, y - alto_enc, ancho_util, alto_enc, stroke=1, fill=1)

        x_fecha = margen_x + 10.0
        x_medio = margen_x + 82.0
        x_nota = margen_x + 170.0
        x_cap_col = ancho - margen_x - 150.0
        x_mora_col = ancho - margen_x - 80.0
        x_sub_col = ancho - margen_x - 10.0

        c.setFillColor(colors.HexColor("#52525B"))
        c.setFont("Helvetica-Bold", 9)
        y_texto_enc = y - 15.0
        c.drawString(x_fecha, y_texto_enc, "Fecha")
        c.drawString(x_medio, y_texto_enc, "Medio")
        c.drawString(x_nota, y_texto_enc, "Nota")
        c.drawRightString(x_cap_col, y_texto_enc, "Capital")
        c.drawRightString(x_mora_col, y_texto_enc, "Mora")
        c.drawRightString(x_sub_col, y_texto_enc, "Imputado")

        y -= alto_enc
        alto_fila = 20.0
        c.setFont("Helvetica", 9.5)
        for p in doc.pagos:
            if y - alto_fila < 190.0:
                break
            c.setStrokeColor(colors.HexColor("#F4F4F5"))
            c.line(margen_x, y - alto_fila, ancho - margen_x, y - alto_fila)
            y_txt = y - 14.0
            c.setFillColor(colors.HexColor("#18181B"))
            c.drawString(x_fecha, y_txt, formatear_fecha_pdf(p.fecha))
            c.drawString(x_medio, y_txt, _truncar_texto(p.medio_etiqueta, 16))
            c.setFillColor(colors.HexColor("#52525B"))
            c.drawString(x_nota, y_txt, _truncar_texto(p.nota or "—", 26))
            c.setFillColor(colors.HexColor("#18181B"))
            c.drawRightString(x_cap_col, y_txt, formatear_monto_pdf(p.capital_centavos))
            c.drawRightString(x_mora_col, y_txt, formatear_monto_pdf(p.mora_centavos))
            c.setFont("Helvetica-Bold", 9.5)
            c.drawRightString(
                x_sub_col, y_txt, formatear_monto_pdf(p.monto_imputado_centavos)
            )
            c.setFont("Helvetica", 9.5)
            y -= alto_fila

        # ── Bloque de firma visual (al pie) ─────────────────────────────────
        y_firma_linea = 135.0
        ancho_linea_firma = 220.0
        x_firma_izq = (ancho - ancho_linea_firma) / 2.0
        x_firma_centro = ancho / 2.0

        c.setStrokeColor(colors.HexColor("#71717A"))
        c.setLineWidth(1.0)
        c.line(x_firma_izq, y_firma_linea, x_firma_izq + ancho_linea_firma, y_firma_linea)

        if doc.firma_nombre:
            c.setFillColor(colors.HexColor("#18181B"))
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(
                x_firma_centro,
                y_firma_linea - 15.0,
                _truncar_texto(doc.firma_nombre, 60),
            )
            y_rol = y_firma_linea - 28.0
        else:
            y_rol = y_firma_linea - 15.0

        c.setFillColor(colors.HexColor("#52525B"))
        c.setFont("Helvetica", 9)
        c.drawCentredString(x_firma_centro, y_rol, doc.firma_rol)

        # ── Pie de alcance (no libre deuda / no fiscal) ─────────────────────
        y_pie = 68.0
        c.setStrokeColor(colors.HexColor("#E4E4E7"))
        c.setLineWidth(0.75)
        c.line(margen_x, y_pie + 16.0, ancho - margen_x, y_pie + 16.0)

        c.setFillColor(colors.HexColor("#52525B"))
        c.setFont("Helvetica", 8.5)
        c.drawString(margen_x, y_pie, doc.leyenda_pie)
        c.setFillColor(colors.HexColor("#71717A"))
        c.setFont("Helvetica", 8)
        c.drawString(margen_x, y_pie - 13.0, doc.leyenda_no_fiscal)

        c.showPage()
        c.save()
        return buffer.getvalue()
