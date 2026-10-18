# 🏢 Brickly

**Fast, local-first Windows desktop app for apartment rental management, collections, daily late fees, and CPI rent adjustments.**

[![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-blue?style=flat)](https://customtkinter.tomschimansky.com/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?style=flat&logo=windows)](https://microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.md)

---

## ⚡ What is Brickly?

**Brickly** is designed for property managers and landlords who need instant answers to three daily operational questions:
1. **Who owes rent today, and how much late fee has accrued?**
2. **Have this month's installments been generated and collected?**
3. **Which lease contracts are due for a CPI (*IPC*) rent adjustment?**

Everything runs **100% locally** on your PC—no external servers, no cloud subscriptions, and with ACID-safe transactional SQLite storage.

---

## ✨ Core Features

| Module | Description |
| :--- | :--- |
| 📊 **Dashboard (`Panel`)** | Real-time monthly KPIs, top 5 overdue arrears with one-click payment, automated alerts (missing CPI, expired leases, backup reminders), and onboarding setup checklist. |
| 🏢 **Apartments & Leases (`Departamentos`)** | Full unit inventory with debounced search, status filters, per-apartment account statements, and lease renewals that preserve payment history. |
| 💰 **Collections & Arrears (`Cobranzas`)** | Idempotent monthly installment generation, cross-period overdue view, and a 380 px **Payment Side Panel** with daily simple late-fee calculation and FIFO allocation. |
| 📈 **CPI Adjustments (`Ajustes IPC`)** | Monthly index tracking, automatic cycle detection, and a **3-step adjustment wizard** featuring compound rate calculations and audited manual overrides. |
| 📑 **Reports & Backup (`Informes`)** | Excel-ready CSV exports (`UTF-8 with BOM`) for account statements, collections, and overdue tenants; plus native SQLite online backups. |
| ⚙️ **Settings (`Configuración`)** | Contract defaults (due day, grace period, late-fee rate), administrator info, and database file location shortcuts. |

---

## 🚀 Quick Start

### Option 1: Standalone Windows App (No Python Needed)
1. Download or locate the precompiled executable at:
   ```text
   dist\GestionDepartamentos.exe
   ```
2. Double-click to launch. The SQLite database is created automatically at `%APPDATA%\GestionDepartamentos\datos.sqlite3`.

### Option 2: Run from Source
Requires **Windows 10/11** and **Python 3.13+**.

```powershell
# 1. Clone the repository
git clone https://github.com/LucaLaatigano/Apartments-Manager.git
cd Apartments-Manager

# 2. Set up virtual environment & install dependencies
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 3. Launch the application
.venv\Scripts\python main.py
```

---

## 🛠️ Development Commands

| Action | PowerShell Command |
| :--- | :--- |
| **Run Test Suite** | `.venv\Scripts\python -m pytest tests/` |
| **Build Executable** | `.venv\Scripts\python -m PyInstaller --clean --noconfirm GestionDepartamentos.spec` |

---

## 🏛️ Architecture & Business Rules

The project strictly follows a **4-Layer Hexagonal Architecture (Ports & Adapters)**, validated by automated architecture tests:

```text
gestion/ui  ──▶  gestion/aplicacion  ──▶  gestion/dominio
                         ▲
gestion/infraestructura  ┘   (implements application ports)
```

- **Zero Floats:** All monetary amounts are stored and calculated in integer cents (`int`), and percentages in basis points (`100 bp = 1%`), enforced by domain logic and SQLite `STRICT` tables.
- **Simple Daily Late Fee:** Dynamically calculated based on current query date (`Reloj`) over unpaid principal once grace period expires.
- **FIFO Allocation:** Payments settle accrued late-fee interest first, then remaining rent principal.
- **Non-Retroactive Adjustments:** Confirmed CPI adjustments update future lease rent without altering past installments or payments.

For design decisions and implementation details, see:
- [ADR-0001: Layered Architecture](docs/adr/0001-arquitectura-de-capas.md)
- [ADR-0002: MVP Business Rules](docs/adr/0002-reglas-de-negocio-mvp.md)
- [UX/UI Specification](docs/ux/especificacion-ux-ui.md)

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE.md](LICENSE.md) for details.
