"""Cliente HTTP para el servicio `ipc_nacional` de `api.indec.gob.ar` (ADR-0003).

Implementa `FuenteIpc` usando `urllib.request` de la biblioteca estándar:
- Timeout explícito y reintentos acotados ante fallas transitorias (red / 502-504).
- `User-Agent` identificable (`Brickly/<version>`).
- Parseo JSON directo a `Decimal` (`parse_float=Decimal`) sin pasar por `float`.
- Validación estricta del contrato JSON y errores en castellano claro sin exponer
  jamás el token en mensajes o trazas.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from brickly import VERSION
from brickly.aplicacion.sincronizacion_ipc import DatoIndiceIpc
from brickly.dominio.errores import ErrorDeNegocio

URL_BASE_INDEC = "https://api.indec.gob.ar/v1/ipc_nacional"
CODIGOS_REINTENTABLES = frozenset({502, 503, 504})

PARAMETROS_IPC_NACIONAL: dict[str, str] = {
    "clasificador": "eq.IPC",
    "nivel": "eq.Nivel General",
    "codigo": "eq.0",
    "region": "eq.Nacional",
    "tipo_de_indicador": "eq.Indice",
    "select": "periodo,anio,mes,valor,observaciones",
    "order": "anio.asc,mes.asc",
    "limit": "1000",
}


def construir_url_ipc_nacional(url_base: str = URL_BASE_INDEC) -> str:
    query = urllib.parse.urlencode(
        PARAMETROS_IPC_NACIONAL, quote_via=urllib.parse.quote
    )
    return f"{url_base}?{query}"


def parsear_respuesta_indec(cuerpo: str | bytes) -> list[DatoIndiceIpc]:
    """Valida el JSON de `ipc_nacional` y convierte `valor` directo a `Decimal`."""
    try:
        texto = (
            cuerpo.decode("utf-8")
            if isinstance(cuerpo, (bytes, bytearray))
            else cuerpo
        )
        datos = json.loads(texto, parse_float=Decimal, parse_int=int)
    except (UnicodeDecodeError, json.JSONDecodeError, InvalidOperation) as error:
        raise ErrorDeNegocio(
            "La respuesta de INDEC no es un JSON válido."
        ) from error

    if not isinstance(datos, list):
        raise ErrorDeNegocio(
            "El formato de respuesta de INDEC cambió (se esperaba una lista de períodos)."
        )
    if not datos:
        raise ErrorDeNegocio(
            "La API de INDEC devolvió una lista vacía para IPC Nacional."
        )

    resultado: list[DatoIndiceIpc] = []
    for fila in datos:
        if not isinstance(fila, dict):
            raise ErrorDeNegocio(
                "El formato de respuesta de INDEC cambió (elemento inválido en la lista)."
            )
        anio = fila.get("anio")
        mes = fila.get("mes")
        valor = fila.get("valor")

        if (
            isinstance(anio, bool)
            or not isinstance(anio, int)
            or isinstance(mes, bool)
            or not isinstance(mes, int)
        ):
            raise ErrorDeNegocio(
                "La respuesta de INDEC contiene períodos sin año o mes numérico."
            )
        if not (1 <= mes <= 12) or not (1990 <= anio <= 2100):
            raise ErrorDeNegocio(
                f"La respuesta de INDEC contiene un período fuera de rango ({anio}-{mes:02d})."
            )
        if isinstance(valor, bool) or not isinstance(valor, (Decimal, int, str)):
            raise ErrorDeNegocio(
                f"La respuesta de INDEC no trae un índice numérico válido en {anio}-{mes:02d}."
            )
        try:
            indice = valor if isinstance(valor, Decimal) else Decimal(str(valor))
        except InvalidOperation as error:
            raise ErrorDeNegocio(
                f"Índice inválido en la respuesta de INDEC para {anio}-{mes:02d}."
            ) from error
        if not indice.is_finite() or indice <= 0:
            raise ErrorDeNegocio(
                f"El índice informado por INDEC para {anio}-{mes:02d} debe ser mayor a 0."
            )
        resultado.append(DatoIndiceIpc(anio=anio, mes=mes, indice=indice))

    return resultado


class ClienteIndecHttp:
    """Adaptador HTTP para `api.indec.gob.ar/v1/ipc_nacional`."""

    def __init__(
        self,
        url_base: str = URL_BASE_INDEC,
        timeout_segundos: float = 10.0,
        max_reintentos: int = 2,
        pausa_reintento_segundos: float = 0.4,
        transporte: Callable[[urllib.request.Request, float], bytes] | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._url_base = url_base
        self._timeout = timeout_segundos
        self._max_reintentos = max(0, max_reintentos)
        self._pausa = max(0.0, pausa_reintento_segundos)
        self._transporte = transporte or self._ejecutar_request
        self._dormir = dormir

    def obtener_indices(self, token: str) -> list[DatoIndiceIpc]:
        limpio = (token or "").strip()
        if not limpio:
            raise ErrorDeNegocio(
                "No hay token de INDEC configurado. Cargalo en Configuración."
            )

        url = construir_url_ipc_nacional(self._url_base)
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {limpio}",
                "Accept": "application/json",
                "User-Agent": f"Brickly/{VERSION} (Desktop; Windows)",
            },
        )

        intentos_totales = self._max_reintentos + 1
        for intento in range(1, intentos_totales + 1):
            try:
                cuerpo = self._transporte(req, self._timeout)
                return parsear_respuesta_indec(cuerpo)
            except urllib.error.HTTPError as error:
                codigo = error.code
                if (
                    codigo in CODIGOS_REINTENTABLES
                    and intento < intentos_totales
                ):
                    self._dormir(self._pausa * intento)
                    continue
                raise _traducir_error_http(codigo) from None
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                ConnectionError,
                OSError,
            ) as error:
                if isinstance(error, ErrorDeNegocio):
                    raise
                if intento < intentos_totales:
                    self._dormir(self._pausa * intento)
                    continue
                raise _traducir_error_red(error) from None

        raise ErrorDeNegocio(
            "No se pudo consultar la API de INDEC. Intentá más tarde o cargá el IPC manualmente."
        )

    @staticmethod
    def _ejecutar_request(
        req: urllib.request.Request, timeout: float
    ) -> bytes:
        with urllib.request.urlopen(req, timeout=timeout) as respuesta:
            return respuesta.read()


def _traducir_error_http(codigo: int) -> ErrorDeNegocio:
    if codigo in (401, 403):
        return ErrorDeNegocio(
            "El token de INDEC es inválido, fue revocado o venció. Revisalo en Configuración."
        )
    if codigo == 429:
        return ErrorDeNegocio(
            "Demasiadas consultas seguidas a la API de INDEC. Esperá unos minutos e intentá de nuevo."
        )
    if 500 <= codigo <= 599:
        return ErrorDeNegocio(
            f"El servidor de INDEC no está disponible en este momento (HTTP {codigo}). "
            "Intentá más tarde o cargá el IPC manualmente."
        )
    return ErrorDeNegocio(
        f"La consulta a la API de INDEC fue rechazada (HTTP {codigo})."
    )


def _traducir_error_red(error: BaseException) -> ErrorDeNegocio:
    motivo = getattr(error, "reason", error)
    if isinstance(motivo, (TimeoutError, socket.timeout)) or isinstance(
        error, (TimeoutError, socket.timeout)
    ):
        return ErrorDeNegocio(
            "La consulta a INDEC superó el tiempo de espera. "
            "Verificá tu conexión o cargá el IPC manualmente."
        )
    return ErrorDeNegocio(
        "No se pudo conectar con api.indec.gob.ar. "
        "Verificá tu conexión a internet o cargá el IPC manualmente."
    )
