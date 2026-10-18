# 🏢 Brickly

**Sistema ágil, moderno y local-first para la administración de departamentos en alquiler, cobranzas, mora diaria y ajustes por IPC.**

> *A standalone Windows desktop app for managing rental units, lease contracts, arrears, and CPI adjustments.*

[![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-blue?style=flat)](https://customtkinter.tomschimansky.com/)
[![Plataforma](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?style=flat&logo=windows)](https://microsoft.com/windows)
[![Licencia](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.md)

---

## ⚡ ¿Qué es Brickly?

**Brickly** está diseñado para propietarios y administradores que necesitan responder en segundos a las tres preguntas operativas clave del día a día:
1. **¿Quién debe alquiler hoy y cuánta mora acumuló?**
2. **¿Se generaron y cobraron las cuotas del mes en curso?**
3. **¿Qué contratos cumplen ciclo y toca aplicarles ajuste por IPC?**

Todo funciona de manera **local**, sin servidores externos, sin dependencias en la nube y con almacenamiento transaccional seguro en SQLite.

---

## ✨ Características Principales

| Módulo | Descripción |
| :--- | :--- |
| 📊 **Panel (Dashboard)** | KPIs mensuales en tiempo real, top 5 atrasos con cobro directo, alertas automáticas (IPC faltante, contratos vencidos, respaldos) y checklist de onboarding. |
| 🏢 **Departamentos & Contratos** | Catálogo completo con búsqueda en vivo, filtros de estado, estados de cuenta por unidad y renovación de contratos preservando el historial. |
| 💰 **Cobranzas & Atrasos** | Generación mensual idempotente de cuotas, vista consolidada de atrasos y **Panel lateral de Pago** (380 px) con cálculo dinámico de mora simple e imputación FIFO. |
| 📈 **Ajustes IPC** | Registro de índices mensuales, detección automática de ciclos vencidos y **Wizard de ajuste** en 3 pasos con cálculo compuesto y anulación manual auditada. |
| 📑 **Informes & Respaldo** | Exportación de estados de cuenta, recaudación y morosos a CSV formateado para Excel (`UTF-8 con BOM`) y copia de seguridad nativa con SQLite Backup API. |
| ⚙️ **Configuración** | Parámetros predeterminados de contratos (día de vencimiento, gracia, tasa de mora diaria), datos del administrador y ruta de la base de datos. |

---

## 🚀 Inicio Rápido

### Opción 1: Ejecutable para Windows (Sin instalar Python)
1. Descarga o localiza el binario compilado en:
   ```text
   dist\GestionDepartamentos.exe
   ```
2. Ejecútalo directamente con doble clic. La base de datos SQLite se crea automáticamente en `%APPDATA%\GestionDepartamentos\datos.sqlite3`.

### Opción 2: Ejecución desde el código fuente
Requiere **Windows 10/11** y **Python 3.13+**.

```powershell
# 1. Clonar el repositorio
git clone https://github.com/LucaLaatigano/Apartments-Manager.git
cd Apartments-Manager

# 2. Crear entorno virtual e instalar dependencias
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 3. Iniciar la aplicación
.venv\Scripts\python main.py
```

---

## 🛠️ Comandos de Desarrollo

| Acción | Comando PowerShell |
| :--- | :--- |
| **Ejecutar tests** | `.venv\Scripts\python -m pytest tests/` |
| **Compilar `.exe`** | `.venv\Scripts\python -m PyInstaller --clean --noconfirm GestionDepartamentos.spec` |

---

## 🏛️ Arquitectura & Principios de Negocio

El proyecto sigue una arquitectura **Hexagonal / Puertos y Adaptadores (4 capas)** estricta, validada automáticamente por tests de arquitectura:

```text
gestion/ui  ──▶  gestion/aplicacion  ──▶  gestion/dominio
                         ▲
gestion/infraestructura  ┘   (implementa puertos de aplicación)
```

- **Cero Floats:** Todo cálculo monetario se realiza en centavos enteros (`int`) y las tasas en puntos básicos (`100 bp = 1%`), tanto en dominio como en SQLite `STRICT`.
- **Mora Diaria Simple:** Calculada a la fecha de consulta (`Reloj`) sobre el saldo principal impago una vez superado el período de gracia.
- **Imputación FIFO:** Los pagos amortizan primero el interés por mora devengado y luego el capital de la cuota.
- **Ajustes IPC no retroactivos:** Los ajustes actualizan el canon locativo futuro sin alterar cuotas ya emitidas.

Para más detalles, consulta las decisiones de diseño:
- [ADR-0001: Arquitectura de capas](docs/adr/0001-arquitectura-de-capas.md)
- [ADR-0002: Reglas de negocio del MVP](docs/adr/0002-reglas-de-negocio-mvp.md)
- [Especificación UX/UI](docs/ux/especificacion-ux-ui.md)

---

## 📄 Licencia

Distribuido bajo la Licencia **MIT**. Consulta [LICENSE.md](LICENSE.md) para más información.
