from sqlmodel import text
from database import engine

# This script imports 'engine' directly from database.py
# ensuring it uses the same configuration (Process/Env) as the main app.

def fix_postgres():
    print(f"Connecting to database using engine: {engine.url}")
    with engine.connect() as connection:
        trans = connection.begin()
        try:
            # Check if column exists
            # For Postgres, we can query information_schema or just try/except
            print("Attempting to add 'shift' column...")
            connection.execute(text("ALTER TABLE route ADD COLUMN shift VARCHAR DEFAULT 'Manhã'"))
            trans.commit()
            print("SUCCESS: Column 'shift' added to 'route' table.")
        except Exception as e:
            trans.rollback()
            print(f"FAILED (or column exists): {e}")

if __name__ == "__main__":
    fix_postgres()
