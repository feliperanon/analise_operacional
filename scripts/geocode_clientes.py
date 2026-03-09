#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script standalone para geocodificar clientes pendentes em lote.

Uso:
    python scripts/geocode_clientes.py [--limit N] [--reprocessar-falhas]

Exemplos:
    python scripts/geocode_clientes.py                   # Processa até 100 pendentes
    python scripts/geocode_clientes.py --limit 50        # Processa até 50 pendentes
    python scripts/geocode_clientes.py --reprocessar-falhas  # Reprocessa clientes com falha
"""

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime

# Adiciona o diretório raiz ao path para importar os módulos do projeto
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from sqlmodel import Session, select
from database import engine
import models
from services.geocoding_service import geocoding_service


def geocode_batch(limit: int = 100, reprocessar_falhas: bool = False) -> None:
    """Geocodifica clientes pendentes ou com falha em lote.

    Args:
        limit: Número máximo de clientes a processar.
        reprocessar_falhas: Se True, reprocessa clientes com status 'failed'.
    """
    with Session(engine) as session:
        if reprocessar_falhas:
            query = (
                select(models.Client)
                .where(models.Client.geocoding_status == "failed")
                .limit(limit)
            )
            label = "com falha"
        else:
            query = (
                select(models.Client)
                .where(
                    (models.Client.geocoding_status == "pending")
                    | models.Client.geocoding_status.is_(None)
                )
                .limit(limit)
            )
            label = "pendentes"

        clientes = session.exec(query).all()

        if not clientes:
            print(f"✅ Nenhum cliente {label} encontrado.")
            return

        print(f"🔍 Encontrados {len(clientes)} clientes {label}. Iniciando geocodificação...")
        print(f"   Rate limit: 1 req/segundo (Nominatim)\n")

        total = len(clientes)
        success_count = 0
        failed_count = 0

        for idx, client in enumerate(clientes, 1):
            name = client.razao_social or client.name or f"ID {client.id}"
            address = client.get_full_address()
            print(f"[{idx:3d}/{total}] {name}")
            if address:
                print(f"         Endereço: {address}")

            result = geocoding_service.geocode_cliente(client)
            now = datetime.now()

            if result.success:
                client.latitude = result.latitude
                client.longitude = result.longitude
                client.geocoding_status = "success"
                client.geocoded_at = now
                client.geocoding_source = result.source
                client.geocoding_error = None
                if result.display_name:
                    client.address_normalized = result.display_name[:500]
                session.add(client)
                session.commit()
                success_count += 1
                print(f"         ✅ {result.latitude:.6f}, {result.longitude:.6f}")
            else:
                client.geocoding_status = "failed"
                client.geocoded_at = now
                client.geocoding_error = (result.error or "Erro desconhecido")[:500]
                session.add(client)
                session.commit()
                failed_count += 1
                print(f"         ❌ {result.error}")

        print(f"\n{'='*50}")
        print(f"📊 Estatísticas:")
        print(f"   Total processados : {total}")
        print(f"   ✅ Sucesso         : {success_count}")
        print(f"   ❌ Falhas          : {failed_count}")
        print(f"   Taxa de sucesso   : {success_count/total*100:.1f}%" if total > 0 else "   Taxa de sucesso   : N/A")


def print_stats() -> None:
    """Imprime estatísticas de geocodificação."""
    with Session(engine) as session:
        all_clients = session.exec(select(models.Client)).all()
        total = len(all_clients)
        status_counts: dict = {}
        for c in all_clients:
            st = c.geocoding_status or "pending"
            status_counts[st] = status_counts.get(st, 0) + 1

        com_coords = sum(1 for c in all_clients if c.has_valid_coordinates())

        print(f"\n📊 Status de Geocodificação:")
        print(f"   Total de clientes  : {total}")
        print(f"   Com coordenadas    : {com_coords}")
        print(f"   Sem coordenadas    : {total - com_coords}")
        print(f"\n   Por status:")
        for st, count in sorted(status_counts.items()):
            pct = count / total * 100 if total > 0 else 0
            print(f"     {st:12s}: {count:5d} ({pct:.1f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Geocodifica clientes pendentes usando Nominatim (OpenStreetMap)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Número máximo de clientes a processar (default: 100)",
    )
    parser.add_argument(
        "--reprocessar-falhas",
        action="store_true",
        help="Reprocessa clientes com geocodificação que falhou",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Apenas mostra estatísticas sem processar",
    )
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        geocode_batch(limit=args.limit, reprocessar_falhas=args.reprocessar_falhas)
        print_stats()
