"""Asistente inline de importación de departamentos y contratos desde Excel (spec §3 y ADR-0005).

Wizard de 3 pasos (1 Archivo y hoja › 2 Columnas › 3 Revisión e importación),
con edición en vivo en panel lateral de 380 px y confirmación atómica.
"""

from __future__ import annotations

from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Callable

import customtkinter as ctk

from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.importacion import (
    CAMPOS_CANONICOS,
    ETIQUETAS_CAMPOS,
    EdicionManualFilaImportacion,
    FilaPrevisualizacionImportacion,
    InspeccionArchivoImportacion,
    PrevisualizacionImportacion,
)
from brickly.dominio.errores import ErrorDeNegocio
from brickly.ui import estilo
from brickly.ui.componentes.chip import ChipEstado
from brickly.ui.componentes.formulario import Campo
from brickly.ui.componentes.tabla import Columna, Tabla
from brickly.ui.componentes.tarjeta import Tarjeta
from brickly.ui.presenters.importacion import (
    FilaImportacionPresentada,
    ResumenImportacionPresentado,
    presentar_previsualizacion,
)
from brickly.ui.vistas.base import VistaBase

_OPCION_NO_IMPORTAR = "(No importar / usar predeterminado)"
_FILTROS_TABLA = ("Todas", "Listas", "Con errores", "Omitidas")


