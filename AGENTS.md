# AGENTS.md — app de departamentos

App de escritorio (Python + SQLite + CustomTkinter) para administrar
departamentos: cuotas, mora por atraso y ajuste trimestral por IPC.

## Entorno

- Dependencias en `.venv` (customtkinter, pytest, pyinstaller — ver
  `requirements.txt`). Todo comando Python se corre con el venv:
  `.venv\Scripts\python -m ...`
- Recrear desde cero: `py -m venv .venv` y
  `.venv\Scripts\python -m pip install -r requirements.txt`.
- En Windows, el alias `python` del Store no funciona: usar `py` (launcher)
  para armar el venv, o directamente `.venv\Scripts\python`.
- Empaquetado reproducible: PyInstaller con `--collect-all customtkinter` y
  las migraciones como data (`gestion\infraestructura\db\migraciones`); el
  comando vigente queda registrado en `GestionDepartamentos.spec`.

## Antes de tocar estructura o datos

- Antes de tocar la UI, leer `docs/ux/especificacion-ux-ui.md` (spec UX/UI
  vigente: tokens, componentes, pantallas, estados y criterios de aceptación).
- Leer `docs/adr/README.md` (índice de decisiones). Vigentes: **ADR-0001**
  (4 capas con dependencias hacia adentro) y **ADR-0002** (reglas de negocio
  del MVP: ajuste IPC, redondeo, vencimiento, mora). Una decisión aceptada se
  aplica, no se re-deriva en silencio; si cambia, se supersede con un ADR nuevo.
- Correr `.venv\Scripts\python -m pytest tests/` tras cualquier cambio. El test
  de dependencias (`tests/test_arquitectura.py`) es obligatorio en verde: si
  falla, se mueve el código de capa, no se relaja el test.

## Reglas operativas vigentes (ADR-0001)

- SQL solo en `gestion/infraestructura/db/`.
- Montos en centavos (`int`), nunca floats.
- Fechas vía `Reloj` inyectable.
- La UI no importa infraestructura; el dominio no importa nada del proyecto.

## Estado actual

H0, H1, H2, H3 y H4 implementados (2026-10-16):
- **H0:** composition root (`main.py`), conexión + migrador, shell con
  navegación (`gestion/ui/ventana.py`), componentes base de §2 y
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
  - **Dominio (`gestion/dominio/ipc.py`):** cálculo de acumulación compuesta
    en puntos básicos enteros (`acumular_variaciones_bp`), ventana de meses base
    por ciclo (`meses_base`), aplicación de variación con redondeo exacto
    (`aplicar_variacion`), promedio ponderado (`variacion_promedio_bp`) y
    entidades `IpcMensual` y `AjusteCalculado` (invariante: override exige motivo).
  - **Aplicación (`gestion/aplicacion/ajustes.py`):** `ServicioAjustesIpc` con
    ABM de IPC mensual, detección de contratos con ciclo vencido este mes,
    cálculo de cuotas ajustadas con preview en vivo, y aplicación atómica
    ("todo o nada", ADR-0002 §1).
  - **Infraestructura (`gestion/infraestructura/db/repositorios/ajustes.py`):**
    `RepositorioAjustesSQLite` para tablas `ipc_valores` y `ajustes`, con
    actualización transaccional de cuotas vigentes y validación optimista.
  - **Puertos y Contenedor:** puerto `RepositorioAjustes` en `puertos.py`,
    servicio cableado en `Servicios` y en el composition root (`main.py`).
  - **UI (`gestion/ui/vistas/ajustes_ipc.py`, montada en `ventana.py`):**
    tres secciones con segmented button — **Valores IPC** (form Mes/Año/Variación
    + tabla con ✎/✕ y confirmaciones nativas si un ajuste pendiente lo usa),
    **Ajustes por aplicar** (lista con chips `Listo`/`Faltan datos` con link a
    los períodos faltantes + `Revisar y aplicar`) e **Historial** (solo lectura).
    Wizard de 3 pasos con stepper dentro de la pantalla (Selección solo con
    varios contratos · Revisión con celda «IPC aplicado» editable → chip
    `Ajustado a mano` + motivo obligatorio · Resultado); salir a mitad avisa
    si hubo ediciones; `PanelIpc` lateral de 380 px para editar. Presentador
    `gestion/ui/presenters/ajuste.py` (DTOs `FilaIpcPresentada`,
    `FilaAjustePresentada`, `FilaHistorialPresentada`); formatos nuevos en
    `formato.py` (`formatear_monto_con_signo`, `formatear_mes_abreviado`,
    `formatear_rango_meses`, `formatear_porcentaje(con_signo)`); chips
    `listo`/`faltan_datos` en `chip.py`; `Columna.ancho_accion` en `tabla.py`;
    `Campo` sin etiqueta (`etiqueta=None`) en `formulario.py`.
- **H4 — Panel, Informes y Configuración:**
  - **Aplicación:** `gestion/aplicacion/informes.py` (`ServicioInformes`:
    `estado()`, exportación de estado de cuenta / cobranzas del mes / morosos y
    `respaldar`; builders CSV puros) y `gestion/aplicacion/configuracion.py`
    (`ServicioConfiguracion` sobre la tabla `configuracion` clave/valor de la
    migración 0001 — sin migración nueva). Puertos nuevos en `puertos.py`:
    `RepositorioConfiguracion`, `RepositorioInformes`, `EscritorArchivos` y
    `Respaldador`.
  - **Infraestructura:** `repositorios/configuracion.py` (UPSERT) y
    `repositorios/informes.py` (una consulta por informe);
    `gestion/infraestructura/archivos.py` con `EscritorArchivosSistema`
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
    alerta de contratos vencidos; `VERSION`/`FECHA_BUILD` en `gestion/__init__.py`.
  - **Presentador:** `gestion/ui/presenters/panel.py` (DTOs `PanelDatos`,
    `FilaVencidaPresentada`, `PasoOnboarding`, `AlertaPresentada`).
  - **Tests:** suite completa en verde (`229 passed`), incluyendo
    `test_aplicacion_configuracion.py`, `test_aplicacion_informes.py`,
    `test_presenter_panel.py` y `test_informes_h4.py` (CSV y respaldo reales
    sobre `tmp_path`). Smoke manual de las tres vistas y de la navegación con
    contexto (DB en memoria).

- Pendiente para cerrar visualmente: pasada del usuario a 125 % DPI
  (checklist §6.4, incluye Ajustes IPC, Panel, Informes y Configuración);
  recién ahí se borra `docs/arranque-h0.md`.
- Empaquetado: `dist\GestionDepartamentos.exe` reconstruido (2026-10-16) con
  `GestionDepartamentos.spec`; verificado el arranque real del binario
  (ventana "Gestión de Departamentos") y las pantallas H4 con un build
  temporal del mismo spec dentro del entorno congelado (smoke de Panel,
  Informes, Configuración, Ajustes IPC y navegación con contexto).

