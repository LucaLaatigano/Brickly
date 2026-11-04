# Especificación UX/UI — Brickly

- **Estado:** v1 — propuesta para H0 · **Fecha:** 2026-10-15
- **Para quién:** senior-dev (implementación) · qa (los estados de cada pantalla son casos de prueba)
- **Base:** ADR-0001 (arquitectura de 4 capas) + plan MVP del eng-manager
- **Librería:** CustomTkinter **6.0.0** (verificado: hereda `grid`/`pack` de Tk; trae `CTkScrollableFrame`, `CTkSegmentedButton`, `CTkTabview`, `CTkOptionMenu`, `CTkComboBox`, `CTkProgressBar`, `CTkFont`, `CTkToplevel`, `CTkInputDialog`. **No trae tabla ni messagebox propios** — la tabla es un componente nuestro y los diálogos van con `tkinter.messagebox`).

> Cómo usar este documento: §1–§2 se leen una vez (fundaciones y componentes). Después, pantalla por pantalla en el orden de §6, implementando con sus criterios de aceptación. Si algo de acá contradice al dominio o a la aplicación, **ganan la arquitectura y el dominio** — este documento no redefine reglas de negocio, las muestra.

---

## 1. Fundaciones

### 1.1 Principios

1. **Es una herramienta de trabajo, no una vidriera.** El usuario quiere responder en 5 segundos: ¿quién me debe?, ¿cobré el mes?, ¿toca ajuste? Cada pantalla tiene **una** acción primaria.
2. **La plata se muestra, no se calcula en la UI.** Mora e IPC vienen del dominio vía casos de uso; la UI solo formatea. Si un número no vino de `aplicacion`, está mal.
3. **Los estados son el diseño.** Vacío, error, parcial y overflow se especifican y se implementan para cada pantalla (§3). Una pantalla sin su estado vacío está a medias.
4. **Un lenguaje visual único (CTk).** Nada de mezclar widgets ttk sueltos ni `place()`. Todo se arma con `grid`/`pack` y los componentes de §2.

### 1.2 Ventana y shell

- Título: `Brickly`. Tamaño inicial 1280×800, **mínimo 1100×700**, centrada al abrir.
- `set_appearance_mode("light")` **fijo en v1** (tokens igual se definen como tuplas `(claro, oscuro)` para que un dark mode futuro sea una segunda capa de mapeo, no un rediseño).
- `set_default_color_theme("blue")` (base; nuestros tokens pisan lo visible).
- Estructura: sidebar izquierdo fijo de **220 px** + área de contenido. Contenido con padding 24 y header de pantalla (título 22 bold a la izquierda; acciones primarias a la derecha).
- Nav (6 ítems, altura 40 c/u, alineados a la izquierda): **Panel · Departamentos · Cobranzas · Ajustes IPC · Informes · Configuración**.
  - Ítem activo: fondo `SUPERFICIE` + texto `TEXTO` bold. Hover: `SUPERFICIE_2`. El título de cada pantalla coincide exactamente con el ítem del nav (el usuario siempre sabe dónde está).
- Nav → contenido: las vistas se montan y desmontan en el área de contenido (`for w in contenido.winfo_children(): w.destroy()` + montar la nueva). Sin `CTkTabview` para navegación principal.

### 1.3 Tokens (`brickly/ui/estilo.py`)

Colores semánticos (rol, no valor; tupla = claro/oscuro):

| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| `FONDO_APP` | `#F3F4F6` | `#18181B` | Fondo de ventana y contenido |
| `SUPERFICIE` | `#FFFFFF` | `#232326` | Cards, sidebar, filas de tabla |
| `SUPERFICIE_2` | `#F9FAFB` | `#2A2A2E` | Hover de filas, elementos sutiles |
| `BORDE` | `#E5E7EB` | `#3A3A40` | Bordes de cards e inputs, divisores |
| `TEXTO` | `#111827` | `#F4F4F5` | Texto principal |
| `TEXTO_2` | `#4B5563` | `#A1A1AA` | Texto secundario |
| `TEXTO_3` | `#6B7280` | `#71717A` | Captions, metadatos |
| `ACENTO` | `#2563EB` | `#3B82F6` | Botón primario, foco, links |
| `ACENTO_HOVER` | `#1D4ED8` | `#2563EB` | Hover del primario |
| `EXITO` / `EXITO_BG` | `#15803D` / `#DCFCE7` | `#4ADE80` / `#0E2A1B` | Pagada |
| `ALERTA` / `ALERTA_BG` | `#B45309` / `#FEF3C7` | `#FBBF24` / `#332503` | Parcial, avisos |
| `PELIGRO` / `PELIGRO_BG` | `#B91C1C` / `#FEE2E2` | `#F87171` / `#3A0F0F` | Vencida, deuda, borrar |
| `INFO_BG` | `#DBEAFE` | `#1E2A4A` | Chips informativos (override «Ajustado a mano», avisos neutros) |

