"""
Script para executar migration da tabela palletcount
Adiciona colunas necessárias para contagem por quantidade (não por número individual)
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Carregar variáveis de ambiente
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    print("❌ DATABASE_URL não encontrada no .env")
    sys.exit(1)

def run_migration():
    """Executa a migration SQL"""
    print("[MIGRATION] Executando migration da tabela palletcount...")
    
    # Ler arquivo SQL
    sql_file = BASE_DIR / "migration_pallet_count_v2.sql"
    if not sql_file.exists():
        print(f"[ERRO] Arquivo de migration nao encontrado: {sql_file}")
        sys.exit(1)
    
    with open(sql_file, "r", encoding="utf-8") as f:
        sql_content = f.read()
    
    try:
        # Conectar ao banco
        conn = psycopg2.connect(DATABASE_URL)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Executar migration
        cursor.execute(sql_content)
        
        print("[OK] Migration executada com sucesso!")
        print("\nColunas adicionadas:")
        print("  - quantity (INTEGER)")
        print("  - previous_quantity (INTEGER)")
        print("  - quantity_difference (INTEGER)")
        print("  - detection_type (VARCHAR)")
        print("  - email_sent_at (TIMESTAMP)")
        print("  - email_error (TEXT)")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"[ERRO] Erro ao executar migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
