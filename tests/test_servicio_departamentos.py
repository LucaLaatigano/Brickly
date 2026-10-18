"""Servicio de departamentos con repositorio doble en memoria (sin SQLite)."""

import pytest

from gestion.aplicacion.departamentos import (
    DatosDepartamento,
    DependenciasDepartamento,
    FilaDepartamento,
    ServicioDepartamentos,
)
from gestion.dominio.errores import ErrorDeNegocio, ErrorDeValidacion


class RepoFalso:
    """Doble del puerto: filas/listas cargadas a mano y registro de llamadas."""

    def __init__(self):
        self.filas: list[FilaDepartamento] = []
        self.detalles: dict = {}
        self.departamentos: dict[int, object] = {}
        self.duplicada = False
        self.guardados: list = []
        self.actualizados: list = []
        self.eliminados: list[int] = []
        self.unidad_consultada: tuple | None = None

    def listar(self) -> list[FilaDepartamento]:
        return list(self.filas)

    def obtener(self, departamento_id: int):
        return self.departamentos.get(departamento_id)

    def detalle(self, departamento_id: int):
        return self.detalles.get(departamento_id)

    def guardar(self, departamento) -> int:
        self.guardados.append(departamento)
        return 7

    def actualizar(self, departamento) -> None:
        self.actualizados.append(departamento)

    def eliminar(self, departamento_id: int) -> None:
        self.eliminados.append(departamento_id)

    def existe_unidad(self, direccion, piso, depto, excluyendo=None) -> bool:
        self.unidad_consultada = (direccion, piso, depto, excluyendo)
        return self.duplicada

    def contar_dependencias(self, departamento_id: int) -> DependenciasDepartamento:
        return DependenciasDepartamento(contratos=2, cuotas=24, pagos=18)


def fila(
    id=1,
    direccion="Rivadavia 3421",
    piso="3",
    depto="B",
    inquilino="María Giménez",
    deuda=None,
    estado=None,
) -> FilaDepartamento:
    return FilaDepartamento(
        id=id,
        direccion=direccion,
        piso=piso,
        depto=depto,
        inquilino=inquilino,
        cuota_vigente_centavos=None,
        estado_mes=estado,
        deuda_centavos=deuda,
        ultimo_pago=None,
    )


@pytest.fixture
def par():
    repo = RepoFalso()
    return ServicioDepartamentos(repo), repo


class TestBusqueda:
    def test_sin_termino_devuelve_todo(self, par):
        servicio, repo = par
        repo.filas = [fila(id=1), fila(id=2, direccion="Mitre 1180")]
        assert len(servicio.listar()) == 2

    def test_encuentra_por_direccion_ignorando_acentos(self, par):
        servicio, repo = par
        repo.filas = [fila(direccion="José Hernández 450"), fila(direccion="Mitre 1180")]
        resultado = servicio.listar(busqueda="jose hernandez")
        assert [f.id for f in resultado] == [1]

    def test_encuentra_por_inquilino(self, par):
        servicio, repo = par
        repo.filas = [fila(inquilino="María Giménez"), fila(id=2, inquilino="Juan Pérez")]
        assert [f.id for f in servicio.listar(busqueda="gimenez")] == [1]

    def test_sin_coincidencias_devuelve_vacio(self, par):
        servicio, repo = par
        repo.filas = [fila()]
        assert servicio.listar(busqueda="zzz") == []


class TestFiltros:
    def test_deuda_desconocida_no_matchea_al_dia_ni_deben(self, par):
        """H0: sin cobranzas, la deuda es None — no se puede afirmar nada."""
        servicio, repo = par
        repo.filas = [fila(deuda=None)]
        assert servicio.listar(filtro="al_dia") == []
        assert servicio.listar(filtro="deben") == []

    def test_al_dia_y_deben_usan_la_deuda(self, par):
        servicio, repo = par
        repo.filas = [
            fila(id=1, deuda=0),
            fila(id=2, deuda=14_336_00),
            fila(id=3, deuda=None),
        ]
        assert [f.id for f in servicio.listar(filtro="al_dia")] == [1]
        assert [f.id for f in servicio.listar(filtro="deben")] == [2]

    def test_sin_contrato(self, par):
        servicio, repo = par
        repo.filas = [fila(id=1, inquilino=None), fila(id=2)]
        assert [f.id for f in servicio.listar(filtro="sin_contrato")] == [1]


class TestCrear:
    def test_guarda_y_devuelve_el_id(self, par):
        servicio, repo = par
        nuevo_id = servicio.crear(DatosDepartamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        assert nuevo_id == 7
        assert repo.guardados[0].unidad == "Rivadavia 3421 · 3º B"
        assert repo.unidad_consultada == ("Rivadavia 3421", "3", "B", None)

    def test_valida_el_dato_antes_de_tocar_el_repositorio(self, par):
        servicio, repo = par
        with pytest.raises(ErrorDeValidacion) as error:
            servicio.crear(DatosDepartamento(direccion=""))
        assert error.value.campo == "direccion"
        assert repo.guardados == []

    def test_rechaza_unidad_duplicada(self, par):
        servicio, repo = par
        repo.duplicada = True
        with pytest.raises(ErrorDeNegocio) as error:
            servicio.crear(DatosDepartamento(direccion="Rivadavia 3421", piso="3", depto="B"))
        assert "Rivadavia 3421 · 3º B" in str(error.value)
        assert repo.guardados == []


class TestEditar:
    def test_exige_que_exista(self, par):
        servicio, _ = par
        with pytest.raises(ErrorDeNegocio):
            servicio.editar(99, DatosDepartamento(direccion="Mitre 1180"))

    def test_actualiza_con_el_id(self, par):
        servicio, repo = par
        repo.departamentos[3] = object()
        servicio.editar(3, DatosDepartamento(direccion="Mitre 1180", m2=55))
        assert repo.actualizados[0].id == 3
        assert repo.actualizados[0].m2 == 55

    def test_el_duplicado_excluye_al_propio(self, par):
        servicio, repo = par
        repo.departamentos[3] = object()
        repo.duplicada = True
        with pytest.raises(ErrorDeNegocio):
            servicio.editar(3, DatosDepartamento(direccion="Mitre 1180"))
        assert repo.unidad_consultada == ("Mitre 1180", None, None, 3)


class TestEliminar:
    def test_exige_que_exista(self, par):
        servicio, _ = par
        with pytest.raises(ErrorDeNegocio):
            servicio.eliminar(99)

    def test_elimina(self, par):
        servicio, repo = par
        repo.departamentos[5] = object()
        servicio.eliminar(5)
        assert repo.eliminados == [5]


class TestDetalleYDependencias:
    def test_detalle_inexistente(self, par):
        servicio, _ = par
        with pytest.raises(ErrorDeNegocio):
            servicio.detalle(99)

    def test_detalle_delega(self, par):
        servicio, repo = par
        repo.detalles[4] = "detalle"
        assert servicio.detalle(4) == "detalle"

    def test_dependencias_delega(self, par):
        servicio, _ = par
        assert servicio.contar_dependencias(4) == DependenciasDepartamento(2, 24, 18)
