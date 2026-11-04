"""Pantalla Panel (spec §3.1 — H4): KPIs del mes, vencidas, alertas y onboarding.

Responde "¿qué tengo que hacer hoy?": 4 KPIs del mes en curso (mismo servicio
que Cobranzas — la vista no suma nada), top 5 de vencidas con acceso directo al
pago (flujo F3), alertas calculadas (IPC faltante · respaldo viejo · contratos
vencidos) y el checklist de puesta en marcha (F1) mientras no haya pagos.

La navegación sale por `al_navegar(clave, opciones)`: la ventana es la única
que sabe montar pantallas; acá solo se pide destino + contexto (mes, cuota,
departamento).
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from brickly.aplicacion.contenedor import Servicios
from brickly.dominio.errores import ErrorDeNegocio
from brickly.ui import estilo
from brickly.ui.componentes.kpi import TarjetaKPI
from brickly.ui.componentes.tarjeta import Tarjeta
from brickly.ui.formato import (
    MESES,
    formatear_dias,
    formatear_monto,
    formatear_periodo,
    formatear_porcentaje,
)
from brickly.ui.presenters.panel import (
    DESTINO_AJUSTES,
    DESTINO_COBRANZAS,
    DESTINO_DEPARTAMENTOS,
    AlertaPresentada,
    FilaVencidaPresentada,
    PanelDatos,
    PresenterPanel,
)
from brickly.ui.vistas.base import VistaBase


def texto_banner_generar(anio: int, mes: int) -> str:
    """Banner cuando el mes en curso no está generado (§3.1)."""
    return f"Las cuotas de {formatear_periodo(anio, mes)} todavía no están generadas."


def texto_etiqueta_generar(mes: int) -> str:
    """CTA del banner de generación (§3.1): solo el mes, como en Cobranzas."""
    return f"Generar cuotas de {MESES[mes - 1]}"


def texto_vencidas(cantidad: int, total_centavos: int) -> str:
    """`4 · $ 38.400` (KPI vencidas); vacío → estado explícito."""
    if cantidad == 0:
        return "Sin vencidas"
    return f"{formatear_monto(total_centavos)} con mora a hoy"


def texto_ajustes(cantidad: int) -> str:
    """`2 contratos` / `1 contrato` (KPI ajustes)."""
    return "1 contrato" if cantidad == 1 else f"{cantidad} contratos"


class VistaPanel(VistaBase):
    def __init__(
        self,
        master,
        servicios: Servicios,
        al_navegar: Callable[[str, dict | None], None],
    ):
        super().__init__(master, titulo="Panel")
        self._servicios = servicios
        self._presentador = PresenterPanel(servicios)
        self._al_navegar = al_navegar
        self._datos: PanelDatos | None = None

        self._boton_pago = estilo.boton_primario(
            self._acciones, "Registrar pago", command=self._registrar_pago
        )
        self.agregar_accion(self._boton_pago)

        self._area = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        self._area.grid(row=0, column=0, sticky="nsew")
        self._area.grid_columnconfigure(0, weight=1)
        self._area.grid_rowconfigure(0, weight=1)

        self._cargar()

    # --- carga ----------------------------------------------------------------

    def _cargar(self) -> None:
        try:
            self._datos = self._presentador.cargar()
        except ErrorDeNegocio as error:
            self._pintar_error(str(error))
            return

        datos = self._datos
        self._boton_pago.configure(
            state="normal" if datos.hay_impagas else "disabled"
        )
        if not datos.generado:
            self.mostrar_banner(
                "alerta",
                texto_banner_generar(datos.anio, datos.mes),
                accion=(
                    texto_etiqueta_generar(datos.mes),
                    lambda: self._al_navegar(DESTINO_COBRANZAS, None),
                ),
            )
        if datos.onboarding:
            self._pintar_onboarding(datos)
        else:
            self._pintar_dashboard(datos)

    def _recargar(self) -> None:
        self.limpiar_banner()
        self._cargar()

    def _pintar_error(self, mensaje: str) -> None:
        self.mostrar_banner(
            "error",
            f"No se pudo cargar el panel: {mensaje}",
            accion=("Reintentar", self._recargar),
        )
        self._limpiar_area()
        ctk.CTkLabel(
            self._area,
            text="No se pudo cargar el panel.",
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
        ).grid(row=0, column=0)

    def _limpiar_area(self) -> None:
        for hijo in self._area.winfo_children():
            hijo.destroy()

    # --- render ---------------------------------------------------------------

    def _pintar_onboarding(self, datos: PanelDatos) -> None:
        """F1: checklist hasta el primer pago; sin KPIs (§3.1 estados)."""
        self._limpiar_area()
        tarjeta = Tarjeta(self._area, titulo="Puesta en marcha")
        tarjeta.grid(row=0, column=0, sticky="new")

        ctk.CTkLabel(
            tarjeta.cuerpo,
            text="Tres pasos para empezar a cobrar. Se tachan solos a medida que avanzás.",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        fuente_hecho = ctk.CTkFont(
            family=estilo.FAMILIA, size=12, overstrike=True
        )
        for indice, paso in enumerate(datos.pasos, start=1):
            texto = f"{'✓' if paso.hecho else '○'}  {paso.texto}"
            boton = ctk.CTkButton(
                tarjeta.cuerpo,
                text=texto,
                command=lambda destino=paso.destino: self._al_navegar(destino, None),
                anchor="w",
                height=estilo.ALTO_BOTON,
                fg_color="transparent",
                hover_color=estilo.SUPERFICIE_2,
                text_color=estilo.EXITO if paso.hecho else estilo.ACENTO,
                font=fuente_hecho if paso.hecho else estilo.FUENTE_CUERPO_NEGRITA,
            )
            boton.grid(row=indice, column=0, sticky="ew", pady=2)

    def _pintar_dashboard(self, datos: PanelDatos) -> None:
        self._limpiar_area()
        marco = ctk.CTkFrame(self._area, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(1, weight=1)

        self._pintar_kpis(marco, datos)
        self._pintar_inferior(marco, datos)

    def _pintar_kpis(self, marco, datos: PanelDatos) -> None:
        fila = ctk.CTkFrame(marco, fg_color="transparent")
        fila.grid(row=0, column=0, sticky="ew")
        for columna in range(4):
            fila.grid_columnconfigure(columna, weight=1, uniform="kpi")

        TarjetaKPI(
            fila,
            "Cobrado",
            formatear_monto(datos.cobrado_centavos),
            sublinea=(
                f"{formatear_periodo(datos.anio, datos.mes)} · "
                f"{formatear_porcentaje(datos.porcentaje_bp)} de "
                f"{formatear_monto(datos.esperado_centavos)}"
            ),
            progreso=min(max(datos.porcentaje_bp / 10_000, 0.0), 1.0),
        ).grid(row=0, column=0, sticky="nsew", padx=(0, estilo.GAP))

        TarjetaKPI(
            fila,
            "Vencidas sin pago",
            str(datos.vencidas_cantidad),
            sublinea=texto_vencidas(
                datos.vencidas_cantidad, datos.vencidas_total_centavos
            ),
            tono="peligro" if datos.vencidas_cantidad else "normal",
        ).grid(row=0, column=1, sticky="nsew", padx=(0, estilo.GAP))

        TarjetaKPI(
            fila,
            "Pendientes (a término)",
            str(datos.pendientes_cantidad),
            sublinea=(
                formatear_monto(datos.pendientes_total_centavos)
                if datos.pendientes_cantidad
                else "Sin pendientes a término"
            ),
        ).grid(row=0, column=2, sticky="nsew", padx=(0, estilo.GAP))

        tarjeta_ajustes = TarjetaKPI(
            fila,
            "Ajustes IPC este mes",
            texto_ajustes(datos.ajustes_cantidad),
            sublinea=(
                "→ Revisar y aplicar" if datos.ajustes_cantidad else "Sin ajustes este mes"
            ),
            al_click=(
                (lambda: self._al_navegar(DESTINO_AJUSTES, None))
                if datos.ajustes_cantidad
                else None
            ),
        )
        tarjeta_ajustes.grid(row=0, column=3, sticky="nsew")

    def _pintar_inferior(self, marco, datos: PanelDatos) -> None:
        inferior = ctk.CTkFrame(marco, fg_color="transparent")
        inferior.grid(row=1, column=0, sticky="nsew", pady=(estilo.GAP, 0))
        inferior.grid_columnconfigure(0, weight=1)
        inferior.grid_columnconfigure(1, weight=0, minsize=360)
        inferior.grid_rowconfigure(0, weight=1)

        self._pintar_vencidas(inferior, datos)
        self._pintar_alertas(inferior, datos)

    def _pintar_vencidas(self, marco, datos: PanelDatos) -> None:
        tarjeta = Tarjeta(marco)
        tarjeta.grid(row=0, column=0, sticky="nsew", padx=(0, estilo.GAP))

        cabecera = ctk.CTkFrame(tarjeta.cuerpo, fg_color="transparent")
        cabecera.grid(row=0, column=0, sticky="ew")
        cabecera.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            cabecera,
            text=f"Vencidas sin pago · {datos.vencidas_cantidad}",
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        estilo.boton_secundario(
            cabecera,
            "Ver todas",
            command=lambda: self._al_navegar(
                DESTINO_COBRANZAS, {"modo_inicial": "Atrasos"}
            ),
            height=estilo.ALTO_BOTON_FILA,
        ).grid(row=0, column=1, sticky="e")

        if not datos.filas_vencidas:
            ctk.CTkLabel(
                tarjeta.cuerpo,
                text="No hay vencidas sin pago.",
                font=estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO_2,
                anchor="w",
            ).grid(row=1, column=0, sticky="w", pady=(12, 0))
            return

        for indice, fila in enumerate(datos.filas_vencidas, start=1):
            self._fila_vencida(tarjeta.cuerpo, indice, fila)

    def _fila_vencida(self, marco, fila_grid: int, fila: FilaVencidaPresentada) -> None:
        contenedor = ctk.CTkFrame(marco, fg_color=estilo.SUPERFICIE, corner_radius=0)
        contenedor.grid(row=fila_grid, column=0, sticky="ew", pady=(1, 0))
        contenedor.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            contenedor,
            text=fila.unidad,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(4, 8), pady=4)

        ctk.CTkLabel(
            contenedor,
            text=formatear_dias(fila.dias_atraso),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.PELIGRO,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(0, 12), pady=4)

        ctk.CTkLabel(
            contenedor,
            text=formatear_monto(fila.total_centavos),
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.PELIGRO,
            anchor="e",
        ).grid(row=0, column=2, sticky="e", padx=(0, 4), pady=4)

        contenedor.configure(cursor="hand2")

        def entrar(_evento):
            contenedor.configure(fg_color=estilo.SUPERFICIE_2)

        def salir(_evento):
            contenedor.configure(fg_color=estilo.SUPERFICIE)

        def abrir_cuota(_evento=None, cuota_id=fila.cuota_id):
            self._al_navegar(
                DESTINO_COBRANZAS,
                {"modo_inicial": "Atrasos", "cuota_inicial_id": cuota_id},
            )

        for widget in (contenedor, *contenedor.winfo_children()):
            widget.bind("<Enter>", entrar)
            widget.bind("<Leave>", salir)
            widget.bind("<Button-1>", abrir_cuota)
            try:
                widget.configure(cursor="hand2")
            except Exception:
                pass

    def _pintar_alertas(self, marco, datos: PanelDatos) -> None:
        tarjeta = Tarjeta(marco, titulo="Alertas")
        tarjeta.grid(row=0, column=1, sticky="nsew")

        if not datos.alertas:
            ctk.CTkLabel(
                tarjeta.cuerpo,
                text="Sin alertas",
                font=estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO_2,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            return

        for indice, alerta in enumerate(datos.alertas):
            self._fila_alerta(tarjeta.cuerpo, indice, alerta)

    def _fila_alerta(self, marco, fila_grid: int, alerta: AlertaPresentada) -> None:
        boton = ctk.CTkButton(
            marco,
            text=f"▸ {alerta.texto} → {alerta.etiqueta_accion}",
            command=lambda: self._abrir_alerta(alerta),
            anchor="w",
            height=estilo.ALTO_BOTON,
            fg_color="transparent",
            hover_color=estilo.SUPERFICIE_2,
            text_color=estilo.ACENTO,
            font=estilo.FUENTE_CHICO,
        )
        boton.grid(row=fila_grid, column=0, sticky="ew", pady=2)

    def _abrir_alerta(self, alerta: AlertaPresentada) -> None:
        opciones = None
        if alerta.destino == DESTINO_DEPARTAMENTOS and alerta.departamento_id is not None:
            opciones = {"departamento_id": alerta.departamento_id}
        self._al_navegar(alerta.destino, opciones)

    # --- acciones -------------------------------------------------------------

    def _registrar_pago(self) -> None:
        if self._datos is None or not self._datos.hay_impagas:
            return
        if self._datos.filas_vencidas:
            self._al_navegar(
                DESTINO_COBRANZAS,
                {
                    "modo_inicial": "Atrasos",
                    "cuota_inicial_id": self._datos.filas_vencidas[0].cuota_id,
                },
            )
            return
        self._al_navegar(DESTINO_COBRANZAS, {"abrir_primer_pago": True})
