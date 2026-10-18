"""Repositorio SQLite de departamentos contra una base migrada real."""

from datetime import date

import pytest

from gestion.dominio.departamento import Departamento
from gestion.dominio.errores import ErrorDeNegocio
from gestion.infraestructura.db.conexion import abrir_conexion
from gestion.infraestructura.db.migrador import migrar
from gestion.infraestructura.db.repositorios.departamentos import (
    RepositorioDepartamentosSQLite,
)


@pytest.fixture()
def con():
    conexion = abrir_conexion(":memory:")
    migrar(conexion)
    yield conexion
    conexion.close()


@pytest.fixture()
def repo(con):
    return RepositorioDepartamentosSQLite(con)


def _inquilino(con, nombre="María Giménez", telefono="+54 11 5555-1234", email="maria@mail.com"):
    return con.execute(
        "INSERT INTO inquilinos (nombre, telefono, email) VALUES (?, ?, ?)",
        (nombre, telefono, email),
    ).lastrowid


def _contrato(con, departamento_id, inquilino_id, monto=800_000_00, fecha_fin=None):
    return con.execute(
        "INSERT INTO contratos (departamento_id, inquilino_id, fecha_inicio, fecha_fin,"
        "                       monto_centavos)"
        " VALUES (?, ?, '2026-01-01', ?, ?)",
        (departamento_id, inquilino_id, fecha_fin, monto),
    ).lastrowid


def _pago(con, contrato_id, fecha, monto=100_000_00):
    return con.execute(
        "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio)"
        " VALUES (?, ?, ?, 'efectivo')",
        (contrato_id, fecha, monto),
    ).lastrowid


class TestGuardarYObtener:
    def test_round_trip(self, repo):
        nuevo_id = repo.guardar(
            Departamento(direccion="Rivadavia 3421", piso="3", depto="B", m2=62, propietario="Ana")
        )
        guardado = repo.obtener(nuevo_id)
        assert guardado.unidad == "Rivadavia 3421 · 3º B"
        assert guardado.m2 == 62
        assert repo.obtener(999) is None

    def test_duplicado_exacto_choca_con_el_indice_unico(self, repo):
        repo.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        with pytest.raises(ErrorDeNegocio) as error:
            repo.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        assert "Rivadavia 3421 · 3º B" in str(error.value)

    def test_actualizar(self, repo):
        nuevo_id = repo.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        repo.actualizar(Departamento(id=nuevo_id, direccion="Mitre 1180", m2=55))
        actualizado = repo.obtener(nuevo_id)
        assert actualizado.unidad == "Mitre 1180"
        assert actualizado.m2 == 55


class TestListar:
    def test_trae_el_contrato_vigente(self, repo, con):
        depto_id = repo.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        contrato_id = _contrato(con, depto_id, _inquilino(con))
        _pago(con, contrato_id, "2026-03-05")
        _pago(con, contrato_id, "2026-04-02")
        con.commit()

        (fila,) = repo.listar()
        assert fila.unidad == "Rivadavia 3421 · 3º B"
        assert fila.inquilino == "María Giménez"
        assert fila.cuota_vigente_centavos == 800_000_00
        assert fila.ultimo_pago == date(2026, 4, 2)
        # H0: cobranzas/mora todavía no calculan estos campos.
        assert fila.estado_mes is None
        assert fila.deuda_centavos is None

    def test_sin_contrato_queda_en_none(self, repo):
        repo.guardar(Departamento(direccion="Mitre 1180"))
        (fila,) = repo.listar()
        assert fila.sin_contrato
        assert fila.cuota_vigente_centavos is None
        assert fila.ultimo_pago is None

    def test_contrato_cerrado_no_es_vigente_pero_sus_pagos_cuentan(self, repo, con):
        depto_id = repo.guardar(Departamento(direccion="Mitre 1180"))
        contrato_viejo = _contrato(con, depto_id, _inquilino(con), fecha_fin="2026-03-31")
        _pago(con, contrato_viejo, "2026-03-30")
        con.commit()

        (fila,) = repo.listar()
        assert fila.inquilino is None
        assert fila.cuota_vigente_centavos is None
        assert fila.ultimo_pago == date(2026, 3, 30)

    def test_ordena_por_direccion_sin_distinguir_mayusculas(self, repo):
        id_b = repo.guardar(Departamento(direccion="rivadavia 3421"))
        id_a = repo.guardar(Departamento(direccion="Mitre 1180"))
        assert [f.id for f in repo.listar()] == [id_a, id_b]


