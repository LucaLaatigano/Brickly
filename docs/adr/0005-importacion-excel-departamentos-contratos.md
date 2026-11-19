# ADR-0005 — Importación de Excel de Departamentos, Inquilinos y Contratos Vigentes

- **Fecha:** 2026-11-13
- **Estado:** aceptada
- **Hito:** H9 (Brickly v1.2)

## Contexto y problema

Quienes administran entre 5 y 60 departamentos en planillas Excel necesitan migrar su
cartera actual a Brickly en pocos minutos sin tipear departamento por departamento ni
contrato por contrato, y sin riesgo de ensuciar la base SQLite con datos inválidos,
duplicados o errores de coma flotante.

Al diseñar la importación contra el esquema SQLite existente (`0001_inicial.sql`) y la
arquitectura de 4 capas (ADR-0001), aparecen cinco decisiones estructurales:

1. Cómo conciliar una columna opcional `Fecha fin` del Excel con el índice parcial
   `ux_contratos_vigente` y las consultas SQL de contratos vigentes (`WHERE c.fecha_fin IS NULL`).
2. Dónde colocar la lectura de `.xlsx` (`openpyxl`) y cómo impedir que `float` o tipos
   de `openpyxl` crucen hacia `aplicacion`, `dominio` o `ui`.
3. Cómo definir la identidad de una unidad para que reimportar el mismo archivo sea
   idempotente y cómo resolver unidades repetidas dentro del mismo Excel.
4. Cómo persistir los `inquilinos` sin acoplar accidentalmente contratos de distintas
   unidades.
5. Cómo garantizar atomicidad ("todo o nada") en la confirmación del lote.

## Decisiones

### 1. Invariante de `contratos.fecha_fin` vs. `ux_contratos_vigente`

En `0001_inicial.sql`, el índice único parcial:

```sql
CREATE UNIQUE INDEX ux_contratos_vigente
    ON contratos (departamento_id) WHERE fecha_fin IS NULL;
```

y las consultas de `departamentos.py`, `cobranzas.py`, `ajustes.py` e `informes.py`
definen **contrato vigente** estrictamente como `c.fecha_fin IS NULL` (en Brickly,
`fecha_fin` se graba al cerrar o reemplazar un contrato en `reemplazar_contrato`).

Por lo tanto, al importar desde Excel:

- **Contrato vigente (`Fecha fin` vacía o `Fecha fin >= Reloj.hoy()`):** si la fila
  trae contrato y `fecha_fin` está vacía o es mayor o igual a `Reloj.hoy()` (y
  `>= fecha_inicio`), el contrato está activo hoy. Se clasifica como
  `nuevo_con_contrato` y se persiste en `contratos` con `fecha_fin = None` para que
  quede cubierto por `ux_contratos_vigente` y sea visible como contrato activo en toda
  la aplicación. La fecha de fin original del Excel se conserva en el DTO de
  previsualización (`fecha_fin_informativa: date | None`) para mostrarla en la UI.
- **Contrato vencido (`fecha_inicio <= fecha_fin < Reloj.hoy()`):** la fila se
  clasifica como `nuevo_contrato_vencido`. Se importa únicamente el `Departamento`
  como **vacante** (sin insertar fila en `contratos` ni `inquilinos`) y se informa una
  advertencia explícita en la previsualización (`"Contrato vencido el dd/mm/aaaa: se importará solo el departamento (vacante)."`).
- **Rango inválido (`fecha_fin < fecha_inicio`):** la fila se clasifica como `error`
  (`"La fecha de fin no puede ser anterior al inicio."`) y bloquea la confirmación
  hasta ser corregida o desmarcada.

### 2. Frontera de `openpyxl` y prohibición de `float`

- Se define el puerto `LectorExcel` en `brickly/aplicacion/puertos.py` (`listar_hojas`
  y `leer_hoja`) que devuelve estructuras puras e inmutables (`HojaCrudaExcel`,
  `FilaCrudaExcel`, `ValorCeldaCruda = str | int | Decimal | date | None`).
