import sqlite3

db_file = "database.db"

def check():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    print("--- Tables ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for t in tables:
        print(t[0])
        
    print("\n--- Columns in employeeroutine ---")
    try:
        cursor.execute("PRAGMA table_info(employeeroutine)")
        columns = cursor.fetchall()
        for c in columns:
            print(c)
    except Exception as e:
        print(f"Error: {e}")

    conn.close()

if __name__ == "__main__":
    check()
