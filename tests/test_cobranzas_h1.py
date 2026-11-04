"""Servicio y repositorio SQLite de Cobranzas (H1: generación idempotente y tabla del mes)."""

from datetime import date

import pytest

from brickly.aplicacion.cobranzas import ServicioCobranzas
from brickly.aplicacion.departamentos import DatosContrato, ServicioDepartamentos
from brickly.dominio.departamento import Departamento
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.cobranzas import (
    RepositorioCobranzasSQLite,
)
from brickly.infraestructura.db.repositorios.departamentos import (
    RepositorioDepartamentosSQLite,
)


class RelojFijo:
    def __init__(self, fecha: date):
        self.fecha = fecha

    def hoy(self) -> date:
        return self.fecha


@pytest.fixture()
def entorno():
    con = abrir_conexion(":memory:")
    migrar(con)
    reloj = RelojFijo(date(2026, 10, 15))
    repo_deptos = RepositorioDepartamentosSQLite(con, reloj=reloj)
    repo_cobranzas = RepositorioCobranzasSQLite(con)
    serv_deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)
    serv_cobranzas = ServicioCobranzas(repo_cobranzas, reloj=reloj)
    yield con, reloj, repo_deptos, serv_deptos, serv_cobranzas
    con.close()


class TestGeneracionMensual:
    def test_preview_y_generacion_idempotente(self, entorno):
        _con, _reloj, repo_deptos, serv_deptos, serv_cobranzas = entorno
        d1 = repo_deptos.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        d2 = repo_deptos.guardar(Departamento(direccion="Mitre 1180", piso="1", depto="A"))
        repo_deptos.guardar(Departamento(direccion="Sarmiento 890", piso="PB"))  # sin contrato

        serv_deptos.cargar_contrato(
            d1,
            DatosContrato(
                inquilino_nombre="Laura Giménez",
                fecha_inicio=date(2026, 3, 1),
                monto_centavos=1_280_000,
                dia_vencimiento=10,
            ),
        )
        serv_deptos.cargar_contrato(
            d2,
            DatosContrato(
                inquilino_nombre="Diego Ferreyra",
                fecha_inicio=date(2026, 5, 1),
                monto_centavos=960_000,
                dia_vencimiento=10,
            ),
        )

        preview = serv_cobranzas.preview_generacion(2026, 10)
        assert preview.cuotas_a_generar == 2
        assert preview.total_centavos == 2_240_000
        assert preview.unidades_sin_contrato == 1
        assert preview.cuotas_existentes == 0

        primero = serv_cobranzas.generar_cuotas(2026, 10)
        assert primero.cuotas_generadas == 2
        assert primero.total_centavos == 2_240_000
        assert primero.unidades_sin_contrato == 1

        # Segundo clic: idempotente, no duplica ni suma monto nuevo.
        segundo = serv_cobranzas.generar_cuotas(2026, 10)
        assert segundo.cuotas_generadas == 0
        assert segundo.total_centavos == 0
        assert segundo.unidades_sin_contrato == 1

        del_mes = serv_cobranzas.del_mes(2026, 10)
        assert del_mes.generado is True
        assert len(del_mes.filas) == 2

    def test_tabla_del_mes_estados_filtros_y_busqueda(self, entorno):
        con, _reloj, repo_deptos, serv_deptos, serv_cobranzas = entorno
        d1 = repo_deptos.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        d2 = repo_deptos.guardar(Departamento(direccion="Mitre 1180", piso="1", depto="A"))
        d3 = repo_deptos.guardar(Departamento(direccion="Belgrano 500"))

        c1 = serv_deptos.cargar_contrato(
            d1,
            DatosContrato(
                inquilino_nombre="Laura Giménez",
                fecha_inicio=date(2026, 3, 1),
                monto_centavos=1_280_000,
                dia_vencimiento=10,
            ),
        )
        c2 = serv_deptos.cargar_contrato(
            d2,
            DatosContrato(
                inquilino_nombre="Diego Ferreyra",
                fecha_inicio=date(2026, 3, 1),
                monto_centavos=960_000,
                dia_vencimiento=10,
            ),
        )
        serv_deptos.cargar_contrato(
            d3,
            DatosContrato(
                inquilino_nombre="Ana Suárez",
                fecha_inicio=date(2026, 3, 1),
                monto_centavos=1_000_000,
                dia_vencimiento=20,  # vence después de hoy (15/10) -> pendiente
            ),
        )

        serv_cobranzas.generar_cuotas(2026, 10)

        # Cobrar la cuota de Mitre 1180 (c2).
        cuota_c2 = con.execute(
            "SELECT id FROM cuotas WHERE contrato_id = ?", (c2,)
        ).fetchone()["id"]
        pago_id = con.execute(
            "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio)"
            " VALUES (?, '2026-10-10', 960000, 'transferencia')",
            (c2,),
        ).lastrowid
        con.execute(
            "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos)"
            " VALUES (?, ?, 960000)",
            (pago_id, cuota_c2),
        )
        con.commit()

        mes = serv_cobranzas.del_mes(2026, 10)
        assert mes.resumen.esperado_centavos == 3_240_000
        assert mes.resumen.cobrado_centavos == 960_000
        assert mes.resumen.cantidad_vencidas == 1
        assert mes.resumen.monto_vencidas_centavos == 1_280_000
        assert mes.resumen.cantidad_pendientes == 1
        assert mes.resumen.cantidad_pagadas == 1

        # Filtros por estado.
        vencidas = serv_cobranzas.del_mes(2026, 10, filtro="vencidas").filas
        assert [f.contrato_id for f in vencidas] == [c1]
        assert vencidas[0].dias_atraso == 5
        assert vencidas[0].saldo_centavos == 1_280_000

        pagadas = serv_cobranzas.del_mes(2026, 10, filtro="pagadas").filas
        assert [f.contrato_id for f in pagadas] == [c2]
        assert pagadas[0].saldo_centavos is None

        pendientes = serv_cobranzas.del_mes(2026, 10, filtro="pendientes").filas
        assert len(pendientes) == 1
        assert pendientes[0].estado == "pendiente"

        # Búsqueda sin distinguir acentos.
        buscadas = serv_cobranzas.del_mes(2026, 10, busqueda="gimenez").filas
        assert len(buscadas) == 1
        assert buscadas[0].unidad == "Rivadavia 3421 · 3º B"