- La implementación `LectorExcelOpenpyxl` vive en `brickly/infraestructura/excel.py`.
  Ningún módulo de `dominio`, `aplicacion` ni `ui` importa `openpyxl` (regla vigilada
  por `tests/test_arquitectura.py`).
- Todo `float` entregado por `openpyxl` se convierte inmediatamente en el adaptador a
  `Decimal(str(round(val, 6)))` antes de cruzar a `aplicacion`. Los parsers de
  aplicación (`parsear_monto_importacion`, `parsear_tasa_mora_importacion`) operan
  exclusivamente con `int`, `Decimal` y `str` hacia centavos enteros (`int`) y puntos
  básicos (`int`), rechazando `float` y `bool`.

### 3. Identidad normalizada de unidad, idempotencia y dedupe intra-archivo

- La identidad de unidad se determina con `clave_unidad_normalizada(direccion, piso, depto)`
  en `brickly/dominio/departamento.py`: aplica `limpiar_espacios` (colapsa espacios
  múltiples y recorta extremos), pasa a `.casefold()` y en `piso` quita el sufijo
  `"º"` o `"°"` cuando acompaña a dígitos (`"3º"` / `"3°"` → `"3"`, consistente con
  `nombre_unidad`).
- **Contra la base de datos:** si la clave normalizada ya existe en SQLite, la fila se
  clasifica como `omitido_existente` (`"Ya existe en Brickly; se omite para no duplicar."`).
  Nunca se pisa ni modifica un departamento o contrato ya cargado. Reimportar el
  mismo archivo una segunda vez produce 100 % de filas en `omitido_existente`.
- **Dentro del mismo archivo:** si una unidad nueva aparece en múltiples filas del
  mismo Excel (p. ej. una planilla con renovaciones históricas):
  1. Gana la fila con contrato vigente que cubre `Reloj.hoy()` (`fecha_inicio <= hoy`
     y sin fin vencido); si hay más de una, la de `fecha_inicio` más reciente (y ante
     empate exacto, la última fila del archivo).
  2. Si no hay vigentes a hoy pero hay contratos futuros (`fecha_inicio > hoy`), gana
     el de `fecha_inicio` más reciente.
  3. Si todas las apariciones son vacantes o con contrato vencido, queda una sola fila
     vacante (`nuevo_contrato_vencido` o `nuevo_vacante`).
  Las filas descartadas pasan a `omitido_contrato_anterior` con advertencia indicando
  qué fila ganó, y la fila ganadora informa que había múltiples filas para esa unidad.

### 4. Aislamiento de `inquilinos` por contrato importado

- Al igual que `RepositorioDepartamentosSQLite.guardar_contrato`, cada contrato
  vigente importado inserta su propia fila en `inquilinos` vinculada a ese contrato.
- Esto preserva la invariante de `actualizar_contrato` (donde editar el nombre,
  teléfono o email del inquilino de una unidad no altera accidentalmente otros
  contratos de otras unidades con homónimos).

### 5. Persistencia atómica ("todo o nada")

- `RepositorioDepartamentos.guardar_lote_importacion(items)` ejecuta todas las
  inserciones de `departamentos`, `inquilinos` y `contratos` dentro de un único bloque
  transaccional `with self._conexion:`.
- Si cualquier restricción de SQLite falla (`IntegrityError`, `CHECK`, etc.), toda la
  transacción hace rollback y la base queda exactamente como antes de confirmar,
  traduciendo el fallo a `ErrorDeNegocio` en castellano.

## Consecuencias

- La migración inicial desde planillas de inmobiliaria o administración propia (así
  como desde la hoja `Contratos` del propio export `Excel completo` de H7) se resuelve
  en un wizard inline de 3 pasos dentro de `Departamentos` con edición en vivo en
  panel lateral de 380 px y descarga de plantilla `.xlsx`.
- No se requiere nueva migración SQL: se utiliza el esquema `STRICT` vigente.
