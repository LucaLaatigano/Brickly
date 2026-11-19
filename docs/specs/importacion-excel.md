# Especificación Funcional y Técnica — Importación de Excel de Departamentos, Inquilinos y Contratos Vigentes (H9)

- **Estado:** Aprobada
- **ADR asociado:** [ADR-0005](../adr/0005-importacion-excel-departamentos-contratos.md)

## 1. Problema y objetivo

Quienes administran entre 5 y 60 departamentos en planillas Excel necesitan pasar su
cartera actual a Brickly en pocos minutos, sin cargar departamento por departamento ni
contrato por contrato, y sin riesgo de ensuciar la base de datos con duplicados,
errores de redondeo o contratos inconsistentes.

## 2. Alcance (In / Out)

### Entra en alcance (v1 de Importación)
- **Archivo `.xlsx`** (Excel moderno, leído con `openpyxl` ya incluido en `requirements.txt`).
- **Departamentos:** `direccion` (obligatorio), `piso`, `depto`, `m2`, `propietario`.
  Soporta tanto columnas separadas (`Dirección`, `Piso`, `Depto`) como columna
  unificada `Unidad` con separador `" · "` (formato del export `Excel completo` de H7,
  ej. `"Rivadavia 3421 · 3º B"`).
- **Inquilino + Contrato vigente (opcional por fila):** si la fila trae datos de
  alquiler activo, se crea el departamento junto con su inquilino y contrato vigente
  (`nombre_inquilino`, `telefono`, `email`, `fecha_inicio`, `fecha_fin` informativa,
  `monto_inicial_centavos`, `dia_vencimiento`, `dias_gracia`, `tasa_diaria_bp`,
  `ciclo_ipc_meses`, `redondeo`). Si no trae contrato, se crea el departamento como
  **vacante** (`Sin contrato`).
- **Mapeo flexible de columnas** con auto-detección de encabezados (hasta fila 10) +
  **plantilla `.xlsx` descargable** lista para completar.
- **Vista previa obligatoria** antes de tocar SQLite, con edición inline en panel
  lateral de **380 px** para corregir celdas con error o desmarcar filas.

### Fuera de alcance explícito
- **No se importan cuotas históricas, pagos anteriores, imputaciones, deuda acumulada
  previa ni historial de ajustes IPC.** Una vez importados los contratos vigentes con
  su cuota actual, el usuario genera las cuotas desde el mes en curso en **Cobranzas**.
- **No se pisan ni actualizan departamentos o contratos que ya existen en Brickly:**
  si una unidad ya existe en la base, se informa como `Ya existe (se omite)`.
- **No se leen archivos `.xls` binarios legacy (Excel 97-2003) ni `.csv`:** si el
  usuario elige un `.xls`, se muestra un mensaje claro indicando guardarlo como `.xlsx`.

---

## 3. Flujo UX paso a paso

### Puntos de entrada
1. **Pantalla `Departamentos`:** botón secundario `[ Importar desde Excel ]` en el
   encabezado superior derecho, a la izquierda de `[ + Agregar departamento ]`.
2. **Estado vacío de `Departamentos`** (cuando hay 0 unidades): acción secundaria
   `[ Importar desde un Excel ]` + link `[ Descargar plantilla de ejemplo (.xlsx) ]`.
3. **Checklist de puesta en marcha en `Panel` (F1):** el paso 1 permite ir a cargar o
   importar departamentos desde Excel (`modo_inicial="importar"`).

### Wizard inline de 3 pasos (nunca modal)
Vive dentro del área de contenido de `Departamentos`, con `‹ Volver a Departamentos` y
stepper visual:
`1 Archivo y hoja` › `2 Columnas` › `3 Revisión e importación`

