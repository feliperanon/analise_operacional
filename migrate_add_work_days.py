"""
Migração: Adicionar coluna work_days à tabela employee
"""
import sqlite3

# Conectar ao banco
conn = sqlite3.connect('database.db')
cursor = conn.cursor()

try:
    # Tentar adicionar a coluna
    cursor.execute('''
        ALTER TABLE employee 
        ADD COLUMN work_days TEXT DEFAULT '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]'
    ''')
    print("✅ Coluna work_days adicionada com sucesso!")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("ℹ️  Coluna work_days já existe")
    else:
        print(f"❌ Erro: {e}")
        raise

# Atualizar colaboradores existentes que não têm work_days
cursor.execute('''
    UPDATE employee 
    SET work_days = '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]'
    WHERE work_days IS NULL OR work_days = ''
''')

affected = cursor.rowcount
conn.commit()
conn.close()

print(f"✅ Migração concluída: {affected} colaboradores atualizados com dias padrão (Seg-Sáb)")
