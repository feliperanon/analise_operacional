import sqlite3

def run_debug():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    print("--- Tables ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print(cursor.fetchall())

    print("--- Event Schema ---")
    cursor.execute("PRAGMA table_info(event)")
    cols = cursor.fetchall()
    for c in cols:
        print(c)
        
    print("--- Event Data Sample ---")
    cursor.execute("SELECT * FROM event LIMIT 5")
    rows = cursor.fetchall()
    for r in rows:
        print(r)
    
    conn.close()

if __name__ == "__main__":
    run_debug()
