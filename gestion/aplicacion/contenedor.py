"""Contenedor de casos de uso que la UI recibe inyectado (spec §6.3).

Un atributo por área; crece a medida que los hitos agregan servicios.
`main.py` lo arma; la UI nunca construye servicios.
"""

from dataclasses import dataclass

from gestion.aplicacion.ajustes import ServicioAjustesIpc
from gestion.aplicacion.cobranzas import ServicioCobranzas
from gestion.aplicacion.configuracion import ServicioConfiguracion
from gestion.aplicacion.departamentos import ServicioDepartamentos
from gestion.aplicacion.informes import ServicioInformes


@dataclass(frozen=True)
class Servicios:
    departamentos: ServicioDepartamentos
    cobranzas: ServicioCobranzas | None = None
    ajustes: ServicioAjustesIpc | None = None
    informes: ServicioInformes | None = None
    configuracion: ServicioConfiguracion | None = None
    # Ruta física de la base (la muestra Configuración, §3.7). La elige main.
    ruta_base: str | None = None
