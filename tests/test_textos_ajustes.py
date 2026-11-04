"""Textos exactos de la pantalla Ajustes IPC (spec §3.5 y §4 F4)."""

from datetime import date

from brickly.aplicacion.ajustes import (
    AjustePendiente,
    AjustesPorAplicar,
    ContratoParaAjuste,
    FilaHistorialAjuste,
    MesBase,
    RegistroIpc,
    ResultadoAjustes,
    ServicioAjustesIpc,
)
from brickly.aplicacion.contenedor import Servicios
from brickly.ui.presenters.ajuste import PresenterAjustes
from brickly.ui.vistas.ajustes_ipc import (
    anios_disponibles,
    texto_detalle_meses,
    texto_estado_por_aplicar,
    texto_exito_aplicacion,
    texto_formula_ipc,
    texto_motivo_bloqueo,
    texto_periodos,
    texto_resultado_aplicacion,
    texto_uso_ipc,
)


class RelojFijo:
    def hoy(self) -> date:
        return date(2026, 10, 15)


def _pendiente(
    contrato_id: int = 7,
    meses: tuple[MesBase, ...] = (
        MesBase(2026, 7, 210),
        MesBase(2026, 8, 340),
        MesBase(2026, 9, 370),
    ),
    variacion_bp: int | None = 948,
    cuota_actual_centavos: int = 1_280_000,
    cuota_nueva_centavos: int | None = 1_401_344,
    delta_centavos: int | None = 121_344,
) -> AjustePendiente:
    return AjustePendiente(
        id=contrato_id,
        contrato_id=contrato_id,
        departamento_id=1,
        direccion="Rivadavia 3421",
        piso="3",
        depto="B",
        inquilino="Laura Giménez",
        fecha_ajuste=date(2026, 10, 1),
        meses=meses,
        cuota_actual_centavos=cuota_actual_centavos,
        redondeo_centavos=1,
        variacion_bp=variacion_bp,
        cuota_nueva_centavos=cuota_nueva_centavos,
        delta_centavos=delta_centavos,
    )


class TestTextosPuros:
    def test_periodos_agrupa_rangos_consecutivos(self):
        assert texto_periodos([(2026, 4), (2026, 5), (2026, 6)]) == "abr–jun 2026"
        assert texto_periodos([(2026, 9)]) == "sep 2026"
        assert (
            texto_periodos([(2026, 11), (2027, 1)]) == "nov 2026 y ene 2027"
        )
        assert texto_periodos([(2026, 12), (2027, 1)]) == "dic 2026–ene 2027"

    def test_formula_ipc_compuesta_exacta_de_la_spec(self):
        # (1+2,10 %) × (1+3,40 %) × (1+3,70 %) − 1 = 9,4775… % → 948 bp
        assert (
            texto_formula_ipc(_pendiente())
            == "IPC jul–sep 2026: (1+2,10 %) × (1+3,40 %) × (1+3,70 %) − 1 = 9,48 %"
        )

    def test_detalle_meses_para_ver_meses(self):
        assert (
            texto_detalle_meses(_pendiente())
            == "jul 2026: 2,10 % · ago 2026: 3,40 % · sep 2026: 3,70 %"
        )

    def test_estado_por_aplicar_segun_chips(self):
        listo = _pendiente()
        faltante = _pendiente(
            contrato_id=8,
            meses=(
                MesBase(2026, 4, None),
                MesBase(2026, 5, None),
                MesBase(2026, 6, None),
            ),
            variacion_bp=None,
            cuota_nueva_centavos=None,
            delta_centavos=None,
        )
        estado = AjustesPorAplicar(
            fecha_calculo=date(2026, 10, 15), filas=[listo, faltante]
        )
        assert (
            texto_estado_por_aplicar(estado)
            == "1 contrato listo para ajustar · 1 contrato con datos faltantes."
        )
        assert (
            texto_motivo_bloqueo(estado)
            == "Faltan valores de IPC para ajustar: abr–jun 2026."
        )

        solo_listos = AjustesPorAplicar(
            fecha_calculo=date(2026, 10, 15), filas=[listo]
        )
        assert texto_estado_por_aplicar(solo_listos) == "1 contrato listo para ajustar."

    def test_resultado_y_exito_del_paso_3(self):
        resultado = ResultadoAjustes(
            cantidad=2,
            variacion_promedio_bp=942,
            total_antes_centavos=2_240_000,
            total_despues_centavos=2_451_000,
        )
        assert (
            texto_resultado_aplicacion(resultado)
            == "Se ajustan 2 contratos · cuota promedio +9,42 %"
        )
        assert (
            texto_exito_aplicacion(resultado)
            == "Se aplicaron 2 ajustes · cuota promedio +9,42 %"
        )

        unico = ResultadoAjustes(
            cantidad=1,
            variacion_promedio_bp=948,
            total_antes_centavos=1_280_000,
            total_despues_centavos=1_401_344,
        )
        assert (
            texto_resultado_aplicacion(unico)
            == "Se ajusta 1 contrato · cuota promedio +9,48 %"
        )
        assert (
            texto_exito_aplicacion(unico) == "Se aplicó 1 ajuste · cuota promedio +9,48 %"
        )

    def test_uso_ipc_en_confirmaciones(self):
        assert texto_uso_ipc(1) == "Lo usa 1 ajuste pendiente de este mes."
        assert texto_uso_ipc(3) == "Lo usan 3 ajustes pendientes de este mes."

    def test_anios_disponibles_alrededor_de_hoy(self):
        assert anios_disponibles(date(2026, 10, 16)) == [
            "2024",
            "2025",
            "2026",
            "2027",
        ]


