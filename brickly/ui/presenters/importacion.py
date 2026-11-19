"""Presentador de importación desde planillas Excel (spec §3 y ADR-0005).

Convierte las estructuras de `aplicacion.importacion` a DTOs listos para pintar
en la tabla de previsualización y el panel lateral de 380 px.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from brickly.aplicacion.importacion import (
    FilaPrevisualizacionImportacion,
    PrevisualizacionImportacion,
)
from brickly.ui.formato import formatear_fecha, formatear_monto


@dataclass(frozen=True)
class FilaImportacionPresentada:
    """Fila formateada para la tabla de previsualización en el paso 3."""

    numero_fila: int
    unidad: str
    inquilino: str
    vigencia: str
    cuota_mensual: str
    estado_texto: str
    variante_chip: str
    motivo_o_detalle: str
    es_importable: bool
    tiene_errores: bool
    tiene_advertencias: bool
    fila_original: FilaPrevisualizacionImportacion


@dataclass(frozen=True)
class ResumenImportacionPresentado:
    """Totales y estado de habilitación del botón de confirmación."""

    total_filas: int
    filas_listas: int
    filas_con_errores: int
    filas_omitidas: int
    texto_resumen: str
    puede_importar: bool
    texto_boton_importar: str


def presentar_fila_importacion(
    fila: FilaPrevisualizacionImportacion,
) -> FilaImportacionPresentada:
    """Formatea una fila para la tabla y determina el chip y detalle."""
    if fila.fecha_inicio is not None and fila.fecha_fin_informativa is not None:
        vigencia = (
            f"{formatear_fecha(fila.fecha_inicio)} al {formatear_fecha(fila.fecha_fin_informativa)}"
        )
    elif fila.fecha_inicio is not None:
        vigencia = f"Desde {formatear_fecha(fila.fecha_inicio)}"
    else:
        vigencia = "Sin contrato"

    cuota = (
        formatear_monto(fila.monto_inicial_centavos)
        if fila.monto_inicial_centavos is not None
        else "—"
    )

    inquilino = fila.inquilino_nombre or "Sin inquilino"

    tiene_err = bool(fila.errores) or fila.estado == "error"
    tiene_adv = bool(fila.advertencias)

    if tiene_err:
        estado_texto = "Con errores"
        variante_chip = "vencida"
        motivo = " · ".join(fila.errores)
    elif fila.estado == "omitido_existente":
        estado_texto = "Ya existe"
        variante_chip = "sin_cambios"
        motivo = fila.advertencias[0] if fila.advertencias else "Se omite para no duplicar."
    elif fila.estado == "omitido_contrato_anterior":
        estado_texto = "Contrato anterior"
        variante_chip = "sin_cambios"
        motivo = fila.advertencias[0] if fila.advertencias else "Se omite contrato anterior."
    elif fila.estado == "omitido_manual":
        estado_texto = "Omitida a mano"
        variante_chip = "sin_cambios"
        motivo = "Desmarcada manualmente por el usuario."
    elif fila.estado == "nuevo_con_contrato":
        estado_texto = "Listo"
        variante_chip = "listo"
        motivo = " · ".join(fila.advertencias) if fila.advertencias else "Contrato vigente listo para importar."
    elif fila.estado == "nuevo_contrato_vencido":
        estado_texto = "Vacante (vencido)"
        variante_chip = "parcial"
        motivo = fila.advertencias[0] if fila.advertencias else "Se importará solo departamento."
    else:
        # nuevo_vacante
        estado_texto = "Listo (vacante)"
        variante_chip = "listo"
        motivo = "Departamento sin contrato activo."

    return FilaImportacionPresentada(
        numero_fila=fila.numero_fila,
        unidad=fila.unidad_texto,
        inquilino=inquilino,
        vigencia=vigencia,
        cuota_mensual=cuota,
        estado_texto=estado_texto,
        variante_chip=variante_chip,
        motivo_o_detalle=motivo,
        es_importable=fila.es_importable,
        tiene_errores=tiene_err,
        tiene_advertencias=tiene_adv,
        fila_original=fila,
    )


def presentar_resumen_importacion(
    prev: PrevisualizacionImportacion,
) -> ResumenImportacionPresentado:
    """Calcula el balance textual del resumen y habilita el CTA de importación."""
    listas = prev.filas_listas
    errores = prev.filas_con_errores
    omitidas = prev.filas_omitidas

    partes_resumen = []
    partes_resumen.append(f"{listas} lista{'s' if listas != 1 else ''}")
    if errores > 0:
        partes_resumen.append(f"{errores} con error{'es' if errores != 1 else ''}")
    if omitidas > 0:
        partes_resumen.append(f"{omitidas} se omitir{'án' if omitidas != 1 else 'á'}")

    texto_resumen = " · ".join(partes_resumen)

    puede_importar = listas > 0 and errores == 0

    if listas == 1:
        texto_boton = "Importar 1 departamento"
    else:
        texto_boton = f"Importar {listas} departamentos"

    return ResumenImportacionPresentado(
        total_filas=prev.total_filas,
        filas_listas=listas,
        filas_con_errores=errores,
        filas_omitidas=omitidas,
        texto_resumen=texto_resumen,
        puede_importar=puede_importar,
        texto_boton_importar=texto_boton,
    )


def presentar_previsualizacion(
    prev: PrevisualizacionImportacion,
) -> tuple[ResumenImportacionPresentado, list[FilaImportacionPresentada]]:
    resumen = presentar_resumen_importacion(prev)
    filas = [presentar_fila_importacion(f) for f in prev.filas]
    return resumen, filas
