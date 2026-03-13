#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Limpa horários inválidos em rotas de entrega.

Regra: quem dita a hora é o app mobile. Rotas que não foram iniciadas via mobile
(driver_lat_start is None) não devem ter end_time, delivery_finished_at ou delivery_returned_at,
pois esses horários foram criados por Excel, fechamento forçado ou edição web.

Este script zera esses campos em rotas que:
- São do tipo "delivery"
- Não têm driver_lat_start (nunca foram iniciadas pelo mobile)
- Têm end_time OU delivery_finished_at OU delivery_returned_at preenchidos

Uso:
  python scripts/clear_invalid_route_times.py --dry-run   # mostra quantos seriam limpos
  python scripts/clear_invalid_route_times.py --confirm   # executa a limpeza
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import engine
from sqlmodel import Session, select
from models import Route


def run_clear(session: Session) -> int:
    stmt = (
        select(Route)
        .where(Route.type == "delivery")
        .where(Route.driver_lat_start.is_(None))
        .where(
            (Route.end_time.isnot(None)) |
            (Route.delivery_finished_at.isnot(None)) |
            (Route.delivery_returned_at.isnot(None))
        )
    )
    routes = session.exec(stmt).all()
    count = 0
    for r in routes:
        r.end_time = None
        r.delivery_finished_at = None
        r.delivery_returned_at = None
        session.add(r)
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Limpar horários inválidos em rotas (não iniciadas via mobile)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Executa a limpeza. Sem isso, apenas --dry-run está disponível.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra quantas rotas seriam limpas, sem alterar o banco.",
    )
    args = parser.parse_args()

    if not args.confirm and not args.dry_run:
        print("Use --dry-run para simular ou --confirm para executar.")
        sys.exit(1)

    with Session(engine) as session:
        stmt = (
            select(Route)
            .where(Route.type == "delivery")
            .where(Route.driver_lat_start.is_(None))
            .where(
                (Route.end_time.isnot(None)) |
                (Route.delivery_finished_at.isnot(None)) |
                (Route.delivery_returned_at.isnot(None))
            )
        )
        routes = list(session.exec(stmt).all())
        n = len(routes)

        if args.dry_run:
            print(f"Rotas com horários inválidos (sem mobile): {n}")
            if n > 0 and n <= 20:
                for r in routes:
                    print(f"  id={r.id} date={r.date} client_id={r.client_id} end={r.end_time} finished={r.delivery_finished_at} returned={r.delivery_returned_at}")
            elif n > 20:
                for r in routes[:10]:
                    print(f"  id={r.id} date={r.date} client_id={r.client_id} end={r.end_time}")
                print(f"  ... e mais {n - 10}")
            return

        count = run_clear(session)
        session.commit()
        print(f"Limpeza concluída: {count} rota(s) atualizada(s).")


if __name__ == "__main__":
    main()
