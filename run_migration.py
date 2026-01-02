"""
Script para executar migração: adicionar coluna replaced_by usando SQLAlchemy
"""
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# SQL de migração
migration_sql = """
ALTER TABLE employee 
ADD COLUMN IF NOT EXISTS replaced_by INTEGER;
"""

constraint_sql = """
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_employee_replaced_by'
    ) THEN
        ALTER TABLE employee
        ADD CONSTRAINT fk_employee_replaced_by 
        FOREIGN KEY (replaced_by) REFERENCES employee(id);
    END IF;
END $$;
"""

try:
    print("Conectando ao banco de dados...")
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        print("Executando migração...")
        
        # Adicionar coluna
        conn.execute(text(migration_sql))
        print("✅ Coluna 'replaced_by' adicionada")
        
        # Adicionar constraint
        conn.execute(text(constraint_sql))
        print("✅ Foreign key constraint adicionada")
        
        conn.commit()
        
    print("\n🎉 Migração executada com sucesso!")
    print("Reinicie o servidor agora.")
    
except Exception as e:
    print(f"❌ Erro ao executar migração: {e}")
    import traceback
    traceback.print_exc()
