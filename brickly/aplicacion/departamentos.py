"""Casos de uso de departamentos y sus contratos: ABM y lecturas de §3.2–§3.3.

Los DTO son la forma que consume la UI: llevar los campos finales desde ahora
(p. ej. `deuda_centavos`) permite cablear las pantallas una sola vez.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from brickly.dominio.contrato import Contrato, Inquilino
from brickly.dominio.departamento import Departamento, nombre_unidad
from brickly.dominio.errores import ErrorDeNegocio

if TYPE_CHECKING:  # evita el ciclo puertos → DTOs → puertos
    from brickly.aplicacion.puertos import Reloj, RepositorioDepartamentos

EstadoMes = Literal["pagada", "parcial", "pendiente", "vencida"]
FiltroDepartamentos = Literal["todos", "al_dia", "deben", "sin_contrato"]


@dataclass(frozen=True)
class DatosDepartamento:
    """Lo que llega del formulario de alta/edición (m² ya parseado o None)."""

    direccion: str
    piso: str | None = None
    depto: str | None = None
    m2: int | None = None
    propietario: str | None = None


@dataclass(frozen=True)
class PredeterminadosContrato:
    """Valores iniciales al abrir el formulario de contrato (§3.3 / §3.7)."""

    dia_vencimiento: int = 10
    dias_gracia: int = 5
    tasa_mora_bp: int = 200
    ciclo_meses: int = 3
    redondeo_centavos: int = 1


@dataclass(frozen=True)
class DatosContrato:
    """Datos que envía el panel de carga/edición/renovación de contrato (§3.3)."""

    inquilino_nombre: str
    fecha_inicio: date
    monto_centavos: int
    inquilino_telefono: str | None = None
    inquilino_email: str | None = None
    dia_vencimiento: int = 10
    dias_gracia: int = 5
    tasa_mora_bp: int = 200
    ciclo_meses: int = 3
    redondeo_centavos: int = 1
    fecha_fin: date | None = None


@dataclass(frozen=True)
class ContratoEnDetalle:
    """Contrato vigente listo para pintar en la solapa Contrato (§3.3)."""

    id: int
    inquilino_id: int
    inquilino_nombre: str
    inquilino_telefono: str | None
    inquilino_email: str | None
    fecha_inicio: date
    fecha_fin: date | None
    monto_centavos: int
    dia_vencimiento: int
    dias_gracia: int
    tasa_mora_bp: int
    ciclo_meses: int
    redondeo_centavos: int
    proxima_fecha_ajuste: date | None


@dataclass(frozen=True)
class FilaCuotaDepartamento:
    """Fila de la tabla de cuotas en Detalle de departamento (§3.3)."""

    id: int
    anio: int
    mes: int
    fecha_vencimiento: date
    monto_centavos: int
    pagado_centavos: int
    mora_centavos: int | None
    saldo_centavos: int | None
    estado: EstadoMes


@dataclass(frozen=True)
class PagoImputadoCuota:
    """Detalle de un pago aplicado a una cuota específica (§3.3)."""

    id: int
    fecha: date
    monto_centavos: int
    mora_centavos: int
    medio: str
    nota: str | None = None


@dataclass(frozen=True)
class FilaDepartamento:
    """Fila de la lista §3.2.

    `estado_mes` se calcula desde H1 con la cuota del mes actual;
    `deuda_centavos` queda en None hasta que mora (H2) lo calcule.
    """

    id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str | None
    cuota_vigente_centavos: int | None
    estado_mes: EstadoMes | None
    deuda_centavos: int | None
    ultimo_pago: date | None
    # Fecha de cierre del último contrato sin renovar (alerta del Panel, §3.1).
    fecha_contrato_vencido: date | None = None

    @property
    def unidad(self) -> str:
        return nombre_unidad(self.direccion, self.piso, self.depto)

    @property
    def sin_contrato(self) -> bool:
        return self.inquilino is None


@dataclass(frozen=True)
class InquilinoEnDetalle:
    nombre: str
    telefono: str | None
    email: str | None


@dataclass(frozen=True)
class DetalleDepartamento:
    """Cabecera y solapas del detalle §3.3."""

    id: int
    direccion: str
    piso: str | None
    depto: str | None
    m2: int | None
    propietario: str | None
    inquilino: InquilinoEnDetalle | None
    cuota_vigente_centavos: int | None
    deuda_centavos: int | None
    proximo_vencimiento: date | None
    contrato: ContratoEnDetalle | None = None
    estado_mes: EstadoMes | None = None
    fecha_contrato_vencido: date | None = None

    @property
    def unidad(self) -> str:
        return nombre_unidad(self.direccion, self.piso, self.depto)


@dataclass(frozen=True)
class DependenciasDepartamento:
    """Filas que el diálogo de confirmación de borrado cuenta (§3.2)."""

    contratos: int
    cuotas: int
    pagos: int


def _normalizar(texto: str) -> str:
    """«Giménez» y «gimenez» encuentran lo mismo (búsqueda de la lista)."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_acentos.lower()


def _coincide_filtro(fila: FilaDepartamento, filtro: FiltroDepartamentos) -> bool:
    # `al_dia`/`deben` se activan solos cuando cobranzas/mora llenen la deuda
    # (H1–H2); con deuda desconocida (None) no coinciden: no se puede afirmar.
    if filtro == "al_dia":
        return fila.deuda_centavos == 0
    if filtro == "deben":
        return fila.deuda_centavos is not None and fila.deuda_centavos > 0
    if filtro == "sin_contrato":
        return fila.sin_contrato
    return True