class RepositorioFalso:
    """Solo lo que leen `filas_ipc`, `pendientes` e `historial` del servicio."""

    def __init__(self) -> None:
        self._ipc = [
            RegistroIpc(
                id=indice,
                anio=2026,
                mes=mes,
                variacion_bp=bp,
                origen="manual",
                cargado_en=date(2026, 10, 15),
            )
            for indice, (mes, bp) in enumerate(
                ((7, 210), (8, 340), (9, 370)), start=1
            )
        ]
        self._contratos = [
            ContratoParaAjuste(
                contrato_id=7,
                departamento_id=1,
                direccion="Rivadavia 3421",
                piso="3",
                depto="B",
                inquilino="Laura Giménez",
                fecha_inicio=date(2026, 7, 1),
                monto_centavos=1_280_000,
                ciclo_meses=3,
                redondeo_centavos=1,
            ),
            ContratoParaAjuste(
                contrato_id=8,
                departamento_id=2,
                direccion="Belgrano 500",
                piso=None,
                depto=None,
                inquilino="Marcos Paz",
                fecha_inicio=date(2026, 4, 10),
                monto_centavos=1_000_000,
                ciclo_meses=6,
                redondeo_centavos=1,
            ),
        ]

    def listar_ipc(self):
        return self._ipc

    def listar_contratos_para_ajuste(self):
        return self._contratos

    def listar_historial(self):
        return [
            FilaHistorialAjuste(
                id=1,
                contrato_id=6,
                direccion="Mitre 1180",
                piso="1",
                depto="A",
                inquilino="Sofía Ramos",
                fecha_aplicacion=date(2026, 10, 1),
                anio_base=2026,
                mes_base=7,
                meses_ciclo=3,
                variacion_bp=948,
                cuota_antes_centavos=1_280_000,
                cuota_despues_centavos=1_401_344,
                es_override=True,
                motivo_override="Pactado 8 % en contrato",
            )
        ]


class TestPresenterAjustes:
    def _presentador(self) -> PresenterAjustes:
        servicios = Servicios(
            departamentos=None,  # el presentador solo usa `ajustes`
            ajustes=ServicioAjustesIpc(RepositorioFalso(), RelojFijo()),
        )
        return PresenterAjustes(servicios)

    def test_filas_ipc_mapean_origen_y_uso(self):
        filas = self._presentador().filas_ipc()
        assert [fila.periodo for fila in filas] == [
            "julio 2026",
            "agosto 2026",
            "septiembre 2026",
        ]
        assert filas[0].origen == "Manual"
        # Julio es mes base de los dos contratos pendientes (Rivadavia y Belgrano).
        assert filas[0].contratos_que_lo_usan == 2
        assert filas[0].cargado_en == date(2026, 10, 15)

    def test_filas_por_aplicar_con_chips_y_faltantes(self):
        presentador = self._presentador()
        estado = presentador.pendientes()
        filas = presentador.filas_por_aplicar(estado)

        belgrano, rivadavia = filas  # ordenado por unidad
        assert rivadavia.meses_base == "jul–sep 2026"
        assert rivadavia.estado == "listo"
        assert rivadavia.faltantes == ()
        assert rivadavia.cuota_nueva_centavos == 1_401_344

        assert belgrano.estado == "faltan_datos"
        assert belgrano.faltantes == ((2026, 4), (2026, 5), (2026, 6))

    def test_historial_arma_cuota_antes_despues(self):
        (fila,) = self._presentador().historial()
        assert fila.meses_base == "jul–sep 2026"
        assert fila.cuota_transicion == "$ 12.800 → $ 14.013,44"
        assert fila.motivo_override == "Pactado 8 % en contrato"