Notas de por qué: un solo acento (`ACENTO`) marca interactividad — si el azul aparece en todas partes, no marca nada. Todos los pares texto/fondo de arriba apuntan a ≥ 4.5:1 sobre `SUPERFICIE`; **senior-dev: validar con un checker y corregir oscureciendo texto, no aclarando fondo.**

Tipografía (una sola familia: `Segoe UI`; crear los `CTkFont` una vez en `estilo.py` y reusar — no crear fuentes por widget):

| Token | Tamaño / peso | Uso |
|---|---|---|
| `FUENTE_TITULO` | 22 bold | Título de pantalla |
| `FUENTE_SECCION` | 15 bold | Títulos de card/sección |
| `FUENTE_CUERPO` | 13 normal | Texto y tablas |
| `FUENTE_CHICO` | 12 normal | Captions, filas de encabezado |
| `FUENTE_MICRO` | 11 bold | Chips |
| `FUENTE_KPI` | 30 bold | Números grandes del Panel |

Espaciado (escala única, base 4): **4, 8, 12, 16, 24, 32, 48**. Padding de página 24; de card 16; gap entre cards 16; entre filas de tabla 0 (divisor) con alto de fila 44. Radios: botones/inputs 8, cards 10, chips 12 (píldora).

Botones (alturas: primario/secundario 36, dentro de filas de tabla 32; targets ≥ 32 px — es desktop con mouse, no touch):
- **Primario**: `fg_color=ACENTO`, hover `ACENTO_HOVER`, texto blanco. Uno por pantalla (el de la acción principal).
- **Secundario**: `fg_color=SUPERFICIE`, borde 1 `BORDE`, texto `TEXTO`, hover `SUPERFICIE_2`.
- **Peligro**: se usa en texto y chips (deuda, vencida); no hay botones rojos sueltos en pantalla. Las confirmaciones destructivas van por diálogo nativo con su ícono de advertencia.

### 1.4 Formatos (argentino — `brickly/ui/formato.py`)

| Qué | Formato | Ejemplo |
|---|---|---|
| Montos | `$ 123.456,78` (punto de miles, coma decimal; sin decimales si son 0) | `$ 12.800` |
| Fechas | `dd/mm/aaaa` | `15/10/2026` |
| Períodos | `octubre 2026` (minúscula en prosa, en tablas columna propia) | — |
| Porcentajes | coma decimal, 2 decimales | `9,42 %` |
| Días de atraso | entero + "días" en tablas, chip: `Vencida · 12 días` | — |

Parseo de entrada (montos y %): aceptar `12800`, `12.800`, `12.800,50`; error inline `Monto inválido` (texto, no solo color). Fechas: `dd/mm/aaaa` con `strptime`; default = hoy (viene del `Reloj`).

### 1.5 Notas técnicas CTk (ahorro de horas)

- Todo con `grid` (o `pack`); `place()` prohibido.
- `CTkScrollableFrame` para listas largas; dar `sticky="nsew"` + `rowconfigure(weight=...)`; refresco de listas = destruir hijos y reconstruir (a esta escala alcanza).
- `CTkSegmentedButton` para filtros (`values=[...]`, `command=`); `CTkOptionMenu` para sets fijos (medio de pago); `CTkComboBox` solo si hace falta tipear (no lo usamos en v1).
- Enter en un formulario dispara la acción primaria (`bind("<Return>")`); Esc cierra el panel de pago. Primer campo con foco al abrir un formulario.
- DPI: CTk escala solo en Windows; probar a 125 % (laptop común) antes de dar por cerrada una pantalla.
- Los números nunca se calculan acá: `presenters` piden a `aplicacion` y la vista solo pinta.

---

## 2. Componentes (spec de implementación — `brickly/ui/componentes/`)

### 2.1 `tarjeta.py` — Card
`CTkFrame(fg_color=SUPERFICIE, corner_radius=10, border_width=1, border_color=BORDE)` + padding interno 16. Título opcional (`FUENTE_SECCION`) + contenido.

### 2.2 `kpi.py` — TarjetaKPI
Anatomía: caption (`FUENTE_CHICO`, `TEXTO_2`) → valor (`FUENTE_KPI`) → sub-línea (`FUENTE_CHICO`, `TEXTO_3`) → opcional barra de progreso (`CTkProgressBar`, alto 6, progreso `ACENTO`). Variante `tono` para el valor (`normal`, `peligro`).

### 2.3 `chip.py` — ChipEstado
`CTkLabel(height=24, corner_radius=12, font=FUENTE_MICRO, padx=10)` con variantes:

| Variante | Fondo / texto | Texto |
|---|---|---|
| `pagada` | `EXITO_BG` / `EXITO` | `Pagada` |
| `parcial` | `ALERTA_BG` / `ALERTA` | `Parcial` |
| `pendiente` | `SUPERFICIE_2` / `TEXTO_2` | `Pendiente` |
| `vencida` | `PELIGRO_BG` / `PELIGRO` | `Vencida` (+ `· N días` cuando hay columna de días) |
| `info` | `INFO_BG` / `ACENTO` | override `Ajustado a mano`, etc. |

