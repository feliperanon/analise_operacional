
from sqlmodel import text
from sqlalchemy import exc
from database import engine

# Removed local sqlite hardcoding
# sqlite_url = "sqlite:///database.db"
# engine = create_engine(sqlite_url)

def apply_migration():
    print("Applying migration: Add work_schedule to employee...")
    try:
        with engine.connect() as conn:
            with open("migration_add_work_schedule.sql", "r") as f:
                sql = f.read()
            conn.execute(text(sql))
            conn.commit()
        print("Migration applied successfully!")
    except exc.OperationalError as e:
        if "duplicate column name" in str(e):
            print("Column already exists. Skipping.")
        else:
            print(f"Error applying migration: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    apply_migration()
