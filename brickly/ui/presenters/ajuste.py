"""Presentador de Ajustes IPC (spec §3.5 y §6.3).

Agrupa lo que necesita `VistaAjustesIpc` en una llamada por tabla: valores
IPC, contratos por aplicar (ciclo vencido este mes) e historial. Todo número
sale de `ServicioAjustesIpc`; la vista solo formatea.
"""

from dataclasses import dataclass
from datetime import date

from brickly.aplicacion.ajustes import (
    AjustesPorAplicar,
    DatosAjuste,
    PreviewCuotaAjustada,
    ResultadoAjustes,
    ServicioAjustesIpc,
)
from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.sincronizacion_ipc import (
    DatoIndiceIpc,
    EstadoTokenIpc,
    PreviewSincronizacionIpc,
    ResultadoSincronizacionIpc,
    ServicioSincronizacionIpc,
)
from brickly.dominio.errores import ErrorDeNegocio
from brickly.ui.formato import (
    formatear_monto,
    formatear_periodo,
    formatear_porcentaje,
    formatear_rango_meses,
)

_ORIGEN_ETIQUETA = {"manual": "Manual", "api": "INDEC"}


def formatear_indice_milesimos(indice_milesimos: int) -> str:
    """Formatea `12514151` milésimos como `12.514,151`."""
    entero, milesimos = divmod(abs(indice_milesimos), 1_000)
    miles = f"{entero:,}".replace(",", ".")
    signo = "-" if indice_milesimos < 0 else ""
    return f"{signo}{miles},{milesimos:03d}"


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
class FilaPreviewSincronizacionPresentada:
    """Fila presentada en la vista previa de sincronización con INDEC (H6)."""

    periodo: tuple[int, int]
    periodo_texto: str
    variacion_indec_bp: int
    variacion_indec_texto: str
    indice_texto: str
    valor_actual_texto: str
    estado: str  # "nuevo" | "actualizado" | "sin_cambios" | "manual_protegido"
    seleccionado_por_defecto: bool


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
        self._sincronizacion: ServicioSincronizacionIpc | None = (
            servicios.sincronizacion_ipc
        )

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

    # --- A.2) sincronización con INDEC (H6) -----------------------------------

    def estado_token_indec(self) -> EstadoTokenIpc:
        if self._sincronizacion is None:
            return EstadoTokenIpc(
                configurado=False,
                token_enmascarado=None,
                fecha_emision=None,
                fecha_vencimiento=None,
                vencido=False,
                dias_restantes=None,
                ultima_sincronizacion=None,
                motivo_deshabilitado=(
                    "Configurá el token de INDEC en Configuración para sincronizar."
                ),
            )
        return self._sincronizacion.estado_token()

    def consultar_indices_indec(self) -> list[DatoIndiceIpc]:
        if self._sincronizacion is None:
            raise ErrorDeNegocio(
                "El servicio de sincronización con INDEC no está disponible."
            )
        return self._sincronizacion.consultar_remoto()

    def previsualizar_indec(
        self, indices: list[DatoIndiceIpc] | None = None
    ) -> PreviewSincronizacionIpc:
        if self._sincronizacion is None:
            raise ErrorDeNegocio(
                "El servicio de sincronización con INDEC no está disponible."
            )
        return self._sincronizacion.previsualizar(indices=indices)

    def filas_preview_indec(
        self, preview: PreviewSincronizacionIpc
    ) -> list[FilaPreviewSincronizacionPresentada]:
        filas: list[FilaPreviewSincronizacionPresentada] = []
        for item in preview.items:
            if item.variacion_actual_bp is None:
                actual_texto = "—"
            else:
                origen_etiqueta = _ORIGEN_ETIQUETA.get(
                    item.origen_actual or "", item.origen_actual or ""
                )
                sufijo = f" ({origen_etiqueta})" if origen_etiqueta else ""
                actual_texto = (
                    f"{formatear_porcentaje(item.variacion_actual_bp)}{sufijo}"
                )
            filas.append(
                FilaPreviewSincronizacionPresentada(
                    periodo=(item.anio, item.mes),
                    periodo_texto=formatear_periodo(item.anio, item.mes),
                    variacion_indec_bp=item.variacion_bp,
                    variacion_indec_texto=formatear_porcentaje(item.variacion_bp),
                    indice_texto=formatear_indice_milesimos(item.indice_milesimos),
                    valor_actual_texto=actual_texto,
                    estado=item.estado,
                    seleccionado_por_defecto=item.seleccionado_por_defecto,
                )
            )
        return filas

    def importar_indec(
        self,
        periodos_seleccionados: list[tuple[int, int]],
        reemplazar_manuales: bool = False,
        preview: PreviewSincronizacionIpc | None = None,
    ) -> ResultadoSincronizacionIpc:
        if self._sincronizacion is None:
            raise ErrorDeNegocio(
                "El servicio de sincronización con INDEC no está disponible."
            )
        return self._sincronizacion.importar(
            periodos_seleccionados=periodos_seleccionados,
            reemplazar_manuales=reemplazar_manuales,
            preview=preview,
        )

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
    "FilaPreviewSincronizacionPresentada",
    "PresenterAjustes",
    "fila_ipc_de",
    "formatear_indice_milesimos",
]

