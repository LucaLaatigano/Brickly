"""Pantalla Ajustes IPC (spec §3.5 — H3: valores, ajustes por aplicar, wizard, historial).

Tres secciones sobre la misma pantalla (`CTkSegmentedButton`): **Valores IPC**
(ABM con confirmación cuando un ajuste pendiente lo usa), **Ajustes por aplicar**
(lista con chips `Listo`/`Faltan datos` y CTA `Revisar y aplicar`) e **Historial**
(solo lectura).

El wizard de 3 pasos vive dentro de la misma pantalla (nunca modal), con stepper
visual 1–2–3: **Selección** (solo si hay varios contratos listos) · **Revisión**
con la celda «IPC aplicado» editable (override → chip `Ajustado a mano` +
motivo) · **Resultado**. Es efímero: salir a la mitad no persiste nada; si hubo
ediciones se avisa con confirmación. Aplicar es atómico — lo garantiza el
servicio — así que un error deja todo como estaba.

Todos los números (acumulado, cuota nueva, Δ, promedio) salen de
`ServicioAjustesIpc`; acá solo se formatea (§6.2).
"""

from __future__ import annotations

from datetime import date
import queue
import threading
from tkinter import messagebox

import customtkinter as ctk

from brickly.aplicacion.ajustes import (
    AjustePendiente,
    AjustesPorAplicar,
    DatosAjuste,
    ResultadoAjustes,
)
from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.sincronizacion_ipc import (
    EstadoTokenIpc,
    PreviewSincronizacionIpc,
    ResultadoSincronizacionIpc,
)
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.ui import estilo
from brickly.ui.componentes.chip import ChipEstado
from brickly.ui.componentes.formulario import Campo
from brickly.ui.componentes.tabla import Columna, Tabla
from brickly.ui.componentes.tarjeta import Tarjeta
from brickly.ui.formato import (
    MESES,
    formatear_fecha,
    formatear_mes_abreviado,
    formatear_monto,
    formatear_monto_con_signo,
    formatear_porcentaje,
    formatear_periodo,
    formatear_rango_meses,
    parsear_porcentaje,
)
from brickly.ui.presenters.ajuste import (
    FilaAjustePresentada,
    FilaHistorialPresentada,
    FilaIpcPresentada,
    FilaPreviewSincronizacionPresentada,
    PresenterAjustes,
    fila_ipc_de,
)
from brickly.ui.vistas.base import VistaBase

_SECCIONES = ("Valores IPC", "Ajustes por aplicar", "Historial")

_TITULOS_MES = [mes.capitalize() for mes in MESES]

_PLACEHOLDER_VARIACION = "3,70"


# --- funciones puras (testeables sin UI) -------------------------------------


def anios_disponibles(hoy: date) -> list[str]:
    """Años del selector de carga: el actual ±2 (el IPC puede cargarse rezagado)."""
    return [str(anio) for anio in range(hoy.year - 2, hoy.year + 2)]


def texto_uso_ipc(cantidad: int) -> str:
    """Consecuencia de editar/borrar un IPC usado por ajustes pendientes (§3.5 A)."""
    if cantidad == 1:
        return "Lo usa 1 ajuste pendiente de este mes."
    return f"Lo usan {cantidad} ajustes pendientes de este mes."


def texto_fuente_indec(estado: EstadoTokenIpc) -> str:
    """Línea de estado de la fuente oficial en Valores IPC (H6)."""
    if estado.motivo_deshabilitado:
        return f"Fuente: INDEC · {estado.motivo_deshabilitado}"
    if estado.ultima_sincronizacion is not None:
        return (
            "Fuente: INDEC · Última sincronización: "
            f"{formatear_fecha(estado.ultima_sincronizacion)}"
        )
    return "Fuente: INDEC · Listo para sincronizar"


def texto_resumen_preview_indec(preview: PreviewSincronizacionIpc) -> str:
    """Resumen de conteos por estado en la vista previa de sincronización."""
    partes: list[str] = []
    nuevos = len(preview.nuevos)
    actualizados = len(preview.actualizados)
    manuales = len(preview.manuales_protegidos)
    sin_cambios = len(preview.sin_cambios)
    if nuevos:
        partes.append("1 nuevo" if nuevos == 1 else f"{nuevos} nuevos")
    if actualizados:
        partes.append(
            "1 actualizado" if actualizados == 1 else f"{actualizados} actualizados"
        )
    if manuales:
        partes.append(
            "1 manual protegido"
            if manuales == 1
            else f"{manuales} manuales protegidos"
        )
    if sin_cambios:
        partes.append(f"{sin_cambios} sin cambios")
    return " · ".join(partes) if partes else "Sin períodos para mostrar"


def texto_exito_sincronizacion_indec(
    resultado: ResultadoSincronizacionIpc,
) -> str:
    """Banner de éxito tras importar valores desde INDEC."""
    partes: list[str] = []
    if resultado.nuevos:
        partes.append(
            "1 nuevo" if resultado.nuevos == 1 else f"{resultado.nuevos} nuevos"
        )
    if resultado.actualizados:
        partes.append(
            "1 actualizado"
            if resultado.actualizados == 1
            else f"{resultado.actualizados} actualizados"
        )
    if resultado.reemplazados_manuales:
        partes.append(
            "1 manual reemplazado"
            if resultado.reemplazados_manuales == 1
            else f"{resultado.reemplazados_manuales} manuales reemplazados"
        )
    if not partes:
        return "Sincronización con INDEC completada: sin cambios para importar."
    return f"Sincronización con INDEC completada: {', '.join(partes)}."


def texto_confirmar_reemplazo_manuales(cantidad: int) -> str:
    """Texto de confirmación explícita antes de pisar valores manuales (ADR-0003)."""
    if cantidad == 1:
        return (
            "Seleccionaste 1 período que fue cargado manualmente.\n\n"
            "¿Querés reemplazar ese valor manual por el oficial de INDEC?"
        )
    return (
        f"Seleccionaste {cantidad} períodos que fueron cargados manualmente.\n\n"
        "¿Querés reemplazar esos valores manuales por los oficiales de INDEC?"
    )


def texto_estado_por_aplicar(pendientes: AjustesPorAplicar) -> str:
    """Línea de estado encima de la lista de la sección B (§3.5)."""
    listos = len(pendientes.listos)
    faltantes = len(pendientes.filas) - listos
    partes: list[str] = []
    if listos:
        partes.append(
            "1 contrato listo para ajustar"
            if listos == 1
            else f"{listos} contratos listos para ajustar"
        )
    if faltantes:
        partes.append(
            "1 contrato con datos faltantes"
            if faltantes == 1
            else f"{faltantes} contratos con datos faltantes"
        )
    return " · ".join(partes) + "." if partes else ""


def texto_motivo_bloqueo(pendientes: AjustesPorAplicar) -> str:
    """Por qué el wizard no puede avanzar (§3.5: bloqueado con motivo)."""
    return (
        "Faltan valores de IPC para ajustar: "
        f"{texto_periodos(pendientes.meses_faltantes)}."
    )


def texto_periodos(periodos: list[tuple[int, int]]) -> str:
    """Períodos agrupados en rangos consecutivos: `jul–sep 2026`, `nov 2026 y ene 2027`."""
    if not periodos:
        return ""
    indices = sorted({anio * 12 + mes - 1 for anio, mes in periodos})
    tramos: list[tuple[int, int]] = []
    for indice in indices:
        if tramos and tramos[-1][1] == indice - 1:
            tramos[-1] = (tramos[-1][0], indice)
        else:
            tramos.append((indice, indice))
    textos: list[str] = []
    for inicio, fin in tramos:
        anio_ini, mes_ini = divmod(inicio, 12)
        anio_fin, mes_fin = divmod(fin, 12)
        textos.append(
            formatear_rango_meses(anio_ini, mes_ini + 1, anio_fin, mes_fin + 1)
        )
    if len(textos) == 1:
        return textos[0]
    return ", ".join(textos[:-1]) + " y " + textos[-1]


