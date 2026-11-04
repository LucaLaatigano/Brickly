"""Casos de uso de Ajustes IPC (spec §3.5 — H3: valores, ajustes por aplicar, wizard, historial).

Reglas (ADR-0002 §1): el ajuste confirmado actualiza la cuota VIGENTE del
contrato, así que solo impacta en cuotas que se generen después; no toca cuotas
emitidas ni pagos. Todo el cálculo (acumulado, cuota nueva, Δ, promedio) sale
del dominio por acá: la UI solo formatea.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from brickly.dominio.contrato import Contrato
from brickly.dominio.departamento import nombre_unidad
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.dominio.ipc import (
    AjusteCalculado,
    IpcMensual,
    acumular_variaciones_bp,
    aplicar_variacion,
    meses_base,
    validar_variacion_bp,
    variacion_promedio_bp,
)

if TYPE_CHECKING:
    from brickly.aplicacion.puertos import Reloj, RepositorioAjustes

EstadoAjuste = Literal["listo", "faltan_datos"]


@dataclass(frozen=True)
class ContratoParaAjuste:
    """Contrato vigente leído del repositorio con lo necesario para ajustarlo."""

    contrato_id: int
    departamento_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    fecha_inicio: date
    monto_centavos: int
    ciclo_meses: int
    redondeo_centavos: int
    ultimo_ajuste: date | None = None


@dataclass(frozen=True)
class RegistroIpc:
    """Fila cruda de `ipc_valores`."""

    id: int
    anio: int
    mes: int
    variacion_bp: int
    origen: str
    cargado_en: date
    indice_milesimos: int | None = None
    actualizado_en: str | None = None


@dataclass(frozen=True)
class FilaIpc:
    """Fila de la tabla de valores IPC (§3.5 A). `id` sirve a `Tabla`."""

    id: int
    anio: int
    mes: int
    variacion_bp: int
    origen: str
    cargado_en: date
    contratos_que_lo_usan: int  # ajustes pendientes de este mes que lo usan
    indice_milesimos: int | None = None
    actualizado_en: str | None = None


@dataclass(frozen=True)
class MesBase:
    anio: int
    mes: int
    variacion_bp: int | None  # None = IPC sin cargar


@dataclass(frozen=True)
class AjustePendiente:
    """Contrato cuyo ciclo vence este mes (§3.5 B). `id` = contrato_id."""

    id: int
    contrato_id: int
    departamento_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    fecha_ajuste: date
    meses: tuple[MesBase, ...]
    cuota_actual_centavos: int
    redondeo_centavos: int
    variacion_bp: int | None
    cuota_nueva_centavos: int | None
    delta_centavos: int | None

    @property
    def unidad(self) -> str:
        return nombre_unidad(self.direccion, self.piso, self.depto)

    @property
    def estado(self) -> EstadoAjuste:
        return "listo" if self.variacion_bp is not None else "faltan_datos"

    @property
    def listo(self) -> bool:
        return self.variacion_bp is not None

    @property
    def meses_faltantes(self) -> list[tuple[int, int]]:
        return [(m.anio, m.mes) for m in self.meses if m.variacion_bp is None]

    @property
    def desde(self) -> tuple[int, int]:
        return self.meses[0].anio, self.meses[0].mes

    @property
    def hasta(self) -> tuple[int, int]:
        return self.meses[-1].anio, self.meses[-1].mes


@dataclass(frozen=True)
class AjustesPorAplicar:
    fecha_calculo: date
    filas: list[AjustePendiente]

    @property
    def listos(self) -> list[AjustePendiente]:
        return [fila for fila in self.filas if fila.listo]

    @property
    def meses_faltantes(self) -> list[tuple[int, int]]:
        """Períodos sin IPC que bloquean algún ajuste, sin repetir y en orden."""
        return sorted({m for fila in self.filas for m in fila.meses_faltantes})


@dataclass(frozen=True)
class PreviewCuotaAjustada:
    """Recalculo en vivo de la celda «IPC aplicado» del wizard (§3.5 paso 2)."""

    contrato_id: int
    variacion_bp: int
    cuota_nueva_centavos: int
    delta_centavos: int
    es_override: bool


@dataclass(frozen=True)
class DatosAjuste:
    """Entrada del wizard por contrato marcado."""

    contrato_id: int
    variacion_bp: int
    motivo_override: str | None = None


@dataclass(frozen=True)
class ResultadoAjustes:
    cantidad: int
    variacion_promedio_bp: int
    total_antes_centavos: int
    total_despues_centavos: int


@dataclass(frozen=True)
class FilaHistorialAjuste:
    """Fila de solo lectura del Historial de ajustes (§3.5)."""

    id: int
    contrato_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    fecha_aplicacion: date
    anio_base: int
    mes_base: int
    meses_ciclo: int
    variacion_bp: int
    cuota_antes_centavos: int
    cuota_despues_centavos: int
    es_override: bool
    motivo_override: str | None

    @property
    def unidad(self) -> str:
        return nombre_unidad(self.direccion, self.piso, self.depto)

    @property
    def desde(self) -> tuple[int, int]:
        return self.anio_base, self.mes_base

    @property
    def hasta(self) -> tuple[int, int]:
        anio, mes_0 = divmod(self.anio_base * 12 + self.mes_base - 1 + self.meses_ciclo - 1, 12)
        return anio, mes_0 + 1


class ServicioAjustesIpc:
    """ABM de IPC mensual, cálculo de ajustes pendientes y aplicación atómica."""

    def __init__(self, repositorio: RepositorioAjustes, reloj: Reloj):
        self._repositorio = repositorio
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj.hoy()

    def periodo_sugerido(self) -> tuple[int, int]:
        """El IPC se publica con un mes de rezago: el default es el mes anterior a hoy."""
        hoy = self._reloj.hoy()
        anio, mes_0 = divmod(hoy.year * 12 + hoy.month - 2, 12)
        return anio, mes_0 + 1

    # --- A) valores IPC ----------------------------------------------------

    def listar_ipc(self) -> list[FilaIpc]:
        registros = self._repositorio.listar_ipc()
        uso: dict[tuple[int, int], int] = {}
        for pendiente in self._pendientes(self._indice_ipc(registros)):
            for mes in pendiente.meses:
                clave = (mes.anio, mes.mes)
                uso[clave] = uso.get(clave, 0) + 1
        return [
            FilaIpc(
                id=r.id,
                anio=r.anio,
                mes=r.mes,
                variacion_bp=r.variacion_bp,
                origen=r.origen,
                cargado_en=r.cargado_en,
                contratos_que_lo_usan=uso.get((r.anio, r.mes), 0),
                indice_milesimos=r.indice_milesimos,
                actualizado_en=r.actualizado_en,
            )
            for r in registros
        ]

    def agregar_ipc(self, anio: int, mes: int, variacion_bp: int) -> int:
        ipc = IpcMensual(anio=anio, mes=mes, variacion_bp=variacion_bp)
        if self._repositorio.existe_ipc(anio, mes):
            raise ErrorDeValidacion(
                "Ya hay un IPC cargado para ese mes; editalo desde la tabla.",
                campo="periodo",
            )
        return self._repositorio.guardar_ipc(ipc)

    def editar_ipc(self, ipc_id: int, variacion_bp: int) -> None:
        actual = self._obtener_ipc(ipc_id)
        IpcMensual(anio=actual.anio, mes=actual.mes, variacion_bp=variacion_bp)
        self._repositorio.actualizar_ipc(ipc_id, variacion_bp)

    def eliminar_ipc(self, ipc_id: int) -> None:
        self._obtener_ipc(ipc_id)
        self._repositorio.eliminar_ipc(ipc_id)

    # --- B) ajustes por aplicar + wizard -----------------------------------

    def ajustes_por_aplicar(self) -> AjustesPorAplicar:
        indice = self._indice_ipc(self._repositorio.listar_ipc())
        return AjustesPorAplicar(fecha_calculo=self._reloj.hoy(), filas=self._pendientes(indice))

    def calcular_cuota(self, contrato_id: int, variacion_bp: int) -> PreviewCuotaAjustada:
        pendiente = self._pendiente(contrato_id, self.ajustes_por_aplicar())
        nueva = aplicar_variacion(
            pendiente.cuota_actual_centavos, variacion_bp, pendiente.redondeo_centavos
        )
        return PreviewCuotaAjustada(
            contrato_id=contrato_id,
            variacion_bp=variacion_bp,
            cuota_nueva_centavos=nueva,
            delta_centavos=nueva - pendiente.cuota_actual_centavos,
            es_override=variacion_bp != pendiente.variacion_bp,
        )

    def aplicar(self, datos: list[DatosAjuste]) -> ResultadoAjustes:
        """Todo o nada: si un contrato falla, no se aplica ninguno (§3.5)."""
        if not datos:
            raise ErrorDeNegocio("Elegí al menos un contrato para ajustar.")
        ids = [d.contrato_id for d in datos]
        if len(set(ids)) != len(ids):
            raise ErrorDeNegocio("Un contrato aparece dos veces en el ajuste.")

        estado = self.ajustes_por_aplicar()
        ajustes: list[AjusteCalculado] = []
        for dato in datos:
            validar_variacion_bp(dato.variacion_bp)
            pendiente = self._pendiente(dato.contrato_id, estado)
            if not pendiente.listo:
                raise ErrorDeNegocio(
                    f"Faltan datos de IPC para {pendiente.unidad}."
                )
            es_override = dato.variacion_bp != pendiente.variacion_bp
            anio_base, mes_base = pendiente.desde
            ajustes.append(
                AjusteCalculado(
                    contrato_id=pendiente.contrato_id,
                    fecha_ajuste=pendiente.fecha_ajuste,
                    anio_base=anio_base,
                    mes_base=mes_base,
                    meses_ciclo=len(pendiente.meses),
                    variacion_bp=dato.variacion_bp,
                    cuota_antes_centavos=pendiente.cuota_actual_centavos,
                    cuota_despues_centavos=aplicar_variacion(
                        pendiente.cuota_actual_centavos,
                        dato.variacion_bp,
                        pendiente.redondeo_centavos,
                    ),
                    es_override=es_override,
                    motivo_override=dato.motivo_override,
                )
            )

        self._repositorio.guardar_ajustes(ajustes)
        antes = sum(a.cuota_antes_centavos for a in ajustes)
        despues = sum(a.cuota_despues_centavos for a in ajustes)
        return ResultadoAjustes(
            cantidad=len(ajustes),
            variacion_promedio_bp=variacion_promedio_bp(antes, despues),
            total_antes_centavos=antes,
            total_despues_centavos=despues,
        )

    def historial(self) -> list[FilaHistorialAjuste]:
        return self._repositorio.listar_historial()

    # --- internos ----------------------------------------------------------

    def _obtener_ipc(self, ipc_id: int) -> RegistroIpc:
        registro = self._repositorio.obtener_ipc(ipc_id)
        if registro is None:
            raise ErrorDeNegocio("El IPC seleccionado no existe.")
        return registro

    @staticmethod
    def _indice_ipc(registros: list[RegistroIpc]) -> dict[tuple[int, int], int]:
        return {(r.anio, r.mes): r.variacion_bp for r in registros}

    @staticmethod
    def _pendiente(contrato_id: int, estado: AjustesPorAplicar) -> AjustePendiente:
        for fila in estado.filas:
            if fila.contrato_id == contrato_id:
                return fila
        raise ErrorDeNegocio("Ese contrato ya no tiene un ajuste pendiente este mes.")

    def _pendientes(self, indice_ipc: dict[tuple[int, int], int]) -> list[AjustePendiente]:
        hoy = self._reloj.hoy()
        filas: list[AjustePendiente] = []
        for registro in self._repositorio.listar_contratos_para_ajuste():
            contrato = Contrato(
                departamento_id=registro.departamento_id,
                fecha_inicio=registro.fecha_inicio,
                monto_centavos=registro.monto_centavos,
                ciclo_meses=registro.ciclo_meses,
                redondeo_centavos=registro.redondeo_centavos,
            )
            fecha_ajuste = contrato.proxima_fecha_ajuste(hoy, registro.ultimo_ajuste)
            if fecha_ajuste is None or (fecha_ajuste.year, fecha_ajuste.month) != (
                hoy.year,
                hoy.month,
            ):
                continue
            meses = tuple(
                MesBase(anio, mes, indice_ipc.get((anio, mes)))
                for anio, mes in meses_base(fecha_ajuste, registro.ciclo_meses)
            )
            variacion = None
            nueva = None
            delta = None
            if all(m.variacion_bp is not None for m in meses):
                variacion = acumular_variaciones_bp([m.variacion_bp for m in meses])
                nueva = aplicar_variacion(
                    registro.monto_centavos, variacion, registro.redondeo_centavos
                )
                delta = nueva - registro.monto_centavos
            filas.append(
                AjustePendiente(
                    id=registro.contrato_id,
                    contrato_id=registro.contrato_id,
                    departamento_id=registro.departamento_id,
                    direccion=registro.direccion,
                    piso=registro.piso,
                    depto=registro.depto,
                    inquilino=registro.inquilino,
                    fecha_ajuste=fecha_ajuste,
                    meses=meses,
                    cuota_actual_centavos=registro.monto_centavos,
                    redondeo_centavos=registro.redondeo_centavos,
                    variacion_bp=variacion,
                    cuota_nueva_centavos=nueva,
                    delta_centavos=delta,
                )
            )
        filas.sort(key=lambda f: f.unidad.lower())
        return filas
