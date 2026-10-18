"""Tabla (spec §2.4) — el componente clave; CTk no trae tabla, la armamos con grid.

Contrato de uso:
- `mostrar(filas)` recibe DTOs de `aplicacion` (nunca dicts crudos). Cada
  columna declara su `campo` (atributo del DTO) y la fila necesita `id` si hay
  `al_click_fila`. La tabla no consulta nada: anti N+1 por diseño.
- El encabezado vive dentro del área scrolleable: `CTkScrollableFrame` reserva
  siempre su scrollbar a la derecha y un encabezado afuera de ese marco quedaría
  desalineado al scrollear.
"""

from dataclasses import dataclass
from typing import Any, Callable

import customtkinter as ctk

from gestion.ui import estilo
from gestion.ui.componentes.chip import ChipEstado


@dataclass(frozen=True)
class Columna:
    """`formato` recibe valores no-None; `color` recibe el valor crudo (a veces None)."""

    titulo: str
    campo: str
    peso: int | float
    alineacion: str = "w"  # "w" izq · "e" der (numéricas)
    formato: Callable[[Any], str] | None = None
    color: Callable[[Any], Any] | None = None  # color de texto o None
    texto_none: str = "—"  # Inquilino usa "(sin contrato)"
    es_chip: bool = False  # Si True y valor != None, pinta ChipEstado(variante=valor)
    texto_accion: str | None = None  # Si se define, pinta botón de fila (ALTO_BOTON_FILA)
    al_accion: Callable[[int], None] | None = None
    ancho_accion: int | None = None  # Ancho del botón de acción (default 84; ✎/✕ usan 40)


def truncar(texto: str, limite: int = 40) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def _todos_los_widgets(raiz: ctk.CTkBaseClass) -> list:
    """Devuelve `raiz` y todos sus descendientes para enlazar hover y click."""
    resultado = [raiz]
    for hijo in raiz.winfo_children():
        resultado.extend(_todos_los_widgets(hijo))
    return resultado


