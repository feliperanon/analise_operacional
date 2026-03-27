# -*- coding: utf-8 -*-
"""
Análise Operacional — FastAPI entry point.

Startup: apenas create_db_and_tables() do database.py (SQLModel/SQLAlchemy).
Alembic NÃO é executado no startup — as tabelas já existem no banco migrado.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Callable, List, Optional
from zoneinfo import ZoneInfo

from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    File,
    BackgroundTasks,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer
from pydantic import BaseModel
from sqlmodel import Session, select

import models
from database import create_db_and_tables, get_session, engine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Lifespan: inicializa tabelas via SQLModel (SEM Alembic)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: cria tabelas que ainda não existem. Não usa Alembic."""
    try:
        create_db_and_tables()
        logger.info("Banco de dados inicializado com sucesso (create_db_and_tables).")
    except Exception as exc:
        logger.error("Erro ao inicializar banco de dados: %s", exc)
    yield
    # Shutdown — nada a fazer


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Análise Operacional",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
_serializer = URLSafeTimedSerializer(SECRET_KEY)
PASSWORD_ITERATIONS = 120_000
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 dias


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    try:
        algo, iterations_str, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def _get_session_data(request: Request) -> Optional[dict]:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except Exception:
        return None


def require_login(request: Request) -> dict:
    data = _get_session_data(request)
    if not data:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return data


def require_leader(request: Request) -> dict:
    data = require_login(request)
    if data.get("role") not in ("admin", "leader"):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return data


def require_admin(request: Request) -> dict:
    data = require_login(request)
    if data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return data


def _fmt_datetime_br(dt: Optional[datetime]) -> str:
    if not dt:
        return "-"
    try:
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt)


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, message: Optional[str] = None):
    return templates.TemplateResponse("login.html", {"request": request, "message": message})


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    with Session(engine) as session:
        user = session.exec(
            select(models.User).where(models.User.username == username.strip().lower())
        ).first()
        if not user or not user.is_active or not _verify_password(password, user.password_hash or ""):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "message": "Usuário ou senha inválidos."},
                status_code=401,
            )
        employee = session.get(models.Employee, user.employee_id) if user.employee_id else None
        allowed_pages: List[str] = []
        try:
            allowed_pages = json.loads(user.allowed_pages or "[]")
        except Exception:
            pass
        token_data = {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "employee_id": user.employee_id,
            "employee_name": employee.name if employee else user.username,
            "allowed_pages": allowed_pages,
        }
        token = _serializer.dumps(token_data)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
        return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    data = _get_session_data(request)
    if not data:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/smart-flow", status_code=302)


# ---------------------------------------------------------------------------
# Incluir routers modulares
# ---------------------------------------------------------------------------

# BI Entregas
from bi_delivery_routes import router as bi_delivery_router
app.include_router(bi_delivery_router)

# BI Motorista
from bi_motorista_routes import router as bi_motorista_router
app.include_router(bi_motorista_router)

# Devoluções
from devolucoes_routes import init_devolucoes_router
app.include_router(
    init_devolucoes_router(
        templates=templates,
        require_login=require_login,
        logger=logger,
    )
)

# Documentos Institucionais
from documentos_routes import init_documentos_router
app.include_router(
    init_documentos_router(
        templates=templates,
        require_login=require_login,
    )
)

# Escala Operacional
from escalas_routes import init_escalas_router
app.include_router(init_escalas_router(templates=templates))

# Game Achievements
from game_achievements_routes import init_game_achievements_router
app.include_router(
    init_game_achievements_router(
        templates=templates,
        require_leader=require_leader,
        require_login=require_login,
        logger=logger,
    )
)

# Game Audit
from game_audit_routes import init_game_audit_router
app.include_router(
    init_game_audit_router(
        require_login=require_login,
        require_leader=require_leader,
    )
)

# Admin Geocoding
from routers.admin_geocoding import init_admin_geocoding_router
app.include_router(init_admin_geocoding_router(require_leader=require_leader))
