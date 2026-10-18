"""Presentador de Ajustes IPC (spec §3.5 y §6.3).

Agrupa lo que necesita `VistaAjustesIpc` en una llamada por tabla: valores
IPC, contratos por aplicar (ciclo vencido este mes) e historial. Todo número
sale de `ServicioAjustesIpc`; la vista solo formatea.
"""

from dataclasses import dataclass
from datetime import date

from gestion.aplicacion.ajustes import (
    AjustesPorAplicar,
    DatosAjuste,
    PreviewCuotaAjustada,
    ResultadoAjustes,
    ServicioAjustesIpc,
)
from gestion.aplicacion.contenedor import Servicios
from gestion.ui.formato import (
    formatear_monto,
    formatear_periodo,
    formatear_rango_meses,
)

_ORIGEN_ETIQUETA = {"manual": "Manual"}


@dataclass(frozen=True)
class FilaIpcPresentada:
    """Fila de la tabla «Valores IPC cargados» (§3.5 A)."""

    id: int
    periodo: str
    variacion_bp: int
    origen: str
    cargado_en: date
    contratos_que_lo_usan: int


@dataclass(frozen=True)
class FilaAjustePresentada:
    """Fila de «Ajustes por aplicar» (§3.5 B); `id` = contrato_id."""

    id: int
    contrato_id: int
    unidad: str
    inquilino: str
    meses_base: str  # "jul–sep 2026"
    estado: str  # variante de chip: "listo" | "faltan_datos"
    listo: bool
    cuota_actual_centavos: int
    variacion_bp: int | None
    cuota_nueva_centavos: int | None
    delta_centavos: int | None
    faltantes: tuple[tuple[int, int], ...]  # meses sin IPC que bloquean el ajuste


@dataclass(frozen=True)
class FilaHistorialPresentada:
    """Fila del «Historial de ajustes» (§3.5, solo lectura)."""

    id: int
    fecha_aplicacion: date
    unidad: str
    inquilino: str
    meses_base: str
    variacion_bp: int
    cuota_transicion: str  # "$ 12.800 → $ 14.006"
    motivo_override: str | None


class PresenterAjustes:
    def __init__(self, servicios: Servicios):
        self._ajustes: ServicioAjustesIpc = servicios.ajustes

    # --- períodos ------------------------------------------------------------

    def hoy(self) -> date:
        return self._ajustes.hoy()

    def periodo_sugerido(self) -> tuple[int, int]:
        return self._ajustes.periodo_sugerido()

    # --- A) valores IPC -------------------------------------------------------

    def filas_ipc(self) -> list[FilaIpcPresentada]:
        return [
            FilaIpcPresentada(
                id=fila.id,
                periodo=formatear_periodo(fila.anio, fila.mes),
                variacion_bp=fila.variacion_bp,
                origen=_ORIGEN_ETIQUETA.get(fila.origen, fila.origen.capitalize()),
                cargado_en=fila.cargado_en,
                contratos_que_lo_usan=fila.contratos_que_lo_usan,
            )
            for fila in self._ajustes.listar_ipc()
        ]

    def agregar_ipc(self, anio: int, mes: int, variacion_bp: int) -> int:
        return self._ajustes.agregar_ipc(anio, mes, variacion_bp)

    def editar_ipc(self, ipc_id: int, variacion_bp: int) -> None:
        self._ajustes.editar_ipc(ipc_id, variacion_bp)

    def eliminar_ipc(self, ipc_id: int) -> None:
        self._ajustes.eliminar_ipc(ipc_id)

    # --- B) ajustes por aplicar + wizard --------------------------------------

    def pendientes(self) -> AjustesPorAplicar:
        return self._ajustes.ajustes_por_aplicar()

    def filas_por_aplicar(self, pendientes: AjustesPorAplicar) -> list[FilaAjustePresentada]:
        return [
            FilaAjustePresentada(
                id=fila.contrato_id,
                contrato_id=fila.contrato_id,
                unidad=fila.unidad,
                inquilino=fila.inquilino,
                meses_base=formatear_rango_meses(*fila.desde, *fila.hasta),
                estado=fila.estado,
                listo=fila.listo,
                cuota_actual_centavos=fila.cuota_actual_centavos,
                variacion_bp=fila.variacion_bp,
                cuota_nueva_centavos=fila.cuota_nueva_centavos,
                delta_centavos=fila.delta_centavos,
                faltantes=tuple(fila.meses_faltantes),
            )
            for fila in pendientes.filas
        ]

    def calcular_cuota(self, contrato_id: int, variacion_bp: int) -> PreviewCuotaAjustada:
        return self._ajustes.calcular_cuota(contrato_id, variacion_bp)

    def aplicar(self, datos: list[DatosAjuste]) -> ResultadoAjustes:
        return self._ajustes.aplicar(datos)

    def historial(self) -> list[FilaHistorialPresentada]:
        return [
            FilaHistorialPresentada(
                id=fila.id,
                fecha_aplicacion=fila.fecha_aplicacion,
                unidad=fila.unidad,
                inquilino=fila.inquilino,
                meses_base=formatear_rango_meses(*fila.desde, *fila.hasta),
                variacion_bp=fila.variacion_bp,
                cuota_transicion=(
                    f"{formatear_monto(fila.cuota_antes_centavos)}"
                    f" → {formatear_monto(fila.cuota_despues_centavos)}"
                ),
                motivo_override=fila.motivo_override,
            )
            for fila in self._ajustes.historial()
        ]


def fila_ipc_de(filas: list[FilaIpcPresentada], ipc_id: int) -> FilaIpcPresentada | None:
    """Busca una fila ya cargada (paneles de edición y confirmaciones)."""
    for fila in filas:
        if fila.id == ipc_id:
            return fila
    return None


__all__ = [
    "FilaAjustePresentada",
    "FilaHistorialPresentada",
    "FilaIpcPresentada",
    "PresenterAjustes",
    "fila_ipc_de",
]
