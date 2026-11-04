# AGENTS.md — Brickly

App de escritorio (Python + SQLite + CustomTkinter) para administrar
departamentos: cuotas, mora por atraso y ajuste trimestral por IPC.

## Entorno

- Dependencias en `.venv` (customtkinter, openpyxl, reportlab, pytest,
  pyinstaller — ver `requirements.txt`). Todo comando Python se corre con el
  venv: `.venv\Scripts\python -m ...`
- Recrear desde cero: `py -m venv .venv` y
  `.venv\Scripts\python -m pip install -r requirements.txt`.
- En Windows, el alias `python` del Store no funciona: usar `py` (launcher)
  para armar el venv, o directamente `.venv\Scripts\python`.
- Empaquetado reproducible: PyInstaller con `--collect-all customtkinter` y
  las migraciones como data (`brickly\infraestructura\db\migraciones`); el
  comando vigente queda registrado en `Brickly.spec`.

## Antes de tocar estructura o datos

- Antes de tocar la UI, leer `docs/ux/especificacion-ux-ui.md` (spec UX/UI
  vigente: tokens, componentes, pantallas, estados y criterios de aceptación).
- Leer `docs/adr/README.md` (índice de decisiones). Vigentes: **ADR-0001**
  (4 capas con dependencias hacia adentro), **ADR-0002** (reglas de negocio
  del MVP: ajuste IPC, redondeo, vencimiento, mora), **ADR-0003**
  (sincronización automática de IPC Nacional desde API INDEC) y **ADR-0004**
  (constancia de pago mensual en PDF con firma visual). Una decisión aceptada
  se aplica, no se re-deriva en silencio; si cambia, se supersede con un ADR
  nuevo.
- Correr `.venv\Scripts\python -m pytest tests/` tras cualquier cambio. El test
  de dependencias (`tests/test_arquitectura.py`) es obligatorio en verde: si
  falla, se mueve el código de capa, no se relaja el test.

## Reglas operativas vigentes (ADR-0001)

- SQL solo en `brickly/infraestructura/db/`.
- Montos en centavos (`int`), nunca floats.
- Fechas vía `Reloj` inyectable.
- La UI no importa infraestructura; el dominio no importa nada del proyecto.

## Estado actual

H0, H1, H2, H3, H4, H5, H6, H7 y H8 implementados — **Release 1.1.0** (2026-11-04):
- **H0:** composition root (`main.py`), conexión + migrador, shell con
  navegación (`brickly/ui/ventana.py`), componentes base de §2 y
  **departamentos de punta a punta** (ABM en panel lateral de 380 px).
- **H1 — cobranzas (generación de cuotas del mes + tabla) y contratos:**
  `RelojSistema` cableado en `main.py`, entidades de dominio (`Contrato`,
  `Inquilino`, `Cuota`), carga/edición/renovación de contratos e historial de
  cuotas en el detalle de departamento (§3.3), `ChipEstado` en tablas y pantalla
  **Cobranzas** (§3.4) con navegador de mes, preview + generación mensual
  idempotente, resumen del período y tabla filtrable.
- **H2 — panel de pago + mora en UI + Atrasos:** cálculo de mora simple diaria en
  dominio (`calcular_mora_cuota`) e imputación de pagos (`Pago`,
  `imputar_pago_a_cuota`, `imputar_pago_fifo`), deuda viva por departamento,
  solapa **Atrasos** con acción `[ Cobrar ]` y `PanelPago` lateral de 380 px con
  defaults inteligentes y validación en vivo en Cobranzas y Detalle de
  departamento (§3.3–§3.4).
