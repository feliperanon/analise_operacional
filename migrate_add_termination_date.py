"""
Migração: Adicionar coluna termination_date à tabela employee (PostgreSQL)
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
        # Tentar adicionar coluna
        try:
            sql_add = "ALTER TABLE employee ADD COLUMN termination_date TIMESTAMP;"
            session.exec(text(sql_add))
            session.commit()
            print("✅ Coluna termination_date adicionada com sucesso!")
        except Exception as e:
            if "already exists" in str(e) or "duplicate column" in str(e).lower():
                print("ℹ️  Coluna termination_date já existe")
                session.rollback()
            else:
                raise
        
        print("✅ Migração concluída!")
        
except Exception as e:
    print(f"❌ Erro na migração: {e}")
    import traceback
    traceback.print_exc()
