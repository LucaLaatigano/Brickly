# Plan Brickly 1.1 — Identidad, IPC automático, Excel y constancias de pago

- **Estado:** H5, H6, H7 y H8 técnicos completos — Release 1.1.0 (2026-11-04);
  pendiente la pasada visual del usuario a 125 % DPI.
- **Plan anterior:** `docs/arranque-h0.md` (H0–H4, cerrado; se conserva como
  histórico para comparar features).
- **Dueño de ejecución:** senior-dev.
- **Revisiones previstas:** architect (ADR-0003, H6.0 y ADR-0004), dba
  (migración 0002; H8 no migra), qa (aceptación), devops (release).

## Features por plan

| Plan | Features |
|---|---|
| **H0 — `docs/arranque-h0.md`** | Shell y navegación, departamentos, contratos, cuotas, mora y pagos FIFO, Ajustes IPC, Panel, Informes CSV, Configuración. Implementado. |
| **1.1 — este plan** | Renombre a Brickly + migración de datos, README/release descargable, IPC desde INDEC, Excel completo, constancia de pago PDF. |
| **1.2 — futuro** | Anular/reverso de pago, recordatorios de cobranza, importación masiva, backup automático, reporte de aging, etc. |

## Decisiones cerradas

1. Paquete Python `brickly` en minúscula. `Brickly` queda para el nombre
   visible, el `.exe` y la carpeta de datos.
2. Migrar `%APPDATA%\GestionDepartamentos\datos.sqlite3` a
   `%APPDATA%\Brickly\datos.sqlite3` copiando la base, verificando integridad y
   conservando la vieja como respaldo. Nunca borrar la base vieja.
3. Fuente IPC primaria: `api.indec.gob.ar` con token de usuario.
   **H6.0 es un spike bloqueante:** verificar endpoint, auth, payload y que la
   API realmente exponga IPC. Si no lo expone, el agente se detiene y reporta;
   no inventa endpoints ni cambia a otra fuente sin aprobación.
4. La API solo pisa valores manuales si el usuario lo confirma explícitamente.
   Sin confirmación, los valores manuales quedan protegidos y editables.
5. Los extras (anular pago, recibo fiscal, etc.) van a 1.2.
6. No se borra `docs/arranque-h0.md`.
7. Constancia de pago (H8): PDF por unidad + período, solo para cuotas
   pagadas; firma visual (línea + nombre y rol), no digital; no es factura ni
   comprobante fiscal.

## Alcance 1.1

**Incluye:** H5 (renombre + migración + README + release), H6 (IPC INDEC),
H7 (Excel completo), H8 (constancia de pago PDF).

**No incluye:** auto-aplicar ajustes IPC, expensas, liquidación al propietario,
multi-edificio, contratos en USD, auto-update, anular pago, recibos fiscales,
facturación electrónica, firma digital.

## H5 — Identidad Brickly + release

### Alcance

- `gestion/` → `brickly/`; imports, tests, docs, ADRs y spec UX actualizados.
- `GestionDepartamentos.spec` → `Brickly.spec`.
- `dist\GestionDepartamentos.exe` → `dist\Brickly.exe`.
- Backups `GestionDepartamentos-*.sqlite3` → `Brickly-*.sqlite3`.
- `%APPDATA%\GestionDepartamentos` → `%APPDATA%\Brickly` con migración de una
  sola vez:
  - Si la base nueva no existe y la vieja sí, copiarla con la API de backup de
    SQLite (no copia de archivo a ciegas).
  - Correr `PRAGMA integrity_check` sobre la copia.
  - Dejar la vieja intacta como respaldo.
  - Test con `APPDATA` temporal y con una base vieja con datos.
- Actualizar `AGENTS.md`, `README.md`, ADRs, spec UX y
  `tests/test_arquitectura.py`.
- Rebuild, smoke del `.exe` y pasada a 125 % DPI.

### README — especificación obligatoria

La sección de descarga actual está mal: apunta a `dist\GestionDepartamentos.exe`,
que solo existe en un clon del repo. El README nuevo debe explicar:

