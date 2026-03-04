#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para resetar/limpar todos os dados de:
- Separação (/separacao) -> Route (separation + delivery)
- Devoluções (/devolucoes) -> Devolucao, DevolucaoImportBatch, DevolucaoImportRowError, DevolucaoStaging
- BI Delivery (/bi/delivery) -> usa Route + Devolucao (fica zerado ao limpar)

Também limpa DeliverySession (sessões de entrega com placa/KM).

Uso: python reset_delivery_data.py --confirm
"""

import sys
import argparse
from pathlib import Path

# Garante que a raiz do projeto está no path (funciona na raiz ou em scripts/)
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from database import engine
from sqlmodel import Session, delete, func, select
from models import (
    Route,
    DeliverySession,
    Devolucao,
    DevolucaoImportBatch,
    DevolucaoImportRowError,
    DevolucaoStaging,
)


def run_reset(session: Session) -> dict:
    counts = {}
    r = session.execute(delete(DevolucaoStaging))
    counts["DevolucaoStaging"] = r.rowcount or 0
    r = session.execute(delete(DevolucaoImportRowError))
    counts["DevolucaoImportRowError"] = r.rowcount or 0
    r = session.execute(delete(Devolucao))
    counts["Devolucao"] = r.rowcount or 0
    r = session.execute(delete(DevolucaoImportBatch))
    counts["DevolucaoImportBatch"] = r.rowcount or 0
    r = session.execute(delete(DeliverySession))
    counts["DeliverySession"] = r.rowcount or 0
    r = session.execute(delete(Route))
    counts["Route"] = r.rowcount or 0
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Confirma a exclusão")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem excluir")
    args = parser.parse_args()

    if not args.confirm and not args.dry_run:
        print("Erro: use --confirm ou --dry-run")
        sys.exit(1)

    with Session(engine) as session:
        if args.dry_run:
            tables = [
                (DevolucaoStaging, "DevolucaoStaging"),
                (DevolucaoImportRowError, "DevolucaoImportRowError"),
                (Devolucao, "Devolucao"),
                (DevolucaoImportBatch, "DevolucaoImportBatch"),
                (DeliverySession, "DeliverySession"),
                (Route, "Route"),
            ]
            print("Simulação (--dry-run):")
            for model, name in tables:
                count = session.exec(select(func.count()).select_from(model)).one()
                print(f"  {name}: {count}")
            return
        counts = run_reset(session)
        session.commit()

    print("Reset concluído:")
    for table, n in counts.items():
        print(f"  {table}: {n}")


if __name__ == "__main__":
    main()
