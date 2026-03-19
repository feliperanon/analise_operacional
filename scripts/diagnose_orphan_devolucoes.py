#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnóstico: por que devoluções ORPHAN_ROUTE não foram reconectadas às rotas?

Uso:
  python scripts/diagnose_orphan_devolucoes.py
  python scripts/diagnose_orphan_devolucoes.py "SUPERMERCADOS BH"
  python scripts/diagnose_orphan_devolucoes.py --start 2026-03-01 --end 2026-03-31

Requer DATABASE_URL no .env ou ambiente.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Carrega .env antes de importar database
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from sqlmodel import Session, select
from sqlalchemy import func, or_
from database import engine
from models import Devolucao, Route, Client, Employee


def diagnose(client_filter: str | None = None, start_date: str | None = None, end_date: str | None = None) -> None:
    eff_date = func.coalesce(Devolucao.data_entrega, Devolucao.data_romaneio)
    q = (
        select(Devolucao)
        .where(Devolucao.validation_status == "ORPHAN_ROUTE")
        .where(Devolucao.route_id.is_(None))
        .where(Devolucao.client_id.is_not(None))
        .where(Devolucao.motorista_id.is_not(None))
    )
    if start_date:
        q = q.where(eff_date >= start_date)
    if end_date:
        q = q.where(eff_date <= end_date)
    orphans = list(Session(engine).exec(q.order_by(Devolucao.data_romaneio, Devolucao.id)).all())

    if not orphans:
        print("Nenhuma devolução ORPHAN_ROUTE no período.")
        return

    session = Session(engine)
    print(f"\n=== Diagnóstico de {len(orphans)} devolução(ões) órfã(s) ===\n")

    for d in orphans:
        c = session.get(Client, d.client_id) if d.client_id else None
        m = session.get(Employee, d.motorista_id) if d.motorista_id else None
        client_name = (getattr(c, "name", None) or getattr(c, "razao_social", None) or "-") if c else "-"
        motorista_name = (getattr(m, "name", None) or "-") if m else "-"

        if client_filter and client_filter.upper() not in (client_name or "").upper():
            continue

        data_efetiva = str(d.data_entrega or d.data_romaneio or "")[:10]
        valor = float(d.valor or 0)
        dates_to_try = [d.data_entrega, d.data_romaneio]
        dates_to_try = list(dict.fromkeys(str(x)[:10] for x in dates_to_try if x is not None and str(x).strip()))

        print(f"--- Devolução id={d.id} ---")
        print(f"  Cliente: {client_name} (client_id={d.client_id})")
        print(f"  Motorista: {motorista_name} (motorista_id={d.motorista_id})")
        print(f"  Data efetiva: {data_efetiva} | Valor: R$ {valor:.2f}")
        print(f"  data_romaneio: {d.data_romaneio} | data_entrega: {d.data_entrega}")

        if not dates_to_try:
            print(f"  [ERRO] Sem data válida para buscar rota (data_romaneio/data_entrega vazias)")
            print()
            continue

        # Busca por client + motorista + date
        resolved = False
        for date_str in dates_to_try:
            routes_match = list(session.exec(
                select(Route)
                .where(Route.type == "delivery")
                .where(Route.client_id == d.client_id)
                .where(Route.employee_id == d.motorista_id)
                .where(Route.date == date_str)
            ).all())
            routes_client_only = list(session.exec(
                select(Route)
                .where(Route.type == "delivery")
                .where(Route.client_id == d.client_id)
                .where(Route.date == date_str)
            ).all()) if not routes_match else []

            if routes_match:
                r = routes_match[0]
                print(f"  [OK] Rota encontrada (client+motorista+date): route_id={r.id}, date={r.date}")
                print(f"       -> DEVERIA ter reconectado. Verifique se reconnect foi executado.")
                resolved = True
                break
            elif routes_client_only:
                r = routes_client_only[0]
                emp_route = session.get(Employee, r.employee_id) if r.employee_id else None
                motorista_rota = (getattr(emp_route, "name", None) or "-") if emp_route else "-"
                print(f"  [MOTORISTA DIFERENTE] Rota existe para client+date {date_str}:")
                print(f"       route_id={r.id} | employee_id={r.employee_id} | motorista na rota: {motorista_rota}")
                print(f"       Sugestão: corrigir planilha para motorista: {motorista_rota}")
                resolved = True
                break

        if not resolved:
            # Verifica se existe cliente com nome similar (possível client_id errado)
            term = (client_name or "")[:40].strip() if client_name else ""
            clientes_similares = []
            if term and len(term) > 4:
                clientes_similares = list(session.exec(
                    select(Client).where(
                        or_(
                            Client.name.ilike(f"%{term}%"),
                            (Client.razao_social.is_not(None)) & (Client.razao_social.ilike(f"%{term}%")),
                        )
                    ).limit(10)
                ).all())
            rotas_outro_client = []
            for cc in clientes_similares:
                if cc.id == d.client_id:
                    continue
                rr = list(session.exec(
                    select(Route)
                    .where(Route.type == "delivery")
                    .where(Route.client_id == cc.id)
                    .where(Route.date.in_(dates_to_try))
                    .where(Route.employee_id == d.motorista_id)
                ).all())
                if rr:
                    rotas_outro_client.append((cc, rr))
            if rotas_outro_client:
                print(f"  [CLIENT_ID POSSIVELMENTE ERRADO] Existe rota com cliente similar:")
                for cc, rlist in rotas_outro_client:
                    print(f"       Client id={cc.id}: {getattr(cc, 'name', '')} | routes: {[r.id for r in rlist]}")
            else:
                print(f"  [ROTA NAO ENCONTRADA] Nenhuma rota para client_id={d.client_id}+motorista_id={d.motorista_id}+date em {dates_to_try}")
                # Lista rotas nessa(s) data(s) com cliente de nome similar (diagnóstico)
                search_terms = [term] if term and len(term) > 3 else []
                if client_name and len(client_name) > 5:
                    # Também tenta prefixo (ex: "SUPERMERCADOS BH" para "SUPERMERCADOS BH 19")
                    prefix = " ".join((client_name or "").split()[:3])  # primeiras 3 palavras
                    if prefix and prefix not in search_terms:
                        search_terms.append(prefix)
                for st in search_terms[:2]:  # máx 2 termos
                    rotas_similares = list(session.exec(
                        select(Route, Client)
                        .join(Client, Route.client_id == Client.id)
                        .where(Route.type == "delivery")
                        .where(Route.date.in_(dates_to_try))
                        .where(
                            or_(
                                Client.name.ilike(f"%{st}%"),
                                (Client.razao_social.is_not(None)) & (Client.razao_social.ilike(f"%{st}%")),
                            )
                        )
                        .limit(20)
                    ).all())
                    if rotas_similares:
                        print(f"  [DIAGNOSTICO] Rotas em {dates_to_try} com cliente similar (termo: {st!r}):")
                        for r, c in rotas_similares:
                            emp = session.get(Employee, r.employee_id) if r.employee_id else None
                            emp_nome = (getattr(emp, "name", None) or "-") if emp else "-"
                            print(f"       route_id={r.id} | client_id={r.client_id} ({getattr(c,'name','')}) | employee_id={r.employee_id} ({emp_nome}) | date={r.date}")
                        break
                # Último recurso: lista rotas do motorista nessas datas (qualquer cliente)
                rotas_motorista = list(session.exec(
                    select(Route, Client)
                    .join(Client, Route.client_id == Client.id)
                    .where(Route.type == "delivery")
                    .where(Route.employee_id == d.motorista_id)
                    .where(Route.date.in_(dates_to_try))
                    .limit(20)
                ).all())
                if rotas_motorista:
                    print(f"  [DIAGNOSTICO] Rotas do motorista {motorista_name} (id={d.motorista_id}) em {dates_to_try}:")
                    client_words = set((client_name or "").upper().split()) - {"LTDA", "ME", "EIRELI", "EPP", "COMERCIO", "DE", "ALIM", "ALIMENTOS"}
                    for r, c in rotas_motorista:
                        rc_name = getattr(c, "name", "") or ""
                        extra = ""
                        if client_words and any(len(w) >= 2 and w in (rc_name or "").upper() for w in client_words):
                            extra = " <-- POSSIVEL CLIENTE DUPLICADO (mesmo grupo/nome similar)"
                        print(f"       route_id={r.id} | client_id={r.client_id} ({rc_name}) | date={r.date}{extra}")
        print()
    session.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Diagnostica devoluções ORPHAN_ROUTE não reconectadas")
    ap.add_argument("client_filter", nargs="?", help="Filtrar por nome de cliente (substring)")
    ap.add_argument("--start", default=None, help="Data início YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="Data fim YYYY-MM-DD")
    args = ap.parse_args()
    diagnose(client_filter=args.client_filter, start_date=args.start, end_date=args.end)
