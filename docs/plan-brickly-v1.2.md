# Plan Brickly 1.2 — Importación de Excel (H9) y recibo con firma

- **Estado:** H9 y el recibo con foto de firma implementados técnicamente —
  Release 1.2.0 en preparación. Pendiente: smoke del `.exe` y pasada visual del
  usuario a 125 % DPI.
- **Plan anterior:** `docs/plan-brickly-v1.1.md` (H5–H8, cerrado — Release 1.1.0,
  2026-11-04).
- **Dueño de ejecución:** senior-dev.
- **Revisiones previstas:** architect (ADR-0005), qa (aceptación), devops
  (release).

## Features por plan

| Plan | Features |
|---|---|
| **H0–H4 — `docs/arranque-h0.md`** | Shell, departamentos, contratos, cuotas, mora y pagos FIFO, Ajustes IPC, Panel, Informes CSV, Configuración. Cerrado. |
| **1.1 — `docs/plan-brickly-v1.1.md`** | Renombre a Brickly + migración, README/release, IPC INDEC, Excel completo, constancia PDF. Cerrado — Release 1.1.0. |
| **1.2 — este plan** | H9 importación de Excel de departamentos, inquilinos y contratos + recibo de pago con foto de firma. |
| **1.3 — futuro** | Anular/reverso de pago, recordatorios de cobranza, backup automático, reporte de aging, etc. |

## Decisiones cerradas

1. La importación se rige por **ADR-0005** y
   `docs/specs/importacion-excel.md`: solo `.xlsx`, `openpyxl` confinado a
   infraestructura, cero `float`, identidad de unidad normalizada,
   deduplicación idempotente y guardado atómico.
2. No se importan cuotas, pagos, deudas ni ajustes históricos: solo
   departamentos, inquilinos y contratos vigentes. Las cuotas se generan después
   desde **Cobranzas**.
3. Una unidad que ya existe en Brickly no se pisa: se informa
   `Ya existe (se omite)`.
4. El recibo mantiene las reglas de **ADR-0004**: solo cuotas pagadas, firma
   visual, no fiscal. Se agrega la posibilidad de subir una foto de firma desde
   **Configuración → Datos del administrador**, almacenada como BLOB en la tabla
   singleton `firma_admin` (migración `0003_firma_admin.sql`).
5. La versión de la app pasa a **1.2.0**.

## Alcance 1.2

**Incluye:** H9 (importación Excel), recibo de pago con foto de firma, plantilla
`.xlsx` y archivo de ejemplo con datos ficticios.

**No incluye:** anular/reverso de pago, recordatorios de cobranza, backup
automático, reporte de aging, expensas, liquidación al propietario,
multi-edificio, contratos en USD, auto-update, recibos fiscales, facturación
electrónica ni firma digital.

## H9 — Importación de Excel

### Alcance

- Archivo `.xlsx` con columnas separadas (`Dirección`, `Piso`, `Depto`) o
  columna unificada `Unidad` con separador `" · "` (formato del export de H7).
- 16 campos canónicos: dirección, piso, depto, m², propietario, datos del
  inquilino, fechas de inicio y fin, cuota, día de vencimiento, días de gracia,
  mora diaria, ciclo IPC y redondeo.
- Contrato vigente, departamento vacante o contrato vencido: el vencido se
  importa solo como departamento vacante con una advertencia explícita.
- Wizard inline de 3 pasos dentro de **Departamentos**, mapeo asistido, vista
  previa obligatoria y panel lateral de 380 px para corregir u omitir filas.
- Plantilla `.xlsx` descargable desde el paso 1.

### Implementación

- **Aplicación (`brickly/aplicacion/importacion.py`):** parsers sin `float`,
  detección de fila de encabezado, sugerencia de mapeo y
  `ServicioImportacionDepartamentos` con `inspeccionar_archivo`,
  `previsualizar`, `importar` y `generar_plantilla`.
- **Dominio:** `clave_unidad_normalizada` y `desglosar_unidad_compuesta` en
  `brickly/dominio/departamento.py`.
- **Puertos:** `LectorExcel` y `EscritorExcel` en `brickly/aplicacion/puertos.py`;
  `guardar_lote_importacion` en `RepositorioDepartamentos`.
