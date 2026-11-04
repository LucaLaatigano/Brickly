"""Casos de uso de Cobranzas (spec §3.4 — H1 y H2: generación, tabla del mes, atrasos, mora y pagos).

La generación es idempotente y la mora se calcula siempre en el dominio a la
fecha del `Reloj` ("a hoy"), quedando congelada en `imputaciones` al registrar
el pago (ADR-0002).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from brickly.dominio.cuota import (
    Cuota,
    EstadoCuota,
    calcular_mora_cuota,
    dias_atraso_cuota,
    estado_cuota,
    fecha_vencimiento_cuota,
    saldo_capital_cuota,
)
from brickly.dominio.departamento import nombre_unidad
from brickly.dominio.errores import ErrorDeNegocio
from brickly.dominio.pago import (
    CuotaImputable,
    MedioPago,
    Pago,
    imputar_pago_a_cuota,
)

if TYPE_CHECKING:
    from brickly.aplicacion.puertos import Reloj, RepositorioCobranzas

FiltroCobranzas = Literal["todas", "pendientes", "vencidas", "pagadas"]


@dataclass(frozen=True)
class ContratoParaCuota:
    """Contrato vigente que todavía no tiene cuota emitida en el período."""

    contrato_id: int
    departamento_id: int
    monto_centavos: int
    dia_vencimiento: int


@dataclass(frozen=True)
class RegistroCuotaMes:
    """Fila cruda leída del repositorio para una cuota."""

    cuota_id: int
    contrato_id: int
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
    dias_gracia: int = 5
    tasa_mora_bp: int = 200
    mora_pagada_centavos: int = 0


@dataclass(frozen=True)
class PreviewGeneracionCuotas:
    """Vista previa antes de generar las cuotas de `(anio, mes)` (§3.4)."""

    anio: int
    mes: int
    cuotas_a_generar: int
    total_centavos: int
    unidades_sin_contrato: int
    cuotas_existentes: int


@dataclass(frozen=True)
class ResultadoGeneracionCuotas:
    """Resultado de ejecutar la generación mensual (§3.4 y §4 F2)."""

    anio: int
    mes: int
    cuotas_generadas: int
    total_centavos: int
    unidades_sin_contrato: int


@dataclass(frozen=True)
class FilaCobranzaMes:
    """Fila de la tabla de Cobranzas del mes (§3.4).

    `id` es `cuota_id` para que `Tabla` dispare `al_click_fila(cuota_id)`.
    """

    id: int
    cuota_id: int
    contrato_id: int
    departamento_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    fecha_vencimiento: date
    monto_centavos: int
    pagado_centavos: int
    mora_centavos: int | None
    saldo_centavos: int | None
    estado: EstadoCuota
    dias_atraso: int

    @property
    def unidad(self) -> str:
        return nombre_unidad(self.direccion, self.piso, self.depto)


@dataclass(frozen=True)
class FilaAtraso:
    """Fila de la solapa Atrasos (§3.4): cuotas vencidas impagas de cualquier período."""

    id: int
    cuota_id: int
    contrato_id: int
    departamento_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    anio: int
    mes: int
    fecha_vencimiento: date
    dias_atraso: int
    cuota_centavos: int
    mora_centavos: int | None
    total_centavos: int

    @property
    def unidad(self) -> str:
        return nombre_unidad(self.direccion, self.piso, self.depto)


@dataclass(frozen=True)
class DetalleCuotaParaPago:
    """Datos listos para abrir el panel de pago lateral de 380 px (§3.4)."""

    cuota_id: int
    contrato_id: int
    departamento_id: int
    unidad: str
    inquilino: str
    anio: int
    mes: int
    fecha_vencimiento: date
    dias_atraso: int
    saldo_capital_centavos: int
    mora_centavos: int
    total_centavos: int
    fecha_sugerida: date
    medio_sugerido: MedioPago


@dataclass(frozen=True)
class DatosPago:
    """Entrada del caso de uso `registrar_pago` (§3.4)."""

    cuota_id: int
    fecha: date
    monto_centavos: int
    medio: MedioPago
    nota: str | None = None


@dataclass(frozen=True)
class ResultadoPago:
    """Confirmación devuelta tras registrar e imputar un pago."""

    pago_id: int
    cuota_id: int
    departamento_id: int
    unidad: str
    monto_centavos: int
    capital_aplicado_centavos: int
    mora_aplicada_centavos: int
    saldo_restante_centavos: int


@dataclass(frozen=True)
class ResumenCobranzasMes:
    """Totales del período mostrados encima de la tabla (§3.4)."""

    cobrado_centavos: int
    esperado_centavos: int
    cantidad_vencidas: int
    monto_vencidas_centavos: int
    cantidad_pendientes: int
    cantidad_pagadas: int
    total_cuotas: int


@dataclass(frozen=True)
class CobranzasDelMes:
    """Respuesta completa para pintar la pantalla Cobranzas en modo Mes."""

    anio: int
    mes: int
    fecha_calculo: date
    generado: bool
    preview: PreviewGeneracionCuotas
    resumen: ResumenCobranzasMes
    filas: list[FilaCobranzaMes]


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_acentos.lower()


def _coincide_filtro(fila: FilaCobranzaMes, filtro: FiltroCobranzas) -> bool:
    if filtro == "pendientes":
        return fila.estado in ("pendiente", "parcial")
    if filtro == "vencidas":
        return fila.estado == "vencida"
    if filtro == "pagadas":
        return fila.estado == "pagada"
    return True


class ServicioCobranzas:
    """Generación mensual idempotente, consulta de cobranzas/atrasos y registro de pagos."""

    def __init__(self, repositorio: RepositorioCobranzas, reloj: Reloj):
        self._repositorio = repositorio
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj.hoy()

    def periodo_actual(self) -> tuple[int, int]:
        hoy = self._reloj.hoy()
        return hoy.year, hoy.month

    def preview_generacion(self, anio: int, mes: int) -> PreviewGeneracionCuotas:
        fecha_vencimiento_cuota(anio, mes, 1)  # valida rango de año y mes
        pendientes, sin_contrato, existentes = self._repositorio.contratos_para_generar(
            anio, mes
        )
        total = sum(contrato.monto_centavos for contrato in pendientes)
        return PreviewGeneracionCuotas(
            anio=anio,
            mes=mes,
            cuotas_a_generar=len(pendientes),
            total_centavos=total,
            unidades_sin_contrato=sin_contrato,
            cuotas_existentes=existentes,
        )

    def generar_cuotas(self, anio: int, mes: int) -> ResultadoGeneracionCuotas:
        fecha_vencimiento_cuota(anio, mes, 1)
        pendientes, sin_contrato, _existentes = self._repositorio.contratos_para_generar(
            anio, mes
        )
        nuevas = [
            Cuota(
                contrato_id=contrato.contrato_id,
                anio=anio,
                mes=mes,
                fecha_vencimiento=fecha_vencimiento_cuota(
                    anio, mes, contrato.dia_vencimiento
                ),
                monto_centavos=contrato.monto_centavos,
            )
            for contrato in pendientes
        ]
        insertadas = self._repositorio.guardar_cuotas(nuevas) if nuevas else 0
        total = sum(cuota.monto_centavos for cuota in nuevas) if insertadas else 0
        return ResultadoGeneracionCuotas(
            anio=anio,
            mes=mes,
            cuotas_generadas=insertadas,
            total_centavos=total,
            unidades_sin_contrato=sin_contrato,
        )

    def del_mes(
        self,
        anio: int,
        mes: int,
        busqueda: str = "",
        filtro: FiltroCobranzas = "todas",
    ) -> CobranzasDelMes:
        hoy = self._reloj.hoy()
        preview = self.preview_generacion(anio, mes)
        registros = self._repositorio.listar_cuotas_del_mes(anio, mes)
        todas = [self._armar_fila(registro, hoy) for registro in registros]
        resumen = self._calcular_resumen(todas)

        termino = _normalizar(busqueda.strip())
        filtradas = todas
        if termino:
            filtradas = [
                fila
                for fila in filtradas
                if termino in _normalizar(fila.direccion)
                or termino in _normalizar(fila.unidad)
                or termino in _normalizar(fila.inquilino)
            ]
        filtradas = [fila for fila in filtradas if _coincide_filtro(fila, filtro)]

        return CobranzasDelMes(
            anio=anio,
            mes=mes,
            fecha_calculo=hoy,
            generado=len(todas) > 0,
            preview=preview,
            resumen=resumen,
            filas=filtradas,
        )

    def atrasos(self) -> list[FilaAtraso]:
        """Todas las cuotas vencidas impagas ordenadas por días de atraso descendente (§3.4)."""
        hoy = self._reloj.hoy()
        registros = self._repositorio.listar_cuotas_impagas()
        filas: list[FilaAtraso] = []
        for registro in registros:
            estado = estado_cuota(
                monto_centavos=registro.monto_centavos,
                pagado_centavos=registro.pagado_centavos,
                fecha_vencimiento=registro.fecha_vencimiento,
                hoy=hoy,
            )
            if estado != "vencida":
                continue
            saldo_capital = saldo_capital_cuota(
                registro.monto_centavos, registro.pagado_centavos
            )
            atraso = dias_atraso_cuota(
                monto_centavos=registro.monto_centavos,
                pagado_centavos=registro.pagado_centavos,
                fecha_vencimiento=registro.fecha_vencimiento,
                hoy=hoy,
            )
            mora = calcular_mora_cuota(
                monto_centavos=registro.monto_centavos,
                pagado_centavos=registro.pagado_centavos,
                fecha_vencimiento=registro.fecha_vencimiento,
                hoy=hoy,
                dias_gracia=registro.dias_gracia,
                tasa_mora_bp=registro.tasa_mora_bp,
            )
            filas.append(
                FilaAtraso(
                    id=registro.cuota_id,
                    cuota_id=registro.cuota_id,
                    contrato_id=registro.contrato_id,
                    departamento_id=registro.departamento_id,
                    direccion=registro.direccion,
                    piso=registro.piso,
                    depto=registro.depto,
                    inquilino=registro.inquilino,
                    anio=registro.anio,
                    mes=registro.mes,
                    fecha_vencimiento=registro.fecha_vencimiento,
                    dias_atraso=atraso,
                    cuota_centavos=saldo_capital,
                    mora_centavos=mora if mora > 0 else None,
                    total_centavos=saldo_capital + mora,
                )
            )
        filas.sort(key=lambda f: (-f.dias_atraso, f.unidad.lower(), f.anio, f.mes))
        return filas

    def preparar_pago(self, cuota_id: int) -> DetalleCuotaParaPago:
        """Arma el desglose vivo (cuota + mora a hoy) y defaults para el panel de pago."""
        hoy = self._reloj.hoy()
        registro = self._repositorio.obtener_cuota(cuota_id)
        if registro is None:
            raise ErrorDeNegocio("La cuota seleccionada no existe.")
        saldo_capital = saldo_capital_cuota(
            registro.monto_centavos, registro.pagado_centavos
        )
        if saldo_capital == 0:
            raise ErrorDeNegocio("La cuota seleccionada ya está pagada.")
        atraso = dias_atraso_cuota(
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            fecha_vencimiento=registro.fecha_vencimiento,
            hoy=hoy,
        )
        mora = calcular_mora_cuota(
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            fecha_vencimiento=registro.fecha_vencimiento,
            hoy=hoy,
            dias_gracia=registro.dias_gracia,
            tasa_mora_bp=registro.tasa_mora_bp,
        )
        medio = self._repositorio.ultimo_medio_pago() or "transferencia"
        return DetalleCuotaParaPago(
            cuota_id=registro.cuota_id,
            contrato_id=registro.contrato_id,
            departamento_id=registro.departamento_id,
            unidad=nombre_unidad(registro.direccion, registro.piso, registro.depto),
            inquilino=registro.inquilino,
            anio=registro.anio,
            mes=registro.mes,
            fecha_vencimiento=registro.fecha_vencimiento,
            dias_atraso=atraso,
            saldo_capital_centavos=saldo_capital,
            mora_centavos=mora,
            total_centavos=saldo_capital + mora,
            fecha_sugerida=hoy,
            medio_sugerido=medio,
        )

    def preparar_pago_departamento(self, departamento_id: int) -> DetalleCuotaParaPago:
        """Selecciona la cuota impaga más antigua (FIFO) de una unidad para cobrar."""
        impagas = [
            r
            for r in self._repositorio.listar_cuotas_impagas()
            if r.departamento_id == departamento_id
        ]
        if not impagas:
            raise ErrorDeNegocio("Esta unidad no tiene cuotas pendientes de cobro.")
        impagas.sort(key=lambda r: (r.fecha_vencimiento, r.anio, r.mes, r.cuota_id))
        return self.preparar_pago(impagas[0].cuota_id)

    def registrar_pago(self, datos: DatosPago) -> ResultadoPago:
        """Registra un pago y congela la mora imputada en una transacción atómica."""
        hoy = self._reloj.hoy()
        registro = self._repositorio.obtener_cuota(datos.cuota_id)
        if registro is None:
            raise ErrorDeNegocio("La cuota seleccionada no existe.")

        pago = Pago(
            contrato_id=registro.contrato_id,
            fecha=datos.fecha,
            monto_centavos=datos.monto_centavos,
            medio=datos.medio,
            nota=datos.nota,
        )
        saldo_capital = saldo_capital_cuota(
            registro.monto_centavos, registro.pagado_centavos
        )
        mora_hoy = calcular_mora_cuota(
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            fecha_vencimiento=registro.fecha_vencimiento,
            hoy=hoy,
            dias_gracia=registro.dias_gracia,
            tasa_mora_bp=registro.tasa_mora_bp,
        )
        cuota_imputable = CuotaImputable(
            cuota_id=registro.cuota_id,
            saldo_capital_centavos=saldo_capital,
            mora_centavos=mora_hoy,
        )
        imputacion = imputar_pago_a_cuota(cuota_imputable, pago.monto_centavos)
        pago_id = self._repositorio.guardar_pago(pago, [imputacion])

        unidad = nombre_unidad(registro.direccion, registro.piso, registro.depto)
        return ResultadoPago(
            pago_id=pago_id,
            cuota_id=registro.cuota_id,
            departamento_id=registro.departamento_id,
            unidad=unidad,
            monto_centavos=pago.monto_centavos,
            capital_aplicado_centavos=imputacion.monto_centavos,
            mora_aplicada_centavos=imputacion.mora_centavos,
            saldo_restante_centavos=cuota_imputable.total_centavos - pago.monto_centavos,
        )

    def _armar_fila(self, registro: RegistroCuotaMes, hoy: date) -> FilaCobranzaMes:
        estado = estado_cuota(
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            fecha_vencimiento=registro.fecha_vencimiento,
            hoy=hoy,
        )
        saldo_capital = saldo_capital_cuota(
            registro.monto_centavos, registro.pagado_centavos
        )
        atraso = dias_atraso_cuota(
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            fecha_vencimiento=registro.fecha_vencimiento,
            hoy=hoy,
        )
        if estado == "pagada":
            mora_visible = (
                registro.mora_pagada_centavos
                if registro.mora_pagada_centavos > 0
                else None
            )
            saldo_visible = None
        else:
            mora_viva = calcular_mora_cuota(
                monto_centavos=registro.monto_centavos,
                pagado_centavos=registro.pagado_centavos,
                fecha_vencimiento=registro.fecha_vencimiento,
                hoy=hoy,
                dias_gracia=registro.dias_gracia,
                tasa_mora_bp=registro.tasa_mora_bp,
            )
            mora_visible = mora_viva if mora_viva > 0 else None
            saldo_visible = saldo_capital + mora_viva

        return FilaCobranzaMes(
            id=registro.cuota_id,
            cuota_id=registro.cuota_id,
            contrato_id=registro.contrato_id,
            departamento_id=registro.departamento_id,
            direccion=registro.direccion,
            piso=registro.piso,
            depto=registro.depto,
            inquilino=registro.inquilino,
            fecha_vencimiento=registro.fecha_vencimiento,
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            mora_centavos=mora_visible,
            saldo_centavos=saldo_visible,
            estado=estado,
            dias_atraso=atraso,
        )

    def _calcular_resumen(self, filas: list[FilaCobranzaMes]) -> ResumenCobranzasMes:
        cobrado = sum(fila.pagado_centavos for fila in filas)
        esperado = sum(fila.monto_centavos for fila in filas)
        vencidas = [fila for fila in filas if fila.estado == "vencida"]
        pendientes = [fila for fila in filas if fila.estado in ("pendiente", "parcial")]
        pagadas = [fila for fila in filas if fila.estado == "pagada"]
        return ResumenCobranzasMes(
            cobrado_centavos=cobrado,
            esperado_centavos=esperado,
            cantidad_vencidas=len(vencidas),
            monto_vencidas_centavos=sum(fila.saldo_centavos or 0 for fila in vencidas),
            cantidad_pendientes=len(pendientes),
            cantidad_pagadas=len(pagadas),
            total_cuotas=len(filas),
        )
