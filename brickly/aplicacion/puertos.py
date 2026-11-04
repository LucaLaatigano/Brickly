"""Puertos: lo que la aplicación necesita del mundo (ADR-0001).

Acá van los `Protocol`; `brickly.infraestructura` los implementa y `main.py`
decide qué implementación entra. Los tests inyectan dobles sin tocar SQLite.
"""

from datetime import date
from pathlib import Path
from typing import Protocol

from brickly.aplicacion.ajustes import (
    ContratoParaAjuste,
    FilaHistorialAjuste,
    RegistroIpc,
)
from brickly.aplicacion.cobranzas import ContratoParaCuota, RegistroCuotaMes
from brickly.aplicacion.constancias import (
    ConstanciaPago,
    CuotaPagadaDisponible,
    RegistroConstanciaCuota,
)
from brickly.aplicacion.departamentos import (
    DependenciasDepartamento,
    DetalleDepartamento,
    FilaCuotaDepartamento,
    FilaDepartamento,
    PagoImputadoCuota,
    PredeterminadosContrato,
)
from brickly.aplicacion.informes import (
    LibroExportable,
    RegistroAjusteInforme,
    RegistroContratoInforme,
    RegistroDepartamentoInforme,
    RegistroEstadoCuenta,
    RegistroPagoInforme,
)
from brickly.aplicacion.sincronizacion_ipc import DatoIndiceIpc, IpcSincronizado
from brickly.dominio.contrato import Contrato, Inquilino
from brickly.dominio.cuota import Cuota
from brickly.dominio.departamento import Departamento
from brickly.dominio.ipc import AjusteCalculado, IpcMensual
from brickly.dominio.pago import ImputacionPago, MedioPago, Pago


class Reloj(Protocol):
    """El "hoy" del negocio. Inyectable para testear mora sin viajar en el tiempo."""

    def hoy(self) -> date: ...


class RepositorioDepartamentos(Protocol):
    """Persistencia de departamentos y sus contratos (la implementa infraestructura)."""

    def listar(self) -> list[FilaDepartamento]: ...

    def obtener(self, departamento_id: int) -> Departamento | None: ...

    def detalle(self, departamento_id: int) -> DetalleDepartamento | None: ...

    def guardar(self, departamento: Departamento) -> int: ...

    def actualizar(self, departamento: Departamento) -> None: ...

    def eliminar(self, departamento_id: int) -> None: ...

    def existe_unidad(
        self,
        direccion: str,
        piso: str | None,
        depto: str | None,
        excluyendo: int | None = None,
    ) -> bool: ...

    def contar_dependencias(self, departamento_id: int) -> DependenciasDepartamento: ...

    def predeterminados_contrato(self) -> PredeterminadosContrato: ...

    def guardar_contrato(
        self, departamento_id: int, inquilino: Inquilino, contrato: Contrato
    ) -> int: ...

    def actualizar_contrato(
        self, contrato_id: int, inquilino: Inquilino, contrato: Contrato
    ) -> None: ...

    def reemplazar_contrato(
        self,
        departamento_id: int,
        fecha_cierre: date,
        inquilino: Inquilino,
        contrato: Contrato,
    ) -> int: ...

    def listar_cuotas_departamento(
        self, departamento_id: int
    ) -> list[FilaCuotaDepartamento]: ...

    def listar_pagos_cuota(self, cuota_id: int) -> list[PagoImputadoCuota]: ...


class RepositorioCobranzas(Protocol):
    """Persistencia para la generación, listado de cuotas/atrasos y registro de pagos."""

    def contratos_para_generar(
        self, anio: int, mes: int
    ) -> tuple[list[ContratoParaCuota], int, int]: ...

    def guardar_cuotas(self, cuotas: list[Cuota]) -> int: ...

    def listar_cuotas_del_mes(self, anio: int, mes: int) -> list[RegistroCuotaMes]: ...

    def listar_cuotas_impagas(self) -> list[RegistroCuotaMes]: ...

    def obtener_cuota(self, cuota_id: int) -> RegistroCuotaMes | None: ...

    def ultimo_medio_pago(self) -> MedioPago | None: ...

    def guardar_pago(
        self, pago: Pago, imputaciones: list[ImputacionPago]
    ) -> int: ...