1. **Descargar Brickly para Windows**
   - Ir a `https://github.com/LucaLaatigano/Brickly/releases/latest`.
   - Descargar `Brickly.exe` y el `SHA256.txt` publicado con el release.
   - Verificar el hash con
     `Get-FileHash .\Brickly.exe -Algorithm SHA256`.
   - Aviso de SmartScreen: “Más información” → “Ejecutar de todas formas”,
     porque el `.exe` no está firmado. Aclarar que solo se descargue del
     release oficial.
   - Doble clic; no requiere instalador ni Python.
   - Primer arranque: la base se crea sola en
     `%APPDATA%\Brickly\datos.sqlite3`.
2. **Requisitos:** Windows 10/11 64-bit; sin Python; internet solo para IPC
   cuando H6 esté implementado.
3. **Actualizar:** hacer respaldo, cerrar la app, reemplazar el `.exe`; la base
   y la configuración quedan en `%APPDATA%\Brickly`.
4. **Desinstalar:** borrar el `.exe`; opcionalmente borrar
   `%APPDATA%\Brickly` (con advertencia de que se pierden los datos).
5. **Datos y respaldo:** ruta de la base, cómo hacer respaldo desde Informes,
   cómo restaurar con la app cerrada.
6. **Desde el código:** clonar, crear `.venv`, instalar `requirements.txt`,
   correr `main.py`, correr tests y build con `Brickly.spec`.
7. **Problemas comunes:** SmartScreen, antivirus, archivo Excel abierto,
   PDF abierto en otro programa, token vencido, sin internet.
8. **Fuente de datos:** en H5 los valores IPC se cargan manualmente; la
   integración INDEC se documenta al cerrar H6.
9. **Licencia.**

No debe quedar ninguna instrucción que diga “descargá de `dist\`” ni
`GestionDepartamentos.exe`.

### Terminado cuando

- No quedan imports de `gestion`.
- `pytest tests/` verde (229+ tests).
- El `.exe` nuevo abre y una base vieja migra sin perder datos.
- El README permite descargar, ejecutar, actualizar y desinstalar sin clonar.
- 125 % DPI verificado.

### Cierre H5 (2026-10-19)

- `234 passed` en `.venv\Scripts\python -m pytest tests/`.
- `dist\Brickly.exe` construido con `Brickly.spec` (13.169.357 bytes,
  SHA256 `9122d8c821a68880a9395fa0530ef35f8a84af964a1ecad6c45496e08dd2f047`);
  smoke real con base nueva y con base vieja migrada (título "Brickly", datos
  copiados, base vieja conservada).
- README y `.gitignore` actualizados.
- Pendiente: pasada visual del usuario a 125 % DPI.

## H6 — IPC automático desde INDEC

### H6.0 — Spike bloqueante

Antes de codificar:

- Crear cuenta en `api.indec.gob.ar` y obtener token.
- Encontrar en el catálogo/documentación el servicio de IPC Nacional.
- Documentar: endpoint, método, header de auth, parámetros, formato JSON,
  cobertura temporal, límites de uso y vencimiento del token.
- Verificar que devuelva IPC Nacional mensual (índice o variación).
- **Si no hay servicio IPC o no hay endpoint estable: detenerse y reportar.**
  No sustituir por `datos.gob.ar` sin aprobación explícita.

### Implementación

- **ADR-0003:** fuente `api.indec.gob.ar`, manejo de token, redondeo,
  política de conflicto manual/API y fallback si el spike falla.
- **Dominio:** `variacion_bp_desde_indices` con `Decimal`, half-up a 1 bp.
- **Aplicación:** puerto `FuenteIpc`; `ServicioSincronizacionIpc` con
  `previsualizar()` e `importar()`; importación atómica e idempotente.
- **Infraestructura:** cliente HTTP con timeout, reintentos, User-Agent,
  validación de JSON y errores en castellano. Token en Windows Credential
  Manager (`keyring`) o DPAPI; **nunca en la base, logs ni backups**.
- **Base:** migración 0002 para `indice_milesimos` y `actualizado_en`;
  upsert masivo por `(anio, mes)`.
- **UI Configuración:** card “INDEC” con token enmascarado, “Probar conexión”,
  “Guardar token”, “Borrar token”, estado y vencimiento.
- **UI Ajustes IPC:** botón “Actualizar desde INDEC”, consulta en segundo plano,
  preview con estados “Nuevo / Actualizado / Sin cambios / Manual protegido”,
  checkboxes y confirmación explícita para reemplazar manuales.
- **Reglas:** sin token, el botón queda deshabilitado con el motivo; la carga
  manual sigue disponible. Editar una fila de API la marca como `manual`.
  No se auto-aplican ajustes: solo se importan valores.

### Terminado cuando

- Funciona dentro del `.exe`, sin congelar la UI.
- Sin token: mensaje claro y carga manual operativa.
- Token inválido/vencido, 429, timeout o JSON roto: banner claro, sin escrituras
  parciales.
- Dos clics no duplican; una revisión de un mes anterior se previsualiza.
- Los valores manuales no se pisan sin confirmación.
- “Fuente: INDEC” y última sincronización visibles.

### Cierre H6 (2026-11-03)

- **Spike H6.0:** Go confirmado sobre `GET https://api.indec.gob.ar/v1/ipc_nacional` (`tipo_de_indicador=eq.Indice`, serie nacional general con 4 decimales desde `201612`).
- **ADR-0003** publicado en `docs/adr/0003-ipc-automatico-indec.md` e indexado en `docs/adr/README.md`.
- **Implementación completa en las 4 capas:**
  - Dominio: `variacion_bp_desde_indices` (`Decimal`, half-up a 1 bp) e `indice_a_milesimos`.
  - Aplicación: `ServicioSincronizacionIpc` + puertos `FuenteIpc` y `AlmacenTokenIpc`.
  - Infraestructura: `ClienteIndecHttp` (`urllib.request`, timeout, reintentos ante 502/503/504/red, `parse_float=Decimal`), `AlmacenTokenCredencialesWindows` (`Advapi32.dll` vía `ctypes`), migración `0002_ipc_indec.sql` y `guardar_ipc_masivo` transaccional.
  - UI: card `INDEC` en Configuración y vista previa `VistaPreviaSincronizacionIpc` en Ajustes IPC con consulta en hilo de fondo + `queue.Queue`.
