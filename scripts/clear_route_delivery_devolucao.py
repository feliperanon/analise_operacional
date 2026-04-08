#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zera o indicador de devolução do dashboard que usa Route.delivery_status.

O /dashboard compara rotas com status entregue|devolucao; linhas com
delivery_status=devolucao entram no numerador. Limpar só a tabela Devolucao
não altera esse KPI.

Este script define delivery_status='entregue' nas rotas type=delivery que
estão como devolucao (preserva registros e FKs em deliveryauthrequest, etc.).

O BI Delivery (/bi/delivery) usa essas rotas para taxa em quantidade e valor;
limpar só a tabela Devolucao não remove o efeito se a rota continuar como
devolucao. Use --zero-return-fields para também zerar valor/motivo na rota.

Uso:
  python scripts/clear_route_delivery_devolucao.py --dry-run
  python scripts/clear_route_delivery_devolucao.py --apply
  python scripts/clear_route_delivery_devolucao.py --apply --since 2026-03-01 --until 2026-03-31
  python scripts/clear_route_delivery_devolucao.py --apply --since 2026-03-01 --until 2026-03-31 --zero-return-fields

Reset total (apaga TODAS as rotas + devoluções — destrutivo): ver reset_delivery_data.py

Requer DATABASE_URL no .env (Postgres) ou database.db local (SQLite).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from sqlmodel import Session, select

from database import engine
from models import Route


def main() -> None:
    p = argparse.ArgumentParser(description="Limpa status devolucao em rotas de entrega (KPI informativo).")
    p.add_argument("--dry-run", action="store_true", help="Só lista quantas rotas seriam alteradas (padrão se não passar --apply).")
    p.add_argument("--apply", action="store_true", help="Aplica alteração no banco.")
    p.add_argument("--since", type=str, default=None, help="YYYY-MM-DD inclusive (opcional).")
    p.add_argument("--until", type=str, default=None, help="YYYY-MM-DD inclusive (opcional).")
    p.add_argument(
        "--zero-return-fields",
        action="store_true",
        help="Com --apply: zera valor_devolucao/devolucao_volume e limpa motivo/categoria/foto de devolução na rota.",
    )
    args = p.parse_args()

    if not args.apply:
        args.dry_run = True

    q = select(Route).where(Route.type == "delivery")
    if args.since:
        q = q.where(Route.date >= args.since)
    if args.until:
        q = q.where(Route.date <= args.until)

    with Session(engine) as session:
        rows = list(session.exec(q).all())
        alvo = [r for r in rows if (r.delivery_status or "").strip().lower() == "devolucao"]

        print(f"engine={engine.url}")
        print(f"rotas delivery no filtro: {len(rows)}")
        print(f"com delivery_status=devolucao: {len(alvo)}")
        if alvo:
            alvo.sort(key=lambda r: ((r.date or ""), int(r.id or 0)))
            for r in alvo[:50]:
                print(f"  id={r.id} date={r.date} employee_id={r.employee_id} client_id={r.client_id}")
            if len(alvo) > 50:
                print(f"  ... e mais {len(alvo) - 50} rotas.")

        if args.dry_run and not args.apply:
            print("\n[DRY-RUN] Nada alterado. Use --apply para gravar.")
            return

        for r in alvo:
            r.delivery_status = "entregue"
            if args.zero_return_fields:
                r.valor_devolucao = None
                r.devolucao_volume = None
                r.delivery_return_reason = None
                r.delivery_return_category = None
                r.delivery_return_photo_url = None
        session.commit()
        extra = " + campos de devolução zerados na rota." if args.zero_return_fields else "."
        print(f"\n[OK] Atualizadas {len(alvo)} rota(s) para delivery_status=entregue{extra}")


if __name__ == "__main__":
    main()
