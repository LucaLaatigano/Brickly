# ADR-0003: Sincronización automática de IPC Nacional desde API INDEC

- **Status:** aceptada
- **Fecha:** 2026-11-03
- **Aplica a:** `brickly/dominio/ipc.py`, `brickly/aplicacion/sincronizacion_ipc.py`, `brickly/aplicacion/puertos.py`, `brickly/infraestructura/indec.py`, `brickly/infraestructura/credenciales.py`, `brickly/infraestructura/db/migraciones/0002_ipc_indec.sql`, `brickly/infraestructura/db/repositorios/ajustes.py`, `brickly/ui/vistas/configuracion.py`, `brickly/ui/vistas/ajustes_ipc.py`

## Drivers

- **Evitar carga manual repetitiva y errores de tipeo** — cargar todos los meses la variación del IPC Nacional a mano es propenso a olvidos o errores al copiar decimales.
- **Exactitud aritmética (ADR-0001 y ADR-0002)** — las variaciones mensuales en Brickly se expresan en puntos básicos enteros (`100 bp = 1 %`, dos decimales de porcentaje) y nunca usan `float`.
- **Seguridad del token y empaquetado limpio** — la API de INDEC exige un token JWT por usuario. Ese secreto no puede guardarse en `datos.sqlite3` (viajaría en texto plano dentro de cada respaldo `.sqlite3`), ni aparecer en logs o errores, y la solución no debe fragilizar el ejecutable generado con PyInstaller.
- **Resiliencia operativa** — si el servicio externo falla, cambia de contrato o el token vence, la carga manual debe seguir funcionando sin bloqueo.

## Decisión

### 1. Fuente de datos y cálculo de variación desde el índice (`Decimal`, half-up a 1 bp)

- Se consume el endpoint oficial PostgREST de INDEC:
  `GET https://api.indec.gob.ar/v1/ipc_nacional` con header `Authorization: Bearer <token>`.
- Parámetros de consulta para la serie general nacional:
  `clasificador=eq.IPC&nivel=eq.Nivel%20General&codigo=eq.0&region=eq.Nacional&tipo_de_indicador=eq.Indice&select=periodo,anio,mes,valor,observaciones&order=anio.asc,mes.asc&limit=1000`.
- **Por qué `Indice` y no `v_m`:** en `api.indec.gob.ar`, el indicador `v_m` (variación mensual) se entrega redondeado a **1 solo decimal** (`1.9` %), lo que perdería precisión frente a los puntos básicos de Brickly (`100 bp = 1,00 %`). En cambio, `Indice` se publica con **4 decimales** (`12514.1508`, base dic-2016 = 100).
- El dominio calcula la variación mensual en puntos básicos a partir de dos índices consecutivos usando `decimal.Decimal` (parseado directo desde el JSON sin pasar por `float`) con redondeo `ROUND_HALF_UP` a `1 bp`:
  $$\text{variacion\_bp} = \text{round\_half\_up}\left(\left(\frac{I_t}{I_{t-1}} - 1\right) \times 10\,000\right)$$
- Para trazabilidad y auditoría, `ipc_valores` guarda además `indice_milesimos` (`round_half_up(I_t * 1000)`, entero positivo) y `actualizado_en` (migración aditiva `0002_ipc_indec.sql`).

### 2. Almacenamiento del token en Windows Credential Manager (`Advapi32.dll`)

Se evaluaron tres opciones para persistir el token fuera de SQLite:

| Opción | Pros | Contras |
|--------|------|---------|
| **A. Windows Credential Manager vía `ctypes` (`Advapi32.dll`)** | Cero dependencias nuevas, nativo de Windows, visible en el Administrador de credenciales, sin problemas de imports ocultos en PyInstaller | Código específico de Windows (con fallback simple a variable de entorno en otros entornos/tests) |
| **B. Librería `keyring`** | API de alto nivel | Agrega dependencia externa y backends dinámicos (`jaraco`/` pywin32-ctypes`) que suelen requerir hooks adicionales en PyInstaller |
| **C. Archivo propio cifrado con DPAPI (`CryptProtectData`)** | Sin dependencias externas | Obliga a gestionar un archivo adicional en `%APPDATA%\Brickly` y no es visible en la herramienta estándar de credenciales de Windows |

Se elige **A**: `AlmacenTokenCredencialesWindows` en `brickly/infraestructura/credenciales.py` invoca `CredWriteW`, `CredReadW`, `CredDeleteW` y `CredFree` de `Advapi32.dll` sobre la credencial genérica `Brickly/indec_api_token` (`CRED_PERSIST_LOCAL_MACHINE`). Si no hay credencial guardada en el Credential Manager y el usuario no la borró explícitamente en la sesión, se admite como fallback de lectura la variable de entorno `INDEC_TOKEN`.

**Vencimiento real del JWT:** aunque la ayuda del portal menciona 12 meses, el JWT emitido por `api.indec.gob.ar` contiene los claims `iat` y `exp` con una vigencia exacta de **180 días (6 meses)**. Brickly decodifica el payload base64url del JWT con la biblioteca estándar para informar la fecha exacta de vencimiento en Configuración y advertir cuando haya expirado.

### 3. Política de conflicto `manual` vs. `api` y vista previa obligatoria

- **Sin auto-aplicación de ajustes:** sincronizar desde INDEC solo actualiza el catálogo `ipc_valores`; los contratos cuyos ciclos vencen siguen requiriendo pasar por el wizard de `Ajustes por aplicar` (ADR-0002 §1).
- **Vista previa antes de escribir:** al pulsar `Actualizar desde INDEC`, la consulta HTTP corre en un hilo de fondo para no congelar la interfaz y presenta cada período clasificado en uno de cuatro estados:
  1. `nuevo`: no existe en `ipc_valores` (seleccionado por defecto).
  2. `actualizado`: existe con `origen = 'api'` y cambió su variación o índice (seleccionado por defecto).
  3. `sin_cambios`: ya existe con la misma `variacion_bp` (desmarcado).
  4. `manual_protegido`: existe con `origen = 'manual'` y difiere del valor oficial (desmarcado por defecto; nunca se pisa en silencio).
- **Confirmación explícita para pisar manuales:** si el usuario marca manualmente uno o más períodos en estado `manual_protegido`, al importar se exige confirmación explícita detallando cuántos valores manuales serán reemplazados.
- **Edición manual de un valor importado:** si el usuario edita desde el panel lateral un registro que tenía `origen = 'api'`, el repositorio actualiza `origen = 'manual'` y limpia `indice_milesimos = NULL`, protegiéndolo frente a futuras sincronizaciones.

### 4. Fallback manual garantizado

- Si no hay token configurado, el token venció o `api.indec.gob.ar` devuelve error de red/servidor, el flujo de carga y edición manual en `Ajustes IPC → Valores IPC` permanece 100 % operativo.