El estado **siempre se lee como texto** (nunca solo color — daltonismo).

### 2.4 `tabla.py` — Tabla (el componente clave; no existe en CTk)

```python
class Tabla(ctk.CTkFrame):
    def __init__(self, master, columnas: list[Columna], al_click_fila=None,
                 mensaje_vacio="No hay nada para mostrar", cta_vacio=None):
        ...
    def mostrar(self, filas: list) -> None:
        """Destruye y reconstruye. Recibe DTOs de aplicacion, no dicts crudos."""
```

- `Columna(titulo, peso, alineacion="w"|"e", formato=None)`; el ancho sale del `peso` relativo (`grid_columnconfigure(weight=peso)`).
- Encabezado: fila de 36 px, `FUENTE_CHICO` bold `TEXTO_2`, divisor 1 px `BORDE` abajo. Filas de 44 px, fondo `SUPERFICIE`, divisor 1 px entre filas; hover `SUPERFICIE_2`; click en fila llama `al_click_fila(id)`.
- Columnas numéricas **alineadas a la derecha** (`anchor="e"`); montos con `formato.py`. Deuda/mora en `PELIGRO` cuando > 0.
- **Estados**: vacío (mensaje + CTA opcional, centrado, `TEXTO_2`) · overflow (scroll; nombres > 40 caracteres se truncan con `…`; el nombre completo se ve en el detalle) · **regla de paginación: si una tabla pasa de 300 filas, paginar de a 50** (paginador mínimo `‹ 1/6 ›` al pie). A la escala del MVP (cientos de unidades) no debería dispararse: es red de seguridad, no feature.
- Anti N+1: `presenters` traen todas las filas en **una** llamada; la tabla no consulta nada.

### 2.5 `banner.py` — Banner (feedback de acciones)
`CTkFrame` en el ancho del contenido, borde izquierdo 3 px del color de estado, fondo `*_BG`, texto `FUENTE_CHICO`, botón ✕ para cerrar. Variantes `exito`, `alerta`, `error`. Se muestra arriba del contenido y **no bloquea nada**. No hay toasts en v1 (CTk no los trae; construirlos es scope creep).

### 2.6 `formulario.py` — Campo
Label arriba (`FUENTE_CHICO`, `TEXTO_2`) + `CTkEntry`/`CTkOptionMenu` de 36 px (`border_color=BORDE`; en foco → `ACENTO`, vía `bind("<FocusIn>/<FocusOut>")`) + mensaje de error debajo (`FUENTE_CHICO`, `PELIGRO`) + texto de ayuda opcional (`TEXTO_3`). Nada de validación silenciosa: el error aparece al confirmar, junto al campo.

### 2.7 Diálogos
Confirmaciones destructivas y avisos con `tkinter.messagebox` (nativo: fiable, cero código). Texto siempre con **consecuencia explícita**: "¿Eliminar «Rivadavia 3421 · 3º B»? Se borran también su contrato, 14 cuotas y 32 pagos. **No se puede deshacer.**" Modales themed con `CTkToplevel` quedan para después — anotado en §7.

---

## 3. Pantallas

### 3.0 Mapa de navegación

```
Panel ──▶ Cobranzas (Mes · Atrasos) ──▶ [panel de pago lateral]
  │            ▲
  ├──▶ Departamentos ──▶ Detalle de departamento (Cuotas y pagos · Contrato)
  ├──▶ Ajustes IPC ──▶ Wizard de ajuste (3 pasos)
  ├──▶ Informes
  └──▶ Configuración
```

### 3.1 Panel

**Objetivo:** responder en 5 segundos "¿qué tengo que hacer hoy?". **Acción primaria:** `Registrar pago` (arriba a la derecha).

```
┌─────────────┬───────────────────────────────────────────────────────────────────┐
│ Gestión de  │  Panel                                        [ Registrar pago ]  │
│ Departamentos│                                                                  │
│             │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────┐   │
│ ▸ Panel     │  │ Cobrado     │ │ Vencidas    │ │ Pendientes  │ │ Ajustes    │   │
│   Departa…  │  │ octubre     │ │ sin pago    │ │ (a término) │ │ este mes   │   │
│   Cobranzas │  │ $ 412.500   │ │ 4 · $ 38.400│ │ 6 · $ 96.000│ │ 2 contratos│   │
│   Ajustes   │  │ ▓▓▓▓▓▓▓░░ 76%│ │             │ │             │ │ → revisar  │   │
│   Informes  │  └─────────────┘ └─────────────┘ └─────────────┘ └────────────┘   │
│   Config.   │  ┌───────────────────────────────────────┐ ┌────────────────────┐ │
│             │  │ Vencidas sin pago · 4       [Ver todas]│ │ Alertas            │ │
│             │  │ 3º B · Rivadavia 3421   12 d  $ 14.336 │ │ ▸ Falta IPC de     │ │
│             │  │ 1º A · Mitre 1180        8 d  $ 10.368 │ │   septiembre →     │ │
│             │  │ PB · Sarmiento 890       3 d  $  8.240 │ │ ▸ Respaldo hace 21 │ │
│             │  └───────────────────────────────────────┘ │   días → Respaldar │ │
│             │                                             └────────────────────┘ │
└─────────────┴───────────────────────────────────────────────────────────────────┘
```

