"""Migración y conexión: esquema desde cero, una sola vez, FK activas (H0–H8+)."""

from pathlib import Path
import sqlite3

import pytest

from brickly.aplicacion.puertos import FirmaAdminGuardada
from brickly.infraestructura.db.conexion import abrir_conexion, ruta_base_datos
from brickly.infraestructura.db.migrador import migrar
from brickly.infraestructura.db.repositorios.configuracion import (
    RepositorioConfiguracionSQLite,
)

RAIZ = Path(__file__).resolve().parents[1]
DIR_MIGRACIONES = RAIZ / "brickly" / "infraestructura" / "db" / "migraciones"

TABLAS = {
    "ajustes",
    "configuracion",
    "contratos",
    "cuotas",
    "departamentos",
    "firma_admin",
    "imputaciones",
    "inquilinos",
    "ipc_valores",
    "pagos",
}


@pytest.fixture()
def ruta(tmp_path):
    return tmp_path / "Brickly" / "datos.sqlite3"


def test_crea_la_base_desde_cero(ruta):
    con = abrir_conexion(ruta)
    assert migrar(con) == 3
    tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tablas == TABLAS
    con.close()


def test_segunda_apertura_no_re_migra(ruta):
    con = abrir_conexion(ruta)
    migrar(con)
    con.execute("INSERT INTO departamentos (direccion) VALUES ('Rivadavia 3421')")
    con.commit()
    con.close()

    con2 = abrir_conexion(ruta)
    # Si re-corriera el script, el CREATE TABLE fallaría: no re-migra.
    assert migrar(con2) == 3
    assert con2.execute("SELECT COUNT(*) FROM departamentos").fetchone()[0] == 1
    con2.close()


def test_migracion_0001_a_0002_conserva_datos_y_agrega_columnas(ruta):
    sql_0001 = (DIR_MIGRACIONES / "0001_inicial.sql").read_text(encoding="utf-8")

    con = abrir_conexion(ruta)
    con.executescript(sql_0001)
    con.execute("PRAGMA user_version = 1")
    con.execute(
        "INSERT INTO ipc_valores (anio, mes, variacion_bp, origen, cargado_en)"
        " VALUES (2026, 7, 210, 'manual', '2026-08-15 10:00:00')"
    )
    con.commit()

    assert migrar(con) == 3
    fila = con.execute(
        "SELECT anio, mes, variacion_bp, origen, cargado_en, indice_milesimos, actualizado_en"
        " FROM ipc_valores WHERE anio = 2026 AND mes = 7"
    ).fetchone()
    assert fila["variacion_bp"] == 210
    assert fila["origen"] == "manual"
    assert fila["indice_milesimos"] is None
    assert fila["actualizado_en"] == "2026-08-15 10:00:00"

    # CHECK sobre indice_milesimos (> 0 o NULL)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO ipc_valores (anio, mes, variacion_bp, origen, indice_milesimos)"
            " VALUES (2026, 8, 166, 'api', 0)"
        )
    con.close()


def test_migracion_0002_a_0003_crea_firma_admin_y_conserva_datos(ruta):
    sql_0001 = (DIR_MIGRACIONES / "0001_inicial.sql").read_text(encoding="utf-8")
    sql_0002 = (DIR_MIGRACIONES / "0002_ipc_indec.sql").read_text(encoding="utf-8")

    con = abrir_conexion(ruta)
    con.executescript(sql_0001)
    con.executescript(sql_0002)
    con.execute("PRAGMA user_version = 2")
    con.execute(
        "INSERT INTO configuracion (clave, valor) VALUES ('admin_nombre', 'Ana Gómez')"
    )
    con.commit()

    assert migrar(con) == 3
    tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "firma_admin" in tablas
    valor = con.execute(
        "SELECT valor FROM configuracion WHERE clave = 'admin_nombre'"
    ).fetchone()[0]
    assert valor == "Ana Gómez"
    con.close()


@pytest.mark.parametrize(
    ("descripcion", "sql", "parametros"),
    [
        (
            "id distinto de 1 (singleton)",
            "INSERT INTO firma_admin (id, nombre_archivo, contenido) VALUES (2, ?, ?)",
            ("firma.png", b"\x89PNG\r\n\x1a\n1234"),
        ),
        (
            "nombre_archivo vacio",
            "INSERT INTO firma_admin (id, nombre_archivo, contenido) VALUES (1, ?, ?)",
            ("   ", b"\x89PNG\r\n\x1a\n1234"),
        ),
        (
            "contenido vacio (0 bytes)",
            "INSERT INTO firma_admin (id, nombre_archivo, contenido) VALUES (1, ?, ?)",
            ("firma.png", b""),
        ),
        (
            "contenido TEXT en lugar de BLOB (STRICT)",
            "INSERT INTO firma_admin (id, nombre_archivo, contenido) VALUES (1, ?, ?)",
            ("firma.png", "no-es-blob"),
        ),
        (
            "actualizado_en vacio",
            "INSERT INTO firma_admin (id, nombre_archivo, contenido, actualizado_en) VALUES (1, ?, ?, ?)",
            ("firma.png", b"\x89PNG\r\n\x1a\n1234", "  "),
        ),
    ],
)
def test_firma_admin_invariantes_ddl(ruta, descripcion, sql, parametros):
    con = abrir_conexion(ruta)
    migrar(con)
    with pytest.raises(sqlite3.IntegrityError, match=".*"):
        con.execute(sql, parametros)
    con.close()