class RepositorioAjustes(Protocol):
    """Persistencia de IPC mensual, contratos a ajustar e historial de ajustes."""

    def listar_ipc(self) -> list[RegistroIpc]: ...

    def obtener_ipc(self, ipc_id: int) -> RegistroIpc | None: ...

    def existe_ipc(self, anio: int, mes: int) -> bool: ...

    def guardar_ipc(self, ipc: IpcMensual) -> int: ...

    def actualizar_ipc(self, ipc_id: int, variacion_bp: int) -> None: ...

    def eliminar_ipc(self, ipc_id: int) -> None: ...

    def guardar_ipc_masivo(
        self,
        items: list[IpcSincronizado],
        reemplazar_manuales: bool = False,
        fecha_carga: date | None = None,
    ) -> int: ...

    def listar_contratos_para_ajuste(self) -> list[ContratoParaAjuste]: ...

    def guardar_ajustes(self, ajustes: list[AjusteCalculado]) -> None: ...

    def listar_historial(self) -> list[FilaHistorialAjuste]: ...


class FuenteIpc(Protocol):
    """Fuente externa de la serie de índices IPC Nacional (API INDEC, ADR-0003)."""

    def obtener_indices(self, token: str) -> list[DatoIndiceIpc]: ...


class AlmacenTokenIpc(Protocol):
    """Almacén seguro del token de acceso a la API de INDEC (fuera de SQLite)."""

    def obtener_token(self) -> str | None: ...

    def guardar_token(self, token: str) -> None: ...

    def borrar_token(self) -> None: ...


class RepositorioConfiguracion(Protocol):
    """Valores sueltos de la instalación (tabla `configuracion`, clave/valor)."""

    def cargar(self) -> dict[str, str]: ...

    def actualizar(self, valores: dict[str, str]) -> None: ...


class RepositorioInformes(Protocol):
    """Lecturas tabulares para los informes exportables (§3.6 — H4 y H7)."""

    def contar_departamentos(self) -> int: ...

    def contar_cuotas(self) -> int: ...

    def listar_estado_cuenta(
        self, departamento_id: int | None = None
    ) -> list[RegistroEstadoCuenta]: ...

    def listar_departamentos_resumen(self) -> list[RegistroDepartamentoInforme]: ...

    def listar_pagos_informe(self) -> list[RegistroPagoInforme]: ...

    def listar_contratos_informe(self) -> list[RegistroContratoInforme]: ...

    def listar_ajustes_informe(self) -> list[RegistroAjusteInforme]: ...


class EscritorArchivos(Protocol):
    """Escritura física de un archivo de texto en una ruta elegida por el usuario."""

    def escribir(self, ruta: Path | str, contenido: str) -> None: ...


class EscritorExcel(Protocol):
    """Escritura física de un `LibroExportable` en un archivo `.xlsx` (H7)."""

    def escribir(self, ruta: Path | str, libro: LibroExportable) -> None: ...


class Respaldador(Protocol):
    """Copia segura de la base (la implementa infraestructura con el backup API)."""

    def respaldar(self, destino: Path | str) -> None: ...


class RepositorioConstancias(Protocol):
    """Lecturas para constancias de pago mensual por cuota (H8 — ADR-0004)."""

    def listar_pagadas_del_mes(
        self, anio: int, mes: int
    ) -> list[CuotaPagadaDisponible]: ...

    def obtener_constancia(self, cuota_id: int) -> RegistroConstanciaCuota | None: ...


class GeneradorPdf(Protocol):
    """Render y escritura atómica de una `ConstanciaPago` en un archivo `.pdf` (H8)."""

    def generar(self, documento: ConstanciaPago, ruta: Path | str) -> None: ...



