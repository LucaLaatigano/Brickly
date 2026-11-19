"""Tests de integración de punta a punta para Importación de Excel (H9).

Verifica los criterios de aceptación 1 y 2 de la especificación:
1. Descarga y reimportación de la plantilla (.xlsx) con idempotencia en segunda pasada.
2. Reimportación directa de la hoja 'Contratos' del export 'Excel completo' (H7).
"""

from datetime import date
from pathlib import Path

import pytest

from brickly.aplicacion.configuracion import ServicioConfiguracion
from brickly.aplicacion.departamentos import DatosContrato, DatosDepartamento, ServicioDepartamentos
from brickly.aplicacion.importacion import ServicioImportacionDepartamentos
from brickly.aplicacion.informes import ServicioInformes
from brickly.dominio.departamento import Departamento
from brickly.infraestructura.archivos import EscritorArchivosSistema, RespaldadorSQLite
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.configuracion import RepositorioConfiguracionSQLite
from brickly.infraestructura.db.repositorios.departamentos import RepositorioDepartamentosSQLite
from brickly.infraestructura.db.repositorios.informes import RepositorioInformesSQLite
from brickly.infraestructura.excel import EscritorExcelOpenpyxl, LectorExcelOpenpyxl


class RelojFijo:
    def __init__(self, fecha: date):
        self._fecha = fecha

    def hoy(self) -> date:
        return self._fecha


@pytest.fixture()
def con():
    conexion = abrir_conexion(":memory:")
    migrar(conexion)
    yield conexion
    conexion.close()


def test_criterio_1_plantilla_reimportada_e_idempotente(con, tmp_path: Path):
    reloj = RelojFijo(date(2026, 6, 1))
    repo_deptos = RepositorioDepartamentosSQLite(con, reloj=reloj)
    lector = LectorExcelOpenpyxl()
    escritor = EscritorExcelOpenpyxl()

    servicio = ServicioImportacionDepartamentos(
        repositorio_departamentos=repo_deptos,
        lector_excel=lector,
        reloj=reloj,
        escritor_excel=escritor,
    )

    ruta_plantilla = str(tmp_path / "plantilla.xlsx")
    servicio.generar_plantilla(ruta_plantilla)

    # Inspeccionamos la plantilla generada
    insp = servicio.inspeccionar_archivo(ruta_plantilla)
    assert "Departamentos y Contratos" in insp.hojas
    mapeo = {c.campo_mapeado: c.indice for c in insp.columnas_detectadas if c.campo_mapeado}

    # Primera pasada: debe importar 2 departamentos (1 con contrato vigente, 1 vacante)
    prev1 = servicio.previsualizar(
        ruta=ruta_plantilla,
        nombre_hoja="Departamentos y Contratos",
        fila_encabezado=insp.fila_encabezado_detectada,
        mapeo=mapeo,
    )
    assert prev1.total_filas == 2
    assert prev1.filas_listas == 2
    assert prev1.filas_con_errores == 0

    res1 = servicio.importar(
        ruta=ruta_plantilla,
        nombre_hoja="Departamentos y Contratos",
        fila_encabezado=insp.fila_encabezado_detectada,
        mapeo=mapeo,
    )
    assert res1.departamentos_creados == 2
    assert res1.contratos_creados == 1

    # Segunda pasada con el mismo archivo: ambas deben figurar como ya existentes (omitidas)
    prev2 = servicio.previsualizar(
        ruta=ruta_plantilla,
        nombre_hoja="Departamentos y Contratos",
        fila_encabezado=insp.fila_encabezado_detectada,
        mapeo=mapeo,
    )
    assert prev2.total_filas == 2
    assert prev2.filas_listas == 0
    assert prev2.filas_omitidas == 2
    for f in prev2.filas:
        assert f.estado == "omitido_existente"


