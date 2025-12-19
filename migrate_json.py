
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(database_url)

with engine.connect() as conn:
    print("Adding JSON column...")
    try:
        conn.execute(text("ALTER TABLE dailyoperation ADD COLUMN attendance_log JSON"))
        conn.commit()
    except Exception as e:
        print(e)
    print("Done.")
