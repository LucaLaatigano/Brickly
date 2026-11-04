"""Pantalla Departamentos (spec §3.2): lista + ABM inline en columna de 380 px.

El panel de alta/edición nunca es modal: vive en la columna derecha, el mismo
patrón del panel de pago de Cobranzas (§3.4). La vista no calcula nada — el
presentador trae las filas y el servicio ejecuta los comandos (§1.5).
"""

from tkinter import messagebox

import customtkinter as ctk

from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.departamentos import (
    DependenciasDepartamento,
    DetalleDepartamento,
    DatosDepartamento,
    FiltroDepartamentos,
)
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.ui import estilo
from brickly.ui.componentes.formulario import Campo
from brickly.ui.componentes.tabla import Columna, Tabla
from brickly.ui.formato import formatear_fecha, formatear_monto
from brickly.ui.presenters.departamento import PresenterDepartamentos
from brickly.ui.vistas.base import VistaBase

_FILTROS: dict[str, FiltroDepartamentos] = {
    "Todos": "todos",
    "Al día": "al_dia",
    "Deben": "deben",
    "Sin contrato": "sin_contrato",
}

_ETIQUETAS_ESTADO = {
    "pagada": "Pagada",
    "parcial": "Parcial",
    "pendiente": "Pendiente",
    "vencida": "Vencida",
}


def consecuencia_de_borrado(dependencias: DependenciasDepartamento) -> str:
    """Frase de consecuencia del diálogo (§2.7); vacía si no hay movimientos."""
    partes = []
    if dependencias.contratos:
        partes.append(
            "su contrato" if dependencias.contratos == 1 else f"sus {dependencias.contratos} contratos"
        )
    if dependencias.cuotas:
        partes.append(_plural(dependencias.cuotas, "cuota", "cuotas"))
    if dependencias.pagos:
        partes.append(_plural(dependencias.pagos, "pago", "pagos"))
    if not partes:
        return ""
    return f" Se borran también {_enumerar(partes)}."


def _plural(cantidad: int, singular: str, plural: str) -> str:
    return f"{cantidad} {singular}" if cantidad == 1 else f"{cantidad} {plural}"


def _enumerar(partes: list[str]) -> str:
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + " y " + partes[-1]


def _color_inquilino(valor) -> tuple | None:
    return estilo.TEXTO_3 if valor is None else None


def _color_deuda(valor) -> tuple | None:
    return estilo.PELIGRO if valor and valor > 0 else None


def _formato_deuda(valor: int) -> str:
    return formatear_monto(valor) if valor > 0 else "—"


