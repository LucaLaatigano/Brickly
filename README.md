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

Everything runs **100% locally** on your PC — no external servers, no cloud subscriptions, and with ACID-safe transactional SQLite storage.

---

## ✨ Core Features

| Module | Description |
| :--- | :--- |
| 📊 **Dashboard (`Panel`)** | Real-time monthly KPIs, top 5 overdue arrears with one-click payment, automated alerts (missing CPI, expired leases, backup reminders), and onboarding setup checklist. |
| 🏢 **Apartments & Leases (`Departamentos`)** | Full unit inventory with debounced search, status filters, per-apartment account statements, and lease renewals that preserve payment history. |
| 💰 **Collections & Arrears (`Cobranzas`)** | Idempotent monthly installment generation, cross-period overdue view, 380 px **Payment Side Panel** with daily simple late-fee calculation and FIFO allocation, and one-click **PDF Payment Receipts (`Constancia de pago`)** for paid installments. |
| 📈 **CPI Adjustments (`Ajustes IPC`)** | Official **INDEC API** synchronization + manual fallback, automatic cycle detection, and a **3-step adjustment wizard** featuring compound rate calculations and audited manual overrides. |
| 📑 **Reports & Backup (`Informes`)** | Full multi-sheet Excel workbook (`.xlsx` with `Resumen`, `Deudas`, `Pagos`, `Cuotas`, `Contratos`, `Ajustes IPC`), Excel-ready CSV exports (`UTF-8 with BOM`), and native SQLite online backups. |
| ⚙️ **Settings (`Configuración`)** | Contract defaults (due day, grace period, late-fee rate), administrator info for receipts and exports, INDEC token management, and database file location shortcuts. |

---

## 🧾 Monthly Payment Receipts (`Constancia de pago` PDF)

Once a monthly installment reaches the **`Pagada`** state, you can issue a PDF receipt for the tenant:

