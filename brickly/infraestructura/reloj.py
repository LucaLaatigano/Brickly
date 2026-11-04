"""Adaptador del puerto `Reloj`: el tiempo real del sistema."""

from datetime import date


class RelojSistema:
    """Implementa `brickly.aplicacion.puertos.Reloj`."""

    def hoy(self) -> date:
        return date.today()
