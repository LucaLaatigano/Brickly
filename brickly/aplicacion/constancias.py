"""Casos de uso de Constancias de pago mensual en PDF (H8 — ADR-0004).

Reglas de negocio:
- La constancia es por **unidad + período** (`cuota_id`), nunca un estado de
  cuenta general ni un certificado de libre deuda.
- Solo se habilita cuando la cuota está en estado `pagada` (capital totalmente
  imputado). Si está `pendiente`, `parcial` o `vencida`, se bloquea informando
  el estado y el saldo pendiente.
- El inquilino que figura es el del contrato de esa cuota, aunque el contrato
  haya sido cerrado o renovado después.
- Por cada pago imputado a la cuota se informa solo la porción imputada a esta
  cuota (capital + mora), sin inflar el monto si el pago cubrió varias cuotas.
- La firma visual al pie resuelve entre `departamentos.propietario` y
  `admin_nombre` de Configuración bajo el rol `Propietario/a o Administrador/a`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from brickly.dominio.cuota import (
    calcular_mora_cuota,
    estado_cuota,
    saldo_capital_cuota,
)
from brickly.dominio.departamento import nombre_unidad
from brickly.dominio.errores import ErrorDeNegocio

if TYPE_CHECKING:
    from brickly.aplicacion.configuracion import ServicioConfiguracion
    from brickly.aplicacion.puertos import (
        GeneradorPdf,
        Reloj,
        RepositorioConstancias,
    )

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

_ETIQUETA_MEDIO = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "deposito": "Depósito",
    "otro": "Otro",
}

TITULO_CONSTANCIA = "Constancia de pago"
ROL_FIRMA_CONSTANCIA = "Propietario/a o Administrador/a"
LEYENDA_PIE_CONSTANCIA = (
    "La presente constancia certifica el pago de la cuota del período "
    "indicado y no implica que la unidad esté libre de otras obligaciones."
)
LEYENDA_NO_FISCAL = "Documento no válido como factura ni comprobante fiscal."


@dataclass(frozen=True)
class RegistroPagoConstancia:
    """Fila cruda de un pago imputado a una cuota específica."""

    pago_id: int
    fecha: date
    medio: str
    capital_centavos: int
    mora_centavos: int
    nota: str | None = None


@dataclass(frozen=True)
class RegistroConstanciaCuota:
    """Datos crudos de la cuota, su contrato, su unidad y sus pagos imputados."""

    cuota_id: int
    contrato_id: int
    departamento_id: int
    direccion: str
    piso: str | None
    depto: str | None
    propietario: str | None
    inquilino: str
    anio: int
    mes: int
    fecha_vencimiento: date
    monto_centavos: int
    pagado_centavos: int
    mora_pagada_centavos: int
    dias_gracia: int
    tasa_mora_bp: int
    pagos: tuple[RegistroPagoConstancia, ...]


@dataclass(frozen=True)
class CuotaPagadaDisponible:
    """Resumen de una cuota pagada elegible para emitir constancia en un período."""

    cuota_id: int
    departamento_id: int
    unidad: str
    inquilino: str
    anio: int
    mes: int
    capital_centavos: int
    mora_centavos: int
    total_centavos: int


@dataclass(frozen=True)
class PagoConstancia:
    """Detalle de un pago aplicado a la cuota dentro de la constancia."""

    pago_id: int
    fecha: date
    medio: str
    medio_etiqueta: str
    capital_centavos: int
    mora_centavos: int
    monto_imputado_centavos: int
    nota: str | None = None


@dataclass(frozen=True)
class ConstanciaPago:
    """DTO puro listo para previsualizar en UI o renderizar a PDF."""

    cuota_id: int
    departamento_id: int
    titulo: str
    unidad: str
    inquilino: str
    anio: int
    mes: int
    periodo: str
    fecha_vencimiento: date
    capital_centavos: int
    mora_centavos: int
    total_centavos: int
    pagos: tuple[PagoConstancia, ...]
    fecha_emision: date
    admin_nombre: str | None
    admin_telefono: str | None
    admin_email: str | None
    propietario_nombre: str | None
    firma_nombre: str | None
    firma_rol: str
    leyenda_pie: str
    leyenda_no_fiscal: str
    nombre_archivo_sugerido: str


def _formatear_pesos_error(centavos: int) -> str:
    enteros, resto = divmod(abs(centavos), 100)
    miles = f"{enteros:,}".replace(",", ".")
    return f"$ {miles},{resto:02d}" if resto else f"$ {miles}"


def _slug_ascii(texto: str) -> str:
    reemplazado = texto.replace("º", "").replace("°", "")
    normalizado = (
        unicodedata.normalize("NFKD", reemplazado)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    limpio = re.sub(r"[^a-z0-9]+", "-", normalizado).strip("-")
    return limpio or "unidad"


def nombre_archivo_constancia(unidad: str, anio: int, mes: int) -> str:
    """`constancia-<unidad>-<mes>-<anio>.pdf` sin acentos ni caracteres inválidos."""
    slug_unidad = _slug_ascii(unidad)
    slug_mes = _slug_ascii(MESES[mes - 1])
    return f"constancia-{slug_unidad}-{slug_mes}-{anio}.pdf"


def resolver_firma_constancia(
    propietario: str | None, admin_nombre: str | None
) -> tuple[str | None, str]:
    """Devuelve `(nombre_visible, rol)` según ADR-0004.

    - Si están ambos: se muestran los dos (`"<propietario> / <admin_nombre>"`).
    - Si solo está `propietario`: se muestra `propietario`.
    - Si no está `propietario`, se usa `admin_nombre`.
    - Si no hay ninguno: `None` (línea vacía para firmar a mano).
    """
    prop = (propietario or "").strip() or None
    adm = (admin_nombre or "").strip() or None
    if prop and adm:
        if prop.lower() == adm.lower():
            return prop, ROL_FIRMA_CONSTANCIA
        return f"{prop} / {adm}", ROL_FIRMA_CONSTANCIA
    if prop:
        return prop, ROL_FIRMA_CONSTANCIA
    if adm:
        return adm, ROL_FIRMA_CONSTANCIA
    return None, ROL_FIRMA_CONSTANCIA


def armar_constancia_pago(
    registro: RegistroConstanciaCuota,
    *,
    hoy: date,
    admin_nombre: str | None = None,
    admin_telefono: str | None = None,
    admin_email: str | None = None,
) -> ConstanciaPago:
    """Valida que la cuota esté pagada y construye el DTO `ConstanciaPago`."""
    estado = estado_cuota(
        monto_centavos=registro.monto_centavos,
        pagado_centavos=registro.pagado_centavos,
        fecha_vencimiento=registro.fecha_vencimiento,
        hoy=hoy,
    )
    if estado != "pagada":
        saldo_cap = saldo_capital_cuota(
            registro.monto_centavos, registro.pagado_centavos
        )
        mora_viva = calcular_mora_cuota(
            monto_centavos=registro.monto_centavos,
            pagado_centavos=registro.pagado_centavos,
            fecha_vencimiento=registro.fecha_vencimiento,
            hoy=hoy,
            dias_gracia=registro.dias_gracia,
            tasa_mora_bp=registro.tasa_mora_bp,
        )
        saldo_total = saldo_cap + mora_viva
        raise ErrorDeNegocio(
            "Solo se puede generar constancia para cuotas pagadas. "
            f"La cuota está {estado} (saldo pendiente: {_formatear_pesos_error(saldo_total)})."
        )

    if not registro.pagos:
        raise ErrorDeNegocio(
            "No hay pagos imputados registrados para esta cuota."
        )

    unidad = nombre_unidad(registro.direccion, registro.piso, registro.depto)
    periodo = f"{MESES[registro.mes - 1]} {registro.anio}"

    pagos_dto: list[PagoConstancia] = []
    for p in registro.pagos:
        subtotal = p.capital_centavos + p.mora_centavos
        pagos_dto.append(
            PagoConstancia(
                pago_id=p.pago_id,
                fecha=p.fecha,
                medio=p.medio,
                medio_etiqueta=_ETIQUETA_MEDIO.get(p.medio, p.medio.capitalize()),
                capital_centavos=p.capital_centavos,
                mora_centavos=p.mora_centavos,
                monto_imputado_centavos=subtotal,
                nota=(p.nota or "").strip() or None,
            )
        )

    capital_total = registro.pagado_centavos
    mora_total = registro.mora_pagada_centavos
    total_abonado = capital_total + mora_total
    firma_nombre, firma_rol = resolver_firma_constancia(
        registro.propietario, admin_nombre
    )

    return ConstanciaPago(
        cuota_id=registro.cuota_id,
        departamento_id=registro.departamento_id,
        titulo=TITULO_CONSTANCIA,
        unidad=unidad,
        inquilino=registro.inquilino,
        anio=registro.anio,
        mes=registro.mes,
        periodo=periodo,
        fecha_vencimiento=registro.fecha_vencimiento,
        capital_centavos=capital_total,
        mora_centavos=mora_total,
        total_centavos=total_abonado,
        pagos=tuple(pagos_dto),
        fecha_emision=hoy,
        admin_nombre=(admin_nombre or "").strip() or None,
        admin_telefono=(admin_telefono or "").strip() or None,
        admin_email=(admin_email or "").strip() or None,
        propietario_nombre=(registro.propietario or "").strip() or None,
        firma_nombre=firma_nombre,
        firma_rol=firma_rol,
        leyenda_pie=LEYENDA_PIE_CONSTANCIA,
        leyenda_no_fiscal=LEYENDA_NO_FISCAL,
        nombre_archivo_sugerido=nombre_archivo_constancia(
            unidad, registro.anio, registro.mes
        ),
    )


class ServicioConstancias:
    """Casos de uso de emisión y consulta de constancias de pago mensual."""

    def __init__(
        self,
        repositorio: RepositorioConstancias,
        configuracion: ServicioConfiguracion,
        generador_pdf: GeneradorPdf,
        reloj: Reloj,
    ):
        self._repositorio = repositorio
        self._configuracion = configuracion
        self._generador_pdf = generador_pdf
        self._reloj = reloj

    def disponibles(self, anio: int, mes: int) -> list[CuotaPagadaDisponible]:
        """Cuotas en estado `pagada` del período `(anio, mes)`."""
        if not (2000 <= anio <= 2100) or not (1 <= mes <= 12):
            raise ErrorDeNegocio("El período indicado no es válido.")
        return self._repositorio.listar_pagadas_del_mes(anio, mes)

    def obtener(self, cuota_id: int) -> ConstanciaPago:
        """Arma y valida el DTO `ConstanciaPago` para `cuota_id`."""
        registro = self._repositorio.obtener_constancia(cuota_id)
        if registro is None:
            raise ErrorDeNegocio("La cuota indicada no existe.")
        cfg = self._configuracion.cargar()
        return armar_constancia_pago(
            registro,
            hoy=self._reloj.hoy(),
            admin_nombre=cfg.admin_nombre,
            admin_telefono=cfg.admin_telefono,
            admin_email=cfg.admin_email,
        )

    def generar(self, cuota_id: int, ruta: Path | str) -> ConstanciaPago:
        """Valida `pagada`, arma la constancia y escribe el archivo PDF."""
        constancia = self.obtener(cuota_id)
        self._generador_pdf.generar(constancia, ruta)
        return constancia
