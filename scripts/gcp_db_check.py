#!/usr/bin/env python3
"""Testa conexão com PostgreSQL (Cloud SQL / DATABASE_URL). Rode na raiz do projeto."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))


def main() -> int:
    print("Verificando banco configurado no .env …\n")
    try:
        from sqlalchemy import text
        from database import engine

        source = os.environ.get("ACTIVE_DATABASE_SOURCE", "?")
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version()")).scalar()
        print(f"OK — origem: {source}")
        print(f"PostgreSQL: {str(row)[:120]}…")
        return 0
    except Exception as exc:
        print(f"FALHA: {exc}")
        print(
            "\nDicas:\n"
            "  • Criou instância em https://console.cloud.google.com/sql ?\n"
            "  • IP público: autorize seu IP em 'Conexões' e use DATABASE_URL\n"
            "  • Connector: USE_CLOUD_SQL_CONNECTOR=true + CLOUD_SQL_* + gcloud auth application-default login\n"
            "  • Guia completo: docs/GOOGLE_CLOUD_SETUP.md\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