def texto_formula_ipc(pendiente: AjustePendiente) -> str:
    """Fórmula de la revisión (§3.5 paso 2): `IPC jul–sep 2026: (1+2,10 %) × … − 1 = 9,42 %`."""
    rango = formatear_rango_meses(*pendiente.desde, *pendiente.hasta)
    factores = " × ".join(
        f"(1+{formatear_porcentaje(mes.variacion_bp)})" for mes in pendiente.meses
    )
    return (
        f"IPC {rango}: {factores} − 1 = "
        f"{formatear_porcentaje(pendiente.variacion_bp)}"
    )


def texto_detalle_meses(pendiente: AjustePendiente) -> str:
    """Detalle del toggle `[ver meses]`: `jul 2026: 2,10 % · ago 2026: 3,40 % · …`."""
    return " · ".join(
        f"{formatear_mes_abreviado(mes.anio, mes.mes)}: "
        f"{formatear_porcentaje(mes.variacion_bp)}"
        for mes in pendiente.meses
    )


def texto_resultado_aplicacion(resultado: ResultadoAjustes) -> str:
    """Resumen del paso 3 (§3.5): `Se ajustan 2 contratos · cuota promedio +9,42 %`."""
    promedio = formatear_porcentaje(resultado.variacion_promedio_bp, con_signo=True)
    if resultado.cantidad == 1:
        return f"Se ajusta 1 contrato · cuota promedio {promedio}"
    return f"Se ajustan {resultado.cantidad} contratos · cuota promedio {promedio}"


def texto_exito_aplicacion(resultado: ResultadoAjustes) -> str:
    """Banner de éxito tras aplicar (§3.5 paso 3)."""
    ajustes = (
        "Se aplicó 1 ajuste"
        if resultado.cantidad == 1
        else f"Se aplicaron {resultado.cantidad} ajustes"
    )
    promedio = formatear_porcentaje(resultado.variacion_promedio_bp, con_signo=True)
    return f"{ajustes} · cuota promedio {promedio}"


def _mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    anio_sig, mes_0 = divmod(anio * 12 + mes, 12)
    return anio_sig, mes_0 + 1


# --- pantalla ----------------------------------------------------------------


