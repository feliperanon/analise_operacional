# Implementation Plan: Bulk Absence Import

## Goal
Allow the user to upload an Excel spreadsheet containing historical absence data (Faltas, Atestados) to bulk-update `EmployeeRoutine` and `Event` references.

## Data Source
- Format: Excel `.xlsx`
- Columns: `Matricula`, `Nome` (Ignored), `Data`, `Ocorrencia`
- Mapping:
  - `Matricula` -> `Employee.registration_id`
  - `Data` -> `EmployeeRoutine.date` + `Event.timestamp`
  - `Ocorrencia` -> `EmployeeRoutine.routine` + `Event.type`

## Components

### 1. Backend (`main.py`)
New Endpoint: `POST /api/import/routines`
- Parses Excel.
- Iterates rows.
- Validates Employee existence.
- Normalizes "Ocorrencia" string (e.g., "Falta" -> "absent", "Atestado" -> "sick").
- **Action:**
    - Updates/Creates `EmployeeRoutine` for (Employee, Date).
    - Creates `Event` of type 'falta'/'atestado'.
    - **Crucial:** Does NOT update global `Employee.status` (per previous fix).

### 2. Frontend (`employees.html`)
- Add "Importar Ocorrências" button next to "Importar Colaboradores".
- Modal with File Input.
- Form POST to `/api/import/routines`.

## Logic Details
- **Normalization:**
    - `Falta` -> `routine='absent'`, `event='falta'`
    - `Atestado` -> `routine='sick'`, `event='atestado'`
    - `Suspensão` -> `routine='absent'`, `event='suspension'` (if needed)

- **Idempotency:**
    - If a routine already exists for that day, overwrite it? YES. The spreadsheet is the "correction".

## Verification
- User uploads sample file.
- Check "People Intelligence" report for the imported dates.
