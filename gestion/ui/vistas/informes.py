"""Pantalla Informes (spec §3.6 — H4): exportaciones CSV y respaldo de la base.

Cuatro cards con acción: Estado de cuenta · Cobranzas del mes · Morosos de hoy
(CSV) y Respaldo de la base (`.sqlite3`). Exportar abre el diálogo nativo y el
archivo lo escribe `ServicioInformes` (la UI no toca SQL ni arma CSV); un
resultado vacío jamás genera un archivo: el botón queda deshabilitado con su
motivo, y el servicio igual lo bloquea como red de seguridad.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from gestion.aplicacion.contenedor import Servicios
from gestion.aplicacion.informes import EstadoInformes
from gestion.dominio.errores import ErrorDeNegocio
from gestion.ui import estilo
from gestion.ui.componentes.tarjeta import Tarjeta
from gestion.ui.formato import MESES, formatear_fecha, formatear_periodo
from gestion.ui.vistas.base import VistaBase


def nombre_estado_cuenta(hoy: date) -> str:
    return f"estado-de-cuenta-{hoy.isoformat()}.csv"


def nombre_cobranzas(anio: int, mes: int) -> str:
    return f"cobranzas-{MESES[mes - 1]}-{anio}.csv"


def nombre_morosos(hoy: date) -> str:
    return f"morosos-{hoy.isoformat()}.csv"


def nombre_respaldo(hoy: date) -> str:
    return f"GestionDepartamentos-{hoy.isoformat()}.sqlite3"


def texto_ultimo_respaldo(ultimo: date | None) -> str:
    if ultimo is None:
        return "Último respaldo: Nunca"
    return f"Último respaldo: {formatear_fecha(ultimo)}"


def escritorio_default() -> str | None:
    """Default del diálogo nativo: Escritorio si existe, si no la home."""
    escritorio = Path.home() / "Desktop"
    if escritorio.is_dir():
        return str(escritorio)
    return str(Path.home()) if Path.home().is_dir() else None


class VistaInformes(VistaBase):
    def __init__(self, master, servicios: Servicios):
        super().__init__(master, titulo="Informes")
        self._servicios = servicios
        self._estado: EstadoInformes | None = None
        self._botones: dict[str, ctk.CTkButton] = {}

        self._area = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        self._area.grid(row=0, column=0, sticky="nsew")
        self._area.grid_columnconfigure(0, weight=1)

        self._cargar()

    # --- render ---------------------------------------------------------------

    def _cargar(self) -> None:
        try:
            self._estado = self._servicios.informes.estado()
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return
        self._render()

    def _render(self) -> None:
        for hijo in self._area.winfo_children():
            hijo.destroy()
        self._botones.clear()
        estado = self._estado
        assert estado is not None

        periodo = formatear_periodo(estado.anio, estado.mes)
        self._card(
            fila=0,
            clave="estado-cuenta",
            titulo="Estado de cuenta por departamento",
            descripcion="Todas las cuotas con pagado, mora y saldo de cada unidad.",
            texto_boton="Exportar",
            habilitado=estado.hay_cuotas,
            motivo=None if estado.hay_cuotas else "No hay cuotas generadas todavía.",
            nombre_default=nombre_estado_cuenta(estado.fecha_calculo),
            extension=".csv",
            mensaje_exito=lambda ruta: f"Se exportó a {ruta}",
            ejecutar=lambda ruta: self._servicios.informes.exportar_estado_cuenta(ruta),
        )
        self._card(
            fila=1,
            clave="cobranzas",
            titulo="Cobranzas del mes",
            descripcion=f"Las cuotas de {periodo} con su estado de cobro.",
            texto_boton="Exportar",
            habilitado=estado.cobranzas_generadas,
            motivo=(
                None
                if estado.cobranzas_generadas
                else f"No hay cuotas generadas de {periodo}."
            ),
            nombre_default=nombre_cobranzas(estado.anio, estado.mes),
            extension=".csv",
            mensaje_exito=lambda ruta: f"Se exportó a {ruta}",
            ejecutar=lambda ruta: self._servicios.informes.exportar_cobranzas_del_mes(
                ruta
            ),
        )
        self._card(
            fila=2,
            clave="morosos",
            titulo="Morosos de hoy",
            descripcion="Todas las cuotas vencidas impagas, con la mora al día de hoy.",
            texto_boton="Exportar",
            habilitado=estado.hay_morosos,
            motivo=None if estado.hay_morosos else "No hay morosos hoy.",
            nombre_default=nombre_morosos(estado.fecha_calculo),
            extension=".csv",
            mensaje_exito=lambda ruta: f"Se exportó a {ruta}",
            ejecutar=lambda ruta: self._servicios.informes.exportar_morosos(ruta),
        )
        self._card(
            fila=3,
            clave="respaldo",
            titulo="Respaldo de la base",
            descripcion="Copia completa de la base en un archivo .sqlite3.",
            texto_boton="Respaldar",
            habilitado=True,
            motivo=None,
            nombre_default=nombre_respaldo(estado.fecha_calculo),
            extension=".sqlite3",
            mensaje_exito=lambda ruta: f"Respaldo guardado en {ruta}",
            ejecutar=lambda ruta: self._servicios.informes.respaldar(ruta),
            extra=texto_ultimo_respaldo(estado.ultimo_respaldo),
        )

    def _card(
        self,
        fila: int,
        clave: str,
        titulo: str,
        descripcion: str,
        texto_boton: str,
        habilitado: bool,
        motivo: str | None,
        nombre_default: str,
        extension: str,
        mensaje_exito,
        ejecutar,
        extra: str | None = None,
    ) -> None:
        tarjeta = Tarjeta(self._area)
        tarjeta.grid(
            row=fila, column=0, sticky="ew", pady=(0, 12) if fila else 0
        )
        cuerpo = tarjeta.cuerpo
        cuerpo.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            cuerpo,
            text=titulo,
            font=estilo.FUENTE_SECCION,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            cuerpo,
            text=descripcion,
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        if motivo:
            ctk.CTkLabel(
                cuerpo,
                text=motivo,
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_3,
                anchor="w",
            ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        if extra:
            ctk.CTkLabel(
                cuerpo,
                text=extra,
                font=estilo.FUENTE_CHICO,
                text_color=estilo.TEXTO_3,
                anchor="w",
            ).grid(row=3, column=0, sticky="w", pady=(4, 0))

        boton = estilo.boton_secundario(
            cuerpo,
            texto_boton,
            command=lambda: self._exportar(
                clave, nombre_default, extension, mensaje_exito, ejecutar
            ),
        )
        if not habilitado:
            boton.configure(state="disabled")
        boton.grid(row=0, column=1, rowspan=4, sticky="e", padx=(16, 0))
        self._botones[clave] = boton

    # --- exportación ----------------------------------------------------------

    def _exportar(
        self,
        clave: str,
        nombre_default: str,
        extension: str,
        mensaje_exito,
        ejecutar,
    ) -> None:
        boton = self._botones.get(clave)
        if boton is None:
            return
        boton.configure(text="Exportando…", state="disabled")
        self.update_idletasks()
        try:
            ruta = filedialog.asksaveasfilename(
                parent=self,
                title="Guardar como",
                initialdir=escritorio_default(),
                initialfile=nombre_default,
                defaultextension=extension,
                filetypes=(
                    [("SQLite", "*.sqlite3")]
                    if extension == ".sqlite3"
                    else [("CSV", "*.csv")]
                ),
            )
            if not ruta:
                return
            ejecutar(ruta)
        except (ErrorDeNegocio, OSError) as error:
            self.mostrar_banner("error", f"No se pudo guardar: {error}")
        else:
            self.mostrar_banner("exito", mensaje_exito(ruta))
        finally:
            self._cargar()