class VistaDepartamentos(VistaBase):
    def __init__(
        self,
        master,
        servicios: Servicios,
        al_abrir_detalle,
        mensaje_inicial: tuple[str, str] | None = None,
    ):
        super().__init__(master, titulo="Departamentos")
        self._servicios = servicios
        self._presentador = PresenterDepartamentos(servicios)
        self._al_abrir_detalle = al_abrir_detalle
        self._panel: PanelDepartamento | None = None
        self._rebote: str | None = None

        self.agregar_accion(
            estilo.boton_primario(self._acciones, "+ Agregar departamento", command=self._abrir_alta)
        )

        self.cuerpo.grid_columnconfigure(0, weight=1)
        self.cuerpo.grid_columnconfigure(1, weight=0)

        columna = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        columna.grid(row=0, column=0, sticky="nsew")
        columna.grid_columnconfigure(0, weight=1)
        columna.grid_rowconfigure(1, weight=1)

        filtros = ctk.CTkFrame(columna, fg_color="transparent")
        filtros.grid(row=0, column=0, sticky="ew", pady=(0, estilo.GAP))
        filtros.grid_columnconfigure(0, weight=1)

        self._busqueda = ctk.CTkEntry(
            filtros,
            width=320,
            height=estilo.ALTO_BOTON,
            placeholder_text="Buscar dirección o inquilino…",
            border_color=estilo.BORDE,
            fg_color=estilo.SUPERFICIE,
            text_color=estilo.TEXTO,
            font=estilo.FUENTE_CUERPO,
        )
        self._busqueda.grid(row=0, column=0, sticky="w")
        self._busqueda.bind("<KeyRelease>", self._al_escribir)

        self._selector = ctk.CTkSegmentedButton(
            filtros,
            values=list(_FILTROS),
            command=lambda _valor: self._recargar(),
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
        self._selector.grid(row=0, column=1, sticky="e")
        self._selector.set("Todos")

        self._tabla = Tabla(
            columna,
            columnas=[
                Columna("Unidad", "unidad", 3),
                Columna(
                    "Inquilino",
                    "inquilino",
                    2,
                    texto_none="(sin contrato)",
                    color=_color_inquilino,
                ),
                Columna(
                    "Cuota vig.", "cuota_vigente_centavos", 1.5,
                    alineacion="e", formato=formatear_monto,
                ),
                Columna("Estado", "estado_mes", 1.5, es_chip=True),
                Columna(
                    "Deuda", "deuda_centavos", 1.5,
                    alineacion="e", formato=_formato_deuda, color=_color_deuda,
                ),
                Columna("Últ. pago", "ultimo_pago", 1.5, alineacion="e", formato=formatear_fecha),
            ],
            al_click_fila=self._al_abrir_detalle,
        )
        self._tabla.grid(row=1, column=0, sticky="nsew")

        self._recargar()
        if mensaje_inicial is not None:
            self.mostrar_banner(*mensaje_inicial)

    # --- lista ---------------------------------------------------------------

    def _recargar(self) -> None:
        self._rebote = None
        busqueda = self._busqueda.get().strip()
        filas = self._presentador.filas(busqueda, _FILTROS[self._selector.get()])
        self._tabla.cambiar_vacio(*self._vacio(filas, busqueda))
        self._tabla.mostrar(filas)

    def _vacio(self, filas, busqueda: str) -> tuple[str, tuple[str, object] | None]:
        if filas:
            return "", None
        if busqueda:
            return f"Nada coincide con «{busqueda}».", ("Limpiar filtro", self._limpiar_filtros)
        etiqueta = self._selector.get()
        if etiqueta != "Todos":
            return f"Nada coincide con «{etiqueta}».", ("Limpiar filtro", self._limpiar_filtros)
        return (
            "Todavía no hay departamentos cargados. Empezá agregando el primero.",
            ("Agregar departamento", self._abrir_alta),
        )

    def _al_escribir(self, _evento=None) -> None:
        """Debounce 300 ms (§3.2): una recarga por pausa de tipeo, no por tecla."""
        if self._rebote is not None:
            self.after_cancel(self._rebote)
        self._rebote = self.after(300, self._recargar)

    def _limpiar_filtros(self) -> None:
        self._busqueda.delete(0, "end")
        self._selector.set("Todos")
        self._recargar()

    # --- panel ABM -----------------------------------------------------------

    def _abrir_alta(self) -> None:
        self._abrir_panel(departamento=None)

    def _abrir_panel(self, departamento: DetalleDepartamento | None) -> None:
        self._cerrar_panel()
        self._panel = PanelDepartamento(
            self.cuerpo,
            self._servicios,
            departamento=departamento,
            al_guardado=self._panel_guardado,
            al_error=self._panel_error,
            al_cerrar=self._cerrar_panel,
            al_eliminado=self._panel_eliminado,
        )
        self._panel.grid(row=0, column=1, sticky="ns", padx=(estilo.GAP, 0))

    def _cerrar_panel(self) -> None:
        if self._panel is not None:
            self._panel.destroy()
            self._panel = None

    def _panel_guardado(self, mensaje: str) -> None:
        self._cerrar_panel()
        self._recargar()
        self.mostrar_banner("exito", mensaje)

    def _panel_error(self, mensaje: str) -> None:
        self.mostrar_banner("error", mensaje)

    def _panel_eliminado(self, mensaje: str) -> None:
        self._cerrar_panel()
        self._recargar()
        self.mostrar_banner("exito", mensaje)


class PanelDepartamento(ctk.CTkFrame):
    """Alta/edición inline de 380 px; los errores se muestran, nunca se tragan."""

    ANCHO = 380

    def __init__(
        self,
        master,
        servicios: Servicios,
        departamento: DetalleDepartamento | None,
        al_guardado,
        al_error,
        al_cerrar,
        al_eliminado,
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
        self._departamento = departamento
        self._al_guardado = al_guardado
        self._al_error = al_error
        self._al_cerrar = al_cerrar
        self._al_eliminado = al_eliminado

        interior = ctk.CTkFrame(self, fg_color="transparent")
        interior.pack(fill="both", expand=True, padx=estilo.PADDING_CARD, pady=estilo.PADDING_CARD)
        interior.grid_columnconfigure(0, weight=1)

        editando = departamento is not None
        ctk.CTkLabel(
            interior,
            text="Editar departamento" if editando else "Agregar departamento",
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self._campo_direccion = Campo(interior, "Dirección", placeholder="Rivadavia 3421")
        self._campo_piso = Campo(interior, "Piso", placeholder="3 · PB")
        self._campo_depto = Campo(interior, "Depto", placeholder="B")
        self._campo_m2 = Campo(interior, "m²", placeholder="62")
        self._campo_propietario = Campo(interior, "Propietario", placeholder="Nombre y apellido")
        self._campos = {
            "direccion": self._campo_direccion,
            "m2": self._campo_m2,
        }
        for fila, campo in enumerate(
            (
                self._campo_direccion,
                self._campo_piso,
                self._campo_depto,
                self._campo_m2,
                self._campo_propietario,
            ),
            start=1,
        ):
            campo.grid(row=fila, column=0, sticky="ew", pady=(12, 0))
            campo.atajo("<Return>", self._guardar)
            campo.atajo("<Escape>", self._cerrar)

        botones = ctk.CTkFrame(interior, fg_color="transparent")
        botones.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        botones.grid_columnconfigure(0, weight=1)
        estilo.boton_primario(botones, "Guardar", command=self._guardar).grid(
            row=0, column=0, sticky="ew"
        )
        estilo.boton_secundario(botones, "Cancelar", command=self._cerrar).grid(
            row=0, column=1, padx=(8, 0)
        )

        if editando:
            self._precargar(departamento)
            ctk.CTkFrame(interior, height=1, fg_color=estilo.BORDE, corner_radius=0).grid(
                row=7, column=0, sticky="ew", pady=(16, 8)
            )
            # Texto en PELIGRO, sin botón rojo (§1.3: el peligro va en texto y chips).
            ctk.CTkButton(
                interior,
                text="Eliminar departamento",
                command=self._eliminar,
                anchor="w",
                fg_color="transparent",
                hover_color=estilo.SUPERFICIE_2,
                text_color=estilo.PELIGRO,
                font=estilo.FUENTE_CHICO,
            ).grid(row=8, column=0, sticky="w")

        self._campo_direccion.enfocar()

    def _precargar(self, departamento: DetalleDepartamento) -> None:
        self._campo_direccion.poner_valor(departamento.direccion)
        if departamento.piso:
            self._campo_piso.poner_valor(departamento.piso)
        if departamento.depto:
            self._campo_depto.poner_valor(departamento.depto)
        if departamento.m2 is not None:
            self._campo_m2.poner_valor(str(departamento.m2))
        if departamento.propietario:
            self._campo_propietario.poner_valor(departamento.propietario)

    # --- acciones ------------------------------------------------------------

    def _guardar(self) -> None:
        for campo in self._campos.values():
            campo.limpiar_error()

        m2 = None
        texto_m2 = self._campo_m2.valor().strip()
        if texto_m2:
            try:
                m2 = int(texto_m2)
            except ValueError:
                self._campo_m2.mostrar_error("Los m² deben ser un número entero.")
                return

        datos = DatosDepartamento(
            direccion=self._campo_direccion.valor(),
            piso=self._campo_piso.valor(),
            depto=self._campo_depto.valor(),
            m2=m2,
            propietario=self._campo_propietario.valor(),
        )
        try:
            if self._departamento is None:
                nuevo_id = self._servicios.departamentos.crear(datos)
                self._al_guardado(f"Departamento agregado: «{self._unidad(nuevo_id)}»")
            else:
                self._servicios.departamentos.editar(self._departamento.id, datos)
                self._al_guardado(f"Cambios guardados: «{self._unidad(self._departamento.id)}»")
        except ErrorDeValidacion as error:
            campo = self._campos.get(error.campo)
            if campo is not None:
                campo.mostrar_error(str(error))
                campo.enfocar()
            else:
                self._al_error(str(error))
        except ErrorDeNegocio as error:
            self._al_error(str(error))

    def _eliminar(self) -> None:
        dependencias = self._servicios.departamentos.contar_dependencias(self._departamento.id)
        respuesta = messagebox.askyesno(
            "Eliminar departamento",
            f"¿Eliminar «{self._departamento.unidad}»?"
            f"{consecuencia_de_borrado(dependencias)} No se puede deshacer.",
            icon="warning",
            parent=self.winfo_toplevel(),
        )
        if not respuesta:
            return
        try:
            self._servicios.departamentos.eliminar(self._departamento.id)
        except ErrorDeNegocio as error:
            self._al_error(str(error))
            return
        self._al_eliminado(f"Departamento eliminado: «{self._departamento.unidad}»")

    def _cerrar(self) -> None:
        self._al_cerrar()

    def _unidad(self, departamento_id: int) -> str:
        return self._servicios.departamentos.detalle(departamento_id).unidad
