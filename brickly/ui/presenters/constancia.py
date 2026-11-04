"""Presentador de Constancias de pago mensual (H8 — ADR-0004).

Transforma `ConstanciaPago` (aplicación) en textos formateados en `es-AR` listos
para mostrar en `PanelConstancia` y sugerir el nombre de archivo en el diálogo.
"""

from __future__ import annotations

from dataclasses import dataclass

from brickly.aplicacion.constancias import ConstanciaPago, ServicioConstancias
from brickly.aplicacion.contenedor import Servicios
from brickly.dominio.errores import ErrorDeNegocio
from brickly.ui.formato import formatear_fecha


def formatear_monto_constancia(centavos: int) -> str:
    """Formatea centavos enteros como `$ 12.800,00` (siempre con 2 decimales)."""
    signo = "-" if centavos < 0 else ""
    enteros, resto = divmod(abs(centavos), 100)
    miles = f"{enteros:,}".replace(",", ".")
    return f"{signo}$ {miles},{resto:02d}"


@dataclass(frozen=True)
class PagoConstanciaPresentado:
    """Fila de un pago imputado para la vista previa de `PanelConstancia`."""

    pago_id: int
    fecha: str
    medio: str
    capital: str
    mora: str
    monto_imputado: str
    nota: str | None = None


@dataclass(frozen=True)
class ConstanciaPresentada:
    """DTO de presentación listo para renderizar en `PanelConstancia`."""

    cuota_id: int
    departamento_id: int
    titulo: str
    unidad: str
    inquilino: str
    periodo: str
    fecha_vencimiento: str
    fecha_emision: str
    capital: str
    mora: str
    total: str
    emisor: str | None
    firma_nombre: str | None
    firma_rol: str
    leyenda_pie: str
    leyenda_no_fiscal: str
    nombre_archivo_sugerido: str
    pagos: tuple[PagoConstanciaPresentado, ...]


def presentar_constancia(doc: ConstanciaPago) -> ConstanciaPresentada:
    """Convierte `ConstanciaPago` puro en `ConstanciaPresentada`."""
    partes_emisor = [
        p
        for p in (doc.admin_nombre, doc.admin_telefono, doc.admin_email)
        if p
    ]
    emisor = " · ".join(partes_emisor) if partes_emisor else None

    pagos = tuple(
        PagoConstanciaPresentado(
            pago_id=p.pago_id,
            fecha=formatear_fecha(p.fecha),
            medio=p.medio_etiqueta,
            capital=formatear_monto_constancia(p.capital_centavos),
            mora=formatear_monto_constancia(p.mora_centavos),
            monto_imputado=formatear_monto_constancia(p.monto_imputado_centavos),
            nota=p.nota,
        )
        for p in doc.pagos
    )

    return ConstanciaPresentada(
        cuota_id=doc.cuota_id,
        departamento_id=doc.departamento_id,
        titulo=doc.titulo,
        unidad=doc.unidad,
        inquilino=doc.inquilino,
        periodo=doc.periodo,
        fecha_vencimiento=formatear_fecha(doc.fecha_vencimiento),
        fecha_emision=formatear_fecha(doc.fecha_emision),
        capital=formatear_monto_constancia(doc.capital_centavos),
        mora=formatear_monto_constancia(doc.mora_centavos),
        total=formatear_monto_constancia(doc.total_centavos),
        emisor=emisor,
        firma_nombre=doc.firma_nombre,
        firma_rol=doc.firma_rol,
        leyenda_pie=doc.leyenda_pie,
        leyenda_no_fiscal=doc.leyenda_no_fiscal,
        nombre_archivo_sugerido=doc.nombre_archivo_sugerido,
        pagos=pagos,
    )


def _resolver_servicio(
    fuente: Servicios | ServicioConstancias,
) -> ServicioConstancias:
    if isinstance(fuente, ServicioConstancias):
        return fuente
    if fuente.constancias is None:
        raise ErrorDeNegocio(
            "El servicio de constancias no está configurado."
        )
    return fuente.constancias


def preparar_constancia(
    fuente: Servicios | ServicioConstancias, cuota_id: int
) -> ConstanciaPresentada:
    """Obtiene y formatea la constancia de `cuota_id` para la vista previa."""
    servicio = _resolver_servicio(fuente)
    return presentar_constancia(servicio.obtener(cuota_id))


class PresenterConstancia:
    """Presentador de `PanelConstancia` en Cobranzas."""

    def __init__(self, servicios: Servicios):
        self._servicios = servicios

    def preparar_constancia(self, cuota_id: int) -> ConstanciaPresentada:
        return preparar_constancia(self._servicios, cuota_id)

    def generar_pdf(self, cuota_id: int, ruta: str) -> ConstanciaPresentada:
        servicio = _resolver_servicio(self._servicios)
        doc = servicio.generar(cuota_id, ruta)
        return presentar_constancia(doc)
