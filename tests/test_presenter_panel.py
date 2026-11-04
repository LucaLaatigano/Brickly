"""Presentador del Panel (H4, spec §3.1): KPIs, top de vencidas, alertas y F1.

Se prueba con dobles de los servicios (el presenter solo agrupa lecturas): los
números tienen que salir tal cual de los servicios — acá se verifica que el
Panel no sume ni calcule por su cuenta.
"""

from datetime import date

import pytest

from brickly.aplicacion.ajustes import AjustePendiente, AjustesPorAplicar, MesBase
from brickly.aplicacion.cobranzas import (
    CobranzasDelMes,
    FilaAtraso,
    FilaCobranzaMes,
    PreviewGeneracionCuotas,
    ResumenCobranzasMes,
)
from brickly.aplicacion.configuracion import ConfiguracionInstalacion
from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.departamentos import FilaDepartamento
from brickly.ui.presenters.panel import (
    DESTINO_AJUSTES,
    DESTINO_COBRANZAS,
    DESTINO_DEPARTAMENTOS,
    DESTINO_INFORMES,
    PresenterPanel,
    texto_alerta_ipc,
    texto_alerta_respaldo,
)

HOY = date(2026, 10, 15)


def _depto(**cambios) -> FilaDepartamento:
    base = dict(
        id=1,
        direccion="Rivadavia 3421",
        piso=None,
        depto=None,
        inquilino="Laura Giménez",
        cuota_vigente_centavos=1_280_000,
        estado_mes="vencida",
        deuda_centavos=1_536_000,
        ultimo_pago=None,
    )
    base.update(cambios)
    return FilaDepartamento(**base)


def _fila_mes(**cambios) -> FilaCobranzaMes:
    base = dict(
        id=1,
        cuota_id=1,
        contrato_id=1,
        departamento_id=1,
        direccion="Rivadavia 3421",
        piso=None,
        depto=None,
        inquilino="Laura Giménez",
        fecha_vencimiento=date(2026, 10, 10),
        monto_centavos=1_280_000,
        pagado_centavos=0,
        mora_centavos=0,
        saldo_centavos=1_280_000,
        estado="vencida",
        dias_atraso=5,
    )
    base.update(cambios)
    return FilaCobranzaMes(**base)


def _atraso(indice: int) -> FilaAtraso:
    return FilaAtraso(
        id=indice,
        cuota_id=indice,
        contrato_id=1,
        departamento_id=1,
        direccion=f"Unidad {indice}",
        piso=None,
        depto=None,
        inquilino="Inquilino",
        anio=2026,
        mes=9,
        fecha_vencimiento=date(2026, 9, 10),
        dias_atraso=40 - indice,
        cuota_centavos=100_000,
        mora_centavos=1_000,
        total_centavos=101_000,
    )


def _pendiente(faltan: bool) -> AjustePendiente:
    return AjustePendiente(
        id=1,
        contrato_id=1,
        departamento_id=1,
        direccion="Mitre 1180",
        piso=None,
        depto=None,
        inquilino="Diego Ferreyra",
        fecha_ajuste=date(2026, 10, 1),
        meses=(MesBase(2026, 9, None if faltan else 370),),
        cuota_actual_centavos=960_000,
        redondeo_centavos=1,
        variacion_bp=None if faltan else 370,
        cuota_nueva_centavos=None if faltan else 995_520,
        delta_centavos=None if faltan else 35_520,
    )


class DepartamentosFalso:
    def __init__(self, filas: list[FilaDepartamento] | None = None):
        self.filas = filas or []

    def listar(self) -> list[FilaDepartamento]:
        return self.filas


class CobranzasFalsa:
    def __init__(
        self,
        filas: list[FilaCobranzaMes] | None = None,
        atrasos: list[FilaAtraso] | None = None,
        resumen: ResumenCobranzasMes | None = None,
        generado: bool = True,
    ):
        self.filas = filas or []
        self.atrasos_lista = atrasos or []
        self.resumen = resumen or ResumenCobranzasMes(
            cobrado_centavos=41_250_000,
            esperado_centavos=54_000_000,
            cantidad_vencidas=0,
            monto_vencidas_centavos=0,
            cantidad_pendientes=0,
            cantidad_pagadas=0,
            total_cuotas=len(self.filas),
        )
        self.generado = generado

    def hoy(self) -> date:
        return HOY

    def periodo_actual(self) -> tuple[int, int]:
        return (2026, 10)

    def del_mes(self, anio: int, mes: int) -> CobranzasDelMes:
        return CobranzasDelMes(
            anio=anio,
            mes=mes,
            fecha_calculo=HOY,
            generado=self.generado,
            preview=PreviewGeneracionCuotas(
                anio=anio, mes=mes, cuotas_a_generar=0, total_centavos=0,
                unidades_sin_contrato=0, cuotas_existentes=1 if self.generado else 0,
            ),
            resumen=self.resumen,
            filas=self.filas,
        )

    def atrasos(self) -> list[FilaAtraso]:
        return self.atrasos_lista


class AjustesFalso:
    def __init__(self, pendientes: list[AjustePendiente] | None = None):
        self.pendientes = pendientes or []

    def ajustes_por_aplicar(self) -> AjustesPorAplicar:
        return AjustesPorAplicar(fecha_calculo=HOY, filas=self.pendientes)


class ConfigFalsa:
    def __init__(self, ultimo: date | None = None, recordatorio: int = 14):
        self.config = ConfiguracionInstalacion(
            respaldo_recordatorio_dias=recordatorio, ultimo_respaldo=ultimo
        )

    def cargar(self) -> ConfiguracionInstalacion:
        return self.config


