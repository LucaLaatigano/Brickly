"""Verificación del esquema inicial (0001_inicial.sql) contra SQLite real.

Corre el script tal cual lo va a correr el migrador y después intenta violar
cada invariante: si una violación NO falla, el invariante no está en el
esquema.
"""

import sqlite3
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SQL_0001 = RAIZ / "brickly" / "infraestructura" / "db" / "migraciones" / "0001_inicial.sql"

TABLAS_ESPERADAS = {
    "ajustes",
    "configuracion",
    "contratos",
    "cuotas",
    "departamentos",
    "imputaciones",
    "inquilinos",
    "ipc_valores",
    "pagos",
}

# Flujo mínimo: una unidad, un inquilino, un contrato vigente, una cuota
# cobrada (capital + mora), un IPC, un ajuste aplicado, configuración, y una
# segunda unidad limpia (sin contrato) para checks que necesitan aislamiento.
SEMILLA = [
    "INSERT INTO departamentos (direccion, piso, depto, m2, propietario) VALUES ('Rivadavia 3421', '3', 'B', 62, 'Marta Perez')",
    "INSERT INTO departamentos (direccion, piso, depto) VALUES ('Mitre 1180', '1', 'A')",
    "INSERT INTO inquilinos (nombre, telefono, email) VALUES ('Laura Gimenez', '11 5555-1234', 'laura@mail.com')",
    "INSERT INTO contratos (departamento_id, inquilino_id, fecha_inicio, monto_centavos) VALUES (1, 1, '2026-03-01', 1280000)",
    "INSERT INTO cuotas (contrato_id, anio, mes, fecha_vencimiento, monto_centavos) VALUES (1, 2026, 10, '2026-10-10', 1280000)",
    "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio) VALUES (1, '2026-10-15', 1433600, 'transferencia')",
    "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos, mora_centavos) VALUES (1, 1, 1280000, 153600)",
    "INSERT INTO ipc_valores (anio, mes, variacion_bp) VALUES (2026, 7, 210)",
    "INSERT INTO ajustes (contrato_id, fecha_aplicacion, anio_base, mes_base, meses_ciclo, variacion_bp, cuota_antes_centavos, cuota_despues_centavos) VALUES (1, '2026-10-15', 2026, 4, 3, 942, 1280000, 1400600)",
    "INSERT INTO configuracion (clave, valor) VALUES ('vencimiento_dia', '10')",
]

# Cada sentencia tiene que ser RECHAZADA por la base (IntegrityError).
INVARIANTES = [
    (
        "cuota duplicada del mismo periodo (generacion idempotente)",
        "INSERT INTO cuotas (contrato_id, anio, mes, fecha_vencimiento, monto_centavos) VALUES (1, 2026, 10, '2026-10-10', 999)",
    ),
    (
        "segundo contrato vigente en el mismo departamento",
        "INSERT INTO contratos (departamento_id, inquilino_id, fecha_inicio, monto_centavos) VALUES (1, 1, '2026-11-01', 1300000)",
    ),
    (
        "float en columna de dinero (tabla STRICT)",
        "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio) VALUES (1, '2026-10-16', 100.5, 'efectivo')",
    ),
    (
        "monto de pago <= 0",
        "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio) VALUES (1, '2026-10-16', 0, 'efectivo')",
    ),
    (
        "fecha mal formada (15/11/2026)",
        "INSERT INTO cuotas (contrato_id, anio, mes, fecha_vencimiento, monto_centavos) VALUES (1, 2026, 11, '15/11/2026', 1280000)",
    ),
    (
        "medio de pago inexistente ('bitcoin')",
        "INSERT INTO pagos (contrato_id, fecha, monto_centavos, medio) VALUES (1, '2026-10-16', 1000, 'bitcoin')",
    ),
    (
        "imputacion a cuota inexistente (FK rota)",
        "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos) VALUES (1, 999, 100)",
    ),
    (
        "imputacion vacia (0 + 0)",
        "INSERT INTO imputaciones (pago_id, cuota_id, monto_centavos, mora_centavos) VALUES (1, 1, 0, 0)",
    ),
    (
        "override sin motivo",
        "INSERT INTO ajustes (contrato_id, fecha_aplicacion, anio_base, mes_base, meses_ciclo, variacion_bp, cuota_antes_centavos, cuota_despues_centavos, es_override) VALUES (1, '2026-11-01', 2026, 5, 3, 400, 1280000, 1331200, 1)",
    ),
    (
        "dia de vencimiento 31 (fuera de 1-28)",
        "INSERT INTO contratos (departamento_id, inquilino_id, fecha_inicio, monto_centavos, dia_vencimiento) VALUES (2, 1, '2027-01-01', 500, 31)",
    ),
    (
        "fecha_fin anterior a fecha_inicio",
        "INSERT INTO contratos (departamento_id, inquilino_id, fecha_inicio, fecha_fin, monto_centavos) VALUES (2, 1, '2026-01-01', '2020-01-01', 500)",
    ),
    (
        "IPC duplicado del mismo mes",
        "INSERT INTO ipc_valores (anio, mes, variacion_bp) VALUES (2026, 7, 999)",
    ),
]


def _sembrar(con: sqlite3.Connection) -> None:
    for sentencia in SEMILLA:
        con.execute(sentencia)


@pytest.fixture()
def db():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SQL_0001.read_text(encoding="utf-8"))
    yield con
    con.close()


def test_crea_el_esquema(db):
    tablas = {fila[0] for fila in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tablas == TABLAS_ESPERADAS
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_flujo_minimo(db):
    _sembrar(db)
    db.commit()

    aplicado = db.execute(
        "SELECT SUM(monto_centavos + mora_centavos) FROM imputaciones WHERE cuota_id = 1"
    ).fetchone()[0]
    assert aplicado == 1_433_600
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_unidad_sin_piso_depto_no_se_duplica(db):
    db.execute("INSERT INTO departamentos (direccion) VALUES ('Sarmiento 890')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO departamentos (direccion) VALUES ('Sarmiento 890')")


@pytest.mark.parametrize(
    "sql",
    [sentencia for _, sentencia in INVARIANTES],
    ids=[descripcion for descripcion, _ in INVARIANTES],
)
def test_invariantes(db, sql):
    _sembrar(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql)