- 4 KPIs: Cobrado (con progreso cobrado/esperado del mes en curso) · Vencidas sin pago (cantidad + deuda con mora a hoy) · Pendientes a término · Ajustes IPC que tocan este mes (CTA → Ajustes).
- "Vencidas sin pago": top 5 por días de atraso (monto = cuota + mora de hoy). Click en fila o "Ver todas" → Cobranzas → pestaña **Atrasos** con el pago abierto.
- Alertas (calculadas, no decorativas): faltan meses de IPC para algún ajuste · último respaldo > 14 días · contratos vencidos sin renovar. Sin alertas → card dice `Sin alertas`.
- Si no hay cuotas generadas del mes: banner con CTA `Generar cuotas de {mes}` (lleva a Cobranzas con la generación lista).

**Estados:** vacío total (0 departamentos) → card de onboarding (§4, Flujo 1) ocupa el lugar de KPIs/tablas. Sin mora → "No hay vencidas sin pago." Datos parciales (sin cuotas del mes) → banner de generación. Error de carga → banner `error` con "Reintentar".

**Criterios de aceptación:**
- [ ] Los 4 KPIs y la tabla coinciden al peso con Cobranzas (mismo servicio; la UI no suma por su cuenta).
- [ ] Click en vencida abre Cobranzas/Atrasos con el panel de pago ya abierto en esa cuota.
- [ ] Con 0 departamentos, muestra onboarding y no KPIs.
- [ ] Alerta de IPC aparece si y solo si el servicio reporta meses faltantes.

### 3.2 Departamentos (lista)

**Objetivo:** encontrar una unidad y ver su situación. **Acción primaria:** `+ Agregar departamento`.

```
│  Departamentos                              [ + Agregar departamento ]        │
│                                                                                 │
│  [ Buscar dirección o inquilino…    ]   ( Todos │ Al día │ Deben │ Sin contrato)│
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │ Unidad                    Inquilino        Cuota vig.  Estado    Deuda  Últ. pago │
│  │ Rivadavia 3421 · 3º B     Laura Giménez    $ 12.800   Vencida  $ 15.360  02/09 │
│  │ Mitre 1180 · 1º A         Diego Ferreyra   $  9.600   Pagada   —         10/10 │
│  │ Sarmiento 890 · PB        (sin contrato)   —          —        —         —     │
│  └────────────────────────────────────────────────────────────────────────────┘ │
```

Columnas (peso, alineación): Unidad (3, izq) · Inquilino (2, izq; `(sin contrato)` en `TEXTO_3`) · Cuota vigente (1.5, der) · Estado del mes (1.5, chip) · Deuda total (1.5, der; `PELIGRO` si > 0; incluye mora a hoy) · Último pago (1.5, der).

- Búsqueda: filtra al tipear (debounce 300 ms con `after`) por dirección o inquilino. Filtros de `CTkSegmentedButton` combinables con la búsqueda.
- Click en fila → Detalle. `Últ. pago` dice `—` si nunca pagó.
- **Estados:** vacío → "Todavía no hay departamentos cargados. Empezá agregando el primero." + botón · filtro sin resultados → "Nada coincide con «pepe»." + `Limpiar filtro` · overflow → scroll (y paginación si > 300).

**Criterios de aceptación:**
- [ ] Los filtros se combinan (búsqueda + estado) sin recargar de la base por cada tecla (una llamada por debounce).
- [ ] Deuda viene del servicio (suma de saldos + mora a hoy) — nunca calculada en la vista.
- [ ] Sin contrato la fila es válida y clickeable (invita a cargar contrato en el detalle).

### 3.3 Detalle de departamento

**Objetivo:** el estado de cuenta completo de una unidad. Header: `Rivadavia 3421 · 3º B` + chips (estado del mes, contrato) + acciones `[ Registrar pago ]` `[ Editar ]`. Secciones con `CTkSegmentedButton`: **Resumen · Contrato · Cuotas y pagos**.

- **Resumen:** card de datos (dirección, piso/nº, m², propietario) · card del inquilino (nombre, teléfono, email — con botón "Copiar teléfono") · mini-KPIs: Deuda total · Cuota vigente · Próximo vencimiento.
- **Contrato:** datos del contrato vigente (desde/hasta, monto, día de vencimiento, días de gracia, tasa de mora, ciclo de ajuste y **próxima fecha de ajuste**). Botones `Editar contrato` y `Nuevo contrato` (cambio de inquilino: cierra el actual y crea otro; el historial queda). Sin contrato → card vacía con CTA `Cargar contrato`.
- **Cuotas y pagos:** tabla de cuotas (Período · Vence · Cuota · Pagado · Mora · Saldo · Estado) con las cuotas del contrato actual e históricas; click en una cuota → sus pagos imputados (fecha, monto, medio, mora cobrada). Botón `Exportar estado de cuenta (CSV)` (secundario).
- **Estados:** sin contrato (CTA) · contrato vencido (chip `alerta`: `Contrato vencido el 30/09`) · sin cuotas ("Generá las cuotas del mes desde Cobranzas") · error → banner con reintento.