- **H3 — Ajustes IPC:**
  - **Dominio (`brickly/dominio/ipc.py`):** cálculo de acumulación compuesta
    en puntos básicos enteros (`acumular_variaciones_bp`), ventana de meses base
    por ciclo (`meses_base`), aplicación de variación con redondeo exacto
    (`aplicar_variacion`), promedio ponderado (`variacion_promedio_bp`) y
    entidades `IpcMensual` y `AjusteCalculado` (invariante: override exige motivo).
  - **Aplicación (`brickly/aplicacion/ajustes.py`):** `ServicioAjustesIpc` con
    ABM de IPC mensual, detección de contratos con ciclo vencido este mes,
    cálculo de cuotas ajustadas con preview en vivo, y aplicación atómica
    ("todo o nada", ADR-0002 §1).
  - **Infraestructura (`brickly/infraestructura/db/repositorios/ajustes.py`):**
    `RepositorioAjustesSQLite` para tablas `ipc_valores` y `ajustes`, con
    actualización transaccional de cuotas vigentes y validación optimista.
  - **Puertos y Contenedor:** puerto `RepositorioAjustes` en `puertos.py`,
    servicio cableado en `Servicios` y en el composition root (`main.py`).
  - **UI (`brickly/ui/vistas/ajustes_ipc.py`, montada en `ventana.py`):**
    tres secciones con segmented button — **Valores IPC** (form Mes/Año/Variación
    + tabla con ✎/✕ y confirmaciones nativas si un ajuste pendiente lo usa),
    **Ajustes por aplicar** (lista con chips `Listo`/`Faltan datos` con link a
    los períodos faltantes + `Revisar y aplicar`) e **Historial** (solo lectura).
    Wizard de 3 pasos con stepper dentro de la pantalla (Selección solo con
    varios contratos · Revisión con celda «IPC aplicado» editable → chip
    `Ajustado a mano` + motivo obligatorio · Resultado); salir a mitad avisa
    si hubo ediciones; `PanelIpc` lateral de 380 px para editar. Presentador
    `brickly/ui/presenters/ajuste.py` (DTOs `FilaIpcPresentada`,
    `FilaAjustePresentada`, `FilaHistorialPresentada`); formatos nuevos en
    `formato.py` (`formatear_monto_con_signo`, `formatear_mes_abreviado`,
    `formatear_rango_meses`, `formatear_porcentaje(con_signo)`); chips
    `listo`/`faltan_datos` en `chip.py`; `Columna.ancho_accion` en `tabla.py`;
    `Campo` sin etiqueta (`etiqueta=None`) en `formulario.py`.
- **H4 — Panel, Informes y Configuración:**
  - **Aplicación:** `brickly/aplicacion/informes.py` (`ServicioInformes`:
    `estado()`, exportación de estado de cuenta / cobranzas del mes / morosos y
    `respaldar`; builders CSV puros) y `brickly/aplicacion/configuracion.py`
    (`ServicioConfiguracion` sobre la tabla `configuracion` clave/valor de la
    migración 0001 — sin migración nueva). Puertos nuevos en `puertos.py`:
    `RepositorioConfiguracion`, `RepositorioInformes`, `EscritorArchivos` y
    `Respaldador`.
  - **Infraestructura:** `repositorios/configuracion.py` (UPSERT) y
    `repositorios/informes.py` (una consulta por informe);
    `brickly/infraestructura/archivos.py` con `EscritorArchivosSistema`
    (UTF-8 con BOM para Excel) y `RespaldadorSQLite` (backup API, mapea
    `sqlite3.Error` → `OSError` para que la UI no conozca sqlite3).
  - **UI:** `vistas/panel.py` (4 KPIs del mes, top 5 de vencidas con acceso
    directo al pago en Cobranzas/Atrasos — F3, alertas calculadas: IPC
    faltante / respaldo vencido / contrato vencido sin renovar, checklist de
    puesta en marcha F1 hasta el primer pago, banner con CTA de generación y
    estado de error con reintento), `vistas/informes.py` (4 cards con diálogo
    nativo, estado `Exportando…`, banner con ruta y botones deshabilitados con
    motivo si no hay datos) y `vistas/configuracion.py` (predeterminados de
    contrato, datos del admin, ruta de base + `Abrir carpeta`, respaldo manual,
    `Acerca de` con versión/build; guardado explícito con validación inline).
    `ventana.py` monta las tres y `ir_a` acepta `opciones` (navegación con
    contexto: `modo_inicial`, `cuota_inicial_id`, `abrir_primer_pago`,
    `departamento_id`); `VistaCobranzas` suma `abrir_primer_pago`; el export de
    §3.3 en el detalle quedó habilitado vía `ServicioInformes` (filtro por
    departamento); `Banner` admite `accion=(texto, callback)`; `TarjetaKPI`
    admite `al_click`; `FilaDepartamento.fecha_contrato_vencido` alimenta la
    alerta de contratos vencidos; `VERSION`/`FECHA_BUILD` en `brickly/__init__.py`.
  - **Presentador:** `brickly/ui/presenters/panel.py` (DTOs `PanelDatos`,
    `FilaVencidaPresentada`, `PasoOnboarding`, `AlertaPresentada`).
  - **Tests:** suite completa en verde (`229 passed`), incluyendo
    `test_aplicacion_configuracion.py`, `test_aplicacion_informes.py`,
    `test_presenter_panel.py` y `test_informes_h4.py` (CSV y respaldo reales
    sobre `tmp_path`). Smoke manual de las tres vistas y de la navegación con
    contexto (DB en memoria).

