from sqlmodel import SQLModel, text
from database import engine
import models # Import models to register them with SQLModel

def migrate():
    print("Starting PostgreSQL Migration...")
    
    # 1. Create new tables (XPLedger) safely
    try:
        print("Creating missing tables (XPLedger)...")
        SQLModel.metadata.create_all(engine)
        print("- Tables check/creation done.")
    except Exception as e:
        print(f"Error creating tables: {e}")

    # 2. Alter existing table (EmployeeRoutine)
    # We use raw SQL because SQLModel doesn't migrate existing tables
    from sqlalchemy import inspect
    
    # Check if table exists first (sanity check)
    insp = inspect(engine)
    if not insp.has_table("employeeroutine"):
        print("CRITICAL: 'employeeroutine' table not found in DB!")
        return

    print("Altering EmployeeRoutine table...")
    columns_to_add = [
        ("start_time", "VARCHAR"),
        ("end_time", "VARCHAR"),
        ("status", "VARCHAR DEFAULT 'open'"),
        ("reopened_at", "TIMESTAMP"),
        ("reopened_by", "VARCHAR"),
        ("reopened_reason", "VARCHAR")
    ]

    with engine.connect() as conn:
        conn.begin() # Start transaction
        for col_name, col_type in columns_to_add:
            try:
                # PG supports ADD COLUMN IF NOT EXISTS
                sql = text(f"ALTER TABLE employeeroutine ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
                conn.execute(sql)
                print(f"- Added/Checked column: {col_name}")
            except Exception as e:
                print(f"- Error adding {col_name}: {e}")
        conn.commit()
    
    print("Migration Completed!")

if __name__ == "__main__":
    migrate()