1. Go to **Cobranzas → Mes**.
2. Click any row with status **`Pagada`** to open the 380 px **Constancia de pago** preview panel on the right.
3. Review the unit, tenant (from that installment's lease), period, principal, late fee collected, imputed payments, and signature block.
4. Click **Generar PDF** and choose where to save `constancia-<unidad>-<mes>-<anio>.pdf` (defaults to Desktop).

> **Scope & Legal Note:** The generated PDF certifies payment **only for that specific unit and period** (it is not a general clearance or *libre deuda* certificate). It includes a **visual** signature line (`Propietario/a o Administrador/a`) for printing or hand-signing — it is **not** a digital cryptographic signature and **not** a tax invoice or fiscal receipt (*comprobante fiscal*).

---

## 🚀 Download and install (Windows)

### Requirements

- Windows 10 or 11, 64-bit.
- No Python installation is required.
- No administrator permissions are required.

### Steps

1. Open the latest release:

   **https://github.com/LucaLaatigano/Brickly/releases/latest**

2. Download these two files:

   - `Brickly.exe`
   - `SHA256.txt` (published with the same release)

3. Verify the download in PowerShell:

   ```powershell
   Get-FileHash .\Brickly.exe -Algorithm SHA256
   ```

   The output must match the value in `SHA256.txt`. If it does not match,
   delete the file and download it again from the official release.

4. Windows SmartScreen may show a warning because the executable is not
   code-signed. Only if you downloaded it from the official release above,
   click **More info** → **Run anyway**.

5. Double-click `Brickly.exe`. There is no installer: the app runs directly.

The database is created automatically on first launch at:

```text
%APPDATA%\Brickly\datos.sqlite3
```

### Upgrading from an older version

1. Create a backup from **Informes → Respaldo de la base**.
2. Close Brickly.
3. Replace the old `.exe` with the new `Brickly.exe`.
4. Open the app. Your data stays in `%APPDATA%\Brickly`.

If you used the previous `GestionDepartamentos` version, Brickly copies its
database once, on first launch, and keeps the old folder untouched as a
backup.

### Uninstalling

- Delete `Brickly.exe`.
- Optionally delete `%APPDATA%\Brickly` to remove all local data.
- The old `%APPDATA%\GestionDepartamentos` folder is never deleted by Brickly.

---

## 💾 Data and backups

Brickly stores everything locally in one SQLite database:

```text
%APPDATA%\Brickly\datos.sqlite3
```

- **Backup:** open **Informes** and use **Respaldo de la base**. The file is
  a consistent SQLite online backup.
- **Restore:** close Brickly, replace `datos.sqlite3` with the backup file, and
  open the app again.
- **Move to another PC:** copy the backup file to the same path on the new PC.

The app never uploads your data. The only network feature is the optional INDEC
CPI integration, which queries public national index series and sends no tenant
or payment data.

---

## 🧑‍💻 Run from source

Requires **Windows 10/11** and **Python 3.13+**.

```powershell
# 1. Clone the repository
git clone https://github.com/LucaLaatigano/Brickly.git
cd Brickly

# 2. Create the virtual environment and install dependencies
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 3. Launch the application
.venv\Scripts\python main.py
```

On Windows, use `py` to create the virtual environment. The `python` alias from
the Microsoft Store does not work for this project.

---

## 🛠️ Development commands

| Action | PowerShell command |
| :--- | :--- |
| **Run tests** | `.venv\Scripts\python -m pytest tests/` |
| **Build executable** | `.venv\Scripts\python -m PyInstaller --clean --noconfirm Brickly.spec` |
| **Built executable** | `dist\Brickly.exe` |

The build is reproducible with `Brickly.spec`: it bundles CustomTkinter and the
SQL migration scripts as application data.

---

## 🏛️ Architecture and business rules

The project strictly follows a **4-layer Hexagonal Architecture (Ports & Adapters)**, validated by automated architecture tests:

```text
brickly/ui  ──▶  brickly/aplicacion  ──▶  brickly/dominio
                          ▲
brickly/infraestructura  ┘   (implements application ports)
```

- **Zero floats:** all monetary amounts are stored and calculated in integer
  cents (`int`), and percentages in basis points (`100 bp = 1%`), enforced by
  domain logic and SQLite `STRICT` tables.
- **Simple daily late fee:** dynamically calculated based on the current query
  date (`Reloj`) over unpaid principal once the grace period expires.
- **FIFO allocation:** payments settle accrued late-fee interest first, then
  remaining rent principal.
- **Non-retroactive adjustments:** confirmed CPI adjustments update future
  lease rent without altering past installments or payments.
- **Official INDEC CPI sync + manual fallback:** monthly CPI variations can be
  synchronized from `api.indec.gob.ar` (**Ajustes IPC → Actualizar desde INDEC**)
  or entered manually. The API token is stored in the Windows Credential Manager
  (never in SQLite or backups), and manual values are never overwritten without
  explicit confirmation.

For design decisions and implementation details, see:

- [ADR-0001: Layered Architecture](docs/adr/0001-arquitectura-de-capas.md)
- [ADR-0002: MVP Business Rules](docs/adr/0002-reglas-de-negocio-mvp.md)
- [ADR-0003: Automatic INDEC CPI Synchronization](docs/adr/0003-ipc-automatico-indec.md)
- [ADR-0004: Monthly PDF Payment Receipt](docs/adr/0004-constancia-pago-pdf.md)
- [UX/UI Specification](docs/ux/especificacion-ux-ui.md)

---

## 🧯 Troubleshooting

| Problem | What to do |
| :--- | :--- |
| Windows SmartScreen blocks the app | Use **More info → Run anyway**, but only for a file downloaded from the official release. |
| Antivirus flags the executable | The app is packaged with PyInstaller and is not code-signed. Verify the SHA256 and, if needed, add an exclusion for `Brickly.exe`. |
| The app does not start | Make sure `Brickly.exe` is in a folder where your user can run files. Check that `%APPDATA%\Brickly` is writable. |
| An Excel (`.xlsx`), CSV, or PDF file cannot be written | Close the file if it is currently open in Excel or a PDF viewer and try again. |
| INDEC sync button is disabled or fails | Check in **Configuración → INDEC** that a valid token from `api.indec.gob.ar` is saved and has not expired. You can always enter CPI values manually in **Ajustes IPC**. |
| The database looks empty | Check that you are using the same Windows user. Data lives under that user's `%APPDATA%`. |
| An old database was not migrated | Confirm that `%APPDATA%\GestionDepartamentos\datos.sqlite3` exists and that `%APPDATA%\Brickly\datos.sqlite3` does not. Brickly never overwrites an existing new database. |

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE.md](LICENSE.md) for details.
