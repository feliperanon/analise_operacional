"""
Script para limpar dados históricos de rotas/operações antes de 19/01/2026.
Isso vai zerar os gráficos da página /strategy (Curva ABC, Produtividade, SLA, etc.)

AVISO: Este script deleta dados permanentemente!
"""
import os
from datetime import datetime
from dotenv import load_dotenv
from sqlmodel import Session, create_engine, select, delete
from sqlalchemy import text

load_dotenv()

# Conectar ao banco
database_url = os.environ.get("DATABASE_URL")

if not database_url:
    print("❌ ERRO: DATABASE_URL não encontrada!")
    print("   Configure a variável de ambiente DATABASE_URL para o banco de produção")
    print("   Exemplo: postgresql://user:pass@host/dbname")
    exit(1)

# Fix Render postgres:// -> postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

print(f"🔗 Conectando ao banco: {database_url[:50]}...")

connect_args = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
    "sslmode": "require"
}

engine = create_engine(database_url, connect_args=connect_args)

# Data de corte: Deletar tudo ANTES de 19/01/2026
CUTOFF_DATE = "2026-01-19"

print(f"\n🗑️ LIMPEZA DE DADOS - Deletando registros anteriores a {CUTOFF_DATE}")
print("=" * 60)

with Session(engine) as session:
    try:
        # 1. Contar o que será deletado (para confirmação)
        print("\n📊 Contagem de registros que serão deletados:")
        
        # Routes
        result = session.exec(text(f"SELECT COUNT(*) FROM route WHERE date < '{CUTOFF_DATE}'")).one()
        route_count = result[0] if result else 0
        print(f"   - Rotas (route): {route_count}")
        
        # DailyOperation
        result = session.exec(text(f"SELECT COUNT(*) FROM dailyoperation WHERE date < '{CUTOFF_DATE}'")).one()
        daily_count = result[0] if result else 0
        print(f"   - Operações Diárias (dailyoperation): {daily_count}")
        
        # EmployeeRoutine
        result = session.exec(text(f"SELECT COUNT(*) FROM employeeroutine WHERE date < '{CUTOFF_DATE}'")).one()
        routine_count = result[0] if result else 0
        print(f"   - Rotinas de Funcionários (employeeroutine): {routine_count}")
        
        total = route_count + daily_count + routine_count
        print(f"\n   📌 TOTAL: {total} registros serão deletados")
        
        if total == 0:
            print("\n✅ Nenhum dado para deletar. O banco já está limpo!")
            exit(0)
        
        # Confirmação
        print("\n" + "⚠️ " * 20)
        confirm = input(f"\n❓ Confirma a EXCLUSÃO PERMANENTE de {total} registros? (digite 'SIM' para confirmar): ")
        
        if confirm.strip().upper() != "SIM":
            print("\n❌ Operação cancelada pelo usuário.")
            exit(0)
        
        # 2. Deletar dados
        print("\n🗑️ Deletando dados...")
        
        # Routes
        result = session.exec(text(f"DELETE FROM route WHERE date < '{CUTOFF_DATE}'"))
        print(f"   ✅ Rotas deletadas: {route_count}")
        
        # DailyOperation
        result = session.exec(text(f"DELETE FROM dailyoperation WHERE date < '{CUTOFF_DATE}'"))
        print(f"   ✅ Operações Diárias deletadas: {daily_count}")
        
        # EmployeeRoutine
        result = session.exec(text(f"DELETE FROM employeeroutine WHERE date < '{CUTOFF_DATE}'"))
        print(f"   ✅ Rotinas de Funcionários deletadas: {routine_count}")
        
        # Commit
        session.commit()
        
        print("\n" + "=" * 60)
        print("🎉 LIMPEZA CONCLUÍDA COM SUCESSO!")
        print(f"   Os gráficos da página /strategy agora começarão do zero.")
        print(f"   Novos dados serão acumulados a partir de {CUTOFF_DATE}.")
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ ERRO durante a limpeza: {e}")
        raise