**Criterios de aceptación:**
- [ ] El monto de mora de una cuota vencida coincide con el de Cobranzas (mismo servicio de dominio).
- [ ] `Nuevo contrato` nunca borra historial: las cuotas viejas siguen visibles.
- [ ] La próxima fecha de ajuste sale del ciclo del contrato (dominio), no de un cálculo de la vista.

### 3.4 Cobranzas

**Objetivo:** el ciclo mensual completo — generar, cobrar, perseguir morosos. Tiene dos vistas con `CTkSegmentedButton`: **Mes** (default) y **Atrasos**.

Header: `Cobranzas` + navegador de mes `◀ octubre 2026 ▶` (en Atrasos el navegador no aplica) + acción primaria contextual: `[ Generar cuotas de {mes} ]` si no están generadas, `[ Registrar pago ]` si ya lo están.

```
│  Cobranzas — octubre 2026                       [ Registrar pago ]              │
│  ◀  octubre 2026  ▶      ( Mes │ Atrasos )                                     │
│  Cobrado $ 412.500 de $ 540.000 · Vencidas 4 ($ 38.400) · Pendientes 6         │
│  [ Buscar unidad o inquilino… ]   ( Todas │ Pendientes │ Vencidas │ Pagadas )   │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ Unidad              Inquilino     Vence   Cuota    Mora    Saldo   Estado  │  │
│  │ Rivadavia 3421 3ºB  Laura Giménez 10/10   $12.800  $1.536  $14.336 Vencida │  │
│  │ Mitre 1180 1º A     Diego Ferreyra 10/10  $ 9.600  —       —       Pagada  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
```

- Nota bajo la tabla: "Mora calculada al 15/10/2026 — se recalcula todos los días." (honestidad: la mora es viva, viene del `Reloj`).
- **Mes sin generar:** la tabla se reemplaza por card: "Las cuotas de octubre 2026 todavía no están generadas." + detalle del preview (`Se generarán 36 cuotas por $ 540.000 · 3 unidades sin contrato quedarán afuera`) + `[ Generar cuotas ]` (primario) → botón pasa a `Generando…` deshabilitado + `CTkProgressBar` → banner de resultado. **Idempotente:** si ya existen, no duplica (criterio de aceptación).
- **Atrasos:** tabla plana de todas las cuotas impagas de cualquier período, ordenadas por días de atraso (desc): Unidad · Inquilino · Período · Vence · Días · Cuota · Mora hoy · Total · `[ Cobrar ]`.

**Panel de pago (inline, columna derecha de 380 px — nunca modal):**

```
┌ Registrar pago ───────────────────┐
│ Rivadavia 3421 · 3º B             │
│ Laura Giménez · octubre 2026      │
│ Vence 10/10/2026 (vencida: 5 días)│
│                                   │
│ Cuota           $ 12.800          │
│ Mora (12 días)  $  1.536          │
│ Total           $ 14.336          │
│                                   │
│ Fecha de pago [ 15/10/2026 ]      │
│ Monto         [ 14.336,00  ]      │
│ Medio         [ Transferencia ▾ ] │
│ Nota (opcional) [               ] │
│ [ Confirmar pago ]  [ Cancelar ]  │
└───────────────────────────────────┘
```

- Defaults inteligentes: fecha = hoy (Reloj), monto = total (cuota + mora a hoy), medio = último usado. El 80 % de los cobros es Enter.
- Live al editar monto: `< total` → aviso `alerta` "Quedará un saldo de $ X" (no bloquea); `> total` → error "El monto supera el total ($ X)" y botón deshabilitado. Mora se muestra solo si > 0, con su cálculo ("12 días").
- Al confirmar: se llama al caso de uso `registrar_pago`; éxito → banner "Pago registrado: $ 14.336 · Rivadavia 3421 · 3º B", tabla se refresca, panel se cierra y la fila cobrada desaparece del filtro activo. Error → banner `error` "No se pudo registrar: {detalle}. No se modificó nada." + el panel queda abierto con los datos intactos (jamás perder input).
- Pago parcial permitido (FIFO lo maneja el dominio); el panel no decide imputación.
- **Estados:** sin vencidas → "No hay cuotas vencidas." · mes futuro (navegación) → mismo flujo que mes sin generar · todas pagadas → "Octubre al día: 36 de 36 cobradas." · error de pago (arriba).
- **Constancia de pago (H8):** click en una cuota `Pagada` abre
  `PanelConstancia` (380 px) con la vista previa y `[ Generar PDF ]`; el
  período se elige con el navegador de la pantalla. Solo cuotas pagadas; el
  PDF lleva bloque de firma del propietario/a o administrador/a.

