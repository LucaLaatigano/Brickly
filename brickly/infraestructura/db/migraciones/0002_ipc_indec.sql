-- Migración 0002 — Trazabilidad de IPC importado desde INDEC (ADR-0003).
-- Aditiva sobre `ipc_valores` (STRICT): índice oficial en milésimos enteros y
-- marca de última actualización. Las filas previas conservan `cargado_en`.

ALTER TABLE ipc_valores
    ADD COLUMN indice_milesimos INTEGER
    CHECK (indice_milesimos IS NULL OR indice_milesimos > 0);

ALTER TABLE ipc_valores
    ADD COLUMN actualizado_en TEXT;

UPDATE ipc_valores
   SET actualizado_en = cargado_en
 WHERE actualizado_en IS NULL;
