# -*- coding: utf-8 -*-
"""
Gera planilha para excluir colaboradores duplicados (mesmo nome normalizado).

Uso:
  python scripts/export_employee_duplicates.py
  python scripts/export_employee_duplicates.py --output "C:\\Users\\...\\Desktop\\excluir_duplicados.xlsx"

A aba Excluir pode ser enviada em Colaboradores → Excluir por planilha.
A aba Revisão lista o que será removido e o registro que permanece.
"""
from __future__ import annotations

import argparse
import io
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import engine  # noqa: E402
from models import Employee  # noqa: E402


def _name_key(name: str) -> str:
    return " ".join((name or "").strip().upper().split())


def _completeness_score(emp: Employee) -> int:
    score = 0
    if emp.registration_id:
        score += 1
    if emp.seller_code:
        score += 1
    if emp.admission_date:
        score += 1
    if emp.cost_center:
        score += 1
    if emp.role and str(emp.role).strip():
        score += 1
    if emp.birthday:
        score += 1
    if emp.photo_url:
        score += 1
    if emp.work_schedule:
        score += 1
    if emp.status == "active":
        score += 2
    return score


def find_duplicate_groups(employees: list[Employee]) -> list[tuple[str, list[Employee]]]:
    groups: dict[str, list[Employee]] = defaultdict(list)
    for emp in employees:
        key = _name_key(emp.name or "")
        if not key:
            continue
        groups[key].append(emp)
    return [(name, lst) for name, lst in sorted(groups.items()) if len(lst) > 1]


def build_delete_rows(groups: list[tuple[str, list[Employee]]]) -> tuple[list[dict], list[dict]]:
    to_delete: list[dict] = []
    review: list[dict] = []
    for name, emp_list in groups:
        ranked = sorted(emp_list, key=lambda e: (_completeness_score(e), e.id or 0), reverse=True)
        kept = ranked[0]
        for dup in ranked[1:]:
            row = {
                "Matrícula": dup.registration_id or "",
                "Registration": dup.registration_id or "",
            }
            to_delete.append(row)
            review.append(
                {
                    "Nome": name,
                    "Matrícula excluir": dup.registration_id or "",
                    "ID excluir": dup.id,
                    "Código vendedor excluir": (dup.seller_code or "").strip(),
                    "Matrícula manter": kept.registration_id or "",
                    "ID manter": kept.id,
                    "Código vendedor manter": (kept.seller_code or "").strip(),
                    "Motivo": "Nome duplicado na importação",
                }
            )
    return to_delete, review


def build_workbook_bytes(delete_rows: list[dict], review_rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(delete_rows or [{"Matrícula": "", "Registration": ""}]).to_excel(
            writer, sheet_name="Excluir", index=False
        )
        pd.DataFrame(review_rows or [{"Info": "Nenhum duplicado encontrado"}]).to_excel(
            writer, sheet_name="Revisão", index=False
        )
    buf.seek(0)
    return buf.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta planilha de colaboradores duplicados para exclusão.")
    parser.add_argument(
        "--output",
        default=str(Path.home() / "Desktop" / "excluir_colaboradores_duplicados.xlsx"),
        help="Caminho do arquivo .xlsx de saída",
    )
    args = parser.parse_args()
    out_path = Path(args.output)

    with Session(engine) as session:
        employees = session.exec(select(Employee)).all()
        groups = find_duplicate_groups(list(employees))
        delete_rows, review_rows = build_delete_rows(groups)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_workbook_bytes(delete_rows, review_rows))

    print(f"Colaboradores no banco: {len(employees)}")
    print(f"Grupos com nome duplicado: {len(groups)}")
    print(f"Matrículas marcadas para exclusão: {len(delete_rows)}")
    print(f"Planilha gerada: {out_path}")
    if not delete_rows:
        print("Nenhum duplicado encontrado — planilha vazia na aba Excluir.")
    else:
        print("\nPróximo passo:")
        print("  Colaboradores > Excluir por planilha > envie a aba Excluir deste arquivo.")
        print("  Revise a aba Revisão antes de confirmar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
