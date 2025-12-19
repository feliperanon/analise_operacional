
import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine
import models # Load models

load_dotenv()

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    print("No DATABASE_URL found.")
    exit(1)

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

print(f"Connecting to: {database_url.split('@')[-1]}")

engine = create_engine(database_url)

print("Creating tables...")
SQLModel.metadata.create_all(engine)
print("Done.")
