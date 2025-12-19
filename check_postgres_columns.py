
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(database_url)

with engine.connect() as conn:
    print("Columns for dailyoperation:")
    result = conn.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'dailyoperation'"))
    for row in result:
        print(f"- {row[0]} ({row[1]})")
