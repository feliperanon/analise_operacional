"""
Conexão com Google Cloud SQL (PostgreSQL).

Modos suportados:
1. DATABASE_URL / GOOGLE_DATABASE_URL — IP público ou proxy local (psycopg2 normal).
2. Socket Unix no Cloud Run — URL montada a partir de CLOUD_SQL_CONNECTION_NAME.
3. Cloud SQL Python Connector — USE_CLOUD_SQL_CONNECTOR=true (recomendado sem IP público).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


def connection_name() -> str:
    return (os.environ.get("CLOUD_SQL_CONNECTION_NAME") or "").strip()


def db_user() -> str:
    return (os.environ.get("CLOUD_SQL_USER") or os.environ.get("DB_USER") or "").strip()


def db_password() -> str:
    return (os.environ.get("CLOUD_SQL_PASSWORD") or os.environ.get("DB_PASSWORD") or "").strip()


def db_name() -> str:
    return (os.environ.get("CLOUD_SQL_DB") or os.environ.get("DB_NAME") or "").strip()


def connector_fully_configured() -> bool:
    return bool(connection_name() and db_user() and db_password() and db_name())


def should_use_connector() -> bool:
    if _flag("USE_CLOUD_SQL_CONNECTOR"):
        return connector_fully_configured()
    # Sem DATABASE_URL explícita: montar conexão só pelo connector.
    if connector_fully_configured() and not (os.environ.get("DATABASE_URL") or "").strip():
        return True
    return False


def build_socket_database_url() -> Optional[str]:
    """URL para socket /cloudsql/PROJECT:REGION:INSTANCE (Cloud Run + volume)."""
    cn = connection_name()
    user = db_user()
    password = db_password()
    name = db_name()
    if not (cn and user and password and name):
        return None
    host = f"/cloudsql/{cn}"
    return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@/{quote_plus(name)}?host={quote_plus(host)}"


def _connector_ip_type():
    raw = (os.environ.get("CLOUD_SQL_IP_TYPE") or "public").strip().lower()
    try:
        from google.cloud.sql.connector import IPTypes

        if raw in ("private", "priv", "p"):
            return IPTypes.PRIVATE
        return IPTypes.PUBLIC
    except Exception:
        return None


def probe_connector(debug: bool = False) -> bool:
    if not connector_fully_configured():
        return False
    try:
        eng = create_engine_with_connector(echo=debug, pool_pre_ping=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception as exc:
        logger.warning("Cloud SQL Connector: falha na sonda: %s", exc)
        return False


def create_engine_with_connector(**engine_kwargs: Any) -> Engine:
    from google.cloud.sql.connector import Connector

    cn = connection_name()
    user = db_user()
    password = db_password()
    name = db_name()
    ip_type = _connector_ip_type()

    connector = Connector()

    def getconn():
        kwargs = {
            "user": user,
            "password": password,
            "db": name,
        }
        if ip_type is not None:
            kwargs["ip_type"] = ip_type
        return connector.connect(cn, "pg8000", **kwargs)

    # connect_args da URL não se aplicam ao creator.
    kw = dict(engine_kwargs)
    kw.pop("connect_args", None)
    return create_engine("postgresql+pg8000://", creator=getconn, **kw)