**Criterios de aceptación:**
- [ ] Generar cuotas es idempotente (dos clics ≠ cuotas duplicadas) y reporta cuántas se generaron y cuántas unidades quedaron afuera (sin contrato).
- [ ] La mora mostrada es la del dominio "a hoy" (mismo número en Panel, tabla y panel de pago).
- [ ] Monto mayor al total bloquea; monto menor avisa sin bloquear.
- [ ] Enter confirma el pago; Esc cierra el panel sin guardar.
- [ ] Tras confirmar, los filtros y la búsqueda se mantienen (no se resetea el contexto).
- [ ] La constancia solo se genera para cuotas pagadas y muestra la firma del propietario/a o administrador/a.

### 3.5 Ajustes IPC

**Objetivo:** cargar el IPC mensual y aplicar el ajuste trimestral con total transparencia. Dos secciones:

**A) Valores IPC cargados.** Form inline: `[ Mes ▾ ] [ Año ▾ ] [ Variación % ] [ Agregar ]` + tabla (Período · Variación · Origen (`Manual`) · Cargado el · ✎/✕). Editar/borrar con confirmación si algún ajuste futuro lo usa.

**B) Ajustes por aplicar.** Lista de contratos cuyo ciclo vence este mes: Unidad · Inquilino · Meses base (ej. `jul–sep 2026`) · Estado chip (`Listo` = IPC completo / `Faltan datos` → con link a la sección A). Botón `[ Revisar y aplicar ]`.

**Wizard (3 pasos, dentro de la misma pantalla, stepper visual 1–2–3):**

1. **Selección** (si hay varios contratos): checkboxes, todos marcados por defecto (prevención > decisión).
2. **Revisión:**

```
│ Unidad               Cuota actual   IPC aplicado   Cuota nueva     Δ       │
│ Rivadavia 3421 3ºB   $ 12.800       9,42 %         $ 14.006     +$ 1.206  │
│ Mitre 1180 1º A      $  9.600       9,42 %         $ 10.504     +$   904  │
│                                                                           │
│ IPC jul–sep 2026: (1+2,1%) × (1+3,4%) × (1+3,7%) − 1 = 9,42 % [ver meses] │
│ La celda «IPC aplicado» es editable; si la cambiás queda chip «Ajustado   │
│ a mano» con el motivo (contrato con % pactado distinto).                  │
│ [ ← Atrás ]                                    [ Aplicar 2 ajustes ]       │
```

3. **Confirmación/resultado:** resumen ("Se ajustan 2 contratos · cuota promedio +9,42 %") → banner de éxito + el ajuste aparece en **Historial de ajustes** (tabla: fecha · contrato · meses base · % · antes → después), que es de solo lectura.

- **Impacto del ajuste (confirmado — ADR-0002, §7):** el ajuste confirmado aplica a las cuotas que se generen **después** de confirmar (próximo período). No recalcula cuotas ya emitidas.
- **Estados:** sin valores IPC → sección A vacía con "Cargá el primer IPC mensual" · ajustes bloqueados por datos faltantes (chips + wizard deshabilitado con motivo) · sin contratos en ciclo → "No hay contratos que se ajusten este mes." · wizard: salir a la mitad = no guarda nada (efímero; se avisa con confirmación si había ediciones).

**Criterios de aceptación:**
- [ ] El % acumulado por contrato lo calcula el dominio con los 3 meses base de ese contrato (dos contratos con ciclos distintos pueden recibir % distintos).
- [ ] Override manual queda marcado en la vista previa y registrado en el historial.
- [ ] Confirmar es atómico: o se aplican todos los marcados, o ninguno (si falla, banner de error y nada cambió).

### 3.6 Informes

**Objetivo:** sacar datos y respaldar. Lista de cards con acción `Exportar` (o `Respaldar`): Estado de cuenta por departamento (CSV) · Cobranzas del mes (CSV) · Morosos de hoy (CSV) · Respaldo de la base (copia `.sqlite`). Cada card: título, descripción de una línea, botón secundario. Bajo "Respaldo": "Último respaldo: 24/09/2026" (o `Nunca`).

- Export → diálogo nativo de guardado (`tkinter.filedialog.asksaveasfilename`, default: Escritorio, nombre `cobranzas-octubre-2026.csv`) → banner éxito con la ruta completa. Sin datos → botón deshabilitado con motivo ("No hay morosos hoy") — nunca un CSV vacío.
- **Estados:** exportando (botón deshabilitado `Exportando…`) · éxito (banner con ruta) · error (banner `error` con detalle) · sin datos (deshabilitado + motivo).

**Criterios de aceptación:**
- [ ] El CSV sale de un servicio de `aplicacion` (puerto exportador de la arquitectura), no de SQL en la UI.
- [ ] El respaldo usa la copia segura de SQLite (el mecanismo lo implementa infraestructura) y muestra la ruta del archivo creado.

### 3.7 Configuración

