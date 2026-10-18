"""Casos de uso de Informes (spec §3.6 — H4).

La UI no arma CSV ni copia bases: acá se leen los datos (una consulta por
informe; los totales viven en `aplicacion`/dominio) y se arma el texto CSV con
formato de exportación; `infraestructura` escribe el archivo y hace la copia
segura de SQLite (puertos `EscritorArchivos` y `Respaldador`).

Formato del CSV (pensado para Excel en es-AR): separador `;`, decimales con
coma, sin separador de miles, fechas `dd/mm/aaaa`, períodos `octubre 2026`.
El `EscritorArchivosSistema` graba con `utf-8-sig` para que Excel respete los
acentos.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from gestion.aplicacion.cobranzas import CobranzasDelMes, FilaAtraso
from gestion.dominio.cuota import (
    calcular_mora_cuota,
    estado_cuota,
    saldo_capital_cuota,
)
from gestion.dominio.departamento import nombre_unidad
from gestion.dominio.errores import ErrorDeNegocio

if TYPE_CHECKING:
    from gestion.aplicacion.configuracion import ServicioConfiguracion
    from gestion.aplicacion.cobranzas import ServicioCobranzas
    from gestion.aplicacion.puertos import (
        EscritorArchivos,
        Reloj,
        RepositorioInformes,
        Respaldador,
    )

# Nombres de meses para el CSV (la capa ui tiene los suyos en `formato.py`;
# `aplicacion` no importa ui — duplicar acá es deliberado y está testeado).
MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


@dataclass(frozen=True)
class RegistroEstadoCuenta:
    """Fila cruda de cuota + contrato + unidad para el estado de cuenta."""

    departamento_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    anio: int
    mes: int
    fecha_vencimiento: date
    monto_centavos: int
    pagado_centavos: int
    mora_pagada_centavos: int
    dias_gracia: int
    tasa_mora_bp: int


@dataclass(frozen=True)
class EstadoInformes:
    """Lo que la pantalla Informes necesita para pintar botones y motivos."""

    anio: int
    mes: int
    fecha_calculo: date
    hay_departamentos: bool
    hay_cuotas: bool
    cobranzas_generadas: bool
    hay_morosos: bool
    ultimo_respaldo: date | None


# --- armado de CSV (puro y testeable) ----------------------------------------


def _csv(filas: list[list[str]]) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerows(filas)
    return salida.getvalue()


def _monto(centavos: int) -> str:
    """`1234,56` — número pelado para que Excel lo sume (sin `$` ni miles)."""
    signo = "-" if centavos < 0 else ""
    enteros, resto = divmod(abs(centavos), 100)
    return f"{signo}{enteros},{resto:02d}"


def _fecha(fecha: date) -> str:
    return fecha.strftime("%d/%m/%Y")


def _periodo(anio: int, mes: int) -> str:
    return f"{MESES[mes - 1]} {anio}"


def _estado(estado: str) -> str:
    return estado.capitalize()


def csv_estado_cuenta(registros: list[RegistroEstadoCuenta], hoy: date) -> str:
    """Cuotas de todas las unidades con pagado, mora viva y saldo a `hoy`."""
    filas = [
        ["Unidad", "Inquilino", "Período", "Vence", "Cuota", "Pagado", "Mora", "Saldo", "Estado"]
    ]
    for registro in registros:
        estado = estado_cuota(
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            fecha_vencimiento=registro.fecha_vencimiento,
            hoy=hoy,
        )
        if estado == "pagada":
            mora = registro.mora_pagada_centavos
            saldo = 0
        else:
            mora = calcular_mora_cuota(
                monto_centavos=registro.monto_centavos,
                pagado_centavos=registro.pagado_centavos,
                fecha_vencimiento=registro.fecha_vencimiento,
                hoy=hoy,
                dias_gracia=registro.dias_gracia,
                tasa_mora_bp=registro.tasa_mora_bp,
            )
            saldo = saldo_capital_cuota(
                registro.monto_centavos, registro.pagado_centavos
            ) + mora
        filas.append(
            [
                nombre_unidad(registro.direccion, registro.piso, registro.depto),
                registro.inquilino,
                _periodo(registro.anio, registro.mes),
                _fecha(registro.fecha_vencimiento),
                _monto(registro.monto_centavos),
                _monto(registro.pagado_centavos),
                _monto(mora),
                _monto(saldo),
                _estado(estado),
            ]
        )
    return _csv(filas)


def csv_cobranzas_del_mes(datos: CobranzasDelMes) -> str:
    """Las cuotas del período mostrado en Cobranzas, con su estado de cobro."""
    filas = [
        ["Unidad", "Inquilino", "Vence", "Cuota", "Mora", "Saldo", "Estado"]
    ]
    for fila in datos.filas:
        filas.append(
            [
                fila.unidad,
                fila.inquilino,
                _fecha(fila.fecha_vencimiento),
                _monto(fila.monto_centavos),
                _monto(fila.mora_centavos or 0),
                _monto(fila.saldo_centavos or 0),
                _estado(fila.estado),
            ]
        )
    return _csv(filas)


def csv_morosos(filas_atraso: list[FilaAtraso]) -> str:
    """Cuotas vencidas impagas de cualquier período, ordenadas por atraso."""
    filas = [
        ["Unidad", "Inquilino", "Período", "Vence", "Días", "Cuota", "Mora hoy", "Total"]
    ]
    for fila in filas_atraso:
        filas.append(
            [
                fila.unidad,
                fila.inquilino,
                _periodo(fila.anio, fila.mes),
                _fecha(fila.fecha_vencimiento),
                str(fila.dias_atraso),
                _monto(fila.cuota_centavos),
                _monto(fila.mora_centavos or 0),
                _monto(fila.total_centavos),
            ]
        )
    return _csv(filas)


# --- servicio -----------------------------------------------------------------


class ServicioInformes:
    """Arma los CSV y orquesta el respaldo (la escritura física es de infra)."""

    def __init__(
        self,
        repositorio: RepositorioInformes,
        cobranzas: ServicioCobranzas,
        configuracion: ServicioConfiguracion,
        respaldador: Respaldador,
        escritor: EscritorArchivos,
        reloj: Reloj,
    ):
        self._repositorio = repositorio
        self._cobranzas = cobranzas
        self._configuracion = configuracion
        self._respaldador = respaldador
        self._escritor = escritor
        self._reloj = reloj

    def estado(self) -> EstadoInformes:
        """Qué se puede exportar ahora y cuándo fue el último respaldo."""
        anio, mes = self._cobranzas.periodo_actual()
        return EstadoInformes(
            anio=anio,
            mes=mes,
            fecha_calculo=self._reloj.hoy(),
            hay_departamentos=self._repositorio.contar_departamentos() > 0,
            hay_cuotas=self._repositorio.contar_cuotas() > 0,
            cobranzas_generadas=(
                self._cobranzas.preview_generacion(anio, mes).cuotas_existentes > 0
            ),
            hay_morosos=bool(self._cobranzas.atrasos()),
            ultimo_respaldo=self._configuracion.ultimo_respaldo(),
        )

    def exportar_estado_cuenta(
        self, ruta: Path | str, departamento_id: int | None = None
    ) -> None:
        """Estado de cuenta de todas las unidades, o de una sola (§3.3)."""
        registros = self._repositorio.listar_estado_cuenta(departamento_id)
        if not registros:
            raise ErrorDeNegocio(
                "No hay cuotas para exportar. Generá primero las cuotas del mes."
            )
        self._escritor.escribir(ruta, csv_estado_cuenta(registros, self._reloj.hoy()))

    def exportar_cobranzas_del_mes(self, ruta: Path | str) -> None:
        anio, mes = self._cobranzas.periodo_actual()
        datos = self._cobranzas.del_mes(anio, mes)
        if not datos.generado:
            raise ErrorDeNegocio(
                f"No hay cuotas generadas de {_periodo(anio, mes)}."
            )
        self._escritor.escribir(ruta, csv_cobranzas_del_mes(datos))

    def exportar_morosos(self, ruta: Path | str) -> None:
        filas = self._cobranzas.atrasos()
        if not filas:
            raise ErrorDeNegocio("No hay morosos para exportar.")
        self._escritor.escribir(ruta, csv_morosos(filas))

    def respaldar(self, ruta: Path | str) -> None:
        """Copia segura de la base (backup API de SQLite, implementa infra) y
        registra la fecha del último respaldo."""
        self._respaldador.respaldar(ruta)
        self._configuracion.registrar_respaldo(self._reloj.hoy())
