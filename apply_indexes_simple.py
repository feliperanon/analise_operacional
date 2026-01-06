import sqlite3
import os

db_path = "database.db"
sql_file = "migration_add_indexes.sql"

if not os.path.exists(db_path):
    print(f"❌ Banco {db_path} não encontrado.")
    exit(1)

if not os.path.exists(sql_file):
    print(f"❌ SQL {sql_file} não encontrado.")
    exit(1)

print(f"🔧 Aplicando índices em {db_path}...")

with open(sql_file, 'r', encoding='utf-8') as f:
    sql = f.read()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

statements = [s.strip() for s in sql.split(';') if s.strip()]

count = 0
for stmt in statements:
    try:
        cursor.execute(stmt)
        count += 1
        print(f"  ✅ Executado: {stmt[:50]}...")
    except Exception as e:
        print(f"  ⚠️ Erro (pode já existir): {e}")

conn.commit()
conn.close()
print(f"✅ Concluído. {count} índices processados.")