- **H5 — Identidad Brickly y migración de datos:**
  - Paquete `gestion/` renombrado a `brickly/`; imports, tests, ADRs, spec UX
    y `AGENTS.md` actualizados. `GestionDepartamentos.spec` pasó a
    `Brickly.spec` y el ejecutable a `dist\Brickly.exe`.
  - `brickly/infraestructura/db/conexion.py` ahora usa
    `%APPDATA%\Brickly\datos.sqlite3` y expone
    `ruta_base_datos_legacy()` para la carpeta vieja.
  - `brickly/infraestructura/db/migracion_datos.py` copia una sola vez la base
    de `%APPDATA%\GestionDepartamentos` con la API de backup de SQLite,
    verifica `PRAGMA integrity_check`, publica la copia de forma atómica y
    **nunca borra la base vieja**. `main.py` la invoca antes de abrir la base y
    muestra un diálogo de error si la migración falla.
  - README reescrito para instalar desde GitHub Releases (`Brickly.exe` +
    `SHA256.txt`), con SmartScreen, actualización, desinstalación, datos,
    respaldo, ejecución desde código y build con `Brickly.spec`.
  - `.gitignore` agregado para `__pycache__`, `.venv`, `build`, `dist` y
    archivos de datos/exportaciones.
  - Tests nuevos en `tests/test_migracion_datos.py` (copia, no pisado,
    ausencia de origen, origen corrupto y rutas APPDATA): suite completa
    `234 passed`.

- **H6 — IPC automático desde INDEC (ADR-0003):**
  - **Spike H6.0:** verificado contra `GET https://api.indec.gob.ar/v1/ipc_nacional`
    (`clasificador=eq.IPC`, `nivel=eq.Nivel General`, `codigo=eq.0`,
    `region=eq.Nacional`, `tipo_de_indicador=eq.Indice`, 118 períodos desde
    `201612` con 4 decimales). Decisión documentada en
    `docs/adr/0003-ipc-automatico-indec.md`.
  - **Dominio (`brickly/dominio/ipc.py`):** `variacion_bp_desde_indices` con
    `Decimal` y `ROUND_HALF_UP` a `1 bp` (rechaza `float`/`bool`),
    `indice_a_milesimos` y `IpcMensual.indice_milesimos` opcional.
  - **Aplicación (`brickly/aplicacion/sincronizacion_ipc.py`):**
    `ServicioSincronizacionIpc` con administración de token, lectura de
    vencimiento real del JWT (`exp` = 180 días), `probar_conexion()`,
    `consultar_remoto()`, `previsualizar()` (estados `nuevo`, `actualizado`,
    `sin_cambios`, `manual_protegido`) e `importar()` atómico e idempotente.
    Puertos `FuenteIpc` y `AlmacenTokenIpc` en `puertos.py`; cableado en
    `Servicios` (`contenedor.py`) y `main.py`.
  - **Infraestructura:** `brickly/infraestructura/indec.py` (`ClienteIndecHttp`
    con timeout, reintentos acotados ante 502/503/504 y fallas de red,
    `User-Agent` propio, parseo JSON directo a `Decimal` y mensajes en
    castellano sin exponer jamás el token) y
    `brickly/infraestructura/credenciales.py`
    (`AlmacenTokenCredencialesWindows` sobre Windows Credential Manager vía
    `ctypes`/`Advapi32.dll`, con fallback de lectura a `INDEC_TOKEN`).
  - **Base de datos:** migración aditiva
    `brickly/infraestructura/db/migraciones/0002_ipc_indec.sql`
    (`indice_milesimos` y `actualizado_en` en `ipc_valores`);
    `RepositorioAjustesSQLite.guardar_ipc_masivo` transaccional y pasaje a
    `origen = 'manual'` cuando se edita una fila importada.
  - **UI:** card `INDEC` en `brickly/ui/vistas/configuracion.py` (token
    enmascarado, estado y vencimiento JWT, `Guardar token`, `Probar conexión`
    en hilo de fondo con `queue.Queue` y `Borrar token`); barra `Fuente: INDEC`
    + botón `Actualizar desde INDEC` y `VistaPreviaSincronizacionIpc` inline en
    `brickly/ui/vistas/ajustes_ipc.py` con chips `Nuevo`, `Actualizado`,
    `Sin cambios` y `Manual protegido` y confirmación explícita antes de pisar
    valores manuales.
  - **Tests:** suite completa en verde (`260 passed`), incluyendo
    `tests/test_sincronizacion_ipc_h6.py`, `tests/test_dominio_ipc.py`,
    `tests/test_migrador.py`, `tests/test_textos_ajustes.py` y
    `tests/test_arquitectura.py`.

