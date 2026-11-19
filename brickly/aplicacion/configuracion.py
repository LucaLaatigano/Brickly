"""Casos de uso de Configuración (spec §3.7 — H4).

Los predeterminados de contrato son **valores de instalación**: viajan a la
tabla `configuracion` (clave/valor) y se usan como valores iniciales al crear
contratos nuevos; cambiar uno no toca contratos existentes. El recordatorio de
respaldo y la fecha del último respaldo viven en la misma tabla.

Las claves de `configuracion` (documentadas en la migración 0001):
`vencimiento_dia`, `gracia_dias`, `mora_bp`, `redondeo_centavos`,
`admin_nombre`, `admin_telefono`, `admin_email`, `ultimo_respaldo`,
`respaldo_recordatorio_dias`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from brickly.dominio.errores import ErrorDeValidacion

if TYPE_CHECKING:
    from brickly.aplicacion.puertos import (
        FirmaAdminGuardada,
        Reloj,
        RepositorioConfiguracion,
    )

# Redondeo de cuota: 1 = centavos (default), 100 = $ 100 (ADR-0002 §2).
REDONDEO_CENTAVOS = 1
REDONDEO_CIEN_PESOS = 100


@dataclass(frozen=True)
class ConfiguracionInstalacion:
    """Valores vigentes con los defaults de la instalación ya aplicados."""

    dia_vencimiento: int = 10
    dias_gracia: int = 5
    tasa_mora_bp: int = 200
    redondeo_centavos: int = REDONDEO_CENTAVOS
    admin_nombre: str | None = None
    admin_telefono: str | None = None
    admin_email: str | None = None
    respaldo_recordatorio_dias: int = 14
    ultimo_respaldo: date | None = None


@dataclass(frozen=True)
class DatosConfiguracion:
    """Lo que llega del formulario de Configuración (ya parseado)."""

    dia_vencimiento: int
    dias_gracia: int
    tasa_mora_bp: int
    redondeo_centavos: int
    respaldo_recordatorio_dias: int
    admin_nombre: str | None = None
    admin_telefono: str | None = None
    admin_email: str | None = None


def _entero(mapa: dict[str, str], clave: str, default: int) -> int:
    try:
        return int(mapa[clave])
    except (KeyError, ValueError):
        return default


def _texto(mapa: dict[str, str], clave: str) -> str | None:
    valor = mapa.get(clave, "").strip()
    return valor or None


def _fecha(mapa: dict[str, str], clave: str) -> date | None:
    try:
        return date.fromisoformat(mapa[clave])
    except (KeyError, ValueError):
        return None


def es_imagen_firma_valida(datos: bytes) -> bool:
    """Verifica por magic bytes que `datos` corresponda a PNG, JPEG, WebP o BMP."""
    if not datos:
        return False
    if datos.startswith(b"\x89PNG\r\n\x1a\n") and len(datos) > 8:
        return True
    if datos.startswith(b"\xff\xd8\xff") and len(datos) > 3:
        return True
    if len(datos) > 12 and datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return True
    if len(datos) >= 14 and datos.startswith(b"BM"):
        return True
    return False


class ServicioConfiguracion:
    """Lectura/escritura validada de los valores de la instalación."""

    def __init__(self, repositorio: RepositorioConfiguracion, reloj: Reloj):
        self._repositorio = repositorio
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj.hoy()

    def cargar(self) -> ConfiguracionInstalacion:
        mapa = self._repositorio.cargar()
        return ConfiguracionInstalacion(
            dia_vencimiento=_entero(mapa, "vencimiento_dia", 10),
            dias_gracia=_entero(mapa, "gracia_dias", 5),
            tasa_mora_bp=_entero(mapa, "mora_bp", 200),
            redondeo_centavos=_entero(
                mapa, "redondeo_centavos", REDONDEO_CENTAVOS
            ),
            admin_nombre=_texto(mapa, "admin_nombre"),
            admin_telefono=_texto(mapa, "admin_telefono"),
            admin_email=_texto(mapa, "admin_email"),
            respaldo_recordatorio_dias=_entero(
                mapa, "respaldo_recordatorio_dias", 14
            ),
            ultimo_respaldo=_fecha(mapa, "ultimo_respaldo"),
        )

    def guardar(self, datos: DatosConfiguracion) -> None:
        """Valida y persiste todo junto (una sola escritura, todo o nada)."""
        if not 1 <= datos.dia_vencimiento <= 28:
            raise ErrorDeValidacion(
                "El día de vencimiento debe estar entre 1 y 28.",
                campo="vencimiento_dia",
            )
        if datos.dias_gracia < 0:
            raise ErrorDeValidacion(
                "Los días de gracia no pueden ser negativos.",
                campo="gracia_dias",
            )
        if not 0 <= datos.tasa_mora_bp <= 10_000:
            raise ErrorDeValidacion(
                "La tasa de mora debe estar entre 0 % y 100 %.",
                campo="mora_bp",
            )
        if datos.redondeo_centavos not in (REDONDEO_CENTAVOS, REDONDEO_CIEN_PESOS):
            raise ErrorDeValidacion(
                "El redondeo de cuota debe ser «Centavos» o «$ 100».",
                campo="redondeo_centavos",
            )
        if datos.respaldo_recordatorio_dias < 1:
            raise ErrorDeValidacion(
                "El recordatorio de respaldo debe ser de al menos 1 día.",
                campo="respaldo_recordatorio_dias",
            )

        self._repositorio.actualizar(
            {
                "vencimiento_dia": str(datos.dia_vencimiento),
                "gracia_dias": str(datos.dias_gracia),
                "mora_bp": str(datos.tasa_mora_bp),
                "redondeo_centavos": str(datos.redondeo_centavos),
                "respaldo_recordatorio_dias": str(datos.respaldo_recordatorio_dias),
                "admin_nombre": (datos.admin_nombre or "").strip(),
                "admin_telefono": (datos.admin_telefono or "").strip(),
                "admin_email": (datos.admin_email or "").strip(),
            }
        )

    # --- firma (foto/imagen) del administrador -------------------------------

    def obtener_firma(self) -> FirmaAdminGuardada | None:
        return self._repositorio.obtener_firma()

    def guardar_firma(
        self, nombre_archivo: str, contenido: bytes
    ) -> FirmaAdminGuardada:
        nombre = (nombre_archivo or "").strip()
        if not nombre:
            raise ErrorDeValidacion(
                "El nombre del archivo de firma no puede estar vacío.",
                campo="firma_imagen",
            )
        if not isinstance(contenido, (bytes, bytearray)) or not es_imagen_firma_valida(
            bytes(contenido)
        ):
            raise ErrorDeValidacion(
                "El archivo seleccionado no es una imagen válida (usá PNG, JPG, WebP o BMP).",
                campo="firma_imagen",
            )
        datos_imagen = bytes(contenido)
        self._repositorio.guardar_firma(nombre, datos_imagen)
        guardada = self._repositorio.obtener_firma()
        if guardada is None:
            raise ErrorDeValidacion(
                "No se pudo guardar la firma en la base de datos.",
                campo="firma_imagen",
            )
        return guardada

    def borrar_firma(self) -> None:
        self._repositorio.borrar_firma()

    # --- respaldo ------------------------------------------------------------

    def ultimo_respaldo(self) -> date | None:
        return _fecha(self._repositorio.cargar(), "ultimo_respaldo")

    def registrar_respaldo(self, fecha: date) -> None:
        self._repositorio.actualizar({"ultimo_respaldo": fecha.isoformat()})

