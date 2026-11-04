"""Pantalla Cobranzas (spec §3.4 — H1 y H2: Mes, Atrasos, mora viva y PanelPago).

- **Mes:** navegador de período `◀ mes año ▶`, preview y generación idempotente
  con progreso, resumen del período, filtros combinables con debounce de 300 ms,
  tabla de cuotas con mora viva y apertura del panel de pago lateral.
- **Atrasos:** tabla plana de cuotas vencidas impagas de cualquier período
  ordenadas por días de atraso descendente, con acción `[ Cobrar ]`.
- **Panel de pago (`PanelPago`):** columna derecha de 380 px (nunca modal),
  defaults inteligentes, validación en vivo del monto (`< total` avisa en
  `ALERTA`, `> total` bloquea en `PELIGRO`), `Enter` confirma y `Esc` cierra.
"""

from pathlib import Path
from tkinter import filedialog
from typing import Literal

import customtkinter as ctk

from brickly.aplicacion.cobranzas import (
    CobranzasDelMes,
    DatosPago,
    DetalleCuotaParaPago,
    FiltroCobranzas,
    PreviewGeneracionCuotas,
    ResultadoGeneracionCuotas,
    ResultadoPago,
    ResumenCobranzasMes,
)
from brickly.aplicacion.contenedor import Servicios
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.dominio.pago import MedioPago
from brickly.ui import estilo
from brickly.ui.componentes.formulario import Campo
from brickly.ui.componentes.tabla import Columna, Tabla
from brickly.ui.componentes.tarjeta import Tarjeta
from brickly.ui.formato import (
    MESES,
    formatear_dias,
    formatear_fecha,
    formatear_monto,
    formatear_periodo,
    parsear_fecha,
    parsear_monto,
)
from brickly.ui.presenters.cobranzas import FilaAtrasoPresentada, PresenterCobranzas
from brickly.ui.presenters.constancia import (
    ConstanciaPresentada,
    preparar_constancia,
)
from brickly.ui.vistas.base import VistaBase

AYUDA_CONSTANCIA_MES = "Click en una cuota pagada para generar su constancia."

_MODOS = ("Mes", "Atrasos")

_FILTROS: dict[str, FiltroCobranzas] = {
    "Todas": "todas",
    "Pendientes": "pendientes",
    "Vencidas": "vencidas",
    "Pagadas": "pagadas",
}

_ETIQUETA_A_MEDIO: dict[str, MedioPago] = {
    "Transferencia": "transferencia",
    "Efectivo": "efectivo",
    "Depósito": "deposito",
    "Otro": "otro",
}

_MEDIO_A_ETIQUETA: dict[str, str] = {
    valor: etiqueta for etiqueta, valor in _ETIQUETA_A_MEDIO.items()
}


def texto_preview_generacion(preview: PreviewGeneracionCuotas) -> str:
    """Detalle del card de mes sin generar (§3.4)."""
    afuera = (
        "1 unidad sin contrato quedará afuera"
        if preview.unidades_sin_contrato == 1
        else f"{preview.unidades_sin_contrato} unidades sin contrato quedarán afuera"
    )
    if preview.cuotas_a_generar == 0:
        return f"No hay contratos vigentes para generar cuotas · {afuera}"
    cuotas = (
        "1 cuota"
        if preview.cuotas_a_generar == 1
        else f"{preview.cuotas_a_generar} cuotas"
    )
    return (
        f"Se generarán {cuotas} por {formatear_monto(preview.total_centavos)} · {afuera}"
    )


def texto_resultado_generacion(resultado: ResultadoGeneracionCuotas) -> str:
    """Texto del banner al terminar de generar (§4 F2)."""
    if resultado.cuotas_generadas == 0:
        periodo = formatear_periodo(resultado.anio, resultado.mes)
        return f"Las cuotas de {periodo} ya estaban generadas (0 nuevas)."
    cuotas = (
        "1 cuota generada"
        if resultado.cuotas_generadas == 1
        else f"{resultado.cuotas_generadas} cuotas generadas"
    )
    afuera = (
        "1 unidad sin contrato quedó afuera"
        if resultado.unidades_sin_contrato == 1
        else f"{resultado.unidades_sin_contrato} unidades sin contrato quedaron afuera"
    )
    return f"{cuotas} · {formatear_monto(resultado.total_centavos)} · {afuera}"


def texto_resumen_mes(resumen: ResumenCobranzasMes) -> str:
    """Línea de resumen encima de la tabla (§3.4)."""
    vencidas = (
        f"Vencidas {resumen.cantidad_vencidas} ({formatear_monto(resumen.monto_vencidas_centavos)})"
        if resumen.cantidad_vencidas > 0
        else "Vencidas 0"
    )
    return (
        f"Cobrado {formatear_monto(resumen.cobrado_centavos)} de "
        f"{formatear_monto(resumen.esperado_centavos)} · "
        f"{vencidas} · Pendientes {resumen.cantidad_pendientes}"
    )


