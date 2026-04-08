#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apaga apenas linhas da tabela Devolucao (não altera Route).

Antes de deletar:
- zera duplicate_of_id em outras devoluções que apontam para as removidas;
- zera devolucao_id em DevolucaoStaging;
- remove DevolucaoAjusteResponsabilidade vinculados.

Não apaga: DevolucaoImportBatch, DevolucaoImportRowError, motivos/responsabilidades cadastrais.

O BI e o dashboard ainda podem mostrar devolução se existirem rotas com
delivery_status=devolucao — use scripts/clear_route_delivery_devolucao.py se precisar.

Uso:
  python scripts/delete_devolucoes_only.py --dry-run --since 2026-03-01 --until 2026-03-31
  python scripts/delete_devolucoes_only.py --apply --since 2026-03-01 --until 2026-03-31
  python scripts/delete_devolucoes_only.py --apply --all --confirm-all   # apaga TODAS as devoluções

Requer .env com DATABASE_URL (Postgres) ou SQLite local.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import delete, update
from sqlmodel import Session, select

from database import engine
from models import Devolucao, DevolucaoAjusteResponsabilidade, DevolucaoStaging


def _collect_ids(session: Session, since: str | None, until: str | None, delete_all: bool) -> list[int]:
    q = select(Devolucao)
    if not delete_all:
        q = q.where(Devolucao.data_romaneio >= since).where(Devolucao.data_romaneio <= until)
    rows = session.exec(q).all()
    return [int(d.id) for d in rows if d.id is not None]


def main() -> None:
    p = argparse.ArgumentParser(description="Apaga registros só da tabela Devolucao.")
    p.add_argument("--dry-run", action="store_true", help="Só mostra quantidade (padrão sem --apply).")
    p.add_argument("--apply", action="store_true", help="Executa a exclusão.")
    p.add_argument("--since", type=str, default=None, help="YYYY-MM-DD (data_romaneio), inclusive.")
    p.add_argument("--until", type=str, default=None, help="YYYY-MM-DD (data_romaneio), inclusive.")
    p.add_argument("--all", action="store_true", help="Apagar todas as devoluções (exige --confirm-all).")
    p.add_argument(
        "--confirm-all",
        action="store_true",
        help="Confirma apagar todas as linhas Devolucao (só com --all).",
    )
    args = p.parse_args()

    if args.all:
        if not args.confirm_all:
            print("Erro: com --all é obrigatório passar também --confirm-all.")
            sys.exit(1)
        since = until = None
    else:
        if not args.since or not args.until:
            print("Erro: informe --since e --until (data_romaneio), ou use --all --confirm-all.")
            sys.exit(1)
        since, until = args.since, args.until

    if not args.apply:
        args.dry_run = True

    with Session(engine) as session:
        ids = _collect_ids(session, since, until, args.all)
        print(f"engine={engine.url}")
        if args.all:
            print("modo=ALL (todas as devoluções)")
        else:
            print(f"periodo data_romaneio={since}..{until}")
        print(f"registros Devolucao a apagar: {len(ids)}")

        if args.dry_run and not args.apply:
            print("\n[DRY-RUN] Nada apagado. Use --apply para executar.")
            return

        if not ids:
            session.commit()
            print("\n[OK] Nenhum registro para apagar.")
            return

        session.execute(
            update(Devolucao)
            .where(Devolucao.duplicate_of_id.in_(ids))
            .values(duplicate_of_id=None)
        )
        session.execute(
            update(Devolucao).where(Devolucao.id.in_(ids)).values(duplicate_of_id=None)
        )
        session.execute(
            update(DevolucaoStaging)
            .where(DevolucaoStaging.devolucao_id.in_(ids))
            .values(devolucao_id=None)
        )
        session.execute(
            delete(DevolucaoAjusteResponsabilidade).where(
                DevolucaoAjusteResponsabilidade.devolucao_id.in_(ids)
            )
        )
        session.execute(delete(Devolucao).where(Devolucao.id.in_(ids)))
        session.commit()
        print(f"\n[OK] Removidos {len(ids)} registro(s) em Devolucao (FKs tratadas).")


if __name__ == "__main__":
    main()
