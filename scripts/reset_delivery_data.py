#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para resetar/limpar todos os dados de:
- Separação (/separacao) -> Route (separation + delivery)
- Devoluções (/devolucoes) -> Devolucao, DevolucaoImportBatch, DevolucaoImportRowError, DevolucaoStaging
- BI Delivery (/bi/delivery) -> usa Route + Devolucao (fica zerado ao limpar)

Também limpa DeliverySession (sessões de entrega com placa/KM).

Cadastros (clientes, motoristas, veículos, motivos) são preservados.

Uso: python scripts/reset_delivery_data.py --confirm
"""

import sys
import argparse
from pathlib import Path

# Adiciona raiz do projeto ao path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    # 1. DevolucaoStaging (referencia Devolucao e DevolucaoImportBatch)
    r = session.execute(delete(DevolucaoStaging))
    counts["DevolucaoStaging"] = r.rowcount or 0

    # 2. DevolucaoImportRowError (referencia DevolucaoImportBatch)
    r = session.execute(delete(DevolucaoImportRowError))
    counts["DevolucaoImportRowError"] = r.rowcount or 0

    # 3. Devolucao
    r = session.execute(delete(Devolucao))
    counts["Devolucao"] = r.rowcount or 0

    # 4. DevolucaoImportBatch
    r = session.execute(delete(DevolucaoImportBatch))
    counts["DevolucaoImportBatch"] = r.rowcount or 0

    # 5. DeliverySession (sessões de entrega: placa, KM)
    r = session.execute(delete(DeliverySession))
    counts["DeliverySession"] = r.rowcount or 0

    # 6. Route (separação + entregas)
    r = session.execute(delete(Route))
    counts["Route"] = r.rowcount or 0

    return counts


def main():
    parser = argparse.ArgumentParser(description="Resetar dados de separação, entregas e devoluções")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Obrigatório. Confirma a exclusão dos dados.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas mostra quantos registros seriam removidos, sem excluir.",
    )
    args = parser.parse_args()

    if not args.confirm and not args.dry_run:
        print("Erro: use --confirm para executar ou --dry-run para simular.")
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
            print("Simulação (--dry-run): registros que seriam removidos:")
            for model, name in tables:
                count = session.exec(select(func.count()).select_from(model)).one()
                print(f"  {name}: {count}")
            return

        counts = run_reset(session)
        session.commit()

    print("Reset concluído. Registros removidos:")
    for table, n in counts.items():
        print(f"  {table}: {n}")
    print("\nSeparação, entregas, devoluções e BI Delivery estão zerados.")


if __name__ == "__main__":
    main()