def _servicios(deptos, cobranzas, ajustes=None, configuracion=None) -> Servicios:
    return Servicios(
        departamentos=deptos,
        cobranzas=cobranzas,
        ajustes=ajustes,
        configuracion=configuracion,
    )


class TestTextos:
    def test_alerta_ipc_uno_y_varios(self):
        assert texto_alerta_ipc([(2026, 9)]) == "Falta IPC de septiembre"
        assert (
            texto_alerta_ipc([(2026, 7), (2026, 8), (2026, 9)])
            == "Faltan IPC de julio, agosto y septiembre"
        )

    def test_alerta_respaldo(self):
        assert texto_alerta_respaldo(None, 14, HOY) == "Nunca hiciste un respaldo"
        assert texto_alerta_respaldo(date(2026, 10, 1), 14, HOY) is None
        assert texto_alerta_respaldo(date(2026, 9, 30), 14, HOY) == "Respaldo hace 15 días"
        assert texto_alerta_respaldo(date(2026, 10, 1), 14, date(2026, 10, 16)) == (
            "Respaldo hace 15 días"
        )


class TestCargar:
    def test_kpis_salen_tal_cual_de_los_servicios(self):
        atrasos = [_atraso(i) for i in range(1, 8)]
        filas = [
            _fila_mes(estado="pagada", pagado_centavos=1_280_000, saldo_centavos=0),
            _fila_mes(cuota_id=2, id=2, estado="parcial", pagado_centavos=300_000, saldo_centavos=980_000),
            _fila_mes(cuota_id=3, id=3, estado="pendiente"),
        ]
        servicios = _servicios(
            DepartamentosFalso([_depto()]),
            CobranzasFalsa(filas=filas, atrasos=atrasos),
        )
        datos = PresenterPanel(servicios).cargar()

        assert (datos.anio, datos.mes) == (2026, 10)
        assert datos.cobrado_centavos == 41_250_000
        assert datos.esperado_centavos == 54_000_000
        assert datos.porcentaje_bp == 7639  # 41.250.000 bp·% → round(7638.9)
        assert datos.generado is True

        assert datos.vencidas_cantidad == 7
        assert datos.vencidas_total_centavos == 7 * 101_000
        assert [f.unidad for f in datos.filas_vencidas] == [f"Unidad {i}" for i in range(1, 6)]

        assert datos.pendientes_cantidad == 2  # parcial + pendiente
        assert datos.pendientes_total_centavos == 980_000 + 1_280_000
        assert datos.hay_impagas is True

    def test_onboarding_hasta_el_primer_pago(self):
        servicios = _servicios(
            DepartamentosFalso([_depto(ultimo_pago=None)]),
            CobranzasFalsa(generado=False),
        )
        datos = PresenterPanel(servicios).cargar()
        assert datos.onboarding is True
        assert [(p.texto, p.hecho) for p in datos.pasos] == [
            ("1. Agregá tus departamentos", True),
            ("2. Cargá los contratos", True),
            ("3. Generá las cuotas del mes", False),
        ]
        assert [p.destino for p in datos.pasos] == [
            DESTINO_DEPARTAMENTOS,
            DESTINO_DEPARTAMENTOS,
            DESTINO_COBRANZAS,
        ]

        servicios = _servicios(
            DepartamentosFalso([_depto(ultimo_pago=date(2026, 10, 5))]),
            CobranzasFalsa(),
        )
        assert PresenterPanel(servicios).cargar().onboarding is False

    def test_panel_vacio_no_marca_pasos(self):
        servicios = _servicios(DepartamentosFalso([]), CobranzasFalsa(generado=False))
        datos = PresenterPanel(servicios).cargar()
        assert datos.onboarding is True
        assert all(not paso.hecho for paso in datos.pasos)

    def test_alerta_ipc_y_de_ajustes(self):
        servicios = _servicios(
            DepartamentosFalso([_depto()]),
            CobranzasFalsa(),
            ajustes=AjustesFalso([_pendiente(faltan=True)]),
            configuracion=ConfigFalsa(ultimo=HOY),
        )
        datos = PresenterPanel(servicios).cargar()
        assert datos.ajustes_cantidad == 1
        (alerta,) = datos.alertas
        assert alerta.texto == "Falta IPC de septiembre"
        assert (alerta.etiqueta_accion, alerta.destino) == ("Cargar IPC", DESTINO_AJUSTES)

    def test_alertas_respaldo_y_contrato_vencido(self):
        servicios = _servicios(
            DepartamentosFalso(
                [
                    _depto(),
                    _depto(
                        id=2,
                        direccion="Sarmiento 890",
                        inquilino=None,
                        fecha_contrato_vencido=date(2026, 9, 30),
                    ),
                ]
            ),
            CobranzasFalsa(),
            ajustes=AjustesFalso(),
            configuracion=ConfigFalsa(ultimo=date(2026, 9, 20)),
        )
        datos = PresenterPanel(servicios).cargar()
        assert [a.texto for a in datos.alertas] == [
            "Respaldo hace 25 días",
            "Contrato vencido el 30/09/2026 en Sarmiento 890",
        ]
        respaldo, contrato = datos.alertas
        assert (respaldo.etiqueta_accion, respaldo.destino) == (
            "Respaldar",
            DESTINO_INFORMES,
        )
        assert contrato.destino == DESTINO_DEPARTAMENTOS
        assert contrato.departamento_id == 2

    def test_sin_alertas(self):
        servicios = _servicios(
            DepartamentosFalso([_depto()]),
            CobranzasFalsa(),
            ajustes=AjustesFalso([_pendiente(faltan=False)]),
            configuracion=ConfigFalsa(ultimo=HOY),
        )
        datos = PresenterPanel(servicios).cargar()
        assert datos.ajustes_cantidad == 1
        assert datos.alertas == ()
