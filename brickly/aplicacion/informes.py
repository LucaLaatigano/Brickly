"""Casos de uso de Informes (spec §3.6 — H4 y H7).

La UI no arma CSV, libros Excel ni copia bases: acá se leen los datos (una
consulta por informe; los totales viven en `aplicacion`/dominio) y se arman
tanto el texto CSV como el `LibroExportable` puro en centavos; `infraestructura`
escribe los archivos (`.csv`, `.xlsx`, `.sqlite3`) a través de los puertos
`EscritorArchivos`, `EscritorExcel` y `Respaldador`.

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
from typing import TYPE_CHECKING, Literal

from brickly.aplicacion.cobranzas import CobranzasDelMes, FilaAtraso
from brickly.dominio.cuota import (
    calcular_mora_cuota,
    dias_atraso_cuota,
    estado_cuota,
    saldo_capital_cuota,
)
from brickly.dominio.departamento import nombre_unidad
from brickly.dominio.errores import ErrorDeNegocio
from brickly.dominio.ipc import meses_base

if TYPE_CHECKING:
    from brickly.aplicacion.cobranzas import ServicioCobranzas
    from brickly.aplicacion.configuracion import ServicioConfiguracion
    from brickly.aplicacion.puertos import (
        EscritorArchivos,
        EscritorExcel,
        Reloj,
        RepositorioInformes,
        Respaldador,
    )

# Nombres de meses para el CSV y Excel (la capa ui tiene los suyos en `formato.py`;
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

MESES_ABREV = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

_ETIQUETA_MEDIO = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "deposito": "Depósito",
    "otro": "Otro",
}

_PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")

TipoColumnaExcel = Literal["texto", "fecha", "moneda", "entero"]
ValorCeldaExcel = str | int | date | None


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
class RegistroDepartamentoInforme:
    """Fila cruda de departamento + contrato vigente + fechas clave (H7 Resumen)."""

    departamento_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str | None = None
    fecha_inicio_vigente: date | None = None
    cuota_vigente_centavos: int | None = None
    ultima_fecha_fin: date | None = None
    ultimo_pago: date | None = None


@dataclass(frozen=True)
class RegistroPagoInforme:
    """Fila cruda de pago e imputación a cuota (H7 Pagos)."""

    pago_id: int
    fecha: date
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    medio: str
    nota: str | None
    monto_pago_centavos: int
    anio_cuota: int | None
    mes_cuota: int | None
    capital_imputado_centavos: int
    mora_imputada_centavos: int


@dataclass(frozen=True)
class RegistroContratoInforme:
    """Fila cruda de contrato vigente o histórico (H7 Contratos)."""

    contrato_id: int
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    fecha_inicio: date
    fecha_fin: date | None
    monto_centavos: int
    dia_vencimiento: int
    dias_gracia: int
    tasa_mora_bp: int
    ciclo_meses: int
    redondeo_centavos: int


@dataclass(frozen=True)
class RegistroAjusteInforme:
    """Fila cruda de ajuste IPC aplicado (H7 Ajustes IPC)."""

    ajuste_id: int
    fecha_aplicacion: date
    direccion: str
    piso: str | None
    depto: str | None
    inquilino: str
    anio_base: int
    mes_base: int
    meses_ciclo: int
    variacion_bp: int
    cuota_antes_centavos: int
    cuota_despues_centavos: int
    es_override: bool
    motivo_override: str | None = None


@dataclass(frozen=True)
class ColumnaExcel:
    """Definición de columna para `HojaExportable`.

    En columnas `moneda`, los valores en `filas` y `totales` viajan en centavos
    enteros (`int` o `None`); el adaptador de infraestructura solo los formatea.
    """

    titulo: str
    tipo: TipoColumnaExcel = "texto"


@dataclass(frozen=True)
class FilaExcel:
    """Fila de datos de una hoja. `resaltada=True` marca cuotas/unidades vencidas."""

    valores: tuple[ValorCeldaExcel, ...]
    resaltada: bool = False


@dataclass(frozen=True)
class HojaExportable:
    """Hoja pura lista para exportar a `.xlsx`."""

    nombre: str
    columnas: tuple[ColumnaExcel, ...]
    filas: tuple[FilaExcel, ...]
    totales: tuple[ValorCeldaExcel, ...] | None = None


@dataclass(frozen=True)
class LibroExportable:
    """Libro Excel completo armado en `aplicacion` con cálculos en centavos."""

    fecha_generacion: date
    hojas: tuple[HojaExportable, ...]

    def hoja(self, nombre: str) -> HojaExportable:
        for h in self.hojas:
            if h.nombre == nombre:
                return h
        raise KeyError(nombre)


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


# --- sanitización y formatos puros --------------------------------------------


def sanitizar_texto_excel(texto: str | None) -> str:
    """Prefija `'` si el texto empieza con `=`, `+`, `-` o `@` (anti-fórmulas)."""
    if not texto:
        return ""
    limpio = texto.lstrip()
    if texto.startswith(_PREFIJOS_FORMULA) or limpio.startswith(("=", "+", "-", "@")):
        return f"'{texto}"
    return texto


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


def _porcentaje_bp(bp: int) -> str:
    signo = "-" if bp < 0 else ""
    enteros, resto = divmod(abs(bp), 100)
    texto = f"{signo}{enteros},{resto:02d} %"
    return sanitizar_texto_excel(texto)


def _rango_meses_base(anio_base: int, mes_base: int, meses_ciclo: int) -> str:
    anio_ini, mes_ini = anio_base, mes_base
    anio_fin, mes_0 = divmod(anio_base * 12 + mes_base - 1 + meses_ciclo - 1, 12)
    mes_fin = mes_0 + 1
    if (anio_ini, mes_ini) == (anio_fin, mes_fin):
        return f"{MESES_ABREV[mes_ini - 1]} {anio_ini}"
    if anio_ini == anio_fin:
        return f"{MESES_ABREV[mes_ini - 1]}–{MESES_ABREV[mes_fin - 1]} {anio_ini}"
    return (
        f"{MESES_ABREV[mes_ini - 1]} {anio_ini}"
        f"–{MESES_ABREV[mes_fin - 1]} {anio_fin}"
    )


# --- armado de CSV (puro y testeable) ----------------------------------------


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
                sanitizar_texto_excel(
                    nombre_unidad(registro.direccion, registro.piso, registro.depto)
                ),
                sanitizar_texto_excel(registro.inquilino),
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
                sanitizar_texto_excel(fila.unidad),
                sanitizar_texto_excel(fila.inquilino),
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
                sanitizar_texto_excel(fila.unidad),
                sanitizar_texto_excel(fila.inquilino),
                _periodo(fila.anio, fila.mes),
                _fecha(fila.fecha_vencimiento),
                str(fila.dias_atraso),
                _monto(fila.cuota_centavos),
                _monto(fila.mora_centavos or 0),
                _monto(fila.total_centavos),
            ]
        )
    return _csv(filas)


# --- armado de LibroExportable (H7, puro en centavos) -------------------------


def armar_libro_excel(
    *,
    departamentos: list[RegistroDepartamentoInforme],
    cuotas: list[RegistroEstadoCuenta],
    pagos: list[RegistroPagoInforme],
    contratos: list[RegistroContratoInforme],
    ajustes: list[RegistroAjusteInforme],
    hoy: date,
) -> LibroExportable:
    """Construye el `LibroExportable` con todas las hojas y totales en centavos."""
    deuda_capital_por_depto: dict[int, int] = {}
    mora_por_depto: dict[int, int] = {}
    deptos_con_vencidas: set[int] = set()

    filas_cuotas: list[FilaExcel] = []
    tot_cuotas_monto = 0
    tot_cuotas_pagado = 0
    tot_cuotas_mora = 0
    tot_cuotas_saldo = 0

    deudas_crudas: list[tuple[int, date, str, FilaExcel, int, int, int]] = []

    for r in cuotas:
        unidad = sanitizar_texto_excel(nombre_unidad(r.direccion, r.piso, r.depto))
        inquilino = sanitizar_texto_excel(r.inquilino)
        estado = estado_cuota(
            monto_centavos=r.monto_centavos,
            pagado_centavos=r.pagado_centavos,
            fecha_vencimiento=r.fecha_vencimiento,
            hoy=hoy,
        )
        es_vencida = estado == "vencida"
        if estado == "pagada":
            mora = r.mora_pagada_centavos
            saldo = 0
        else:
            capital_impago = saldo_capital_cuota(r.monto_centavos, r.pagado_centavos)
            mora = calcular_mora_cuota(
                monto_centavos=r.monto_centavos,
                pagado_centavos=r.pagado_centavos,
                fecha_vencimiento=r.fecha_vencimiento,
                hoy=hoy,
                dias_gracia=r.dias_gracia,
                tasa_mora_bp=r.tasa_mora_bp,
            )
            saldo = capital_impago + mora
            deuda_capital_por_depto[r.departamento_id] = (
                deuda_capital_por_depto.get(r.departamento_id, 0) + capital_impago
            )
            mora_por_depto[r.departamento_id] = (
                mora_por_depto.get(r.departamento_id, 0) + mora
            )
            if es_vencida:
                deptos_con_vencidas.add(r.departamento_id)
            atraso = dias_atraso_cuota(
                r.monto_centavos,
                r.pagado_centavos,
                r.fecha_vencimiento,
                hoy,
            )
            fila_deuda = FilaExcel(
                valores=(
                    unidad,
                    inquilino,
                    _periodo(r.anio, r.mes),
                    r.fecha_vencimiento,
                    _estado(estado),
                    atraso,
                    capital_impago,
                    mora,
                    saldo,
                ),
                resaltada=es_vencida,
            )
            deudas_crudas.append(
                (-atraso, r.fecha_vencimiento, unidad.lower(), fila_deuda, capital_impago, mora, saldo)
            )

        tot_cuotas_monto += r.monto_centavos
        tot_cuotas_pagado += r.pagado_centavos
        tot_cuotas_mora += mora
        tot_cuotas_saldo += saldo
        filas_cuotas.append(
            FilaExcel(
                valores=(
                    unidad,
                    inquilino,
                    _periodo(r.anio, r.mes),
                    r.fecha_vencimiento,
                    r.monto_centavos,
                    r.pagado_centavos,
                    mora,
                    saldo,
                    _estado(estado),
                ),
                resaltada=es_vencida,
            )
        )

    # 1. Hoja Resumen
    filas_resumen: list[FilaExcel] = []
    tot_res_cuota = 0
    tot_res_capital = 0
    tot_res_mora = 0
    tot_res_total = 0
    for d in departamentos:
        unidad = sanitizar_texto_excel(nombre_unidad(d.direccion, d.piso, d.depto))
        if d.inquilino is not None:
            inquilino_txt = sanitizar_texto_excel(d.inquilino)
            contrato_txt = (
                f"Vigente (desde {_fecha(d.fecha_inicio_vigente)})"
                if d.fecha_inicio_vigente is not None
                else "Vigente"
            )
        else:
            inquilino_txt = "Sin contrato"
            if d.ultima_fecha_fin is not None and d.ultima_fecha_fin < hoy:
                contrato_txt = f"Vencido ({_fecha(d.ultima_fecha_fin)})"
            else:
                contrato_txt = "Sin contrato"
        cuota_vigente = d.cuota_vigente_centavos
        deuda_cap = deuda_capital_por_depto.get(d.departamento_id, 0)
        mora_dep = mora_por_depto.get(d.departamento_id, 0)
        total_dep = deuda_cap + mora_dep
        tot_res_cuota += cuota_vigente or 0
        tot_res_capital += deuda_cap
        tot_res_mora += mora_dep
        tot_res_total += total_dep
        filas_resumen.append(
            FilaExcel(
                valores=(
                    unidad,
                    inquilino_txt,
                    contrato_txt,
                    cuota_vigente,
                    deuda_cap,
                    mora_dep,
                    total_dep,
                    d.ultimo_pago,
                ),
                resaltada=d.departamento_id in deptos_con_vencidas,
            )
        )

    hoja_resumen = HojaExportable(
        nombre="Resumen",
        columnas=(
            ColumnaExcel("Unidad", "texto"),
            ColumnaExcel("Inquilino", "texto"),
            ColumnaExcel("Contrato", "texto"),
            ColumnaExcel("Cuota vigente", "moneda"),
            ColumnaExcel("Deuda capital", "moneda"),
            ColumnaExcel("Mora", "moneda"),
            ColumnaExcel("Total", "moneda"),
            ColumnaExcel("Último pago", "fecha"),
        ),
        filas=tuple(filas_resumen),
        totales=(
            "Totales",
            None,
            None,
            tot_res_cuota,
            tot_res_capital,
            tot_res_mora,
            tot_res_total,
            None,
        ),
    )

    # 2. Hoja Deudas (ordenadas por atraso descendente)
    deudas_crudas.sort(key=lambda item: (item[0], item[1], item[2]))
    filas_deudas = [item[3] for item in deudas_crudas]
    tot_deuda_cap = sum(item[4] for item in deudas_crudas)
    tot_deuda_mora = sum(item[5] for item in deudas_crudas)
    tot_deuda_total = sum(item[6] for item in deudas_crudas)

    hoja_deudas = HojaExportable(
        nombre="Deudas",
        columnas=(
            ColumnaExcel("Unidad", "texto"),
            ColumnaExcel("Inquilino", "texto"),
            ColumnaExcel("Período", "texto"),
            ColumnaExcel("Vence", "fecha"),
            ColumnaExcel("Estado", "texto"),
            ColumnaExcel("Días de atraso", "entero"),
            ColumnaExcel("Capital", "moneda"),
            ColumnaExcel("Mora a hoy", "moneda"),
            ColumnaExcel("Total", "moneda"),
        ),
        filas=tuple(filas_deudas),
        totales=(
            "Totales",
            None,
            None,
            None,
            None,
            None,
            tot_deuda_cap,
            tot_deuda_mora,
            tot_deuda_total,
        ),
    )

    # 3. Hoja Pagos
    filas_pagos: list[FilaExcel] = []
    tot_pago_cap = 0
    tot_pago_mora = 0
    tot_pago_imputado = 0
    for p in pagos:
        unidad = sanitizar_texto_excel(nombre_unidad(p.direccion, p.piso, p.depto))
        inquilino = sanitizar_texto_excel(p.inquilino)
        periodo = (
            _periodo(p.anio_cuota, p.mes_cuota)
            if p.anio_cuota is not None and p.mes_cuota is not None
            else ""
        )
        medio = _ETIQUETA_MEDIO.get(p.medio, p.medio.capitalize())
        total_imp = p.capital_imputado_centavos + p.mora_imputada_centavos
        tot_pago_cap += p.capital_imputado_centavos
        tot_pago_mora += p.mora_imputada_centavos
        tot_pago_imputado += total_imp
        filas_pagos.append(
            FilaExcel(
                valores=(
                    p.fecha,
                    unidad,
                    inquilino,
                    periodo,
                    medio,
                    p.capital_imputado_centavos,
                    p.mora_imputada_centavos,
                    total_imp,
                    p.monto_pago_centavos,
                    sanitizar_texto_excel(p.nota),
                ),
            )
        )

    hoja_pagos = HojaExportable(
        nombre="Pagos",
        columnas=(
            ColumnaExcel("Fecha", "fecha"),
            ColumnaExcel("Unidad", "texto"),
            ColumnaExcel("Inquilino", "texto"),
            ColumnaExcel("Período imputado", "texto"),
            ColumnaExcel("Medio", "texto"),
            ColumnaExcel("Capital imputado", "moneda"),
            ColumnaExcel("Mora cobrada", "moneda"),
            ColumnaExcel("Total imputado", "moneda"),
            ColumnaExcel("Total del pago", "moneda"),
            ColumnaExcel("Nota", "texto"),
        ),
        filas=tuple(filas_pagos),
        totales=(
            "Totales",
            None,
            None,
            None,
            None,
            tot_pago_cap,
            tot_pago_mora,
            tot_pago_imputado,
            None,
            None,
        ),
    )

    # 4. Hoja Cuotas
    hoja_cuotas = HojaExportable(
        nombre="Cuotas",
        columnas=(
            ColumnaExcel("Unidad", "texto"),
            ColumnaExcel("Inquilino", "texto"),
            ColumnaExcel("Período", "texto"),
            ColumnaExcel("Vence", "fecha"),
            ColumnaExcel("Cuota", "moneda"),
            ColumnaExcel("Pagado", "moneda"),
            ColumnaExcel("Mora", "moneda"),
            ColumnaExcel("Saldo", "moneda"),
            ColumnaExcel("Estado", "texto"),
        ),
        filas=tuple(filas_cuotas),
        totales=(
            "Totales",
            None,
            None,
            None,
            tot_cuotas_monto,
            tot_cuotas_pagado,
            tot_cuotas_mora,
            tot_cuotas_saldo,
            None,
        ),
    )

    # 5. Hoja Contratos
    filas_contratos: list[FilaExcel] = []
    tot_contratos_cuota = 0
    for c in contratos:
        unidad = sanitizar_texto_excel(nombre_unidad(c.direccion, c.piso, c.depto))
        inquilino = sanitizar_texto_excel(c.inquilino)
        estado_contrato = "Vigente" if c.fecha_fin is None else "Cerrado"
        ciclo = "1 mes" if c.ciclo_meses == 1 else f"{c.ciclo_meses} meses"
        redondeo = "Centavos" if c.redondeo_centavos == 1 else "$ 100"
        tot_contratos_cuota += c.monto_centavos
        filas_contratos.append(
            FilaExcel(
                valores=(
                    unidad,
                    inquilino,
                    estado_contrato,
                    c.fecha_inicio,
                    c.fecha_fin,
                    c.monto_centavos,
                    c.dia_vencimiento,
                    c.dias_gracia,
                    _porcentaje_bp(c.tasa_mora_bp),
                    ciclo,
                    redondeo,
                ),
            )
        )

    hoja_contratos = HojaExportable(
        nombre="Contratos",
        columnas=(
            ColumnaExcel("Unidad", "texto"),
            ColumnaExcel("Inquilino", "texto"),
            ColumnaExcel("Estado", "texto"),
            ColumnaExcel("Inicio", "fecha"),
            ColumnaExcel("Fin", "fecha"),
            ColumnaExcel("Cuota", "moneda"),
            ColumnaExcel("Día vencimiento", "entero"),
            ColumnaExcel("Días gracia", "entero"),
            ColumnaExcel("Mora mensual", "texto"),
            ColumnaExcel("Ciclo IPC", "texto"),
            ColumnaExcel("Redondeo", "texto"),
        ),
        filas=tuple(filas_contratos),
        totales=(
            "Totales",
            None,
            None,
            None,
            None,
            tot_contratos_cuota,
            None,
            None,
            None,
            None,
            None,
        ),
    )

    # 6. Hoja Ajustes IPC
    filas_ajustes: list[FilaExcel] = []
    tot_aj_antes = 0
    tot_aj_despues = 0
    tot_aj_dif = 0
    for a in ajustes:
        unidad = sanitizar_texto_excel(nombre_unidad(a.direccion, a.piso, a.depto))
        inquilino = sanitizar_texto_excel(a.inquilino)
        dif = a.cuota_despues_centavos - a.cuota_antes_centavos
        tot_aj_antes += a.cuota_antes_centavos
        tot_aj_despues += a.cuota_despues_centavos
        tot_aj_dif += dif
        filas_ajustes.append(
            FilaExcel(
                valores=(
                    a.fecha_aplicacion,
                    unidad,
                    inquilino,
                    _rango_meses_base(a.anio_base, a.mes_base, a.meses_ciclo),
                    _porcentaje_bp(a.variacion_bp),
                    a.cuota_antes_centavos,
                    a.cuota_despues_centavos,
                    dif,
                    "Ajustado a mano" if a.es_override else "IPC",
                    sanitizar_texto_excel(a.motivo_override),
                ),
            )
        )

    hoja_ajustes = HojaExportable(
        nombre="Ajustes IPC",
        columnas=(
            ColumnaExcel("Fecha", "fecha"),
            ColumnaExcel("Unidad", "texto"),
            ColumnaExcel("Inquilino", "texto"),
            ColumnaExcel("Meses base", "texto"),
            ColumnaExcel("IPC aplicado", "texto"),
            ColumnaExcel("Cuota antes", "moneda"),
            ColumnaExcel("Cuota después", "moneda"),
            ColumnaExcel("Diferencia", "moneda"),
            ColumnaExcel("Origen", "texto"),
            ColumnaExcel("Motivo", "texto"),
        ),
        filas=tuple(filas_ajustes),
        totales=(
            "Totales",
            None,
            None,
            None,
            None,
            tot_aj_antes,
            tot_aj_despues,
            tot_aj_dif,
            None,
            None,
        ),
    )

    return LibroExportable(
        fecha_generacion=hoy,
        hojas=(
            hoja_resumen,
            hoja_deudas,
            hoja_pagos,
            hoja_cuotas,
            hoja_contratos,
            hoja_ajustes,
        ),
    )


# --- servicio -----------------------------------------------------------------


class ServicioInformes:
    """Arma los CSV, el `LibroExportable` y orquesta el respaldo."""

    def __init__(
        self,
        repositorio: RepositorioInformes,
        cobranzas: ServicioCobranzas,
        configuracion: ServicioConfiguracion,
        respaldador: Respaldador,
        escritor: EscritorArchivos,
        reloj: Reloj,
        escritor_excel: EscritorExcel | None = None,
    ):
        self._repositorio = repositorio
        self._cobranzas = cobranzas
        self._configuracion = configuracion
        self._respaldador = respaldador
        self._escritor = escritor
        self._reloj = reloj
        self._escritor_excel = escritor_excel

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

    def armar_libro_completo(self) -> LibroExportable:
        """Construye el `LibroExportable` completo a la fecha del reloj."""
        departamentos = self._repositorio.listar_departamentos_resumen()
        if not departamentos:
            raise ErrorDeNegocio(
                "No hay datos para exportar. Cargá al menos un departamento."
            )
        return armar_libro_excel(
            departamentos=departamentos,
            cuotas=self._repositorio.listar_estado_cuenta(),
            pagos=self._repositorio.listar_pagos_informe(),
            contratos=self._repositorio.listar_contratos_informe(),
            ajustes=self._repositorio.listar_ajustes_informe(),
            hoy=self._reloj.hoy(),
        )

    def exportar_excel_completo(self, ruta: Path | str) -> None:
        """Exporta el libro `.xlsx` completo (H7)."""
        if self._escritor_excel is None:
            raise ErrorDeNegocio("El exportador de Excel no está configurado.")
        libro = self.armar_libro_completo()
        self._escritor_excel.escribir(ruta, libro)

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