def texto_mes_al_dia(mes: int, total_cuotas: int) -> str:
    """Mensaje cuando todas las cuotas del mes están cobradas (§3.4)."""
    nombre_mes = MESES[mes - 1].capitalize()
    return f"{nombre_mes} al día: {total_cuotas} de {total_cuotas} cobradas."


def texto_vencimiento_pago(detalle: DetalleCuotaParaPago) -> str:
    """Línea de vencimiento en el encabezado del panel de pago (§3.4)."""
    vence = formatear_fecha(detalle.fecha_vencimiento)
    if detalle.dias_atraso > 0:
        return f"Vence {vence} (vencida: {formatear_dias(detalle.dias_atraso)})"
    return f"Vence {vence}"


def evaluar_monto_pago(
    texto_monto: str, total_centavos: int
) -> tuple[Literal["ok", "alerta", "error"], str, bool]:
    """Evalúa el monto tipeado en `PanelPago` contra el total de la cuota (§3.4).

    Devuelve `(nivel, mensaje, boton_habilitado)`.
    """
    try:
        monto = parsear_monto(texto_monto)
    except ValueError:
        return ("error", "El monto del pago debe ser mayor a cero.", False)
    if monto <= 0:
        return ("error", "El monto del pago debe ser mayor a cero.", False)
    if monto > total_centavos:
        return (
            "error",
            f"El monto supera el total ({formatear_monto(total_centavos)})",
            False,
        )
    if monto < total_centavos:
        saldo = total_centavos - monto
        return ("alerta", f"Quedará un saldo de {formatear_monto(saldo)}", True)
    return ("ok", "", True)


def texto_exito_pago(resultado: ResultadoPago) -> str:
    """Banner de éxito al confirmar un pago (§3.4)."""
    return f"Pago registrado: {formatear_monto(resultado.monto_centavos)} · {resultado.unidad}"


def texto_error_pago(detalle: object) -> str:
    """Banner de error cuando falla `registrar_pago` (§3.4 y §6.3)."""
    return f"No se pudo registrar: {detalle}. No se modificó nada."


def avanzar_periodo(anio: int, mes: int, delta: int) -> tuple[int, int]:
    """Navega `delta` meses hacia atrás o adelante manteniendo `(anio, mes)`."""
    total = (anio * 12 + (mes - 1)) + delta
    nuevo_anio, nuevo_mes_0 = divmod(total, 12)
    return nuevo_anio, nuevo_mes_0 + 1


def _color_deuda(valor) -> tuple | None:
    return estilo.PELIGRO if valor and valor > 0 else None


