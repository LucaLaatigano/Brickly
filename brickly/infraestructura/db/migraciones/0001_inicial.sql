-- ============================================================================
-- 0001_inicial.sql — Esquema inicial · App de Gestión de Departamentos
-- ============================================================================
-- Convenciones (aplican a todo el archivo):
--   * Dinero: centavos enteros (INTEGER). Tablas STRICT: un float ni siquiera
--     entra (regla dura de ADR-0001: nunca floats para plata).
--   * Tasas y variaciones: puntos básicos (bp), 100 bp = 1 %. El IPC admite
--     valores negativos (deflación).
--   * Fechas de negocio: TEXT 'YYYY-MM-DD', las escribe la aplicación con el
--     Reloj inyectable. Timestamps de auditoría: 'YYYY-MM-DD HH:MM:SS' en UTC
--     (datetime('now')), nunca fechas de negocio.
--   * SQLite >= 3.37 (tablas STRICT). El migrador corre este script dentro de
--     una transacción y al terminar setea PRAGMA user_version = 1.
--   * La conexión de la app DEBE abrir con PRAGMA foreign_keys = ON.
--
-- Mapa de tablas:
--   departamentos  unidades administradas
--   inquilinos     personas (una persona puede tener varios contratos)
--   contratos      relación inquilino ↔ departamento con sus condiciones
--   cuotas         obligación mensual generada por contrato
--   pagos          cobros recibidos (un pago puede cubrir varias cuotas)
--   imputaciones   cómo se aplicó cada pago (FIFO): capital y mora por cuota
--   ipc_valores    variación mensual del IPC cargada a mano (API a futuro)
--   ajustes        historial inmutable de ajustes trimestrales aplicados
--   configuracion  valores sueltos de la instalación (clave/valor)
-- ============================================================================

-- Unidades administradas. piso/depto NULL = no informado (se muestra solo la
-- dirección).
CREATE TABLE departamentos (
    id          INTEGER PRIMARY KEY,
    direccion   TEXT    NOT NULL,
    piso        TEXT,
    depto       TEXT,
    m2          INTEGER CHECK (m2 IS NULL OR m2 > 0),
    propietario TEXT
) STRICT;

-- Dos unidades no pueden repetir (direccion, piso, depto); con COALESCE para
-- que NULL no burle el UNIQUE (en SQLite los NULL no colisionan entre sí).
CREATE UNIQUE INDEX ux_departamentos_unidad
    ON departamentos (direccion, COALESCE(piso, ''), COALESCE(depto, ''));

-- Personas: un inquilino puede alquilar varias veces (renovación, otro depto).
CREATE TABLE inquilinos (
    id       INTEGER PRIMARY KEY,
    nombre   TEXT NOT NULL,
    telefono TEXT,
    email    TEXT
) STRICT;

