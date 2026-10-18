"""Pantalla Configuración (spec §3.7 — H4): predeterminados, admin y respaldo.

Guardado explícito con `[ Guardar cambios ]`: se parsean los campos, se llama a
`ServicioConfiguracion.guardar` (valida y persiste todo junto) y los errores de
validación vuelven campo por campo (`ErrorDeValidacion.campo`). Cambiar un
predeterminado no toca contratos existentes — la ayuda de los campos lo dice y
solo aplica a contratos nuevos (lo consume `predeterminados_contrato`).
"""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from gestion import FECHA_BUILD, VERSION
from gestion.aplicacion.configuracion import (
    REDONDEO_CIEN_PESOS,
    REDONDEO_CENTAVOS,
    DatosConfiguracion,
)
from gestion.aplicacion.contenedor import Servicios
from gestion.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from gestion.ui import estilo
from gestion.ui.componentes.formulario import Campo
from gestion.ui.componentes.tarjeta import Tarjeta
from gestion.ui.formato import formatear_porcentaje, parsear_porcentaje
from gestion.ui.vistas.informes import nombre_respaldo
from gestion.ui.vistas.base import VistaBase

_AYUDA_PREDETERMINADOS = (
    "Se usa al crear contratos nuevos; cada contrato puede pisarlo."
)
_ETIQUETA_REDONDEO = {REDONDEO_CENTAVOS: "Centavos", REDONDEO_CIEN_PESOS: "$ 100"}
_REDONDEO_POR_ETIQUETA = {v: k for k, v in _ETIQUETA_REDONDEO.items()}


def texto_tasa_input(bp: int) -> str:
    """`2,00` (sin `%`) para el input; el parseo lo hace `parsear_porcentaje`."""
    return formatear_porcentaje(bp).removesuffix(" %")


