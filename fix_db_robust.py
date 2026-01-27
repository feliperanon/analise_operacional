from database import engine
from sqlalchemy import text, inspect

def fix_robust():
    print(f"Connecting to: {engine.url}")
    inspector = inspect(engine)
    existing_cols = [c['name'] for c in inspector.get_columns('equipmentticket')]
    print(f"Existing columns: {existing_cols}")

    cols_to_add = [
        ("maintenance_email_sent_at", "TIMESTAMP"),
        ("maintenance_email_error", "VARCHAR(255)"),
        ("closed_at", "TIMESTAMP"),
        ("closed_by", "VARCHAR(255)")
    ]

    with engine.connect() as conn:
        for col_name, col_type in cols_to_add:
            if col_name in existing_cols:
                print(f"SKIP: {col_name} exists.")
                continue
            
            print(f"ADDING: {col_name} ({col_type})...")
            try:
                # Postgres often requires transactional DDL commit
                sql = text(f"ALTER TABLE equipmentticket ADD COLUMN {col_name} {col_type}")
                conn.execute(sql)
                conn.commit()
                print(f"SUCCESS: {col_name} added.")
            except Exception as e:
                print(f"ERROR adding {col_name}: {e}")
                conn.rollback()

if __name__ == "__main__":
    fix_robust()
