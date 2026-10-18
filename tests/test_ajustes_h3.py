"""Servicio + repositorio SQLite de Ajustes IPC (H3, spec §3.5 y ADR-0002 §1)."""

from datetime import date

import pytest

from gestion.aplicacion.ajustes import DatosAjuste, ServicioAjustesIpc
from gestion.aplicacion.cobranzas import ServicioCobranzas
from gestion.aplicacion.departamentos import DatosContrato, ServicioDepartamentos
from gestion.dominio.departamento import Departamento
from gestion.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from gestion.dominio.ipc import AjusteCalculado
from gestion.infraestructura.db.conexion import abrir_conexion
from gestion.infraestructura.db.migrador import migrar
from gestion.infraestructura.db.repositorios.ajustes import RepositorioAjustesSQLite
from gestion.infraestructura.db.repositorios.cobranzas import RepositorioCobranzasSQLite
from gestion.infraestructura.db.repositorios.departamentos import (
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
    repo_ajustes = RepositorioAjustesSQLite(con)
    deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)
    cobranzas = ServicioCobranzas(RepositorioCobranzasSQLite(con), reloj=reloj)
    ajustes = ServicioAjustesIpc(repo_ajustes, reloj=reloj)

    def contrato(direccion: str, inicio: date, monto: int, ciclo: int = 3) -> int:
        depto_id = repo_deptos.guardar(Departamento(direccion=direccion))
        deptos.cargar_contrato(
            depto_id,
            DatosContrato(
                inquilino_nombre=f"Inquilino {direccion}",
                fecha_inicio=inicio,
                monto_centavos=monto,
                dia_vencimiento=10,
                ciclo_meses=ciclo,
            ),
        )
        return depto_id

    yield con, deptos, cobranzas, ajustes, repo_ajustes, contrato
    con.close()


def _cargar_trimestre(ajustes: ServicioAjustesIpc) -> None:
    ajustes.agregar_ipc(2026, 7, 210)
    ajustes.agregar_ipc(2026, 8, 340)
    ajustes.agregar_ipc(2026, 9, 370)


class TestAjustesPorAplicar:
    def test_solo_contratos_cuyo_ciclo_vence_este_mes_y_faltantes(self, entorno):
        _con, _deptos, _cob, ajustes, _repo, contrato = entorno
        contrato("Rivadavia 3421", date(2026, 7, 1), 1_280_000)          # hito 01/10 ✔
        contrato("Mitre 1180", date(2026, 8, 1), 960_000)                # hito 01/11 ✘
        contrato("Belgrano 500", date(2026, 4, 10), 1_000_000, ciclo=6)  # hito 10/10 ✔

        estado = ajustes.ajustes_por_aplicar()
        assert [f.unidad for f in estado.filas] == ["Belgrano 500", "Rivadavia 3421"]
        assert all(f.estado == "faltan_datos" for f in estado.filas)
        assert estado.meses_faltantes == [(2026, m) for m in range(4, 10)]

        _cargar_trimestre(ajustes)
        estado = ajustes.ajustes_por_aplicar()
        rivadavia = next(f for f in estado.filas if f.unidad == "Rivadavia 3421")
        belgrano = next(f for f in estado.filas if f.unidad == "Belgrano 500")

        assert rivadavia.estado == "listo"
        assert (rivadavia.desde, rivadavia.hasta) == ((2026, 7), (2026, 9))
        assert rivadavia.variacion_bp == 948  # compuesto, no 920 (suma simple)
        assert rivadavia.cuota_nueva_centavos == 1_401_344
        assert rivadavia.delta_centavos == 121_344
        # Mismo IPC, otro ciclo → otro %: Belgrano necesita abr–sep.
        assert belgrano.estado == "faltan_datos"
        assert belgrano.meses_faltantes == [(2026, 4), (2026, 5), (2026, 6)]

        # Julio lo usan los dos ajustes pendientes (para la confirmación de editar/borrar).
        julio = next(f for f in ajustes.listar_ipc() if (f.anio, f.mes) == (2026, 7))
        assert julio.contratos_que_lo_usan == 2

    def test_abm_ipc(self, entorno):
        *_, ajustes, _repo, _contrato = entorno
        ipc_id = ajustes.agregar_ipc(2026, 9, 370)
        with pytest.raises(ErrorDeValidacion, match="Ya hay un IPC"):
            ajustes.agregar_ipc(2026, 9, 100)
        with pytest.raises(ErrorDeValidacion):
            ajustes.agregar_ipc(2026, 8, 10_001)

        ajustes.editar_ipc(ipc_id, -50)  # deflación permitida
        (fila,) = ajustes.listar_ipc()
        assert (fila.variacion_bp, fila.origen) == (-50, "manual")

        ajustes.eliminar_ipc(ipc_id)
        assert ajustes.listar_ipc() == []
        with pytest.raises(ErrorDeNegocio, match="no existe"):
            ajustes.eliminar_ipc(ipc_id)

    def test_periodo_sugerido_es_el_mes_anterior(self, entorno):
        *_, ajustes, _repo, _contrato = entorno
        assert ajustes.periodo_sugerido() == (2026, 9)


