"""Composition root — el único módulo que conoce todas las capas (ADR-0001).

Acá se instancian las implementaciones concretas y se inyectan hacia adentro,
en este orden:

    conexión (infra) → migrar → reloj + repositorios (infra)
    → casos de uso (aplicación) → ventana (ui)

Ninguna capa se auto-arma: todo entra por parámetro desde acá, para que la UI
no conozca la base y el dominio no conozca a nadie.
"""

from gestion.aplicacion.ajustes import ServicioAjustesIpc
from gestion.aplicacion.cobranzas import ServicioCobranzas
from gestion.aplicacion.configuracion import ServicioConfiguracion
from gestion.aplicacion.contenedor import Servicios
from gestion.aplicacion.departamentos import ServicioDepartamentos
from gestion.aplicacion.informes import ServicioInformes
from gestion.infraestructura.archivos import EscritorArchivosSistema, RespaldadorSQLite
from gestion.infraestructura.db.conexion import abrir_conexion, ruta_base_datos
from gestion.infraestructura.db.migrador import migrar
from gestion.infraestructura.db.repositorios.ajustes import RepositorioAjustesSQLite
from gestion.infraestructura.db.repositorios.cobranzas import (
    RepositorioCobranzasSQLite,
)
from gestion.infraestructura.db.repositorios.configuracion import (
    RepositorioConfiguracionSQLite,
)
from gestion.infraestructura.db.repositorios.departamentos import (
    RepositorioDepartamentosSQLite,
)
from gestion.infraestructura.db.repositorios.informes import RepositorioInformesSQLite
from gestion.infraestructura.reloj import RelojSistema
from gestion.ui.ventana import VentanaPrincipal


def main() -> None:
    ruta = ruta_base_datos()
    conexion = abrir_conexion(ruta)
    migrar(conexion)
    reloj = RelojSistema()

    configuracion = ServicioConfiguracion(
        RepositorioConfiguracionSQLite(conexion), reloj
    )
    cobranzas = ServicioCobranzas(RepositorioCobranzasSQLite(conexion), reloj=reloj)

    servicios = Servicios(
        departamentos=ServicioDepartamentos(
            RepositorioDepartamentosSQLite(conexion, reloj=reloj),
            reloj=reloj,
        ),
        cobranzas=cobranzas,
        ajustes=ServicioAjustesIpc(
            RepositorioAjustesSQLite(conexion),
            reloj=reloj,
        ),
        informes=ServicioInformes(
            repositorio=RepositorioInformesSQLite(conexion),
            cobranzas=cobranzas,
            configuracion=configuracion,
            respaldador=RespaldadorSQLite(conexion),
            escritor=EscritorArchivosSistema(),
            reloj=reloj,
        ),
        configuracion=configuracion,
        ruta_base=str(ruta),
    )

    ventana = VentanaPrincipal(servicios)
    ventana.mainloop()


if __name__ == "__main__":
    main()