- **Tests:** `260 passed` en `.venv\Scripts\python -m pytest tests/` (`test_arquitectura.py` y `test_contraste.py` en verde).
- **Build y smoke:** `dist\Brickly.exe` reconstruido con `Brickly.spec` (`13.775.670` bytes, SHA256 `2fbc837275d6331dc4f01821043aba2e03ff05b741ecd88146f45ce83be3d100`); verificado arranque real y migración automática a esquema v2.


## H7 — Excel completo

### Contenido

- **Resumen:** una fila por departamento actual (incluye sin contrato), con
  inquilino, contrato, cuota vigente, deuda de capital, mora, total y último pago.
- **Deudas:** cuotas impagas de cualquier período, con días de atraso y mora a hoy.
- **Pagos:** todos los pagos con medio, nota e imputación a cuotas.
- **Cuotas:** historial completo con estado, pagado, mora y saldo.
- **Contratos:** vigentes e históricos, con fechas, monto, ciclo y redondeo.
- Opcional: **Ajustes IPC** si el tiempo alcanza.

### Implementación

- `openpyxl` en `requirements.txt`.
- `LibroExportable` puro en `aplicacion`; puerto `EscritorExcel`; adaptador
  `openpyxl` en `infraestructura`.
- UI: card “Excel completo” en Informes, `.xlsx`, estados “Exportando…”,
  error si el archivo está abierto en Excel, botón deshabilitado sin datos.
- Formato: encabezados en negrita, autofiltro, panel congelado, fechas
  `dd/mm/aaaa`, montos en pesos, totales, vencidas resaltadas.
- Sanitizar textos que empiecen con `=`, `+`, `-` o `@`.
- Los cálculos y totales se hacen en centavos; la hoja solo formatea.

### Terminado cuando

- El `.xlsx` abre en Excel/LibreOffice.
- Los totales coinciden con Panel/Cobranzas.
- Acentos, fechas y montos salen bien.
- El build empaquetado incluye `openpyxl`.

### Cierre H7 (2026-11-04)

