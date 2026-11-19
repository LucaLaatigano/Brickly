-- Migración 0003 — Firma del administrador (imagen) para constancias de pago.
-- Tabla singleton STRICT separada de `configuracion` (clave/valor TEXT) para:
--   1. Almacenar la foto/imagen de la firma (PNG, JPG, WebP, BMP) como BLOB nativo.
--   2. No arrastrar el binario de imagen en cada lectura liviana de `configuracion`.
--   3. Imponer integridad en el motor: fila única (id = 1), nombre de archivo
--      no vacío y contenido binario con al menos 1 byte.

CREATE TABLE firma_admin (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    nombre_archivo TEXT    NOT NULL CHECK (trim(nombre_archivo) <> ''),
    contenido      BLOB    NOT NULL CHECK (length(contenido) > 0),
    actualizado_en TEXT    NOT NULL DEFAULT (datetime('now')) CHECK (trim(actualizado_en) <> '')
) STRICT;
