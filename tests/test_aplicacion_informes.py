"""ServicioInformes y armado de CSV (H4, spec §3.6): formato y orquestación.

Los builders de CSV son puros (DTOs → texto) y se testean al detalle; el
servicio se prueba con dobles de los puertos (repo, cobranzas, config, escritor
y respaldador) para verificar guardas, filtros y el registro del respaldo.
"""

from datetime import date

import pytest

from brickly.aplicacion.cobranzas import (
    CobranzasDelMes,
    FilaAtraso,
    FilaCobranzaMes,
    PreviewGeneracionCuotas,
    ResumenCobranzasMes,
)
from brickly.aplicacion.informes import (
    RegistroEstadoCuenta,
    ServicioInformes,
    csv_cobranzas_del_mes,
    csv_estado_cuenta,
    csv_morosos,
)
from brickly.dominio.errores import ErrorDeNegocio

HOY = date(2026, 10, 15)


class RelojFijo:
    def __init__(self, fecha: date = HOY):
        self.fecha = fecha

    def hoy(self) -> date:
        return self.fecha


class CobranzasFalsa:
    def __init__(self, generado: bool = True, filas: list | None = None, atrasos: list | None = None):
        self.generado = generado
        self.filas = filas or []
        self.atrasos_lista = atrasos or []

    def periodo_actual(self) -> tuple[int, int]:
        return (2026, 10)

    def preview_generacion(self, anio: int, mes: int) -> PreviewGeneracionCuotas:
        return PreviewGeneracionCuotas(
            anio=anio, mes=mes, cuotas_a_generar=0, total_centavos=0,
            unidades_sin_contrato=0, cuotas_existentes=1 if self.generado else 0,
        )

    def del_mes(self, anio: int, mes: int) -> CobranzasDelMes:
        return CobranzasDelMes(
            anio=anio,
            mes=mes,
            fecha_calculo=HOY,
            generado=self.generado,
            preview=self.preview_generacion(anio, mes),
            resumen=ResumenCobranzasMes(0, 0, 0, 0, 0, 0, len(self.filas)),
            filas=self.filas,
        )

    def atrasos(self) -> list:
        return self.atrasos_lista


class ConfigFalsa:
    def __init__(self, ultimo: date | None = None):
        self.ultimo = ultimo
        self.registrados: list[date] = []

    def ultimo_respaldo(self) -> date | None:
        return self.ultimo

    def registrar_respaldo(self, fecha: date) -> None:
        self.registrados.append(fecha)


class RepoInformesFalso:
    def __init__(self, registros: list | None = None, departamentos: int = 0, cuotas: int = 0):
        self.registros = registros or []
        self.departamentos = departamentos
        self.cuotas = cuotas
        self.filtros: list[int | None] = []

    def contar_departamentos(self) -> int:
        return self.departamentos

    def contar_cuotas(self) -> int:
        return self.cuotas

    def listar_estado_cuenta(self, departamento_id: int | None = None) -> list:
        self.filtros.append(departamento_id)
        if departamento_id is None:
            return list(self.registros)
        return [r for r in self.registros if r.departamento_id == departamento_id]


class EscritorFalso:
    def __init__(self):
        self.escritos: list[tuple[str, str]] = []

    def escribir(self, ruta, contenido: str) -> None:
        self.escritos.append((str(ruta), contenido))


class RespaldadorFalso:
    def __init__(self):
        self.destinos: list[str] = []

    def respaldar(self, destino) -> None:
        self.destinos.append(str(destino))


def _registro(**cambios) -> RegistroEstadoCuenta:
    base = dict(
        departamento_id=1,
        direccion="Rivadavia 3421",
        piso=None,
        depto=None,
        inquilino="Laura Giménez",
        anio=2026,
        mes=10,
        fecha_vencimiento=date(2026, 10, 5),
        monto_centavos=1_280_000,
        pagado_centavos=0,
        mora_pagada_centavos=0,
        dias_gracia=5,
        tasa_mora_bp=200,
    )
    base.update(cambios)
    return RegistroEstadoCuenta(**base)


def _cobranza(**cambios) -> FilaCobranzaMes:
    base = dict(
        id=5,
        cuota_id=5,
        contrato_id=1,
        departamento_id=1,
        direccion="Mitre 1180",
        piso=None,
        depto=None,
        inquilino="Diego Ferreyra",
        fecha_vencimiento=date(2026, 10, 10),
        monto_centavos=960_000,
        pagado_centavos=0,
        mora_centavos=None,
        saldo_centavos=None,
        estado="pendiente",
        dias_atraso=0,
    )
    base.update(cambios)
    return FilaCobranzaMes(**base)


def _atraso(**cambios) -> FilaAtraso:
    base = dict(
        id=7,
        cuota_id=7,
        contrato_id=1,
        departamento_id=1,
        direccion="Rivadavia 3421",
        piso=None,
        depto=None,
        inquilino="Laura Giménez",
        anio=2026,
        mes=9,
        fecha_vencimiento=date(2026, 9, 10),
        dias_atraso=35,
        cuota_centavos=1_280_000,
        mora_centavos=29_867,
        total_centavos=1_309_867,
    )
    base.update(cambios)
    return FilaAtraso(**base)


