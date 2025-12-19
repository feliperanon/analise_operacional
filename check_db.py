
import sqlite3
conn = sqlite3.connect('database.db')
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(employee)")
columns = cursor.fetchall()
for col in columns:
    print(col)
conn.close()
