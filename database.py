from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, dotenv_values

BASE_DIR = Path(__file__).resolve().parent
_env_path = BASE_DIR / ".env"
_cwd_env_path = (Path.cwd() / ".env").resolve()

for _env_key in ("DATABASE_URL", "RENDER_DATABASE_URL", "RENDER_POSTGRES_URL"):
    if (_env_key in os.environ) and not str(os.environ.get(_env_key) or "").strip():
        os.environ.pop(_env_key, None)

load_dotenv(dotenv_path=_env_path, override=False)
if not os.environ.get("DATABASE_URL") and _cwd_env_path != _env_path.resolve():
    load_dotenv(dotenv_path=_cwd_env_path, override=False)

_env_file_values = dotenv_values(_env_path)
_cwd_env_file_values = dotenv_values(_cwd_env_path) if _cwd_env_path != _env_path.resolve() and _cwd_env_path.exists() else {}

sqlite_file_name = "database.db"
local_sqlite_url = f"sqlite:///{sqlite_file_name}"


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _build_connect_args(db_url: str, *, connect_timeout_sec: Optional[int] = None) -> dict:
    if "sqlite" in db_url:
        return {"check_same_thread": False}
    # connect_timeout evita travar o reload do Uvicorn (e o terminal) se a rede/Postgres demorar.
    default_to = int(os.environ.get("DB_CONNECT_TIMEOUT", "12") or "12")
    to = connect_timeout_sec if connect_timeout_sec is not None else max(3, min(default_to, 60))
    # Postgres (Render) options + UTF-8 explícito
    return {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "sslmode": "require",
        "options": "-c client_encoding=UTF8",
        "connect_timeout": to,
    }


def _can_connect(db_url: str, debug: bool, *, log_failure: bool = True) -> bool:
    import logging
    logger = logging.getLogger(__name__)
    try:
        # Sonda: timeout maior para conexão internacional (ex.: Brasil -> Virginia Render)
        probe_to = int(os.environ.get("DB_PROBE_TIMEOUT", "15") or "15")
        probe_engine = create_engine(
            db_url,
            echo=debug,
            connect_args=_build_connect_args(db_url, connect_timeout_sec=max(5, min(probe_to, 45))),
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_timeout=10,
        )
        with probe_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        probe_engine.dispose()
        return True
    except Exception as e:
        safe_url = (db_url.split("@")[-1] if "@" in db_url else db_url)[:80]
        if log_failure:
            logger.warning(
                "Falha ao conectar no Postgres remoto (%s): %s. Usando SQLite local.",
                safe_url,
                str(e),
            )
        return False


def _ordered_remote_candidates() -> list[tuple[str, str]]:
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    keys = ("DATABASE_URL", "RENDER_DATABASE_URL", "RENDER_POSTGRES_URL")
    sources = (
        ("env", os.environ),
        ("file", _env_file_values),
        ("cwd_file", _cwd_env_file_values),
    )
    for source_name, source_values in sources:
        for key in keys:
            candidate = _normalize_url(source_values.get(key, ""))
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            ordered.append((source_name, candidate))
    return ordered


# Render-first: tenta banco remoto primeiro; fallback local apenas se indisponível.
primary_candidates = _ordered_remote_candidates()

# Performance: only echo SQL in DEBUG mode
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
REQUIRE_RENDER_DB = os.environ.get("REQUIRE_RENDER_DB", "false").lower() == "true"
FORCE_LOCAL_DB = os.environ.get("FORCE_LOCAL_DB", "false").lower() == "true"

db_url = local_sqlite_url
if FORCE_LOCAL_DB:
    # Desenvolvimento local: permite subir a aplicação mesmo quando o Postgres remoto
    # está indisponível ou REQUIRE_RENDER_DB=true no .env compartilhado.
    os.environ["ACTIVE_DATABASE_SOURCE"] = "local_forced"
elif primary_candidates:
    for source_name, primary_db_url in primary_candidates:
        if _can_connect(primary_db_url, DEBUG, log_failure=False):
            db_url = primary_db_url
            os.environ["ACTIVE_DATABASE_SOURCE"] = "render"
            os.environ["ACTIVE_DATABASE_URL_SOURCE"] = source_name
            break
    else:
        import logging
        logging.getLogger(__name__).warning(
            "Falha ao conectar em qualquer banco remoto configurado. Usando SQLite local."
        )
        if REQUIRE_RENDER_DB:
            raise RuntimeError(
                "REQUIRE_RENDER_DB=true e falha ao conectar em qualquer banco remoto configurado. "
                "Verifique DATABASE_URL/RENDER_DATABASE_URL/RENDER_POSTGRES_URL e conectividade."
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

_engine_kw = dict(
    echo=DEBUG,
    connect_args=_build_connect_args(db_url),
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
)
# Postgres remoto (ex.: Render EUA): mais conexões reutilizáveis reduzem latência sob carga.
# Em dev, pool menor evita dois processos (reload) disputando muitas conexões no Render.
if "postgresql" in (db_url or "").lower():
    if os.environ.get("ENV", "").lower() in ("prod", "production"):
        _engine_kw["pool_size"] = int(os.environ.get("DB_POOL_SIZE", "8") or "8")
        _engine_kw["max_overflow"] = int(os.environ.get("DB_MAX_OVERFLOW", "12") or "12")
    else:
        _engine_kw["pool_size"] = int(os.environ.get("DB_POOL_SIZE", "3") or "3")
        _engine_kw["max_overflow"] = int(os.environ.get("DB_MAX_OVERFLOW", "5") or "5")

engine = create_engine(db_url, **_engine_kw)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _migrate_devolucao_ajuste_responsavel_ajudante()
    _migrate_devolucao_observacao_gestor()
    _migrate_devolucao_duplicate_fields()
    _migrate_route_escala_status()


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


def _migrate_devolucao_duplicate_fields():
    """duplicate_of_id, validation_status em devolucao."""
    table = "devolucao"
    cols_sqlite = [
        ("duplicate_of_id", "INTEGER"),
        ("validation_status", "TEXT"),
    ]
    try:
        with engine.connect() as conn:
            if "sqlite" in str(engine.url):
                cur = conn.execute(text(f"PRAGMA table_info({table})"))
                existing = [r[1] for r in list(cur) if len(r) > 1]
                for col_name, col_type in cols_sqlite:
                    if col_name not in existing:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
            else:
                for col_name, col_type in cols_sqlite:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            conn.commit()
    except Exception:
        pass


def _migrate_route_escala_status():
    """Adiciona coluna escala_status em route e cria tabela escalaalteracaolog."""
    table = "route"
    col = "escala_status"
    try:
        with engine.connect() as conn:
            if "sqlite" in str(engine.url):
                cur = conn.execute(text(f"PRAGMA table_info({table})"))
                existing = [r[1] for r in list(cur) if len(r) > 1]
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} TEXT"))
            else:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} VARCHAR(32)"))
            conn.commit()
    except Exception:
        pass


def get_session():
    with Session(engine) as session:
        yield session