class VistaCobranzas(VistaBase):
    def __init__(
        self,
        master,
        servicios: Servicios,
        modo_inicial: str = "Mes",
        cuota_inicial_id: int | None = None,
        abrir_primer_pago: bool = False,
    ):
        super().__init__(master, titulo="Cobranzas")
        self._servicios = servicios
        self._presentador = PresenterCobranzas(servicios)
        self._anio, self._mes = self._presentador.periodo_inicial()
        self._modo = modo_inicial if modo_inicial in _MODOS else "Mes"
        self._busqueda_actual = ""
        self._filtro_actual = "Todas"
        self._rebote: str | None = None
        self._datos: CobranzasDelMes | None = None
        self._filas_atrasos: list[FilaAtrasoPresentada] = []
        self._panel: PanelPago | None = None

        self.cuerpo.grid_columnconfigure(0, weight=1)
        self.cuerpo.grid_columnconfigure(1, weight=0)
        self.cuerpo.grid_rowconfigure(0, weight=1)

        columna = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        columna.grid(row=0, column=0, sticky="nsew")
        columna.grid_columnconfigure(0, weight=1)
        columna.grid_rowconfigure(1, weight=1)

        # Fila 0: navegador de período ◀ mes año ▶ (izq) + selector Mes | Atrasos (der)
        subcabecera = ctk.CTkFrame(columna, fg_color="transparent")
        subcabecera.grid(row=0, column=0, sticky="ew", pady=(0, estilo.GAP))
        subcabecera.grid_columnconfigure(0, weight=1)

        self._navegador_mes = ctk.CTkFrame(subcabecera, fg_color="transparent")
        self._navegador_mes.grid(row=0, column=0, sticky="w")

        estilo.boton_secundario(
            self._navegador_mes,
            "◀",
            command=lambda: self._cambiar_mes(-1),
            width=36,
        ).pack(side="left")

        self._etiqueta_periodo = ctk.CTkLabel(
            self._navegador_mes,
            text="",
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            width=150,
            anchor="center",
        )
        self._etiqueta_periodo.pack(side="left", padx=8)

        estilo.boton_secundario(
            self._navegador_mes,
            "▶",
            command=lambda: self._cambiar_mes(1),
            width=36,
        ).pack(side="left")

        self._selector_modo = ctk.CTkSegmentedButton(
            subcabecera,
            values=list(_MODOS),
            command=self._cambiar_modo,
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
        self._selector_modo.grid(row=0, column=1, sticky="e")
        self._selector_modo.set(self._modo)

        # Fila 1: contenedor dinámico según modo y estado de generación
        self._area = ctk.CTkFrame(columna, fg_color="transparent")
        self._area.grid(row=1, column=0, sticky="nsew")
        self._area.grid_columnconfigure(0, weight=1)
        self._area.grid_rowconfigure(0, weight=1)

        self._cargar()
        if cuota_inicial_id is not None:
            self._abrir_panel_pago(cuota_inicial_id)
        elif abrir_primer_pago:
            # CTA del Panel: entra directo al primer pago pendiente (flujo F3).
            self._registrar_primer_pago()

    # --- navegación y carga --------------------------------------------------

    def _cambiar_mes(self, delta: int) -> None:
        self._anio, self._mes = avanzar_periodo(self._anio, self._mes, delta)
        self._cerrar_panel()
        self.limpiar_banner()
        self._cargar()

    def _cambiar_modo(self, modo: str) -> None:
        self._modo = modo
        self._cerrar_panel()
        self._cargar()

    def _cargar(self) -> None:
        if self._rebote is not None:
            self.after_cancel(self._rebote)
            self._rebote = None

        if self._modo == "Atrasos":
            self._navegador_mes.grid_remove()
            self.poner_titulo("Cobranzas")
            self._filas_atrasos = self._presentador.atrasos()
            self._actualizar_acciones_cabecera(datos=None)
            self._pintar_atrasos()
            return

        self._navegador_mes.grid(row=0, column=0, sticky="w")
        periodo = formatear_periodo(self._anio, self._mes)
        self.poner_titulo(f"Cobranzas — {periodo}")
        self._etiqueta_periodo.configure(text=periodo)

        try:
            self._datos = self._presentador.del_mes(
                self._anio,
                self._mes,
                busqueda=self._busqueda_actual,
                filtro=_FILTROS[self._filtro_actual],
            )
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return

        self._actualizar_acciones_cabecera(self._datos)
        if not self._datos.generado:
            self._pintar_sin_generar(self._datos)
        else:
            self._pintar_mes_generado(self._datos)

    def _actualizar_acciones_cabecera(self, datos: CobranzasDelMes | None) -> None:
        for hijo in self._acciones.winfo_children():
            hijo.destroy()

        if datos is not None and not datos.generado:
            nombre_mes = MESES[self._mes - 1]
            boton = estilo.boton_primario(
                self._acciones,
                f"Generar cuotas de {nombre_mes}",
                command=self._generar_cuotas,
            )
            if datos.preview.cuotas_a_generar == 0:
                boton.configure(state="disabled")
            self.agregar_accion(boton)
            return

        if datos is not None and datos.preview.cuotas_a_generar > 0:
            nombre_mes = MESES[self._mes - 1]
            self.agregar_accion(
                estilo.boton_secundario(
                    self._acciones,
                    f"Generar cuotas de {nombre_mes} ({datos.preview.cuotas_a_generar})",
                    command=self._generar_cuotas,
                )
            )

        hay_impagas = self._hay_cuotas_impagas(datos)
        registrar = estilo.boton_primario(
            self._acciones,
            "Registrar pago",
            command=self._registrar_primer_pago if hay_impagas else None,
        )
        if not hay_impagas:
            registrar.configure(state="disabled")
        self.agregar_accion(registrar)

    def _hay_cuotas_impagas(self, datos: CobranzasDelMes | None) -> bool:
        if self._modo == "Atrasos":
            return len(self._filas_atrasos) > 0
        if datos is None or not datos.generado:
            return False
        return datos.resumen.cantidad_pagadas < datos.resumen.total_cuotas

    # --- estados de pantalla -------------------------------------------------

    def _limpiar_area(self) -> None:
        for hijo in self._area.winfo_children():
            hijo.destroy()

    def _pintar_sin_generar(self, datos: CobranzasDelMes) -> None:
        self._limpiar_area()
        periodo = formatear_periodo(self._anio, self._mes)
        tarjeta = Tarjeta(
            self._area,
            titulo=f"Las cuotas de {periodo} todavía no están generadas.",
        )
        tarjeta.grid(row=0, column=0, sticky="new")

        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=texto_preview_generacion(datos.preview),
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self._barra_progreso = ctk.CTkProgressBar(
            tarjeta.cuerpo,
            height=6,
            corner_radius=3,
            fg_color=estilo.FONDO_APP,
            progress_color=estilo.ACENTO,
        )
        self._barra_progreso.set(0)

        self._boton_generar_card = estilo.boton_primario(
            tarjeta.cuerpo,
            "Generar cuotas",
            command=self._generar_cuotas,
        )
        if datos.preview.cuotas_a_generar == 0:
            self._boton_generar_card.configure(state="disabled")
        self._boton_generar_card.grid(row=2, column=0, sticky="w", pady=(16, 0))

    def _generar_cuotas(self) -> None:
        if hasattr(self, "_boton_generar_card") and self._boton_generar_card.winfo_exists():
            self._boton_generar_card.configure(text="Generando…", state="disabled")
            self._barra_progreso.grid(row=1, column=0, sticky="ew", pady=(12, 0))
            self._barra_progreso.set(0.5)
            self.update_idletasks()

        try:
            resultado = self._servicios.cobranzas.generar_cuotas(self._anio, self._mes)
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            self._cargar()
            return

        if hasattr(self, "_barra_progreso") and self._barra_progreso.winfo_exists():
            self._barra_progreso.set(1.0)
            self.update_idletasks()

        self._cargar()
        self.mostrar_banner("exito", texto_resultado_generacion(resultado))

    def _pintar_mes_generado(self, datos: CobranzasDelMes) -> None:
        self._limpiar_area()
        marco = ctk.CTkFrame(self._area, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)

        fila_grid = 0
        ctk.CTkLabel(
            marco,
            text=texto_resumen_mes(datos.resumen),
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=fila_grid, column=0, sticky="w", pady=(0, 8))
        fila_grid += 1

        if (
            datos.resumen.total_cuotas > 0
            and datos.resumen.cantidad_pagadas == datos.resumen.total_cuotas
        ):
            ctk.CTkLabel(
                marco,
                text=texto_mes_al_dia(self._mes, datos.resumen.total_cuotas),
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.EXITO,
                anchor="w",
            ).grid(row=fila_grid, column=0, sticky="w", pady=(0, 8))
            fila_grid += 1

        filtros = ctk.CTkFrame(marco, fg_color="transparent")
        filtros.grid(row=fila_grid, column=0, sticky="ew", pady=(4, estilo.GAP))
        filtros.grid_columnconfigure(0, weight=1)
        fila_grid += 1

        self._busqueda = ctk.CTkEntry(
            filtros,
            width=320,
            height=estilo.ALTO_BOTON,
            placeholder_text="Buscar unidad o inquilino…",
            border_color=estilo.BORDE,
            fg_color=estilo.SUPERFICIE,
            text_color=estilo.TEXTO,
            font=estilo.FUENTE_CUERPO,
        )
        self._busqueda.grid(row=0, column=0, sticky="w")
        if self._busqueda_actual:
            self._busqueda.insert(0, self._busqueda_actual)
        self._busqueda.bind("<KeyRelease>", self._al_escribir)

        self._selector_filtro = ctk.CTkSegmentedButton(
            filtros,
            values=list(_FILTROS),
            command=self._al_cambiar_filtro,
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
        self._selector_filtro.grid(row=0, column=1, sticky="e")
        self._selector_filtro.set(self._filtro_actual)

        marco.grid_rowconfigure(fila_grid, weight=1)
        self._tabla = Tabla(
            marco,
            columnas=[
                Columna("Unidad", "unidad", 3),
                Columna("Inquilino", "inquilino", 2),
                Columna(
                    "Vence",
                    "fecha_vencimiento",
                    1.2,
                    alineacion="e",
                    formato=formatear_fecha,
                ),
                Columna(
                    "Cuota",
                    "monto_centavos",
                    1.5,
                    alineacion="e",
                    formato=formatear_monto,
                ),
                Columna(
                    "Mora",
                    "mora_centavos",
                    1.2,
                    alineacion="e",
                    formato=formatear_monto,
                    color=_color_deuda,
                ),
                Columna(
                    "Saldo",
                    "saldo_centavos",
                    1.5,
                    alineacion="e",
                    formato=formatear_monto,
                    color=_color_deuda,
                ),
                Columna("Estado", "estado", 1.5, es_chip=True),
            ],
            al_click_fila=self._al_click_fila_mes,
        )
        self._tabla.grid(row=fila_grid, column=0, sticky="nsew")
        self._tabla.cambiar_vacio(*self._vacio_tabla(datos))
        self._tabla.mostrar(datos.filas)
        fila_grid += 1

        ctk.CTkLabel(
            marco,
            text=(
                f"Mora calculada al {formatear_fecha(datos.fecha_calculo)}"
                f" — se recalcula todos los días. · {AYUDA_CONSTANCIA_MES}"
            ),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
        ).grid(row=fila_grid, column=0, sticky="w", pady=(8, 0))

    def _pintar_atrasos(self) -> None:
        self._limpiar_area()
        marco = ctk.CTkFrame(self._area, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(0, weight=1)

        self._tabla_atrasos = Tabla(
            marco,
            columnas=[
                Columna("Unidad", "unidad", 2.5),
                Columna("Inquilino", "inquilino", 2.0),
                Columna("Período", "periodo", 1.3),
                Columna(
                    "Vence",
                    "fecha_vencimiento",
                    1.2,
                    alineacion="e",
                    formato=formatear_fecha,
                ),
                Columna(
                    "Días",
                    "dias_atraso",
                    1.0,
                    alineacion="e",
                    formato=formatear_dias,
                    color=_color_deuda,
                ),
                Columna(
                    "Cuota",
                    "cuota_centavos",
                    1.4,
                    alineacion="e",
                    formato=formatear_monto,
                ),
                Columna(
                    "Mora hoy",
                    "mora_centavos",
                    1.3,
                    alineacion="e",
                    formato=formatear_monto,
                    color=_color_deuda,
                ),
                Columna(
                    "Total",
                    "total_centavos",
                    1.4,
                    alineacion="e",
                    formato=formatear_monto,
                    color=_color_deuda,
                ),
                Columna(
                    "",
                    "id",
                    1.1,
                    alineacion="e",
                    texto_accion="Cobrar",
                    al_accion=self._abrir_panel_pago,
                ),
            ],
            al_click_fila=self._abrir_panel_pago,
            mensaje_vacio="No hay cuotas vencidas.",
        )
        self._tabla_atrasos.grid(row=0, column=0, sticky="nsew")
        self._tabla_atrasos.mostrar(self._filas_atrasos)

        hoy = self._servicios.cobranzas.hoy()
        ctk.CTkLabel(
            marco,
            text=(
                f"Mora calculada al {formatear_fecha(hoy)}"
                " — se recalcula todos los días."
            ),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

    # --- panel de pago y constancia ------------------------------------------

    def _al_click_fila_mes(self, cuota_id: int) -> None:
        if self._datos is not None:
            for fila in self._datos.filas:
                if fila.cuota_id == cuota_id and fila.estado == "pagada":
                    self._abrir_panel_constancia(cuota_id)
                    return
        self._abrir_panel_pago(cuota_id)

    def _registrar_primer_pago(self) -> None:
        if self._modo == "Atrasos":
            if self._filas_atrasos:
                self._abrir_panel_pago(self._filas_atrasos[0].cuota_id)
            return

        if self._datos is None:
            return
        for fila in self._datos.filas:
            if fila.estado != "pagada":
                self._abrir_panel_pago(fila.cuota_id)
                return
        todas = self._presentador.del_mes(self._anio, self._mes).filas
        for fila in todas:
            if fila.estado != "pagada":
                self._abrir_panel_pago(fila.cuota_id)
                return

    def _abrir_panel_pago(self, cuota_id: int) -> None:
        try:
            detalle = self._presentador.preparar_pago(cuota_id)
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return

        self._cerrar_panel()
        self._panel = PanelPago(
            self.cuerpo,
            self._servicios,
            detalle=detalle,
            al_confirmado=self._pago_confirmado,
            al_error=self._pago_error,
            al_cerrar=self._cerrar_panel,
        )
        self._panel.grid(row=0, column=1, sticky="ns", padx=(estilo.GAP, 0))

    def _abrir_panel_constancia(self, cuota_id: int) -> None:
        try:
            constancia = preparar_constancia(self._servicios, cuota_id)
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return

        self._cerrar_panel()
        self._panel = PanelConstancia(
            self.cuerpo,
            self._servicios,
            constancia=constancia,
            al_generado=self._constancia_generada,
            al_error=self._pago_error,
            al_cerrar=self._cerrar_panel,
        )
        self._panel.grid(row=0, column=1, sticky="ns", padx=(estilo.GAP, 0))

    def _cerrar_panel(self) -> None:
        if self._panel is not None:
            self._panel.destroy()
            self._panel = None

    def _pago_confirmado(self, resultado: ResultadoPago) -> None:
        self._cerrar_panel()
        self._cargar()
        self.mostrar_banner("exito", texto_exito_pago(resultado))

    def _constancia_generada(self, ruta: str) -> None:
        self.mostrar_banner("exito", f"Constancia guardada en {ruta}")

    def _pago_error(self, mensaje: str) -> None:
        self.mostrar_banner("error", mensaje)

    # --- filtros y búsqueda --------------------------------------------------

    def _al_escribir(self, _evento=None) -> None:
        if self._rebote is not None:
            self.after_cancel(self._rebote)
        self._rebote = self.after(300, self._recargar_tabla)

    def _al_cambiar_filtro(self, valor: str) -> None:
        self._filtro_actual = valor
        self._recargar_tabla()

    def _recargar_tabla(self) -> None:
        self._rebote = None
        if hasattr(self, "_busqueda") and self._busqueda.winfo_exists():
            self._busqueda_actual = self._busqueda.get().strip()
        self._datos = self._presentador.del_mes(
            self._anio,
            self._mes,
            busqueda=self._busqueda_actual,
            filtro=_FILTROS[self._filtro_actual],
        )
        if hasattr(self, "_tabla") and self._tabla.winfo_exists():
            self._tabla.cambiar_vacio(*self._vacio_tabla(self._datos))
            self._tabla.mostrar(self._datos.filas)

    def _limpiar_filtros(self) -> None:
        self._busqueda_actual = ""
        self._filtro_actual = "Todas"
        if hasattr(self, "_busqueda") and self._busqueda.winfo_exists():
            self._busqueda.delete(0, "end")
        if hasattr(self, "_selector_filtro") and self._selector_filtro.winfo_exists():
            self._selector_filtro.set("Todas")
        self._recargar_tabla()

    def _vacio_tabla(
        self, datos: CobranzasDelMes
    ) -> tuple[str, tuple[str, object] | None]:
        if datos.filas:
            return "", None
        if self._busqueda_actual:
            return (
                f"Nada coincide con «{self._busqueda_actual}».",
                ("Limpiar filtro", self._limpiar_filtros),
            )
        if self._filtro_actual == "Vencidas":
            return "No hay cuotas vencidas.", None
        if (
            self._filtro_actual == "Pendientes"
            and datos.resumen.total_cuotas > 0
            and datos.resumen.cantidad_pagadas == datos.resumen.total_cuotas
        ):
            return texto_mes_al_dia(self._mes, datos.resumen.total_cuotas), None
        if self._filtro_actual != "Todas":
            return (
                f"Nada coincide con «{self._filtro_actual}».",
                ("Limpiar filtro", self._limpiar_filtros),
            )
        return "No hay cuotas para mostrar.", None


class PanelPago(ctk.CTkFrame):
    """Panel lateral de pago de 380 px (spec §3.4 — nunca modal)."""

    ANCHO = 380

    def __init__(
        self,
        master,
        servicios: Servicios,
        detalle: DetalleCuotaParaPago,
        al_confirmado,
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
        self._detalle = detalle
        self._al_confirmado = al_confirmado
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

        fila = 0
        ctk.CTkLabel(
            interior,
            text="Registrar pago",
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w")
        fila += 1

        ctk.CTkLabel(
            interior,
            text=detalle.unidad,
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", pady=(8, 0))
        fila += 1

        periodo = formatear_periodo(detalle.anio, detalle.mes)
        ctk.CTkLabel(
            interior,
            text=f"{detalle.inquilino} · {periodo}",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", pady=(2, 0))
        fila += 1

        color_vence = estilo.PELIGRO if detalle.dias_atraso > 0 else estilo.TEXTO_2
        ctk.CTkLabel(
            interior,
            text=texto_vencimiento_pago(detalle),
            font=estilo.FUENTE_CHICO,
            text_color=color_vence,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", pady=(2, 0))
        fila += 1

        # Desglose de importes: Cuota, Mora (solo si > 0) y Total
        desglose = ctk.CTkFrame(
            interior,
            fg_color=estilo.SUPERFICIE_2,
            corner_radius=estilo.RADIO_BOTON,
        )
        desglose.grid(row=fila, column=0, sticky="ew", pady=(12, 4))
        desglose.grid_columnconfigure(0, weight=1)
        desglose.grid_columnconfigure(1, weight=0)
        fila += 1

        fila_d = 0
        self._fila_desglose(
            desglose,
            fila_d,
            "Cuota",
            formatear_monto(detalle.saldo_capital_centavos),
        )
        fila_d += 1

        if detalle.mora_centavos > 0:
            self._fila_desglose(
                desglose,
                fila_d,
                f"Mora ({formatear_dias(detalle.dias_atraso)})",
                formatear_monto(detalle.mora_centavos),
                color=estilo.PELIGRO,
            )
            fila_d += 1

        self._fila_desglose(
            desglose,
            fila_d,
            "Total",
            formatear_monto(detalle.total_centavos),
            negrita=True,
        )

        # Campos del formulario con defaults inteligentes (§3.4)
        self._campo_fecha = Campo(
            interior, "Fecha de pago", placeholder="15/10/2026"
        )
        self._campo_fecha.poner_valor(formatear_fecha(detalle.fecha_sugerida))
        self._campo_fecha.grid(row=fila, column=0, sticky="ew", pady=(10, 0))
        fila += 1

        self._campo_monto = Campo(interior, "Monto", placeholder="14.336")
        self._campo_monto.poner_valor(formatear_monto(detalle.total_centavos))
        self._campo_monto.al_cambiar(self._validar_monto_en_vivo)
        self._campo_monto.grid(row=fila, column=0, sticky="ew", pady=(10, 0))
        fila += 1

        self._campo_medio = Campo(
            interior,
            "Medio",
            tipo="opciones",
            valores=list(_ETIQUETA_A_MEDIO.keys()),
        )
        self._campo_medio.poner_valor(
            _MEDIO_A_ETIQUETA.get(detalle.medio_sugerido, "Transferencia")
        )
        self._campo_medio.grid(row=fila, column=0, sticky="ew", pady=(10, 0))
        fila += 1

        self._campo_nota = Campo(
            interior, "Nota (opcional)", placeholder="Comprobante o referencia"
        )
        self._campo_nota.grid(row=fila, column=0, sticky="ew", pady=(10, 0))
        fila += 1

        for campo in (self._campo_fecha, self._campo_monto, self._campo_nota):
            campo.atajo("<Return>", self._confirmar)
            campo.atajo("<Escape>", self._cerrar)

        botones = ctk.CTkFrame(interior, fg_color="transparent")
        botones.grid(row=fila, column=0, sticky="ew", pady=(16, 0))
        botones.grid_columnconfigure(0, weight=1)

        self._boton_confirmar = estilo.boton_primario(
            botones, "Confirmar pago", command=self._confirmar
        )
        self._boton_confirmar.grid(row=0, column=0, sticky="ew")

        estilo.boton_secundario(
            botones, "Cancelar", command=self._cerrar
        ).grid(row=0, column=1, padx=(8, 0))

        self._campo_monto.enfocar()

    def _fila_desglose(
        self,
        marco: ctk.CTkFrame,
        fila: int,
        etiqueta: str,
        valor: str,
        color=None,
        negrita: bool = False,
    ) -> None:
        fuente = estilo.FUENTE_CUERPO_NEGRITA if negrita else estilo.FUENTE_CHICO
        ctk.CTkLabel(
            marco,
            text=etiqueta,
            font=fuente,
            text_color=estilo.TEXTO if negrita else estilo.TEXTO_2,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", padx=12, pady=4)
        ctk.CTkLabel(
            marco,
            text=valor,
            font=fuente,
            text_color=color or estilo.TEXTO,
            anchor="e",
        ).grid(row=fila, column=1, sticky="e", padx=12, pady=4)

    def _validar_monto_en_vivo(self) -> bool:
        nivel, mensaje, habilitado = evaluar_monto_pago(
            self._campo_monto.valor(), self._detalle.total_centavos
        )
        if nivel == "error":
            self._campo_monto.mostrar_error(mensaje)
        elif nivel == "alerta":
            self._campo_monto.mostrar_aviso(mensaje)
        else:
            self._campo_monto.limpiar_error()

        self._boton_confirmar.configure(
            state="normal" if habilitado else "disabled"
        )
        return habilitado

    def _confirmar(self) -> None:
        self._campo_fecha.limpiar_error()
        if not self._validar_monto_en_vivo():
            return

        try:
            fecha = parsear_fecha(self._campo_fecha.valor())
        except ValueError:
            self._campo_fecha.mostrar_error("Usá el formato dd/mm/aaaa.")
            self._campo_fecha.enfocar()
            return

        monto = parsear_monto(self._campo_monto.valor())
        medio = _ETIQUETA_A_MEDIO.get(
            self._campo_medio.valor(), "transferencia"
        )
        nota = self._campo_nota.valor().strip() or None

        datos = DatosPago(
            cuota_id=self._detalle.cuota_id,
            fecha=fecha,
            monto_centavos=monto,
            medio=medio,
            nota=nota,
        )
        try:
            resultado = self._servicios.cobranzas.registrar_pago(datos)
        except (ErrorDeValidacion, ErrorDeNegocio) as error:
            self._al_error(texto_error_pago(error))
            return

        self._al_confirmado(resultado)

    def _cerrar(self) -> None:
        self._al_cerrar()


def _escritorio_default() -> str | None:
    escritorio = Path.home() / "Desktop"
    if escritorio.is_dir():
        return str(escritorio)
    return str(Path.home()) if Path.home().is_dir() else None


class PanelConstancia(ctk.CTkFrame):
    """Panel lateral de 380 px con vista previa de la constancia y `[ Generar PDF ]` (H8)."""

    ANCHO = 380

    def __init__(
        self,
        master,
        servicios: Servicios,
        constancia: ConstanciaPresentada,
        al_generado,
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
        self._constancia = constancia
        self._al_generado = al_generado
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
        interior.grid_rowconfigure(0, weight=1)

        cuerpo = ctk.CTkScrollableFrame(interior, fg_color="transparent")
        cuerpo.grid(row=0, column=0, sticky="nsew")
        cuerpo.grid_columnconfigure(0, weight=1)

        fila = 0
        ctk.CTkLabel(
            cuerpo,
            text=constancia.titulo,
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w")
        fila += 1

        ctk.CTkLabel(
            cuerpo,
            text=constancia.unidad,
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", pady=(8, 0))
        fila += 1

        ctk.CTkLabel(
            cuerpo,
            text=f"{constancia.inquilino} · {constancia.periodo}",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", pady=(2, 0))
        fila += 1

        ctk.CTkLabel(
            cuerpo,
            text=(
                f"Vence {constancia.fecha_vencimiento}"
                f" · Emisión {constancia.fecha_emision}"
            ),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", pady=(2, 0))
        fila += 1

        if constancia.emisor:
            ctk.CTkLabel(
                cuerpo,
                text=f"Emisor: {constancia.emisor}",
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_3,
                anchor="w",
                justify="left",
                wraplength=310,
            ).grid(row=fila, column=0, sticky="w", pady=(4, 0))
            fila += 1

        # Desglose de importes de la cuota
        desglose = ctk.CTkFrame(
            cuerpo,
            fg_color=estilo.SUPERFICIE_2,
            corner_radius=estilo.RADIO_BOTON,
        )
        desglose.grid(row=fila, column=0, sticky="ew", pady=(12, 8))
        desglose.grid_columnconfigure(0, weight=1)
        desglose.grid_columnconfigure(1, weight=0)
        fila += 1

        self._fila_desglose(desglose, 0, "Capital", constancia.capital)
        self._fila_desglose(desglose, 1, "Mora cobrada", constancia.mora)
        self._fila_desglose(
            desglose, 2, "Total abonado", constancia.total, negrita=True
        )

        # Lista de pagos imputados
        ctk.CTkLabel(
            cuerpo,
            text="Pagos imputados a este período",
            font=estilo.FUENTE_CHICO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", pady=(6, 4))
        fila += 1

        marco_pagos = ctk.CTkFrame(
            cuerpo,
            fg_color=estilo.SUPERFICIE_2,
            corner_radius=estilo.RADIO_BOTON,
        )
        marco_pagos.grid(row=fila, column=0, sticky="ew")
        marco_pagos.grid_columnconfigure(0, weight=1)
        marco_pagos.grid_columnconfigure(1, weight=0)
        fila += 1

        for idx, p in enumerate(constancia.pagos):
            etiqueta_pago = f"{p.fecha} · {p.medio}"
            if p.nota:
                etiqueta_pago = f"{etiqueta_pago} ({p.nota})"
            ctk.CTkLabel(
                marco_pagos,
                text=etiqueta_pago,
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_2,
                anchor="w",
                justify="left",
                wraplength=200,
            ).grid(row=idx, column=0, sticky="w", padx=12, pady=4)
            ctk.CTkLabel(
                marco_pagos,
                text=p.monto_imputado,
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.TEXTO,
                anchor="e",
            ).grid(row=idx, column=1, sticky="e", padx=12, pady=4)

        # Bloque de firma y alcance
        texto_firma = (
            f"Firma: {constancia.firma_nombre} ({constancia.firma_rol})"
            if constancia.firma_nombre
            else f"Firma: línea en blanco ({constancia.firma_rol})"
        )
        ctk.CTkLabel(
            cuerpo,
            text=texto_firma,
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
            justify="left",
            wraplength=310,
        ).grid(row=fila, column=0, sticky="w", pady=(10, 4))
        fila += 1

        ctk.CTkLabel(
            cuerpo,
            text=f"{constancia.leyenda_pie}\n{constancia.leyenda_no_fiscal}",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
            justify="left",
            wraplength=310,
        ).grid(row=fila, column=0, sticky="w", pady=(2, 4))

        # Botonera fija abajo
        botones = ctk.CTkFrame(interior, fg_color="transparent")
        botones.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        botones.grid_columnconfigure(0, weight=1)

        self._boton_generar = estilo.boton_primario(
            botones,
            "Generar PDF",
            command=self._generar_pdf,
        )
        self._boton_generar.grid(row=0, column=0, sticky="ew")

        estilo.boton_secundario(
            botones,
            "Cerrar",
            command=self._cerrar,
        ).grid(row=0, column=1, padx=(8, 0))

        self.bind("<Return>", lambda _e: self._generar_pdf())
        self.bind("<Escape>", lambda _e: self._cerrar())

    def _fila_desglose(
        self,
        marco: ctk.CTkFrame,
        fila: int,
        etiqueta: str,
        valor: str,
        negrita: bool = False,
    ) -> None:
        fuente = estilo.FUENTE_CUERPO_NEGRITA if negrita else estilo.FUENTE_CHICO
        ctk.CTkLabel(
            marco,
            text=etiqueta,
            font=fuente,
            text_color=estilo.TEXTO if negrita else estilo.TEXTO_2,
            anchor="w",
        ).grid(row=fila, column=0, sticky="w", padx=12, pady=4)
        ctk.CTkLabel(
            marco,
            text=valor,
            font=fuente,
            text_color=estilo.TEXTO,
            anchor="e",
        ).grid(row=fila, column=1, sticky="e", padx=12, pady=4)

    def _generar_pdf(self, ruta_destino: str | None = None) -> None:
        if self._servicios.constancias is None:
            self._al_error("El servicio de constancias no está configurado.")
            return

        ruta = ruta_destino
        if not ruta:
            ruta = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
                initialdir=_escritorio_default(),
                initialfile=self._constancia.nombre_archivo_sugerido,
            )
            if not ruta:
                return

        self._boton_generar.configure(text="Generando…", state="disabled")
        self.update_idletasks()
        try:
            self._servicios.constancias.generar(
                self._constancia.cuota_id, ruta
            )
        except (ErrorDeNegocio, OSError) as error:
            if self._boton_generar.winfo_exists():
                self._boton_generar.configure(text="Generar PDF", state="normal")
            self._al_error(f"No se pudo generar la constancia: {error}")
            return

        if self._boton_generar.winfo_exists():
            self._boton_generar.configure(text="Generar PDF", state="normal")
        self._al_generado(ruta)

    def _cerrar(self) -> None:
        self._al_cerrar()