class ServicioDepartamentos:
    """ABM de departamentos y sus contratos sobre `RepositorioDepartamentos`."""

    def __init__(
        self,
        repositorio: RepositorioDepartamentos,
        reloj: Reloj | None = None,
    ):
        self._repositorio = repositorio
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj.hoy() if self._reloj is not None else date.today()

    def listar(
        self, busqueda: str = "", filtro: FiltroDepartamentos = "todos"
    ) -> list[FilaDepartamento]:
        filas = self._repositorio.listar()
        termino = _normalizar(busqueda.strip())
        if termino:
            filas = [
                fila
                for fila in filas
                if termino in _normalizar(fila.direccion)
                or termino in _normalizar(fila.unidad)
                or termino in _normalizar(fila.inquilino or "")
            ]
        return [fila for fila in filas if _coincide_filtro(fila, filtro)]

    def detalle(self, departamento_id: int) -> DetalleDepartamento:
        detalle = self._repositorio.detalle(departamento_id)
        if detalle is None:
            raise ErrorDeNegocio("El departamento no existe o ya fue eliminado.")
        return detalle

    def crear(self, datos: DatosDepartamento) -> int:
        departamento = self._departamento_de(datos)
        self._verificar_unidad_libre(departamento)
        return self._repositorio.guardar(departamento)

    def editar(self, departamento_id: int, datos: DatosDepartamento) -> None:
        self._exigir_existente(departamento_id)
        departamento = self._departamento_de(datos, id=departamento_id)
        self._verificar_unidad_libre(departamento)
        self._repositorio.actualizar(departamento)

    def eliminar(self, departamento_id: int) -> None:
        self._exigir_existente(departamento_id)
        self._repositorio.eliminar(departamento_id)

    def contar_dependencias(self, departamento_id: int) -> DependenciasDepartamento:
        return self._repositorio.contar_dependencias(departamento_id)

    # --- contratos y cuotas de la unidad (§3.3) ------------------------------

    def predeterminados_contrato(self) -> PredeterminadosContrato:
        return self._repositorio.predeterminados_contrato()

    def cargar_contrato(self, departamento_id: int, datos: DatosContrato) -> int:
        self._exigir_existente(departamento_id)
        inquilino, contrato = self._contrato_de(departamento_id, datos)
        return self._repositorio.guardar_contrato(departamento_id, inquilino, contrato)

    def editar_contrato(self, departamento_id: int, datos: DatosContrato) -> None:
        detalle = self.detalle(departamento_id)
        if detalle.contrato is None:
            raise ErrorDeNegocio("Esta unidad no tiene un contrato vigente para editar.")
        inquilino, contrato = self._contrato_de(
            departamento_id,
            datos,
            contrato_id=detalle.contrato.id,
            inquilino_id=detalle.contrato.inquilino_id,
        )
        self._repositorio.actualizar_contrato(detalle.contrato.id, inquilino, contrato)

    def nuevo_contrato(self, departamento_id: int, datos: DatosContrato) -> int:
        """Cierra el contrato vigente y crea el nuevo sin borrar historial (§3.3)."""
        self._exigir_existente(departamento_id)
        inquilino, contrato = self._contrato_de(departamento_id, datos)
        return self._repositorio.reemplazar_contrato(
            departamento_id=departamento_id,
            fecha_cierre=self.hoy(),
            inquilino=inquilino,
            contrato=contrato,
        )

    def listar_cuotas(self, departamento_id: int) -> list[FilaCuotaDepartamento]:
        self._exigir_existente(departamento_id)
        return self._repositorio.listar_cuotas_departamento(departamento_id)

    def pagos_de_cuota(self, cuota_id: int) -> list[PagoImputadoCuota]:
        return self._repositorio.listar_pagos_cuota(cuota_id)

    # --- helpers internos ----------------------------------------------------

    def _departamento_de(
        self, datos: DatosDepartamento, id: int | None = None
    ) -> Departamento:
        return Departamento(
            direccion=datos.direccion,
            piso=datos.piso,
            depto=datos.depto,
            m2=datos.m2,
            propietario=datos.propietario,
            id=id,
        )

    def _contrato_de(
        self,
        departamento_id: int,
        datos: DatosContrato,
        contrato_id: int | None = None,
        inquilino_id: int | None = None,
    ) -> tuple[Inquilino, Contrato]:
        inquilino = Inquilino(
            id=inquilino_id,
            nombre=datos.inquilino_nombre,
            telefono=datos.inquilino_telefono,
            email=datos.inquilino_email,
        )
        contrato = Contrato(
            id=contrato_id,
            departamento_id=departamento_id,
            inquilino_id=inquilino_id,
            fecha_inicio=datos.fecha_inicio,
            fecha_fin=datos.fecha_fin,
            monto_centavos=datos.monto_centavos,
            dia_vencimiento=datos.dia_vencimiento,
            dias_gracia=datos.dias_gracia,
            tasa_mora_bp=datos.tasa_mora_bp,
            ciclo_meses=datos.ciclo_meses,
            redondeo_centavos=datos.redondeo_centavos,
        )
        return inquilino, contrato

    def _exigir_existente(self, departamento_id: int) -> None:
        if self._repositorio.obtener(departamento_id) is None:
            raise ErrorDeNegocio("El departamento no existe o ya fue eliminado.")

    def _verificar_unidad_libre(self, departamento: Departamento) -> None:
        duplicado = self._repositorio.existe_unidad(
            departamento.direccion,
            departamento.piso,
            departamento.depto,
            excluyendo=departamento.id,
        )
        if duplicado:
            raise ErrorDeNegocio(f"Ya existe un departamento en «{departamento.unidad}».")