class TestContratosYCuotasEnDepartamento:
    def test_cargar_editar_y_renovar_sin_perder_historial(self, entorno):
        _con, _reloj, repo_deptos, serv_deptos, serv_cobranzas = entorno
        depto_id = repo_deptos.guardar(
            Departamento(direccion="Rivadavia 3421", piso="3", depto="B")
        )
        serv_deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Laura Giménez",
                inquilino_telefono="11 5555-1234",
                fecha_inicio=date(2026, 7, 1),
                monto_centavos=1_280_000,
                dia_vencimiento=10,
                ciclo_meses=3,
            ),
        )
        serv_cobranzas.generar_cuotas(2026, 9)

        detalle = serv_deptos.detalle(depto_id)
        assert detalle.contrato is not None
        assert detalle.contrato.inquilino_nombre == "Laura Giménez"
        assert detalle.contrato.proxima_fecha_ajuste == date(2026, 10, 1)
        assert detalle.proximo_vencimiento == date(2026, 9, 10)

        # Editar contrato vigente.
        serv_deptos.editar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Laura M. Giménez",
                inquilino_telefono="11 5555-9999",
                fecha_inicio=date(2026, 7, 1),
                monto_centavos=1_350_000,
                dia_vencimiento=10,
            ),
        )
        assert serv_deptos.detalle(depto_id).cuota_vigente_centavos == 1_350_000

        # Cambio de inquilino (Nuevo contrato): cierra el anterior y conserva sus cuotas.
        serv_deptos.nuevo_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre="Martín Acosta",
                fecha_inicio=date(2026, 10, 15),
                monto_centavos=1_500_000,
                dia_vencimiento=10,
            ),
        )
        serv_cobranzas.generar_cuotas(2026, 10)

        actualizado = serv_deptos.detalle(depto_id)
        assert actualizado.inquilino.nombre == "Martín Acosta"
        assert actualizado.cuota_vigente_centavos == 1_500_000
        assert actualizado.estado_mes == "vencida"

        # Las cuotas del contrato anterior y del nuevo siguen visibles en el historial.
        cuotas = serv_deptos.listar_cuotas(depto_id)
        assert [(c.anio, c.mes, c.monto_centavos) for c in cuotas] == [
            (2026, 10, 1_500_000),
            (2026, 9, 1_280_000),
        ]

        # Y la lista general de departamentos refleja el estado del mes corriente.
        (fila_depto,) = serv_deptos.listar()
        assert fila_depto.estado_mes == "vencida"


