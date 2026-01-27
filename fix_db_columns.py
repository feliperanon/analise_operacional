from database import engine
from sqlalchemy import text

def fix_schema():
    with engine.connect() as conn:
        print("Checking/Adding columns to equipmentticket...")
        
        # List of columns to check/add
        # (column_name, column_type)
        cols_to_add = [
            ("maintenance_email_sent_at", "DATETIME"),
            ("maintenance_email_error", "VARCHAR"),
            ("closed_at", "DATETIME"),
            ("closed_by", "VARCHAR")
        ]

        for col_name, col_type in cols_to_add:
            try:
                # Try adding the column. SQLite doesn't support IF NOT EXISTS in ADD COLUMN easily, 
                # so we catch the error if it exists.
                sql = f"ALTER TABLE equipmentticket ADD COLUMN {col_name} {col_type}"
                conn.execute(text(sql))
                print(f"Added column: {col_name}")
            except Exception as e:
                # Expecting "duplicate column name" error if it exists
                if "duplicate column name" in str(e).lower() or "no such table" in str(e).lower():
                    print(f"Column {col_name} already exists or error: {e}")
                else:
                    print(f"Error adding {col_name}: {e}")
        
        conn.commit()
        print("Schema fix complete.")

if __name__ == "__main__":
    fix_schema()
