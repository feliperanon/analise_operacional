# -*- coding: utf-8 -*-
"""
Corrige colaboradores com admissão e nascimento invertidos no banco.

Uso:
  python scripts/fix_employee_dates_swapped.py
  python scripts/fix_employee_dates_swapped.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import engine  # noqa: E402
from models import Employee  # noqa: E402


def fix_swapped_dates(session: Session, dry_run: bool = False) -> int:
    fixed = 0
    for emp in session.exec(select(Employee)).all():
        if not emp.admission_date or not emp.birthday:
            continue
        if emp.birthday <= emp.admission_date:
            continue
        adm, bday = emp.birthday, emp.admission_date
        print(
            f"{'[dry-run] ' if dry_run else ''}{emp.name} ({emp.registration_id}): "
            f"admissão {emp.admission_date.date()} -> {adm.date()}, "
            f"nascimento {emp.birthday.date()} -> {bday.date()}"
        )
        if not dry_run:
            emp.admission_date = adm
            emp.birthday = bday
            session.add(emp)
        fixed += 1
    if not dry_run and fixed:
        session.commit()
    return fixed


def main() -> int:
    parser = argparse.ArgumentParser(description="Inverte admissão/nascimento quando estiverem trocados.")
    parser.add_argument("--dry-run", action="store_true", help="Somente listar, sem gravar")
    args = parser.parse_args()

    with Session(engine) as session:
        fixed = fix_swapped_dates(session, dry_run=args.dry_run)

    print(f"\nRegistros corrigidos: {fixed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
