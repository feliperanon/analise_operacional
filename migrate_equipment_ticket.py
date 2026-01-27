"""
Migração: Adicionar colunas faltantes à tabela EquipmentTicket
Execute este script para atualizar o banco de dados de produção.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Get DATABASE_URL
db_url = os.environ.get("DATABASE_URL", "").strip()
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

if not db_url:
    print("ERRO: DATABASE_URL nao configurada")
    exit(1)

print("Conectando ao banco de dados...")

connect_args = {}
if "postgresql" in db_url:
    connect_args = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "sslmode": "require"
    }

engine = create_engine(db_url, connect_args=connect_args)

# Colunas que devem existir na tabela equipmentticket
EXPECTED_COLUMNS = {
    "title": "VARCHAR(255)",
    "shift": "VARCHAR(50)",
    "priority": "VARCHAR(50) DEFAULT 'medium'",
    "severity": "VARCHAR(50) DEFAULT 'low'",
    "resolved_at": "TIMESTAMP WITH TIME ZONE",
    "resolved_by": "VARCHAR(255)",
    "resolution_notes": "TEXT",
    "closed_at": "TIMESTAMP WITH TIME ZONE",
    "closed_by": "VARCHAR(255)",
    "email_sent_at": "TIMESTAMP WITH TIME ZONE",
    "email_error": "TEXT",
    "maintenance_email_sent_at": "TIMESTAMP WITH TIME ZONE",
    "maintenance_email_error": "TEXT"
}

def get_existing_columns(conn, table_name):
    """Retorna lista de colunas existentes na tabela"""
    inspector = inspect(conn)
    columns = inspector.get_columns(table_name)
    return {col['name'].lower() for col in columns}

def create_event_table(conn):
    """Criar tabela equipmentticketevent se nao existir"""
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    
    if "equipmentticketevent" not in tables:
        print("\n[TABELA] Criando tabela 'equipmentticketevent'...")
        sql = """
        CREATE TABLE equipmentticketevent (
            id SERIAL PRIMARY KEY,
            ticket_id INTEGER NOT NULL REFERENCES equipmentticket(id),
            event_type VARCHAR(50) NOT NULL,
            description TEXT NOT NULL,
            created_by VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        CREATE INDEX ix_equipmentticketevent_ticket_id ON equipmentticketevent(ticket_id);
        CREATE INDEX ix_equipmentticketevent_event_type ON equipmentticketevent(event_type);
        CREATE INDEX ix_equipmentticketevent_created_at ON equipmentticketevent(created_at);
        """
        conn.execute(text(sql))
        conn.commit()
        print("   SUCESSO: Tabela 'equipmentticketevent' criada!")
        return True
    else:
        print("\n[TABELA] Tabela 'equipmentticketevent' ja existe.")
        return False

def run_migration():
    with engine.connect() as conn:
        # Verificar se tabela existe
        inspector = inspect(conn)
        tables = inspector.get_table_names()
        
        if "equipmentticket" not in tables:
            print("ERRO: Tabela 'equipmentticket' nao existe. Execute create_db_and_tables() primeiro.")
            return False
        
        # Obter colunas existentes
        existing = get_existing_columns(conn, "equipmentticket")
        print(f"Colunas existentes: {existing}")
        
        # Adicionar colunas faltantes
        added = []
        for col_name, col_type in EXPECTED_COLUMNS.items():
            if col_name.lower() not in existing:
                try:
                    sql = f'ALTER TABLE equipmentticket ADD COLUMN "{col_name}" {col_type}'
                    print(f"   + Adicionando coluna '{col_name}'...")
                    conn.execute(text(sql))
                    conn.commit()
                    added.append(col_name)
                except Exception as e:
                    print(f"   AVISO: Erro ao adicionar '{col_name}': {e}")
            else:
                print(f"   OK: Coluna '{col_name}' ja existe")
        
        # Criar tabela de eventos
        create_event_table(conn)
        
        if added:
            print(f"\nSUCESSO: Migracao concluida! Colunas adicionadas: {', '.join(added)}")
        else:
            print(f"\nSUCESSO: Nenhuma migracao necessaria. Todas as colunas ja existem.")
        
        return True

if __name__ == "__main__":
    print("=" * 60)
    print("MIGRAÇÃO: EquipmentTicket")
    print("=" * 60)
    run_migration()
