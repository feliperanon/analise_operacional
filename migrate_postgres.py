
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    print("No DATABASE_URL found. Using SQLite?")
    exit(1)

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

print(f"Connecting to: {database_url.split('@')[-1]}") # Hide credentials

engine = create_engine(database_url)

with engine.connect() as conn:
    print("Checking columns...")
    try:
        # Check flow_step
        try:
            conn.execute(text("SELECT flow_step FROM employee LIMIT 1"))
            print("flow_step exists.")
        except Exception:
            print("Adding flow_step...")
            conn.rollback()
            conn.execute(text("ALTER TABLE employee ADD COLUMN flow_step VARCHAR"))
            conn.commit()
            print("Added flow_step.")

        # Check flow_override_sector
        try:
            conn.execute(text("SELECT flow_override_sector FROM employee LIMIT 1"))
            print("flow_override_sector exists.")
        except Exception:
            print("Adding flow_override_sector...")
            conn.rollback()
            conn.execute(text("ALTER TABLE employee ADD COLUMN flow_override_sector VARCHAR"))
            conn.commit()
            print("Added flow_override_sector.")
            
        print("Migration done.")
    except Exception as e:
        print(f"Error: {e}")
