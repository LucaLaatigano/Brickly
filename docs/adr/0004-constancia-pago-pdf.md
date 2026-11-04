# ADR-0004 — Constancia de pago mensual en PDF

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Hito:** H8 (Brickly v1.1)

## Contexto y problema

Al cobrar el alquiler mensual, quien administra necesita entregar al inquilino una
constancia impresa o en PDF que acredite que la cuota de ese período quedó saldada,
incluyendo el detalle de capital y mora cobrada y los pagos que se imputaron a esa
cuota.

Necesitamos definir:
1. El alcance del documento (por cuota vs. estado de cuenta completo, condición de
   habilitación y persistencia).
2. Qué librería usar para generar el PDF dentro del ejecutable empaquetado con
   PyInstaller sin depender de herramientas externas instaladas en Windows.
3. Qué datos exactos incluye el documento y cómo se resuelve el bloque de firma.
4. Qué queda explícitamente fuera de alcance (no-goals) y cómo se manejan los
   errores de validación o escritura.

## Decisiones

### 1. Alcance: documento por unidad + período, solo para cuotas pagadas y sin persistencia

- La constancia certifica **una cuota específica** (`unidad + período`, identificada
  por `cuota_id`), elegida desde el período activo en **Cobranzas → Mes**.
- **Condición estricta de habilitación:** solo se emite para cuotas en estado
  `pagada` (`saldo_capital_cuota(monto_centavos, pagado_centavos) == 0` y al menos
  una imputación registrada). Si una cuota está `pendiente`, `parcial` o `vencida`,
  `ServicioConstancias` rechaza la operación indicando el motivo y el saldo de
  capital pendiente.
- **Sin migración ni escrituras:** el PDF se construye en el momento leyendo las
  tablas existentes (`cuotas`, `contratos`, `departamentos`, `inquilinos`, `pagos`,
  `imputaciones`, `configuracion`). Repetir la generación es 100 % idempotente y no
  registra emisiones ni altera datos.

### 2. Librería PDF y publicación atómica

- Se adopta **`reportlab` (`reportlab==5.1.0`, licencia BSD)** en la capa
  `brickly/infraestructura/pdf.py` (`GeneradorPdfReportlab`), detrás del puerto
  `GeneradorPdf` de `brickly/aplicacion/puertos.py`.
- Se utilizan las fuentes estándar **Helvetica / Helvetica-Bold** con codificación
  WinAnsi (incluidas en el estándar PDF), que soportan todos los caracteres del
  castellano (`áéíóúñÁÉÍÓÚÑüÜº°`) sin incrustar archivos `.ttf` externos.
- El documento se renderiza completo en memoria (`io.BytesIO`) y se escribe en un
  archivo temporal en la carpeta destino antes de publicarse con `os.replace`. Si
  el archivo destino está abierto en un visor PDF (`PermissionError` en Windows) o
  falla el render, se limpia el temporal y nunca queda un PDF truncado o corrupto.

### 3. Contenido del documento y política de firma

El DTO puro `ConstanciaPago` (armado en `brickly/aplicacion/constancias.py` con
montos en centavos enteros) contiene:

1. **Encabezado:** título `"Constancia de pago"`, fecha de emisión (`Reloj.hoy()`)
   y datos del emisor si están configurados (`admin_nombre`, `admin_telefono`,
   `admin_email`).
2. **Identificación:**
   - **Unidad:** `nombre_unidad(direccion, piso, depto)`.
   - **Inquilino:** el asociado al contrato de esa cuota (`contratos.inquilino_id`),
     incluso si ese contrato ya fue cerrado o renovado posteriormente.
   - **Período:** `<mes> <año>` (p. ej. `octubre 2026`).
3. **Resumen imputado a la cuota:**
   - Capital de la cuota (`pagado_centavos`).
   - Mora cobrada (`mora_pagada_centavos`).
   - Total abonado por la cuota (`pagado_centavos + mora_pagada_centavos`).
4. **Pagos aplicados a la cuota:** por cada fila de `imputaciones` asociada a
   `cuota_id`, fecha del pago, medio (`Efectivo`, `Transferencia`, `Depósito`,
   `Otro`), capital imputado, mora imputada y subtotal aplicado a esta cuota. Si un
   pago cubrió varias cuotas en FIFO, se informa únicamente la fracción imputada a
   esta cuota.
5. **Pie de alcance:**
   *"La presente constancia certifica el pago de la cuota del período indicado y no
   implica que la unidad esté libre de otras obligaciones."*
6. **Bloque de firma visual al pie:**
   - Línea de firma + nombre disponible + rol **`Propietario/a o Administrador/a`**.
   - **Regla de resolución del nombre:**
     - Si están cargados tanto `departamentos.propietario` como `admin_nombre` en
       Configuración: se muestran ambos (`"<propietario> / <admin_nombre>"`) y la
       línea queda para quien firme.
     - Si solo está `departamentos.propietario`: se muestra ese nombre.
     - Si no está `propietario` pero sí `admin_nombre`: se muestra `admin_nombre`.
     - Si ninguno está cargado: se muestra solo la línea y el rol
       `"Propietario/a o Administrador/a"` para firmar de puño y letra.

### 4. No-goals (fuera de alcance)

- **No es factura ni comprobante fiscal** (no reemplaza facturación AFIP/ARCA).
- **No posee firma digital ni validez criptográfica** (es una línea de firma visual
  para impresión o envío informativo).
- **No es un certificado de libre deuda** de la unidad: solo acredita el período
  indicado.

### 5. Manejo de errores

- **Cuota no pagada (`pendiente`, `parcial`, `vencida`):** `ErrorDeNegocio` con el
  estado y el saldo pendiente en pesos.
- **Archivo bloqueado (`PermissionError`):** se traduce a un mensaje claro en
  castellano indicando que el PDF está abierto en otro programa y que debe cerrarse
  antes de volver a guardar.

## Consecuencias

- `brickly/dominio` y `brickly/aplicacion` permanecen libres de `reportlab` (regla
  vigilada por `tests/test_arquitectura.py`).
- En `Cobranzas → Mes`, hacer clic en una fila con estado `Pagada` abre el
  `PanelConstancia` lateral de 380 px con la vista previa de los datos y el botón
  `Generar PDF` (con nombre sugerido ASCII `constancia-<unidad>-<mes>-<anio>.pdf`).
