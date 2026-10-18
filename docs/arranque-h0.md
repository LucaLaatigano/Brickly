# Arranque H0 — orden de trabajo para senior-dev

- **Fecha:** 2026-10-15 · **Estado:** repositorio listo, H0 puede empezar
- Este archivo es temporal: se lee al arrancar H0 y se borra cuando H0 cierre
  (el estado de largo plazo vive en `AGENTS.md`).

## Leer primero (en este orden)

1. `AGENTS.md` — entorno: todo comando Python va con `.venv\Scripts\python`
   (el `python` del PATH es el stub del Store, no sirve).
2. `docs/adr/0001-arquitectura-de-capas.md` y `docs/adr/0002-reglas-de-negocio-mvp.md`.
3. `docs/ux/especificacion-ux-ui.md` — §1–§2 (fundaciones y componentes) y
   **§6 completo**: archivos a crear, reglas duras, orden H0–H4 y el
   "terminado" de cada pantalla.
4. `gestion/infraestructura/db/migraciones/0001_inicial.sql` — esquema ya
   verificado contra SQLite real (lo cubre `tests/test_esquema_inicial.py`).
   El migrador debe: correr el script pendiente y setear `user_version = 1`;
   la conexión debe abrir con `PRAGMA foreign_keys = ON`.

## Orden recomendado dentro de H0 (riesgo primero)

1. **Esqueleto caminante + exe**: `main.py` (composition root) + conexión y
   migrador + `ventana.py` con el shell vacío. Empaquetar YA y verificar que
   el exe abre y crea la base desde cero (la migración corre una sola vez; la
   segunda apertura no re-migra). Es el riesgo más barato de despejar ahora.
   - Comando base: `pyinstaller --noconsole --onefile --name "GestionDepartamentos" --collect-all customtkinter main.py`
   - `--collect-all customtkinter` es obligatorio (CTk trae data files). Si el
     arranque onefile queda lento por el unpack, evaluar `--onedir`.
2. **Base UI**: `estilo.py`, `formato.py` y componentes de §2 — empezando por
   `tabla.py` ("el más importante, hacerlo primero y bien").
3. **ABM de departamentos**: capas completas en vertical (dominio →
   aplicación con puertos → infraestructura con repositorio SQLite → vistas).
   El detalle de departamento arranca mostrando los estados vacíos de §3.3
   (cargar contrato: final de H0 o inicio de H1, secuencia a ajustar con el EM
   si H0 crece).
4. **Cierre de H0**: checklist de §6.4 (estados visibles, textos exactos,
   funciona dentro del exe, probado a 125 % DPI).

## Decisiones tuyas (con propuesta)

- **Ubicación de la base:** propuesta `%APPDATA%\GestionDepartamentos\datos.sqlite3`
  — por usuario y escribible, y funciona tanto si el exe vive en Program Files
  como siendo onefile (el temp del unpack es volátil). La pantalla Configuración
  la muestra en solo-lectura con "Abrir carpeta".
- Nombres de puertos, DTOs y casos de uso de `aplicacion`: los fija tu
  implementación; el patrón de conexión vista↔servicios está en §6.3.

## Verificación en cada paso

- `.venv\Scripts\python -m pytest tests/` SIEMPRE en verde (el test de
  dependencias es intocable: si falla, se mueve el código de capa, no el test).
- El exe abre, crea la base desde cero, y la segunda apertura no re-migra.
- Textos y formatos exactos de la spec (§1.4 y §3).

## Alcance

- **En H0:** shell + navegación, componentes base, departamentos de punta a
  punta, migrador + conexión, spike de empaquetado.
- **Fuera de H0:** cobranzas, mora, ajustes IPC, informes, configuración
  (H1–H4, ver §6.4 de la spec).
