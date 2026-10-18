"""Gestión de departamentos — paquete raíz.

Capas (ver docs/adr/0001-arquitectura-de-capas.md):
dominio → aplicacion → infraestructura / ui, con dependencias hacia adentro.
La regla se verifica con tests/test_arquitectura.py.
"""

VERSION = "1.0.0"
FECHA_BUILD = "2026-10-16"  # se actualiza al empaquetar una release
