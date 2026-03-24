from sqlmodel import create_engine, text, inspect
import os
from pathlib import Path
from dotenv import load_dotenv

# Load Env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

# DB Connection
sqlite_url = os.environ.get("DATABASE_URL", "").strip()
if sqlite_url.startswith("postgres://"):
    sqlite_url = sqlite_url.replace("postgres://", "postgresql://", 1)

print(f"Connecting to DB: {sqlite_url}")

connect_args = {"sslmode": "require"} if "postgresql" in sqlite_url else {}
engine = create_engine(sqlite_url, connect_args=connect_args)

try:
    with engine.connect() as conn:
        inspector = inspect(engine)
        columns = inspector.get_columns("employee")
        col_names = [c["name"] for c in columns]
        
        print(f"Current columns in employee: {col_names}")
        
        if "mobile_access_admin_start" not in col_names:
            print("Column 'mobile_access_admin_start' MISSING. Adding it...")
            try:
                # Postgres Syntax
                conn.execute(text("ALTER TABLE employee ADD COLUMN mobile_access_admin_start BOOLEAN DEFAULT FALSE"))
                conn.commit()
                print("Column added successfully!")
            except Exception as e:
                print(f"Error executing ALTER TABLE: {e}")
        else:
            print("Column 'mobile_access_admin_start' ALREADY EXISTS.")

        if "mobile_access_returns" not in col_names:
            print("Column 'mobile_access_returns' MISSING. Adding it...")
            try:
                conn.execute(text("ALTER TABLE employee ADD COLUMN mobile_access_returns BOOLEAN DEFAULT FALSE"))
                conn.commit()
                print("Column mobile_access_returns added successfully!")
            except Exception as e:
                print(f"Error adding mobile_access_returns: {e}")
        else:
            print("Column 'mobile_access_returns' ALREADY EXISTS.")

        if "phone" not in col_names:
            print("Column 'phone' MISSING. Adding it...")
            try:
                conn.execute(text("ALTER TABLE employee ADD COLUMN phone VARCHAR(20)"))
                conn.commit()
                print("Column phone added successfully!")
            except Exception as e:
                print(f"Error adding phone: {e}")
        else:
            print("Column 'phone' ALREADY EXISTS.")

except Exception as e:
    print(f"Connection failed: {e}")