- **H7 — Excel completo (`.xlsx`):**
  - **Dependencia:** `openpyxl==3.1.5` en `requirements.txt` (prohibido en `dominio`, `aplicacion` y `ui` por `tests/test_arquitectura.py`).
  - **Aplicación (`brickly/aplicacion/informes.py`):** `LibroExportable`, `HojaExportable`, `ColumnaExcel` y `FilaExcel` puros con cálculos y totales en centavos enteros para las 6 hojas (**Resumen**, **Deudas**, **Pagos**, **Cuotas**, **Contratos** y **Ajustes IPC**), `sanitizar_texto_excel` contra inyección de fórmulas (`=`, `+`, `-`, `@`) y `ServicioInformes.exportar_excel_completo`. Puerto `EscritorExcel` en `puertos.py`.
  - **Infraestructura:** `brickly/infraestructura/excel.py` (`EscritorExcelOpenpyxl` con encabezados en negrita, autofiltro, `freeze_panes = "A2"`, fechas `dd/mm/yyyy`, montos `Decimal(centavos)/100` en formato moneda, totales en negrita, filas vencidas resaltadas, escritura atómica y mensaje claro si el archivo está abierto en Excel) y consultas por hoja en `RepositorioInformesSQLite` (`repositorios/informes.py`); cableado en `main.py`.
  - **UI (`brickly/ui/vistas/informes.py`):** card `Excel completo` (`.xlsx`, `Exportando…`, deshabilitado con motivo si no hay departamentos, contenedor scrollable para 125 % DPI).
  - **Tests:** suite completa en verde (`275 passed`), incluyendo `tests/test_informes_h7_excel.py` y `tests/test_arquitectura.py`.

- **H8 — Constancia de pago mensual (PDF — ADR-0004) y cierre Release 1.1:**
  - **Dependencia:** `reportlab==5.1.0` en `requirements.txt` (prohibido en `dominio`, `aplicacion` y `ui` por `tests/test_arquitectura.py`).
  - **Aplicación (`brickly/aplicacion/constancias.py`):** `ConstanciaPago`, `PagoConstancia`, `CuotaPagadaDisponible`, `armar_constancia_pago` (bloquea cuotas `pendiente`, `parcial` o `vencida` con el motivo y el saldo pendiente), `resolver_firma_constancia` (`Propietario/a o Administrador/a`), `nombre_archivo_constancia` y `ServicioConstancias`. Puertos `RepositorioConstancias` y `GeneradorPdf` en `puertos.py`; cableado en `Servicios` (`contenedor.py`) y `main.py`.
  - **Infraestructura:** `brickly/infraestructura/db/repositorios/constancias.py` (`RepositorioConstanciasSQLite` con una sola consulta SQL por operación y preservación del inquilino del contrato de la cuota) y `brickly/infraestructura/pdf.py` (`GeneradorPdfReportlab` con fuentes estándar Helvetica/WinAnsi en A4, render en `io.BytesIO`, escritura atómica con `os.replace` y mensaje claro si el archivo está abierto en otro programa).
  - **UI y Presentador:** `brickly/ui/presenters/constancia.py` (`ConstanciaPresentada`, `preparar_constancia`, `PresenterConstancia`), `PanelConstancia` lateral de 380 px en `brickly/ui/vistas/cobranzas.py` al hacer clic en una fila `pagada` de `Cobranzas → Mes` (con ayuda `"Click en una cuota pagada para generar su constancia."`) y texto de ayuda actualizado en `brickly/ui/vistas/configuracion.py`.
  - **Tests y Release 1.1.0:** `VERSION = "1.1.0"`, `FECHA_BUILD = "2026-11-04"`, suite completa en verde (`283 passed`, incluyendo `tests/test_constancias_h8.py` y `tests/test_arquitectura.py`), `dist\Brickly.exe` y `dist\SHA256.txt` generados y verificados.

- Pendiente para cerrar visualmente: pasada del usuario a 125 % DPI
  (checklist §6.4, incluye Ajustes IPC, Panel, Informes, Configuración y
  `PanelConstancia`). `docs/arranque-h0.md` se conserva por decisión del usuario,
  no se borra.