- **Dependencia:** `openpyxl==3.1.5` agregada en `requirements.txt` y empaquetada en `dist\Brickly.exe`.
- **Aplicación (`brickly/aplicacion/informes.py`):**
  - `LibroExportable`, `HojaExportable`, `ColumnaExcel` y `FilaExcel` puros en centavos enteros para las 6 hojas: **Resumen**, **Deudas**, **Pagos**, **Cuotas**, **Contratos** y **Ajustes IPC**.
  - `sanitizar_texto_excel` prefija `'` en textos que comienzan con `=`, `+`, `-` o `@` (aplicado en `LibroExportable`, CSV y como defensa en profundidad en `EscritorExcelOpenpyxl`).
  - `ServicioInformes.armar_libro_completo()` y `exportar_excel_completo(ruta)`; puerto `EscritorExcel` y consultas en `RepositorioInformes` (`puertos.py`).
- **Infraestructura:**
  - `brickly/infraestructura/excel.py`: `EscritorExcelOpenpyxl` con encabezados en negrita, autofiltro, `freeze_panes = "A2"`, fechas `dd/mm/yyyy`, montos en pesos con `Decimal(centavos)/100` (cero `float`), fila `Totales` en negrita, resaltado de filas vencidas (`#FEE2E2` / `#991B1B`), escritura atómica (`os.replace`) y mensaje claro en castellano ante `PermissionError` si el archivo está abierto en Excel.
  - `brickly/infraestructura/db/repositorios/informes.py`: consultas anti N+1 para Resumen, Pagos, Contratos y Ajustes IPC.
- **UI (`brickly/ui/vistas/informes.py`):** card **Excel completo** (`.xlsx`, estado `Exportando…`, deshabilitado con motivo si no hay departamentos, banner con ruta o detalle de error).
- **Tests y Build:** `275 passed` en `.venv\Scripts\python -m pytest tests/` (`test_informes_h7_excel.py` + `test_arquitectura.py` prohibiendo `openpyxl` fuera de `infraestructura`); `dist\Brickly.exe` reconstruido (`14.529.350` bytes, SHA256 `8123f8445796d84e7d70b2a1caa37f697f76c74c3c910092c46e16911c7c4158`) y verificado con smoke UI + arranque real del `.exe`.

## H8 — Constancia de pago mensual (PDF)

### Alcance

- Generar un PDF que certifique que la cuota de un período fue pagada.
- La constancia es **por unidad + período** (una cuota), no un resumen de todo
  el mes. El período se elige con el navegador de mes de **Cobranzas**.
- Solo se habilita para cuotas en estado `pagada` (capital totalmente
  imputado). Una cuota parcial o impaga no genera documento: se muestra el
  motivo y el saldo.
- El documento certifica **solo ese período**. No afirma que la unidad esté al
  día ni que no existan otras deudas.
- Al final, bloque de firma con línea, nombre y rol: **Propietario/a o
  Administrador/a**. Se usa `departamentos.propietario`; si no está cargado,
  `admin_nombre` de Configuración; si tampoco, la línea queda vacía para
  firmar a mano. Si hay ambos, se muestran los dos y la línea queda para quien
  firma.
- Firma **visual**, no digital: no hay certificado ni validez criptográfica.
- No es factura ni comprobante fiscal.
- Sin migración ni escrituras: se leen las tablas existentes y el PDF se
  genera en el momento. No se registra la emisión.

### Contenido del documento

- Encabezado: "Constancia de pago" + emisor (`admin_nombre`,
  `admin_telefono`, `admin_email` si están cargados).
- Unidad: `nombre_unidad(direccion, piso, depto)`.
- Inquilino: el del contrato de esa cuota, aunque el contrato ya esté cerrado
  (no el inquilino vigente de la unidad).
- Período: `octubre 2026`.
- Detalle imputado a esa cuota: capital, mora cobrada y total.
- Pagos: por cada pago imputado a la cuota, fecha, medio y monto. Si un pago
  cubrió varias cuotas, se muestra solo la parte imputada a esta.
- Fecha de emisión: `Reloj.hoy()`.
- Pie: "La presente constancia certifica el pago de la cuota del período
  indicado y no implica que la unidad esté libre de otras obligaciones."