class TestTextosH6Indec:
    def test_formatear_indice_milesimos(self):
        from brickly.ui.presenters.ajuste import formatear_indice_milesimos

        assert formatear_indice_milesimos(12_514_151) == "12.514,151"
        assert formatear_indice_milesimos(100_000) == "100,000"

    def test_origen_api_se_muestra_como_indec(self):
        repo = RepositorioFalso()
        repo._ipc.append(
            RegistroIpc(
                id=4,
                anio=2026,
                mes=10,
                variacion_bp=193,
                origen="api",
                cargado_en=date(2026, 11, 3),
                indice_milesimos=12_514_151,
            )
        )
        servicios = Servicios(
            departamentos=None,
            ajustes=ServicioAjustesIpc(repo, RelojFijo()),
        )
        filas = PresenterAjustes(servicios).filas_ipc()
        assert filas[-1].origen == "INDEC"

    def test_textos_fuente_y_preview_indec(self):
        from brickly.aplicacion.sincronizacion_ipc import (
            EstadoTokenIpc,
            ItemPreviewIpc,
            PreviewSincronizacionIpc,
            ResultadoPruebaIpc,
            ResultadoSincronizacionIpc,
        )
        from brickly.ui.vistas.ajustes_ipc import (
            texto_confirmar_reemplazo_manuales,
            texto_exito_sincronizacion_indec,
            texto_fuente_indec,
            texto_resumen_preview_indec,
        )
        from brickly.ui.vistas.configuracion import (
            texto_estado_token_indec,
            texto_resultado_prueba_indec,
        )

        sin_token = EstadoTokenIpc(
            configurado=False,
            token_enmascarado=None,
            fecha_emision=None,
            fecha_vencimiento=None,
            vencido=False,
            dias_restantes=None,
            ultima_sincronizacion=None,
            motivo_deshabilitado=(
                "Configurá el token de INDEC en Configuración para sincronizar."
            ),
        )
        assert texto_estado_token_indec(sin_token) == "Estado: Sin configurar"
        assert (
            texto_fuente_indec(sin_token)
            == "Fuente: INDEC · Configurá el token de INDEC en Configuración para sincronizar."
        )

        activo = EstadoTokenIpc(
            configurado=True,
            token_enmascarado="eyJh••••••vpwM",
            fecha_emision=date(2026, 11, 3),
            fecha_vencimiento=date(2027, 5, 2),
            vencido=False,
            dias_restantes=180,
            ultima_sincronizacion=date(2026, 11, 3),
            motivo_deshabilitado=None,
        )
        assert (
            texto_estado_token_indec(activo)
            == "Estado: Configurado (eyJh••••••vpwM) · Vence el 02/05/2027 · Última sincronización: 03/11/2026"
        )
        assert (
            texto_fuente_indec(activo)
            == "Fuente: INDEC · Última sincronización: 03/11/2026"
        )

        preview = PreviewSincronizacionIpc(
            fecha_consulta=date(2026, 11, 3),
            items=(
                ItemPreviewIpc(
                    anio=2026,
                    mes=9,
                    variacion_bp=193,
                    indice_milesimos=12_514_151,
                    variacion_actual_bp=None,
                    origen_actual=None,
                    estado="nuevo",
                    seleccionado_por_defecto=True,
                ),
                ItemPreviewIpc(
                    anio=2026,
                    mes=8,
                    variacion_bp=166,
                    indice_milesimos=12_277_386,
                    variacion_actual_bp=200,
                    origen_actual="manual",
                    estado="manual_protegido",
                    seleccionado_por_defecto=False,
                ),
            ),
        )
        assert (
            texto_resumen_preview_indec(preview)
            == "1 nuevo · 1 manual protegido"
        )
        assert "1 período" in texto_confirmar_reemplazo_manuales(1)
        assert "2 períodos" in texto_confirmar_reemplazo_manuales(2)

        exito = ResultadoSincronizacionIpc(
            nuevos=2, actualizados=1, reemplazados_manuales=0, omitidos=5
        )
        assert (
            texto_exito_sincronizacion_indec(exito)
            == "Sincronización con INDEC completada: 2 nuevos, 1 actualizado."
        )

        prueba = ResultadoPruebaIpc(
            ok=True,
            mensaje="Conexión verificada con INDEC.",
            ultimo_periodo=(2026, 9),
            ultima_variacion_bp=193,
            fecha_vencimiento=date(2027, 5, 2),
        )
        assert (
            texto_resultado_prueba_indec(prueba)
            == "Conexión verificada con INDEC. Último período: septiembre 2026 (1,93 %)."
        )