class VistaAjustesIpc(VistaBase):
    def __init__(self, master, servicios: Servicios):
        super().__init__(master, titulo="Ajustes IPC")
        self._servicios = servicios
        self._presentador = PresenterAjustes(servicios)
        self._seccion = _SECCIONES[0]
        self._filas_ipc: list[FilaIpcPresentada] = []
        self._pendientes = AjustesPorAplicar(
            fecha_calculo=self._presentador.hoy(), filas=[]
        )
        self._historial: list[FilaHistorialPresentada] = []
        self._panel: PanelIpc | None = None
        self._wizard: WizardAjuste | None = None
        self._vista_previa_indec: VistaPreviaSincronizacionIpc | None = None
        self._boton_indec: ctk.CTkButton | None = None
        self._consultando_indec = False
        self._anio_form: int | None = None
        self._mes_form: int | None = None
        self._anios: list[str] = []
        self._campo_mes: Campo | None = None
        self._campo_anio: Campo | None = None
        self._campo_variacion: Campo | None = None

        self.cuerpo.grid_columnconfigure(0, weight=1)
        self.cuerpo.grid_columnconfigure(1, weight=0)
        self.cuerpo.grid_rowconfigure(0, weight=1)

        columna = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        columna.grid(row=0, column=0, sticky="nsew")
        columna.grid_columnconfigure(0, weight=1)
        columna.grid_rowconfigure(1, weight=1)

        self._selector = ctk.CTkSegmentedButton(
            columna,
            values=list(_SECCIONES),
            command=self._cambiar_seccion,
            height=estilo.ALTO_BOTON,
            corner_radius=estilo.RADIO_BOTON,
            fg_color=estilo.SUPERFICIE_2,
            selected_color=estilo.ACENTO,
            selected_hover_color=estilo.ACENTO_HOVER,
            unselected_color=estilo.SUPERFICIE,
            unselected_hover_color=estilo.SUPERFICIE_2,
            text_color=estilo.TEXTO,
            font=estilo.FUENTE_CHICO,
        )
        self._selector.grid(row=0, column=0, sticky="w", pady=(0, estilo.GAP))
        self._selector.set(self._seccion)

        self._area = ctk.CTkFrame(columna, fg_color="transparent")
        self._area.grid(row=1, column=0, sticky="nsew")
        self._area.grid_columnconfigure(0, weight=1)
        self._area.grid_rowconfigure(0, weight=1)

        self._cargar()

    # --- carga y render ------------------------------------------------------

    def _cargar(self) -> None:
        try:
            self._filas_ipc = self._presentador.filas_ipc()
            self._pendientes = self._presentador.pendientes()
            self._historial = self._presentador.historial()
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return
        self._render()

    def _cambiar_seccion(self, valor: str) -> None:
        self._seccion = valor
        self._cerrar_panel()
        self._cargar()

    def _render(self) -> None:
        for hijo in self._area.winfo_children():
            hijo.destroy()
        if self._seccion == "Valores IPC":
            self._pintar_valores()
        elif self._seccion == "Ajustes por aplicar":
            self._pintar_por_aplicar()
        else:
            self._pintar_historial()

    # --- A) valores IPC ------------------------------------------------------

    def _pintar_valores(self) -> None:
        marco = ctk.CTkFrame(self._area, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(1, weight=1)

        tarjeta = Tarjeta(marco, titulo="Cargar IPC mensual")
        tarjeta.grid(row=0, column=0, sticky="ew")

        hoy = self._presentador.hoy()
        anio_sugerido, mes_sugerido = self._presentador.periodo_sugerido()
        self._anios = anios_disponibles(hoy)
        if self._anio_form is None or str(self._anio_form) not in self._anios:
            anio_inicial, mes_inicial = anio_sugerido, mes_sugerido
        else:
            anio_inicial, mes_inicial = self._anio_form, self._mes_form or mes_sugerido

        cuerpo = tarjeta.cuerpo
        cuerpo.grid_columnconfigure(4, weight=1)

        self._campo_mes = Campo(
            cuerpo, "Mes", tipo="opciones", valores=_TITULOS_MES
        )
        self._campo_mes.poner_valor(_TITULOS_MES[mes_inicial - 1])
        self._campo_mes.grid(row=0, column=0, sticky="w")

        self._campo_anio = Campo(cuerpo, "Año", tipo="opciones", valores=self._anios)
        self._campo_anio.poner_valor(str(anio_inicial))
        self._campo_anio.grid(row=0, column=1, sticky="w", padx=(12, 0))

        self._campo_variacion = Campo(
            cuerpo, "Variación %", placeholder=_PLACEHOLDER_VARIACION
        )
        self._campo_variacion.grid(row=0, column=2, sticky="ew", padx=(12, 0))
        self._campo_variacion.atajo("<Return>", self._agregar_ipc)

        estilo.boton_primario(cuerpo, "Agregar", command=self._agregar_ipc).grid(
            row=0, column=3, sticky="s", padx=(12, 0)
        )

        # Franja de sincronización con INDEC (H6)
        ctk.CTkFrame(
            cuerpo, height=1, fg_color=estilo.BORDE, corner_radius=0
        ).grid(row=1, column=0, columnspan=5, sticky="ew", pady=(12, 10))

        barra_indec = ctk.CTkFrame(cuerpo, fg_color="transparent")
        barra_indec.grid(row=2, column=0, columnspan=5, sticky="ew")
        barra_indec.grid_columnconfigure(0, weight=1)

        estado_token = self._presentador.estado_token_indec()
        color_fuente = (
            estilo.ALERTA if estado_token.vencido else estilo.TEXTO_2
        )
        ctk.CTkLabel(
            barra_indec,
            text=texto_fuente_indec(estado_token),
            font=estilo.FUENTE_CHICO,
            text_color=color_fuente,
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, sticky="w")

        texto_boton = (
            "Consultando INDEC…"
            if self._consultando_indec
            else "Actualizar desde INDEC"
        )
        self._boton_indec = estilo.boton_secundario(
            barra_indec,
            texto_boton,
            command=self._iniciar_consulta_indec,
            height=estilo.ALTO_BOTON_FILA,
        )
        if not estado_token.habilitado or self._consultando_indec:
            self._boton_indec.configure(state="disabled")
        self._boton_indec.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self._tabla_valores = Tabla(
            marco,
            columnas=[
                Columna("Período", "periodo", 1.6),
                Columna(
                    "Variación",
                    "variacion_bp",
                    1.0,
                    alineacion="e",
                    formato=formatear_porcentaje,
                ),
                Columna("Origen", "origen", 1.0),
                Columna(
                    "Cargado el",
                    "cargado_en",
                    1.2,
                    alineacion="e",
                    formato=formatear_fecha,
                ),
                Columna(
                    "",
                    "id",
                    0.5,
                    alineacion="e",
                    texto_accion="✎",
                    al_accion=self._abrir_panel_ipc,
                    ancho_accion=40,
                ),
                Columna(
                    "",
                    "id",
                    0.5,
                    alineacion="e",
                    texto_accion="✕",
                    al_accion=self._confirmar_eliminar_ipc,
                    ancho_accion=40,
                ),
            ],
            mensaje_vacio="Cargá el primer IPC mensual",
        )
        self._tabla_valores.grid(row=1, column=0, sticky="nsew", pady=(estilo.GAP, 0))
        self._tabla_valores.mostrar(self._filas_ipc)

    def _agregar_ipc(self) -> None:
        if self._campo_mes is None or self._campo_anio is None or self._campo_variacion is None:
            return
        self._campo_mes.limpiar_error()
        self._campo_variacion.limpiar_error()

        mes = MESES.index(self._campo_mes.valor().lower()) + 1
        anio = int(self._campo_anio.valor())
        try:
            variacion_bp = parsear_porcentaje(self._campo_variacion.valor())
        except ValueError:
            self._campo_variacion.mostrar_error("Porcentaje inválido")
            self._campo_variacion.enfocar()
            return

        try:
            self._presentador.agregar_ipc(anio, mes, variacion_bp)
        except ErrorDeValidacion as error:
            if error.campo == "variacion":
                self._campo_variacion.mostrar_error(str(error))
                self._campo_variacion.enfocar()
            else:
                self._campo_mes.mostrar_error(str(error))
                self._campo_mes.enfocar()
            return
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return

        self._anio_form, self._mes_form = _mes_siguiente(anio, mes)
        self._cargar()
        self.mostrar_banner(
            "exito",
            f"IPC de {formatear_periodo(anio, mes)} cargado: "
            f"{formatear_porcentaje(variacion_bp)}.",
        )

    def _ir_a_valores(self, faltantes: tuple[tuple[int, int], ...] = ()) -> None:
        """Salto desde la sección B: abre Valores IPC con el período faltante sugerido."""
        if self._wizard is not None:
            return
        if faltantes:
            self._anio_form, self._mes_form = faltantes[0]
        self._seccion = "Valores IPC"
        self._selector.set(self._seccion)
        self._cerrar_panel()
        self._cargar()
        if self._campo_variacion is not None and self._campo_variacion.winfo_exists():
            self._campo_variacion.enfocar()

    def _abrir_panel_ipc(self, ipc_id: int) -> None:
        fila = fila_ipc_de(self._filas_ipc, ipc_id)
        if fila is None:
            return
        self._cerrar_panel()
        self._panel = PanelIpc(
            self.cuerpo,
            self._servicios,
            fila=fila,
            al_guardado=self._ipc_guardado,
            al_error=self._mostrar_error,
            al_cerrar=self._cerrar_panel,
        )
        self._panel.grid(row=0, column=1, sticky="ns", padx=(estilo.GAP, 0))

    def _cerrar_panel(self) -> None:
        if self._panel is not None:
            self._panel.destroy()
            self._panel = None

    def _ipc_guardado(self, mensaje: str) -> None:
        self._cerrar_panel()
        self._cargar()
        self.mostrar_banner("exito", mensaje)

    def _confirmar_eliminar_ipc(self, ipc_id: int) -> None:
        fila = fila_ipc_de(self._filas_ipc, ipc_id)
        if fila is None:
            return
        consecuencia = ""
        if fila.contratos_que_lo_usan:
            consecuencia = (
                f"\n\n{texto_uso_ipc(fila.contratos_que_lo_usan)} "
                "Los ajustes pendientes van a quedar con datos faltantes."
            )
        if not messagebox.askyesno(
            "Eliminar IPC",
            f"¿Eliminar el IPC de {fila.periodo}?{consecuencia}"
            "\n\nNo se puede deshacer.",
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            self._servicios.ajustes.eliminar_ipc(ipc_id)
        except ErrorDeNegocio as error:
            self._mostrar_error(str(error))
            return
        self._cerrar_panel()
        self._cargar()
        self.mostrar_banner("exito", f"IPC de {fila.periodo} eliminado.")

    # --- B) ajustes por aplicar ----------------------------------------------

    def _pintar_por_aplicar(self) -> None:
        marco = ctk.CTkFrame(self._area, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)

        fila_grid = 0
        if self._pendientes.filas:
            cabecera = ctk.CTkFrame(marco, fg_color="transparent")
            cabecera.grid(row=fila_grid, column=0, sticky="ew")
            cabecera.grid_columnconfigure(0, weight=1)
            fila_grid += 1

            ctk.CTkLabel(
                cabecera,
                text=texto_estado_por_aplicar(self._pendientes),
                font=estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO_2,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")

            self._boton_wizard = estilo.boton_primario(
                cabecera, "Revisar y aplicar", command=self._abrir_wizard
            )
            if not self._pendientes.listos:
                self._boton_wizard.configure(state="disabled")
            self._boton_wizard.grid(row=0, column=1, sticky="e")

        if self._pendientes.meses_faltantes:
            aviso = ctk.CTkFrame(marco, fg_color="transparent")
            aviso.grid(row=fila_grid, column=0, sticky="ew", pady=(8, 0))
            aviso.grid_columnconfigure(0, weight=1)
            fila_grid += 1

            ctk.CTkLabel(
                aviso,
                text=texto_motivo_bloqueo(self._pendientes),
                font=estilo.FUENTE_CHICO,
                text_color=estilo.ALERTA,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")

            estilo.boton_secundario(
                aviso,
                "Cargar valores IPC",
                command=self._ir_a_valores,
                height=estilo.ALTO_BOTON_FILA,
            ).grid(row=0, column=1, sticky="e")

        marco.grid_rowconfigure(fila_grid, weight=1)
        contenedor = ctk.CTkFrame(marco, fg_color="transparent")
        contenedor.grid(row=fila_grid, column=0, sticky="nsew", pady=(estilo.GAP, 0))
        contenedor.grid_columnconfigure(0, weight=1)
        contenedor.grid_rowconfigure(0, weight=1)

        if not self._pendientes.filas:
            ctk.CTkLabel(
                contenedor,
                text="No hay contratos que se ajusten este mes.",
                font=estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO_2,
            ).grid(row=0, column=0)
            return

        self._crear_lista_ajustes(
            contenedor, self._presentador.filas_por_aplicar(self._pendientes)
        )

    def _crear_lista_ajustes(
        self, padre: ctk.CTkFrame, filas: list[FilaAjustePresentada]
    ) -> None:
        scroll = ctk.CTkScrollableFrame(padre, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        encabezado = ctk.CTkFrame(
            scroll, fg_color="transparent", height=estilo.ALTO_ENCABEZADO_TABLA
        )
        encabezado.grid(row=0, column=0, sticky="ew")
        _configurar_columnas_ajustes(encabezado)
        for indice, (titulo, alineacion) in enumerate(
            (
                ("Unidad", "w"),
                ("Inquilino", "w"),
                ("Meses base", "w"),
                ("Estado", "w"),
                ("", "e"),
            )
        ):
            ctk.CTkLabel(
                encabezado,
                text=titulo,
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.TEXTO_2,
                anchor=alineacion,
            ).grid(row=0, column=indice, sticky="ew", padx=estilo.GAP // 2)
        ctk.CTkFrame(
            scroll, height=1, fg_color=estilo.BORDE, corner_radius=0
        ).grid(row=1, column=0, sticky="ew")

        for indice, fila in enumerate(filas):
            base = 2 + indice * 2
            self._crear_fila_ajuste(scroll, fila, base)
            if indice < len(filas) - 1:
                ctk.CTkFrame(
                    scroll, height=1, fg_color=estilo.BORDE, corner_radius=0
                ).grid(row=base + 1, column=0, sticky="ew")

    def _crear_fila_ajuste(
        self, scroll: ctk.CTkScrollableFrame, fila: FilaAjustePresentada, fila_grid: int
    ) -> None:
        marco = ctk.CTkFrame(
            scroll,
            fg_color=estilo.SUPERFICIE,
            corner_radius=0,
            height=estilo.ALTO_FILA,
        )
        marco.grid(row=fila_grid, column=0, sticky="ew")
        marco.grid_rowconfigure(0, weight=1)
        _configurar_columnas_ajustes(marco)

        ctk.CTkLabel(
            marco,
            text=fila.unidad,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=estilo.GAP // 2)
        ctk.CTkLabel(
            marco,
            text=fila.inquilino,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=estilo.GAP // 2)
        ctk.CTkLabel(
            marco,
            text=fila.meses_base,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=0, column=2, sticky="ew", padx=estilo.GAP // 2)

        celda_chip = ctk.CTkFrame(marco, fg_color="transparent")
        celda_chip.grid(row=0, column=3, sticky="w", padx=estilo.GAP // 2)
        ChipEstado(celda_chip, fila.estado).pack(side="left")

        if not fila.listo:
            acciones = ctk.CTkFrame(marco, fg_color="transparent")
            acciones.grid(row=0, column=4, sticky="e", padx=estilo.GAP // 2)
            estilo.boton_secundario(
                acciones,
                "Cargar IPC",
                command=lambda faltantes=fila.faltantes: self._ir_a_valores(faltantes),
                height=estilo.ALTO_BOTON_FILA,
                width=110,
            ).pack(side="right")

    # --- historial -----------------------------------------------------------

    def _pintar_historial(self) -> None:
        marco = ctk.CTkFrame(self._area, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(0, weight=1)

        tabla = Tabla(
            marco,
            columnas=[
                Columna(
                    "Fecha",
                    "fecha_aplicacion",
                    1.1,
                    alineacion="e",
                    formato=formatear_fecha,
                ),
                Columna("Unidad", "unidad", 2.4),
                Columna("Inquilino", "inquilino", 2.0),
                Columna("Meses base", "meses_base", 1.4),
                Columna(
                    "Variación",
                    "variacion_bp",
                    1.0,
                    alineacion="e",
                    formato=formatear_porcentaje,
                ),
                Columna("Cuota", "cuota_transicion", 1.8, alineacion="e"),
                Columna("Motivo", "motivo_override", 1.6),
            ],
            mensaje_vacio="Todavía no hay ajustes aplicados.",
        )
        tabla.grid(row=0, column=0, sticky="nsew")
        tabla.mostrar(self._historial)

    # --- sincronización con INDEC (H6) ---------------------------------------

    def _iniciar_consulta_indec(self) -> None:
        if self._consultando_indec or self._vista_previa_indec is not None:
            return
        estado = self._presentador.estado_token_indec()
        if not estado.habilitado:
            self.mostrar_banner(
                "alerta",
                estado.motivo_deshabilitado
                or "Configurá el token de INDEC en Configuración.",
            )
            return

        self._cerrar_panel()
        self.limpiar_banner()
        self._consultando_indec = True
        if self._boton_indec is not None and self._boton_indec.winfo_exists():
            self._boton_indec.configure(
                text="Consultando INDEC…", state="disabled"
            )

        cola: queue.Queue[tuple[str, object]] = queue.Queue()

        def _tarea() -> None:
            try:
                indices = self._presentador.consultar_indices_indec()
            except (ErrorDeNegocio, ErrorDeValidacion) as error:
                cola.put(("error", str(error)))
            except Exception:
                cola.put(
                    (
                        "error",
                        "No se pudo consultar la API de INDEC. Intentá más tarde o cargá el IPC manualmente.",
                    )
                )
            else:
                cola.put(("ok", indices))

        threading.Thread(target=_tarea, daemon=True).start()
        self.after(40, lambda: self._revisar_cola_consulta_indec(cola))

    def _revisar_cola_consulta_indec(
        self, cola: queue.Queue[tuple[str, object]]
    ) -> None:
        if not self.winfo_exists():
            return
        try:
            estado, valor = cola.get_nowait()
        except queue.Empty:
            self.after(40, lambda: self._revisar_cola_consulta_indec(cola))
            return
        if estado == "ok":
            self._finalizar_consulta_indec(valor)
        else:
            self._error_consulta_indec(str(valor))

    def _finalizar_consulta_indec(self, indices) -> None:
        if not self.winfo_exists():
            return
        try:
            preview = self._presentador.previsualizar_indec(indices=indices)
        except (ErrorDeNegocio, ErrorDeValidacion) as error:
            self._error_consulta_indec(str(error))
            return
        self._abrir_preview_indec(preview)

    def _error_consulta_indec(self, mensaje: str) -> None:
        self._consultando_indec = False
        if not self.winfo_exists():
            return
        if self._boton_indec is not None and self._boton_indec.winfo_exists():
            estado = self._presentador.estado_token_indec()
            self._boton_indec.configure(
                text="Actualizar desde INDEC",
                state="normal" if estado.habilitado else "disabled",
            )
        self.mostrar_banner("error", mensaje)

    def _abrir_preview_indec(self, preview: PreviewSincronizacionIpc) -> None:
        self._consultando_indec = False
        if not self.winfo_exists():
            return
        self._cerrar_panel()
        self.limpiar_banner()
        for hijo in self._area.winfo_children():
            hijo.destroy()
        self._selector.configure(state="disabled")
        self._vista_previa_indec = VistaPreviaSincronizacionIpc(
            self._area,
            self._presentador,
            preview=preview,
            al_importado=self._indec_importado,
            al_error=self._mostrar_error,
            al_cancelar=self._cerrar_preview_indec,
        )
        self._vista_previa_indec.grid(row=0, column=0, sticky="nsew")

    def _cerrar_preview_indec(self) -> None:
        if self._vista_previa_indec is not None:
            self._vista_previa_indec.destroy()
            self._vista_previa_indec = None
        self._selector.configure(state="normal")
        self._cargar()

    def _indec_importado(self, resultado: ResultadoSincronizacionIpc) -> None:
        self._cerrar_preview_indec()
        self.mostrar_banner(
            "exito", texto_exito_sincronizacion_indec(resultado)
        )

    # --- wizard --------------------------------------------------------------

    def _abrir_wizard(self) -> None:
        pendientes = self._presentador.pendientes()
        if not pendientes.listos:
            self.mostrar_banner("alerta", texto_motivo_bloqueo(pendientes))
            return
        self._cerrar_panel()
        self.limpiar_banner()
        for hijo in self._area.winfo_children():
            hijo.destroy()
        self._selector.configure(state="disabled")
        self._wizard = WizardAjuste(
            self._area,
            self._presentador,
            pendientes,
            al_aplicado=self._wizard_aplicado,
            al_error=self._mostrar_error,
            al_salir=self._salir_wizard,
        )
        self._wizard.grid(row=0, column=0, sticky="nsew")

    def _wizard_aplicado(self, resultado: ResultadoAjustes) -> None:
        self.mostrar_banner("exito", texto_exito_aplicacion(resultado))

    def _salir_wizard(self, destino: str | None) -> None:
        if self._wizard is not None:
            self._wizard.destroy()
            self._wizard = None
        self._selector.configure(state="normal")
        if destino is not None:
            self._seccion = destino
            self._selector.set(destino)
        self._cargar()

    def _mostrar_error(self, mensaje: str) -> None:
        self.mostrar_banner("error", mensaje)


def _configurar_columnas_ajustes(marco: ctk.CTkFrame) -> None:
    """Mismos pesos (x10) en encabezado y filas, como `Tabla`."""
    for indice, peso in enumerate((30, 26, 16, 14, 14)):
        marco.grid_columnconfigure(indice, weight=peso)


def _configurar_columnas_preview_indec(marco: ctk.CTkFrame) -> None:
    """Pesos de las columnas de la vista previa de sincronización INDEC."""
    for indice, peso in enumerate((8, 22, 16, 16, 20, 18)):
        marco.grid_columnconfigure(indice, weight=peso)


# --- vista previa de sincronización INDEC (H6) -------------------------------


class VistaPreviaSincronizacionIpc(ctk.CTkFrame):
    """Vista previa inline antes de importar IPC Nacional desde INDEC (ADR-0003).

    Muestra los estados `Nuevo`, `Actualizado`, `Sin cambios` y `Manual protegido`,
    permite elegir qué períodos importar y pide confirmación explícita si el
    usuario tilda algún período con carga manual.
    """

    def __init__(
        self,
        master,
        presentador: PresenterAjustes,
        preview: PreviewSincronizacionIpc,
        al_importado,
        al_error,
        al_cancelar,
    ):
        super().__init__(master, fg_color="transparent")
        self._presentador = presentador
        self._preview = preview
        self._filas = presentador.filas_preview_indec(preview)
        self._al_importado = al_importado
        self._al_error = al_error
        self._al_cancelar = al_cancelar
        self._seleccion: dict[tuple[int, int], ctk.BooleanVar] = {}
        self._estado_por_periodo: dict[tuple[int, int], str] = {
            f.periodo: f.estado for f in self._filas
        }

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        cabecera = Tarjeta(
            self, titulo="Vista previa — IPC Nacional (INDEC)"
        )
        cabecera.grid(row=0, column=0, sticky="ew")
        cabecera.cuerpo.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            cabecera.cuerpo,
            text=texto_resumen_preview_indec(preview),
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        if preview.manuales_protegidos:
            ctk.CTkLabel(
                cabecera.cuerpo,
                text=(
                    "Los períodos cargados manualmente quedan desmarcados por defecto "
                    "para no pisarlos. Tildalos solo si querés reemplazarlos por el dato oficial."
                ),
                font=estilo.FUENTE_CHICO,
                text_color=estilo.ALERTA,
                anchor="w",
                justify="left",
                wraplength=760,
            ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        marco_tabla = ctk.CTkFrame(
            self,
            fg_color=estilo.SUPERFICIE,
            corner_radius=estilo.RADIO_CARD,
            border_width=1,
            border_color=estilo.BORDE,
        )
        marco_tabla.grid(
            row=1, column=0, sticky="nsew", pady=(estilo.GAP, 0)
        )
        marco_tabla.grid_columnconfigure(0, weight=1)
        marco_tabla.grid_rowconfigure(1, weight=1)

        encabezado = ctk.CTkFrame(
            marco_tabla,
            fg_color="transparent",
            height=estilo.ALTO_ENCABEZADO_TABLA,
        )
        encabezado.grid(row=0, column=0, sticky="ew", padx=estilo.GAP // 2)
        _configurar_columnas_preview_indec(encabezado)
        for indice, (titulo, alineacion) in enumerate(
            (
                ("Importar", "w"),
                ("Período", "w"),
                ("Índice INDEC", "e"),
                ("Variación INDEC", "e"),
                ("Valor actual", "e"),
                ("Estado", "w"),
            )
        ):
            ctk.CTkLabel(
                encabezado,
                text=titulo,
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.TEXTO_2,
                anchor=alineacion,
            ).grid(
                row=0,
                column=indice,
                sticky="ew",
                padx=estilo.GAP // 2,
                pady=(8, 4),
            )

        scroll = ctk.CTkScrollableFrame(marco_tabla, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        for indice, fila in enumerate(self._filas):
            self._pintar_fila(scroll, fila, indice * 2)
            if indice < len(self._filas) - 1:
                ctk.CTkFrame(
                    scroll, height=1, fg_color=estilo.BORDE, corner_radius=0
                ).grid(row=indice * 2 + 1, column=0, sticky="ew")

        botones = ctk.CTkFrame(self, fg_color="transparent")
        botones.grid(row=2, column=0, sticky="ew", pady=(estilo.GAP, 0))
        botones.grid_columnconfigure(0, weight=1)

        estilo.boton_secundario(
            botones, "Cancelar", command=self._al_cancelar
        ).grid(row=0, column=0, sticky="w")

        self._boton_importar = estilo.boton_primario(
            botones,
            "Importar seleccionados",
            command=self._confirmar_importacion,
        )
        self._boton_importar.grid(row=0, column=1, sticky="e")
        self._actualizar_boton_importar()

    def _pintar_fila(
        self,
        scroll: ctk.CTkScrollableFrame,
        fila: FilaPreviewSincronizacionPresentada,
        fila_grid: int,
    ) -> None:
        marco = ctk.CTkFrame(
            scroll,
            fg_color="transparent",
            corner_radius=0,
            height=estilo.ALTO_FILA,
        )
        marco.grid(row=fila_grid, column=0, sticky="ew")
        marco.grid_rowconfigure(0, weight=1)
        _configurar_columnas_preview_indec(marco)

        var = ctk.BooleanVar(value=fila.seleccionado_por_defecto)
        self._seleccion[fila.periodo] = var
        chk = ctk.CTkCheckBox(
            marco,
            text="",
            variable=var,
            width=24,
            fg_color=estilo.ACENTO,
            hover_color=estilo.ACENTO_HOVER,
            border_color=estilo.BORDE,
            command=self._actualizar_boton_importar,
        )
        if fila.estado == "sin_cambios":
            chk.configure(state="disabled")
        chk.grid(row=0, column=0, sticky="w", padx=estilo.GAP // 2)

        ctk.CTkLabel(
            marco,
            text=fila.periodo_texto,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=estilo.GAP // 2)

        ctk.CTkLabel(
            marco,
            text=fila.indice_texto,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="e",
        ).grid(row=0, column=2, sticky="ew", padx=estilo.GAP // 2)

        ctk.CTkLabel(
            marco,
            text=fila.variacion_indec_texto,
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="e",
        ).grid(row=0, column=3, sticky="ew", padx=estilo.GAP // 2)

        ctk.CTkLabel(
            marco,
            text=fila.valor_actual_texto,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="e",
        ).grid(row=0, column=4, sticky="ew", padx=estilo.GAP // 2)

        celda_chip = ctk.CTkFrame(marco, fg_color="transparent")
        celda_chip.grid(row=0, column=5, sticky="w", padx=estilo.GAP // 2)
        ChipEstado(celda_chip, fila.estado).pack(side="left")

    def _periodos_marcados(self) -> list[tuple[int, int]]:
        return [
            periodo
            for periodo, var in self._seleccion.items()
            if bool(var.get())
        ]

    def _actualizar_boton_importar(self) -> None:
        marcados = self._periodos_marcados()
        self._boton_importar.configure(
            state="normal" if marcados else "disabled"
        )

    def _confirmar_importacion(self) -> None:
        seleccionados = self._periodos_marcados()
        if not seleccionados:
            return
        manuales = [
            p
            for p in seleccionados
            if self._estado_por_periodo.get(p) == "manual_protegido"
        ]
        if manuales and not messagebox.askyesno(
            "Reemplazar valores manuales",
            texto_confirmar_reemplazo_manuales(len(manuales)),
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return

        try:
            resultado = self._presentador.importar_indec(
                periodos_seleccionados=seleccionados,
                reemplazar_manuales=bool(manuales),
                preview=self._preview,
            )
        except (ErrorDeNegocio, ErrorDeValidacion) as error:
            self._al_error(str(error))
            return

        self._al_importado(resultado)


# --- panel de edición de un IPC ----------------------------------------------


class PanelIpc(ctk.CTkFrame):
    """Panel lateral de 380 px para editar un valor IPC (§3.5 A — nunca modal)."""

    ANCHO = 380

    def __init__(
        self,
        master,
        servicios: Servicios,
        fila: FilaIpcPresentada,
        al_guardado,
        al_error,
        al_cerrar,
    ):
        super().__init__(
            master,
            width=self.ANCHO,
            fg_color=estilo.SUPERFICIE,
            corner_radius=estilo.RADIO_CARD,
            border_width=1,
            border_color=estilo.BORDE,
        )
        self.grid_propagate(False)
        self.pack_propagate(False)
        self._servicios = servicios
        self._fila = fila
        self._al_guardado = al_guardado
        self._al_error = al_error
        self._al_cerrar = al_cerrar

        interior = ctk.CTkFrame(self, fg_color="transparent")
        interior.pack(
            fill="both",
            expand=True,
            padx=estilo.PADDING_CARD,
            pady=estilo.PADDING_CARD,
        )
        interior.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            interior,
            text="Editar IPC",
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            interior,
            text=fila.periodo,
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        ctk.CTkLabel(
            interior,
            text=f"Cargado el {formatear_fecha(fila.cargado_en)}",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        if fila.contratos_que_lo_usan:
            ctk.CTkLabel(
                interior,
                text=(
                    f"{texto_uso_ipc(fila.contratos_que_lo_usan)} "
                    "Sus cuotas se recalculan con el valor nuevo."
                ),
                font=estilo.FUENTE_CHICO,
                text_color=estilo.ALERTA,
                anchor="w",
                justify="left",
                wraplength=self.ANCHO - 2 * estilo.PADDING_CARD,
            ).grid(row=3, column=0, sticky="w", pady=(8, 0))

        self._campo_variacion = Campo(
            interior, "Variación %", placeholder=_PLACEHOLDER_VARIACION
        )
        self._campo_variacion.poner_valor(formatear_porcentaje(fila.variacion_bp))
        self._campo_variacion.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self._campo_variacion.atajo("<Return>", self._guardar)
        self._campo_variacion.atajo("<Escape>", self._cerrar)

        botones = ctk.CTkFrame(interior, fg_color="transparent")
        botones.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        botones.grid_columnconfigure(0, weight=1)

        estilo.boton_primario(botones, "Guardar", command=self._guardar).grid(
            row=0, column=0, sticky="ew"
        )
        estilo.boton_secundario(botones, "Cancelar", command=self._cerrar).grid(
            row=0, column=1, padx=(8, 0)
        )

        self._campo_variacion.enfocar()

    def _guardar(self) -> None:
        self._campo_variacion.limpiar_error()
        try:
            variacion_bp = parsear_porcentaje(self._campo_variacion.valor())
        except ValueError:
            self._campo_variacion.mostrar_error("Porcentaje inválido")
            self._campo_variacion.enfocar()
            return

        if variacion_bp == self._fila.variacion_bp:
            self._cerrar()
            return

        if self._fila.contratos_que_lo_usan and not messagebox.askyesno(
            "Editar IPC",
            f"¿Guardar el cambio del IPC de {self._fila.periodo}?"
            f"\n\n{texto_uso_ipc(self._fila.contratos_que_lo_usan)} "
            "Las cuotas de esos ajustes se van a recalcular con el valor nuevo.",
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return

        try:
            self._servicios.ajustes.editar_ipc(self._fila.id, variacion_bp)
        except ErrorDeValidacion as error:
            self._campo_variacion.mostrar_error(str(error))
            self._campo_variacion.enfocar()
            return
        except ErrorDeNegocio as error:
            self._al_error(str(error))
            return

        self._al_guardado(
            f"IPC de {self._fila.periodo} actualizado: "
            f"{formatear_porcentaje(variacion_bp)}."
        )

    def _cerrar(self) -> None:
        self._al_cerrar()


# --- wizard de 3 pasos -------------------------------------------------------


class WizardAjuste(ctk.CTkFrame):
    """Wizard de la sección B (§3.5): Selección → Revisión → Resultado.

    Efímero: nada se persiste hasta `Aplicar`; salir a la mitad con ediciones
    pide confirmación. La celda «IPC aplicado» recalcula en vivo contra el
    servicio; si difiere del cálculo IPC queda como override con motivo.
    """

    def __init__(
        self,
        master,
        presentador: PresenterAjustes,
        pendientes: AjustesPorAplicar,
        al_aplicado,
        al_error,
        al_salir,
    ):
        super().__init__(master, fg_color="transparent")
        self._presentador = presentador
        self._pendientes = pendientes
        self._al_aplicado = al_aplicado
        self._al_error = al_error
        self._al_salir = al_salir
        self._por_id: dict[int, AjustePendiente] = {
            fila.contrato_id: fila for fila in pendientes.filas
        }

        self._listos = pendientes.listos
        self._mostrar_paso_1 = len(self._listos) > 1
        self._paso = 1 if self._mostrar_paso_1 else 2
        self._seleccion: dict[int, bool] = {
            fila.contrato_id: True for fila in self._listos
        }
        self._seleccion_inicial = dict(self._seleccion)
        self._resultado: ResultadoAjustes | None = None

        self._entradas: dict[int, Campo] = {}
        self._labels_nueva: dict[int, ctk.CTkLabel] = {}
        self._labels_delta: dict[int, ctk.CTkLabel] = {}
        self._filas_override: dict[int, ctk.CTkFrame] = {}
        self._campos_motivo: dict[int, Campo] = {}
        self._detalles_meses: dict[int, tuple[ctk.CTkLabel, ctk.CTkButton]] = {}
        self._meses_visibles: dict[int, bool] = {}
        self._boton_continuar: ctk.CTkButton | None = None
        self._boton_aplicar: ctk.CTkButton | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._franja_pasos = ctk.CTkFrame(self, fg_color="transparent")
        self._franja_pasos.grid(row=0, column=0, sticky="w", pady=(0, estilo.GAP))

        self._cuerpo_paso = ctk.CTkFrame(self, fg_color="transparent")
        self._cuerpo_paso.grid(row=1, column=0, sticky="nsew")
        self._cuerpo_paso.grid_columnconfigure(0, weight=1)
        self._cuerpo_paso.grid_rowconfigure(0, weight=1)

        self._pintar_paso()

    # --- comunes -------------------------------------------------------------

    def _pintar_paso(self) -> None:
        self._pintar_stepper()
        for hijo in self._cuerpo_paso.winfo_children():
            hijo.destroy()
        self._entradas.clear()
        self._labels_nueva.clear()
        self._labels_delta.clear()
        self._filas_override.clear()
        self._campos_motivo.clear()
        self._detalles_meses.clear()
        self._meses_visibles.clear()
        if self._paso == 1:
            self._pintar_seleccion()
        elif self._paso == 2:
            self._pintar_revision()
        else:
            self._pintar_resultado()

    def _pintar_stepper(self) -> None:
        for hijo in self._franja_pasos.winfo_children():
            hijo.destroy()
        pasos = ((1, "Selección"), (2, "Revisión"), (3, "Resultado"))
        for indice, (numero, nombre) in enumerate(pasos):
            estado = self._estado_paso(numero)
            if estado == "activo":
                color, fuente = estilo.ACENTO, estilo.FUENTE_CHICO_NEGRITA
            elif estado == "completado":
                color, fuente = estilo.EXITO, estilo.FUENTE_CHICO_NEGRITA
            else:
                color, fuente = estilo.TEXTO_3, estilo.FUENTE_CHICO
            ctk.CTkLabel(
                self._franja_pasos,
                text=f"{numero} {nombre}",
                font=fuente,
                text_color=color,
            ).pack(side="left")
            if indice < len(pasos) - 1:
                ctk.CTkLabel(
                    self._franja_pasos,
                    text="›",
                    font=estilo.FUENTE_CHICO,
                    text_color=estilo.TEXTO_3,
                ).pack(side="left", padx=6)

    def _estado_paso(self, numero: int) -> str:
        if numero == 1 and not self._mostrar_paso_1:
            return "completado"
        if numero < self._paso:
            return "completado"
        if numero == self._paso:
            return "activo"
        return "pendiente"

    def _seleccionados(self) -> list[int]:
        return [
            fila.contrato_id
            for fila in self._pendientes.filas
            if self._seleccion.get(fila.contrato_id)
        ]

    def _hay_ediciones(self) -> bool:
        if self._seleccion != self._seleccion_inicial:
            return True
        return any(
            entrada.valor().strip()
            != formatear_porcentaje(self._por_id[cid].variacion_bp)
            for cid, entrada in self._entradas.items()
        )

    def _salir(self, destino: str | None) -> None:
        if self._hay_ediciones() and not messagebox.askyesno(
            "Salir del ajuste",
            "¿Salir del ajuste sin aplicar?\n\n"
            "Se pierden los cambios sin aplicar. Ninguna cuota se modificó.",
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return
        self._al_salir(destino)

    def _cerrar(self) -> None:
        self._al_salir("Ajustes por aplicar")

    # --- paso 1: selección ---------------------------------------------------

    def _pintar_seleccion(self) -> None:
        marco = ctk.CTkFrame(self._cuerpo_paso, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            marco,
            text="Elegí los contratos a ajustar. Vienen todos marcados.",
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        lista = ctk.CTkScrollableFrame(marco, fg_color="transparent")
        lista.grid(row=1, column=0, sticky="nsew")
        lista.grid_columnconfigure(0, weight=1)

        for indice, pendiente in enumerate(self._pendientes.filas):
            self._fila_seleccion(lista, indice, pendiente)

        botones = ctk.CTkFrame(marco, fg_color="transparent")
        botones.grid(row=2, column=0, sticky="ew", pady=(estilo.GAP, 0))
        botones.grid_columnconfigure(0, weight=1)

        estilo.boton_secundario(botones, "Cancelar", command=self._cerrar).grid(
            row=0, column=0, sticky="w"
        )
        self._boton_continuar = estilo.boton_primario(
            botones, "Continuar", command=self._continuar
        )
        self._boton_continuar.grid(row=0, column=1, sticky="e")
        self._actualizar_boton_continuar()

    def _fila_seleccion(
        self, lista: ctk.CTkScrollableFrame, indice: int, pendiente: AjustePendiente
    ) -> None:
        marco = ctk.CTkFrame(
            lista,
            fg_color=estilo.SUPERFICIE,
            corner_radius=0,
            height=estilo.ALTO_FILA + 12,
        )
        marco.grid(row=indice, column=0, sticky="ew")
        marco.grid_columnconfigure(1, weight=1)

        variable = ctk.BooleanVar(master=self, value=pendiente.listo)
        casilla = ctk.CTkCheckBox(
            marco,
            text="",
            variable=variable,
            width=24,
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=4,
            fg_color=estilo.ACENTO,
            hover_color=estilo.ACENTO_HOVER,
            border_color=estilo.BORDE,
            checkmark_color=estilo.BLANCO,
        )
        if not pendiente.listo:
            casilla.configure(state="disabled")
        else:
            casilla.configure(
                command=lambda cid=pendiente.contrato_id, var=variable: self._cambiar_seleccion(
                    cid, var
                )
            )
        casilla.grid(row=0, column=0, padx=(estilo.GAP, 8), pady=10)

        textos = ctk.CTkFrame(marco, fg_color="transparent")
        textos.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(
            textos,
            text=pendiente.unidad,
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).pack(anchor="w")

        detalle = (
            f"{pendiente.inquilino} · "
            f"{formatear_rango_meses(*pendiente.desde, *pendiente.hasta)}"
        )
        if not pendiente.listo:
            detalle += f" · Falta {texto_periodos(pendiente.meses_faltantes)}"
        ctk.CTkLabel(
            textos,
            text=detalle,
            font=estilo.FUENTE_CHICO,
            text_color=estilo.ALERTA if not pendiente.listo else estilo.TEXTO_2,
            anchor="w",
        ).pack(anchor="w")

        celda_chip = ctk.CTkFrame(marco, fg_color="transparent")
        celda_chip.grid(row=0, column=2, sticky="e", padx=(8, estilo.GAP))
        ChipEstado(celda_chip, pendiente.estado).pack(side="right")

    def _cambiar_seleccion(self, contrato_id: int, variable: ctk.BooleanVar) -> None:
        self._seleccion[contrato_id] = bool(variable.get())
        self._actualizar_boton_continuar()

    def _actualizar_boton_continuar(self) -> None:
        habilitado = any(self._seleccion.values())
        if self._boton_continuar is not None and self._boton_continuar.winfo_exists():
            self._boton_continuar.configure(
                state="normal" if habilitado else "disabled"
            )

    def _continuar(self) -> None:
        self._paso = 2
        self._pintar_paso()

    # --- paso 2: revisión ----------------------------------------------------

    def _pintar_revision(self) -> None:
        seleccionados = [
            fila
            for fila in self._pendientes.filas
            if self._seleccion.get(fila.contrato_id)
        ]
        marco = ctk.CTkFrame(self._cuerpo_paso, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            marco,
            text=(
                "La celda «IPC aplicado» es editable: si la cambiás, el ajuste "
                "queda como «Ajustado a mano» y pide el motivo."
            ),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        lista = ctk.CTkScrollableFrame(marco, fg_color="transparent")
        lista.grid(row=1, column=0, sticky="nsew")
        lista.grid_columnconfigure(0, weight=1)

        encabezado = ctk.CTkFrame(
            lista, fg_color="transparent", height=estilo.ALTO_ENCABEZADO_TABLA
        )
        encabezado.grid(row=0, column=0, sticky="ew")
        _configurar_columnas_revision(encabezado)
        for indice, (titulo, alineacion) in enumerate(
            (
                ("Unidad", "w"),
                ("Cuota actual", "e"),
                ("IPC aplicado", "e"),
                ("Cuota nueva", "e"),
                ("Δ", "e"),
            )
        ):
            ctk.CTkLabel(
                encabezado,
                text=titulo,
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.TEXTO_2,
                anchor=alineacion,
            ).grid(row=0, column=indice, sticky="ew", padx=estilo.GAP // 2)
        ctk.CTkFrame(
            lista, height=1, fg_color=estilo.BORDE, corner_radius=0
        ).grid(row=1, column=0, sticky="ew")

        for indice, pendiente in enumerate(seleccionados):
            base = 2 + indice * 4
            self._bloque_revision(lista, base, pendiente)
            if indice < len(seleccionados) - 1:
                ctk.CTkFrame(
                    lista, height=1, fg_color=estilo.BORDE, corner_radius=0
                ).grid(row=base + 3, column=0, sticky="ew")

        botones = ctk.CTkFrame(marco, fg_color="transparent")
        botones.grid(row=2, column=0, sticky="ew", pady=(estilo.GAP, 0))
        botones.grid_columnconfigure(0, weight=1)

        estilo.boton_secundario(botones, "← Atrás", command=self._atras).grid(
            row=0, column=0, sticky="w"
        )
        self._boton_aplicar = estilo.boton_primario(
            botones, self._texto_boton_aplicar(), command=self._aplicar
        )
        self._boton_aplicar.grid(row=0, column=1, sticky="e")

    def _bloque_revision(
        self, lista: ctk.CTkScrollableFrame, base: int, pendiente: AjustePendiente
    ) -> None:
        cid = pendiente.contrato_id

        fila = ctk.CTkFrame(lista, fg_color=estilo.SUPERFICIE, corner_radius=0)
        fila.grid(row=base, column=0, sticky="ew")
        fila.grid_rowconfigure(0, weight=1)
        _configurar_columnas_revision(fila)

        ctk.CTkLabel(
            fila,
            text=pendiente.unidad,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=estilo.GAP // 2, pady=6)
        ctk.CTkLabel(
            fila,
            text=formatear_monto(pendiente.cuota_actual_centavos),
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="e",
        ).grid(row=0, column=1, sticky="ew", padx=estilo.GAP // 2)

        entrada = Campo(fila, etiqueta=None, justificar="right")
        entrada.poner_valor(formatear_porcentaje(pendiente.variacion_bp))
        entrada.al_cambiar(lambda cid=cid: self._al_editar_variacion(cid))
        entrada.atajo("<Return>", self._aplicar)
        entrada.atajo("<Escape>", self._cerrar)
        entrada.grid(row=0, column=2, sticky="ew", padx=estilo.GAP // 2, pady=6)
        self._entradas[cid] = entrada

        nueva = ctk.CTkLabel(
            fila,
            text=formatear_monto(pendiente.cuota_nueva_centavos),
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="e",
        )
        nueva.grid(row=0, column=3, sticky="ew", padx=estilo.GAP // 2)
        self._labels_nueva[cid] = nueva

        delta = ctk.CTkLabel(
            fila,
            text=formatear_monto_con_signo(pendiente.delta_centavos),
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="e",
        )
        delta.grid(row=0, column=4, sticky="ew", padx=estilo.GAP // 2)
        self._labels_delta[cid] = delta

        # Override: chip + motivo, oculto hasta que la celda difiera del IPC
        auto = ctk.CTkFrame(lista, fg_color=estilo.SUPERFICIE, corner_radius=0)
        auto.grid(row=base + 1, column=0, sticky="ew")
        auto.grid_columnconfigure(1, weight=1)
        ChipEstado(auto, "info", texto="Ajustado a mano").grid(
            row=0, column=0, sticky="sw", padx=(estilo.GAP, 8), pady=(2, 10)
        )
        campo_motivo = Campo(
            auto,
            "Motivo del ajuste a mano",
            placeholder="Ej.: % pactado distinto en el contrato",
        )
        campo_motivo.grid(row=0, column=1, sticky="ew", padx=(0, estilo.GAP), pady=(0, 10))
        auto.grid_remove()
        self._filas_override[cid] = auto
        self._campos_motivo[cid] = campo_motivo

        # Fórmula del ciclo + detalle mensual (§3.5 paso 2)
        formula = ctk.CTkFrame(lista, fg_color="transparent")
        formula.grid(row=base + 2, column=0, sticky="ew", pady=(6, 8))
        formula.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            formula,
            text=texto_formula_ipc(pendiente),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=estilo.GAP // 2)

        detalle = ctk.CTkLabel(
            formula,
            text=texto_detalle_meses(pendiente),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
            justify="left",
        )
        detalle.grid(
            row=1, column=0, columnspan=2, sticky="w", padx=estilo.GAP // 2, pady=(2, 0)
        )
        detalle.grid_remove()

        boton_meses = ctk.CTkButton(
            formula,
            text="ver meses",
            command=lambda cid=cid: self._alternar_meses(cid),
            width=78,
            height=24,
            corner_radius=estilo.RADIO_BOTON,
            fg_color="transparent",
            hover_color=estilo.SUPERFICIE_2,
            text_color=estilo.ACENTO,
            font=estilo.FUENTE_CHICO,
        )
        boton_meses.grid(row=0, column=1, sticky="e", padx=(8, estilo.GAP // 2))
        self._detalles_meses[cid] = (detalle, boton_meses)

    def _alternar_meses(self, contrato_id: int) -> None:
        detalle, boton = self._detalles_meses[contrato_id]
        visible = self._meses_visibles.get(contrato_id, False)
        if visible:
            detalle.grid_remove()
            boton.configure(text="ver meses")
        else:
            detalle.grid()
            boton.configure(text="ocultar")
        self._meses_visibles[contrato_id] = not visible

    def _al_editar_variacion(self, contrato_id: int) -> None:
        entrada = self._entradas[contrato_id]
        try:
            variacion_bp = parsear_porcentaje(entrada.valor())
        except ValueError:
            entrada.mostrar_error("Porcentaje inválido")
            return
        try:
            preview = self._presentador.calcular_cuota(contrato_id, variacion_bp)
        except (ErrorDeValidacion, ErrorDeNegocio) as error:
            entrada.mostrar_error(str(error))
            return

        entrada.limpiar_error()
        self._labels_nueva[contrato_id].configure(
            text=formatear_monto(preview.cuota_nueva_centavos)
        )
        self._labels_delta[contrato_id].configure(
            text=formatear_monto_con_signo(preview.delta_centavos)
        )
        if preview.es_override:
            self._filas_override[contrato_id].grid()
            self._campos_motivo[contrato_id].limpiar_error()
        else:
            self._filas_override[contrato_id].grid_remove()

    def _texto_boton_aplicar(self) -> str:
        cantidad = len(self._seleccionados())
        return "Aplicar 1 ajuste" if cantidad == 1 else f"Aplicar {cantidad} ajustes"

    def _atras(self) -> None:
        if self._mostrar_paso_1:
            self._paso = 1
            self._pintar_paso()
        else:
            self._salir("Ajustes por aplicar")

    def _aplicar(self) -> None:
        datos: list[DatosAjuste] = []
        for cid in self._seleccionados():
            entrada = self._entradas[cid]
            try:
                variacion_bp = parsear_porcentaje(entrada.valor())
            except ValueError:
                entrada.mostrar_error("Porcentaje inválido")
                entrada.enfocar()
                return
            try:
                preview = self._presentador.calcular_cuota(cid, variacion_bp)
            except (ErrorDeValidacion, ErrorDeNegocio) as error:
                entrada.mostrar_error(str(error))
                entrada.enfocar()
                return

            motivo = None
            if preview.es_override:
                campo_motivo = self._campos_motivo[cid]
                motivo = campo_motivo.valor().strip()
                if not motivo:
                    campo_motivo.mostrar_error("Indicá el motivo del ajuste a mano.")
                    campo_motivo.enfocar()
                    return
            datos.append(
                DatosAjuste(
                    contrato_id=cid,
                    variacion_bp=preview.variacion_bp,
                    motivo_override=motivo,
                )
            )

        if self._boton_aplicar is not None:
            self._boton_aplicar.configure(text="Aplicando…", state="disabled")
            self.update_idletasks()

        try:
            resultado = self._presentador.aplicar(datos)
        except (ErrorDeValidacion, ErrorDeNegocio) as error:
            self._al_error(f"No se pudo aplicar: {error}. No se modificó nada.")
            if self._boton_aplicar is not None and self._boton_aplicar.winfo_exists():
                self._boton_aplicar.configure(
                    text=self._texto_boton_aplicar(), state="normal"
                )
            return

        self._resultado = resultado
        self._paso = 3
        self._pintar_paso()
        self._al_aplicado(resultado)

    # --- paso 3: resultado ---------------------------------------------------

    def _pintar_resultado(self) -> None:
        resultado = self._resultado
        marco = ctk.CTkFrame(self._cuerpo_paso, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)

        tarjeta = Tarjeta(marco, titulo="Ajuste aplicado")
        tarjeta.grid(row=0, column=0, sticky="new")

        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=texto_resultado_aplicacion(resultado),
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=(
                "Total de las cuotas ajustadas: "
                f"{formatear_monto(resultado.total_antes_centavos)}"
                f" → {formatear_monto(resultado.total_despues_centavos)}"
            ),
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=(
                "El ajuste impacta en las cuotas que se generen después de "
                "confirmar: las cuotas ya emitidas no se recalculan."
            ),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))

        botones = ctk.CTkFrame(marco, fg_color="transparent")
        botones.grid(row=1, column=0, sticky="ew", pady=(estilo.GAP, 0))
        botones.grid_columnconfigure(0, weight=1)

        estilo.boton_primario(
            botones, "Ver historial", command=lambda: self._al_salir("Historial")
        ).grid(row=0, column=0, sticky="w")
        estilo.boton_secundario(
            botones, "Cerrar", command=self._cerrar
        ).grid(row=0, column=1, sticky="e")


def _configurar_columnas_revision(marco: ctk.CTkFrame) -> None:
    """Pesos (x10) + piso para las columnas numéricas, como `Tabla`."""
    for indice, peso in enumerate((26, 16, 18, 18, 12)):
        marco.grid_columnconfigure(indice, weight=peso)
        if indice:
            marco.grid_columnconfigure(indice, minsize=110)
