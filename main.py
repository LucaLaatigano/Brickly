"""Composition root — el único módulo que conoce todas las capas (ADR-0001).

Acá se instancian las implementaciones concretas y se inyectan hacia adentro,
en este orden:

    migración de datos (infra) → conexión → migrar esquema
    → reloj + repositorios (infra) → casos de uso (aplicación) → ventana (ui)

Ninguna capa se auto-arma: todo entra por parámetro desde acá, para que la UI
no conozca la base y el dominio no conozca a nadie.
"""

from brickly.aplicacion.ajustes import ServicioAjustesIpc
from brickly.aplicacion.cobranzas import ServicioCobranzas
from brickly.aplicacion.configuracion import ServicioConfiguracion
from brickly.aplicacion.constancias import ServicioConstancias
from brickly.aplicacion.contenedor import Servicios
from brickly.aplicacion.departamentos import ServicioDepartamentos
from brickly.aplicacion.informes import ServicioInformes
from brickly.aplicacion.sincronizacion_ipc import ServicioSincronizacionIpc
from brickly.infraestructura.archivos import EscritorArchivosSistema, RespaldadorSQLite
from brickly.infraestructura.credenciales import AlmacenTokenCredencialesWindows
from brickly.infraestructura.db.conexion import abrir_conexion, ruta_base_datos
from brickly.infraestructura.db.migracion_datos import migrar_datos_si_hace_falta
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.ajustes import RepositorioAjustesSQLite
from brickly.infraestructura.db.repositorios.cobranzas import (
    RepositorioCobranzasSQLite,
)
from brickly.infraestructura.db.repositorios.configuracion import (
    RepositorioConfiguracionSQLite,
)
from brickly.infraestructura.db.repositorios.constancias import (
    RepositorioConstanciasSQLite,
)
from brickly.infraestructura.db.repositorios.departamentos import (
    RepositorioDepartamentosSQLite,
)
from brickly.infraestructura.db.repositorios.informes import RepositorioInformesSQLite
from brickly.infraestructura.excel import EscritorExcelOpenpyxl
from brickly.infraestructura.indec import ClienteIndecHttp
from brickly.infraestructura.pdf import GeneradorPdfReportlab
from brickly.infraestructura.reloj import RelojSistema
from brickly.ui.ventana import VentanaPrincipal


import sys


def _configurar_id_proceso_windows() -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Brickly.App.1"
            )
        except Exception:
            pass


def main() -> None:
    _configurar_id_proceso_windows()
    try:
        migrar_datos_si_hace_falta()
    except OSError as exc:
        from tkinter import messagebox

        messagebox.showerror("Brickly", str(exc))
        return

    ruta = ruta_base_datos()
    conexion = abrir_conexion(ruta)
    migrar(conexion)
    reloj = RelojSistema()

    repo_configuracion = RepositorioConfiguracionSQLite(conexion)
    repo_ajustes = RepositorioAjustesSQLite(conexion)
    configuracion = ServicioConfiguracion(repo_configuracion, reloj)
    cobranzas = ServicioCobranzas(RepositorioCobranzasSQLite(conexion), reloj=reloj)

    servicios = Servicios(
        departamentos=ServicioDepartamentos(
            RepositorioDepartamentosSQLite(conexion, reloj=reloj),
            reloj=reloj,
        ),
        cobranzas=cobranzas,
        ajustes=ServicioAjustesIpc(
            repo_ajustes,
            reloj=reloj,
        ),
        sincronizacion_ipc=ServicioSincronizacionIpc(
            repositorio=repo_ajustes,
            fuente=ClienteIndecHttp(),
            almacen_token=AlmacenTokenCredencialesWindows(),
            reloj=reloj,
            configuracion=repo_configuracion,
        ),
        informes=ServicioInformes(
            repositorio=RepositorioInformesSQLite(conexion),
            cobranzas=cobranzas,
            configuracion=configuracion,
            respaldador=RespaldadorSQLite(conexion),
            escritor=EscritorArchivosSistema(),
            reloj=reloj,
            escritor_excel=EscritorExcelOpenpyxl(),
        ),
        constancias=ServicioConstancias(
            repositorio=RepositorioConstanciasSQLite(conexion),
            configuracion=configuracion,
            generador_pdf=GeneradorPdfReportlab(),
            reloj=reloj,
        ),
        configuracion=configuracion,
        ruta_base=str(ruta),
    )

    ventana = VentanaPrincipal(servicios)
    ventana.mainloop()


if __name__ == "__main__":
    main()
