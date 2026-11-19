"""Tests de persistencia de lote de importación en RepositorioDepartamentosSQLite."""

from datetime import date

import pytest

from brickly.aplicacion.puertos import ItemImportacionPersistible
from brickly.dominio.contrato import Contrato, Inquilino
from brickly.dominio.departamento import Departamento
from brickly.dominio.errores import ErrorDeNegocio
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.departamentos import (
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


def test_guardar_lote_importacion_exitoso(repo, con):
    items = [
        ItemImportacionPersistible(
            departamento=Departamento(direccion="Av. Corrientes 1200", piso="3", depto="A"),
            inquilino=Inquilino(nombre="Juan Pérez", telefono="11-2222-3333"),
            contrato=Contrato(
                fecha_inicio=date(2026, 1, 1),
                monto_centavos=45000000,
            ),
        ),
        ItemImportacionPersistible(
            departamento=Departamento(direccion="Av. Belgrano 500", piso="PB"),
            inquilino=None,
            contrato=None,
        ),
    ]

    deptos, contratos = repo.guardar_lote_importacion(items)
    assert deptos == 2
    assert contratos == 1

    # Verificamos que existan en la DB
    filas = repo.listar()
    assert len(filas) == 2
    unidad_con_contrato = next(f for f in filas if f.direccion == "Av. Corrientes 1200")
    assert unidad_con_contrato.inquilino == "Juan Pérez"
    assert unidad_con_contrato.cuota_vigente_centavos == 45000000

    unidad_vacante = next(f for f in filas if f.direccion == "Av. Belgrano 500")
    assert unidad_vacante.inquilino is None
    assert unidad_vacante.cuota_vigente_centavos is None


def test_guardar_lote_importacion_rollback_si_falla(repo, con):
    # Ya insertamos un depto previo
    repo.guardar(Departamento(direccion="Av. San Martín 100", piso="1", depto="A"))

    # Intentamos guardar un lote donde el segundo item colisiona con el existente
    items = [
        ItemImportacionPersistible(
            departamento=Departamento(direccion="Nueva Calle 200"),
        ),
        ItemImportacionPersistible(
            # Colisión estricta en SQLite
            departamento=Departamento(direccion="Av. San Martín 100", piso="1", depto="A"),
        ),
    ]

    with pytest.raises(ErrorDeNegocio):
        repo.guardar_lote_importacion(items)

    # Rollback total: "Nueva Calle 200" NO debe haberse guardado
    filas = repo.listar()
    assert len(filas) == 1
    assert filas[0].direccion == "Av. San Martín 100"