class VistaImportacionDepartamentos(VistaBase):
    """Wizard inline para importar unidades, inquilinos y contratos desde Excel."""

    def __init__(
        self,
        master,
        servicios: Servicios,
        al_volver: Callable[[], None],
        al_navegar: Callable[[str, dict | None], None],
    ) -> None:
        super().__init__(master, titulo="Importar desde Excel")
        self._servicios = servicios
        self._al_volver = al_volver
        self._al_navegar = al_navegar

        self._servicio_imp = servicios.importacion

        self._paso: int = 1
        self._ruta_archivo: str | None = None
        self._inspeccion: InspeccionArchivoImportacion | None = None
        self._nombre_hoja_seleccionada: str | None = None
        self._fila_encabezado_seleccionada: int = 1

        self._mapeo_columnas: dict[str, int] = {}
        self._menus_mapeo: dict[str, ctk.CTkOptionMenu] = {}

        self._previsualizacion: PrevisualizacionImportacion | None = None
        self._resumen_presentado: ResumenImportacionPresentado | None = None
        self._filas_presentadas: list[FilaImportacionPresentada] = []
        self._filtro_tabla: str = "Todas"
        self._ediciones: dict[int, EdicionManualFilaImportacion] = {}
        self._fila_en_edicion: FilaPrevisualizacionImportacion | None = None

        # Botón Volver en cabecera
        self.agregar_accion(
            estilo.boton_secundario(
                self._acciones,
                "‹ Volver a Departamentos",
                command=self._volver_con_confirmacion,
            )
        )

        self.cuerpo.grid_columnconfigure(0, weight=1)
        self.cuerpo.grid_rowconfigure(1, weight=1)

        # Franja de Stepper
        self._franja_pasos = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        self._franja_pasos.grid(row=0, column=0, sticky="w", pady=(0, estilo.GAP))

        # Contenedor principal de pasos
        self._cuerpo_paso = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        self._cuerpo_paso.grid(row=1, column=0, sticky="nsew")
        self._cuerpo_paso.grid_columnconfigure(0, weight=1)
        self._cuerpo_paso.grid_rowconfigure(0, weight=1)

        self._panel_edicion: PanelFilaImportacion | None = None

        self._pintar_paso()

    def _volver_con_confirmacion(self) -> None:
        if self._paso == 3 and self._ediciones:
            if not messagebox.askyesno(
                "Descartar cambios",
                "Hiciste correcciones en la previsualización que no se guardaron. ¿Seguro que querés salir?",
            ):
                return
        self._al_volver()

    def _pintar_stepper(self) -> None:
        for hijo in self._franja_pasos.winfo_children():
            hijo.destroy()
        pasos = (
            (1, "Archivo y hoja"),
            (2, "Columnas"),
            (3, "Revisión e importación"),
        )
        for indice, (numero, nombre) in enumerate(pasos):
            if numero == self._paso:
                color, fuente = estilo.ACENTO, estilo.FUENTE_CHICO_NEGRITA
            elif numero < self._paso:
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
                ).pack(side="left", padx=8)

    def _limpiar_cuerpo(self) -> None:
        self._cerrar_panel()
        for hijo in self._cuerpo_paso.winfo_children():
            hijo.destroy()

    def _pintar_paso(self) -> None:
        self._pintar_stepper()
        self._limpiar_cuerpo()
        if self._paso == 1:
            self._pintar_paso_1()
        elif self._paso == 2:
            self._pintar_paso_2()
        elif self._paso == 3:
            self._pintar_paso_3()
        elif self._paso == 4:
            self._pintar_resultado()

    # --- Paso 1: Archivo y hoja ----------------------------------------------

    def _pintar_paso_1(self) -> None:
        marco = ctk.CTkFrame(self._cuerpo_paso, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)

        tarjeta = Tarjeta(marco, titulo="1. Seleccionar archivo Excel")
        tarjeta.grid(row=0, column=0, sticky="new", pady=(0, estilo.GAP))

        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=(
                "Elegí una planilla de cálculo (.xlsx) con los datos de tus departamentos e inquilinos.\n"
                "Se importarán departamentos, inquilinos y contratos vigentes. No se importan pagos ni deudas anteriores."
            ),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(0, 16))

        fila_archivo = ctk.CTkFrame(tarjeta.cuerpo, fg_color="transparent")
        fila_archivo.pack(fill="x", pady=(0, 16))

        btn_elegir = estilo.boton_secundario(
            fila_archivo, "Seleccionar archivo .xlsx…", command=self._seleccionar_archivo
        )
        btn_elegir.pack(side="left", padx=(0, 12))

        texto_ruta = self._ruta_archivo or "Ningún archivo seleccionado."
        lbl_ruta = ctk.CTkLabel(
            fila_archivo,
            text=texto_ruta,
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO if self._ruta_archivo else estilo.TEXTO_3,
            anchor="w",
        )
        lbl_ruta.pack(side="left", fill="x", expand=True)

        # Opciones si ya se seleccionó archivo
        if self._inspeccion is not None:
            fila_config = ctk.CTkFrame(tarjeta.cuerpo, fg_color="transparent")
            fila_config.pack(fill="x", pady=(0, 16))

            # Selector de hoja
            ctk.CTkLabel(
                fila_config,
                text="Hoja a importar:",
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.TEXTO,
            ).pack(side="left", padx=(0, 8))

            opt_hojas = ctk.CTkOptionMenu(
                fila_config,
                values=list(self._inspeccion.hojas),
                command=self._cambiar_hoja,
                height=estilo.ALTO_BOTON,
                fg_color=estilo.SUPERFICIE_2,
                button_color=estilo.SUPERFICIE_2,
                text_color=estilo.TEXTO,
                font=estilo.FUENTE_CHICO,
            )
            opt_hojas.set(self._nombre_hoja_seleccionada or self._inspeccion.hoja_seleccionada)
            opt_hojas.pack(side="left", padx=(0, 24))

            # Fila de encabezado
            ctk.CTkLabel(
                fila_config,
                text="Fila de encabezados:",
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.TEXTO,
            ).pack(side="left", padx=(0, 8))

            opt_fila = ctk.CTkOptionMenu(
                fila_config,
                values=[str(i) for i in range(1, 11)],
                command=self._cambiar_fila_encabezado,
                width=80,
                height=estilo.ALTO_BOTON,
                fg_color=estilo.SUPERFICIE_2,
                button_color=estilo.SUPERFICIE_2,
                text_color=estilo.TEXTO,
                font=estilo.FUENTE_CHICO,
            )
            opt_fila.set(str(self._fila_encabezado_seleccionada))
            opt_fila.pack(side="left")

        # Botón de plantilla de ejemplo
        fila_plantilla = ctk.CTkFrame(tarjeta.cuerpo, fg_color="transparent")
        fila_plantilla.pack(fill="x", pady=(8, 0))

        btn_plantilla = estilo.boton_secundario(
            fila_plantilla,
            "Descargar plantilla de ejemplo (.xlsx)",
            command=self._descargar_plantilla,
        )
        btn_plantilla.pack(side="left")

        # Barra inferior de acciones
        barra_acciones = ctk.CTkFrame(marco, fg_color="transparent")
        barra_acciones.grid(row=1, column=0, sticky="ew", pady=(16, 0))

        btn_siguiente = estilo.boton_primario(
            barra_acciones,
            "Siguiente: Mapear columnas ›",
            command=self._avanzar_paso_2,
        )
        if self._inspeccion is None:
            btn_siguiente.configure(state="disabled")
        btn_siguiente.pack(side="right")

    def _seleccionar_archivo(self) -> None:
        ruta = filedialog.askopenfilename(
            title="Seleccionar planilla de Excel",
            filetypes=[("Libros de Excel (*.xlsx)", "*.xlsx"), ("Todos los archivos", "*.*")],
        )
        if not ruta:
            return
        if self._servicio_imp is None:
            messagebox.showerror("Error", "El servicio de importación no está disponible.")
            return

        try:
            insp = self._servicio_imp.inspeccionar_archivo(ruta)
            self._ruta_archivo = ruta
            self._inspeccion = insp
            self._nombre_hoja_seleccionada = insp.hoja_seleccionada
            self._fila_encabezado_seleccionada = insp.fila_encabezado_detectada
            self._pintar_paso_1()
        except ErrorDeNegocio as exc:
            messagebox.showerror("No se pudo leer el archivo", str(exc))
        except Exception as exc:
            messagebox.showerror("Error inesperado", f"Ocurrió un error al inspeccionar el archivo:\n{exc}")

    def _cambiar_hoja(self, hoja: str) -> None:
        if self._servicio_imp is None or self._ruta_archivo is None:
            return
        self._nombre_hoja_seleccionada = hoja
        try:
            # Re-inspeccionamos la hoja elegida
            hoja_cruda = self._servicios.importacion._lector.leer_hoja(self._ruta_archivo, hoja)
            from brickly.aplicacion.importacion import (
                detectar_fila_encabezado,
                sugerir_mapeo_columnas,
            )

            fila_enc = detectar_fila_encabezado(hoja_cruda.filas)
            self._fila_encabezado_seleccionada = fila_enc
            fila_obj = next((f for f in hoja_cruda.filas if f.numero_fila == fila_enc), hoja_cruda.filas[0])
            primera_datos = next((f for f in hoja_cruda.filas if f.numero_fila > fila_enc), None)
            cols = sugerir_mapeo_columnas(fila_obj, primera_datos)
            self._inspeccion = InspeccionArchivoImportacion(
                ruta=self._ruta_archivo,
                hojas=self._inspeccion.hojas,
                hoja_seleccionada=hoja,
                fila_encabezado_detectada=fila_enc,
                columnas_detectadas=tuple(cols),
            )
            self._pintar_paso_1()
        except Exception as exc:
            messagebox.showerror("Error al cambiar de hoja", str(exc))

    def _cambiar_fila_encabezado(self, fila_str: str) -> None:
        self._fila_encabezado_seleccionada = int(fila_str)

    def _descargar_plantilla(self) -> None:
        if self._servicio_imp is None:
            return
        ruta = filedialog.asksaveasfilename(
            title="Guardar plantilla de ejemplo",
            defaultextension=".xlsx",
            initialfile="plantilla_departamentos_brickly.xlsx",
            filetypes=[("Libro de Excel (*.xlsx)", "*.xlsx")],
        )
        if not ruta:
            return
        try:
            self._servicio_imp.generar_plantilla(ruta)
            messagebox.showinfo(
                "Plantilla guardada",
                "La plantilla de ejemplo se guardó correctamente. Podés completarla e importarla.",
            )
        except Exception as exc:
            messagebox.showerror("Error al guardar plantilla", str(exc))

    def _avanzar_paso_2(self) -> None:
        self._paso = 2
        self._pintar_paso()

    # --- Paso 2: Columnas ----------------------------------------------------

    def _pintar_paso_2(self) -> None:
        marco = ctk.CTkFrame(self._cuerpo_paso, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(0, weight=1)

        tarjeta = Tarjeta(marco, titulo="2. Mapeo de columnas")
        tarjeta.grid(row=0, column=0, sticky="nsew", pady=(0, estilo.GAP))

        scroll = ctk.CTkScrollableFrame(tarjeta.cuerpo, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            scroll,
            text=(
                "Asociá cada campo de Brickly con una columna de tu planilla Excel.\n"
                "Los campos opcionales no mapeados usarán los valores predeterminados de Configuración."
            ),
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

        # Encabezados de la grilla
        ctk.CTkLabel(
            scroll,
            text="Campo en Brickly",
            font=estilo.FUENTE_CHICO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))

        ctk.CTkLabel(
            scroll,
            text="Columna en tu archivo",
            font=estilo.FUENTE_CHICO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(0, 8))

        ctk.CTkLabel(
            scroll,
            text="Primer valor de ejemplo",
            font=estilo.FUENTE_CHICO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=1, column=2, sticky="w", padx=8, pady=(0, 8))

        # Opciones de columnas para el option menu
        cols_detectadas = self._inspeccion.columnas_detectadas if self._inspeccion else ()
        opciones_menu = [_OPCION_NO_IMPORTAR]
        mapa_etiqueta_col: dict[str, int] = {}
        for c in cols_detectadas:
            etiqueta = f"Col {c.indice + 1}: {c.nombre_original}"
            opciones_menu.append(etiqueta)
            mapa_etiqueta_col[etiqueta] = c.indice

        self._menus_mapeo.clear()

        # Generar una fila por cada campo canónico
        for r_idx, campo in enumerate(CAMPOS_CANONICOS, start=2):
            etiqueta_campo = ETIQUETAS_CAMPOS.get(campo, campo)
            if campo == "direccion":
                etiqueta_campo += " (obligatorio)"

            ctk.CTkLabel(
                scroll,
                text=etiqueta_campo,
                font=estilo.FUENTE_CUERPO_NEGRITA if campo == "direccion" else estilo.FUENTE_CUERPO,
                text_color=estilo.TEXTO,
                anchor="w",
            ).grid(row=r_idx, column=0, sticky="w", padx=8, pady=4)

            menu = ctk.CTkOptionMenu(
                scroll,
                values=opciones_menu,
                height=32,
                width=260,
                fg_color=estilo.SUPERFICIE_2,
                button_color=estilo.SUPERFICIE_2,
                text_color=estilo.TEXTO,
                font=estilo.FUENTE_CHICO,
            )

            # Pre-seleccionar
            col_previa = next((c for c in cols_detectadas if c.campo_mapeado == campo), None)
            if col_previa is not None:
                menu.set(f"Col {col_previa.indice + 1}: {col_previa.nombre_original}")
            else:
                menu.set(_OPCION_NO_IMPORTAR)

            menu.grid(row=r_idx, column=1, sticky="w", padx=8, pady=4)
            self._menus_mapeo[campo] = menu

            ejemplo_txt = "—"
            if col_previa is not None and col_previa.primer_valor_ejemplo:
                ejemplo_txt = str(col_previa.primer_valor_ejemplo)

            ctk.CTkLabel(
                scroll,
                text=ejemplo_txt,
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_2,
                anchor="w",
            ).grid(row=r_idx, column=2, sticky="w", padx=8, pady=4)

        # Barra inferior
        barra = ctk.CTkFrame(marco, fg_color="transparent")
        barra.grid(row=1, column=0, sticky="ew", pady=(16, 0))

        btn_volver = estilo.boton_secundario(barra, "‹ Volver a Archivo", command=self._volver_paso_1)
        btn_volver.pack(side="left")

        btn_siguiente = estilo.boton_primario(
            barra, "Siguiente: Revisar importación ›", command=self._avanzar_paso_3
        )
        btn_siguiente.pack(side="right")

    def _volver_paso_1(self) -> None:
        self._paso = 1
        self._pintar_paso()

    def _avanzar_paso_3(self) -> None:
        # Construimos el mapeo de columnas
        cols_detectadas = self._inspeccion.columnas_detectadas if self._inspeccion else ()
        mapa_col_indices = {f"Col {c.indice + 1}: {c.nombre_original}": c.indice for c in cols_detectadas}

        nuevo_mapeo: dict[str, int] = {}
        for campo, menu in self._menus_mapeo.items():
            sel = menu.get()
            if sel in mapa_col_indices:
                nuevo_mapeo[campo] = mapa_col_indices[sel]

        if "direccion" not in nuevo_mapeo:
            messagebox.showwarning(
                "Columna requerida",
                "Debés asociar una columna para la Dirección de los departamentos.",
            )
            return

        self._mapeo_columnas = nuevo_mapeo
        self._paso = 3
        self._cargar_y_pintar_paso_3()

    # --- Paso 3: Revisión e importación --------------------------------------

    def _cargar_y_pintar_paso_3(self) -> None:
        if self._servicio_imp is None or self._ruta_archivo is None:
            return

        try:
            prev = self._servicio_imp.previsualizar(
                ruta=self._ruta_archivo,
                nombre_hoja=self._nombre_hoja_seleccionada or "",
                fila_encabezado=self._fila_encabezado_seleccionada,
                mapeo=self._mapeo_columnas,
                ediciones=self._ediciones,
            )
            self._previsualizacion = prev
            resumen, filas = presentar_previsualizacion(prev)
            self._resumen_presentado = resumen
            self._filas_presentadas = filas
            self._pintar_paso_3()
        except ErrorDeNegocio as exc:
            messagebox.showerror("Error de validación", str(exc))
            self._volver_paso_2()
        except Exception as exc:
            messagebox.showerror("Error inesperado", f"Error al generar la vista previa:\n{exc}")
            self._volver_paso_2()

    def _volver_paso_2(self) -> None:
        self._paso = 2
        self._pintar_paso()

    def _pintar_paso_3(self) -> None:
        self._pintar_stepper()
        self._limpiar_cuerpo()

        marco = ctk.CTkFrame(self._cuerpo_paso, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_columnconfigure(1, weight=0)
        marco.grid_rowconfigure(1, weight=1)

        # Columna izquierda: tabla y controles
        col_izq = ctk.CTkFrame(marco, fg_color="transparent")
        col_izq.grid(row=0, column=0, rowspan=2, sticky="nsew")
        col_izq.grid_columnconfigure(0, weight=1)
        col_izq.grid_rowconfigure(1, weight=1)

        # Franja superior: Resumen y filtros
        franja_sup = ctk.CTkFrame(col_izq, fg_color="transparent")
        franja_sup.grid(row=0, column=0, sticky="ew", pady=(0, estilo.GAP))
        franja_sup.grid_columnconfigure(0, weight=1)

        texto_resumen = self._resumen_presentado.texto_resumen if self._resumen_presentado else ""
        lbl_resumen = ctk.CTkLabel(
            franja_sup,
            text=texto_resumen,
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        )
        lbl_resumen.grid(row=0, column=0, sticky="w")

        selector_filtro = ctk.CTkSegmentedButton(
            franja_sup,
            values=list(_FILTROS_TABLA),
            command=self._cambiar_filtro_tabla,
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
        selector_filtro.grid(row=0, column=1, sticky="e")
        selector_filtro.set(self._filtro_tabla)

        # Tabla de previsualización
        self._tabla_prev = Tabla(
            col_izq,
            columnas=[
                Columna("Fila", "numero_fila", 0.6, alineacion="e"),
                Columna("Unidad", "unidad", 2.2),
                Columna("Inquilino", "inquilino", 1.8),
                Columna("Vigencia", "vigencia", 1.8),
                Columna("Cuota mensual", "cuota_mensual", 1.4, alineacion="e"),
                Columna("Estado", "estado_texto", 1.4, es_chip=True),
                Columna("Detalle / Motivo", "motivo_o_detalle", 2.5),
            ],
            al_click_fila=self._al_click_fila_prev,
        )
        self._tabla_prev.grid(row=1, column=0, sticky="nsew")

        self._filtrar_y_mostrar_filas()

        # Barra inferior de acciones
        barra = ctk.CTkFrame(col_izq, fg_color="transparent")
        barra.grid(row=2, column=0, sticky="ew", pady=(16, 0))

        btn_volver = estilo.boton_secundario(barra, "‹ Volver a Columnas", command=self._volver_paso_2)
        btn_volver.pack(side="left")

        texto_btn_imp = (
            self._resumen_presentado.texto_boton_importar
            if self._resumen_presentado
            else "Importar departamentos"
        )
        btn_confirmar = estilo.boton_primario(
            barra,
            texto_btn_imp,
            command=self._confirmar_importacion,
        )
        puede_imp = self._resumen_presentado.puede_importar if self._resumen_presentado else False
        if not puede_imp:
            btn_confirmar.configure(state="disabled")
        btn_confirmar.pack(side="right")

    def _cambiar_filtro_tabla(self, nuevo_filtro: str) -> None:
        self._filtro_tabla = nuevo_filtro
        self._filtrar_y_mostrar_filas()

    def _filtrar_y_mostrar_filas(self) -> None:
        filas = self._filas_presentadas
        if self._filtro_tabla == "Listas":
            filas = [f for f in filas if f.es_importable and not f.tiene_errores]
        elif self._filtro_tabla == "Con errores":
            filas = [f for f in filas if f.tiene_errores]
        elif self._filtro_tabla == "Omitidas":
            filas = [f for f in filas if not f.es_importable and not f.tiene_errores]

        self._tabla_prev.mostrar(filas)

    def _al_click_fila_prev(self, fila_pres: FilaImportacionPresentada) -> None:
        self._abrir_panel(fila_pres.fila_original)

    # --- Panel lateral de 380 px para edición inline -------------------------

    def _abrir_panel(self, fila_orig: FilaPrevisualizacionImportacion) -> None:
        self._cerrar_panel()
        self._fila_en_edicion = fila_orig
        self._panel_edicion = PanelFilaImportacion(
            self._cuerpo_paso.winfo_children()[0],
            fila=fila_orig,
            al_guardar=self._guardar_edicion_fila,
            al_omitir=self._omitir_fila,
            al_cerrar=self._cerrar_panel,
        )
        self._panel_edicion.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(estilo.GAP, 0))

    def _cerrar_panel(self) -> None:
        if self._panel_edicion is not None:
            self._panel_edicion.destroy()
            self._panel_edicion = None
            self._fila_en_edicion = None

    def _guardar_edicion_fila(self, numero_fila: int, valores_editados: dict[str, str | None]) -> None:
        self._ediciones[numero_fila] = EdicionManualFilaImportacion(
            numero_fila=numero_fila,
            valores=valores_editados,
            omitir=False,
        )
        self._cerrar_panel()
        self._cargar_y_pintar_paso_3()

    def _omitir_fila(self, numero_fila: int) -> None:
        self._ediciones[numero_fila] = EdicionManualFilaImportacion(
            numero_fila=numero_fila,
            valores={},
            omitir=True,
        )
        self._cerrar_panel()
        self._cargar_y_pintar_paso_3()

    # --- Confirmación e importación ------------------------------------------

    def _confirmar_importacion(self) -> None:
        if self._servicio_imp is None or self._ruta_archivo is None:
            return

        try:
            res = self._servicio_imp.importar(
                ruta=self._ruta_archivo,
                nombre_hoja=self._nombre_hoja_seleccionada or "",
                fila_encabezado=self._fila_encabezado_seleccionada,
                mapeo=self._mapeo_columnas,
                ediciones=self._ediciones,
            )
            self._resultado_importacion = res
            self._paso = 4
            self._pintar_paso()
        except ErrorDeNegocio as exc:
            messagebox.showerror("No se pudo importar", str(exc))
        except Exception as exc:
            messagebox.showerror("Error durante la importación", f"Ocurrió un error inesperado:\n{exc}")

    # --- Resultado final -----------------------------------------------------

    def _pintar_resultado(self) -> None:
        marco = ctk.CTkFrame(self._cuerpo_paso, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1)

        tarjeta = Tarjeta(marco, titulo="¡Importación completada con éxito!")
        tarjeta.grid(row=0, column=0, sticky="new", pady=(0, estilo.GAP))

        res = getattr(self, "_resultado_importacion", None)
        deptos_creados = res.departamentos_creados if res else 0
        contratos_creados = res.contratos_creados if res else 0
        unidades_omitidas = res.unidades_omitidas if res else 0

        texto_balance = (
            f"Se crearon {deptos_creados} departamentos y {contratos_creados} contratos vigentes en Brickly.\n"
            f"Se omitieron {unidades_omitidas} unidades existentes o duplicadas.\n\n"
            "Recordá que no se importaron pagos ni cuotas anteriores. Podés generarlas ahora desde Cobranzas."
        )

        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=texto_balance,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(0, 24))

        fila_botones = ctk.CTkFrame(tarjeta.cuerpo, fg_color="transparent")
        fila_botones.pack(fill="x")

        btn_cobranzas = estilo.boton_primario(
            fila_botones,
            "Ir a Cobranzas y generar cuotas →",
            command=lambda: self._al_navegar("Cobranzas", None),
        )
        btn_cobranzas.pack(side="left", padx=(0, 12))

        btn_deptos = estilo.boton_secundario(
            fila_botones,
            "Ver mis departamentos",
            command=self._al_volver,
        )
        btn_deptos.pack(side="left", padx=(0, 12))

        btn_reimportar = estilo.boton_secundario(
            fila_botones,
            "Importar otra hoja o archivo",
            command=self._reiniciar_asistente,
        )
        btn_reimportar.pack(side="left")

    def _reiniciar_asistente(self) -> None:
        self._paso = 1
        self._ruta_archivo = None
        self._inspeccion = None
        self._ediciones.clear()
        self._pintar_paso()


# --- Panel lateral de 380 px para edición inline -----------------------------


class PanelFilaImportacion(ctk.CTkFrame):
    """Panel lateral de 380 px para corregir una celda con error o desmarcar la fila."""

    def __init__(
        self,
        master,
        fila: FilaPrevisualizacionImportacion,
        al_guardar: Callable[[int, dict[str, str | None]], None],
        al_omitir: Callable[[int], None],
        al_cerrar: Callable[[], None],
    ) -> None:
        super().__init__(
            master,
            width=380,
            fg_color=estilo.SUPERFICIE,
            corner_radius=estilo.RADIO_TARJETA,
            border_width=1,
            border_color=estilo.BORDE,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._fila = fila
        self._al_guardar = al_guardar
        self._al_omitir = al_omitir
        self._al_cerrar = al_cerrar

        # Cabecera
        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        cabecera.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            cabecera,
            text=f"Fila {fila.numero_fila} — {fila.unidad_texto}",
            font=estilo.FUENTE_SUBTITULO,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            cabecera,
            text="✕",
            width=28,
            height=28,
            fg_color="transparent",
            hover_color=estilo.SUPERFICIE_2,
            text_color=estilo.TEXTO_2,
            command=al_cerrar,
        ).grid(row=0, column=1, sticky="e")

        # Scrollable Form
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=8)
        scroll.grid_columnconfigure(0, weight=1)

        # Campos
        self._campo_dir = Campo(scroll, "Dirección", fila.direccion)
        self._campo_dir.pack(fill="x", pady=4)

        fila_depto = ctk.CTkFrame(scroll, fg_color="transparent")
        fila_depto.pack(fill="x", pady=4)
        fila_depto.grid_columnconfigure(0, weight=1)
        fila_depto.grid_columnconfigure(1, weight=1)

        self._campo_piso = Campo(fila_depto, "Piso", fila.piso or "")
        self._campo_piso.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._campo_depto = Campo(fila_depto, "Depto", fila.depto or "")
        self._campo_depto.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._campo_inq = Campo(scroll, "Inquilino", fila.inquilino_nombre or "")
        self._campo_inq.pack(fill="x", pady=4)

        self._campo_tel = Campo(scroll, "Teléfono inquilino", fila.inquilino_telefono or "")
        self._campo_tel.pack(fill="x", pady=4)

        self._campo_email = Campo(scroll, "Email inquilino", fila.inquilino_email or "")
        self._campo_email.pack(fill="x", pady=4)

        fila_fechas = ctk.CTkFrame(scroll, fg_color="transparent")
        fila_fechas.pack(fill="x", pady=4)
        fila_fechas.grid_columnconfigure(0, weight=1)
        fila_fechas.grid_columnconfigure(1, weight=1)

        from brickly.ui.formato import formatear_fecha

        inicio_txt = formatear_fecha(fila.fecha_inicio) if fila.fecha_inicio else ""
        self._campo_inicio = Campo(fila_fechas, "Inicio contrato", inicio_txt)
        self._campo_inicio.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        fin_txt = (
            formatear_fecha(fila.fecha_fin_informativa) if fila.fecha_fin_informativa else ""
        )
        self._campo_fin = Campo(fila_fechas, "Fin contrato", fin_txt)
        self._campo_fin.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        cuota_txt = str(fila.monto_inicial_centavos // 100) if fila.monto_inicial_centavos else ""
        self._campo_cuota = Campo(scroll, "Cuota mensual ($)", cuota_txt)
        self._campo_cuota.pack(fill="x", pady=4)

        # Botones inferiores del panel
        barra_inferior = ctk.CTkFrame(self, fg_color="transparent")
        barra_inferior.grid(row=2, column=0, sticky="ew", padx=16, pady=16)

        btn_omitir = estilo.boton_secundario(
            barra_inferior,
            "Omitir fila",
            command=lambda: self._al_omitir(self._fila.numero_fila),
        )
        btn_omitir.pack(side="left")

        btn_guardar = estilo.boton_primario(
            barra_inferior,
            "Aplicar corrección",
            command=self._guardar,
        )
        btn_guardar.pack(side="right")

    def _guardar(self) -> None:
        ediciones: dict[str, str | None] = {
            "direccion": self._campo_dir.valor.strip() or None,
            "piso": self._campo_piso.valor.strip() or None,
            "depto": self._campo_depto.valor.strip() or None,
            "nombre_inquilino": self._campo_inq.valor.strip() or None,
            "telefono_inquilino": self._campo_tel.valor.strip() or None,
            "email_inquilino": self._campo_email.valor.strip() or None,
            "fecha_inicio": self._campo_inicio.valor.strip() or None,
            "fecha_fin": self._campo_fin.valor.strip() or None,
            "monto_inicial_centavos": self._campo_cuota.valor.strip() or None,
        }
        self._al_guardar(self._fila.numero_fila, ediciones)
