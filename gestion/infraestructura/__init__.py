"""Infraestructura — adaptadores que tocan el mundo real.

SQLite (`db/`), reloj del sistema, exportadores, futuras integraciones
(API IPC, notificadores). Implementa los puertos de `gestion.aplicacion`;
`ui` y `dominio` no la importan nunca.
"""
