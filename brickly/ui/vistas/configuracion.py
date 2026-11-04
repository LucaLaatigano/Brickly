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
import queue
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from brickly import FECHA_BUILD, VERSION
from brickly.aplicacion.configuracion import (
    REDONDEO_CIEN_PESOS,
    REDONDEO_CENTAVOS,
    DatosConfiguracion,
)
from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.sincronizacion_ipc import (
    EstadoTokenIpc,
    ResultadoPruebaIpc,
)
from brickly.dominio.errores import ErrorDeNegocio, ErrorDeValidacion
from brickly.ui import estilo
from brickly.ui.componentes.formulario import Campo
from brickly.ui.componentes.tarjeta import Tarjeta
from brickly.ui.formato import (
    formatear_fecha,
    formatear_periodo,
    formatear_porcentaje,
    parsear_porcentaje,
)
from brickly.ui.vistas.informes import nombre_respaldo
from brickly.ui.vistas.base import VistaBase

_AYUDA_PREDETERMINADOS = (
    "Se usa al crear contratos nuevos; cada contrato puede pisarlo."
)
_ETIQUETA_REDONDEO = {REDONDEO_CENTAVOS: "Centavos", REDONDEO_CIEN_PESOS: "$ 100"}
_REDONDEO_POR_ETIQUETA = {v: k for k, v in _ETIQUETA_REDONDEO.items()}


def texto_tasa_input(bp: int) -> str:
    """`2,00` (sin `%`) para el input; el parseo lo hace `parsear_porcentaje`."""
    return formatear_porcentaje(bp).removesuffix(" %")


def texto_estado_token_indec(estado: EstadoTokenIpc) -> str:
    """Resumen legible del estado del token y su vencimiento para la card INDEC."""
    if not estado.configurado:
        return "Estado: Sin configurar"
    if estado.vencido:
        sufijo = (
            f" · Venció el {formatear_fecha(estado.fecha_vencimiento)}"
            if estado.fecha_vencimiento is not None
            else ""
        )
        return f"Estado: Token vencido ({estado.token_enmascarado}){sufijo}"
    partes = [f"Estado: Configurado ({estado.token_enmascarado})"]
    if estado.fecha_vencimiento is not None:
        partes.append(f"Vence el {formatear_fecha(estado.fecha_vencimiento)}")
    if estado.ultima_sincronizacion is not None:
        partes.append(
            f"Última sincronización: {formatear_fecha(estado.ultima_sincronizacion)}"
        )
    return " · ".join(partes)


def texto_resultado_prueba_indec(resultado: ResultadoPruebaIpc) -> str:
    """Mensaje de éxito tras probar conexión con `api.indec.gob.ar`."""
    if (
        resultado.ultimo_periodo is not None
        and resultado.ultima_variacion_bp is not None
    ):
        periodo = formatear_periodo(*resultado.ultimo_periodo)
        variacion = formatear_porcentaje(resultado.ultima_variacion_bp)
        return f"{resultado.mensaje} Último período: {periodo} ({variacion})."
    return resultado.mensaje


