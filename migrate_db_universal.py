from sqlalchemy import text
from database import engine

def migrate():
    print("Starting migration using configured engine...")
    with engine.connect() as conn:
        with conn.begin():
            # Add vacation_start
            try:
                print("Attempting to add vacation_start...")
                conn.execute(text("ALTER TABLE employee ADD COLUMN vacation_start TIMESTAMP"))
                print("Successfully added vacation_start column")
            except Exception as e:
                print(f"Skipped vacation_start (check error if not expected): {e}")

            # Add vacation_end
            try:
                print("Attempting to add vacation_end...")
                conn.execute(text("ALTER TABLE employee ADD COLUMN vacation_end TIMESTAMP"))
                print("Successfully added vacation_end column")
            except Exception as e:
                print(f"Skipped vacation_end (check error if not expected): {e}")

    print("Migration completed.")

if __name__ == "__main__":
    migrate()