**Objetivo:** predeterminados y datos de la instalación. Cards:
- **Predeterminados de contrato:** día de vencimiento (1–28, default 10) · días de gracia (default 5) · tasa de mora mensual % (default 2,0) · redondeo de cuota (`Centavos` / `$ 100`). Cada campo con su ayuda de una línea ("Se usa al crear contratos nuevos; cada contrato puede pisarlo").
- **Datos del administrador:** nombre, teléfono, email (para constancias de pago y exportaciones).
- **Datos y respaldo:** ruta de la base (solo lectura, con `Abrir carpeta`) · recordatorio de respaldo (14 días) · botón `Hacer respaldo ahora`.
- **Acerca de:** versión + fecha de build.
- Guardado explícito: `[ Guardar cambios ]` (primario) → banner `éxito`. Validación inline (día fuera de rango, tasa no numérica). **Estados:** guardado · errores inline · error de escritura → banner con detalle.

**Criterios de aceptación:**
- [ ] Cambiar un predeterminado no toca contratos existentes (aplica solo a nuevos) — comportamiento visible en la ayuda del campo.
- [ ] Tasa de mora acepta coma decimal; fuera de rango [0, 100] bloquea con mensaje.

---

## 4. Flujos clave (los que qa va a caminar)

**F1 · Puesta en marcha (primera vez).** Panel vacío → card onboarding tipo checklist: `1. Agregá tus departamentos → 2. Cargá los contratos → 3. Generá las cuotas del mes`. Cada paso linkea a su pantalla y se tacha solo cuando el servicio reporta datos. Done = primer pago registrado.

**F2 · Generación mensual.** Cobranzas/Mes → si no hay cuotas: card con preview → `Generar cuotas` → progreso → banner (`36 cuotas generadas · $ 540.000 · 3 unidades sin contrato quedaron afuera`) → tabla poblada → cobrar.

**F3 · Cobranza diaria (el flujo más caliente).** Panel → "Vencidas sin pago" → click fila → Cobranzas/Atrasos con panel de pago abierto y total (cuota + mora) precargado → Enter → banner + siguiente moroso. Cero modales, cero campos de más: 3 interacciones por cobro.

**F4 · Cierre trimestral.** Alerta de IPC faltante → Ajustes IPC → cargar 2–3 meses → `Revisar y aplicar` → wizard (selección → revisión con override opcional → confirmar) → historial. Abandonar a mitad no persiste nada.

**F5 · Cambio de inquilino.** Detalle → `Nuevo contrato` → se cierra el actual (fecha fin) y se crea el nuevo → cuotas futuras usan el nuevo contrato; el historial anterior queda visible. Las cuotas ya generadas del mes en curso no se tocan.

**Accesibilidad de transiciones (aplica a F2–F5):** al abrir un formulario/panel, foco al primer campo; Enter = acción principal; Esc cierra panel; errores y banners con texto legible (no solo color); todo completable con teclado.

---

## 5. Estados globales (transversal)

| Estado | Regla |
|---|---|
| **Vacío** | Siempre con mensaje + salida (CTA o instrucción). Nunca un área en blanco. |
| **Carga** | SQLite local ≈ instantáneo: no hay spinners en v1. La única excepción es Generar cuotas (bloquea botón + `CTkProgressBar`). Si una consulta supera ~300 ms, texto `Cargando…` en el área de la tabla. |
| **Error** | Banner `error` con qué pasó + "Reintentar" cuando aplica. **Nunca se pierde input**: formularios y paneles quedan con los datos cargados. |
| **Parcial** | Ej.: unidades sin contrato (quedan afuera de la generación con aviso), ajuste con datos faltantes (bloqueado con motivo), contratos vencidos (chip). Siempre decir qué falta y dónde arreglarlo. |
| **Overflow** | Nombres > 40 chars: truncados con `…` en tablas (completo en detalle). Listas > 300 filas: paginar de a 50. Montos: columna de ancho fijo que banca $ 99.999.999,99. |

**Confirmaciones (fricción donde corresponde):** solo en borrados y acciones irreversibles, con consecuencia explícita (qué más se borra, cuántos registros, "no se puede deshacer"). Cobrar y generar cuotas **no** se confirman (frecuentes y reversibles vía corrección); se avisan por banner.

---

## 6. Qué tiene que hacer senior-dev

### 6.1 Archivos a crear (dentro de `brickly/ui/`, sin tocar la arquitectura)

```
brickly/ui/
├─ ventana.py            # shell: sidebar + navegación + montaje de vistas. Recibe los servicios por constructor.
├─ estilo.py             # tokens de §1.3 + CTkFont compartidos + set_appearance_mode("light")
├─ formato.py            # §1.4: monto, fecha, período, porcentaje, parseo
├─ componentes/
│  ├─ tarjeta.py         # §2.1
│  ├─ kpi.py             # §2.2
│  ├─ chip.py            # §2.3
│  ├─ tabla.py           # §2.4  ← el más importante, hacerlo primero y bien
│  ├─ banner.py          # §2.5
│  └─ formulario.py      # §2.6 Campo
├─ vistas/
│  ├─ panel.py
│  ├─ departamentos.py   # lista
│  ├─ departamento.py    # detalle (3 secciones)
│  ├─ cobranzas.py       # Mes/Atrasos + panel de pago + generación
│  ├─ ajustes_ipc.py     # valores + wizard + historial
│  ├─ informes.py
│  └─ configuracion.py
└─ presenters/
   ├─ panel.py  cobranzas.py  ajuste.py  departamento.py
```

