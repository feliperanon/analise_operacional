from database import engine
from sqlalchemy import text

def run_migration():
    print('--- Iniciando Migração do Banco de Dados ---')
    with engine.begin() as conn:
        # category
        try:
            conn.execute(text("ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'general'"))
            print("[+] Coluna 'category' adicionada")
        except Exception as e:
            print(f"[!] Erro ao adicionar 'category': {e}")
        
        # trigger_type
        try:
            conn.execute(text("ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS trigger_type VARCHAR(50) DEFAULT 'manual'"))
            print("[+] Coluna 'trigger_type' adicionada")
        except Exception as e:
            print(f"[!] Erro ao adicionar 'trigger_type': {e}")
        
        # trigger_value
        try:
            conn.execute(text("ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS trigger_value TEXT DEFAULT NULL"))
            print("[+] Coluna 'trigger_value' adicionada")
        except Exception as e:
            print(f"[!] Erro ao adicionar 'trigger_value': {e}")
        
        # trigger_rule (Legacy/Compatibility)
        try:
            conn.execute(text("ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS trigger_rule TEXT DEFAULT NULL"))
            print("[!] Coluna 'trigger_rule' (Legacy) verificada")
        except Exception as e:
            pass
            
        # is_manual (Legacy/Compatibility)
        try:
            conn.execute(text("ALTER TABLE gameachievement ADD COLUMN IF NOT EXISTS is_manual BOOLEAN DEFAULT FALSE"))
            print("[!] Coluna 'is_manual' (Legacy) verificada")
        except Exception as e:
            pass

        # Make slug nullable
        try:
            conn.execute(text("ALTER TABLE gameachievement ALTER COLUMN slug DROP NOT NULL"))
            print("[+] Coluna 'slug' agora permite valores nulos")
        except Exception as e:
            print(f"[!] Erro ao alterar 'slug': {e}")

    print('--- Migração Concluída ---')

if __name__ == "__main__":
    run_migration()