class TestAplicar:
    def test_override_exige_motivo_y_queda_en_historial(self, entorno):
        _con, deptos, _cob, ajustes, _repo, contrato = entorno
        depto_id = contrato("Rivadavia 3421", date(2026, 7, 1), 1_280_000)
        _cargar_trimestre(ajustes)
        contrato_id = ajustes.ajustes_por_aplicar().filas[0].contrato_id

        preview = ajustes.calcular_cuota(contrato_id, 800)
        assert (preview.cuota_nueva_centavos, preview.delta_centavos) == (1_382_400, 102_400)
        assert preview.es_override is True
        assert ajustes.calcular_cuota(contrato_id, 948).es_override is False

        with pytest.raises(ErrorDeValidacion, match="motivo"):
            ajustes.aplicar([DatosAjuste(contrato_id, 800)])
        assert deptos.detalle(depto_id).cuota_vigente_centavos == 1_280_000  # nada cambió

        resultado = ajustes.aplicar(
            [DatosAjuste(contrato_id, 800, motivo_override="Pactado 8 % en contrato")]
        )
        assert (resultado.cantidad, resultado.variacion_promedio_bp) == (1, 800)

        detalle = deptos.detalle(depto_id)
        assert detalle.cuota_vigente_centavos == 1_382_400
        assert detalle.contrato.proxima_fecha_ajuste == date(2027, 1, 1)
        assert ajustes.ajustes_por_aplicar().filas == []

        (fila,) = ajustes.historial()
        assert fila.es_override is True
        assert fila.motivo_override == "Pactado 8 % en contrato"
        assert (fila.desde, fila.hasta) == ((2026, 7), (2026, 9))
        assert (fila.cuota_antes_centavos, fila.cuota_despues_centavos) == (1_280_000, 1_382_400)
        assert fila.fecha_aplicacion == date(2026, 10, 1)

        # Segundo intento sobre el mismo ciclo: ya no está pendiente.
        with pytest.raises(ErrorDeNegocio, match="ya no tiene"):
            ajustes.aplicar([DatosAjuste(contrato_id, 948)])

    def test_no_aplica_si_faltan_datos(self, entorno):
        *_, ajustes, _repo, contrato = entorno
        contrato("Belgrano 500", date(2026, 4, 10), 1_000_000, ciclo=6)
        _cargar_trimestre(ajustes)
        fila = ajustes.ajustes_por_aplicar().filas[0]
        with pytest.raises(ErrorDeNegocio, match="Faltan datos"):
            ajustes.aplicar([DatosAjuste(fila.contrato_id, 500)])

    def test_no_recalcula_cuotas_emitidas_solo_las_siguientes(self, entorno):
        con, _deptos, cobranzas, ajustes, _repo, contrato = entorno
        contrato("Rivadavia 3421", date(2026, 7, 1), 1_280_000)
        _cargar_trimestre(ajustes)
        cobranzas.generar_cuotas(2026, 10)  # emitida ANTES de confirmar

        fila = ajustes.ajustes_por_aplicar().filas[0]
        ajustes.aplicar([DatosAjuste(fila.contrato_id, fila.variacion_bp)])

        cobranzas.generar_cuotas(2026, 11)
        montos = dict(
            ((r["mes"], r["monto_centavos"]) for r in con.execute("SELECT mes, monto_centavos FROM cuotas"))
        )
        assert montos == {10: 1_280_000, 11: 1_401_344}

    def test_repositorio_es_todo_o_nada(self, entorno):
        con, _deptos, _cob, ajustes, repo, contrato = entorno
        contrato("Rivadavia 3421", date(2026, 7, 1), 1_280_000)
        contrato("Belgrano 500", date(2026, 7, 1), 1_000_000)
        _cargar_trimestre(ajustes)
        a, b = ajustes.ajustes_por_aplicar().filas  # Belgrano, Rivadavia

        def calculado(fila, cuota_antes):
            return AjusteCalculado(
                contrato_id=fila.contrato_id,
                fecha_ajuste=fila.fecha_ajuste,
                anio_base=2026,
                mes_base=7,
                meses_ciclo=3,
                variacion_bp=948,
                cuota_antes_centavos=cuota_antes,
                cuota_despues_centavos=fila.cuota_nueva_centavos,
            )

        # El segundo trae una cuota «antes» que ya no es la vigente → aborta todo.
        with pytest.raises(ErrorDeNegocio, match="cambió"):
            repo.guardar_ajustes([calculado(a, a.cuota_actual_centavos), calculado(b, 1)])

        assert con.execute("SELECT COUNT(*) FROM ajustes").fetchone()[0] == 0
        montos = sorted(r[0] for r in con.execute("SELECT monto_centavos FROM contratos"))
        assert montos == [1_000_000, 1_280_000]
