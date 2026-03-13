from pathlib import Path
import unicodedata

import pandas as pd
from sqlalchemy import text
from sqlmodel import Session, select

import models
from database import create_db_and_tables, engine


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


def _pick_col(columns, *candidates):
    col_map = {_norm(c): c for c in columns}
    for c in candidates:
        key = _norm(c)
        if key in col_map:
            return col_map[key]
    return None


def reset_employee_data() -> None:
    # Ordem segura para remover dados dependentes de colaborador.
    tables_to_clear = [
        "substitutionhistory",
        "employeeroutine",
        "event",
        "route",
        "gamexptransaction",
        "employeeachievement",
        "equipmentticketevent",
        "equipmentticket",
        "transpalletchecklist",
        "absencealertlog",
        "dailyoperation",
    ]

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            existing = {
                row[0].lower()
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                ).fetchall()
            }
        else:
            existing = {
                row[0].lower()
                for row in conn.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
                ).fetchall()
            }

        for table_name in tables_to_clear:
            if table_name in existing:
                conn.execute(text(f'DELETE FROM "{table_name}"'))

        if "user" in existing:
            conn.execute(text('DELETE FROM "user" WHERE employee_id IS NOT NULL'))
        if "employee" in existing:
            conn.execute(text('DELETE FROM "employee"'))


def import_souza_pinto(file_path: Path) -> dict:
    df = pd.read_excel(file_path, sheet_name="Souza Pinto", header=0)
    df.columns = df.columns.astype(str).str.strip()

    col_role = _pick_col(df.columns, "Nome Cargo", "Cargo")
    col_reg = _pick_col(df.columns, "Matrícula", "Matricula")
    col_name = _pick_col(df.columns, "Nome Funcionário", "Nome Funcionario", "Nome")
    col_birth = _pick_col(df.columns, "Data de Nascimento", "Dt.Nascimento", "Nascimento")
    col_adm = _pick_col(df.columns, "Adminissão", "Adminissao", "Admissão", "Admissao", "Dt.Admissão")

    if not all([col_role, col_reg, col_name]):
        raise RuntimeError(f"Colunas obrigatórias ausentes: {list(df.columns)}")

    inserted = 0
    invalid = 0
    dup_sheet = 0
    seen = set()

    with Session(engine) as session:
        for _, row in df.iterrows():
            reg = str(row.get(col_reg, "")).strip()
            if not reg or reg.lower() == "nan":
                invalid += 1
                continue
            if reg in seen:
                dup_sheet += 1
                continue
            seen.add(reg)

            admission = None
            if col_adm and pd.notna(row.get(col_adm)):
                dt = pd.to_datetime(row[col_adm], errors="coerce", dayfirst=True)
                if pd.notna(dt):
                    admission = dt.to_pydatetime()

            birthday = None
            if col_birth and pd.notna(row.get(col_birth)):
                dt = pd.to_datetime(row[col_birth], errors="coerce", dayfirst=True)
                if pd.notna(dt):
                    birthday = dt.to_pydatetime()

            name_raw = (str(row.get(col_name, "Sem Nome")).strip() or "Sem Nome")
            emp = models.Employee(
                registration_id=reg,
                name=name_raw.upper(),
                role=((str(row.get(col_role, "Operador")).strip() or "Operador").upper()),
                admission_date=admission,
                birthday=birthday,
                cost_center="Souza Pinto",
                work_shift="Manhã",
                work_schedule="05:00 - 13:20",
                status="active",
            )
            session.add(emp)
            inserted += 1

        session.commit()

        total = len(session.exec(select(models.Employee)).all())

    return {
        "sheet_rows": len(df),
        "inserted": inserted,
        "invalid_without_registration": invalid,
        "duplicates_in_sheet": dup_sheet,
        "total_in_db": total,
    }


def main() -> None:
    create_db_and_tables()
    file_path = Path(r"C:\Users\felip\OneDrive\READET~1\Projeto\Funcionários Exemplar e Souza Pinto.xls")
    if not file_path.exists():
        raise SystemExit(f"Arquivo não encontrado: {file_path}")

    reset_employee_data()
    result = import_souza_pinto(file_path)

    print("Reset + import concluído")
    print(f"Linhas na aba Souza Pinto: {result['sheet_rows']}")
    print(f"Inseridos: {result['inserted']}")
    print(f"Sem matrícula: {result['invalid_without_registration']}")
    print(f"Duplicados na aba: {result['duplicates_in_sheet']}")
    print(f"Total de colaboradores no banco: {result['total_in_db']}")


if __name__ == "__main__":
    main()