class TestDetalle:
    def test_con_contrato_vigente(self, repo, con):
        depto_id = repo.guardar(
            Departamento(direccion="Rivadavia 3421", piso="3", depto="B", m2=62)
        )
        _contrato(con, depto_id, _inquilino(con))
        con.commit()

        detalle = repo.detalle(depto_id)
        assert detalle.inquilino.nombre == "María Giménez"
        assert detalle.inquilino.telefono == "+54 11 5555-1234"
        assert detalle.cuota_vigente_centavos == 800_000_00
        assert detalle.m2 == 62
        # H0: llegan con el cálculo de cobranzas/mora.
        assert detalle.deuda_centavos is None
        assert detalle.proximo_vencimiento is None

    def test_sin_contrato(self, repo):
        depto_id = repo.guardar(Departamento(direccion="Mitre 1180"))
        assert repo.detalle(depto_id).inquilino is None

    def test_inexistente(self, repo):
        assert repo.detalle(999) is None


class TestExisteUnidad:
    def test_case_insensitive_y_equivalencia_de_vacios(self, repo):
        repo.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        assert repo.existe_unidad("RIVADAVIA 3421", "3", "B")
        assert repo.existe_unidad("rivadavia 3421", "3", "b")
        assert not repo.existe_unidad("Rivadavia 3421", "3", "A")
        assert not repo.existe_unidad("Mitre 1180", None, None)

    def test_vacio_y_none_son_la_misma_unidad(self, repo):
        repo.guardar(Departamento(direccion="Mitre 1180"))
        assert repo.existe_unidad("MITRE 1180", None, None)
        assert repo.existe_unidad("mitre 1180", "", "")

    def test_excluyendo_ignora_la_propia_fila(self, repo):
        depto_id = repo.guardar(Departamento(direccion="Mitre 1180"))
        assert repo.existe_unidad("Mitre 1180", None, None, excluyendo=depto_id) is False


class TestEliminarYDependencias:
    def _sembrar_completo(self, repo, con):
        depto_id = repo.guardar(Departamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        contrato_id = _contrato(con, depto_id, _inquilino(con))
        pago_id = _pago(con, contrato_id, "2026-04-02")
        cuota_id = con.execute(
            "INSERT INTO cuotas (contrato_id, anio, mes, fecha_vencimiento, monto_centavos)"
            " VALUES (?, 2026, 4, '2026-04-10', 80000000)",
            (contrato_id,),
        ).lastrowid
        con.execute(
            "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos) VALUES (?, ?, 100)",
            (pago_id, cuota_id),
        )
        con.commit()
        return depto_id

    def test_contar_dependencias(self, repo, con):
        depto_id = self._sembrar_completo(repo, con)
        dependencias = repo.contar_dependencias(depto_id)
        assert (dependencias.contratos, dependencias.cuotas, dependencias.pagos) == (1, 1, 1)
        assert (repo.contar_dependencias(999).contratos) == 0

    def test_eliminar_arrastra_todo_en_cascada(self, repo, con):
        depto_id = self._sembrar_completo(repo, con)
        repo.eliminar(depto_id)
        for tabla in ("contratos", "cuotas", "pagos", "imputaciones"):
            total = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
            assert total == 0, f"{tabla} debería quedar vacía"
        assert repo.obtener(depto_id) is None
