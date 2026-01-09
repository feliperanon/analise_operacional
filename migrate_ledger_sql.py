import sqlite3
import datetime

db_file = "database.db"

def migrate():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    print("Starting Raw SQL Migration...")
    
    # 1. Add columns to EmployeeRoutine
    columns_to_add = [
        ("reopened_at", "DATETIME"),
        ("reopened_by", "VARCHAR"),
        ("reopened_reason", "VARCHAR")
    ]
    
    for col, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE employeeroutine ADD COLUMN {col} {col_type}")
            print(f"- Added '{col}' column")
        except sqlite3.OperationalError as e:
            print(f"- '{col}' warning: {e}")

    # 2. Create XPLedger Table
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS xpledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                datetime DATETIME NOT NULL,
                type VARCHAR NOT NULL,
                points FLOAT NOT NULL,
                reference_id VARCHAR,
                note VARCHAR,
                FOREIGN KEY(employee_id) REFERENCES employee(id)
            )
        """)
        print("- Created 'xpledger' table")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_xpledger_employee_id ON xpledger (employee_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_xpledger_type ON xpledger (type)")
        print("- Created indices")
        
    except Exception as e:
        print(f"Error creating XPLedger: {e}")

    conn.commit()
    conn.close()
    print("Migration Completed!")

if __name__ == "__main__":
    migrate()