class TestAtrasosMoraYPagosH2:
    def test_atrasos_ordenados_y_mora_consistente_entre_vistas(self, entorno):
        _con, reloj, repo_deptos, serv_deptos, serv_cobranzas = entorno
        reloj.fecha = date(2026, 10, 22)  # 12 días después del 10/10 (supera 5 de gracia)

        d1 = repo_deptos.guardar(
            Departamento(direccion="Rivadavia 3421", piso="3", depto="B")
        )
        d2 = repo_deptos.guardar(
            Departamento(direccion="Mitre 1180", piso="1", depto="A")
        )
        serv_deptos.cargar_contrato(
            d1,
            DatosContrato(
                inquilino_nombre="Laura Giménez",
                fecha_inicio=date(2026, 8, 1),
                monto_centavos=1_280_000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
            ),
        )
        serv_cobranzas.generar_cuotas(2026, 9)  # solo d1 tenía contrato en sep

        serv_deptos.cargar_contrato(
            d2,
            DatosContrato(
                inquilino_nombre="Diego Ferreyra",
                fecha_inicio=date(2026, 10, 1),
                monto_centavos=960_000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
            ),
        )
        serv_cobranzas.generar_cuotas(2026, 10)  # d1 y d2 en oct

        atrasos = serv_cobranzas.atrasos()
        assert len(atrasos) == 3
        # Orden descendente por días de atraso (sep = 42 días; oct = 12 días).
        assert [a.dias_atraso for a in atrasos] == [42, 12, 12]

        # La mora de oct de d1 debe coincidir exactamente en Cobranzas/Mes, Atrasos,
        # preparar_pago y Detalle de departamento (criterio de aceptación §3.3 / §3.4).
        cuota_oct_d1 = next(
            a for a in atrasos if a.departamento_id == d1 and a.mes == 10
        )
        assert cuota_oct_d1.mora_centavos == 10_240

        fila_mes_d1 = next(
            f
            for f in serv_cobranzas.del_mes(2026, 10).filas
            if f.departamento_id == d1
        )
        assert fila_mes_d1.mora_centavos == 10_240
        assert fila_mes_d1.saldo_centavos == 1_280_000 + 10_240

        prep = serv_cobranzas.preparar_pago(cuota_oct_d1.cuota_id)
        assert prep.mora_centavos == 10_240
        assert prep.total_centavos == 1_290_240
        assert prep.medio_sugerido == "transferencia"

        cuota_det_oct = next(
            c for c in serv_deptos.listar_cuotas(d1) if c.mes == 10
        )
        assert cuota_det_oct.mora_centavos == 10_240
        assert cuota_det_oct.saldo_centavos == 1_290_240

        # Deuda total del departamento = suma de (saldo_capital + mora_hoy) de sus cuotas.
        deuda_esperada_d1 = sum(
            a.total_centavos for a in atrasos if a.departamento_id == d1
        )
        assert serv_deptos.detalle(d1).deuda_centavos == deuda_esperada_d1

    def test_registrar_pago_parcial_y_total_congela_mora_y_actualiza_deuda(self, entorno):
        from brickly.aplicacion.cobranzas import DatosPago
        from brickly.dominio.errores import ErrorDeNegocio

        _con, reloj, repo_deptos, serv_deptos, serv_cobranzas = entorno
        reloj.fecha = date(2026, 10, 22)

        d1 = repo_deptos.guardar(
            Departamento(direccion="Rivadavia 3421", piso="3", depto="B")
        )
        serv_deptos.cargar_contrato(
            d1,
            DatosContrato(
                inquilino_nombre="Laura Giménez",
                fecha_inicio=date(2026, 10, 1),
                monto_centavos=1_280_000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
            ),
        )
        serv_cobranzas.generar_cuotas(2026, 10)
        prep = serv_cobranzas.preparar_pago_departamento(d1)
        assert prep.total_centavos == 1_290_240  # 1.280.000 + 10.240 de mora

        # Monto mayor al total bloquea sin modificar nada.
        with pytest.raises(ErrorDeNegocio, match="supera el total"):
            serv_cobranzas.registrar_pago(
                DatosPago(
                    cuota_id=prep.cuota_id,
                    fecha=reloj.hoy(),
                    monto_centavos=1_300_000,
                    medio="transferencia",
                )
            )
        assert serv_deptos.detalle(d1).deuda_centavos == 1_290_240

        # Pago parcial ($ 5.000 = 500.000 centavos) en efectivo:
        # cubre primero la mora ($ 102,40) y el resto ($ 4.897,60) achica capital.
        parcial = serv_cobranzas.registrar_pago(
            DatosPago(
                cuota_id=prep.cuota_id,
                fecha=reloj.hoy(),
                monto_centavos=500_000,
                medio="efectivo",
                nota="Adelanto en mano",
            )
        )
        assert parcial.mora_aplicada_centavos == 10_240
        assert parcial.capital_aplicado_centavos == 489_760
        assert parcial.saldo_restante_centavos == 790_240

        # El último medio usado pasa a ser el default sugerido.
        prep_2 = serv_cobranzas.preparar_pago(prep.cuota_id)
        assert prep_2.medio_sugerido == "efectivo"
        assert prep_2.saldo_capital_centavos == 1_280_000 - 489_760

        # Saldar el total restante deja la unidad al día (deuda = 0, sin atrasos).
        serv_cobranzas.registrar_pago(
            DatosPago(
                cuota_id=prep.cuota_id,
                fecha=reloj.hoy(),
                monto_centavos=prep_2.total_centavos,
                medio="transferencia",
            )
        )
        assert serv_cobranzas.atrasos() == []
        detalle = serv_deptos.detalle(d1)
        assert detalle.deuda_centavos == 0
        assert detalle.estado_mes == "pagada"
        assert serv_deptos.listar()[0].ultimo_pago == date(2026, 10, 22)

        pagos = serv_deptos.pagos_de_cuota(prep.cuota_id)
        assert len(pagos) == 2
        assert pagos[-1].mora_centavos == 10_240
        assert pagos[0].mora_centavos == 6_322

