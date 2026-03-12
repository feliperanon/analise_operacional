"""
Serviço de backup do banco de dados.
Suporta SQLite (cópia do arquivo) e PostgreSQL (pg_dump).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

from database import engine

BASE_DIR = Path(__file__).resolve().parent
BACKUPS_DIR = BASE_DIR / "backups"


def _ensure_backups_dir() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUPS_DIR


def _parse_pg_url(url: str) -> dict:
    """Extrai host, port, user, password, dbname de DATABASE_URL."""
    try:
        parsed = urlparse(url)
        # postgresql://user:pass@host:port/dbname
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "user": parsed.username or "postgres",
            "password": parsed.password or "",
            "dbname": (parsed.path or "/postgres").lstrip("/") or "postgres",
        }
    except Exception:
        return {}


def create_backup() -> tuple[Path | None, str | None]:
    """
    Cria backup do banco atual.
    Retorna (caminho_arquivo, None) em sucesso ou (None, mensagem_erro).
    """
    db_url = str(engine.url)
    now = datetime.now().strftime("%Y%m%d_%H%M%S")

    if "sqlite" in db_url:
        # SQLite: copiar database.db
        db_path = BASE_DIR / "database.db"
        if not db_path.exists():
            return None, "Arquivo database.db não encontrado."
        _ensure_backups_dir()
        backup_path = BACKUPS_DIR / f"backup_{now}.db"
        try:
            shutil.copy2(db_path, backup_path)
            return backup_path, None
        except Exception as e:
            return None, str(e)

    elif "postgresql" in db_url or "postgres" in db_url:
        # PostgreSQL: pg_dump
        cfg = _parse_pg_url(db_url)
        _ensure_backups_dir()
        backup_path = BACKUPS_DIR / f"backup_{now}.sql"
        env = os.environ.copy()
        if cfg.get("password"):
            env["PGPASSWORD"] = cfg["password"]
        try:
            result = subprocess.run(
                [
                    "pg_dump",
                    "-h", cfg.get("host", "localhost"),
                    "-p", str(cfg.get("port", 5432)),
                    "-U", cfg.get("user", "postgres"),
                    "-d", cfg.get("dbname", "postgres"),
                    "-F", "c",  # custom format (compressed)
                    "-f", str(backup_path),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return None, result.stderr or result.stdout or "pg_dump falhou."
            return backup_path, None
        except FileNotFoundError:
            # pg_dump não instalado - fallback: dump SQL simples
            try:
                from sqlalchemy import text
                with engine.connect() as conn:
                    # pg_dump não disponível; exportar via SQLAlchemy é complexo
                    return None, "pg_dump não encontrado. Instale o cliente PostgreSQL (psql/pg_dump) no servidor."
            except Exception as e:
                return None, str(e)
        except subprocess.TimeoutExpired:
            return None, "Backup excedeu o tempo limite (120s)."
        except Exception as e:
            return None, str(e)

    return None, "Tipo de banco não suportado para backup."


def list_backups(limit: int = 20) -> list[dict]:
    """Lista backups disponíveis (mais recentes primeiro)."""
    if not BACKUPS_DIR.exists():
        return []
    files = []
    for p in BACKUPS_DIR.glob("backup_*.*"):
        if p.is_file():
            stat = p.stat()
            files.append({
                "name": p.name,
                "path": str(p),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return files[:limit]
