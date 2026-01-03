"""
Script para aplicar índices de performance no banco de dados.
Executa o arquivo migration_add_indexes.sql
Suporta PostgreSQL e SQLite
"""
import os
import sys

def get_database_config():
    """Detecta configuração do banco a partir do .env"""
    env_file = '.env'
    
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('DATABASE_URL'):
                    db_url = line.split('=', 1)[1].strip()
                    
                    if 'postgresql' in db_url or 'postgres' in db_url:
                        return 'postgresql', db_url
                    elif 'sqlite' in db_url:
                        db_path = db_url.split('sqlite:///')[-1]
                        return 'sqlite', db_path
    
    # Fallback: SQLite local
    return 'sqlite', 'database.db'

def apply_indexes_postgresql(db_url):
    """Aplica índices no PostgreSQL"""
    try:
        import psycopg2
    except ImportError:
        print("❌ Módulo psycopg2 não encontrado!")
        print("💡 Instale com: pip install psycopg2-binary")
        return False
    
    sql_file = 'migration_add_indexes.sql'
    
    if not os.path.exists(sql_file):
        print(f"❌ Arquivo {sql_file} não encontrado!")
        return False
    
    print(f"📂 Lendo {sql_file}...")
    
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    print(f"🗄️  Conectando ao PostgreSQL...")
    print("🔧 Aplicando índices...")
    
    try:
        # Conectar ao PostgreSQL
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Executar cada statement separadamente
        statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]
        
        for i, statement in enumerate(statements, 1):
            if statement:
                # Extrair nome do índice
                idx_name = "..."
                if "idx_" in statement:
                    idx_name = statement.split("idx_")[1].split()[0]
                
                print(f"  [{i}/{len(statements)}] Criando índice: idx_{idx_name}")
                cursor.execute(statement)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Índices criados com sucesso!")
        print(f"📊 Total de índices: {len(statements)}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao aplicar índices: {e}")
        import traceback
        traceback.print_exc()
        return False

def apply_indexes_sqlite(db_path):
    """Aplica índices no SQLite"""
    import sqlite3
    
    sql_file = 'migration_add_indexes.sql'
    
    if not os.path.exists(sql_file):
        print(f"❌ Arquivo {sql_file} não encontrado!")
        return False
    
    if not os.path.exists(db_path):
        print(f"❌ Banco de dados não encontrado: {db_path}")
        return False
    
    print(f"📂 Lendo {sql_file}...")
    
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    print(f"🗄️  Conectando ao SQLite: {db_path}")
    print("🔧 Aplicando índices...")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]
        
        for i, statement in enumerate(statements, 1):
            if statement:
                idx_name = "..."
                if "idx_" in statement:
                    idx_name = statement.split("idx_")[1].split()[0]
                
                print(f"  [{i}/{len(statements)}] Criando índice: idx_{idx_name}")
                cursor.execute(statement)
        
        conn.commit()
        conn.close()
        
        print("✅ Índices criados com sucesso!")
        print(f"📊 Total de índices: {len(statements)}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao aplicar índices: {e}")
        import traceback
        traceback.print_exc()
        return False

def apply_indexes():
    """Detecta tipo de banco e aplica índices"""
    db_type, db_config = get_database_config()
    
    print(f"🔍 Banco detectado: {db_type.upper()}")
    
    if db_type == 'postgresql':
        return apply_indexes_postgresql(db_config)
    elif db_type == 'sqlite':
        return apply_indexes_sqlite(db_config)
    else:
        print(f"❌ Tipo de banco não suportado: {db_type}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 APLICAÇÃO DE ÍNDICES DE PERFORMANCE")
    print("=" * 60)
    
    success = apply_indexes()
    
    if success:
        print("\n✅ Migração concluída com sucesso!")
        print("💡 Reinicie o servidor para aplicar as otimizações.")
    else:
        print("\n❌ Migração falhou. Verifique os erros acima.")
        sys.exit(1)
