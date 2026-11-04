"""Casos de uso de sincronización automática de IPC con INDEC (H6 — ADR-0003).

Responsabilidades:
- Administrar el token de API (guardar, borrar, estado/vencimiento JWT, probar).
- Calcular variaciones en puntos básicos desde la serie de índices oficiales
  usando `variacion_bp_desde_indices` (dominio puro, Decimal half-up a 1 bp).
- Previsualizar cada período frente a `ipc_valores` clasificando en:
  `nuevo`, `actualizado`, `sin_cambios` o `manual_protegido`.
- Importar en forma atómica e idempotente sin pisar valores manuales salvo
  confirmación explícita (`reemplazar_manuales=True`).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.dominio.ipc import (
    IpcMensual,
    indice_a_milesimos,
    variacion_bp_desde_indices,
)

if TYPE_CHECKING:
    from brickly.aplicacion.puertos import (
        AlmacenTokenIpc,
        FuenteIpc,
        Reloj,
        RepositorioAjustes,
        RepositorioConfiguracion,
    )

CLAVE_ULTIMA_SINCRONIZACION = "indec_ultima_sincronizacion"

EstadoItemSincronizacion = Literal[
    "nuevo", "actualizado", "sin_cambios", "manual_protegido"
]


@dataclass(frozen=True)
class DatoIndiceIpc:
    """Punto mensual de la serie de índices devuelta por la fuente externa."""

    anio: int
    mes: int
    indice: Decimal


@dataclass(frozen=True)
class IpcSincronizado:
    """Variación mensual calculada e índice en milésimos listos para persistir."""

    anio: int
    mes: int
    variacion_bp: int
    indice_milesimos: int

    def __post_init__(self) -> None:
        # Reutiliza las invariantes de dominio de IpcMensual.
        IpcMensual(
            anio=self.anio,
            mes=self.mes,
            variacion_bp=self.variacion_bp,
            indice_milesimos=self.indice_milesimos,
        )


@dataclass(frozen=True)
class ItemPreviewIpc:
    """Fila de la vista previa de sincronización antes de tocar la base."""

    anio: int
    mes: int
    variacion_bp: int
    indice_milesimos: int
    variacion_actual_bp: int | None
    origen_actual: str | None
    estado: EstadoItemSincronizacion
    seleccionado_por_defecto: bool

    @property
    def periodo(self) -> tuple[int, int]:
        return self.anio, self.mes


@dataclass(frozen=True)
class PreviewSincronizacionIpc:
    """Resultado completo de `previsualizar()`."""

    fecha_consulta: date
    items: tuple[ItemPreviewIpc, ...]

    @property
    def nuevos(self) -> list[ItemPreviewIpc]:
        return [i for i in self.items if i.estado == "nuevo"]

    @property
    def actualizados(self) -> list[ItemPreviewIpc]:
        return [i for i in self.items if i.estado == "actualizado"]

    @property
    def sin_cambios(self) -> list[ItemPreviewIpc]:
        return [i for i in self.items if i.estado == "sin_cambios"]

    @property
    def manuales_protegidos(self) -> list[ItemPreviewIpc]:
        return [i for i in self.items if i.estado == "manual_protegido"]

    @property
    def periodos_por_defecto(self) -> list[tuple[int, int]]:
        return [i.periodo for i in self.items if i.seleccionado_por_defecto]


@dataclass(frozen=True)
class ResultadoSincronizacionIpc:
    """Resumen devuelto tras `importar()`."""

    nuevos: int
    actualizados: int
    reemplazados_manuales: int
    omitidos: int

    @property
    def total_importados(self) -> int:
        return self.nuevos + self.actualizados + self.reemplazados_manuales


@dataclass(frozen=True)
class EstadoTokenIpc:
    """Estado del token de API INDEC para mostrar en Configuración y Ajustes IPC."""

    configurado: bool
    token_enmascarado: str | None
    fecha_emision: date | None
    fecha_vencimiento: date | None
    vencido: bool
    dias_restantes: int | None
    ultima_sincronizacion: date | None
    motivo_deshabilitado: str | None

    @property
    def habilitado(self) -> bool:
        return self.configurado and not self.vencido


@dataclass(frozen=True)
class ResultadoPruebaIpc:
    """Resultado de probar la conexión contra la API de INDEC."""

    ok: bool
    mensaje: str
    ultimo_periodo: tuple[int, int] | None = None
    ultima_variacion_bp: int | None = None
    fecha_vencimiento: date | None = None


def normalizar_token_ipc(token: str) -> str:
    """Limpia espacios o prefijo 'Bearer ' y valida que el token no esté vacío."""
    limpio = (token or "").strip()
    if limpio.lower().startswith("bearer "):
        limpio = limpio[7:].strip()
    if not limpio:
        raise ErrorDeValidacion(
            "Ingresá el token de acceso de INDEC.", campo="token_indec"
        )
    if any(ch.isspace() for ch in limpio):
        raise ErrorDeValidacion(
            "El token no puede contener espacios ni saltos de línea.",
            campo="token_indec",
        )
    return limpio


def enmascarar_token(token: str) -> str:
    """Enmascara el token dejando visibles solo los extremos para identificación."""
    limpio = token.strip()
    if len(limpio) <= 10:
        return "••••••••"
    return f"{limpio[:4]}••••••{limpio[-4:]}"


def extraer_fechas_jwt(token: str) -> tuple[date | None, date | None]:
    """Extrae `(fecha_emision, fecha_vencimiento)` de un JWT sin verificar firma.

    Si el token no tiene formato JWT o carece de `iat`/`exp`, devuelve `(None, None)`.
    """
    partes = token.strip().split(".")
    if len(partes) != 3:
        return None, None
    payload_b64 = partes[1]
    relleno = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        crudo = base64.urlsafe_b64decode((payload_b64 + relleno).encode("ascii"))
        datos = json.loads(crudo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(datos, dict):
        return None, None

    emision = _timestamp_a_fecha(datos.get("iat"))
    vencimiento = _timestamp_a_fecha(datos.get("exp"))
    return emision, vencimiento


def _timestamp_a_fecha(valor: object) -> date | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    if valor <= 0:
        return None
    try:
        return datetime.fromtimestamp(valor, tz=timezone.utc).date()
    except (OSError, OverflowError, ValueError):
        return None


def calcular_serie_desde_indices(
    datos: list[DatoIndiceIpc],
) -> list[IpcSincronizado]:
    """Calcula la serie de variaciones mensuales a partir de índices consecutivos.

    Solo calcula la variación entre dos puntos cuando son meses calendario
    consecutivos (`(anio_t * 12 + mes_t) - (anio_{t-1} * 12 + mes_{t-1}) == 1`).
    Devuelve la lista ordenada de más reciente a más antigua.
    """
    if not datos:
        return []

    por_periodo: dict[tuple[int, int], DatoIndiceIpc] = {}
    for dato in datos:
        if not (1 <= dato.mes <= 12) or not (1990 <= dato.anio <= 2100):
            raise ErrorDeValidacion(
                f"Período inválido en la respuesta de INDEC: {dato.anio}-{dato.mes:02d}.",
                campo="periodo",
            )
        por_periodo[(dato.anio, dato.mes)] = dato

    ordenados = [por_periodo[clave] for clave in sorted(por_periodo)]
    resultado: list[IpcSincronizado] = []
    for anterior, actual in zip(ordenados, ordenados[1:]):
        indice_mes_ant = anterior.anio * 12 + (anterior.mes - 1)
        indice_mes_act = actual.anio * 12 + (actual.mes - 1)
        if indice_mes_act - indice_mes_ant != 1:
            continue
        if actual.anio < 2000:
            continue
        variacion_bp = variacion_bp_desde_indices(anterior.indice, actual.indice)
        milesimos = indice_a_milesimos(actual.indice)
        resultado.append(
            IpcSincronizado(
                anio=actual.anio,
                mes=actual.mes,
                variacion_bp=variacion_bp,
                indice_milesimos=milesimos,
            )
        )

    resultado.sort(key=lambda item: (item.anio, item.mes), reverse=True)
    return resultado


class ServicioSincronizacionIpc:
    """Caso de uso para configurar el token, previsualizar e importar IPC desde INDEC."""

    def __init__(
        self,
        repositorio: RepositorioAjustes,
        fuente: FuenteIpc,
        almacen_token: AlmacenTokenIpc,
        reloj: Reloj,
        configuracion: RepositorioConfiguracion | None = None,
    ):
        self._repositorio = repositorio
        self._fuente = fuente
        self._almacen_token = almacen_token
        self._reloj = reloj
        self._configuracion = configuracion

    # --- Token y estado ------------------------------------------------------

    def estado_token(self) -> EstadoTokenIpc:
        hoy = self._reloj.hoy()
        ultima_sync = self._leer_ultima_sincronizacion()
        token = self._almacen_token.obtener_token()
        if not token or not token.strip():
            return EstadoTokenIpc(
                configurado=False,
                token_enmascarado=None,
                fecha_emision=None,
                fecha_vencimiento=None,
                vencido=False,
                dias_restantes=None,
                ultima_sincronizacion=ultima_sync,
                motivo_deshabilitado=(
                    "Configurá el token de INDEC en Configuración para sincronizar."
                ),
            )

        limpio = token.strip()
        emision, vencimiento = extraer_fechas_jwt(limpio)
        vencido = vencimiento is not None and vencimiento < hoy
        dias_restantes = (
            (vencimiento - hoy).days if vencimiento is not None else None
        )
        motivo = None
        if vencido and vencimiento is not None:
            motivo = (
                f"El token de INDEC venció el {vencimiento.strftime('%d/%m/%Y')}; "
                "renovalo en Configuración."
            )

        return EstadoTokenIpc(
            configurado=True,
            token_enmascarado=enmascarar_token(limpio),
            fecha_emision=emision,
            fecha_vencimiento=vencimiento,
            vencido=vencido,
            dias_restantes=dias_restantes,
            ultima_sincronizacion=ultima_sync,
            motivo_deshabilitado=motivo,
        )

    def guardar_token(self, token: str) -> EstadoTokenIpc:
        limpio = normalizar_token_ipc(token)
        self._almacen_token.guardar_token(limpio)
        return self.estado_token()

    def borrar_token(self) -> EstadoTokenIpc:
        self._almacen_token.borrar_token()
        return self.estado_token()

    def probar_conexion(self, token: str | None = None) -> ResultadoPruebaIpc:
        token_a_usar = (
            normalizar_token_ipc(token)
            if token is not None and token.strip()
            else self._obtener_token_activo()
        )
        _, vencimiento = extraer_fechas_jwt(token_a_usar)
        hoy = self._reloj.hoy()
        if vencimiento is not None and vencimiento < hoy:
            raise ErrorDeNegocio(
                f"El token de INDEC venció el {vencimiento.strftime('%d/%m/%Y')}. "
                "Generá uno nuevo en api.indec.gob.ar."
            )

        datos = self._fuente.obtener_indices(token_a_usar)
        serie = calcular_serie_desde_indices(datos)
        if not serie:
            raise ErrorDeNegocio(
                "La API de INDEC respondió sin períodos suficientes para calcular el IPC."
            )
        ultimo = serie[0]
        return ResultadoPruebaIpc(
            ok=True,
            mensaje="Conexión verificada con INDEC.",
            ultimo_periodo=(ultimo.anio, ultimo.mes),
            ultima_variacion_bp=ultimo.variacion_bp,
            fecha_vencimiento=vencimiento,
        )

    # --- Previsualización e importación --------------------------------------

    def consultar_remoto(self) -> list[DatoIndiceIpc]:
        """Consulta la serie de índices a la fuente externa (sin tocar SQLite; apto para hilo de fondo)."""
        token = self._obtener_token_activo()
        hoy = self._reloj.hoy()
        _, vencimiento = extraer_fechas_jwt(token)
        if vencimiento is not None and vencimiento < hoy:
            raise ErrorDeNegocio(
                f"El token de INDEC venció el {vencimiento.strftime('%d/%m/%Y')}; "
                "renovalo en Configuración."
            )
        return self._fuente.obtener_indices(token)

    def previsualizar(
        self, indices: list[DatoIndiceIpc] | None = None
    ) -> PreviewSincronizacionIpc:
        hoy = self._reloj.hoy()
        datos = indices if indices is not None else self.consultar_remoto()
        serie = calcular_serie_desde_indices(datos)
        if not serie:
            raise ErrorDeNegocio(
                "No se recibieron variaciones mensuales válidas desde INDEC."
            )

        actuales = {
            (r.anio, r.mes): r for r in self._repositorio.listar_ipc()
        }
        items: list[ItemPreviewIpc] = []
        for punto in serie:
            existente = actuales.get((punto.anio, punto.mes))
            if existente is None:
                estado: EstadoItemSincronizacion = "nuevo"
                seleccionado = True
                var_actual = None
                origen_actual = None
            elif existente.variacion_bp == punto.variacion_bp:
                estado = "sin_cambios"
                seleccionado = False
                var_actual = existente.variacion_bp
                origen_actual = existente.origen
            elif existente.origen == "manual":
                estado = "manual_protegido"
                seleccionado = False
                var_actual = existente.variacion_bp
                origen_actual = existente.origen
            else:
                estado = "actualizado"
                seleccionado = True
                var_actual = existente.variacion_bp
                origen_actual = existente.origen

            items.append(
                ItemPreviewIpc(
                    anio=punto.anio,
                    mes=punto.mes,
                    variacion_bp=punto.variacion_bp,
                    indice_milesimos=punto.indice_milesimos,
                    variacion_actual_bp=var_actual,
                    origen_actual=origen_actual,
                    estado=estado,
                    seleccionado_por_defecto=seleccionado,
                )
            )

        return PreviewSincronizacionIpc(
            fecha_consulta=hoy,
            items=tuple(items),
        )

    def importar(
        self,
        periodos_seleccionados: list[tuple[int, int]],
        reemplazar_manuales: bool = False,
        preview: PreviewSincronizacionIpc | None = None,
    ) -> ResultadoSincronizacionIpc:
        if not periodos_seleccionados:
            raise ErrorDeNegocio("Seleccioná al menos un período para importar.")

        vista_previa = preview if preview is not None else self.previsualizar()
        por_periodo = {item.periodo: item for item in vista_previa.items}
        actuales = {
            (r.anio, r.mes): r for r in self._repositorio.listar_ipc()
        }

        seleccion_unica: list[tuple[int, int]] = []
        vistos: set[tuple[int, int]] = set()
        for periodo in periodos_seleccionados:
            if periodo not in vistos:
                vistos.add(periodo)
                seleccion_unica.append(periodo)

        a_guardar: list[IpcSincronizado] = []
        nuevos = 0
        actualizados = 0
        reemplazados_manuales = 0
        omitidos = 0

        for periodo in seleccion_unica:
            item = por_periodo.get(periodo)
            if item is None:
                raise ErrorDeNegocio(
                    f"El período {periodo[0]}-{periodo[1]:02d} no está en la vista previa."
                )
            existente = actuales.get(periodo)
            sincronizado = IpcSincronizado(
                anio=item.anio,
                mes=item.mes,
                variacion_bp=item.variacion_bp,
                indice_milesimos=item.indice_milesimos,
            )

            if existente is None:
                a_guardar.append(sincronizado)
                nuevos += 1
            elif existente.variacion_bp == item.variacion_bp:
                # Si ya era 'api' pero no tenía indice_milesimos, lo completamos sin cambiar variación
                if (
                    existente.origen == "api"
                    and existente.indice_milesimos != item.indice_milesimos
                ):
                    a_guardar.append(sincronizado)
                omitidos += 1
            elif existente.origen == "manual":
                if not reemplazar_manuales:
                    raise ErrorDeNegocio(
                        "Seleccionaste períodos con carga manual; confirmá el reemplazo "
                        "para sobrescribirlos."
                    )
                a_guardar.append(sincronizado)
                reemplazados_manuales += 1
            else:
                a_guardar.append(sincronizado)
                actualizados += 1

        hoy = self._reloj.hoy()
        if a_guardar:
            self._repositorio.guardar_ipc_masivo(
                a_guardar,
                reemplazar_manuales=reemplazar_manuales,
                fecha_carga=hoy,
            )

        self._registrar_ultima_sincronizacion(hoy)
        return ResultadoSincronizacionIpc(
            nuevos=nuevos,
            actualizados=actualizados,
            reemplazados_manuales=reemplazados_manuales,
            omitidos=omitidos,
        )

    # --- Internos ------------------------------------------------------------

    def _obtener_token_activo(self) -> str:
        token = self._almacen_token.obtener_token()
        if not token or not token.strip():
            raise ErrorDeNegocio(
                "No hay token de INDEC configurado. Cargalo en Configuración."
            )
        return token.strip()

    def _leer_ultima_sincronizacion(self) -> date | None:
        if self._configuracion is None:
            return None
        mapa = self._configuracion.cargar()
        valor = mapa.get(CLAVE_ULTIMA_SINCRONIZACION, "").strip()
        if not valor:
            return None
        try:
            return date.fromisoformat(valor[:10])
        except ValueError:
            return None

    def _registrar_ultima_sincronizacion(self, fecha: date) -> None:
        if self._configuracion is None:
            return
        self._configuracion.actualizar(
            {CLAVE_ULTIMA_SINCRONIZACION: fecha.isoformat()}
        )
