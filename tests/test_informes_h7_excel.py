"""Tests de H7: Excel completo (`LibroExportable`, `EscritorExcelOpenpyxl` y UI).

Verifica:
1. Sanitización de fórmulas (`=`, `+`, `-`, `@`) tanto en helpers puros como en
   las celdas del `.xlsx` generado.
2. Armado puro de `LibroExportable` en centavos enteros para las 6 hojas
   (`Resumen`, `Deudas`, `Pagos`, `Cuotas`, `Contratos`, `Ajustes IPC`).
3. Consistencia exacta de totales entre `LibroExportable`/`.xlsx` y los números
   de `Panel`, `Cobranzas` y `Departamentos`.
4. Formato del `.xlsx` real leído con `openpyxl.load_workbook`: encabezados en
   negrita, `freeze_panes = "A2"`, `auto_filter`, fechas `dd/mm/yyyy`, montos en
   pesos (`$ #,##0.00`), totales en negrita, resaltado de filas vencidas y
   preservación de acentos y `ñ`.
5. Manejo de archivo bloqueado (`PermissionError` cuando el `.xlsx` está abierto
   en Excel): mensaje claro en castellano y cero archivos temporales residuales.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from brickly.aplicacion.ajustes import (
    DatosAjuste,
    ServicioAjustesIpc,
)
from brickly.aplicacion.cobranzas import DatosPago, ServicioCobranzas
from brickly.aplicacion.configuracion import ServicioConfiguracion
from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.departamentos import (
    DatosContrato,
    DatosDepartamento,
    ServicioDepartamentos,
)
from brickly.aplicacion.informes import (
    LibroExportable,
    RegistroAjusteInforme,
    RegistroContratoInforme,
    RegistroDepartamentoInforme,
    RegistroEstadoCuenta,
    RegistroPagoInforme,
    ServicioInformes,
    armar_libro_excel,
    sanitizar_texto_excel,
)
from brickly.dominio.errores import ErrorDeNegocio
from brickly.infraestructura.archivos import EscritorArchivosSistema, RespaldadorSQLite
from brickly.infraestructura.db.conexion import abrir_conexion
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.ajustes import RepositorioAjustesSQLite
from brickly.infraestructura.db.repositorios.cobranzas import (
    RepositorioCobranzasSQLite,
)
from brickly.infraestructura.db.repositorios.configuracion import (
    RepositorioConfiguracionSQLite,
)
from brickly.infraestructura.db.repositorios.departamentos import (
    RepositorioDepartamentosSQLite,
)
from brickly.infraestructura.db.repositorios.informes import RepositorioInformesSQLite
from brickly.infraestructura.excel import (
    COLOR_VENCIDA_FONDO,
    COLOR_VENCIDA_TEXTO,
    FORMATO_FECHA_EXCEL,
    FORMATO_MONEDA_EXCEL,
    EscritorExcelOpenpyxl,
)
from brickly.ui.presenters.panel import PresenterPanel
from brickly.ui.vistas.informes import _tipos_archivo, nombre_excel_completo

HOY = date(2026, 10, 15)


class RelojFijo:
    def __init__(self, fecha: date = HOY):
        self.fecha = fecha

    def hoy(self) -> date:
        return self.fecha


class TestSanitizarTextoExcel:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("=SUM(A1:A10)", "'=SUM(A1:A10)"),
            ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
            ("-100+200", "'-100+200"),
            ("@SUM(1,2)", "'@SUM(1,2)"),
            ("  =1+1", "'  =1+1"),
            ("\t=1+1", "'\t=1+1"),
            ("Laura Giménez", "Laura Giménez"),
            ("Ñandú 123 1° B", "Ñandú 123 1° B"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_prefija_apostrofe_en_formulas_y_preserva_texto_normal(
        self, entrada: str | None, esperado: str
    ):
        assert sanitizar_texto_excel(entrada) == esperado


class TestArmarLibroExcelPuro:
    def test_calcula_totales_en_centavos_resalta_vencidas_y_sanitiza(self):
        departamentos = [
            RegistroDepartamentoInforme(
                departamento_id=1,
                direccion="Rivadavia 3421",
                piso="2",
                depto="A",
                inquilino="Laura Giménez",
                fecha_inicio_vigente=date(2026, 1, 1),
                cuota_vigente_centavos=1_280_000,
                ultimo_pago=date(2026, 8, 10),
            ),
            RegistroDepartamentoInforme(
                departamento_id=2,
                direccion="=Mitre 1180",
                piso=None,
                depto=None,
                inquilino=None,
                cuota_vigente_centavos=None,
                ultima_fecha_fin=date(2026, 9, 30),
                ultimo_pago=None,
            ),
        ]
        cuotas = [
            # Cuota de agosto pagada con mora congelada
            RegistroEstadoCuenta(
                departamento_id=1,
                direccion="Rivadavia 3421",
                piso="2",
                depto="A",
                inquilino="Laura Giménez",
                anio=2026,
                mes=8,
                fecha_vencimiento=date(2026, 8, 10),
                monto_centavos=1_200_000,
                pagado_centavos=1_200_000,
                mora_pagada_centavos=15_000,
                dias_gracia=5,
                tasa_mora_bp=200,
            ),
            # Cuota de septiembre vencida impaga (35 días de atraso a HOY 15/10 → mora 29.867)
            RegistroEstadoCuenta(
                departamento_id=1,
                direccion="Rivadavia 3421",
                piso="2",
                depto="A",
                inquilino="Laura Giménez",
                anio=2026,
                mes=9,
                fecha_vencimiento=date(2026, 9, 10),
                monto_centavos=1_280_000,
                pagado_centavos=0,
                mora_pagada_centavos=0,
                dias_gracia=5,
                tasa_mora_bp=200,
            ),
        ]
        pagos = [
            RegistroPagoInforme(
                pago_id=10,
                fecha=date(2026, 8, 10),
                direccion="Rivadavia 3421",
                piso="2",
                depto="A",
                inquilino="+Laura Giménez",
                medio="transferencia",
                nota="-Pago con recargo",
                monto_pago_centavos=1_215_000,
                anio_cuota=2026,
                mes_cuota=8,
                capital_imputado_centavos=1_200_000,
                mora_imputada_centavos=15_000,
            )
        ]
        contratos = [
            RegistroContratoInforme(
                contrato_id=1,
                direccion="Rivadavia 3421",
                piso="2",
                depto="A",
                inquilino="Laura Giménez",
                fecha_inicio=date(2026, 1, 1),
                fecha_fin=None,
                monto_centavos=1_280_000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
                ciclo_meses=3,
                redondeo_centavos=1,
            )
        ]
        ajustes = [
            RegistroAjusteInforme(
                ajuste_id=1,
                fecha_aplicacion=date(2026, 9, 1),
                direccion="Rivadavia 3421",
                piso="2",
                depto="A",
                inquilino="Laura Giménez",
                anio_base=2026,
                mes_base=6,
                meses_ciclo=3,
                variacion_bp=667,
                cuota_antes_centavos=1_200_000,
                cuota_despues_centavos=1_280_000,
                es_override=True,
                motivo_override="@Acuerdo partes",
            )
        ]

        libro = armar_libro_excel(
            departamentos=departamentos,
            cuotas=cuotas,
            pagos=pagos,
            contratos=contratos,
            ajustes=ajustes,
            hoy=HOY,
        )

        assert [h.nombre for h in libro.hojas] == [
            "Resumen",
            "Deudas",
            "Pagos",
            "Cuotas",
            "Contratos",
            "Ajustes IPC",
        ]

        resumen = libro.hoja("Resumen")
        assert len(resumen.filas) == 2
        assert resumen.filas[0].resaltada is True
        assert resumen.filas[1].resaltada is False
        assert resumen.filas[1].valores[0] == "'=Mitre 1180"
        assert resumen.filas[1].valores[2] == "Vencido (30/09/2026)"
        assert resumen.totales == (
            "Totales",
            None,
            None,
            1_280_000,
            1_280_000,
            29_867,
            1_309_867,
            None,
        )

        deudas = libro.hoja("Deudas")
        assert len(deudas.filas) == 1
        assert deudas.filas[0].resaltada is True
        assert deudas.totales == (
            "Totales",
            None,
            None,
            None,
            None,
            None,
            1_280_000,
            29_867,
            1_309_867,
        )

        hoja_pagos = libro.hoja("Pagos")
        assert hoja_pagos.filas[0].valores[2] == "'+Laura Giménez"
        assert hoja_pagos.filas[0].valores[9] == "'-Pago con recargo"
        assert hoja_pagos.totales == (
            "Totales",
            None,
            None,
            None,
            None,
            1_200_000,
            15_000,
            1_215_000,
            None,
            None,
        )

        hoja_ajustes = libro.hoja("Ajustes IPC")
        assert hoja_ajustes.filas[0].valores[3] == "jun–ago 2026"
        assert hoja_ajustes.filas[0].valores[9] == "'@Acuerdo partes"
        assert hoja_ajustes.totales == (
            "Totales",
            None,
            None,
            None,
            None,
            1_200_000,
            1_280_000,
            80_000,
            None,
            None,
        )


@pytest.fixture()
def entorno_h7(tmp_path: Path):
    con = abrir_conexion(":memory:")
    migrar(con)
    reloj = RelojFijo(HOY)
    repo_deptos = RepositorioDepartamentosSQLite(con, reloj=reloj)
    deptos = ServicioDepartamentos(repo_deptos, reloj=reloj)
    cobranzas = ServicioCobranzas(RepositorioCobranzasSQLite(con), reloj=reloj)
    ajustes = ServicioAjustesIpc(RepositorioAjustesSQLite(con), reloj=reloj)
    configuracion = ServicioConfiguracion(RepositorioConfiguracionSQLite(con), reloj)
    informes = ServicioInformes(
        repositorio=RepositorioInformesSQLite(con),
        cobranzas=cobranzas,
        configuracion=configuracion,
        respaldador=RespaldadorSQLite(con),
        escritor=EscritorArchivosSistema(),
        reloj=reloj,
        escritor_excel=EscritorExcelOpenpyxl(),
    )
    servicios = Servicios(
        departamentos=deptos,
        cobranzas=cobranzas,
        ajustes=ajustes,
        informes=informes,
        configuracion=configuracion,
    )
    yield con, servicios, reloj, tmp_path
    con.close()


class TestExcelCompletoIntegracion:
    def test_sin_departamentos_bloquea_exportacion(self, entorno_h7):
        _con, servicios, _reloj, tmp_path = entorno_h7
        ruta = tmp_path / "vacio.xlsx"
        with pytest.raises(ErrorDeNegocio, match="Cargá al menos un departamento"):
            servicios.informes.exportar_excel_completo(ruta)
        assert not ruta.exists()

    def test_xlsx_real_coincide_con_panel_y_cobranzas_y_aplica_formatos(
        self, entorno_h7
    ):
        _con, servicios, reloj, tmp_path = entorno_h7
        deptos = servicios.departamentos
        cobranzas = servicios.cobranzas
        ajustes = servicios.ajustes
        informes = servicios.informes

        # 1. Tres unidades: dos con contrato vigente y una sin contrato
        d1 = deptos.crear(
            DatosDepartamento(
                direccion="Rivadavia 3421",
                piso="1",
                depto="A",
                propietario="Martín Ibañez",
            )
        )
        d2 = deptos.crear(
            DatosDepartamento(
                direccion="Mitre 1180",
                piso="3",
                depto="B",
            )
        )
        deptos.crear(DatosDepartamento(direccion="Sarmiento 890"))

        deptos.cargar_contrato(
            d1,
            DatosContrato(
                inquilino_nombre="Laura Giménez",
                fecha_inicio=date(2026, 7, 1),
                monto_centavos=1_200_000,
                dia_vencimiento=5,
                dias_gracia=5,
                tasa_mora_bp=200,
                ciclo_meses=3,
                redondeo_centavos=1,
            ),
        )
        deptos.cargar_contrato(
            d2,
            DatosContrato(
                inquilino_nombre="Diego Ferreyra",
                fecha_inicio=date(2026, 8, 1),
                monto_centavos=960_000,
                dia_vencimiento=10,
                dias_gracia=5,
                tasa_mora_bp=200,
                ciclo_meses=3,
                redondeo_centavos=100,
            ),
        )

        # 2. IPC de jul-sep 2026 y ajuste aplicado a d1 en octubre 2026
        reloj.fecha = date(2026, 10, 1)
        ajustes.agregar_ipc(anio=2026, mes=7, variacion_bp=200)
        ajustes.agregar_ipc(anio=2026, mes=8, variacion_bp=300)
        ajustes.agregar_ipc(anio=2026, mes=9, variacion_bp=400)
        pendientes = ajustes.ajustes_por_aplicar().filas
        assert len(pendientes) == 1
        ajustes.aplicar(
            [
                DatosAjuste(
                    contrato_id=pendientes[0].contrato_id,
                    variacion_bp=pendientes[0].variacion_bp,
                )
            ]
        )

        # 3. Generar cuotas de septiembre y octubre, pagar septiembre y cobrar parcial octubre
        reloj.fecha = HOY  # 15/10/2026
        cobranzas.generar_cuotas(2026, 9)
        cobranzas.generar_cuotas(2026, 10)

        cuotas_sep = cobranzas.del_mes(2026, 9).filas
        for fila_sep in cuotas_sep:
            detalle_pago = cobranzas.preparar_pago(fila_sep.cuota_id)
            cobranzas.registrar_pago(
                DatosPago(
                    cuota_id=fila_sep.cuota_id,
                    fecha=date(2026, 9, 10),
                    monto_centavos=detalle_pago.total_centavos,
                    medio="transferencia",
                    nota="=Pago puntual",
                )
            )

        # En octubre (hoy 15/10):
        # - d1 venció el 05/10 (10 días de atraso > 5 de gracia → vencida con mora)
        # - d2 venció el 10/10; le pagamos todo el capital hoy (dentro de los 5 días de gracia → mora 0)
        cuotas_oct = {f.departamento_id: f for f in cobranzas.del_mes(2026, 10).filas}
        cobranzas.registrar_pago(
            DatosPago(
                cuota_id=cuotas_oct[d2].cuota_id,
                fecha=HOY,
                monto_centavos=cuotas_oct[d2].monto_centavos,
                medio="deposito",
                nota="Depósito por ventanilla",
            )
        )

        # 4. Exportar Excel y comparar contra Panel, Cobranzas y Departamentos
        ruta = tmp_path / "Brickly-informe-2026-10-15.xlsx"
        informes.exportar_excel_completo(ruta)
        assert ruta.is_file()

        panel = PresenterPanel(servicios).cargar()
        atrasos = cobranzas.atrasos()
        lista_deptos = deptos.listar()

        wb = openpyxl.load_workbook(ruta)
        try:
            assert wb.sheetnames == [
                "Resumen",
                "Deudas",
                "Pagos",
                "Cuotas",
                "Contratos",
                "Ajustes IPC",
            ]

            ws_resumen = wb["Resumen"]
            assert ws_resumen.freeze_panes == "A2"
            assert ws_resumen.auto_filter.ref == "A1:H4"
            assert ws_resumen["A1"].font.bold is True
            assert ws_resumen["A5"].value == "Totales"
            assert ws_resumen["A5"].font.bold is True

            # Total deuda en Resumen == suma de deudas en Departamentos == Panel vencidas_total_centavos
            deuda_esperada_pesos = Decimal(
                sum(d.deuda_centavos or 0 for d in lista_deptos)
            ) / Decimal(100)
            assert Decimal(str(ws_resumen["G5"].value)) == deuda_esperada_pesos
            assert Decimal(str(ws_resumen["G5"].value)) == Decimal(
                panel.vencidas_total_centavos
            ) / Decimal(100)
            assert ws_resumen["G5"].number_format == FORMATO_MONEDA_EXCEL

            # La fila de Rivadavia 3421 (vencida) está resaltada en Resumen
            filas_resumen_por_unidad = {
                ws_resumen.cell(row=r, column=1).value: r for r in range(2, 5)
            }
            fila_riv = filas_resumen_por_unidad["Rivadavia 3421 · 1º A"]
            assert ws_resumen.cell(row=fila_riv, column=1).fill.start_color.rgb.endswith(
                COLOR_VENCIDA_FONDO
            )
            assert ws_resumen.cell(row=fila_riv, column=1).font.color.rgb.endswith(
                COLOR_VENCIDA_TEXTO
            )
            assert (
                ws_resumen.cell(row=fila_riv, column=8).number_format
                == FORMATO_FECHA_EXCEL
            )

            # Hoja Deudas coincide con Cobranzas -> Atrasos
            ws_deudas = wb["Deudas"]
            assert ws_deudas.freeze_panes == "A2"
            assert len(atrasos) == 1
            assert Decimal(str(ws_deudas["I3"].value)) == Decimal(
                atrasos[0].total_centavos
            ) / Decimal(100)
            assert ws_deudas["A2"].fill.start_color.rgb.endswith(COLOR_VENCIDA_FONDO)

            # Hoja Pagos preserva acentos ("Depósito") y sanitiza "=Pago puntual"
            ws_pagos = wb["Pagos"]
            notas_pagos = [ws_pagos.cell(row=r, column=10).value for r in range(2, 5)]
            assert "'=Pago puntual" in notas_pagos
            medios_pagos = [ws_pagos.cell(row=r, column=5).value for r in range(2, 5)]
            assert "Depósito" in medios_pagos

            # Hoja Ajustes IPC tiene el ajuste trimestral aplicado
            ws_ajustes = wb["Ajustes IPC"]
            assert ws_ajustes["B2"].value == "Rivadavia 3421 · 1º A"
            assert ws_ajustes["C2"].value == "Laura Giménez"
            assert ws_ajustes["D2"].value == "jul–sep 2026"
        finally:
            wb.close()

    def test_error_claro_si_el_archivo_esta_abierto_en_excel(
        self, entorno_h7, monkeypatch
    ):
        _con, servicios, _reloj, tmp_path = entorno_h7
        servicios.departamentos.crear(DatosDepartamento(direccion="Rivadavia 3421"))
        destino = tmp_path / "abierto.xlsx"
        destino.write_bytes(b"contenido-previo")

        def _simular_archivo_bloqueado(origen, dest):
            raise PermissionError(32, "El proceso no tiene acceso al archivo")

        monkeypatch.setattr("brickly.infraestructura.excel.os.replace", _simular_archivo_bloqueado)

        with pytest.raises(PermissionError, match="abierto en Excel"):
            servicios.informes.exportar_excel_completo(destino)

        # El archivo original no se corrompió y no quedaron temporales `.tmp`
        assert destino.read_bytes() == b"contenido-previo"
        assert list(tmp_path.glob("*.tmp")) == []


class TestHelpersVistaInformesH7:
    def test_nombre_y_tipos_archivo_excel(self):
        assert nombre_excel_completo(date(2026, 10, 15)) == "Brickly-informe-2026-10-15.xlsx"
        assert _tipos_archivo(".xlsx") == [("Excel", "*.xlsx")]
        assert _tipos_archivo(".csv") == [("CSV", "*.csv")]
        assert _tipos_archivo(".sqlite3") == [("SQLite", "*.sqlite3")]
