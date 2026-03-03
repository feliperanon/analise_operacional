from sqlmodel import SQLModel, create_engine, Session

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Check for DATABASE_URL env var (Production) or use local sqlite (Development)
sqlite_file_name = "database.db"
sqlite_url = os.environ.get("DATABASE_URL", f"sqlite:///{sqlite_file_name}").strip()
# Force Local removed per user request

# Fix for Render/Heroku using postgres:// instead of postgresql://
if sqlite_url and sqlite_url.startswith("postgres://"):
    sqlite_url = sqlite_url.replace("postgres://", "postgresql://", 1)

connect_args = {}
if "sqlite" in sqlite_url:
    connect_args = {"check_same_thread": False}
else:
    # Postgres Production Options (Render) + UTF-8 explícito
    connect_args = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "sslmode": "require",
        "options": "-c client_encoding=UTF8"
    }

# Performance: Only echo SQL in DEBUG mode
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
# pool_pre_ping=True helps with "server closed the connection unexpectedly"
# pool_recycle=1800 (30m) recycles connections before cloud timeout (usually 60m)
engine = create_engine(
    sqlite_url, 
    echo=DEBUG, 
    connect_args=connect_args, 
    pool_pre_ping=True, 
    pool_recycle=1800
)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