### 6.2 Reglas duras (el test de arquitectura ya las vigila)

1. `brickly/ui` **no importa** `sqlite3`, ni `brickly.infraestructura`, ni `brickly.dominio` para calcular: los números vienen de **casos de uso** de `aplicacion` (inyectados desde `main.py`).
2. La UI **no calcula mora, ni IPC, ni saldos**. Solo formatea con `formato.py`.
3. Todo dato que se muestra salió de una llamada a un servicio — los `presenters` agrupan las consultas por pantalla (una llamada por tabla, no N).
4. `place()` prohibido; listas largas con `CTkScrollableFrame`; refrescos por reconstrucción.
5. Los textos visibles son **exactamente** los de este documento (botones, banners, vacíos): son la mitad del diseño.

### 6.3 Cómo se conecta una pantalla (patrón único)

```python
class VistaCobranzas(ctk.CTkFrame):
    def __init__(self, master, servicios):          # inyectado desde main.py
        super().__init__(master, fg_color="transparent")
        self.servicios = servicios
        self._cargar()

    def _cargar(self):
        datos = self.servicios.consultar_cobranzas.del_mes(2026, 10)   # 1 llamada → N filas
        self.tabla.mostrar(datos.filas)

    def _registrar_pago(self, fila):
        try:
            self.servicios.registrar_pago.ejecutar(fila.cuota_id, monto, fecha, medio)
            self.mostrar_banner("Pago registrado: …", "exito")
            self._cargar()
        except ErrorDeNegocio as e:                  # ej.: monto > saldo
            self.mostrar_banner(f"No se pudo registrar: {e}. No se modificó nada.", "error")
```

(Los nombres exactos de servicios/DTOs los fija `aplicacion`; ajustar acá cuando existan. Los errores de negocio viajan como excepciones de dominio/aplicación con mensaje en castellano.)

### 6.4 Orden de implementación (espejo de los hitos H0–H4)

1. **H0:** `ventana.py` + `estilo.py` + `formato.py` + componentes base (`tarjeta`, `chip`, `banner`, `formulario`, `tabla`) + `vistas/departamentos.py` + `departamento.py` (ABM y listado). Empaquetado de prueba con esta pantalla.
2. **H1:** `cobranzas.py` — generación de cuotas + tabla del mes.
3. **H2:** panel de pago + mora en UI + Atrasos.
4. **H3:** `ajustes_ipc.py` — valores + wizard + historial.
5. **H4:** `panel.py` (KPIs + alertas) + `informes.py` + `configuracion.py`.

Cada pantalla se da por terminada cuando:
- [ ] Funciona **dentro del exe empaquetado** (no solo en dev).
- [ ] Sus estados de §3 se ven con datos de prueba (vacío, error, parcial; overflow si aplica).
- [ ] El test de arquitectura sigue verde (`tabla.py` no importa infraestructura, etc.).
- [ ] Textos y formatos exactos según §1.4 y §3.
- [ ] Probada a 125 % de DPI.

### 6.5 Para qa

Cada "Estados" y "Criterios de aceptación" de §3 es, línea por línea, un caso de prueba. Los flujos de §4 se caminan de punta a punta, incluyendo: abandonar el wizard a la mitad, doble clic en Generar, monto mayor/menor al total, mes sin datos, filtro sin resultados, y el mismo pago visto desde Panel y desde Cobranzas (los números tienen que coincidir).

---

## 7. Reglas de negocio confirmadas y alcance

Las 4 preguntas del plan del EM quedaron definidas y confirmadas por el usuario el 2026-10-15, y asentadas en `docs/adr/0002-reglas-de-negocio-mvp.md`:

1. **Impacto del ajuste:** aplica a cuotas generadas **después** de confirmar — no recalcula cuotas ya emitidas.
2. **Redondeo:** a centavos por defecto; opción `$ 100` en Configuración.
3. **Día de vencimiento:** igual cada mes (si cae fin de semana no se corre). No hay corrimiento a día hábil en v1.
4. **Mora:** interés simple diario sobre saldo (cuota − pagado), según dominio; se muestra "a hoy" y se congela al cobrar (eso ya es del dominio).

Fuera de alcance de esta especificación (parking lot, no implementar): dark mode toggle · modales themed con `CTkToplevel` · toasts/animaciones · iconografía · recibos fiscales/facturación electrónica · firma digital certificada · atajos globales de teclado · paginación "de verdad" (solo la regla de seguridad de §2.4) · multi-ventana.

---

**Registro de cambios:** v1 (2026-10-15) — versión inicial derivada del plan EM + ADR-0001 · v1.1 (2026-10-15) — reglas de §7 confirmadas y asentadas como ADR-0002 (sin cambios de diseño).