class Tabla(ctk.CTkFrame):
    UMBRAL_PAGINACION = 300
    FILAS_POR_PAGINA = 50

    def __init__(
        self,
        master,
        columnas: list[Columna],
        al_click_fila: Callable[[int], None] | None = None,
        mensaje_vacio: str = "No hay nada para mostrar",
        cta_vacio: tuple[str, Callable[[], None]] | None = None,
    ):
        super().__init__(master, fg_color="transparent")
        self._columnas = list(columnas)
        self._al_click_fila = al_click_fila
        self._mensaje_vacio = mensaje_vacio
        self._cta_vacio = cta_vacio
        self._filas: list = []
        self._pagina = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        self._cuerpo.grid(row=0, column=0, sticky="nsew")
        self._cuerpo.grid_columnconfigure(0, weight=1)
        self._cuerpo.grid_rowconfigure(0, weight=1)

        self._contenido = ctk.CTkScrollableFrame(self._cuerpo, fg_color="transparent")
        self._vacio = self._crear_vacio()
        self._pie = ctk.CTkFrame(self, fg_color="transparent")

        self.cambiar_vacio(self._mensaje_vacio, self._cta_vacio)
        self.mostrar([])

    # --- API -----------------------------------------------------------------

    def cambiar_vacio(self, mensaje: str, cta: tuple[str, Callable[[], None]] | None = None) -> None:
        """El estado vacío cambia según contexto: sin datos vs. sin resultados."""
        self._mensaje_vacio = mensaje
        self._vacio_label.configure(text=mensaje)
        for hijo in self._vacio_cta.winfo_children():
            hijo.destroy()
        if cta:
            texto, accion = cta
            estilo.boton_secundario(self._vacio_cta, texto, command=accion).pack()

    def mostrar(self, filas: list) -> None:
        """Destruye y reconstruye: una llamada = la tabla completa."""
        self._filas = list(filas)
        self._pagina = 0
        if self._filas:
            self._vacio.grid_forget()
            self._contenido.grid(row=0, column=0, sticky="nsew")
            self._render()
        else:
            self._contenido.grid_forget()
            self._vacio.grid(row=0, column=0, sticky="nsew")
            self._pie.grid_forget()

    # --- construcción --------------------------------------------------------

    def _crear_vacio(self) -> ctk.CTkFrame:
        marco = ctk.CTkFrame(self._cuerpo, fg_color="transparent")
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(0, weight=1)

        interior = ctk.CTkFrame(marco, fg_color="transparent")
        interior.grid(row=0, column=0)

        self._vacio_label = ctk.CTkLabel(
            interior,
            text=self._mensaje_vacio,
            font=estilo.FUENTE_CUERPO,
            text_color=estilo.TEXTO_2,
        )
        self._vacio_label.pack()

        self._vacio_cta = ctk.CTkFrame(interior, fg_color="transparent")
        self._vacio_cta.pack(pady=(12, 0))

        return marco

    def _render(self) -> None:
        for hijo in self._contenido.winfo_children():
            hijo.destroy()

        paginado = len(self._filas) > self.UMBRAL_PAGINACION
        if paginado:
            inicio = self._pagina * self.FILAS_POR_PAGINA
            visibles = self._filas[inicio : inicio + self.FILAS_POR_PAGINA]
        else:
            visibles = self._filas

        self._crear_encabezado()

        for indice, fila in enumerate(visibles):
            self._crear_fila(fila, 2 + indice * 2)
            if indice < len(visibles) - 1:
                self._crear_divisor(3 + indice * 2)

        if paginado:
            self._crear_pie()
        else:
            self._pie.grid_forget()

    def _configurar_columnas(self, marco: ctk.CTkFrame) -> None:
        for indice, columna in enumerate(self._columnas):
            peso = max(1, round(columna.peso * 10))
            marco.grid_columnconfigure(indice, weight=peso)
            if columna.alineacion == "e" and columna.texto_accion is None:
                # §5: la columna de montos banca $ 99.999.999,99 aunque apriete el ancho.
                marco.grid_columnconfigure(indice, minsize=110)

    def _crear_encabezado(self) -> None:
        marco = ctk.CTkFrame(self._contenido, fg_color="transparent", height=estilo.ALTO_ENCABEZADO_TABLA)
        marco.grid(row=0, column=0, sticky="ew")
        self._configurar_columnas(marco)
        for indice, columna in enumerate(self._columnas):
            ctk.CTkLabel(
                marco,
                text=columna.titulo,
                font=estilo.FUENTE_CHICO_NEGRITA,
                text_color=estilo.TEXTO_2,
                anchor=columna.alineacion,
            ).grid(row=0, column=indice, sticky="ew", padx=estilo.GAP // 2)
        self._crear_divisor(1)

    def _crear_divisor(self, fila_grid: int) -> None:
        ctk.CTkFrame(
            self._contenido, height=1, fg_color=estilo.BORDE, corner_radius=0,
        ).grid(row=fila_grid, column=0, sticky="ew")

    def _crear_fila(self, fila, fila_grid: int) -> None:
        clicable = self._al_click_fila is not None
        marco = ctk.CTkFrame(
            self._contenido,
            fg_color=estilo.SUPERFICIE,
            corner_radius=0,
            height=estilo.ALTO_FILA,
        )
        marco.grid(row=fila_grid, column=0, sticky="ew")
        marco.grid_rowconfigure(0, weight=1)
        self._configurar_columnas(marco)

        widgets_accion: set = set()
        for indice, columna in enumerate(self._columnas):
            if columna.texto_accion is not None:
                celda = ctk.CTkFrame(marco, fg_color="transparent")
                celda.grid(row=0, column=indice, sticky="ew", padx=estilo.GAP // 2)
                lado = "right" if columna.alineacion == "e" else "left"
                identificador = getattr(fila, "id")
                comando = (
                    (lambda fid=identificador, cb=columna.al_accion: cb(fid))
                    if columna.al_accion is not None
                    else None
                )
                boton = ctk.CTkButton(
                    celda,
                    text=columna.texto_accion,
                    command=comando,
                    height=estilo.ALTO_BOTON_FILA,
                    width=columna.ancho_accion or 84,
                    corner_radius=estilo.RADIO_BOTON,
                    fg_color=estilo.SUPERFICIE,
                    hover_color=estilo.SUPERFICIE_2,
                    text_color=estilo.TEXTO,
                    border_width=1,
                    border_color=estilo.BORDE,
                    font=estilo.FUENTE_CHICO,
                )
                boton.pack(side=lado)
                widgets_accion.update(_todos_los_widgets(boton))
                continue

            valor = getattr(fila, columna.campo)
            if columna.es_chip and valor is not None:
                celda = ctk.CTkFrame(marco, fg_color="transparent")
                celda.grid(row=0, column=indice, sticky="ew", padx=estilo.GAP // 2)
                lado = "right" if columna.alineacion == "e" else "left"
                ChipEstado(celda, variante=str(valor)).pack(side=lado)
            else:
                texto = self._texto(columna, valor)
                color = columna.color(valor) if columna.color else None
                etiqueta = ctk.CTkLabel(
                    marco,
                    text=texto,
                    font=estilo.FUENTE_CUERPO,
                    text_color=color or estilo.TEXTO,
                    anchor=columna.alineacion,
                )
                etiqueta.grid(row=0, column=indice, sticky="ew", padx=estilo.GAP // 2)

        widgets = _todos_los_widgets(marco)

        def entrar(_evento):
            marco.configure(fg_color=estilo.SUPERFICIE_2)

        def salir(_evento):
            marco.configure(fg_color=estilo.SUPERFICIE)

        for widget in widgets:
            widget.bind("<Enter>", entrar)
            widget.bind("<Leave>", salir)

        if clicable:
            identificador = getattr(fila, "id")
            manejador = lambda _evento: self._al_click_fila(identificador)  # noqa: E731
            for widget in widgets:
                if widget in widgets_accion:
                    continue
                widget.bind("<Button-1>", manejador)
                try:
                    widget.configure(cursor="hand2")
                except Exception:  # algunos widgets internos de CTk no aceptan cursor
                    pass

    def _texto(self, columna: Columna, valor) -> str:
        if valor is None:
            return columna.texto_none
        texto = columna.formato(valor) if columna.formato else str(valor)
        return truncar(texto)

    # --- paginación (§2.4: >300 filas → 50 por página) ------------------------

    def _total_paginas(self) -> int:
        return (len(self._filas) + self.FILAS_POR_PAGINA - 1) // self.FILAS_POR_PAGINA

    def _crear_pie(self) -> None:
        for hijo in self._pie.winfo_children():
            hijo.destroy()

        estilo_pie = dict(
            width=28, height=28, corner_radius=estilo.RADIO_BOTON,
            fg_color="transparent", hover_color=estilo.SUPERFICIE_2,
            text_color=estilo.TEXTO_2, font=estilo.FUENTE_CHICO,
        )
        anterior = ctk.CTkButton(self._pie, text="‹", command=lambda: self._ir_pagina(-1), **estilo_pie)
        anterior.pack(side="left")
        anterior.configure(state="normal" if self._pagina > 0 else "disabled")

        ctk.CTkLabel(
            self._pie, text=f"{self._pagina + 1}/{self._total_paginas()}",
            font=estilo.FUENTE_CHICO, text_color=estilo.TEXTO_2,
        ).pack(side="left", padx=8)

        siguiente = ctk.CTkButton(self._pie, text="›", command=lambda: self._ir_pagina(1), **estilo_pie)
        siguiente.pack(side="left")
        siguiente.configure(state="normal" if self._pagina < self._total_paginas() - 1 else "disabled")

        self._pie.grid(row=1, column=0, pady=(8, 0))

    def _ir_pagina(self, delta: int) -> None:
        pagina = min(max(self._pagina + delta, 0), self._total_paginas() - 1)
        if pagina != self._pagina:
            self._pagina = pagina
            self._render()
