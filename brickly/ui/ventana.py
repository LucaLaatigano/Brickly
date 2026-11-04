"""Shell de la app: sidebar fijo + navegación + montaje de vistas (spec §1.2).

`main.py` arma los servicios y los inyecta acá; las vistas se montan y
desmontan en el área de contenido al navegar (sin CTkTabview para navegar).
`ir_a` acepta `opciones` (dict) para navegación con contexto — p. ej. el Panel
abre Cobranzas/Atrasos con una cuota y su panel de pago listos (F3).
"""

import customtkinter as ctk

from brickly.ui import estilo
from brickly.ui.vistas.ajustes_ipc import VistaAjustesIpc
from brickly.ui.vistas.cobranzas import VistaCobranzas
from brickly.ui.vistas.configuracion import VistaConfiguracion
from brickly.ui.vistas.departamentos import VistaDepartamentos
from brickly.ui.vistas.detalle_departamento import VistaDetalleDepartamento
from brickly.ui.vistas.informes import VistaInformes
from brickly.ui.vistas.panel import VistaPanel

ITEMS_NAV = (
    "Panel",
    "Departamentos",
    "Cobranzas",
    "Ajustes IPC",
    "Informes",
    "Configuración",
)


class VentanaPrincipal(ctk.CTk):
    def __init__(self, servicios):
        super().__init__()
        estilo.inicializar()
        self.servicios = servicios
        self.title("Brickly")
        self.configure(fg_color=estilo.FONDO_APP)
        self.minsize(1100, 700)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._botones_nav: dict[str, ctk.CTkButton] = {}
        self._clave_activa: str | None = None

        self._crear_sidebar()

        self.contenido = ctk.CTkFrame(self, fg_color="transparent")
        self.contenido.grid(
            row=0, column=1, sticky="nsew",
            padx=estilo.PADDING_PAGINA, pady=estilo.PADDING_PAGINA,
        )
        self.contenido.grid_columnconfigure(0, weight=1)
        self.contenido.grid_rowconfigure(0, weight=1)

        self._centrar(1280, 800)
        self.ir_a("Panel")

    # --- armado del shell

    def _crear_sidebar(self) -> None:
        barra = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=estilo.FONDO_APP)
        barra.grid(row=0, column=0, sticky="nsw")
        barra.grid_propagate(False)
        barra.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            barra,
            text="Brickly",
            font=estilo.FUENTE_TITULO,
            text_color=estilo.TEXTO,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(24, 16))

        for fila, etiqueta in enumerate(ITEMS_NAV, start=1):
            boton = ctk.CTkButton(
                barra,
                text=etiqueta,
                anchor="w",
                height=estilo.ALTO_NAV,
                corner_radius=estilo.RADIO_BOTON,
                fg_color="transparent",
                hover_color=estilo.SUPERFICIE_2,
                text_color=estilo.TEXTO_2,
                font=estilo.FUENTE_CUERPO,
                command=lambda etiqueta=etiqueta: self.ir_a(etiqueta),
            )
            boton.grid(row=fila, column=0, sticky="ew", padx=8, pady=2)
            self._botones_nav[etiqueta] = boton

    def _centrar(self, ancho: int, alto: int) -> None:
        self.update_idletasks()
        x = max((self.winfo_screenwidth() - ancho) // 2, 0)
        y = max((self.winfo_screenheight() - alto) // 2, 0)
        self.geometry(f"{ancho}x{alto}+{x}+{y}")

    # --- navegación

    def ir_a(
        self,
        clave: str,
        mensaje_banner: tuple[str, str] | None = None,
        opciones: dict | None = None,
    ) -> None:
        self._montar(lambda: self._crear_vista(clave, mensaje_banner, opciones))
        self._marcar_activa(clave)

    def _montar(self, fabrica) -> None:
        for widget in self.contenido.winfo_children():
            widget.destroy()
        fabrica().grid(row=0, column=0, sticky="nsew")

    def _navegar(self, clave: str, opciones: dict | None = None) -> None:
        """Callback que reciben las vistas para pedir navegación con contexto."""
        self.ir_a(clave, opciones=opciones)

    def _crear_vista(
        self,
        clave: str,
        mensaje_banner: tuple[str, str] | None = None,
        opciones: dict | None = None,
    ) -> ctk.CTkFrame:
        opciones = opciones or {}
        if clave == "Panel":
            return VistaPanel(self.contenido, self.servicios, al_navegar=self._navegar)
        if clave == "Departamentos":
            departamento_id = opciones.get("departamento_id")
            if departamento_id is not None:
                return VistaDetalleDepartamento(
                    self.contenido,
                    self.servicios,
                    departamento_id,
                    al_volver=lambda: self.ir_a("Departamentos"),
                    al_eliminado=self._departamento_eliminado,
                )
            return VistaDepartamentos(
                self.contenido,
                self.servicios,
                al_abrir_detalle=self._abrir_detalle_departamento,
                mensaje_inicial=mensaje_banner,
            )
        if clave == "Cobranzas":
            return VistaCobranzas(
                self.contenido,
                self.servicios,
                modo_inicial=opciones.get("modo_inicial", "Mes"),
                cuota_inicial_id=opciones.get("cuota_inicial_id"),
                abrir_primer_pago=opciones.get("abrir_primer_pago", False),
            )
        if clave == "Ajustes IPC":
            return VistaAjustesIpc(self.contenido, self.servicios)
        if clave == "Informes":
            return VistaInformes(self.contenido, self.servicios)
        return VistaConfiguracion(self.contenido, self.servicios)

    def _abrir_detalle_departamento(self, departamento_id: int) -> None:
        self._montar(
            lambda: VistaDetalleDepartamento(
                self.contenido,
                self.servicios,
                departamento_id,
                al_volver=lambda: self.ir_a("Departamentos"),
                al_eliminado=self._departamento_eliminado,
            )
        )
        # El detalle es una hoja de Departamentos: la nav queda en ese ítem.
        self._marcar_activa("Departamentos")

    def _departamento_eliminado(self, mensaje: str) -> None:
        self.ir_a("Departamentos", mensaje_banner=("exito", mensaje))

    def _marcar_activa(self, clave: str) -> None:
        self._clave_activa = clave
        for etiqueta, boton in self._botones_nav.items():
            activa = etiqueta == clave
            boton.configure(
                fg_color=estilo.SUPERFICIE if activa else "transparent",
                text_color=estilo.TEXTO if activa else estilo.TEXTO_2,
                font=estilo.FUENTE_CUERPO_NEGRITA if activa else estilo.FUENTE_CUERPO,
            )
