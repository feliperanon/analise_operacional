import sqlite3

db_file = "database.db"

def migrate():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    print("Starting Fix Migration (EmployeeRoutine columns)...")
    
    columns_to_add = [
        ("start_time", "VARCHAR"),
        ("end_time", "VARCHAR"),
        ("status", "VARCHAR DEFAULT 'open'"),
        ("reopened_at", "DATETIME"),
        ("reopened_by", "VARCHAR"),
        ("reopened_reason", "VARCHAR")
    ]
    
    table_name = "employeeroutine"
    
    for col_name, col_type in columns_to_add:
        try:
            print(f"Adding column {col_name}...")
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
            print(f"- Success: Added {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"- Skipped: {col_name} already exists.")
            else:
                print(f"- Error adding {col_name}: {e}")

    conn.commit()
    conn.close()
    print("Migration Fix Completed!")

if __name__ == "__main__":
    migrate()
