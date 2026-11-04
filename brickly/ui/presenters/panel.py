"""Presentador del Panel (spec §3.1).

Una sola carga por refresco: KPIs del mes, top 5 de vencidas sin pago, alertas
calculadas (IPC faltante · respaldo viejo · contratos vencidos sin renovar) y el
checklist de primeros pasos (F1). Todos los números salen de los servicios de
`aplicacion` — acá solo se agrupan y se arman los textos.
"""

from dataclasses import dataclass
from datetime import date

from brickly.aplicacion.contenedor import Servicios
from brickly.ui.formato import MESES, formatear_dias, formatear_fecha

# Claves de navegación que el Panel le pide a la ventana (§3.0).
DESTINO_DEPARTAMENTOS = "Departamentos"
DESTINO_COBRANZAS = "Cobranzas"
DESTINO_AJUSTES = "Ajustes IPC"
DESTINO_INFORMES = "Informes"


@dataclass(frozen=True)
class FilaVencidaPresentada:
    """Fila del top 5 «Vencidas sin pago» (§3.1). `id` = cuota_id."""

    id: int
    cuota_id: int
    unidad: str
    dias_atraso: int
    total_centavos: int


@dataclass(frozen=True)
class PasoOnboarding:
    """Paso del checklist de puesta en marcha (§4 F1)."""

    texto: str
    hecho: bool
    destino: str


@dataclass(frozen=True)
class AlertaPresentada:
    """Alerta calculada con su acción (§3.1)."""

    texto: str
    etiqueta_accion: str
    destino: str
    departamento_id: int | None = None  # solo para «Ver» de contrato vencido


@dataclass(frozen=True)
class PanelDatos:
    fecha_calculo: date
    anio: int
    mes: int
    onboarding: bool
    pasos: tuple[PasoOnboarding, ...]
    cobrado_centavos: int
    esperado_centavos: int
    porcentaje_bp: int
    vencidas_cantidad: int
    vencidas_total_centavos: int
    pendientes_cantidad: int
    pendientes_total_centavos: int
    ajustes_cantidad: int
    generado: bool
    hay_impagas: bool
    filas_vencidas: tuple[FilaVencidaPresentada, ...]
    alertas: tuple[AlertaPresentada, ...]


def _enumerar(nombres: list[str]) -> str:
    """`a` · `a y b` · `a, b y c` (meses faltantes de IPC, §3.1)."""
    if len(nombres) == 1:
        return nombres[0]
    return f"{', '.join(nombres[:-1])} y {nombres[-1]}"


def texto_alerta_ipc(meses: list[tuple[int, int]]) -> str:
    """«Falta IPC de septiembre» / «Faltan IPC de julio y agosto»."""
    nombres = [MESES[mes - 1] for _anio, mes in meses]
    if len(nombres) == 1:
        return f"Falta IPC de {nombres[0]}"
    return f"Faltan IPC de {_enumerar(nombres)}"


def texto_alerta_respaldo(
    ultimo: date | None, recordatorio_dias: int, hoy: date
) -> str | None:
    """Alerta si nunca hubo respaldo o pasó el recordatorio; si no, `None`."""
    if ultimo is None:
        return "Nunca hiciste un respaldo"
    dias = (hoy - ultimo).days
    if dias > recordatorio_dias:
        return f"Respaldo hace {formatear_dias(dias)}"
    return None


def texto_alerta_contrato(fecha_fin: date, unidad: str) -> str:
    return f"Contrato vencido el {formatear_fecha(fecha_fin)} en {unidad}"


class PresenterPanel:
    def __init__(self, servicios: Servicios):
        self._servicios = servicios

    def cargar(self) -> PanelDatos:
        departamentos = self._servicios.departamentos
        cobranzas = self._servicios.cobranzas

        hoy = cobranzas.hoy()
        anio, mes = cobranzas.periodo_actual()
        filas_departamentos = departamentos.listar()
        del_mes = cobranzas.del_mes(anio, mes)
        atrasos = cobranzas.atrasos()

        pasos = (
            PasoOnboarding(
                "1. Agregá tus departamentos",
                bool(filas_departamentos),
                DESTINO_DEPARTAMENTOS,
            ),
            PasoOnboarding(
                "2. Cargá los contratos",
                any(fila.inquilino for fila in filas_departamentos),
                DESTINO_DEPARTAMENTOS,
            ),
            PasoOnboarding(
                "3. Generá las cuotas del mes",
                del_mes.generado,
                DESTINO_COBRANZAS,
            ),
        )
        # F1: el onboarding del Panel se retira con el primer pago registrado.
        hay_pagos = any(
            fila.ultimo_pago is not None for fila in filas_departamentos
        )

        cobrado = del_mes.resumen.cobrado_centavos
        esperado = del_mes.resumen.esperado_centavos
        porcentaje_bp = round(cobrado * 10_000 / esperado) if esperado else 0

        pendientes = [
            fila
            for fila in del_mes.filas
            if fila.estado in ("pendiente", "parcial")
        ]

        alertas: list[AlertaPresentada] = []
        if self._servicios.ajustes is not None:
            ajustes = self._servicios.ajustes.ajustes_por_aplicar()
            cantidad_ajustes = len(ajustes.filas)
            if ajustes.meses_faltantes:
                alertas.append(
                    AlertaPresentada(
                        texto=texto_alerta_ipc(ajustes.meses_faltantes),
                        etiqueta_accion="Cargar IPC",
                        destino=DESTINO_AJUSTES,
                    )
                )
        else:
            cantidad_ajustes = 0

        if self._servicios.configuracion is not None:
            configuracion = self._servicios.configuracion.cargar()
            texto_respaldo = texto_alerta_respaldo(
                configuracion.ultimo_respaldo,
                configuracion.respaldo_recordatorio_dias,
                hoy,
            )
            if texto_respaldo:
                alertas.append(
                    AlertaPresentada(
                        texto=texto_respaldo,
                        etiqueta_accion="Respaldar",
                        destino=DESTINO_INFORMES,
                    )
                )

        for fila in filas_departamentos:
            if fila.fecha_contrato_vencido is not None:
                alertas.append(
                    AlertaPresentada(
                        texto=texto_alerta_contrato(
                            fila.fecha_contrato_vencido, fila.unidad
                        ),
                        etiqueta_accion="Ver",
                        destino=DESTINO_DEPARTAMENTOS,
                        departamento_id=fila.id,
                    )
                )

        return PanelDatos(
            fecha_calculo=hoy,
            anio=anio,
            mes=mes,
            onboarding=not hay_pagos,
            pasos=pasos,
            cobrado_centavos=cobrado,
            esperado_centavos=esperado,
            porcentaje_bp=porcentaje_bp,
            vencidas_cantidad=len(atrasos),
            vencidas_total_centavos=sum(fila.total_centavos for fila in atrasos),
            pendientes_cantidad=len(pendientes),
            pendientes_total_centavos=sum(
                fila.saldo_centavos or 0 for fila in pendientes
            ),
            ajustes_cantidad=cantidad_ajustes,
            generado=del_mes.generado,
            hay_impagas=bool(atrasos)
            or any(fila.estado != "pagada" for fila in del_mes.filas),
            filas_vencidas=tuple(
                FilaVencidaPresentada(
                    id=fila.cuota_id,
                    cuota_id=fila.cuota_id,
                    unidad=fila.unidad,
                    dias_atraso=fila.dias_atraso,
                    total_centavos=fila.total_centavos,
                )
                for fila in atrasos[:5]
            ),
            alertas=tuple(alertas),
        )