def test_repositorio_configuracion_firma_crud_y_migracion_legacy(ruta):
    import io
    from PIL import Image

    con = abrir_conexion(ruta)
    migrar(con)
    repo = RepositorioConfiguracionSQLite(con)

    assert repo.obtener_firma() is None

    buf_png = io.BytesIO()
    Image.new("RGBA", (180, 60), (15, 25, 35, 255)).save(buf_png, format="PNG")
    bytes_png = buf_png.getvalue()

    # Reemplazo / upsert transaccional y aislamiento respecto de `configuracion`
    repo.actualizar({"admin_nombre": "Marta Perez"})
    repo.guardar_firma("firma_inicial.png", bytes_png, "2026-11-09 12:00:00")
    primera = repo.obtener_firma()
    assert primera == FirmaAdminGuardada(
        nombre_archivo="firma_inicial.png",
        contenido=bytes_png,
        actualizado_en="2026-11-09 12:00:00",
    )
    assert repo.cargar() == {"admin_nombre": "Marta Perez"}

    # Sobrescritura con una foto JPEG en memoria
    buf_jpg = io.BytesIO()
    Image.new("RGB", (240, 80), (255, 255, 255)).save(buf_jpg, format="JPEG")
    bytes_jpg = buf_jpg.getvalue()

    repo.guardar_firma("firma_foto.jpg", bytes_jpg, "2026-11-10 02:04:15")
    actualizada = repo.obtener_firma()
    assert actualizada is not None
    assert actualizada.nombre_archivo == "firma_foto.jpg"
    assert actualizada.contenido == bytes_jpg
    assert actualizada.actualizado_en == "2026-11-10 02:04:15"
    assert con.execute("SELECT COUNT(*) FROM firma_admin").fetchone()[0] == 1

    # Borrado e idempotencia al borrar dos veces
    repo.borrar_firma()
    assert repo.obtener_firma() is None
    repo.borrar_firma()
    assert repo.obtener_firma() is None
    con.close()


def test_repositorio_configuracion_migra_esquema_legacy_contenido_pdf(tmp_path):
    ruta_legacy = tmp_path / "legacy_v3.sqlite3"
    con = abrir_conexion(ruta_legacy)
    con.executescript(
        (DIR_MIGRACIONES / "0001_inicial.sql").read_text(encoding="utf-8")
    )
    con.executescript(
        (DIR_MIGRACIONES / "0002_ipc_indec.sql").read_text(encoding="utf-8")
    )
    con.execute(
        "CREATE TABLE firma_admin ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " nombre_archivo TEXT NOT NULL CHECK (trim(nombre_archivo) <> ''),"
        " contenido_pdf BLOB NOT NULL CHECK (length(contenido_pdf) > 0),"
        " actualizado_en TEXT NOT NULL DEFAULT (datetime('now')) CHECK (trim(actualizado_en) <> '')"
        ") STRICT"
    )
    con.execute("PRAGMA user_version = 3")
    con.execute(
        "INSERT INTO firma_admin (id, nombre_archivo, contenido_pdf) VALUES (1, ?, ?)",
        ("Photo.pdf", b"%PDF-1.3 viejo"),
    )
    con.commit()

    repo = RepositorioConfiguracionSQLite(con)
    assert repo.obtener_firma() is None
    repo.guardar_firma("firma.png", b"\x89PNG\r\n\x1a\n1234", "2026-11-12 10:00:00")
    guardada = repo.obtener_firma()
    assert guardada is not None
    assert guardada.nombre_archivo == "firma.png"
    assert guardada.contenido == b"\x89PNG\r\n\x1a\n1234"
    con.close()


def test_foreign_keys_activas(ruta):
    con = abrir_conexion(ruta)
    migrar(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO contratos (departamento_id, inquilino_id, fecha_inicio, monto_centavos) "
            "VALUES (999, 999, '2026-01-01', 100)"
        )
    con.close()


def test_ruta_por_usuario_bajo_appdata():
    ruta = ruta_base_datos()
    assert ruta.name == "datos.sqlite3"
    assert ruta.parent.name == "Brickly"

