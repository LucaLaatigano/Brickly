"""Contenedor de casos de uso que la UI recibe inyectado (spec §6.3).

Un atributo por área; crece a medida que los hitos agregan servicios.
`main.py` lo arma; la UI nunca construye servicios.
"""

from dataclasses import dataclass

from brickly.aplicacion.ajustes import ServicioAjustesIpc
from brickly.aplicacion.cobranzas import ServicioCobranzas
from brickly.aplicacion.configuracion import ServicioConfiguracion
from brickly.aplicacion.constancias import ServicioConstancias
from brickly.aplicacion.departamentos import ServicioDepartamentos
from brickly.aplicacion.informes import ServicioInformes
from brickly.aplicacion.sincronizacion_ipc import ServicioSincronizacionIpc


@dataclass(frozen=True)
class Servicios:
    departamentos: ServicioDepartamentos
    cobranzas: ServicioCobranzas | None = None
    ajustes: ServicioAjustesIpc | None = None
    sincronizacion_ipc: ServicioSincronizacionIpc | None = None
    informes: ServicioInformes | None = None
    constancias: ServicioConstancias | None = None
    configuracion: ServicioConfiguracion | None = None
    # Ruta física de la base (la muestra Configuración, §3.7). La elige main.
    ruta_base: str | None = None


