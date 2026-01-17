
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

database_url = os.environ.get("DATABASE_URL")

print(f"--- Diagnóstico de Conexão com Banco de Dados ---")
if not database_url:
    print("ERRO: DATABASE_URL não encontrada no ambiente (.env). Usando SQLite local?")
    sys.exit(1)

# Mask password for display
safe_url = database_url.split("@")[-1] if "@" in database_url else "..."
print(f"Tentando conectar em: {safe_url}")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

try:
    # 1. Basic Connection
    print("\n1. Teste Básico (Pool Pre-Ping)...")
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={'sslmode':'require'})
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version();")).fetchone()
        print(f"SUCESSO! Versão: {result[0]}")

    # 2. Teste com Keepalives (Config Atual)
    print("\n2. Teste com Keepalives...")
    ka_args = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "sslmode": "require"
    }
    engine_ka = create_engine(database_url, connect_args=ka_args)
    with engine_ka.connect() as conn:
        result = conn.execute(text("SELECT 1;")).fetchone()
        print(f"SUCESSO! Keepalives funcionando.")

except Exception as e:
    print(f"\n❌ FALHA NA CONEXÃO:")
    print(e)
    print("\nSUGESTÃO: Verifique sua internet, firewall, ou se o Render (banco) está offline.")

print("\n--- Fim do Diagnóstico ---")
