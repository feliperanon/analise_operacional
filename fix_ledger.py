import sqlite3
import datetime

db_file = "database.db"

def migrate():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    print("Starting Fix Migration (Rename fields)...")
    
    # Check if XPLedger exists and recreate/fix if needed
    # Since we likely failed to use it yet, we can drop and recreate or just alter if it was created
    # The previous migration might have succeeded in creating the table with 'datetime' and 'type' columns.
    # We should restart fresh for XPLedger or duplicate columns.
    
    try:
        cursor.execute("DROP TABLE IF EXISTS xpledger")
        print("- Dropped old xpledger")
    except Exception as e:
        print(f"- Drop warning: {e}")

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS xpledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                transaction_type VARCHAR NOT NULL,
                points FLOAT NOT NULL,
                reference_id VARCHAR,
                note VARCHAR,
                FOREIGN KEY(employee_id) REFERENCES employee(id)
            )
        """)
        print("- Created 'xpledger' table (v2)")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_xpledger_employee_id ON xpledger (employee_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_xpledger_transaction_type ON xpledger (transaction_type)")
        print("- Created indices")
        
    except Exception as e:
        print(f"Error creating XPLedger: {e}")

    conn.commit()
    conn.close()
    print("Migration Fix Completed!")

if __name__ == "__main__":
    migrate()
