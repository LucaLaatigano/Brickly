# Gestión de Departamentos (Apartment Management System)

A standalone Windows desktop application built with **Python**, **SQLite**, and **CustomTkinter** for managing rental apartment units, lease contracts, monthly rent collections, daily late-fee (arrears) calculations, and periodic CPI (*IPC*) rent adjustments.

---

## What It Does

**Gestión de Departamentos** is designed for property administrators and landlords who want a fast, local-first tool to answer three core operational questions at a glance: *Who owes rent? Has this month been collected? Which contracts are due for a CPI adjustment?*

### Key Features

- **Dashboard (`Panel`)**
  - First-time onboarding checklist guiding setup from adding units to recording the first payment.
  - Real-time monthly KPIs: collected vs. expected rent progress, overdue unpaid installments, on-time pending installments, and contracts due for adjustment this month.
  - Top 5 overdue installments sorted by days late, with one-click navigation directly into the payment panel.
  - Automated actionable alerts for missing monthly CPI data, expired unrenewed contracts, and overdue database backups (> 14 days).

- **Apartments & Contracts (`Departamentos`)**
  - Full CRUD for managed units (address, floor, unit label, area in m², owner) with live debounced search and status filters (*All*, *Up to date*, *Owing*, *No contract*).
  - Per-unit account statement view (`Detalle de departamento`) split into **Summary**, **Contract**, and **Installments & Payments**.
  - Lease contract creation, editing, and tenant turnover/renewal (`Nuevo contrato`) that closes the previous contract while preserving full historical installments and payments.

- **Collections & Arrears (`Cobranzas`)**
  - **Monthly View (`Mes`):** Period navigator, pre-generation preview, and idempotent monthly installment generation (`Generar cuotas`) for all active contracts.
  - **Arrears View (`Atrasos`):** Flat, cross-period list of all overdue unpaid installments ordered by days late.
  - **Inline Payment Side Panel (`PanelPago`):** 380 px side panel (no blocking modals) with smart defaults (today's date, full balance + accrued late fee, last used payment method) and live validation for partial or full payments.

- **CPI Adjustments (`Ajustes IPC`)**
  - Monthly CPI (*Índice de Precios al Consumidor*) registry supporting positive and negative variations in basis points.
  - Automatic detection of contracts reaching their N-month adjustment cycle (default: quarterly / 3 months) and compound variation calculation over the contract's base months: $\prod (1 + v_i) - 1$.
  - **3-Step Adjustment Wizard:** Select contracts $\rightarrow$ Review calculated new rent (with optional manual percentage override requiring an explicit reason) $\rightarrow$ Apply atomically ("all or nothing").
  - Immutable adjustment audit log (`Historial`).

- **Reports & Backups (`Informes`)**
  - Excel-friendly CSV exports (`UTF-8 with BOM`, `;` delimiter, comma decimals):
    - Account statement (all units or per apartment).
    - Monthly collections summary.
    - Current overdue tenants (*Morosos de hoy*).
  - Online safe SQLite backup using SQLite's native backup API (`Connection.backup`).

- **Settings (`Configuracion`)**
  - Configurable defaults for new contracts: due day (1–28), grace days, monthly late-fee interest rate, and installment rounding (`Centavos` or `$ 100`).
  - Administrator contact details, database file location shortcut, backup reminder threshold, and manual backup trigger.

---

## Core Business Rules & Architecture

The project follows a strict **4-layer Ports & Adapters (Hexagonal) architecture** ([ADR-0001](docs/adr/0001-arquitectura-de-capas.md)) and explicit domain rules ([ADR-0002](docs/adr/0002-reglas-de-negocio-mvp.md)):

```text
ui ──▶ aplicacion ──▶ dominio
         ▲
infraestructura ┘   (implements ports defined in aplicacion)
```

- **Zero Floating-Point Money:** All monetary amounts are stored and computed in integer cents (`int`), and rates/variations are stored in integer basis points (`100 bp = 1%`), enforced both in Python and via SQLite `STRICT` tables.
- **Simple Daily Late Fee (`Mora`):** Calculated dynamically as of "today" (via an injectable `Reloj` clock) over the unpaid principal balance once the grace period is exceeded, and frozen into `imputaciones` when a payment is recorded.
- **FIFO Payment Allocation:** Payments cover accrued late fees first and remaining principal second.
- **Non-Retroactive CPI Adjustments:** Confirmed CPI adjustments update the contract's current rent amount for *future* installment generations without mutating already-issued installments or past payments.
- **Architectural Boundary Enforcement:** Verified automatically by [`tests/test_arquitectura.py`](tests/test_arquitectura.py).

### Project Structure

```text
departamentos-app/
├── main.py                         # Composition root (wires DB, migrations, services, UI)
├── GestionDepartamentos.spec       # PyInstaller build specification
├── requirements.txt                # Pinned runtime and development dependencies
├── docs/                           # ADRs and UX/UI specifications
├── gestion/
│   ├── dominio/                    # Pure business logic & entities (zero external imports)
│   ├── aplicacion/                 # Use cases, DTOs, and port protocols (puertos.py)
│   ├── infraestructura/            # SQLite repositories, sequential migrator, file/backup adapters
│   └── ui/                         # CustomTkinter views, presenters, design tokens, and components
└── tests/                          # Unit, integration, and architecture dependency tests
```

---

## Running the Standalone `.exe` (No Python Required)

If you just want to use the application on Windows without setting up a development environment:

1. Locate the compiled executable at:
   ```text
   dist\GestionDepartamentos.exe
   ```
2. Double-click **`GestionDepartamentos.exe`** (or run `.\dist\GestionDepartamentos.exe` from PowerShell / Command Prompt).
3. **Database & Migrations:** On first launch, the application automatically creates its SQLite database and runs all schema migrations at:
   ```text
   %APPDATA%\GestionDepartamentos\datos.sqlite3
   ```
   *(Typically `C:\Users\<YourUser>\AppData\Roaming\GestionDepartamentos\datos.sqlite3`.)*
   Because the database is stored in your user profile (`%APPDATA%`), you can move or run `GestionDepartamentos.exe` from any folder (such as Desktop or `Program Files`) without losing your data.

---

## Installation & Running from Source

### Prerequisites

- **OS:** Windows 10 or Windows 11
- **Python:** Python **3.13+** (recommended to invoke via the Windows `py` launcher)

### 1. Clone or Download the Repository

```powershell
git clone <repository-url>
cd departamentos-app
```

### 2. Create the Virtual Environment & Install Dependencies

> **Note for Windows users:** Use the `py` launcher to create the virtual environment, and run all commands through `.venv\Scripts\python` to avoid the Windows Store Python alias.

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

### 3. Run the Application in Development Mode

```powershell
.venv\Scripts\python main.py
```

### 4. Run the Test Suite

To run all unit, integration, and architectural boundary tests:

```powershell
.venv\Scripts\python -m pytest tests/
```

---

## Building the `.exe` from Source

The project includes a reproducible **PyInstaller** specification ([`GestionDepartamentos.spec`](GestionDepartamentos.spec)) that bundles `customtkinter` assets and the SQL migrations folder (`gestion/infraestructura/db/migraciones`).

To rebuild `dist\GestionDepartamentos.exe`:

```powershell
.venv\Scripts\python -m PyInstaller --clean --noconfirm GestionDepartamentos.spec
```

Once completed, the standalone single-file executable will be available at:

```text
dist\GestionDepartamentos.exe
```

---

## License

This project is licensed under the **MIT License**. See [LICENSE.md](LICENSE.md) for details.
