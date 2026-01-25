from database import engine
from sqlalchemy import text

def fix_schema():
    with engine.connect() as conn:
        print(f"Connecting to: {engine.url}")
        print("Checking/Adding columns to equipmentticket...")
        
        # List of columns to check/add
        cols_to_add = [
            ("maintenance_email_sent_at", "DATETIME"),
            ("maintenance_email_error", "VARCHAR"),
            ("closed_at", "DATETIME"),
            ("closed_by", "VARCHAR")
        ]

        for col_name, col_type in cols_to_add:
            try:
                # Force attempt to add
                sql = f"ALTER TABLE equipmentticket ADD COLUMN {col_name} {col_type}"
                conn.execute(text(sql))
                print(f"Added column: {col_name}")
            except Exception as e:
                # Check actual error content
                if "duplicate column name" in str(e).lower():
                    print(f"Column {col_name} already confirmed.")
                else:
                    print(f"Error adding {col_name}: {e}")
        
        conn.commit()
        print("Schema fix verification complete.")

if __name__ == "__main__":
    fix_schema()