- **Paso 1 — Archivo y hoja:**
  - Selector de archivo `.xlsx`, selector de hoja (si el libro tiene más de una) y
    selector de fila de encabezado (auto-detectada en las primeras 10 filas).
  - Aviso explícito: *"Se importarán departamentos, inquilinos y contratos vigentes. No se importan pagos ni deudas anteriores."*
  - Botón secundario `[ Descargar plantilla de ejemplo (.xlsx) ]`.
- **Paso 2 — Mapeo de columnas:**
  - Grilla de las 16 propiedades de Brickly con `CTkOptionMenu` de las columnas del
    archivo (`"(No importar / usar predeterminado)"` o las columnas detectadas) y
    muestra del primer valor real no vacío.
  - Nota informativa con los predeterminados actuales de Configuración.
- **Paso 3 — Revisión, corrección inline e importación:**
  - Resumen superior: `N listas · M con errores · K se omitirán`.
  - Filtros (`CTkSegmentedButton`): `Todas` · `Listas` · `Con errores` · `Omitidas`.
  - Tabla de previsualización (`Fila`, `Unidad`, `Inquilino`, `Vigencia`,
    `Cuota mensual`, `Estado` con `ChipEstado`, `Detalle / Motivo`).
  - Clic en cualquier fila abre el panel lateral derecho de **380 px**
    (`PanelFilaImportacion`) para corregir celdas en vivo o elegir `[ Omitir esta fila ]`.
  - Botón primario `[ Importar N departamentos ]` habilitado cuando `filas_con_error == 0`
    y `filas_listas > 0`.
- **Resultado:**
  - Card de éxito con el resumen de unidades y contratos creados, recordatorio de que
    no se importaron pagos ni cuotas de meses anteriores, y CTAs:
    - Primario: `[ Ir a Cobranzas y generar cuotas de {Mes Año} → ]`
    - Secundario: `[ Ver mis departamentos ]`
    - Link: `[ Importar otra hoja o archivo ]`

---

## 4. Contrato de datos de entrada (16 campos canónicos)

| Clave | Etiqueta UI | Obligatorio | Regla / Default | Sinónimos auto-detectados |
|---|---|---|---|---|
| `direccion` | Dirección / Calle y Nº | **Sí** | Texto no vacío. Si el archivo trae `Unidad` con `" · "` y no hay Piso/Depto mapeados, se desglosa automáticamente. | `direccion`, `calle`, `domicilio`, `propiedad`, `inmueble`, `ubicacion`, `unidad`, `departamento` |
| `piso` | Piso | No | Texto opcional (`"3"`, `"PB"`). `"3º"` / `"3°"` se normaliza a `"3"`. | `piso`, `nivel`, `planta` |
| `depto` | Depto / Unidad | No | Texto opcional (`"A"`, `"B"`). | `depto`, `dpto`, `dto`, `uf`, `unidad funcional`, `puerta`, `letra` |
| `m2` | m² | No | Entero `> 0` (si viene decimal `45,0` → `45`). | `m2`, `metros`, `superficie`, `sup`, `m²` |
| `propietario` | Propietario | No | Texto opcional. | `propietario`, `dueno`, `titular`, `locador` |
| `nombre_inquilino` | Inquilino (nombre) | Condicional | Obligatorio si hay contrato. | `inquilino`, `locatario`, `arrendatario`, `titular contrato`, `ocupante` |
| `telefono_inquilino` | Teléfono inquilino | No | Texto opcional. | `telefono`, `tel`, `celular`, `whatsapp`, `movil`, `contacto` |
| `email_inquilino` | Email inquilino | No | Texto opcional con `@` si se informa. | `email`, `mail`, `correo`, `e-mail` |
| `fecha_inicio` | Inicio contrato | Condicional | Obligatorio si hay contrato. `dd/mm/aaaa` o fecha nativa (`2000..2100`). | `inicio`, `fecha inicio`, `inicio contrato`, `desde`, `alta`, `vigencia desde` |
| `fecha_fin` | Fin contrato | No | Fecha opcional `>= fecha_inicio`. Si `< hoy` → `nuevo_contrato_vencido` (vacante). Si `>= hoy` → vigente (`fecha_fin=None` en DB, conservada como informativa en preview). | `fin`, `fecha fin`, `fin contrato`, `vencimiento contrato`, `hasta`, `finalizacion` |
| `monto_inicial_centavos` | Cuota mensual ($) | Condicional | Obligatorio si hay contrato. Entero en centavos `> 0`, sin floats. | `cuota`, `alquiler`, `monto`, `valor`, `canon`, `importe`, `precio`, `cuota vigente`, `cuota mensual`, `cuota inicial` |
| `dia_vencimiento` | Día de vencimiento | No | Entero `1..28`. Default: Configuración (`10`). | `dia vencimiento`, `vence dia`, `vencimiento dia`, `dia de pago` |
| `dias_gracia` | Días de gracia | No | Entero `>= 0`. Default: Configuración (`5`). | `dias gracia`, `gracia`, `gracia (dias)`, `dias de gracia`, `tolerancia` |
| `tasa_diaria_bp` | Mora (%) | No | `0..10000 bp`. Default: Configuración (`200 bp`). | `mora`, `tasa mora`, `interes mora`, `punitorios`, `recargo`, `mora diaria (%)`, `mora mensual` |
| `ciclo_ipc_meses` | Ciclo ajuste IPC (meses) | No | Entero `> 0` o `"Trimestral"` (`3`), `"Semestral"` (`6`), etc. Default: `3`. | `ciclo`, `ciclo ipc`, `ciclo ipc (meses)`, `ajuste cada`, `frecuencia ajuste`, `meses ajuste` |
| `redondeo` | Redondeo de ajuste | No | `1` (`Centavos`) o `100` (`$ 100`). Default: Configuración (`1`). | `redondeo`, `tipo redondeo` |

