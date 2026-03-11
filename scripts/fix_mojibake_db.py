#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Corrige mojibake em campos de texto do banco de dados.
Execute uma vez para corrigir registros já salvos com encoding errado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.fix_mojibake import fix_mojibake
from database import get_session
from sqlmodel import select
import models


def fix_text(val):
    if not val or not isinstance(val, str):
        return val
    return fix_mojibake(val)


def main():
    session = next(get_session())
    updated = 0

    # Route: delivery_return_reason, delivery_return_category
    routes = session.exec(select(models.Route)).all()
    for r in routes:
        changed = False
        if r.delivery_return_reason:
            new = fix_text(r.delivery_return_reason)
            if new != r.delivery_return_reason:
                r.delivery_return_reason = new
                changed = True
        if r.delivery_return_category:
            new = fix_text(r.delivery_return_category)
            if new != r.delivery_return_category:
                r.delivery_return_category = new
                changed = True
        if changed:
            session.add(r)
            updated += 1

    # Devolucao: motivo, etc. (se existir tabela)
    try:
        devolucoes = session.exec(select(models.Devolucao)).all()
        for d in devolucoes:
            changed = False
            for attr in ["motivo", "responsabilidade", "observacoes"]:
                if hasattr(d, attr):
                    val = getattr(d, attr)
                    if val:
                        new = fix_text(val)
                        if new != val:
                            setattr(d, attr, new)
                            changed = True
            if changed:
                session.add(d)
                updated += 1
    except Exception:
        pass  # Tabela pode não existir

    session.commit()
    print(f"Registros corrigidos no banco: {updated}")
    return 0


if __name__ == "__main__":
    exit(main())