-- Contrato de un inquilino en un departamento.
-- monto_centavos es la CUOTA VIGENTE: los ajustes IPC la actualizan y dejan
-- snapshot en `ajustes`. fecha_fin NULL = vigente; se setea al cerrar/renovar
-- (la UI cierra el anterior y crea el nuevo en una sola operación).
CREATE TABLE contratos (
    id                INTEGER PRIMARY KEY,
    departamento_id   INTEGER NOT NULL REFERENCES departamentos (id) ON DELETE CASCADE,
    inquilino_id      INTEGER NOT NULL REFERENCES inquilinos (id)    ON DELETE RESTRICT,
    fecha_inicio      TEXT    NOT NULL CHECK (fecha_inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_fin         TEXT    CHECK (fecha_fin IS NULL OR
                                     (fecha_fin GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                                      AND fecha_fin >= fecha_inicio)),
    monto_centavos    INTEGER NOT NULL CHECK (monto_centavos > 0),
    dia_vencimiento   INTEGER NOT NULL DEFAULT 10  CHECK (dia_vencimiento BETWEEN 1 AND 28),
    dias_gracia       INTEGER NOT NULL DEFAULT 5   CHECK (dias_gracia >= 0),
    tasa_mora_bp      INTEGER NOT NULL DEFAULT 200 CHECK (tasa_mora_bp >= 0),    -- 200 bp = 2,0 % mensual
    ciclo_meses       INTEGER NOT NULL DEFAULT 3   CHECK (ciclo_meses > 0),      -- trimestral
    redondeo_centavos INTEGER NOT NULL DEFAULT 1   CHECK (redondeo_centavos > 0) -- 1 = centavos, 100 = $ 100
) STRICT;

CREATE INDEX ix_contratos_departamento ON contratos (departamento_id);

-- Un departamento tiene a lo sumo UN contrato vigente (la operación de cambio
-- de inquilino cierra el anterior antes de crear el nuevo). El historial queda
-- en los contratos con fecha_fin no NULL.
CREATE UNIQUE INDEX ux_contratos_vigente
    ON contratos (departamento_id) WHERE fecha_fin IS NULL;

-- Obligación mensual. No guarda estado ni saldo: se derivan de imputaciones
-- (fuente única de verdad). UNIQUE(contrato, anio, mes) = generación idempotente
-- (dos clics en "Generar cuotas" no duplican).
CREATE TABLE cuotas (
    id                INTEGER PRIMARY KEY,
    contrato_id       INTEGER NOT NULL REFERENCES contratos (id) ON DELETE CASCADE,
    anio              INTEGER NOT NULL CHECK (anio BETWEEN 2000 AND 2100),
    mes               INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    fecha_vencimiento TEXT    NOT NULL CHECK (fecha_vencimiento GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    monto_centavos    INTEGER NOT NULL CHECK (monto_centavos > 0),
    generada_en       TEXT    NOT NULL DEFAULT (datetime('now'))  -- auditoría
) STRICT;

CREATE UNIQUE INDEX ux_cuotas_periodo     ON cuotas (contrato_id, anio, mes);
CREATE INDEX        ix_cuotas_mes         ON cuotas (anio, mes);           -- Cobranzas del mes
CREATE INDEX        ix_cuotas_vencimiento ON cuotas (fecha_vencimiento);   -- vencidas / mora

-- Cobros recibidos. `fecha` = fecha efectiva del pago (la elige el usuario; el
-- Reloj da el default); `creado_en` = cuándo se cargó.
-- contrato_id vive acá a propósito (desnormalización deliberada: un pago
-- pertenece a un solo contrato y simplifica Cobranzas/Panel). La consistencia
-- la mantiene el único caso de uso que escribe pagos + imputaciones juntos,
-- en una transacción.
CREATE TABLE pagos (
    id             INTEGER PRIMARY KEY,
    contrato_id    INTEGER NOT NULL REFERENCES contratos (id) ON DELETE CASCADE,
    fecha          TEXT    NOT NULL CHECK (fecha GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    monto_centavos INTEGER NOT NULL CHECK (monto_centavos > 0),
    medio          TEXT    NOT NULL CHECK (medio IN ('efectivo', 'transferencia', 'deposito', 'otro')),
    nota           TEXT,
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX ix_pagos_contrato ON pagos (contrato_id);
CREATE INDEX ix_pagos_fecha    ON pagos (fecha);

-- Aplicación del pago a cada cuota (la imputación FIFO la decide el dominio):
-- monto_centavos = capital aplicado; mora_centavos = mora cobrada, congelada
-- al momento del pago.
-- Invariante de aplicación (no expresable en DDL): Σ(monto + mora) de un pago
-- = monto del pago. Lo garantiza el caso de uso.
CREATE TABLE imputaciones (
    id             INTEGER PRIMARY KEY,
    pago_id        INTEGER NOT NULL REFERENCES pagos (id)  ON DELETE CASCADE,
    cuota_id       INTEGER NOT NULL REFERENCES cuotas (id) ON DELETE CASCADE,
    monto_centavos INTEGER NOT NULL CHECK (monto_centavos >= 0),
    mora_centavos  INTEGER NOT NULL DEFAULT 0 CHECK (mora_centavos >= 0),
    CHECK (monto_centavos + mora_centavos > 0),
    UNIQUE (pago_id, cuota_id)
) STRICT;

CREATE INDEX ix_imputaciones_cuota ON imputaciones (cuota_id);

-- Variación mensual del IPC en bp (10 bp = 0,1 %; negativos = deflación).
-- Editable/borrable: los ajustes ya aplicados guardan su propio snapshot y no
-- dependen de estas filas.
CREATE TABLE ipc_valores (
    id           INTEGER PRIMARY KEY,
    anio         INTEGER NOT NULL CHECK (anio BETWEEN 2000 AND 2100),
    mes          INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    variacion_bp INTEGER NOT NULL CHECK (variacion_bp BETWEEN -10000 AND 10000),
    origen       TEXT    NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual', 'api')),
    cargado_en   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (anio, mes)
) STRICT;

-- Historial INMUTABLE de ajustes aplicados. La ventana base son `meses_ciclo`
-- meses consecutivos desde (anio_base, mes_base); ventana y % aplicado quedan
-- congelados aunque después se edite el IPC.
-- Con es_override = 1 (ajuste pactado distinto al IPC), el motivo es obligatorio.
CREATE TABLE ajustes (
    id                     INTEGER PRIMARY KEY,
    contrato_id            INTEGER NOT NULL REFERENCES contratos (id) ON DELETE CASCADE,
    fecha_aplicacion       TEXT    NOT NULL CHECK (fecha_aplicacion GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    anio_base              INTEGER NOT NULL CHECK (anio_base BETWEEN 2000 AND 2100),
    mes_base               INTEGER NOT NULL CHECK (mes_base BETWEEN 1 AND 12),
    meses_ciclo            INTEGER NOT NULL CHECK (meses_ciclo > 0),
    variacion_bp           INTEGER NOT NULL CHECK (variacion_bp BETWEEN -10000 AND 10000),
    cuota_antes_centavos   INTEGER NOT NULL CHECK (cuota_antes_centavos > 0),
    cuota_despues_centavos INTEGER NOT NULL CHECK (cuota_despues_centavos > 0),
    es_override            INTEGER NOT NULL DEFAULT 0 CHECK (es_override IN (0, 1)),
    motivo_override        TEXT,
    creado_en              TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (es_override = 0 OR (motivo_override IS NOT NULL AND motivo_override <> '')),
    UNIQUE (contrato_id, fecha_aplicacion)  -- guarda contra doble aplicación
) STRICT;

CREATE INDEX ix_ajustes_contrato ON ajustes (contrato_id);

-- Valores sueltos de la instalación (clave/valor TEXT; la aplicación parsea).
-- Claves esperadas:
--   vencimiento_dia '10' · gracia_dias '5' · mora_bp '200' · redondeo_centavos '1'
--   admin_nombre / admin_telefono / admin_email
--   ultimo_respaldo 'YYYY-MM-DD' · respaldo_recordatorio_dias '14'
CREATE TABLE configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
) STRICT;

-- ----------------------------------------------------------------------------
-- Accesos que este esquema hace baratos (el índice que los sirve):
--   1. Cobranzas de un mes:      ix_cuotas_mes (anio, mes)
--   2. Estado de una unidad:     ux_cuotas_periodo / ix_pagos_contrato
--   3. Vencidas de hoy:          ix_cuotas_vencimiento + join imputaciones
--   4. Pagos de una cuota:       ix_imputaciones_cuota
--   5. IPC de un mes:            UNIQUE (anio, mes)
--   6. Historial de un contrato: ix_ajustes_contrato
-- ----------------------------------------------------------------------------
