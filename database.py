from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

sqlite_file_name = "database.db"
local_sqlite_url = f"sqlite:///{sqlite_file_name}"


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _build_connect_args(db_url: str) -> dict:
    if "sqlite" in db_url:
        return {"check_same_thread": False}
    # Postgres (Render) options + UTF-8 explícito
    return {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "sslmode": "require",
        "options": "-c client_encoding=UTF8",
    }


def _can_connect(db_url: str, debug: bool) -> bool:
    try:
        probe_engine = create_engine(
            db_url,
            echo=debug,
            connect_args=_build_connect_args(db_url),
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        with probe_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        probe_engine.dispose()
        return True
    except Exception:
        return False


# Render-first: tenta banco remoto primeiro; fallback local apenas se indisponível.
primary_candidates = [
    _normalize_url(os.environ.get("DATABASE_URL", "")),
    _normalize_url(os.environ.get("RENDER_DATABASE_URL", "")),
    _normalize_url(os.environ.get("RENDER_POSTGRES_URL", "")),
]
primary_candidates = [c for c in primary_candidates if c]

# Performance: only echo SQL in DEBUG mode
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

db_url = local_sqlite_url
if primary_candidates:
    primary_db_url = primary_candidates[0]
    if _can_connect(primary_db_url, DEBUG):
        db_url = primary_db_url
        os.environ["ACTIVE_DATABASE_SOURCE"] = "render"
    else:
        db_url = local_sqlite_url
        os.environ["ACTIVE_DATABASE_SOURCE"] = "local_fallback"
else:
    os.environ["ACTIVE_DATABASE_SOURCE"] = "local"

engine = create_engine(
    db_url,
    echo=DEBUG,
    connect_args=_build_connect_args(db_url),
    pool_pre_ping=True,
    pool_recycle=1800,
)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