- **Infraestructura:** `LectorExcelOpenpyxl` en
  `brickly/infraestructura/excel.py` y transacción única en
  `RepositorioDepartamentosSQLite`.
- **UI:** `brickly/ui/presenters/importacion.py` y
  `brickly/ui/vistas/importacion_departamentos.py`; entradas desde
  Departamentos (encabezado y estado vacío) y checklist del Panel
  (`modo_inicial="importar"`).
- **Cableado:** `main.py`, `brickly/ui/ventana.py` y `Servicios.importacion`.

### Terminado cuando

- Los 4 criterios de aceptación de `docs/specs/importacion-excel.md` pasan.
- `pytest tests/` verde, incluido `tests/test_arquitectura.py`.
- El wizard funciona dentro del `.exe`, sin congelar la UI, y a 125 % DPI.
- Reimportar el mismo archivo no duplica y una fila con error bloquea la
  importación hasta corregirse u omitirse.

### Cierre técnico (2026-11-19)

- Suite completa: **369 passed**.
- Tests nuevos: `test_dominio_importacion.py`, `test_importacion_h9_servicio.py`,
  `test_importacion_h9_lectura.py`, `test_importacion_h9_repositorio.py`,
  `test_importacion_h9_integracion.py`, `test_presenter_importacion.py` y
  `test_qa_importacion_h9.py`.
- Archivo de ejemplo con datos ficticios:
  `docs/ejemplos/importacion-departamentos-ficticios.xlsx`.
- Pendiente: smoke manual del flujo dentro del `.exe` y pasada visual a 125 % DPI.

## Recibo de pago con foto de firma (mejora de H8)

### Alcance

- Subir, ver estado y quitar una foto de firma (PNG, JPG/JPEG, WebP o BMP)
  desde **Configuración → Datos del administrador**.
- Persistencia como BLOB en `firma_admin` (migración 0003).
- El PDF del recibo dibuja la imagen centrada sobre la línea de firma; si no hay
  imagen, queda la línea para firmar a mano.
- Título del documento: **"Recibo de pago"**; pie: "Se recibió el dinero
  correspondiente al pago del mes indicado."

### Terminado cuando

- El PDF abre con acentos, ñ, montos y foto de firma.
- Sin foto, el recibo sigue funcionando con la línea de firma.
- La imagen no se guarda en `configuracion` ni viaja en logs o backups de texto.
- Tests verdes, incluido `tests/test_constancias_h8.py`.

### Cierre técnico (2026-11-19)

- ADR-0004 actualizado, migración 0003, UI de Configuración, generador PDF y
  tests en verde.
- Pendiente: validar un PDF real con foto y la pasada visual a 125 % DPI.

## Orden y checkpoints

1. H9 completo → reportar.
2. Recibo con firma completo → reportar.
3. Release 1.2.0 → build, smoke, README y SHA256.

## Definición de terminado 1.2

- Tests verdes, incluido arquitectura.
- Criterios de aceptación de importación aprobados.
- Recibo con y sin foto de firma verificado.
- Smoke del `.exe` y 125 % DPI.
- README, `AGENTS.md` y este plan actualizados.
- Sin regresiones en Panel, Cobranzas, Ajustes, Informes y Configuración.

## Reporte final obligatorio

1. Resumen de lo hecho.
2. Archivos creados, modificados y renombrados.
3. Migraciones y resultado.
4. Tests: comando, cantidad y resultado.
5. Build: ruta, tamaño y SHA256.
6. Smoke: pantallas y escenarios.
7. README: secciones cambiadas.
8. Pendientes, riesgos y decisiones abiertas.

## Riesgos

- Planillas reales con formatos ambiguos: la vista previa bloquea errores y
  permite corregir sin tocar el archivo original.
- Duplicados: la clave normalizada y la deduplicación intra-archivo evitan
  dobles altas.
- Foto de firma: validar formato, tamaño y rotación EXIF; el BLOB no debe
  afectar las lecturas livianas de `configuracion`.
- Build con `openpyxl` y `reportlab`: verificar peso y arranque del `.exe`.
