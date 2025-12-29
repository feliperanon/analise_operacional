"""
Migração: Adicionar coluna work_days à tabela employee (PostgreSQL)
"""
from sqlmodel import create_engine, Session
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()

# Usar mesma configuração do database.py
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database.db")

# Fix for Render/Heroku
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Criar engine
engine = create_engine(DATABASE_URL, echo=False)

try:
    with Session(engine) as session:
        # Tentar adicionar coluna (vai falhar se já existir, mas tudo bem)
        try:
            sql_add = "ALTER TABLE employee ADD COLUMN work_days TEXT DEFAULT '[\"Monday\",\"Tuesday\",\"Wednesday\",\"Thursday\",\"Friday\",\"Saturday\"]';"
            session.exec(text(sql_add))
            session.commit()
            print("✅ Coluna work_days adicionada com sucesso!")
        except Exception as e:
            if "already exists" in str(e) or "duplicate column" in str(e).lower():
                print("ℹ️  Coluna work_days já existe")
                session.rollback()
            else:
                raise
        
        # Atualizar registros existentes que não têm work_days
        sql_update = """
        UPDATE employee 
        SET work_days = '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]'
        WHERE work_days IS NULL OR work_days = '';
        """
        result = session.exec(text(sql_update))
        session.commit()
        
        print(f"✅ Migração concluída! Colaboradores atualizados com dias padrão (Seg-Sáb)")
        
except Exception as e:
    print(f"❌ Erro na migração: {e}")
    import traceback
    traceback.print_exc()
