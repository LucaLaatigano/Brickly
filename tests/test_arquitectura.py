"""Test de arquitectura — hace cumplir la regla de dependencia (ADR-0001).

Flechas hacia adentro:

    ui                → puede importar: aplicacion, dominio
    aplicacion        → puede importar: dominio
    infraestructura   → puede importar: aplicacion (puertos), dominio
    dominio           → NO importa nada del proyecto ni frameworks

main.py queda exento a propósito: es el composition root, el único que
puede verlo todo. Si este test falla, NO se relaja el test: se mueve el
código a la capa que corresponde.
"""

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]  # corre desde donde corre

PROHIBIDOS = {
    "brickly/dominio": (
        "sqlite3",
        "customtkinter",
        "openpyxl",
        "reportlab",
        "brickly.aplicacion",
        "brickly.infraestructura",
        "brickly.ui",
    ),
    "brickly/aplicacion": (
        "sqlite3",
        "customtkinter",
        "openpyxl",
        "reportlab",
        "brickly.infraestructura",
        "brickly.ui",
    ),
    "brickly/ui": (
        "sqlite3",
        "openpyxl",
        "reportlab",
        "brickly.infraestructura",
    ),
    "brickly/infraestructura": (
        "customtkinter",
        "brickly.ui",
    ),
}


def _modulos_importados(archivo: Path):
    """Genera los módulos importados por un .py, resolviendo imports relativos."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    paquete = archivo.relative_to(RAIZ).parent.parts
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                yield alias.name
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:  # relativo: from . import x / from .. import y
                corte = len(paquete) - (nodo.level - 1)
                partes = list(paquete[:corte])
                if nodo.module:
                    partes += nodo.module.split(".")
                yield ".".join(partes)
            elif nodo.module:
                yield nodo.module


def test_reglas_de_dependencia():
    violaciones = []
    for capa, prohibidos in PROHIBIDOS.items():
        for archivo in (RAIZ / capa).rglob("*.py"):
            for modulo in _modulos_importados(archivo):
                if modulo.startswith(prohibidos):
                    relativo = archivo.relative_to(RAIZ)
                    violaciones.append(f"  [{capa}] {relativo}: importa '{modulo}'")
    assert not violaciones, (
        "Regla de dependencia violada (ADR-0001) — mover el código a su capa:\n"
        + "\n".join(violaciones)
    )