---

## 5. Reglas de validación, deduplicación y atomicidad

1. **Cero `float`:** `LectorExcelOpenpyxl` convierte cualquier `float` de `openpyxl` a
   `Decimal` antes de devolver `HojaCrudaExcel`. `parsear_monto_importacion` y
   `parsear_tasa_mora_importacion` rechazan `float` y `bool`.
2. **Formatos ambiguos rechazados:** montos con formato anglosajón (`380,000.00`),
   múltiples separadores decimales (`380.000.00`), monedas extranjeras (`USD`, `U$S`),
   fechas con año de 2 dígitos (`01/03/26`) o seriales numéricos sin formato fecha
   (`45323`), y fórmulas sin valor cacheado (`__FORMULA_SIN_VALOR__`) producen errores
   accionables en español.
3. **Deduplicación e idempotencia:**
   - Unidad existente en SQLite (`clave_unidad_normalizada`) → `omitido_existente`.
   - Unidad repetida en el mismo Excel → gana el contrato vigente más reciente (o
     última fila en caso de empate) y las demás quedan como `omitido_contrato_anterior`.
4. **Atomicidad:** `guardar_lote_importacion` inserta todas las unidades, inquilinos y
   contratos en un único `with self._conexion:`.

---

## 6. Criterios de aceptación

1. Descargar la plantilla `.xlsx` y reimportarla sin tocar el mapeo importa 2 unidades
   (1 con contrato vigente, 1 vacante) y en una segunda pasada marca ambas como
   `Ya existe (se omite)`.
2. Importar la hoja `Contratos` de un archivo exportado por **Informes → Excel completo**
   (H7) auto-mapea sus columnas, desglosa `Unidad` (`"Rivadavia 3421 · 3º B"`) y
   recrea los departamentos y contratos vigentes sin errores.
3. Editar una fila con error desde el panel lateral de 380 px o marcarla para omitir
   habilita inmediatamente la importación sin modificar el archivo Excel original.
4. `pytest tests/` (incluyendo `tests/test_arquitectura.py` y `tests/test_contraste.py`)
   pasa 100 % en verde.
