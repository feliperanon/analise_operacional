from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

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
REQUIRE_RENDER_DB = os.environ.get("REQUIRE_RENDER_DB", "false").lower() == "true"

db_url = local_sqlite_url
if primary_candidates:
    primary_db_url = primary_candidates[0]
    if _can_connect(primary_db_url, DEBUG):
        db_url = primary_db_url
        os.environ["ACTIVE_DATABASE_SOURCE"] = "render"
    else:
        if REQUIRE_RENDER_DB:
            raise RuntimeError(
                "REQUIRE_RENDER_DB=true e falha ao conectar no banco remoto (DATABASE_URL). "
                "Verifique DATABASE_URL/RENDER_DATABASE_URL e conectividade."
            )
        db_url = local_sqlite_url
        os.environ["ACTIVE_DATABASE_SOURCE"] = "local_fallback"
else:
    if REQUIRE_RENDER_DB:
        raise RuntimeError(
            "REQUIRE_RENDER_DB=true mas nenhuma URL remota foi encontrada. "
            "Defina DATABASE_URL (ou RENDER_DATABASE_URL/RENDER_POSTGRES_URL)."
        )
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
    _migrate_devolucao_ajuste_responsavel_ajudante()
    _migrate_devolucao_observacao_gestor()


def _migrate_devolucao_observacao_gestor():
    """Adiciona colunas observacao_gestor, observacao_gestor_edited_by, observacao_gestor_edited_at em devolucao."""
    table = "devolucao"
    cols = [
        ("observacao_gestor", "TEXT"),
        ("observacao_gestor_edited_by", "VARCHAR(255)" if "postgresql" in str(engine.url) else "TEXT"),
        ("observacao_gestor_edited_at", "TIMESTAMP" if "postgresql" in str(engine.url) else "DATETIME"),
    ]
    try:
        with engine.connect() as conn:
            if "sqlite" in str(engine.url):
                cur = conn.execute(text(f"PRAGMA table_info({table})"))
                existing = [r[1] for r in list(cur) if len(r) > 1]
                for col_name, col_type in cols:
                    if col_name not in existing:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
            else:
                for col_name, col_type in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            conn.commit()
    except Exception:
        pass


def _migrate_devolucao_ajuste_responsavel_ajudante():
    """Adiciona coluna responsavel_ajudante em devolucaoajusteresponsabilidade se não existir."""
    table = "devolucaoajusteresponsabilidade"
    col = "responsavel_ajudante"
    try:
        with engine.connect() as conn:
            if "sqlite" in str(engine.url):
                cur = conn.execute(text(f"PRAGMA table_info({table})"))
                rows = list(cur) if hasattr(cur, "fetchall") else list(cur)
                if rows and not any((getattr(r, "name", r[1] if len(r) > 1 else None) == col for r in rows)):
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} BOOLEAN DEFAULT 1"))
            else:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT TRUE"
                ))
            conn.commit()
    except Exception:
        pass  # coluna já existe ou tabela não existe

def get_session():
    with Session(engine) as session:
        yield session