class VistaConfiguracion(VistaBase):
    def __init__(self, master, servicios: Servicios):
        super().__init__(master, titulo="Configuración")
        self._servicios = servicios
        self._campos: dict[str, Campo] = {}

        estilo.boton_primario(
            self._acciones, "Guardar cambios", command=self._guardar
        ).pack(side="left")

        marco = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1, uniform="col")
        marco.grid_columnconfigure(1, weight=1, uniform="col")

        self._pintar_predeterminados(marco)
        self._pintar_admin(marco)
        self._pintar_datos(marco)
        self._pintar_acerca(marco)

        self._cargar()

    # --- cards ----------------------------------------------------------------

    def _pintar_predeterminados(self, marco) -> None:
        tarjeta = Tarjeta(marco, titulo="Predeterminados de contrato")
        tarjeta.grid(row=0, column=0, sticky="nsew", padx=(0, estilo.GAP))
        cuerpo = tarjeta.cuerpo
        cuerpo.grid_columnconfigure(0, weight=1)
        cuerpo.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            cuerpo,
            text=_AYUDA_PREDETERMINADOS,
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_3,
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self._campo("vencimiento_dia", cuerpo, "Día de vencimiento", 0, 0)
        self._campo("gracia_dias", cuerpo, "Días de gracia", 1, 0)
        self._campo("mora_bp", cuerpo, "Tasa de mora mensual %", 0, 1)
        self._campo(
            "redondeo_centavos",
            cuerpo,
            "Redondeo de cuota",
            1,
            1,
            tipo="opciones",
            valores=list(_ETIQUETA_REDONDEO.values()),
        )

    def _pintar_admin(self, marco) -> None:
        tarjeta = Tarjeta(marco, titulo="Datos del administrador")
        tarjeta.grid(row=0, column=1, sticky="nsew")
        cuerpo = tarjeta.cuerpo

        self._campo(
            "admin_nombre", cuerpo, "Nombre", 0, 0,
            ayuda="Para recibos y exportaciones futuras.",
        )
        self._campo("admin_telefono", cuerpo, "Teléfono", 1, 0)
        self._campo("admin_email", cuerpo, "Email", 2, 0)

    def _pintar_datos(self, marco) -> None:
        tarjeta = Tarjeta(marco, titulo="Datos y respaldo")
        tarjeta.grid(
            row=1, column=0, sticky="nsew", padx=(0, estilo.GAP), pady=(estilo.GAP, 0)
        )
        cuerpo = tarjeta.cuerpo
        cuerpo.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            cuerpo,
            text="Base de datos",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ruta = self._servicios.ruta_base or "—"
        ctk.CTkLabel(
            cuerpo,
            text=ruta,
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO,
            anchor="w",
            justify="left",
            wraplength=420,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        estilo.boton_secundario(
            cuerpo, "Abrir carpeta", command=self._abrir_carpeta,
            height=estilo.ALTO_BOTON_FILA,
        ).grid(row=1, column=1, sticky="e", padx=(12, 0))

        self._campo(
            "respaldo_recordatorio_dias",
            cuerpo,
            "Recordar respaldo cada (días)",
            2,
            0,
            ayuda="Pasados estos días, el Panel te recuerda respaldar.",
        )

        self._boton_respaldo = estilo.boton_secundario(
            cuerpo, "Hacer respaldo ahora", command=self._respaldar
        )
        self._boton_respaldo.grid(row=4, column=0, sticky="w", pady=(12, 0))

    def _pintar_acerca(self, marco) -> None:
        tarjeta = Tarjeta(marco, titulo="Acerca de")
        tarjeta.grid(row=1, column=1, sticky="nsew", pady=(estilo.GAP, 0))
        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=f"Gestión de Departamentos {VERSION}",
            font=estilo.FUENTE_CUERPO_NEGRITA,
            text_color=estilo.TEXTO,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=f"Build {FECHA_BUILD}",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _campo(
        self,
        clave: str,
        cuerpo,
        etiqueta: str,
        fila: int,
        columna: int,
        ayuda: str | None = None,
        tipo: str = "texto",
        valores: list[str] | None = None,
    ) -> Campo:
        campo = Campo(cuerpo, etiqueta, ayuda=ayuda, tipo=tipo, valores=valores)
        campo.grid(
            row=fila + 1,
            column=columna,
            sticky="ew",
            padx=(0, 12) if columna == 0 and tipo == "texto" else 0,
            pady=(0, 12),
        )
        self._campos[clave] = campo
        return campo

    # --- carga / guardado -----------------------------------------------------

    def _cargar(self) -> None:
        configuracion = self._servicios.configuracion.cargar()
        self._campos["vencimiento_dia"].poner_valor(str(configuracion.dia_vencimiento))
        self._campos["gracia_dias"].poner_valor(str(configuracion.dias_gracia))
        self._campos["mora_bp"].poner_valor(texto_tasa_input(configuracion.tasa_mora_bp))
        self._campos["redondeo_centavos"].poner_valor(
            _ETIQUETA_REDONDEO[configuracion.redondeo_centavos]
        )
        self._campos["respaldo_recordatorio_dias"].poner_valor(
            str(configuracion.respaldo_recordatorio_dias)
        )
        self._campos["admin_nombre"].poner_valor(configuracion.admin_nombre or "")
        self._campos["admin_telefono"].poner_valor(configuracion.admin_telefono or "")
        self._campos["admin_email"].poner_valor(configuracion.admin_email or "")

    def _guardar(self) -> None:
        for campo in self._campos.values():
            campo.limpiar_error()

        try:
            dia = int(self._campos["vencimiento_dia"].valor().strip())
            gracia = int(self._campos["gracia_dias"].valor().strip())
            recordatorio = int(
                self._campos["respaldo_recordatorio_dias"].valor().strip()
            )
        except ValueError:
            self._error_entero()
            return

        try:
            tasa_bp = parsear_porcentaje(self._campos["mora_bp"].valor())
        except ValueError:
            campo = self._campos["mora_bp"]
            campo.mostrar_error("Porcentaje inválido")
            campo.enfocar()
            return

        datos = DatosConfiguracion(
            dia_vencimiento=dia,
            dias_gracia=gracia,
            tasa_mora_bp=tasa_bp,
            redondeo_centavos=_REDONDEO_POR_ETIQUETA[
                self._campos["redondeo_centavos"].valor()
            ],
            respaldo_recordatorio_dias=recordatorio,
            admin_nombre=self._campos["admin_nombre"].valor().strip() or None,
            admin_telefono=self._campos["admin_telefono"].valor().strip() or None,
            admin_email=self._campos["admin_email"].valor().strip() or None,
        )

        try:
            self._servicios.configuracion.guardar(datos)
        except ErrorDeValidacion as error:
            campo = self._campos.get(error.campo or "")
            if campo is not None:
                campo.mostrar_error(str(error))
                campo.enfocar()
            else:
                self.mostrar_banner("error", str(error))
            return
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return

        self.mostrar_banner("exito", "Cambios guardados.")

    def _error_entero(self) -> None:
        for clave in ("vencimiento_dia", "gracia_dias", "respaldo_recordatorio_dias"):
            campo = self._campos[clave]
            try:
                int(campo.valor().strip())
            except ValueError:
                campo.mostrar_error("Escribí un número entero.")
                campo.enfocar()
                return

    # --- respaldo -------------------------------------------------------------

    def _abrir_carpeta(self) -> None:
        ruta = self._servicios.ruta_base
        if not ruta:
            return
        carpeta = Path(ruta).parent
        if not carpeta.is_dir():
            self.mostrar_banner("error", f"No existe la carpeta {carpeta}.")
            return
        try:
            os.startfile(carpeta)
        except OSError as error:
            self.mostrar_banner("error", f"No se pudo abrir la carpeta: {error}")

    def _respaldar(self) -> None:
        self._boton_respaldo.configure(text="Respaldando…", state="disabled")
        self.update_idletasks()
        try:
            nombre_default = nombre_respaldo(self._servicios.configuracion.hoy())
            ruta = filedialog.asksaveasfilename(
                parent=self,
                title="Guardar respaldo",
                initialfile=nombre_default,
                defaultextension=".sqlite3",
                filetypes=[("SQLite", "*.sqlite3")],
            )
            if not ruta:
                return
            self._servicios.informes.respaldar(ruta)
        except OSError as error:
            self.mostrar_banner("error", f"No se pudo guardar: {error}")
        else:
            self.mostrar_banner("exito", f"Respaldo guardado en {ruta}")
        finally:
            self._boton_respaldo.configure(text="Hacer respaldo ahora", state="normal")
