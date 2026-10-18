"""Detalle de departamento (spec §3.3): el estado de cuenta de una unidad.

Header con la unidad + chips (estado del mes y contrato), secciones
Resumen · Contrato · Cuotas y pagos, y paneles laterales de 380 px para editar
el departamento o cargar/editar/renovar el contrato.
"""

from tkinter import filedialog

import customtkinter as ctk

from gestion.aplicacion.contenedor import Servicios
from gestion.aplicacion.departamentos import (
    ContratoEnDetalle,
    DatosContrato,
    PagoImputadoCuota,
)
from gestion.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from gestion.ui import estilo
from gestion.ui.componentes.chip import ChipEstado
from gestion.ui.componentes.formulario import Campo
from gestion.ui.componentes.kpi import TarjetaKPI
from gestion.ui.componentes.tabla import Columna, Tabla
from gestion.ui.componentes.tarjeta import Tarjeta
from gestion.ui.formato import (
    formatear_dias,
    formatear_fecha,
    formatear_monto,
    formatear_porcentaje,
    parsear_fecha,
    parsear_monto,
    parsear_porcentaje,
)
from gestion.ui.presenters.departamento import PresenterDepartamentos
from gestion.ui.vistas.base import VistaBase
from gestion.ui.vistas.cobranzas import PanelPago, texto_exito_pago
from gestion.ui.vistas.departamentos import PanelDepartamento
from gestion.ui.vistas.informes import escritorio_default, nombre_estado_cuenta

_SECCIONES = ("Resumen", "Contrato", "Cuotas y pagos")

_MEDIOS_ETIQUETA = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "deposito": "Depósito",
    "otro": "Otro",
}


def _color_deuda(valor) -> tuple | None:
    return estilo.PELIGRO if valor and valor > 0 else None