class VistaConfiguracion(VistaBase):
    def __init__(self, master, servicios: Servicios):
        super().__init__(master, titulo="Configuración")
        self._servicios = servicios
        self._campos: dict[str, Campo] = {}
        self._campo_token_indec: Campo | None = None
        self._label_estado_indec: ctk.CTkLabel | None = None
        self._boton_guardar_token: ctk.CTkButton | None = None
        self._boton_probar_indec: ctk.CTkButton | None = None
        self._boton_borrar_token: ctk.CTkButton | None = None
        self._probando_indec = False

        estilo.boton_primario(
            self._acciones, "Guardar cambios", command=self._guardar
        ).pack(side="left")

        marco = ctk.CTkScrollableFrame(self.cuerpo, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="nsew")
        marco.grid_columnconfigure(0, weight=1, uniform="col")
        marco.grid_columnconfigure(1, weight=1, uniform="col")

        self._pintar_predeterminados(marco)
        self._pintar_admin(marco)
        self._pintar_datos(marco)
        self._pintar_indec(marco)
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
            ayuda="Para constancias de pago y exportaciones.",
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

    def _pintar_indec(self, marco) -> None:
        tarjeta = Tarjeta(marco, titulo="INDEC")
        tarjeta.grid(row=1, column=1, sticky="nsew", pady=(estilo.GAP, 0))
        cuerpo = tarjeta.cuerpo
        cuerpo.grid_columnconfigure(0, weight=1)

        self._label_estado_indec = ctk.CTkLabel(
            cuerpo,
            text="Estado: Sin configurar",
            font=estilo.FUENTE_CHICO,
            text_color=estilo.TEXTO_2,
            anchor="w",
            justify="left",
            wraplength=440,
        )
        self._label_estado_indec.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self._campo_token_indec = Campo(
            cuerpo,
            "Token de API (api.indec.gob.ar)",
            placeholder="Pegá el token JWT para guardar o reemplazar",
            ayuda=(
                "Se guarda en el Administrador de credenciales de Windows; "
                "nunca en la base ni en los respaldos."
            ),
            mostrar="•",
        )
        self._campo_token_indec.grid(row=1, column=0, sticky="ew")
        self._campo_token_indec.atajo("<Return>", self._guardar_token_indec)

        botones = ctk.CTkFrame(cuerpo, fg_color="transparent")
        botones.grid(row=2, column=0, sticky="w", pady=(12, 0))

        self._boton_guardar_token = estilo.boton_primario(
            botones,
            "Guardar token",
            command=self._guardar_token_indec,
            height=estilo.ALTO_BOTON_FILA,
        )
        self._boton_guardar_token.pack(side="left")

        self._boton_probar_indec = estilo.boton_secundario(
            botones,
            "Probar conexión",
            command=self._probar_conexion_indec,
            height=estilo.ALTO_BOTON_FILA,
        )
        self._boton_probar_indec.pack(side="left", padx=(8, 0))

        self._boton_borrar_token = estilo.boton_secundario(
            botones,
            "Borrar token",
            command=self._borrar_token_indec,
            height=estilo.ALTO_BOTON_FILA,
        )
        self._boton_borrar_token.configure(text_color=estilo.PELIGRO)
        self._boton_borrar_token.pack(side="left", padx=(8, 0))

    def _pintar_acerca(self, marco) -> None:
        tarjeta = Tarjeta(marco, titulo="Acerca de")
        tarjeta.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(estilo.GAP, 0),
        )
        ctk.CTkLabel(
            tarjeta.cuerpo,
            text=f"Brickly {VERSION}",
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
        self._refrescar_estado_indec()

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

    # --- INDEC ----------------------------------------------------------------

    def _refrescar_estado_indec(self) -> None:
        if self._label_estado_indec is None:
            return
        sinc = self._servicios.sincronizacion_ipc
        if sinc is None:
            self._label_estado_indec.configure(
                text="Estado: Servicio no disponible",
                text_color=estilo.TEXTO_3,
            )
            if self._boton_guardar_token is not None:
                self._boton_guardar_token.configure(state="disabled")
            if self._boton_probar_indec is not None:
                self._boton_probar_indec.configure(state="disabled")
            if self._boton_borrar_token is not None:
                self._boton_borrar_token.configure(state="disabled")
            return

        estado = sinc.estado_token()
        color = estilo.PELIGRO if estado.vencido else estilo.TEXTO_2
        self._label_estado_indec.configure(
            text=texto_estado_token_indec(estado),
            text_color=color,
        )
        if self._boton_borrar_token is not None:
            self._boton_borrar_token.configure(
                state="normal" if estado.configurado else "disabled"
            )
        if self._boton_probar_indec is not None and not self._probando_indec:
            self._boton_probar_indec.configure(state="normal")

    def _guardar_token_indec(self) -> None:
        sinc = self._servicios.sincronizacion_ipc
        if sinc is None or self._campo_token_indec is None:
            return
        self._campo_token_indec.limpiar_error()
        try:
            estado = sinc.guardar_token(self._campo_token_indec.valor())
        except ErrorDeValidacion as error:
            self._campo_token_indec.mostrar_error(str(error))
            self._campo_token_indec.enfocar()
            return
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return

        self._campo_token_indec.poner_valor("")
        self._refrescar_estado_indec()
        if estado.vencido:
            self.mostrar_banner(
                "alerta",
                "Token guardado, pero su fecha de vencimiento ya pasó. Generá uno nuevo en api.indec.gob.ar.",
            )
        else:
            self.mostrar_banner("exito", "Token de INDEC guardado.")

    def _borrar_token_indec(self) -> None:
        sinc = self._servicios.sincronizacion_ipc
        if sinc is None:
            return
        if not messagebox.askyesno(
            "Borrar token de INDEC",
            "¿Eliminar el token guardado de INDEC?\n\n"
            "La carga manual de IPC va a seguir disponible.",
            icon="warning",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            sinc.borrar_token()
        except ErrorDeNegocio as error:
            self.mostrar_banner("error", str(error))
            return
        if self._campo_token_indec is not None:
            self._campo_token_indec.poner_valor("")
            self._campo_token_indec.limpiar_error()
        self._refrescar_estado_indec()
        self.mostrar_banner("exito", "Token de INDEC eliminado.")

    def _probar_conexion_indec(self) -> None:
        sinc = self._servicios.sincronizacion_ipc
        if sinc is None or self._probando_indec:
            return
        if self._campo_token_indec is not None:
            self._campo_token_indec.limpiar_error()
        token_escrito = (
            self._campo_token_indec.valor().strip()
            if self._campo_token_indec is not None
            else ""
        )

        self._probando_indec = True
        if self._boton_probar_indec is not None:
            self._boton_probar_indec.configure(
                text="Probando…", state="disabled"
            )
        self.limpiar_banner()

        cola: queue.Queue[tuple[str, object]] = queue.Queue()

        def _tarea() -> None:
            try:
                resultado = sinc.probar_conexion(token_escrito or None)
            except (ErrorDeValidacion, ErrorDeNegocio) as error:
                cola.put(("error", str(error)))
            except Exception:
                cola.put(
                    (
                        "error",
                        "No se pudo completar la prueba de conexión con INDEC.",
                    )
                )
            else:
                cola.put(("ok", resultado))

        threading.Thread(target=_tarea, daemon=True).start()
        self.after(40, lambda: self._revisar_cola_prueba_indec(cola))

    def _revisar_cola_prueba_indec(
        self, cola: queue.Queue[tuple[str, object]]
    ) -> None:
        if not self.winfo_exists():
            return
        try:
            estado, valor = cola.get_nowait()
        except queue.Empty:
            self.after(40, lambda: self._revisar_cola_prueba_indec(cola))
            return
        if estado == "ok":
            self._fin_prueba_indec_ok(valor)  # type: ignore[arg-type]
        else:
            self._fin_prueba_indec_error(str(valor))

    def _fin_prueba_indec_ok(self, resultado: ResultadoPruebaIpc) -> None:
        self._probando_indec = False
        if not self.winfo_exists():
            return
        if self._boton_probar_indec is not None:
            self._boton_probar_indec.configure(
                text="Probar conexión", state="normal"
            )
        self.mostrar_banner("exito", texto_resultado_prueba_indec(resultado))

    def _fin_prueba_indec_error(self, mensaje: str) -> None:
        self._probando_indec = False
        if not self.winfo_exists():
            return
        if self._boton_probar_indec is not None:
            self._boton_probar_indec.configure(
                text="Probar conexión", state="normal"
            )
        self.mostrar_banner("error", mensaje)

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