- Bloque de firma al final: línea, nombre disponible y rol.
- Formatos es-AR: fechas `dd/mm/aaaa`, montos `$ 12.800,00`, textos con
  acentos y ñ.

### Implementación

- **Dependencia:** `reportlab` (licencia BSD; fuentes estándar Helvetica/WinAnsi
  alcanzan para acentos y ñ). Verificar el build con PyInstaller; si el peso o
  el empaquetado no cierran, evaluar alternativa **con ADR** (no cambiar de
  librería en silencio).
- **ADR-0004:** formato de la constancia, librería, política de firma, datos
  incluidos, no-goals (no fiscal, no firma digital) y manejo de errores.
- **Aplicación:** `brickly/aplicacion/constancias.py` con `ConstanciaPago`
  (DTO puro) y `ServicioConstancias`:
  - `disponibles(anio, mes)` → cuotas pagadas del período (unidad, inquilino,
    cuota_id).
  - `generar(cuota_id, ruta)` → valida `pagada`, arma el DTO y delega el
    render en el puerto.
- **Puertos:** `RepositorioConstancias` (`listar_pagadas_del_mes`,
  `obtener_constancia`) y `GeneradorPdf` (`generar(documento, ruta)`).
- **Infraestructura:** `repositorios/constancias.py` (SQL con JOIN a pagos e
  imputaciones; una consulta por constancia, sin N+1) y `pdf.py`
  (`GeneradorPdfReportlab`). Render en memoria y publicación atómica
  (`os.replace`) para no dejar archivos a medias.
- **Contenedor y composición:** `Servicios.constancias`, cableado en `main.py`
  con `RepositorioConstanciasSQLite` y `GeneradorPdfReportlab`.
- **UI/presenter:** `brickly/ui/presenters/constancia.py` con
  `ConstanciaPresentada` y `preparar_constancia(cuota_id)`; `PanelConstancia`
  (380 px, mismo patrón que `PanelPago`) con vista previa y `[ Generar PDF ]`.
  En `Cobranzas → Mes`, click en una fila `pagada` abre el panel; si la cuota
  no está pagada, no abre. Bajo la tabla, ayuda: "Click en una cuota pagada
  para generar su constancia."
  - Alternativa aceptable (no duplicar): card "Constancia de pago" en Informes
    con selector de mes.
- **Configuración:** actualizar la ayuda de "Datos del administrador" (hoy
  dice "Para recibos y exportaciones futuras.") a "Para constancias de pago y
  exportaciones."
- **Archivo:** diálogo nativo, default Escritorio, nombre
  `constancia-<unidad>-<mes>-<anio>.pdf` (sin acentos ni caracteres
  inválidos).
- **Errores:** cuota impaga/parcial, sin pagos, PDF abierto en otro programa,
  error de escritura → banner claro; nunca un PDF parcial.
- **Tests:** builder puro (montos, fechas, textos, firma), servicio (solo
  pagadas), repositorio sobre DB en memoria, PDF real en `tmp_path`
  (cabecera `%PDF`, tamaño > 0, acentos sin excepción), presenter y
  arquitectura.

### Terminado cuando

- El PDF abre en Edge/Acrobat/LibreOffice y muestra acentos, ñ y montos bien.
- Solo se genera para cuotas pagadas; parcial o impaga queda bloqueada con el
  motivo y el saldo.
- La firma muestra propietario o administrador (o línea vacía si no hay datos).
- Funciona dentro del `.exe`, sin congelar la UI ni dejar archivos parciales.
- Repetir la generación no duplica ni modifica datos.
- Tests verdes, incluido `test_arquitectura.py`.
- README: la constancia figura en las funciones y en el uso.

### Cierre H8 y Release 1.1.0 (2026-11-04)

- **ADR-0004:** documentado en `docs/adr/0004-constancia-pago-pdf.md` e indexado
  en `docs/adr/README.md`.
- **Dependencia:** `reportlab==5.1.0` agregada en `requirements.txt` y bloqueada
  en `dominio`, `aplicacion` y `ui` por `tests/test_arquitectura.py`.