class VistaDetalleDepartamento(VistaBase):
    def __init__(
        self,
        master,
        servicios: Servicios,
        departamento_id: int,
        al_volver,
        al_eliminado,
    ):
        super().__init__(
            master,
            titulo="Departamento",
            al_volver=al_volver,
            texto_volver="‹ Departamentos",
        )
        self._servicios = servicios
        self._presentador = PresenterDepartamentos(servicios)
        self._departamento_id = departamento_id
        self._al_eliminado = al_eliminado
        self._seccion = "Resumen"
        self._panel: ctk.CTkFrame | None = None
        self._detalle = None
        self._cuota_seleccionada_id: int | None = None
        self._marco_pagos_cuota: ctk.CTkFrame | None = None

        self._boton_registrar_pago = estilo.boton_primario(
            self._acciones, "Registrar pago", command=self._registrar_pago
        )
        self._boton_registrar_pago.configure(state="disabled")
        self.agregar_accion(self._boton_registrar_pago)
        self.agregar_accion(
            estilo.boton_secundario(self._acciones, "Editar", command=self._editar)
        )

        self.cuerpo.grid_columnconfigure(0, weight=1)
        self.cuerpo.grid_columnconfigure(1, weight=0)

        self._contenido = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        self._contenido.grid(row=0, column=0, sticky="nsew")
        self._contenido.grid_columnconfigure(0, weight=1)
        self._contenido.grid_rowconfigure(2, weight=1)

        self._cargar()

    # --- carga ---------------------------------------------------------------

    def _cargar(self) -> None:
        try:
            self._detalle = self._presentador.detalle(self._departamento_id)
        except ErrorDeNegocio as error:
            self._detalle = None
            self.mostrar_banner("error", str(error))
            return
        self.poner_titulo(self._detalle.unidad)
        hay_impagas = self._detalle.proximo_vencimiento is not None
        self._boton_registrar_pago.configure(
            state="normal" if hay_impagas else "disabled"
        )
        self._render()

    def _render(self) -> None:
        for hijo in self._contenido.winfo_children():
            hijo.destroy()

        chips = ctk.CTkFrame(self._contenido, fg_color="transparent")
        chips.grid(row=0, column=0, sticky="w")
        if self._detalle.estado_mes is not None:
            ChipEstado(chips, self._detalle.estado_mes).pack(side="left", padx=(0, 8))
        if self._detalle.inquilino is None:
            if self._detalle.fecha_contrato_vencido is not None:
                ChipEstado(
                    chips,
                    "alerta",
                    texto=f"Contrato vencido el {formatear_fecha(self._detalle.fecha_contrato_vencido)}",
                ).pack(side="left")
            else:
                ChipEstado(chips, "pendiente", texto="Sin contrato").pack(side="left")
        elif (
            self._detalle.contrato is not None
            and self._detalle.contrato.fecha_fin is not None
            and self._detalle.contrato.fecha_fin < self._servicios.departamentos.hoy()
        ):
            ChipEstado(
                chips,
                "alerta",
                texto=f"Contrato vencido el {formatear_fecha(self._detalle.contrato.fecha_fin)}",
            ).pack(side="left")

        self._selector = ctk.CTkSegmentedButton(
            self._contenido,
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
        self._selector.grid(row=1, column=0, sticky="w", pady=(12, estilo.GAP))
        self._selector.set(self._seccion)

        self._seccion_activa = ctk.CTkFrame(self._contenido, fg_color="transparent")
        self._seccion_activa.grid(row=2, column=0, sticky="nsew")
        self._seccion_activa.grid_columnconfigure(0, weight=1)
        self._seccion_activa.grid_rowconfigure(0, weight=1)
        self._pintar_seccion()

    def _cambiar_seccion(self, valor: str) -> None:
        self._seccion = valor
        self._pintar_seccion()

    def _pintar_seccion(self) -> None:
        for hijo in self._seccion_activa.winfo_children():
            hijo.destroy()
        {
            "Resumen": self._pintar_resumen,
            "Contrato": self._pintar_contrato,
            "Cuotas y pagos": self._pintar_cuotas,
        }[self._seccion]()

    # --- secciones -----------------------------------------------------------

    def _pintar_resumen(self) -> None:
        marco = ctk.CTkFrame(self._seccion_activa, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="new")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_columnconfigure(1, weight=1)

        datos = Tarjeta(marco, titulo="Datos de la unidad")
        datos.grid(row=0, column=0, sticky="nsew", padx=(0, estilo.GAP // 2))
        detalle = self._detalle
        self._fila_dato(datos.cuerpo, 0, "Dirección", detalle.direccion)
        self._fila_dato(datos.cuerpo, 1, "Piso", detalle.piso)
        self._fila_dato(datos.cuerpo, 2, "Depto", detalle.depto)
        self._fila_dato(datos.cuerpo, 3, "m²", str(detalle.m2) if detalle.m2 else None)
        self._fila_dato(datos.cuerpo, 4, "Propietario", detalle.propietario)

        inquilino = Tarjeta(marco, titulo="Inquilino")
        inquilino.grid(row=0, column=1, sticky="nsew", padx=(estilo.GAP // 2, 0))
        if detalle.inquilino is None:
            ctk.CTkLabel(
                inquilino.cuerpo,
                text="(sin contrato)",
                font=estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO_3,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(
                inquilino.cuerpo,
                text="Se completa al cargar un contrato.",
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_3,
                anchor="w",
            ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        else:
            self._fila_dato(inquilino.cuerpo, 0, "Nombre", detalle.inquilino.nombre)
            self._fila_dato(inquilino.cuerpo, 1, "Teléfono", detalle.inquilino.telefono)
            self._fila_dato(inquilino.cuerpo, 2, "Email", detalle.inquilino.email)
            if detalle.inquilino.telefono:
                estilo.boton_secundario(
                    inquilino.cuerpo,
                    "Copiar teléfono",
                    command=lambda telefono=detalle.inquilino.telefono: self._copiar_telefono(
                        telefono
                    ),
                ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))

        kpis = ctk.CTkFrame(marco, fg_color="transparent")
        kpis.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(estilo.GAP, 0))
        for columna in range(3):
            kpis.grid_columnconfigure(columna, weight=1)

        deuda = detalle.deuda_centavos
        TarjetaKPI(
            kpis,
            "Deuda total",
            valor=formatear_monto(deuda) if deuda is not None else "—",
            tono="peligro" if deuda else "normal",
        ).grid(row=0, column=0, sticky="nsew", padx=(0, estilo.GAP // 2))
        cuota = detalle.cuota_vigente_centavos
        TarjetaKPI(
            kpis,
            "Cuota vigente",
            valor=formatear_monto(cuota) if cuota is not None else "—",
        ).grid(row=0, column=1, sticky="nsew", padx=estilo.GAP // 2)
        proximo = detalle.proximo_vencimiento
        TarjetaKPI(
            kpis,
            "Próximo vencimiento",
            valor=formatear_fecha(proximo) if proximo is not None else "—",
        ).grid(row=0, column=2, sticky="nsew", padx=(estilo.GAP // 2, 0))

    def _pintar_contrato(self) -> None:
        tarjeta = Tarjeta(self._seccion_activa, titulo="Contrato vigente")
        tarjeta.grid(row=0, column=0, sticky="new")
        contrato = self._detalle.contrato
        if contrato is None:
            ctk.CTkLabel(
                tarjeta.cuerpo,
                text="Todavía no hay contrato para esta unidad.",
                font=estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO_2,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            estilo.boton_secundario(
                tarjeta.cuerpo,
                "Cargar contrato",
                command=lambda: self._abrir_panel_contrato("cargar"),
            ).grid(row=1, column=0, sticky="w", pady=(12, 0))
            return

        vigencia = f"Desde {formatear_fecha(contrato.fecha_inicio)}"
        if contrato.fecha_fin is not None:
            vigencia += f" hasta {formatear_fecha(contrato.fecha_fin)}"
        proximo_ajuste = (
            formatear_fecha(contrato.proxima_fecha_ajuste)
            if contrato.proxima_fecha_ajuste is not None
            else "—"
        )

        self._fila_dato(tarjeta.cuerpo, 0, "Inquilino", contrato.inquilino_nombre, ancho=160)
        self._fila_dato(tarjeta.cuerpo, 1, "Vigencia", vigencia, ancho=160)
        self._fila_dato(
            tarjeta.cuerpo,
            2,
            "Cuota vigente",
            formatear_monto(contrato.monto_centavos),
            ancho=160,
        )
        self._fila_dato(
            tarjeta.cuerpo,
            3,
            "Día de vencimiento",
            f"Día {contrato.dia_vencimiento} de cada mes",
            ancho=160,
        )
        self._fila_dato(
            tarjeta.cuerpo,
            4,
            "Días de gracia",
            formatear_dias(contrato.dias_gracia),
            ancho=160,
        )
        self._fila_dato(
            tarjeta.cuerpo,
            5,
            "Tasa de mora",
            f"{formatear_porcentaje(contrato.tasa_mora_bp)} mensual",
            ancho=160,
        )
        self._fila_dato(
            tarjeta.cuerpo,
            6,
            "Ciclo de ajuste",
            f"Cada {contrato.ciclo_meses} meses",
            ancho=160,
        )
        self._fila_dato(
            tarjeta.cuerpo,
            7,
            "Próxima fecha de ajuste",
            proximo_ajuste,
            ancho=160,
        )

        acciones = ctk.CTkFrame(tarjeta.cuerpo, fg_color="transparent")
        acciones.grid(row=8, column=0, columnspan=2, sticky="w", pady=(16, 0))
        estilo.boton_secundario(
            acciones,
            "Editar contrato",
            command=lambda: self._abrir_panel_contrato("editar"),
        ).pack(side="left")
        estilo.boton_secundario(
            acciones,
            "Nuevo contrato",
            command=lambda: self._abrir_panel_contrato("nuevo"),
        ).pack(side="left", padx=(8, 0))

    def _pintar_cuotas(self) -> None:
        marco = self._seccion_activa
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(1, weight=1)

        barra = ctk.CTkFrame(marco, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        barra.grid_columnconfigure(0, weight=1)

        exportar = estilo.boton_secundario(
            barra,
            "Exportar estado de cuenta (CSV)",
            command=self._exportar_estado_cuenta,
        )
        exportar.grid(row=0, column=1, sticky="e")

        cuotas = self._presentador.cuotas(self._departamento_id)
        tabla = Tabla(
            marco,
            columnas=[
                Columna("Período", "periodo", 1.5),
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
                    "Pagado",
                    "pagado_centavos",
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
            al_click_fila=self._seleccionar_cuota,
            mensaje_vacio="Generá las cuotas del mes desde Cobranzas.",
        )
        tabla.grid(row=1, column=0, sticky="nsew")
        tabla.mostrar(cuotas)

        self._marco_pagos_cuota = ctk.CTkFrame(marco, fg_color="transparent")
        self._marco_pagos_cuota.grid(row=2, column=0, sticky="ew", pady=(estilo.GAP, 0))
        self._marco_pagos_cuota.grid_columnconfigure(0, weight=1)
        if self._cuota_seleccionada_id is not None:
            self._render_pagos_cuota(self._cuota_seleccionada_id)

    def _seleccionar_cuota(self, cuota_id: int) -> None:
        self._cuota_seleccionada_id = cuota_id
        if self._marco_pagos_cuota is not None:
            self._render_pagos_cuota(cuota_id)

    def _exportar_estado_cuenta(self) -> None:
        """CSV de las cuotas de esta unidad (§3.3) — escribe `ServicioInformes`."""
        ruta = filedialog.asksaveasfilename(
            parent=self,
            title="Guardar estado de cuenta",
            initialdir=escritorio_default(),
            initialfile=nombre_estado_cuenta(self._servicios.cobranzas.hoy()),
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not ruta:
            return
        try:
            self._servicios.informes.exportar_estado_cuenta(
                ruta, departamento_id=self._departamento_id
            )
        except (ErrorDeNegocio, OSError) as error:
            self.mostrar_banner("error", f"No se pudo guardar: {error}")
            return
        self.mostrar_banner("exito", f"Se exportó a {ruta}")

    def _render_pagos_cuota(self, cuota_id: int) -> None:
        for hijo in self._marco_pagos_cuota.winfo_children():
            hijo.destroy()
        pagos: list[PagoImputadoCuota] = self._presentador.pagos_de_cuota(cuota_id)
        tarjeta = Tarjeta(self._marco_pagos_cuota, titulo="Pagos imputados a la cuota")
        tarjeta.grid(row=0, column=0, sticky="ew")
        if not pagos:
            ctk.CTkLabel(
                tarjeta.cuerpo,
                text="Esta cuota todavía no registra pagos.",
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_2,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            return
        for indice, pago in enumerate(pagos):
            medio = _MEDIOS_ETIQUETA.get(pago.medio, pago.medio)
            mora_txt = (
                f" · Mora cobrada: {formatear_monto(pago.mora_centavos)}"
                if pago.mora_centavos > 0
                else ""
            )
            texto = (
                f"{formatear_fecha(pago.fecha)} · "
                f"{formatear_monto(pago.monto_centavos)} ({medio}){mora_txt}"
            )
            ctk.CTkLabel(
                tarjeta.cuerpo,
                text=texto,
                font=estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO,
                anchor="w",
            ).grid(row=indice, column=0, sticky="w", pady=2)

    # --- acciones ------------------------------------------------------------

    def _fila_dato(
        self,
        cuerpo,
        fila: int,
        etiqueta: str,
        valor: str | None,
        ancho: int = 110,
    ) -> None:
        cuerpo.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            cuerpo,
            text=etiqueta,
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
            width=ancho,
        ).grid(row=fila, column=0, sticky="w", pady=2)
        ctk.CTkLabel(
            cuerpo,
            text=valor if valor else "—",
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=fila, column=1, sticky="w", pady=2)

    def _copiar_telefono(self, telefono: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(telefono)
        self.mostrar_banner("exito", "Teléfono copiado al portapapeles.")

    def _registrar_pago(self) -> None:
        if self._detalle is None:
            return
        detalle_pago = None
        if self._cuota_seleccionada_id is not None:
            try:
                detalle_pago = self._servicios.cobranzas.preparar_pago(
                    self._cuota_seleccionada_id
                )
            except ErrorDeNegocio:
                detalle_pago = None
        if detalle_pago is None:
            try:
                detalle_pago = self._servicios.cobranzas.preparar_pago_departamento(
                    self._departamento_id
                )
            except ErrorDeNegocio as error:
                self.mostrar_banner("error", str(error))
                return

        self._cerrar_panel()
        self._panel = PanelPago(
            self.cuerpo,
            self._servicios,
            detalle=detalle_pago,
            al_confirmado=lambda res: self._panel_guardado(texto_exito_pago(res)),
            al_error=self._panel_error,
            al_cerrar=self._cerrar_panel,
        )
        self._panel.grid(row=0, column=1, sticky="ns", padx=(estilo.GAP, 0))

    def _editar(self) -> None:
        if self._detalle is None:
            return
        self._cerrar_panel()
        self._panel = PanelDepartamento(
            self.cuerpo,
            self._servicios,
            departamento=self._detalle,
            al_guardado=self._panel_guardado,
            al_error=self._panel_error,
            al_cerrar=self._cerrar_panel,
            al_eliminado=self._al_eliminado,
        )
        self._panel.grid(row=0, column=1, sticky="ns", padx=(estilo.GAP, 0))

    def _abrir_panel_contrato(self, modo: str) -> None:
        if self._detalle is None:
            return
        self._cerrar_panel()
        contrato = self._detalle.contrato if modo == "editar" else None
        self._panel = PanelContrato(
            self.cuerpo,
            self._servicios,
            departamento_id=self._departamento_id,
            modo=modo,
            contrato=contrato,
            al_guardado=self._panel_guardado,
            al_error=self._panel_error,
            al_cerrar=self._cerrar_panel,
        )
        self._panel.grid(row=0, column=1, sticky="ns", padx=(estilo.GAP, 0))

    def _cerrar_panel(self) -> None:
        if self._panel is not None:
            self._panel.destroy()
            self._panel = None

    def _panel_guardado(self, mensaje: str) -> None:
        self._cerrar_panel()
        self._cargar()
        self.mostrar_banner("exito", mensaje)

    def _panel_error(self, mensaje: str) -> None:
        self.mostrar_banner("error", mensaje)


class PanelContrato(ctk.CTkFrame):
    """Panel lateral de 380 px para Cargar, Editar o Nuevo contrato (§3.3)."""

    ANCHO = 380

    def __init__(
        self,
        master,
        servicios: Servicios,
        departamento_id: int,
        modo: str,
        contrato: ContratoEnDetalle | None,
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
        self._departamento_id = departamento_id
        self._modo = modo  # "cargar" | "editar" | "nuevo"
        self._contrato = contrato
        self._al_guardado = al_guardado
        self._al_error = al_error
        self._al_cerrar = al_cerrar

        interior = ctk.CTkScrollableFrame(self, fg_color="transparent")
        interior.pack(fill="both", expand=True, padx=4, pady=4)
        interior.grid_columnconfigure(0, weight=1)

        titulos = {
            "cargar": "Cargar contrato",
            "editar": "Editar contrato",
            "nuevo": "Nuevo contrato",
        }
        ctk.CTkLabel(
            interior,
            text=titulos[modo],
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 0))

        fila = 1
        if modo == "nuevo":
            ctk.CTkLabel(
                interior,
                text="Cierra el contrato actual y crea uno nuevo sin borrar el historial.",
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_2,
                anchor="w",
                justify="left",
                wraplength=320,
            ).grid(row=fila, column=0, sticky="w", padx=8, pady=(4, 0))
            fila += 1

        self._campo_nombre = Campo(interior, "Inquilino", placeholder="Laura Giménez")
        self._campo_telefono = Campo(interior, "Teléfono", placeholder="11 5555-1234")
        self._campo_email = Campo(interior, "Email", placeholder="inquilino@mail.com")
        self._campo_inicio = Campo(interior, "Fecha de inicio", placeholder="15/10/2026")
        self._campo_monto = Campo(interior, "Cuota mensual ($)", placeholder="12.800")
        self._campo_vencimiento = Campo(
            interior, "Día de vencimiento (1–28)", placeholder="10"
        )
        self._campo_gracia = Campo(interior, "Días de gracia", placeholder="5")
        self._campo_mora = Campo(interior, "Tasa de mora mensual (%)", placeholder="2,00")
        self._campo_ciclo = Campo(interior, "Ciclo de ajuste (meses)", placeholder="3")

        self._campos = {
            "inquilino_nombre": self._campo_nombre,
            "fecha_inicio": self._campo_inicio,
            "monto": self._campo_monto,
            "dia_vencimiento": self._campo_vencimiento,
            "dias_gracia": self._campo_gracia,
            "tasa_mora": self._campo_mora,
            "ciclo_meses": self._campo_ciclo,
        }

        orden = (
            self._campo_nombre,
            self._campo_telefono,
            self._campo_email,
            self._campo_inicio,
            self._campo_monto,
            self._campo_vencimiento,
            self._campo_gracia,
            self._campo_mora,
            self._campo_ciclo,
        )
        for campo in orden:
            campo.grid(row=fila, column=0, sticky="ew", padx=8, pady=(10, 0))
            campo.atajo("<Return>", self._guardar)
            campo.atajo("<Escape>", self._cerrar)
            fila += 1

        botones = ctk.CTkFrame(interior, fg_color="transparent")
        botones.grid(row=fila, column=0, sticky="ew", padx=8, pady=(16, 8))
        botones.grid_columnconfigure(0, weight=1)
        estilo.boton_primario(botones, "Guardar", command=self._guardar).grid(
            row=0, column=0, sticky="ew"
        )
        estilo.boton_secundario(botones, "Cancelar", command=self._cerrar).grid(
            row=0, column=1, padx=(8, 0)
        )

        self._precargar()
        self._campo_nombre.enfocar()

    def _precargar(self) -> None:
        if self._contrato is not None:
            self._campo_nombre.poner_valor(self._contrato.inquilino_nombre)
            if self._contrato.inquilino_telefono:
                self._campo_telefono.poner_valor(self._contrato.inquilino_telefono)
            if self._contrato.inquilino_email:
                self._campo_email.poner_valor(self._contrato.inquilino_email)
            self._campo_inicio.poner_valor(formatear_fecha(self._contrato.fecha_inicio))
            self._campo_monto.poner_valor(formatear_monto(self._contrato.monto_centavos))
            self._campo_vencimiento.poner_valor(str(self._contrato.dia_vencimiento))
            self._campo_gracia.poner_valor(str(self._contrato.dias_gracia))
            self._campo_mora.poner_valor(formatear_porcentaje(self._contrato.tasa_mora_bp))
            self._campo_ciclo.poner_valor(str(self._contrato.ciclo_meses))
            return

        pred = self._servicios.departamentos.predeterminados_contrato()
        hoy = self._servicios.departamentos.hoy()
        self._campo_inicio.poner_valor(formatear_fecha(hoy))
        self._campo_vencimiento.poner_valor(str(pred.dia_vencimiento))
        self._campo_gracia.poner_valor(str(pred.dias_gracia))
        self._campo_mora.poner_valor(formatear_porcentaje(pred.tasa_mora_bp))
        self._campo_ciclo.poner_valor(str(pred.ciclo_meses))

    def _guardar(self) -> None:
        for campo in self._campos.values():
            campo.limpiar_error()

        try:
            fecha_inicio = parsear_fecha(self._campo_inicio.valor())
        except ValueError:
            self._campo_inicio.mostrar_error("Usá el formato dd/mm/aaaa.")
            self._campo_inicio.enfocar()
            return

        try:
            monto = parsear_monto(self._campo_monto.valor())
        except ValueError:
            self._campo_monto.mostrar_error("Monto inválido")
            self._campo_monto.enfocar()
            return

        try:
            dia_vencimiento = int(self._campo_vencimiento.valor().strip())
        except ValueError:
            self._campo_vencimiento.mostrar_error("Ingresá un día entero entre 1 y 28.")
            self._campo_vencimiento.enfocar()
            return

        try:
            dias_gracia = int(self._campo_gracia.valor().strip())
        except ValueError:
            self._campo_gracia.mostrar_error("Ingresá un número entero de días.")
            self._campo_gracia.enfocar()
            return

        try:
            tasa_mora_bp = parsear_porcentaje(self._campo_mora.valor())
        except ValueError:
            self._campo_mora.mostrar_error("Porcentaje inválido")
            self._campo_mora.enfocar()
            return

        try:
            ciclo_meses = int(self._campo_ciclo.valor().strip())
        except ValueError:
            self._campo_ciclo.mostrar_error("Ingresá la cantidad de meses del ciclo.")
            self._campo_ciclo.enfocar()
            return

        pred = self._servicios.departamentos.predeterminados_contrato()
        redondeo = (
            self._contrato.redondeo_centavos
            if self._contrato is not None
            else pred.redondeo_centavos
        )
        datos = DatosContrato(
            inquilino_nombre=self._campo_nombre.valor(),
            inquilino_telefono=self._campo_telefono.valor(),
            inquilino_email=self._campo_email.valor(),
            fecha_inicio=fecha_inicio,
            monto_centavos=monto,
            dia_vencimiento=dia_vencimiento,
            dias_gracia=dias_gracia,
            tasa_mora_bp=tasa_mora_bp,
            ciclo_meses=ciclo_meses,
            redondeo_centavos=redondeo,
        )

        try:
            if self._modo == "cargar":
                self._servicios.departamentos.cargar_contrato(self._departamento_id, datos)
                self._al_guardado("Contrato cargado.")
            elif self._modo == "editar":
                self._servicios.departamentos.editar_contrato(self._departamento_id, datos)
                self._al_guardado("Contrato actualizado.")
            else:
                self._servicios.departamentos.nuevo_contrato(self._departamento_id, datos)
                self._al_guardado("Nuevo contrato registrado.")
        except ErrorDeValidacion as error:
            campo = self._campos.get(error.campo)
            if campo is not None:
                campo.mostrar_error(str(error))
                campo.enfocar()
            else:
                self._al_error(str(error))
        except ErrorDeNegocio as error:
            self._al_error(str(error))

    def _cerrar(self) -> None:
        self._al_cerrar()