@pytest.fixture()
def entorno():
    repo = RepoInformesFalso()
    cobranzas = CobranzasFalsa()
    config = ConfigFalsa()
    escritor = EscritorFalso()
    respaldador = RespaldadorFalso()
    servicio = ServicioInformes(
        repositorio=repo,
        cobranzas=cobranzas,
        configuracion=config,
        respaldador=respaldador,
        escritor=escritor,
        reloj=RelojFijo(),
    )
    return repo, cobranzas, config, escritor, respaldador, servicio


# --- builders puros -----------------------------------------------------------


class TestCsvEstadoCuenta:
    def test_vencida_lleva_mora_viva_y_saldo(self):
        texto = csv_estado_cuenta([_registro()], HOY)
        lineas = texto.split("\r\n")
        assert (
            lineas[0]
            == "Unidad;Inquilino;Período;Vence;Cuota;Pagado;Mora;Saldo;Estado"
        )
        # Vencimiento 05/10, gracia 5, mora 2 % mensual: 10 días de atraso.
        # 1.280.000 × 200 × 10 / 300.000 = 8.533,33… → 8.533 centavos ($ 85,33).
        assert (
            lineas[1]
            == "Rivadavia 3421;Laura Giménez;octubre 2026;05/10/2026;"
            "12800,00;0,00;85,33;12885,33;Vencida"
        )

    def test_pagada_muestra_mora_cobrada_y_saldo_cero(self):
        texto = csv_estado_cuenta(
            [
                _registro(
                    monto_centavos=960_000,
                    pagado_centavos=960_000,
                    mora_pagada_centavos=10_000,
                )
            ],
            HOY,
        )
        linea = texto.split("\r\n")[1]
        assert linea.endswith(";9600,00;9600,00;100,00;0,00;Pagada")

    def test_dentro_de_la_gracia_no_hay_mora(self):
        texto = csv_estado_cuenta(
            [_registro(fecha_vencimiento=date(2026, 10, 10))], HOY
        )
        assert ";0,00;12800,00;Vencida" in texto


class TestCsvCobranzas:
    def test_fila_con_huecos_escribe_ceros(self):
        texto = csv_cobranzas_del_mes(
            CobranzasFalsa(filas=[_cobranza()]).del_mes(2026, 10)
        )
        lineas = texto.split("\r\n")
        assert lineas[0] == "Unidad;Inquilino;Vence;Cuota;Mora;Saldo;Estado"
        assert lineas[1] == "Mitre 1180;Diego Ferreyra;10/10/2026;9600,00;0,00;0,00;Pendiente"


class TestCsvMorosos:
    def test_columnas_y_montos(self):
        texto = csv_morosos([_atraso()])
        lineas = texto.split("\r\n")
        assert lineas[0] == "Unidad;Inquilino;Período;Vence;Días;Cuota;Mora hoy;Total"
        assert (
            lineas[1]
            == "Rivadavia 3421;Laura Giménez;septiembre 2026;10/09/2026;"
            "35;12800,00;298,67;13098,67"
        )


# --- servicio -----------------------------------------------------------------


class TestEstado:
    def test_flags_y_periodo(self, entorno):
        repo, _cob, config, _esc, _res, servicio = entorno
        repo.departamentos = 3
        repo.cuotas = 12
        config.ultimo = date(2026, 9, 24)

        estado = servicio.estado()
        assert (estado.anio, estado.mes) == (2026, 10)
        assert estado.fecha_calculo == HOY
        assert estado.hay_departamentos is True
        assert estado.hay_cuotas is True
        assert estado.cobranzas_generadas is True
        assert estado.hay_morosos is False
        assert estado.ultimo_respaldo == date(2026, 9, 24)


class TestExportar:
    def test_estado_cuenta_sin_cuotas_no_escribe(self, entorno):
        *_resto, servicio = entorno
        with pytest.raises(ErrorDeNegocio, match="No hay cuotas"):
            servicio.exportar_estado_cuenta("ec.csv")

    def test_estado_cuenta_escribe_y_filtra(self, entorno):
        repo, _cob, _cfg, escritor, _res, servicio = entorno
        repo.registros = [_registro(), _registro(departamento_id=2)]

        servicio.exportar_estado_cuenta("todas.csv")
        servicio.exportar_estado_cuenta("una.csv", departamento_id=2)

        assert [ruta for ruta, _ in escritor.escritos] == ["todas.csv", "una.csv"]
        assert escritor.escritos[0][1].count("\r\n") == 3  # header + 2 filas
        assert escritor.escritos[1][1].count("\r\n") == 2
        assert repo.filtros == [None, 2]

    def test_cobranzas_del_mes_sin_generar_bloquea(self, entorno):
        _repo, cob, _cfg, escritor, _res, servicio = entorno
        cob.generado = False
        with pytest.raises(ErrorDeNegocio, match="octubre 2026"):
            servicio.exportar_cobranzas_del_mes("c.csv")

        cob.generado = True
        cob.filas = [_cobranza()]
        servicio.exportar_cobranzas_del_mes("c.csv")
        (ruta, contenido), = escritor.escritos
        assert ruta == "c.csv"
        assert "Mitre 1180" in contenido

    def test_morosos_sin_filas_bloquea(self, entorno):
        *_resto, servicio = entorno
        with pytest.raises(ErrorDeNegocio, match="No hay morosos"):
            servicio.exportar_morosos("m.csv")

    def test_respaldo_registra_la_fecha(self, entorno):
        _repo, _cob, config, _esc, respaldador, servicio = entorno
        servicio.respaldar("copia.sqlite3")
        assert respaldador.destinos == ["copia.sqlite3"]
        assert config.registrados == [HOY]
