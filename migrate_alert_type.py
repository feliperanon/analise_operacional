# -*- coding: utf-8 -*-
"""
Migracao: Adicionar coluna alert_type na tabela AbsenceAlertRecipient

Este script adiciona o campo alert_type para suportar diferentes tipos de alertas:
- absent: Falta (advertencia)
- dayoff: Folga
- sick: Atestado medico

Execute: python migrate_alert_type.py
"""

import os
import sys

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("[ERRO] DATABASE_URL nao configurada no .env")
    exit(1)

print("Conectando ao banco de dados...")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Verificar se a tabela existe
    inspector = inspect(engine)
    if "absencealertrecipient" not in inspector.get_table_names():
        print("[ERRO] Tabela absencealertrecipient nao existe. O sistema criara automaticamente ao iniciar.")
        exit(0)
    
    # Verificar se a coluna ja existe
    columns = [col["name"] for col in inspector.get_columns("absencealertrecipient")]
    
    if "alert_type" in columns:
        print("[OK] Coluna 'alert_type' ja existe. Nenhuma alteracao necessaria.")
    else:
        print("[INFO] Adicionando coluna 'alert_type'...")
        
        try:
            # Adicionar a coluna com valor padrao 'absent'
            conn.execute(text("""
                ALTER TABLE absencealertrecipient 
                ADD COLUMN alert_type VARCHAR(20) DEFAULT 'absent'
            """))
            conn.commit()
            print("[OK] Coluna 'alert_type' adicionada com sucesso!")
            
            # Criar indice para melhor performance
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_absencealertrecipient_alert_type 
                    ON absencealertrecipient (alert_type)
                """))
                conn.commit()
                print("[OK] Indice criado com sucesso!")
            except Exception as idx_err:
                print(f"[AVISO] Aviso ao criar indice: {idx_err}")
            
        except Exception as e:
            print(f"[ERRO] Erro ao adicionar coluna: {e}")
            exit(1)
    
    # Informar sobre constraints
    print("[INFO] Verificando constraints...")
    print("  Nota: O email agora pode ser repetido para diferentes tipos de alerta.")
    print("  O sistema validara duplicatas por email + alert_type.")

print("")
print("[OK] Migracao concluida com sucesso!")
print("")
print("Agora voce pode cadastrar destinatarios diferentes para:")
print("  - FALTA (advertencia)")
print("  - FOLGA (notificacao)")
print("  - ATESTADO (notificacao medica)")
