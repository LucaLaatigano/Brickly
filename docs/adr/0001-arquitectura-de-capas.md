# ADR-0001: Puertos y adaptadores liviana (4 capas) para la app de departamentos

- **Status:** aceptada
- **Fecha:** 2026-10-15
- **Aplica a:** `gestion/`, `main.py`, `tests/test_arquitectura.py`

## Drivers

- **Features nuevas como cambio frecuente** — se esperan al menos: avisos por
  WhatsApp, recibos PDF, IPC automático por API, multi-edificio. Agregar una
  debe ser un módulo nuevo, no cirugía sobre lo que ya anda.
- **Exactitud de la plata** (mora, ajuste IPC) — exige dominio puro, testeable
  sin UI ni base de datos.
- **Equipo de 1 dev + agentes** — la ceremonia tiene que ser casi cero; la
  estructura tiene que ser navegable de un vistazo.
- **Datos locales chicos** — cientos de unidades, decenas de miles de cuotas en
  10 años: SQLite sobra; no hay backend ni servicios que operar.

## Decisión

Cuatro paquetes con dependencias apuntando hacia adentro:

```
ui ──▶ aplicacion ──▶ dominio
         ▲
infraestructura ┘   (implementa los puertos que define aplicacion)
```

- `gestion/dominio` — reglas puras (mora, IPC, calendario, dinero). No importa
  nada del proyecto ni frameworks.
- `gestion/aplicacion` — casos de uso; define los **puertos** (`puertos.py`,
  `typing.Protocol`) de lo que necesita del mundo.
- `gestion/infraestructura` — adaptadores: SQLite tras repositorios, reloj,
  exportadores, futuras integraciones. Implementa los puertos.
- `gestion/ui` — CustomTkinter. Solo presentación; habla con casos de uso.
- `main.py` — composition root: el único archivo que conoce todas las capas.

Reglas operativas:

- Todo el SQL vive en `gestion/infraestructura/db/` (conexión, migraciones con
  `PRAGMA user_version`, repositorios).
- Montos en **centavos enteros** (`int`); los redondeos son una regla de
  dominio explícita. Nunca floats para plata.
- Fechas y "hoy" entran por un `Reloj` inyectable (testear mora sin viajar en
  el tiempo).
- La regla de dependencia se hace cumplir con `tests/test_arquitectura.py`;
  si falla, se mueve el código de capa, no se relaja el test.

## Tradeoff aceptado

- ~1 día más de esqueleto y disciplina de imports (sostenida por el test, no
  por memoria).
- A cambio: cada feature nueva es un módulo; el núcleo es reusable si algún día
  aparece web/multi-usuario; la plata se testea en milisegundos.

## Revisit if

- Aparece backend web/multi-usuario → extraer API reusando `dominio` +
  `aplicacion` + repositorios y reemplazar solo `ui/`.
- La estructura empieza a pedir ceremonia para cambios chicos → señal de
  sobre-arquitectura; simplificar antes de que duela.