- **Aplicación (`brickly/aplicacion/constancias.py`):** `ConstanciaPago`,
  `PagoConstancia`, `CuotaPagadaDisponible`, `armar_constancia_pago` (solo
  cuotas `pagada`; bloquea `pendiente`, `parcial` y `vencida` con el motivo y el
  saldo pendiente), `resolver_firma_constancia`, `nombre_archivo_constancia` y
  `ServicioConstancias`. Puertos `RepositorioConstancias` y `GeneradorPdf` en
  `brickly/aplicacion/puertos.py`, `Servicios.constancias` en
  `brickly/aplicacion/contenedor.py` y cableado en `main.py`.
- **Infraestructura:** `brickly/infraestructura/db/repositorios/constancias.py`
  (`RepositorioConstanciasSQLite` con una sola consulta SQL por operación y
  preservación del inquilino del contrato de la cuota) y
  `brickly/infraestructura/pdf.py` (`GeneradorPdfReportlab` en A4 con fuentes
  Helvetica/WinAnsi, render en memoria y escritura atómica con `os.replace`).
- **UI y Presentador:** `brickly/ui/presenters/constancia.py`
  (`ConstanciaPresentada`, `preparar_constancia`, `PresenterConstancia`),
  `PanelConstancia` (380 px) en `brickly/ui/vistas/cobranzas.py` al hacer clic
  en una cuota `pagada` en `Cobranzas → Mes` + ayuda bajo la tabla, y ayuda de
  administrador actualizada en `brickly/ui/vistas/configuracion.py`.
- **Tests, Build y PDF de ejemplo:** `283 passed` en `2.85s` (incluyendo
  `tests/test_constancias_h8.py` y `tests/test_arquitectura.py`), `VERSION = "1.1.0"`,
  `dist\Brickly.exe` (`23.360.560 bytes`, SHA256 `DC23F35BB7DF4D7D8947964D20CC3ABAB78D39B74D184D7236AFE07BB6E14802`),
  `dist\SHA256.txt` y constancia de ejemplo generada en
  `dist\constancia-av-santa-fe-2140-4-b-octubre-2026.pdf`.

## Orden y checkpoints

1. **H5 completo** → reportar y esperar OK.
2. **H6.0 spike** → decisión: hay servicio IPC o se detiene.
3. **H6 completo** → reportar.
4. **H7 completo** → reportar.
5. **H8 completo** → reportar.
6. **Release 1.1** → build, smoke, README, SHA256.

## Definición de terminado 1.1

- Tests verdes, incluido arquitectura.
- Tests nuevos de dominio, aplicación, infraestructura y textos/presenters.
- Smoke del `.exe` y 125 % DPI.
- Sin regresiones en Panel, Cobranzas, Ajustes, Informes y Configuración.
- README y release notes actualizados.
- La constancia PDF abre, muestra acentos y firma, y solo se genera para
  cuotas pagadas.
- `docs/arranque-h0.md` conservado.

## Reporte final obligatorio

Cuando termine 1.1, el agente debe entregar:

1. Resumen de lo hecho.
2. Archivos creados, modificados y renombrados.
3. Migraciones y resultado de la migración de datos.
4. Tests: comando, cantidad y resultado.
5. Build: ruta, tamaño y SHA256.
6. Smoke: pantallas y escenarios probados.
7. README: secciones cambiadas.
8. Pendientes, riesgos y decisiones abiertas.
9. Constancia: ruta del PDF de ejemplo y qué se verificó (solo pagadas, firma,
   acentos).

## Riesgos

- `api.indec.gob.ar` exige cuenta/token y hoy el catálogo público muestra
  0 servicios; H6.0 puede bloquear la feature.
- La migración de datos es de una sola dirección: copiar, verificar y conservar.
- `openpyxl` agrega peso al `.exe`; verificar PyInstaller.
- `reportlab` agrega peso al `.exe`; verificar PyInstaller y el arranque del
  binario.
- La constancia no es comprobante fiscal ni firma digital: el texto y el
  README deben decirlo para no prometer validez legal.
- El PDF incluye datos del inquilino; se genera local y el usuario elige
  dónde guardarlo (no se envía a ningún lado).
- Scope creep: todo lo no listado va a 1.2.