def test_criterio_2_reimportar_hoja_contratos_del_export_h7(con, tmp_path: Path):
    hoy = date(2026, 6, 1)
    reloj = RelojFijo(hoy)
    repo_deptos = RepositorioDepartamentosSQLite(con, reloj=reloj)
    srv_deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)

    # 1. Cargamos un departamento con contrato en la base origen
    depto_id = srv_deptos.crear(
        DatosDepartamento(direccion="Rivadavia 3421", piso="3", depto="B", m2=48, propietario="Carlos")
    )
    srv_deptos.cargar_contrato(
        depto_id,
        DatosContrato(
            inquilino_nombre="Lucía Gómez",
            inquilino_telefono="11-4567-8901",
            inquilino_email="lucia.gomez@email.com",
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=None,
            monto_centavos=38000000,
            dia_vencimiento=10,
            dias_gracia=5,
            tasa_mora_bp=15,  # 0.15% diaria
            ciclo_meses=3,
            redondeo_centavos=1,
        ),
    )

    # 2. Exportamos el Excel completo de H7
    from brickly.aplicacion.cobranzas import ServicioCobranzas
    from brickly.infraestructura.db.repositorios.cobranzas import RepositorioCobranzasSQLite

    repo_informes = RepositorioInformesSQLite(con)
    repo_config = RepositorioConfiguracionSQLite(con)
    srv_config = ServicioConfiguracion(repo_config, reloj)
    srv_cobranzas = ServicioCobranzas(RepositorioCobranzasSQLite(con), reloj=reloj)
    escritor = EscritorExcelOpenpyxl()

    srv_informes = ServicioInformes(
        repositorio=repo_informes,
        cobranzas=srv_cobranzas,
        configuracion=srv_config,
        respaldador=RespaldadorSQLite(con),
        escritor=EscritorArchivosSistema(),
        reloj=reloj,
        escritor_excel=escritor,
    )

    ruta_export = str(tmp_path / "export_completo.xlsx")
    srv_informes.exportar_excel_completo(ruta_export)

    # 3. En una nueva base de datos vacía, importamos la hoja 'Contratos' del archivo generado
    con_destino = abrir_conexion(":memory:")
    migrar(con_destino)
    repo_deptos_dest = RepositorioDepartamentosSQLite(con_destino, reloj=reloj)
    lector = LectorExcelOpenpyxl()

    servicio_imp = ServicioImportacionDepartamentos(
        repositorio_departamentos=repo_deptos_dest,
        lector_excel=lector,
        reloj=reloj,
        escritor_excel=escritor,
    )

    insp = servicio_imp.inspeccionar_archivo(ruta_export)
    assert "Contratos" in insp.hojas

    # Leemos la hoja Contratos
    hoja_contratos = lector.leer_hoja(ruta_export, "Contratos")
    from brickly.aplicacion.importacion import sugerir_mapeo_columnas

    cols = sugerir_mapeo_columnas(hoja_contratos.filas[0], hoja_contratos.filas[1])
    mapeo = {c.campo_mapeado: c.indice for c in cols if c.campo_mapeado}

    # Verificamos auto-mapeo correcto
    assert mapeo["direccion"] == 0  # "Unidad" mapeado a direccion
    assert mapeo["nombre_inquilino"] == 1
    assert mapeo["fecha_inicio"] == 3
    assert mapeo["monto_inicial_centavos"] == 5  # "Cuota"

    prev = servicio_imp.previsualizar(
        ruta=ruta_export,
        nombre_hoja="Contratos",
        fila_encabezado=1,
        mapeo=mapeo,
    )

    assert prev.total_filas == 1
    assert prev.filas_listas == 1
    f = prev.filas[0]
    # Desglose de "Rivadavia 3421 · 3º B"
    assert f.direccion == "Rivadavia 3421"
    assert f.piso == "3"
    assert f.depto == "B"
    assert f.inquilino_nombre == "Lucía Gómez"
    assert f.monto_inicial_centavos == 38000000
    assert f.estado == "nuevo_con_contrato"

    # Confirmamos importación
    res = servicio_imp.importar(
        ruta=ruta_export,
        nombre_hoja="Contratos",
        fila_encabezado=1,
        mapeo=mapeo,
    )
    assert res.departamentos_creados == 1
    assert res.contratos_creados == 1

    # Verificamos la base destino
    deptos = repo_deptos_dest.listar()
    assert len(deptos) == 1
    assert deptos[0].direccion == "Rivadavia 3421"
    assert deptos[0].piso == "3"
    assert deptos[0].depto == "B"
    assert deptos[0].inquilino == "Lucía Gómez"
    assert deptos[0].cuota_vigente_centavos == 38000000
    con_destino.close()
