import sqlite3

def run_migration():
    db_path = "database.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check columns
        cursor.execute("PRAGMA table_info(employeeroutine)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "start_time" not in columns:
            print("Adding start_time...")
            cursor.execute("ALTER TABLE employeeroutine ADD COLUMN start_time TEXT")
            
        if "end_time" not in columns:
            print("Adding end_time...")
            cursor.execute("ALTER TABLE employeeroutine ADD COLUMN end_time TEXT")
            
        if "status" not in columns:
            print("Adding status...")
            cursor.execute("ALTER TABLE employeeroutine ADD COLUMN status TEXT DEFAULT 'open'")
            
        conn.commit()
        print("Migration successful: EmployeeRoutine updated.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
