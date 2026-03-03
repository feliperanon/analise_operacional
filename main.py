# Force Reload for TZDATA and Models - v2
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional, List, Any
import json
import csv
import io
import base64
import hashlib
import secrets
import hmac
import smtplib
from datetime import datetime, timedelta, time, date
import calendar
from zoneinfo import ZoneInfo
import traceback
import os
from collections import Counter
import math
import statistics
from email.message import EmailMessage
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select, col, delete, text, or_, desc
from sqlalchemy import func, inspect, not_, and_
from typing import List
from database import create_db_and_tables, get_session, engine
import models
from client_import_utils import normalize_address, normalize_phone_br, normalize_key, find_col_map as find_client_col_map
import logging
import pydantic
from logging.handlers import RotatingFileHandler
import unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)
# Performance: Use INFO level in production, DEBUG only when explicitly enabled
LOG_LEVEL = logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO

# Diagnostic
print(f"DEBUG: Loaded .env. SMTP_HOST='{os.getenv('SMTP_HOST')}'")


# Use RotatingFileHandler to prevent infinite log growth
handler = RotatingFileHandler(
    'logs.txt',
    maxBytes=5*1024*1024,  # 5 MB max per file
    backupCount=3,  # Keep 3 backup files
    encoding='utf-8'  # Fix Windows Unicode encoding issues
)
handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
))

# Console handler with UTF-8 encoding
console_handler = logging.StreamHandler()
console_handler.setLevel(LOG_LEVEL)
console_handler.setFormatter(logging.Formatter(
    '%(levelname)-8s | %(message)s'
))

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)
logger.addHandler(handler)
logger.addHandler(console_handler)

# --- Config ---
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", os.getenv("ADMIN_USER", "admin@local"))
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
ADMIN_ROLE = os.getenv("ADMIN_ROLE", "admin")
RESET_TOKEN_TTL_MINUTES = int(os.getenv("RESET_TOKEN_TTL_MINUTES", "30"))
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "").strip()

# --- AI Configuration (Google Gemini) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
gemini_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Google Gemini client initialized successfully")
    except ImportError:
        logger.warning("Google GenAI library not installed. AI reports will be unavailable.")
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")

# --- Debug logging (session c5b864) ---
def _dbg_log(msg: str, data: dict):
    try:
        import json as _json
        with open(BASE_DIR / "debug-c5b864.log", "a", encoding="utf-8") as f:
            f.write(_json.dumps({"sessionId": "c5b864", "message": msg, "data": data, "timestamp": datetime.now().isoformat()}, ensure_ascii=False) + "\n")
    except Exception:
        pass

# --- Helper Functions ---
def calculate_expected_work_days(
    work_days_json: str, 
    start_date: datetime, 
    end_date: datetime,
    vacation_start: Optional[datetime] = None,
    vacation_end: Optional[datetime] = None
) -> int:
    """
    Calcula quantos dias o colaborador deveria trabalhar baseado na escala,
    descontando dias de fÃƒÆ’Ã‚Â©rias se houver sobreposiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o.
    
    Args:
        work_days_json: JSON string com dias da semana
        start_date: Data inicial do perÃƒÆ’Ã‚Â­odo
        end_date: Data final do perÃƒÆ’Ã‚Â­odo (exclusiva, geralmente)
        vacation_start: InÃƒÆ’Ã‚Â­cio das fÃƒÆ’Ã‚Â©rias
        vacation_end: Fim das fÃƒÆ’Ã‚Â©rias
    
    Returns:
        NÃƒÆ’Ã‚Âºmero de dias esperados de trabalho
    """
    # Default fallback: Segunda a SÃƒÆ’Ã‚Â¡bado (6 dias)
    default_work_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    
    try:
        if work_days_json and work_days_json.strip():
            work_days = json.loads(work_days_json)
            if not work_days:  # Empty list
                work_days = default_work_days
        else:
            work_days = default_work_days
    except (json.JSONDecodeError, TypeError):
        work_days = default_work_days
    
    # Mapeamento de dias da semana (weekday() retorna 0=Monday, 6=Sunday)
    day_map = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
        "Sunday": 6
    }
    
    # Converter work_days para nÃƒÆ’Ã‚Âºmeros
    work_day_numbers = {day_map[day] for day in work_days if day in day_map}
    
    # Contar dias no perÃƒÆ’Ã‚Â­odo
    expected_days = 0
    current_date = start_date
    
    # Normalize vacation dates per day comparison (ignoring time)
    v_start_date = vacation_start.date() if vacation_start else None
    v_end_date = vacation_end.date() if vacation_end else None
    
    while current_date < end_date:
        # Check Vacation
        is_vacation = False
        if v_start_date and v_end_date:
            curr_d = current_date.date()
            if v_start_date <= curr_d <= v_end_date:
                is_vacation = True
        
        # SÃƒÆ’Ã‚Â³ conta se for dia de trabalho E nÃƒÆ’Ã‚Â£o estiver de fÃƒÆ’Ã‚Â©rias
        if not is_vacation and current_date.weekday() in work_day_numbers:
            expected_days += 1
        current_date += timedelta(days=1)
    
    return expected_days


# --- Shift Date Helpers ---
def _get_reference_datetime(reference: Optional[datetime] = None) -> datetime:
    tz = ZoneInfo("America/Sao_Paulo")
    if reference:
        return reference.astimezone(tz)
    return datetime.now(tz)


def get_effective_shift_date(shift: str, reference: Optional[datetime] = None) -> date:
    ref = _get_reference_datetime(reference)
    if (shift or "").strip().lower() == "noite":
        if ref.hour >= 18:
            return ref.date()
        if ref.hour < 6:
            return (ref - timedelta(days=1)).date()
    return ref.date()


def normalize_shift_date(date_str: Optional[str], shift: str, reference: Optional[datetime] = None) -> Optional[str]:
    if not date_str:
        return date_str
    if (shift or "").strip().lower() != "noite":
        return date_str

    ref = _get_reference_datetime(reference)
    if not (0 <= ref.hour < 6):
        return date_str

    try:
        provided = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return date_str

    if provided == ref.date():
        return (ref - timedelta(days=1)).date().strftime("%Y-%m-%d")

    return date_str


def normalize_shift(value: Optional[str]) -> str:
    """Normalize shift labels (ex.: Manha/ManhÃƒÆ’Ã‚Â£ -> manha)."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFD", str(value))
    cleaned = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return cleaned.lower().strip()


def shift_display_label(normalized: str) -> str:
    """Retorna rÃƒÆ’Ã‚Â³tulo em portuguÃƒÆ’Ã‚Âªs para exibiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o (evita duplicatas e encoding)."""
    if not normalized:
        return "Outro"
    n = normalized.strip().lower()
    if n.startswith("manha"):
        return "ManhÃƒÆ’Ã‚Â£"
    if n.startswith("tard"):
        return "Tarde"
    if n.startswith("noit"):
        return "Noite"
    return normalized.strip().title() if normalized else "Outro"


# API Models
from pydantic import BaseModel
from typing import Optional, List

class ManualXPRequest(BaseModel):
    employee_id: int
    amount: int
    reason: str
    status: Optional[str] = "confirmed"  # confirmed | provisional

class DailyRoutineUpdate(BaseModel):
    date: str
    shift: str
    attendance_log: Optional[dict] = {}
    tonnage: Optional[int] = None
    arrival_time: Optional[str] = None
    exit_time: Optional[str] = None
    report: Optional[str] = None
    rating: Optional[int] = 0
    status: Optional[str] = None
    sector_config: Optional[dict] = None
    logs: Optional[list] = None
class VacationSchedule(BaseModel):
    registration_id: str
    start_date: str
    end_date: str
def update_vacation_statuses(session: Session, target_date: datetime):
    """
    Updates employee status based on vacation schedule vs target date.
    Also:
    - Clears vacation dates that have already passed
    - Creates vacation routines for employees on vacation
    """
    check_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    check_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999)
    today_str = target_date.strftime("%Y-%m-%d")
    
    employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
    
    for emp in employees:
        if emp.vacation_start and emp.vacation_end:
            # Basic validation of dates
            v_start = emp.vacation_start
            v_end = emp.vacation_end
            
            # Normalize for comparison
            v_s = v_start.replace(hour=0, minute=0, second=0, microsecond=0)
            v_e = v_end.replace(hour=23, minute=59, second=59, microsecond=999)
            
            # Check if vacation already ended (past vacation)
            if v_e < check_start:
                # Vacation ended - clear the dates and set to active
                print(f"ÃƒÂ°Ã…Â¸Ã‚ÂÃ¢â‚¬â€œÃƒÂ¯Ã‚Â¸Ã‚Â FÃƒÆ’Ã‚Â©rias encerradas para {emp.name} - limpando dados de fÃƒÆ’Ã‚Â©rias")
                emp.vacation_start = None
                emp.vacation_end = None
                if emp.status == 'vacation':
                    emp.status = 'active'
                session.add(emp)
                continue
            
            # Check if currently on vacation
            should_be_vacation = v_s <= check_start <= v_e
            
            if should_be_vacation:
                if emp.status != 'vacation':
                    emp.status = 'vacation'
                    session.add(emp)
                
                # Create vacation routine for today if doesn't exist
                # Check for each shift
                for shift in ["ManhÃƒÆ’Ã‚Â£", "Tarde", "Noite"]:
                    # Only create for the employee's actual shift
                    if emp.work_shift and emp.work_shift.lower() != shift.lower():
                        continue
                        
                    existing_routine = session.exec(
                        select(models.EmployeeRoutine)
                        .where(models.EmployeeRoutine.employee_id == emp.id)
                        .where(models.EmployeeRoutine.date == today_str)
                        .where(models.EmployeeRoutine.shift == shift)
                    ).first()
                    
                    if not existing_routine:
                        new_routine = models.EmployeeRoutine(
                            date=today_str,
                            shift=shift,
                            employee_id=emp.id,
                            routine="vacation"
                        )
                        session.add(new_routine)
                        print(f"ÃƒÂ°Ã…Â¸Ã‚ÂÃ¢â‚¬â€œÃƒÂ¯Ã‚Â¸Ã‚Â Criada rotina de fÃƒÆ’Ã‚Â©rias para {emp.name} - {today_str} ({shift})")
                    elif existing_routine.routine != "vacation":
                        # Update existing routine to vacation
                        existing_routine.routine = "vacation"
                        session.add(existing_routine)
            else:
                # Not yet on vacation or vacation hasn't started
                # If currently marked as vacation but NOT in vacation period anymore (or yet)
                # revert to active.
                if emp.status == 'vacation':
                    emp.status = 'active'
                    session.add(emp)
    
    session.commit()
def sync_sectors_on_startup():
    """Sincroniza automaticamente Sector -> SectorConfiguration ao iniciar"""
    try:
        print("ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ¢â‚¬Å¾ Sincronizando setores com configuraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o...")
        with Session(engine) as session:
            sectors = session.exec(select(models.Sector)).all()
            shifts = {}
            for s in sectors:
                if s.shift not in shifts:
                    shifts[s.shift] = []
                shifts[s.shift].append(s)
                
            for shift, sector_list in shifts.items():
                config_db = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == shift)).first()
                if not config_db:
                    continue
                
                data = config_db.config_json
                if isinstance(data, str):
                    import json
                    data = json.loads(data)
                
                if not data:
                    continue
                
                config_sectors = data.get('sectors', [])
                changed = False
                
                for s in sector_list:
                    for cs in config_sectors:
                        if cs.get('label') == s.name and cs.get('target') != s.max_employees:
                            print(f"   ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ Auto-Corrigindo {s.name} ({shift}): {cs.get('target')} -> {s.max_employees}")
                            cs['target'] = s.max_employees
                            changed = True
                
                if changed:
                    config_db.config_json = data
                    config_db.updated_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
                    session.add(config_db)
            
            session.commit()
        print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ SincronizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de startup concluÃƒÆ’Ã‚Â­da.")
    except Exception as e:
        print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro no sync de startup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    try:
        ensure_vehicle_schema()
        ensure_checklist_odometer_schema()
        ensure_client_schema()
        ensure_route_schema()
        # Employee schema compatibility must run before auth/bootstrap queries
        ensure_column(engine, "employee", "mobile_access_admin_start", "BOOLEAN DEFAULT FALSE")
        ensure_column(engine, "employee", "seller_code", "VARCHAR(64)")
    except Exception as e:
        logger.error(f"Erro ao migrar vehicle/checklist/client/route: {e}")
    try:
        ensure_user_auth_schema()
        ensure_employee_access_schema()
        ensure_employee_replaced_by_schema()
        ensure_event_reference_schema()
        ensure_checklist_email_schema()
        ensure_checklist_edit_schema()
        ensure_pallet_count_schema()
        ensure_substitution_history_schema()
        migrate_existing_substitutions()
        with Session(engine) as session:
            ensure_default_admin(session)
    except Exception as e:
        logger.error(f"Erro ao preparar auth: {e}")
    try:
        from devolucoes_routes import ensure_devolucao_seed, ensure_vendedores_especiais
        with Session(engine) as session:
            ensure_devolucao_seed(session)
            ensure_vendedores_especiais(session)
    except Exception as e:
        logger.error(f"Erro ao seed devoluÃ§Ãµes: {e}")
    try:
        logger.info(f"DATABASE URL DETECTADA: {engine.url}")
        sync_sectors_on_startup()
    except Exception as e:
        logger.error(f"Erro ao iniciar sync: {e}")
    yield

app = FastAPI(title="AnÃƒÆ’Ã‚Â¡lise Operacional", version="2.0.0", lifespan=lifespan)

# Determine if running in Production (Render sets RENDER=true)
IS_PROD = os.environ.get("RENDER", "false").lower() == "true"

# Add Session Middleware with Production Settings
app.add_middleware(
    SessionMiddleware, 
    secret_key=SECRET_KEY,
    https_only=IS_PROD, # True only in production to work on localhost too
    same_site="lax",    # Best for normal top-level navigation
    max_age=86400 * 30  # 30 Days persistence
)

# --- Middleware: Anti-Cache (Force Fresh Data) ---
@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    # Apply to API and Smart Flow HTML pages to prevent "stale" state
    if (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/smart-flow")
        or request.url.path.startswith("/lider")
        or request.url.path.startswith("/routine/report")
        or request.url.path.startswith("/mobile")
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    content_type = response.headers.get("content-type")
    media_type = (content_type or response.media_type or "").lower()
    if ("text/html" in media_type or "application/json" in media_type) and "charset=" not in media_type:
        if content_type:
            response.headers["Content-Type"] = f"{content_type}; charset=utf-8"
        elif response.media_type:
            response.headers["Content-Type"] = f"{response.media_type}; charset=utf-8"
    return response

# --- Global Exception Handler ---
@app.middleware("http")
async def global_exception_handler(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        # If it is a Starlette/FastAPI HTTPException, let it propagate (handles redirects/404s)
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from fastapi import HTTPException as FastAPIHTTPException
        if isinstance(e, (StarletteHTTPException, FastAPIHTTPException)):
            raise e
            
        import traceback
        import uuid
        
        trace_id = str(uuid.uuid4())[:8]
        error_msg = str(e)
        stack_trace = traceback.format_exc()
        
        # Log Full Trace (Removed emoji to prevent UnicodeEncodeError on Windows)
        logger.error(f"[500] {request.method} {request.url} | Trace: {trace_id} | Error: {error_msg}\n{stack_trace}")
        
        # Determine Response Type
        accept = request.headers.get("accept", "")
        
        if "application/json" in accept or request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Erro Interno do Servidor",
                    "detail": error_msg if LOG_LEVEL == logging.DEBUG else "Contate o suporte.",
                    "trace_id": trace_id
                }
            )
        
        return templates.TemplateResponse("error_500.html", {
            "request": request, 
            "error_detail": error_msg if LOG_LEVEL == logging.DEBUG else None,
            "trace_id": trace_id
        }, status_code=500)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Helper function to get user display name
def get_user_display_name(request: Request, session: Session = None) -> tuple[str, str]:
    """
    Returns (display_name, initials) for the current user.
    If session is provided, tries to get Employee name from linked User.
    Otherwise, uses email as fallback.
    """
    user = get_current_user(request)
    if not user:
        return ("UsuÃƒÆ’Ã‚Â¡rio", "US")
    
    if isinstance(user, dict) and user.get("type") == "user":
        user_id = user.get("id")
        if user_id and session:
            try:
                db_user = session.get(models.User, user_id)
                if db_user and db_user.employee_id:
                    employee = session.get(models.Employee, db_user.employee_id)
                    if employee:
                        name = employee.name
                        initials = "".join([n[0].upper() for n in name.split()[:2]]) if name else "US"
                        return (name, initials[:2])
            except Exception:
                pass
        
        # Fallback to email
        email = user.get("email", "")
        if email:
            name = email.split("@")[0].replace(".", " ").title()
            initials = "".join([n[0].upper() for n in name.split()[:2]]) if name else "US"
            return (name, initials[:2])
    
    return ("UsuÃƒÆ’Ã‚Â¡rio", "US")

def format_user_label(user) -> str:
    """Converte o usuÃƒÆ’Ã‚Â¡rio logado em um rÃƒÆ’Ã‚Â³tulo legÃƒÆ’Ã‚Â­vel para eventos e logs."""
    try:
        if isinstance(user, dict):
            email = user.get("email")
            if email:
                return email
            name = user.get("name")
            if name:
                return name
            user_id = user.get("id")
            if user_id:
                return str(user_id)
            role = user.get("role")
            if role:
                return role
            return "usuÃƒÆ’Ã‚Â¡rio"

        email = getattr(user, "email", None)
        if email:
            return email
        username = getattr(user, "username", None)
        if username:
            return username
        full_name = getattr(user, "name", None)
        if full_name:
            return full_name
        return str(user)
    except Exception:
        return "usuÃƒÆ’Ã‚Â¡rio"

# --- Custom Filters ---
def fmt_br(val):
    if val is None: return "0,0"
    try:
        return f"{float(val):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(val)

def fmt_br_int(val):
    if val is None: return "0"
    try:
        return f"{int(val):,.0f}".replace(",", ".")
    except:
        return str(val)

def fmt_br_pct(val):
    if val is None:
        return "0%"
    try:
        num = float(val)
        if num <= 1:
            num *= 100
        return f"{num:,.0f}%".replace(",", ".")
    except:
        return f"{val}%"

def fmt_br_2(val):
    if val is None:
        return "0,00"
    try:
        return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)

templates.env.filters["fmt_br"] = fmt_br
templates.env.filters["fmt_br_int"] = fmt_br_int
templates.env.filters["fmt_br_pct"] = fmt_br_pct
templates.env.filters["fmt_br_2"] = fmt_br_2

# --- Auth Helpers (Local + Google) ---
PASSWORD_ITERATIONS = 120_000

def normalize_email(value: str) -> str:
    return (value or "").strip().lower()

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii")
    )

def verify_password(password: str, stored_hash: str) -> bool:
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

def hash_reset_token(token: str) -> str:
    digest = hashlib.sha256()
    digest.update(token.encode("utf-8"))
    digest.update(SECRET_KEY.encode("utf-8"))
    return digest.hexdigest()

def is_google_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

PAGE_OPTIONS = [
    {"key": "admin_game", "label": "Game Master", "path": "/admin/game", "prefixes": ["/admin/game", "/api/game"]},
    {"key": "smart_flow", "label": "Smart Flow", "path": "/smart-flow", "prefixes": ["/smart-flow", "/api/smart-flow", "/smart-flow/load", "/api/employees", "/settings", "/employees", "/lider", "/api/lider"]},
    {"key": "checklist_admin", "label": "Checklists Operacionais", "path": "/admin/routine/checklists", "prefixes": ["/admin/routine/checklists", "/api/routine/checklists"]},
    {"key": "ops_performance", "label": "Avaliacao Operacional", "path": "/operations/performance", "prefixes": ["/operations/performance", "/operations/performance/analysis", "/rankings", "/api/rankings"]}
]
PAGE_KEYS = {p["key"] for p in PAGE_OPTIONS}

def parse_allowed_pages(raw_value: Optional[str]) -> List[str]:
    if not raw_value:
        return []
    try:
        data = json.loads(raw_value)
        if isinstance(data, list):
            return [str(x) for x in data if str(x) in PAGE_KEYS]
    except Exception:
        return []
    return []

def serialize_allowed_pages(keys: List[str]) -> str:
    clean = [k for k in keys if k in PAGE_KEYS]
    return json.dumps(clean)

def allowed_prefixes_for(keys: List[str]) -> List[str]:
    prefixes = []
    for opt in PAGE_OPTIONS:
        if opt["key"] in keys:
            prefixes.extend(opt["prefixes"])
    return prefixes

# --- Checklist Operacional (Transpaleteira) ---
CHECKLIST_ITEMS = [
    {"key": "limpeza", "label": "Limpeza", "critical": False},
    {"key": "avarias_portas", "label": "Avarias Portas", "critical": False},
    {"key": "vidro_frontal_retrovisor", "label": "Vidro Frontal / Retrovisor", "critical": True},
    {"key": "banco_forro", "label": "Banco e Forro", "critical": False},
    {"key": "cinto_seguranca", "label": "Cinto de Seguranca", "critical": True},
    {"key": "extintor_incendio", "label": "Extintor de Incendio", "critical": True},
    {"key": "triangulo", "label": "Triangulo", "critical": True},
    {"key": "limpador_parabrisa", "label": "Limpador Parabrisa", "critical": True},
    {"key": "chave_basculhar", "label": "Chave Basculhar", "critical": False},
    {"key": "placa_legivel", "label": "Placa Legivel", "critical": True},
    {"key": "macaco", "label": "Macaco", "critical": False},
    {"key": "chave_roda", "label": "Chave de Roda", "critical": False},
    {"key": "estepe", "label": "Estepe", "critical": True},
    {"key": "parte_eletrica", "label": "Parte Eletrica", "critical": True},
    {"key": "parte_mecanica", "label": "Parte Mecanica", "critical": True},
    {"key": "freios", "label": "Freios", "critical": True},
    {"key": "nivel_oleo_agua", "label": "Nivel Oleo e Agua", "critical": True},
    {"key": "avarias_para_choques", "label": "Avarias Para Choques", "critical": False},
    {"key": "avarias_bau", "label": "Avarias Bau", "critical": False}
]
CHECKLIST_ITEM_KEYS = [item["key"] for item in CHECKLIST_ITEMS]
CHECKLIST_CRITICAL_KEYS = {item["key"] for item in CHECKLIST_ITEMS if item["critical"]}

def checklist_item_label_map() -> dict:
    return {item["key"]: item["label"] for item in CHECKLIST_ITEMS}

def parse_items_payload(raw_items: Any) -> dict:
    """Normaliza payload do checklist para {item_key: bool}."""
    if raw_items is None:
        return {}

    data = raw_items
    if isinstance(raw_items, str):
        try:
            data = json.loads(raw_items)
        except Exception:
            return {}

    if isinstance(data, list):
        normalized = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            if not key:
                continue
            value = entry.get("value")
            normalized[key] = bool(value)
        return normalized

    if not isinstance(data, dict):
        return {}

    normalized = {}
    for key, value in data.items():
        key_str = str(key).strip()
        if not key_str:
            continue
        if isinstance(value, str):
            normalized[key_str] = value.strip().lower() in ("1", "true", "yes", "ok", "sim")
        else:
            normalized[key_str] = bool(value)
    return normalized

CHECKLIST_XP = int(os.getenv("CHECKLIST_XP", "10"))
CHECKLIST_IMAGE_DIR = os.path.join(str(BASE_DIR), "static", "uploads", "checklists")
CHECKLIST_MAX_IMAGE_SIZE = 15 * 1024 * 1024
TICKET_IMAGE_DIR = os.path.join(str(BASE_DIR), "static", "uploads", "tickets")
TICKET_MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAINTENANCE_EMAIL_TO = os.getenv("MAINTENANCE_EMAIL_TO", "").strip()
MAINTENANCE_EMAIL_FROM = os.getenv("MAINTENANCE_EMAIL_FROM", "").strip()
DEFAULT_SENDER_EMAIL = "feliperanon@live.com"
MAINTENANCE_EMAIL_FROM_FIXED = (
    MAINTENANCE_EMAIL_FROM
    or DEFAULT_SENDER_EMAIL
)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT_RAW = os.getenv("SMTP_PORT", "587").strip()
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_TLS_RAW = os.getenv("SMTP_TLS", "true").strip()
SMTP_USE_SSL_RAW = os.getenv("SMTP_USE_SSL", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
ALERT_SETTINGS_PATH = "/admin/alerts/settings"

def parse_bool_env(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")

def parse_int_env(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default

def parse_email_list(value: str) -> List[str]:
    if not value:
        return []
    parts = [p.strip() for p in value.replace(";", ",").split(",")]
    return [normalize_email(p) for p in parts if normalize_email(p)]

def get_maintenance_recipient_emails(session: Session) -> List[str]:
    """Destinatarios de manutencao: cadastro de checklist + cadastro setorial geral."""
    emails = set(parse_email_list(MAINTENANCE_EMAIL_TO))

    checklist_recipients = session.exec(
        select(models.ChecklistEmailRecipient)
        .where(models.ChecklistEmailRecipient.is_active == True)
    ).all()
    for rec in checklist_recipients:
        email = normalize_email(getattr(rec, "email", ""))
        if email:
            emails.add(email)

    maintenance_recipients = session.exec(
        select(models.AbsenceAlertRecipient)
        .where(models.AbsenceAlertRecipient.is_active == True)
        .where(models.AbsenceAlertRecipient.alert_type == "maintenance")
    ).all()
    for rec in maintenance_recipients:
        email = normalize_email(getattr(rec, "email", ""))
        if email:
            emails.add(email)

    return sorted(emails)

def smtp_config_error(recipient_list: List[str]) -> Optional[str]:
    missing = []
    host_val = (SMTP_HOST or "").strip()
    if not recipient_list:
        missing.append("MAINTENANCE_EMAIL_TO")
    if not host_val or host_val.upper() == "SEU_HOST_AQUI" or len(host_val) == 0:
        # Verificar se realmente estÃƒÆ’Ã‚Â¡ vazio (nÃƒÆ’Ã‚Â£o apenas espaÃƒÆ’Ã‚Â§os)
        if not host_val:
            missing.append("SMTP_HOST")
        else:
            missing.append(f"SMTP_HOST (valor='{host_val}')")
    port_raw = (SMTP_PORT_RAW or "").strip()
    if not port_raw:
        missing.append("SMTP_PORT")
    else:
        try:
            int(port_raw)
        except Exception:
            missing.append("SMTP_PORT")
    if not (SMTP_TLS_RAW or "").strip():
        missing.append("SMTP_TLS")
    user_val = (SMTP_USER or "").strip()
    if not user_val or len(user_val) == 0:
        missing.append("SMTP_USER")
    pass_val = (SMTP_PASS or "").strip()
    if not pass_val or len(pass_val) == 0:
        missing.append("SMTP_PASS")
    from_val = (MAINTENANCE_EMAIL_FROM_FIXED or "").strip()
    if not from_val:
        missing.append("MAINTENANCE_EMAIL_FROM")
    if "brevo" in host_val.lower() and from_val.lower().endswith("@smtp-brevo.com"):
        missing.append("MAINTENANCE_EMAIL_FROM (use remetente validado no Brevo)")
    if missing:
        return "ConfiguraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de e-mail incompleta. VariÃƒÆ’Ã‚Â¡veis faltando/invalidas: " + ", ".join(missing)
    return None

def checklist_nonconforming_items(keys: Optional[List[str]]) -> List[dict]:
    label_map = checklist_item_label_map()
    items = []
    for key in (keys or []):
        items.append({
            "key": key,
            "label": label_map.get(key, key),
            "critical": key in CHECKLIST_CRITICAL_KEYS
        })
    return items

def build_checklist_pdf(report: dict) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception as exc:
        raise RuntimeError("ReportLab nÃƒÆ’Ã‚Â£o disponÃƒÆ’Ã‚Â­vel para gerar PDF.") from exc

    buffer = io.BytesIO()
    page_width, page_height = A4
    c = canvas.Canvas(buffer, pagesize=A4)
    y = page_height - 40
    line_height = 14

    def draw_line(text: str, bold: bool = False):
        nonlocal y
        if y < 40:
            c.showPage()
            y = page_height - 40
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawString(40, y, text)
        y -= line_height

    draw_line("Checklist Operacional - NÃƒÆ’Ã‚Â£o Conforme", True)
    draw_line(f"Checklist ID: {report['checklist_id']}")
    draw_line(f"Operador: {report['operator_name']} ({report['operator_id']})")
    draw_line(f"Data/Hora: {report['submitted_at']} | Turno: {report['shift']}")
    draw_line(f"Equipamento: {report['equipment_code']}")
    draw_line("")
    draw_line("Itens nÃƒÆ’Ã‚Â£o conformes:", True)
    for item in report["nonconforming_items"]:
        critical_tag = " [CRITICO]" if item["critical"] else ""
        draw_line(f"- {item['label']}{critical_tag}")
    draw_line("")
    draw_line("ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes:", True)
    for line in (report["observations"] or "-").splitlines():
        draw_line(line)
    if report["image_list"]:
        draw_line("")
        draw_line("Imagens:", True)
        for img in report["image_list"]:
            draw_line(f"- {img}")
    draw_line("")
    draw_line(f"Link: {report['checklist_link']}")
    draw_line("")
    draw_line(f"Gerado em: {report['generated_at']}")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def build_ticket_pdf(report: dict) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception as exc:
        raise RuntimeError("ReportLab nÃƒÆ’Ã‚Â£o disponÃƒÆ’Ã‚Â­vel para gerar PDF.") from exc

    buffer = io.BytesIO()
    page_width, page_height = A4
    c = canvas.Canvas(buffer, pagesize=A4)
    y = page_height - 40
    line_height = 14

    def draw_line(text: str, bold: bool = False):
        nonlocal y
        if y < 40:
            c.showPage()
            y = page_height - 40
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawString(40, y, text)
        y -= line_height

    draw_line("Chamado de ManutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o - Novo Registro", True)
    draw_line(f"Ticket ID: {report['ticket_id']}")
    draw_line(f"Solicitante: {report['employee_name']} ({report['employee_id']})")
    draw_line(f"Data/Hora: {report['created_at']} | Turno: {report['shift']}")
    draw_line(f"Equipamento: {report['equipment_code']}")
    draw_line(f"Severidade: {report['severity'].upper()}")
    draw_line("")
    draw_line("DescriÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o do Problema:", True)
    for line in (report["description"] or "-").splitlines():
        draw_line(line)
    if report["image_list"]:
        draw_line("")
        draw_line("Imagens Anexadas:", True)
        for img in report["image_list"]:
            draw_line(f"- {img}")
    draw_line("")
    draw_line(f"Link: {report['ticket_link']}")
    draw_line("")
    draw_line(f"Gerado em: {report['generated_at']}")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def send_maintenance_email(report: dict, recipients: Optional[List[str]] = None) -> tuple:
    smtp_port = parse_int_env(SMTP_PORT_RAW, 587)
    smtp_tls = parse_bool_env(SMTP_TLS_RAW, True)
    recipient_list = [normalize_email(r) for r in (recipients or []) if normalize_email(r)]
    if not recipient_list:
        recipient_list = parse_email_list(MAINTENANCE_EMAIL_TO)

    config_error = smtp_config_error(recipient_list)
    if config_error:
        logger.error(config_error)
        return False, config_error

    if SMTP_USE_SSL_RAW.strip():
        smtp_use_ssl = parse_bool_env(SMTP_USE_SSL_RAW, False)
    else:
        smtp_use_ssl = smtp_port == 465

    def _fix_mojibake(value) -> str:
        text_value = str(value or '').strip()
        if not text_value:
            return ''
        candidate = text_value
        for _ in range(2):
            if not any(token in candidate for token in ("ÃƒÆ’Ã†â€™", "ÃƒÆ’Ã¢â‚¬Å¡", "ÃƒÆ’Ã‚Â¢")):
                break
            try:
                candidate = candidate.encode('latin1').decode('utf-8')
            except Exception:
                break
        return candidate

    def _safe_text(value, default='-') -> str:
        fixed = _fix_mojibake(value)
        return fixed if fixed else default

    def _format_actor_label(value) -> str:
        if isinstance(value, dict):
            candidate = (
                value.get('email')
                or value.get('username')
                or value.get('name')
                or value.get('id')
            )
            return _safe_text(candidate, 'Sistema')
        return _safe_text(value, 'Sistema')

    msg = EmailMessage()
    msg['Subject'] = _safe_text(report.get('subject'), 'NOTIFICAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE MANUTENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O')
    msg['From'] = MAINTENANCE_EMAIL_FROM_FIXED
    msg['To'] = ', '.join(recipient_list)

    submitted_at = _safe_text(
        report.get('submitted_at'),
        datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y ÃƒÆ’Ã‚Â s %H:%M'),
    )
    equipment_code = _safe_text(report.get('equipment_code'))
    operator_name = _safe_text(report.get('operator_name') or report.get('employee_name'))
    operator_id = _safe_text(report.get('operator_id'))
    shift = _safe_text(report.get('shift'))
    observations = _safe_text(report.get('observations'))
    registered_by = _format_actor_label(report.get('registered_by') or report.get('operator_name'))
    action_text = _safe_text(
        report.get('action'),
        'Solicitamos avaliaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o da equipe responsÃƒÆ’Ã‚Â¡vel e tratativa conforme procedimento interno.',
    )

    nonconforming_items = report.get('nonconforming_items') or []
    items_html = ''
    items_text = []
    if nonconforming_items:
        for item in nonconforming_items:
            label = _safe_text(item.get('label') or item.get('key'))
            critical = ' (CRITICO)' if item.get('critical') else ''
            items_html += f'<li>{label}{critical}</li>'
            items_text.append(f'- {label}{critical}')
    else:
        items_html = '<li>Sem itens nÃƒÆ’Ã‚Â£o conformes informados</li>'
        items_text = ['- Sem itens nÃƒÆ’Ã‚Â£o conformes informados']

    now_str = datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y ÃƒÆ’Ã‚Â s %H:%M')

    body_text = f"""
NOTIFICAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE MANUTENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O
SolicitaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o registrada no sistema

Prezados,

Informamos que foi registrado um bloqueio/manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o com os dados abaixo:

- Equipamento: {equipment_code}
- Operador: {operator_name}
- MatrÃƒÆ’Ã‚Â­cula: {operator_id}
- Turno: {shift}
- Data/Hora: {submitted_at}
- Registrado por: {registered_by}

Itens nÃƒÆ’Ã‚Â£o conformes:
{chr(10).join(items_text)}

ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {observations}

{action_text}

---
Este ÃƒÆ’Ã‚Â© um e-mail automÃƒÆ’Ã‚Â¡tico gerado pelo sistema de AnÃƒÆ’Ã‚Â¡lise Operacional.
Data/Hora do registro: {now_str}
    """

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #0f766e; color: white; padding: 15px 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0; font-size: 18px;">NOTIFICAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE MANUTENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O</h2>
                <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">SolicitaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o registrada no sistema</p>
            </div>
            <div style="background: #f9fafb; padding: 20px; border: 1px solid #e5e7eb; border-top: none;">
                <p>Prezados,</p>
                <p>Informamos que foi registrado um bloqueio/manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o com os dados abaixo:</p>
                <div style="background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 15px; margin: 20px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Equipamento:</strong></td><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{equipment_code}</td></tr>
                        <tr><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Operador:</strong></td><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{operator_name}</td></tr>
                        <tr><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>MatrÃƒÆ’Ã‚Â­cula:</strong></td><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{operator_id}</td></tr>
                        <tr><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Turno:</strong></td><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{shift}</td></tr>
                        <tr><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Data/Hora:</strong></td><td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{submitted_at}</td></tr>
                        <tr><td style="padding: 8px 0;"><strong>Registrado por:</strong></td><td style="padding: 8px 0;">{registered_by}</td></tr>
                    </table>
                </div>
                <p><strong>Itens nÃƒÆ’Ã‚Â£o conformes:</strong></p>
                <ul>{items_html}</ul>
                <p><strong>ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes:</strong> {observations}</p>
                <p><strong>{action_text}</strong></p>
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                <p style="font-size: 12px; color: #6b7280;">
                    Este ÃƒÆ’Ã‚Â© um e-mail automÃƒÆ’Ã‚Â¡tico gerado pelo sistema de AnÃƒÆ’Ã‚Â¡lise Operacional.<br>
                    Data/Hora do registro: {now_str}
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype='html')

    if report.get('pdf_bytes'):
        msg.add_attachment(
            report['pdf_bytes'],
            maintype='application',
            subtype='pdf',
            filename=report.get('pdf_name') or 'relatorio_manutencao.pdf',
        )

    if report.get('image_bytes'):
        for idx, image_data in enumerate(report['image_bytes'], start=1):
            filename = image_data.get('name') or f'imagem_{idx}.jpg'
            content_type = image_data.get('content_type') or 'image/jpeg'
            maintype, subtype = content_type.split('/', 1)
            msg.add_attachment(
                image_data['bytes'],
                maintype=maintype,
                subtype=subtype,
                filename=filename,
            )

    try:
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(SMTP_HOST_FIXED, smtp_port, timeout=20) as server:
                if SMTP_USER_FIXED and SMTP_PASS_FIXED:
                    server.login(SMTP_USER_FIXED, SMTP_PASS_FIXED)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST_FIXED, smtp_port, timeout=20) as server:
                if smtp_tls:
                    server.starttls()
                if SMTP_USER_FIXED and SMTP_PASS_FIXED:
                    server.login(SMTP_USER_FIXED, SMTP_PASS_FIXED)
                server.send_message(msg)
        return True, None
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o')
        return False, str(exc)

async def save_checklist_images(files: List[UploadFile]) -> List[str]:
    ensure_checklist_dir()
    saved = []
    for file in files:
        if not file or not file.filename:
            continue
        try:
            contents = await file.read()
            if len(contents) > CHECKLIST_MAX_IMAGE_SIZE:
                logger.warning(f"Image too large: {len(contents)} > {CHECKLIST_MAX_IMAGE_SIZE}")
                raise HTTPException(status_code=400, detail="Imagem muito grande (max 15MB).")
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                raise HTTPException(status_code=400, detail="Formato de imagem invÃƒÆ’Ã‚Â¡lido.")
            
            filename = f"{secrets.token_hex(12)}{ext}"
            path = os.path.join(CHECKLIST_IMAGE_DIR, filename)
            
            logger.info(f"Saving image: {filename} to {path}")
            with open(path, "wb") as handle:
                handle.write(contents)
            saved.append(filename)
        except Exception as e:
            logger.error(f"Error saving image {file.filename}: {e}")
            raise
            
    return saved

TICKET_IMAGE_DIR = os.path.join(str(BASE_DIR), "static", "uploads", "tickets")
def ensure_ticket_dir():
    os.makedirs(TICKET_IMAGE_DIR, exist_ok=True)

async def save_ticket_images(files: List[UploadFile]) -> List[str]:
    ensure_ticket_dir()
    saved = []
    for file in files:
        if not file or not file.filename:
            continue
        try:
            contents = await file.read()
            if len(contents) > CHECKLIST_MAX_IMAGE_SIZE:
                raise HTTPException(status_code=400, detail="Imagem muito grande (max 15MB).")
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                raise HTTPException(status_code=400, detail="Formato de imagem invÃƒÆ’Ã‚Â¡lido.")
            
            filename = f"{secrets.token_hex(12)}{ext}"
            path = os.path.join(TICKET_IMAGE_DIR, filename)
            
            with open(path, "wb") as handle:
                handle.write(contents)
            saved.append(filename)
        except Exception as e:
            logger.error(f"Error saving ticket image {file.filename}: {e}")
            raise
            
    return saved

async def save_ticket_images(files: List[UploadFile]) -> List[str]:
    ensure_ticket_dir()
    saved = []
    for file in files:
        if not file or not file.filename:
            continue
        contents = await file.read()
        if len(contents) > TICKET_MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="Imagem muito grande (max 5MB).")
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            raise HTTPException(status_code=400, detail="Formato de imagem inv\xe1lido.")
        filename = f"{secrets.token_hex(12)}{ext}"
        path = os.path.join(TICKET_IMAGE_DIR, filename)
        with open(path, "wb") as handle:
            handle.write(contents)
        saved.append(filename)
    return saved

def resolve_equipment(session: Session, code: str) -> models.TranspalletEquipment:
    equipment = session.exec(
        select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == code)
    ).first()
    if not equipment:
        equipment = models.TranspalletEquipment(code=code, status="available")
        session.add(equipment)
        session.commit()
        session.refresh(equipment)
    return equipment

def block_equipment(session: Session, equipment: models.TranspalletEquipment, reason: str, checklist_id: Optional[int]):
    equipment.status = "blocked"
    equipment.blocked_reason = reason
    equipment.blocked_at = datetime.now()
    equipment.last_checklist_id = checklist_id
    session.add(equipment)

def release_equipment(session: Session, equipment: models.TranspalletEquipment, released_by: str):
    equipment.status = "available"
    equipment.released_by = released_by
    equipment.released_at = datetime.now()
    session.add(equipment)

def ensure_user_auth_schema():
    inspector = inspect(engine)
    if "user" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("user")}
    missing = {
        "role": "VARCHAR(32)",
        "is_active": "BOOLEAN",
        "employee_id": "INTEGER",
        "allowed_pages": "TEXT",
        "google_sub": "VARCHAR(255)",
        "reset_token_hash": "VARCHAR(255)",
        "reset_token_expires_at": "TIMESTAMP",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP"
    }
    table_name = "\"user\""
    added_is_active = False
    added_role = False
    added_allowed_pages = False
    with engine.begin() as conn:
        for col_name, col_type in missing.items():
            if col_name in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
            if col_name == "is_active":
                added_is_active = True
            if col_name == "role":
                added_role = True
            if col_name == "allowed_pages":
                added_allowed_pages = True
        if "is_active" in existing or added_is_active:
            conn.execute(text(f"UPDATE {table_name} SET is_active = TRUE WHERE is_active IS NULL"))
        if "role" in existing or added_role:
            conn.execute(text(f"UPDATE {table_name} SET role = 'admin' WHERE role IS NULL"))
    if "allowed_pages" in existing or added_allowed_pages:
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE {table_name} SET allowed_pages = '[]' WHERE allowed_pages IS NULL"))

def ensure_employee_access_schema():
    inspector = inspect(engine)
    if "employee" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("employee")}
    missing = {
        "mobile_access_separation": "BOOLEAN",
        "mobile_access_checklist": "BOOLEAN"
    }
    added_separation = False
    added_checklist = False
    with engine.begin() as conn:
        for col_name, col_type in missing.items():
            if col_name in existing:
                continue
            conn.execute(text(f"ALTER TABLE employee ADD COLUMN {col_name} {col_type}"))
            if col_name == "mobile_access_separation":
                added_separation = True
            if col_name == "mobile_access_checklist":
                added_checklist = True
        if "mobile_access_separation" in existing or added_separation:
            conn.execute(text("UPDATE employee SET mobile_access_separation = mobile_access WHERE mobile_access_separation IS NULL"))
        if "mobile_access_checklist" in existing or added_checklist:
            conn.execute(text("UPDATE employee SET mobile_access_checklist = FALSE WHERE mobile_access_checklist IS NULL"))


def ensure_employee_replaced_by_schema():
    """Adiciona coluna replaced_by se nÃƒÆ’Ã‚Â£o existir (compatibilidade com DB antigos)."""
    inspector = inspect(engine)
    if "employee" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("employee")}
    if "replaced_by" in existing:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE employee ADD COLUMN replaced_by INTEGER"))
            try:
                conn.execute(text(
                    "ALTER TABLE employee ADD CONSTRAINT fk_employee_replaced_by "
                    "FOREIGN KEY (replaced_by) REFERENCES employee(id)"
                ))
            except Exception:
                pass  # FK pode jÃƒÆ’Ã‚Â¡ existir ou falhar em alguns DBs
    except Exception as e:
        logger.warning(f"Coluna replaced_by: {e}")

def ensure_event_reference_schema():
    inspector = inspect(engine)
    if "event" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("event")}
    missing = {
        "reference_type": "VARCHAR(64)",
        "reference_id": "INTEGER"
    }
    with engine.begin() as conn:
        for col_name, col_type in missing.items():
            if col_name in existing:
                continue
            conn.execute(text(f"ALTER TABLE event ADD COLUMN {col_name} {col_type}"))

def ensure_checklist_email_schema():
    inspector = inspect(engine)
    table_name = getattr(models.TranspalletChecklist, "__tablename__", "transpalletchecklist")
    if table_name not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    missing = {
        "maintenance_email_sent_at": "TIMESTAMP",
        "maintenance_email_error": "TEXT"
    }
    with engine.begin() as conn:
        for col_name, col_type in missing.items():
            if col_name in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))

def ensure_checklist_edit_schema():
    inspector = inspect(engine)
    table_name = getattr(models.TranspalletChecklist, "__tablename__", "transpalletchecklist")
    if table_name not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    missing = {
        "edited_at": "TIMESTAMP",
        "edited_by": "TEXT",
        "edit_comment": "TEXT",
        "previous_observations": "TEXT",
        "previous_equipment_code": "TEXT"
    }
    with engine.begin() as conn:
        for col_name, col_type in missing.items():
            if col_name in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))

def ensure_substitution_history_schema():
    """Cria tabela de histÃƒÆ’Ã‚Â³rico de substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes se nÃƒÆ’Ã‚Â£o existir"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    if "substitutionhistory" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE substitutionhistory (
                    id SERIAL PRIMARY KEY,
                    original_employee_id INTEGER NOT NULL REFERENCES employee(id),
                    original_employee_name VARCHAR(255) NOT NULL,
                    original_registration_id VARCHAR(50) NOT NULL,
                    new_employee_id INTEGER NOT NULL REFERENCES employee(id),
                    new_employee_name VARCHAR(255) NOT NULL,
                    new_registration_id VARCHAR(50) NOT NULL,
                    reason VARCHAR(50) NOT NULL,
                    substitution_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    shift VARCHAR(50),
                    sector VARCHAR(255),
                    observations TEXT,
                    registered_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_substitutionhistory_original_employee_id ON substitutionhistory (original_employee_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_substitutionhistory_new_employee_id ON substitutionhistory (new_employee_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_substitutionhistory_reason ON substitutionhistory (reason)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_substitutionhistory_substitution_date ON substitutionhistory (substitution_date)"))
            print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Tabela substitutionhistory criada")

def migrate_existing_substitutions():
    """Migra substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes existentes (replaced_by) para o histÃƒÆ’Ã‚Â³rico"""
    with Session(engine) as session:
        # Verificar se jÃƒÆ’Ã‚Â¡ existem registros no histÃƒÆ’Ã‚Â³rico
        existing_count = session.exec(select(func.count()).select_from(models.SubstitutionHistory)).one()
        if existing_count > 0:
            print(f"ÃƒÂ¢Ã‚ÂÃ‚Â­ÃƒÂ¯Ã‚Â¸Ã‚Â HistÃƒÆ’Ã‚Â³rico de substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes jÃƒÆ’Ã‚Â¡ possui {existing_count} registros, pulando migraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o")
            return
        
        # Buscar colaboradores que foram substituÃƒÆ’Ã‚Â­dos (tÃƒÆ’Ã‚Âªm replaced_by preenchido)
        replaced_employees = session.exec(
            select(models.Employee)
            .where(models.Employee.replaced_by.isnot(None))
        ).all()
        
        if not replaced_employees:
            print("ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¹ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o existente para migrar")
            return
        
        migrated = 0
        for old_emp in replaced_employees:
            # Buscar o novo colaborador (que substituiu)
            new_emp = session.get(models.Employee, old_emp.replaced_by)
            if not new_emp:
                continue
            
            # Determinar o motivo baseado no status do colaborador antigo
            reason = 'fired' if old_emp.status == 'fired' else 'away'
            
            # Usar a data de admissÃƒÆ’Ã‚Â£o do novo colaborador ou data de demissÃƒÆ’Ã‚Â£o do antigo
            sub_date = new_emp.admission_date or old_emp.termination_date or datetime.now()
            
            # Criar registro no histÃƒÆ’Ã‚Â³rico
            history_record = models.SubstitutionHistory(
                original_employee_id=old_emp.id,
                original_employee_name=old_emp.name,
                original_registration_id=old_emp.registration_id,
                new_employee_id=new_emp.id,
                new_employee_name=new_emp.name,
                new_registration_id=new_emp.registration_id,
                reason=reason,
                substitution_date=sub_date,
                shift=old_emp.work_shift,
                sector=old_emp.cost_center,
                registered_by="migraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o_automÃƒÆ’Ã‚Â¡tica"
            )
            session.add(history_record)
            migrated += 1
        
        if migrated > 0:
            session.commit()
            print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Migradas {migrated} substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes existentes para o histÃƒÆ’Ã‚Â³rico")

def ensure_pallet_count_schema():
    """Cria ou atualiza as tabelas do sistema de contagem de paleteiras"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    # Criar tabela PalletSector se nÃƒÆ’Ã‚Â£o existir
    if "palletsector" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE palletsector (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    "order" INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletsector_name ON palletsector (name)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletsector_is_active ON palletsector (is_active)"))
            print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Tabela palletsector criada")
    
    # Verificar se sector_id tem constraint NOT NULL e remover
    if "palletcount" in existing_tables:
        try:
            with engine.begin() as conn:
                # Alterar sector_id para permitir NULL
                conn.execute(text("ALTER TABLE palletcount ALTER COLUMN sector_id DROP NOT NULL"))
        except Exception:
            pass  # JÃƒÆ’Ã‚Â¡ permite NULL ou erro ignorÃƒÆ’Ã‚Â¡vel
    
    # Criar tabela PalletCount se nÃƒÆ’Ã‚Â£o existir ou recriar se estrutura antiga
    if "palletcount" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE palletcount (
                    id SERIAL PRIMARY KEY,
                    pallet_number VARCHAR(50) NOT NULL,
                    date VARCHAR(10) NOT NULL,
                    shift VARCHAR(20) NOT NULL,
                    sector_id INTEGER REFERENCES palletsector(id),
                    employee_id INTEGER NOT NULL REFERENCES employee(id),
                    status VARCHAR(20) DEFAULT 'found',
                    observations TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_pallet_number ON palletcount (pallet_number)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_date ON palletcount (date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_shift ON palletcount (shift)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_status ON palletcount (status)"))
            print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Tabela palletcount criada")
    else:
        # Verificar se a tabela tem estrutura antiga (quantity) e migrar para nova (pallet_number)
        existing_cols = {col["name"] for col in inspector.get_columns("palletcount")}
        if "quantity" in existing_cols and "pallet_number" not in existing_cols:
            # Estrutura antiga - dropar e recriar
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS palletcount CASCADE"))
                conn.execute(text("""
                    CREATE TABLE palletcount (
                        id SERIAL PRIMARY KEY,
                        pallet_number VARCHAR(50) NOT NULL,
                        date VARCHAR(10) NOT NULL,
                        shift VARCHAR(20) NOT NULL,
                        sector_id INTEGER REFERENCES palletsector(id),
                        employee_id INTEGER NOT NULL REFERENCES employee(id),
                        status VARCHAR(20) DEFAULT 'found',
                        observations TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_pallet_number ON palletcount (pallet_number)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_date ON palletcount (date)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_shift ON palletcount (shift)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcount_status ON palletcount (status)"))
                print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Tabela palletcount recriada com nova estrutura")
    
    # Criar tabela PalletMaintenanceTicket se nÃƒÆ’Ã‚Â£o existir
    if "palletmaintenanceticket" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE palletmaintenanceticket (
                    id SERIAL PRIMARY KEY,
                    pallet_number VARCHAR(50) NOT NULL,
                    sector_id INTEGER REFERENCES palletsector(id),
                    employee_id INTEGER NOT NULL REFERENCES employee(id),
                    issue_type VARCHAR(50) DEFAULT 'other',
                    description TEXT NOT NULL,
                    priority VARCHAR(20) DEFAULT 'medium',
                    images JSON DEFAULT '[]',
                    status VARCHAR(20) DEFAULT 'open',
                    returned_pallet_number VARCHAR(50),
                    return_date TIMESTAMP,
                    return_notes TEXT,
                    email_sent_at TIMESTAMP,
                    email_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    closed_by VARCHAR(255)
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletmaintenanceticket_pallet_number ON palletmaintenanceticket (pallet_number)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletmaintenanceticket_status ON palletmaintenanceticket (status)"))
            print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Tabela palletmaintenanceticket criada")
    
    # Criar tabela PalletCountEmailRecipient se nÃƒÆ’Ã‚Â£o existir
    if "palletcountemailrecipient" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE palletcountemailrecipient (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    name VARCHAR(255),
                    alert_type VARCHAR(20) DEFAULT 'all',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcountemailrecipient_email ON palletcountemailrecipient (email)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_palletcountemailrecipient_is_active ON palletcountemailrecipient (is_active)"))
            print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Tabela palletcountemailrecipient criada")

def ensure_default_admin(session: Session):
    existing = session.exec(select(models.User)).first()
    if existing:
        return
    email = normalize_email(ADMIN_EMAIL)
    if "@" not in email:
        email = f"{email}@local"
    password = ADMIN_PASS
    if not email or not password:
        logger.warning("Nenhum admin padrÃƒÆ’Ã‚Â£o criado: ADMIN_EMAIL/ADMIN_PASS nÃƒÆ’Ã‚Â£o definidos.")
        return
    user = models.User(
        username=email,
        password_hash=hash_password(password),
        role=ADMIN_ROLE or "admin",
        is_active=True,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    session.add(user)
    session.commit()
    logger.warning("Admin padrÃƒÆ’Ã‚Â£o criado. Atualize ADMIN_EMAIL/ADMIN_PASS imediatamente.")

def admin_users_redirect(message: str, level: str = "success") -> RedirectResponse:
    query = urlencode({"message": message, "level": level})
    return RedirectResponse(url=f"/admin/users?{query}", status_code=status.HTTP_303_SEE_OTHER)

def admin_checklists_settings_redirect(message: str, level: str = "success") -> RedirectResponse:
    query = urlencode({"message": message, "level": level})
    return RedirectResponse(url=f"/admin/routine/checklists/settings?{query}", status_code=status.HTTP_303_SEE_OTHER)

def maintenance_emails_settings_redirect(message: str, level: str = "success") -> RedirectResponse:
    query = urlencode({"message": message, "level": level})
    return RedirectResponse(url=f"/admin/absence-alerts/settings?{query}", status_code=status.HTTP_303_SEE_OTHER)

# --- Auth Helper Functions ---
def get_current_user(request: Request):
    auth_user_id = request.session.get("auth_user_id")
    if auth_user_id:
        return {
            "type": "user",
            "id": auth_user_id,
            "role": request.session.get("auth_user_role"),
            "email": request.session.get("auth_user_email")
        }

    legacy_user = request.session.get("user")
    if legacy_user:
        return {"type": "user", "id": None, "role": "admin", "email": str(legacy_user)}

    # Support for Mobile Employee Session
    user_id = request.session.get("user_id")
    if user_id:
        return {"type": "employee", "id": user_id}
    return None

def require_login(request: Request):
    user = get_current_user(request)
    path = request.url.path

    # Not logged in at all
    if not user:
        if path.startswith("/mobile"):
             raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/mobile/login"})
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})

    # Logged in, check permissions
    if isinstance(user, dict) and user.get("type") == "user":
        role = (user.get("role") or "").lower()
        if role == "leader":
            allowed_keys = request.session.get("allowed_pages")
            if isinstance(allowed_keys, list):
                allowed_keys = [str(k) for k in allowed_keys if str(k) in PAGE_KEYS]
            else:
                allowed_keys = parse_allowed_pages(allowed_keys)
            allowed_prefixes = allowed_prefixes_for(allowed_keys)
            if not any(path.startswith(prefix) for prefix in allowed_prefixes):
                raise HTTPException(status_code=403, detail="Acesso negado.")
        return user

    # User is Employee (dict) -> RESTRICTED TO /mobile ONLY
    if isinstance(user, dict) and user.get("type") == "employee":
        if not path.startswith("/mobile") and not path.startswith("/static") and not path.startswith("/api"):
            # Trying to access Desktop/Admin page -> Redirect to Mobile Dashboard
            # e.g. /smart-flow, /employees, /
            print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ¢â‚¬â„¢ Access Denied: Mobile User {user.get('id')} tried to access {path}")
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/mobile/dashboard"})

    return user

def require_mobile_module(employee, module: str):
    if module == "separation":
        allowed = bool(getattr(employee, "mobile_access_separation", False))
    elif module == "checklist":
        allowed = bool(getattr(employee, "mobile_access_checklist", False))
    else:
        raise HTTPException(status_code=400, detail="MÃƒÆ’Ã‚Â³dulo invÃƒÆ’Ã‚Â¡lido.")

    if not allowed:
        raise HTTPException(status_code=403, detail="Acesso nÃƒÆ’Ã‚Â£o liberado para este mÃƒÆ’Ã‚Â³dulo")
    return True

def require_roles(request: Request, allowed_roles: set):
    user = require_login(request)
    actor_label = format_user_label(user)
    if isinstance(user, dict) and user.get("type") == "user":
        if (user.get("role") or "").lower() not in allowed_roles:
            raise HTTPException(status_code=403, detail="Acesso negado.")
        return user
    raise HTTPException(status_code=403, detail="Acesso negado.")

def require_leader(request: Request):
    return require_roles(request, {"leader", "admin"})

def require_admin(request: Request):
    return require_roles(request, {"admin"})

def require_gm(request: Request, session: Session = Depends(get_session)):
    """
    Dependency to ensure the user is logged in AND is a Game Master (Admin).
    """
    try:
        user = get_current_user(request)
        if not user:
             raise HTTPException(status_code=403, detail="Not authenticated")

        if isinstance(user, dict) and user.get("type") == "user":
            role = (user.get("role") or "").lower()
            if role in {"admin", "leader"}:
                return user
            raise HTTPException(status_code=403, detail="Acesso negado: Requer privilÃƒÆ’Ã‚Â©gios de Admin/GM.")

        if isinstance(user, dict) and user.get("type") == "employee":
            user_id = user.get("id")
            emp = session.get(models.Employee, user_id)
            if not emp:
                 raise HTTPException(status_code=403, detail="Employee not found")
            if emp.role not in ["Admin", "Manager", "Master"]:
                raise HTTPException(status_code=403, detail="Acesso negado: Requer privilÃƒÆ’Ã‚Â©gios de Admin/GM.")
            return emp
            
        raise HTTPException(status_code=403, detail="Invalid auth state")
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

# --- Admin Tools ---
# --- Admin Tools ---
@app.post("/api/admin/sync-xp-totals")
async def api_sync_xp_totals(request: Request, session: Session = Depends(get_session)):
    try:
        require_login(request) # Safety
        employees = session.exec(select(models.Employee)).all()
        count = 0
        for emp in employees:
            # Sum all non-rejected transactions
            total = session.exec(
                select(func.sum(models.GameXPTransaction.amount))
                .where(models.GameXPTransaction.employee_id == emp.id)
                .where(models.GameXPTransaction.status != "rejected")
            ).one() or 0
            
            if emp.total_xp != int(total):
                emp.total_xp = int(total)
                session.add(emp)
                count += 1
        
        session.commit()
        return {"success": True, "updated": count}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

# --- Achievement Management APIs ---

class AchievementSchema(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = ""
    icon: Optional[str] = "ÃƒÂ°Ã…Â¸Ã‚ÂÃ¢â‚¬Â "
    xp_reward: int = 100
    category: str = "general"
    trigger_type: str = "manual"
    trigger_value: Optional[str] = None

@app.get("/admin/game/achievements", response_class=HTMLResponse)
def admin_achievements_page(request: Request, user=Depends(require_leader)):
    """Page to manage achievements"""
    return templates.TemplateResponse("admin_achievements.html", {"request": request, "user": user})

@app.get("/api/game/achievements", dependencies=[Depends(require_leader)])
def api_list_achievements(session: Session = Depends(get_session), user=Depends(require_login)):
    try:
        achievements = session.exec(select(models.GameAchievement).order_by(models.GameAchievement.xp_reward)).all()
        return {"success": True, "data": achievements}
    except Exception as e:
        logger.error(f"Error listing achievements: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/game/achievements", dependencies=[Depends(require_leader)])
def api_save_achievement(
    data: AchievementSchema, 
    session: Session = Depends(get_session),
    user=Depends(require_login)
):
    try:
        if data.id:
            # Update
            ach = session.get(models.GameAchievement, data.id)
            if not ach:
                return {"success": False, "error": "Conquista nÃƒÆ’Ã‚Â£o encontrada"}
            
            ach.name = data.name
            ach.description = data.description
            ach.icon = data.icon
            ach.xp_reward = data.xp_reward
            ach.category = data.category
            ach.trigger_type = data.trigger_type
            ach.trigger_value = data.trigger_value
            session.add(ach)
        else:
            # Create
            ach = models.GameAchievement(
                name=data.name,
                description=data.description,
                icon=data.icon,
                xp_reward=data.xp_reward,
                category=data.category,
                trigger_type=data.trigger_type,
                trigger_value=data.trigger_value,
                slug=data.name.lower().replace(" ", "_") # Simple slug gen
            )
            session.add(ach)
        
        session.commit()
        session.refresh(ach)
        return {"success": True, "data": ach}

    except Exception as e:
        session.rollback()
        logger.error(f"Error saving achievement: {e}")
        return {"success": False, "error": str(e)}

@app.delete("/api/game/achievements/{ach_id}", dependencies=[Depends(require_leader)])
def api_delete_achievement(ach_id: int, session: Session = Depends(get_session), user=Depends(require_login)):
    try:
        ach = session.get(models.GameAchievement, ach_id)
        if not ach:
            return {"success": False, "error": "NÃƒÆ’Ã‚Â£o encontrado"}
        
        session.delete(ach)
        session.commit()
        return {"success": True}
    except Exception as e:
        session.rollback()
        return {"success": False, "error": str(e)}

class GrantAchievementSchema(BaseModel):
    achievement_id: int
    employee_id: int
    reason: Optional[str] = None

@app.post("/api/game/achievements/grant", dependencies=[Depends(require_leader)])
def api_grant_achievement(
    data: GrantAchievementSchema,
    session: Session = Depends(get_session),
    user=Depends(require_login)
):
    try:
        # 1. Verify exists
        ach = session.get(models.GameAchievement, data.achievement_id)
        emp = session.get(models.Employee, data.employee_id)
        
        if not ach or not emp:
            return {"success": False, "error": "Conquista ou Colaborador nÃƒÆ’Ã‚Â£o encontrado."}
        
        # 2. Register User Achievement
        user_ach = models.EmployeeAchievement(
            employee_id=emp.id,
            achievement_id=ach.id,
            status="approved",
            approved_by=str(user),
            approved_at=datetime.now(ZoneInfo("America/Sao_Paulo"))
        )
        session.add(user_ach)
        
        # 3. Create Transaction if XP > 0
        if ach.xp_reward > 0:
            tx = models.GameXPTransaction(
                employee_id=emp.id,
                amount=ach.xp_reward,
                source_type="achievement_grant",
                status="confirmed",
                reason=f"Conquista: {ach.name} | {data.reason or ''}",
                manager_id=str(user),
                confirmed_at=datetime.now(ZoneInfo("America/Sao_Paulo"))
            )
            session.add(tx)
            
            # 4. Update Employee Total
            emp.total_xp += ach.xp_reward
            session.add(emp)
            
        session.commit()
        
        return {
            "success": True, 
            "message": f"Conquista '{ach.name}' concedida para {emp.name}.",
            "xp_added": ach.xp_reward
        }
            
    except Exception as e:
        session.rollback()
        return {"success": False, "error": str(e)}


# --- Automatic Achievement Check/Audit APIs ---
from gamification_engine import check_and_award_achievements, audit_and_revoke_achievements

@app.get("/api/game/audit", dependencies=[Depends(require_leader)])
async def api_game_audit(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None,
    employee_id: Optional[int] = None,
    limit: int = 200,
    session: Session = Depends(get_session)
):
    """Auditoria estruturada de XP (para telas sem depender de parse de texto)."""
    require_login(request)

    q = (
        select(models.GameXPTransaction, models.Employee)
        .join(models.Employee)
        .order_by(models.GameXPTransaction.created_at.desc())
        .limit(min(max(limit, 1), 500))
    )

    if status:
        q = q.where(models.GameXPTransaction.status == status)
    if employee_id:
        q = q.where(models.GameXPTransaction.employee_id == employee_id)

    # Filtro por data via created_at
    if start_date:
        try:
            sdt = datetime.strptime(start_date, "%Y-%m-%d")
            q = q.where(models.GameXPTransaction.created_at >= sdt)
        except:
            pass
    if end_date:
        try:
            edt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            q = q.where(models.GameXPTransaction.created_at < edt)
        except:
            pass

    rows = session.exec(q).all()

    # Timezone BR
    from zoneinfo import ZoneInfo
    tz_br = ZoneInfo("America/Sao_Paulo")

    data = []
    for tx, emp in rows:
        parsed = parse_reason(tx.reason)
        
        # Converter created_at para timezone BR
        created_at_br = None
        if tx.created_at:
            # Se for naive, assumir UTC
            if tx.created_at.tzinfo is None:
                created_at_br = tx.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz_br)
            else:
                created_at_br = tx.created_at.astimezone(tz_br)
        
        data.append({
            "id": tx.id,
            "employee_id": tx.employee_id,
            "employee_name": emp.name,
            "created_at": created_at_br.strftime("%Y-%m-%d %H:%M") if created_at_br else None,
            "amount": int(tx.amount) if tx.amount is not None else 0,
            "status": tx.status,
            "source_type": tx.source_type,
            "reason": tx.reason,
            "ref": parsed["ref"],
            "kg": parsed["kg"],
            "uo": parsed["uo"],
            "evento": parsed["evento"],
            "regra_horario": parsed["regra_horario"],
        })

    return {"success": True, "items": data}


def parse_reason(reason: str):
    """Helper to parse raw reason strings into structured data."""
    # Extrai ref, kg, uo, evento, regra horario (quando existir no texto)
    ref = None
    kg = None
    uo = None
    evento = None
    regra_horario = None

    if not reason:
        return {"ref": ref, "kg": kg, "uo": uo, "evento": evento, "regra_horario": regra_horario}

    if "ref:" in reason:
        try:
            ref = reason.split("ref:")[1].split(")")[0].strip()
        except:
            ref = None

    parts = [p.strip() for p in reason.split("|")]
    for p in parts:
        if p.endswith("kg") and kg is None:
            # ex: "2591kg" ou "2591 kg"
            try:
                num = "".join(ch for ch in p if (ch.isdigit() or ch in ".,"))
                kg = float(num.replace(".", "").replace(",", ".")) if num else None
            except:
                pass
        if " UO" in p and uo is None:
            try:
                num = p.split("UO")[0].strip()
                uo = float(num.replace(",", "."))
            except:
                pass
        if p.startswith("Event:"):
            evento = p.replace("Event:", "").strip()
        if p.startswith("Early"):
            regra_horario = p

    return {"ref": ref, "kg": kg, "uo": uo, "evento": evento, "regra_horario": regra_horario}




@app.get("/api/game/audit/routes", dependencies=[Depends(require_leader)])
async def api_game_audit_routes(
    request: Request,
    date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    employee_id: Optional[int] = None,
    status: Optional[str] = "completed",
    limit: int = 500,
    session: Session = Depends(get_session)
):
    """Detalhamento por rota (rotina) com XP estimado por rota, para auditoria/explicaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o."""
    require_login(request)

    q = (
        select(models.Route, models.Employee.name, models.Client.name)
        .join(models.Employee)
        .join(models.Client)
        .order_by(desc(models.Route.date), desc(models.Route.id))
        .limit(min(max(limit, 1), 2000))
    )

    if status:
        q = q.where(models.Route.status == status)
    if employee_id:
        q = q.where(models.Route.employee_id == employee_id)

    if date:
        q = q.where(models.Route.date == date)
    else:
        if start_date:
            q = q.where(models.Route.date >= start_date)
        if end_date:
            q = q.where(models.Route.date <= end_date)

    rows = session.exec(q).all()

    # Regra base (espelha gamification_engine: 1500kg -> 1 UO, 100 XP por UO)
    KG_PER_UO = 1500.0
    XP_PER_UO = 100

    def parse_hhmm_to_minutes(t: Optional[str]):
        if not t:
            return None
        try:
            parts = str(t).split(":")
            if len(parts) < 2:
                return None
            return int(parts[0]) * 60 + int(parts[1])
        except:
            return None

    items = []
    for r, emp_name, client_name in rows:
        kg = float(r.tonnage or 0.0)
        uo = (kg / KG_PER_UO) if kg > 0 else 0.0
        xp_est = int(uo * XP_PER_UO)

        start_m = parse_hhmm_to_minutes(r.start_time)
        end_m = parse_hhmm_to_minutes(r.end_time)
        dur_min = None
        dur_hhmm = None
        kgh = None
        if start_m is not None and end_m is not None and end_m > start_m:
            dur_min = end_m - start_m
            hh = dur_min // 60
            mm = dur_min % 60
            dur_hhmm = f"{hh:02d}:{mm:02d}"
            hours = dur_min / 60.0
            if hours > 0:
                kgh = kg / hours

        items.append({
            "route_id": r.id,
            "date": r.date,
            "employee_id": r.employee_id,
            "employee_name": emp_name,
            "client_id": r.client_id,
            "client_name": client_name,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "duration": dur_hhmm,
            "duration_minutes": dur_min,
            "kg": kg,
            "uo": round(uo, 2),
            "kgh": round(kgh, 1) if kgh is not None else None,
            "xp_estimado": xp_est,
            "status": r.status,
        })

    return {"success": True, "items": items}

@app.get("/api/game/export/xp", dependencies=[Depends(require_leader)])
async def api_game_export_xp(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None,
    employee_id: Optional[int] = None,
    session: Session = Depends(get_session)
):
    """Exporta histÃƒÆ’Ã‚Â³rico de XP para CSV (Streaming)."""
    require_login(request)
    
    # Reutiliza lÃƒÆ’Ã‚Â³gica de filtro (query base)
    q = (
        select(models.GameXPTransaction, models.Employee)
        .join(models.Employee)
        .order_by(desc(models.GameXPTransaction.created_at))
    )
    
    if status:
        q = q.where(models.GameXPTransaction.status == status)
    if employee_id:
        q = q.where(models.GameXPTransaction.employee_id == employee_id)
        
    if start_date:
        try:
            sdt = datetime.strptime(start_date, "%Y-%m-%d")
            q = q.where(models.GameXPTransaction.created_at >= sdt)
        except: pass
            
    if end_date:
        try:
            edt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            q = q.where(models.GameXPTransaction.created_at < edt)
        except: pass
        
    # Stream Generator (Memory Efficient)
    async def iter_csv():
        # Header
        yield "ID,Data,Horario,Colaborador,Matricula,Quantidade XP,Status,Tipo,Motivo,Detalhes\n"
        
        # Rows
        # Stream chunks from DB if needed, or iterate all (assuming < 100k rows fits in memory/generator)
        # For simplicity and robust lock handling, we fetch all. 
        # If massive, we should paginate. Assuming manageable scale for now.
        records = session.exec(q).all()
        
        for tx, emp in records:
            dt_str = tx.created_at.strftime("%d/%m/%Y")
            hr_str = tx.created_at.strftime("%H:%M:%S")
            # Parse reason basics
            reason_clean = tx.reason.replace("\n", " ").replace(",", ";")
            
            row = [
                str(tx.id),
                dt_str,
                hr_str,
                emp.name,
                str(emp.registration_id),
                str(int(tx.amount)),
                tx.status,
                tx.source_type,
                reason_clean,
                "" # Extra
            ]
            yield ",".join(row) + "\n"

    filename = f"xp_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/game/audit/summary", dependencies=[Depends(require_leader)])
async def api_game_audit_summary(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = "confirmed",
    session: Session = Depends(get_session)
):
    """Retorna sumÃƒÆ’Ã‚Â¡rio agregado de XP por colaborador no perÃƒÆ’Ã‚Â­odo."""
    require_login(request)
    
    q = select(models.GameXPTransaction).where(models.GameXPTransaction.status == status)
    
    if start_date:
        try:
            sdt = datetime.strptime(start_date, "%Y-%m-%d")
            q = q.where(models.GameXPTransaction.created_at >= sdt)
        except: pass
    if end_date:
        try:
            edt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            q = q.where(models.GameXPTransaction.created_at < edt)
        except: pass
        
    transactions = session.exec(q).all()
    
    # Aggregate logic
    summary = {} # emp_id -> {amount: 0, count: 0}
    
    for tx in transactions:
        eid = tx.employee_id
        if eid not in summary:
            summary[eid] = {"amount": 0, "count": 0}
        summary[eid]["amount"] += tx.amount
        summary[eid]["count"] += 1
            
    # Enrich with Employee Names
    result = []
    if summary:
        emps = session.exec(select(models.Employee).where(col(models.Employee.id).in_(summary.keys()))).all()
        emp_map = {e.id: e for e in emps}
        
        for eid, stats in summary.items():
            emp = emp_map.get(eid)
            if emp:
                result.append({
                    "employee_id": eid,
                    "employee_name": emp.name,
                    "photo_url": emp.photo_url,
                    "total_xp": int(stats["amount"]),
                    "tx_count": stats["count"]
                })
    
    # Sort by XP Desc
    result.sort(key=lambda x: x["total_xp"], reverse=True)
    
    return {"success": True, "summary": result}


@app.post("/api/game/manual-xp", dependencies=[Depends(require_leader)])
async def api_manual_xp(payload: ManualXPRequest, request: Request, session: Session = Depends(get_session)):
    """Cria uma transaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o manual de XP (bonificaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o/penalidade)."""
    require_login(request)

    emp = session.get(models.Employee, payload.employee_id)
    if not emp:
        return JSONResponse({"success": False, "error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)

    # ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o bÃƒÆ’Ã‚Â¡sica
    if not payload.reason or not payload.reason.strip():
        return JSONResponse({"success": False, "error": "Informe um motivo (reason)."}, status_code=400)

    try:
        amount = int(payload.amount)
    except Exception:
        return JSONResponse({"success": False, "error": "amount invÃƒÆ’Ã‚Â¡lido."}, status_code=400)

    if amount == 0:
        return JSONResponse({"success": False, "error": "amount nÃƒÆ’Ã‚Â£o pode ser 0."}, status_code=400)

    status_val = (payload.status or "confirmed").strip().lower()
    if status_val not in ("confirmed", "provisional"):
        return JSONResponse({"success": False, "error": "status invÃƒÆ’Ã‚Â¡lido (use confirmed ou provisional)."}, status_code=400)

    now = datetime.now()
    tx = GameXPTransaction(
        employee_id=payload.employee_id,
        amount=amount,
        source_type="manual_admin",
        status=status_val,
        reason=f"Ajuste manual | {payload.reason.strip()}",
        created_at=now,
        confirmed_at=now if status_val == "confirmed" else None
    )

    session.add(tx)

    # Atualiza total_xp somente se confirmado
    if status_val == "confirmed":
        emp.total_xp += amount
        session.add(emp)

    session.commit()

    return {
        "success": True,
        "transaction": {
            "id": tx.id,
            "employee_id": tx.employee_id,
            "amount": tx.amount,
            "status": tx.status,
            "reason": tx.reason,
            "created_at": tx.created_at.isoformat()
        }
    }

@app.get("/admin/game", response_class=HTMLResponse)
async def admin_game_dashboard(request: Request, session: Session = Depends(get_session), user=Depends(require_leader)):
    """Manager Dashboard for Gamification Control"""
    # 1. Fetch Provisional Transactions
    pending_txs = session.exec(
        select(GameXPTransaction, models.Employee)
        .join(models.Employee)
        .where(GameXPTransaction.status == "provisional")
        .order_by(desc(GameXPTransaction.created_at))
    ).all()
    
    # Format for template
    pending_list = []
    for tx, emp in pending_txs:
        pending_list.append({
            "id": tx.id,
            "employee_name": emp.name,
            "amount": tx.amount,
            "reason": tx.reason,
            "date": tx.created_at.strftime("%d/%m %H:%M")
        })

    # 2. Fetch Recent Ledger (Audit)
    history_txs = session.exec(
        select(GameXPTransaction, models.Employee)
        .join(models.Employee)
        .order_by(desc(GameXPTransaction.created_at))
        .limit(50)
    ).all()
    
    formatted_history = []
    for tx, emp in history_txs:
        formatted_history.append({
             "id": tx.id,
             "employee_name": emp.name,
             "amount": tx.amount,
             "status": tx.status,
             "reason": tx.reason,
             "date": tx.created_at.strftime("%d/%m %H:%M")
        })
        
    return templates.TemplateResponse("admin_game.html", {
        "request": request,
        "pending_txs": pending_list
        # History removed from dashboard, moved to exclusive page
    })

@app.get("/admin/game/audit", response_class=HTMLResponse)
async def admin_game_audit(request: Request, session: Session = Depends(get_session), user=Depends(require_leader)):
    """Exclusive Audit Log Page"""
    history_txs = session.exec(
        select(GameXPTransaction, models.Employee)
        .join(models.Employee)
        .order_by(desc(GameXPTransaction.created_at))
        .limit(200) # Load more history
    ).all()
    
    formatted_history = []
    for tx, emp in history_txs:
        formatted_history.append({
             "id": tx.id,
             "employee_id": emp.id,
             "employee_name": emp.name,
             "amount": tx.amount,
             "status": tx.status,
             "reason": tx.reason,
             "date": tx.created_at.strftime("%d/%m/%Y %H:%M")
        })
        
    return templates.TemplateResponse("admin_game_audit.html", {
        "request": request,
        "history_txs": formatted_history
    })

@app.get("/admin/game/audit/employee/{employee_id}", response_class=HTMLResponse)
async def admin_game_employee_detail_page(
    request: Request, 
    employee_id: int, 
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """Employee Detail Page (HTML)"""
    require_login(request)
    emp = session.get(models.Employee, employee_id)
    if not emp:
        return HTMLResponse("Employee not found", status_code=404)
        
    return templates.TemplateResponse("admin_game_employee_detail.html", {
        "request": request,
        "employee": emp
    })

@app.get("/api/game/audit/employee/{employee_id}", dependencies=[Depends(require_leader)])
async def api_game_audit_employee_history(
    employee_id: int, 
    session: Session = Depends(get_session)
):
    """
    Fetch full XP history for a specific employee, including rejected/pending items.
    """
    # 1. Get Employee Info
    emp = session.get(models.Employee, employee_id)
    if not emp:
        return {"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado"}

    # 2. Get All Transactions (History)
    #    Order by newest first
    txs = session.exec(
        select(GameXPTransaction)
        .where(GameXPTransaction.employee_id == employee_id)
        .order_by(desc(GameXPTransaction.created_at))
    ).all()

    # 3. Collect Dates for enrichment (Produtividade YYYY-MM-DD or ref: daily_YYYY-MM-DD in reason)
    import re
    date_map = {} # tx_id -> date_str
    dates_to_fetch = set()
    
    for tx in txs:
        d = None
        reason = tx.reason or ''
        
        # Check for pattern "Produtividade YYYY-MM-DD" in reason
        match = re.search(r"Produtividade (\d{4}-\d{2}-\d{2})", reason)
        if match:
            d = match.group(1)
        else:
            # Fallback: Check for "ref: daily_YYYY-MM-DD" pattern in reason
            match2 = re.search(r"daily_(\d{4}-\d{2}-\d{2})", reason)
            if match2:
                d = match2.group(1)
        
        if d:
            date_map[tx.id] = d
            dates_to_fetch.add(d)
            
    # 4. Fetch Routes for these dates
    routes_by_date = {} # date_str -> list of route dicts
    
    if dates_to_fetch:
        # Helper duration
        def calc_duration(start, end):
            if not start or not end: return None
            try:
                sh, sm = map(int, start.split(':'))
                eh, em = map(int, end.split(':'))
                start_mins = sh * 60 + sm
                end_mins = eh * 60 + em
                if end_mins > start_mins:
                    diff = end_mins - start_mins
                    return f"{diff // 60:02d}:{diff % 60:02d}"
            except: pass
            return None

        # Fetch
        r_rows = session.exec(
            select(models.Route, models.Client.name)
            .join(models.Client, isouter=True)
            .where(
                models.Route.employee_id == employee_id,
                col(models.Route.date).in_(dates_to_fetch)
            )
            .order_by(models.Route.start_time)
        ).all()
        
        for r, cname in r_rows:
            if r.date not in routes_by_date:
                routes_by_date[r.date] = []
            
            duration = calc_duration(r.start_time, r.end_time)
            routes_by_date[r.date].append({
                "id": r.id,
                "client_name": cname or "Cliente Desconhecido",
                "start_time": r.start_time,
                "end_time": r.end_time,
                "duration": duration,
                "kg": r.tonnage
            })

    # 5. Format Response
    history = []
    for tx in txs:
        parsed = parse_reason(tx.reason) # Use local or global parse_reason
        
        # Enrich
        route_info = None
        tx_date = date_map.get(tx.id)
        if tx_date:
            # Always include route_info with the date, even if no routes found
            route_info = {
                "date": tx_date,
                "routes": routes_by_date.get(tx_date, [])
            }
            
        history.append({
            "id": tx.id,
            "amount": tx.amount,
            "status": tx.status,
            "source_type": tx.source_type,
            "reason": tx.reason,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "confirmed_at": tx.confirmed_at.isoformat() if tx.confirmed_at else None,
            "details": parsed,
            "route_info": route_info
        })
    
    # Debug info
    debug = {
        "dates_extracted": list(dates_to_fetch),
        "dates_with_routes": list(routes_by_date.keys()),
        "route_counts": {d: len(routes_by_date[d]) for d in routes_by_date}
    }
    
    return {
        "employee": {
            "id": emp.id,
            "name": emp.name,
            "registration_id": emp.registration_id,
            "total_xp": emp.total_xp
        },
        "history": history,
        "debug": debug
    }

class LevelsPayload(BaseModel):
    levels: List[models.GameLevel]

@app.post("/api/game/levels", dependencies=[Depends(require_leader)])
async def api_save_levels(payload: LevelsPayload, session: Session = Depends(get_session)):
    """Sync Levels: Update existing, Create new, Delete missing"""
    try:
        incoming = payload.levels
        incoming_ids = {l.id for l in incoming if l.id is not None}
        
        # 1. Delete missing
        existing = session.exec(select(models.GameLevel)).all()
        for ex in existing:
            if ex.id not in incoming_ids:
                session.delete(ex)
        
        # 2. Update or Create
        for item in incoming:
            if item.id:
                # Update
                db_item = session.get(models.GameLevel, item.id)
                if db_item:
                    db_item.level = item.level
                    db_item.name = item.name
                    db_item.min_xp = item.min_xp
                    db_item.min_months = item.min_months
                    db_item.badge_image = item.badge_image
                    session.add(db_item)
            else:
                # Create
                # ensure id is None so DB auto-increments
                item.id = None 
                session.add(item)
                
        session.commit()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

class AchievementsPayload(BaseModel):
    achievements: List[models.GameAchievement]

@app.post("/api/game/achievements/sync", dependencies=[Depends(require_leader)])
async def api_save_achievements(payload: AchievementsPayload, session: Session = Depends(get_session)):
    """Sync Achievements: Update existing, Create new, Delete missing"""
    try:
        incoming = payload.achievements
        incoming_ids = {a.id for a in incoming if a.id is not None}
        
        # 1. Delete missing
        existing = session.exec(select(models.GameAchievement)).all()
        for ex in existing:
            if ex.id not in incoming_ids:
                session.delete(ex)
        
        # 2. Update or Create
        for item in incoming:
            if item.id:
                db_item = session.get(models.GameAchievement, item.id)
                if db_item:
                    db_item.slug = item.slug
                    db_item.name = item.name
                    db_item.description = item.description
                    db_item.icon = item.icon
                    db_item.xp_reward = item.xp_reward
                    db_item.is_manual = item.is_manual
                    session.add(db_item)
            else:
                item.id = None
                session.add(item)
                
        session.commit()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/game/transaction/{tx_id}/{action}", dependencies=[Depends(require_leader)])
async def api_manage_tx(tx_id: int, action: str, session: Session = Depends(get_session)):
    """Approve/Reject Provisional Transaction"""
    tx = session.get(GameXPTransaction, tx_id)
    if not tx: return {"error": "TransaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o encontrada"}
    
    
    if action == "approve":
        tx.status = "confirmed"
        tx.confirmed_at = datetime.now()
        # Add to Employee Total
        emp = session.get(models.Employee, tx.employee_id)
        if emp:
            emp.total_xp += tx.amount
            session.add(emp)
    elif action == "reject":
        tx.status = "rejected"
    
    session.add(tx)
    session.commit()
    return {"success": True, "status": tx.status}

@app.get("/admin/game/settings", response_class=HTMLResponse)
async def admin_game_settings(request: Request, session: Session = Depends(get_session)):
    """Configuration Page"""
    try:
        require_leader(request)
        
        configs = session.exec(select(models.GameConfiguration)).all()
        # Convert list to dict for frontend
        config_dict = {c.key: c.value for c in configs}
        
        # Fetch Levels
        levels = session.exec(select(models.GameLevel).order_by(models.GameLevel.level)).all()
        levels_data = [l.model_dump() for l in levels]
        
        # Fetch Achievements
        achievements = session.exec(select(models.GameAchievement)).all()
        achievements_data = [a.model_dump() for a in achievements]
        
        # Parse special events and time bonuses from config (stored as JSON strings)
        special_events = []
        time_bonuses = []
        try:
            special_events_str = config_dict.get("xp_special_events", "[]")
            special_events = json.loads(special_events_str) if special_events_str else []
        except:
            special_events = []
        try:
            time_bonuses_str = config_dict.get("xp_time_rules", "[]")
            time_bonuses = json.loads(time_bonuses_str) if time_bonuses_str else []
        except:
            time_bonuses = []
        
        return templates.TemplateResponse("admin_game_settings.html", {
            "request": request,
            "config_json": json.dumps(config_dict),
            "levels_json": json.dumps(levels_data),
            "achievements_json": json.dumps(achievements_data),
            "special_events_json": json.dumps(special_events),
            "time_bonuses_json": json.dumps(time_bonuses)
        })
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"<h1>Erro 500 Debug</h1><pre>{traceback.format_exc()}</pre>", status_code=500)

@app.post("/api/game/settings", dependencies=[Depends(require_leader)])
async def api_save_settings(request: Request, session: Session = Depends(get_session)):
    data = await request.json()
    
    for key, val in data.items():
        # Update or Insert
        # Ensure complex types are valid JSON strings
        if isinstance(val, (dict, list)):
            val_str = json.dumps(val)
        else:
            val_str = str(val)

        conf = session.get(models.GameConfiguration, key)
        if conf:
            conf.value = val_str
            conf.updated_at = datetime.now()
            session.add(conf)
        else:
            # Create new config if not exists
            # Determine defaults
            cat = "general"
            desc = "Auto-generated setting"
            if "xp_" in key:
                cat = "gamification"
                desc = f"Gamification Setting for {key}"
                
            new_conf = models.GameConfiguration(
                key=key, 
                value=val_str, 
                updated_at=datetime.now(),
                category=cat,
                description=desc
            )
            session.add(new_conf)
            
    session.commit()
    return {"success": True}


# --- END Gamification V2 ---


@app.post("/mobile/route/{route_id}/finish", response_class=JSONResponse)
async def mobile_route_finish(
    request: Request, 
    route_id: int, 
    session: Session = Depends(get_session)
):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
             return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)

        employee = session.get(models.Employee, user_id)
        if not employee:
             return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
        try:
            require_mobile_module(employee, "separation")
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                return JSONResponse({"detail": exc.detail}, status_code=403)
            raise
              
        route = session.get(models.Route, route_id)
        if not route:
             return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
             
        if route.employee_id != user_id:
             return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=403)
             
        # Close Route
        route.end_time = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M")
        route.status = "completed"
        session.add(route)
        session.commit()
        
        # Recalculate Daily XP
        try:
            from gamification_engine import calculate_daily_xp
            calculate_daily_xp(session, route.date)
        except Exception as e:
            logger.error(f"Error calculating XP on mobile finish: {e}")
            
        return JSONResponse({"success": True})
    except Exception as e:
        logger.exception(f"Error finishing route {route_id}: {e}")
class MobileDeletePayload(BaseModel):
    registration_id: str

class MobileUpdatePayload(BaseModel):
    client_id: Optional[int] = None
    tonnage: Optional[float] = None


class MobileDeliverySessionStartPayload(BaseModel):
    plate: str
    helpers: List[str] = []
    km_departure: float


class MobileDeliverySessionEndPayload(BaseModel):
    km_return: float


class MobileDeliveryActionPayload(BaseModel):
    action: str
    return_reason: Optional[str] = None
    return_is_partial: bool = False
    return_partial_weight: Optional[float] = None
    return_partial_value: Optional[float] = None

class AdminStartRoutePayload(BaseModel):
    client_id: int
    tonnage: Optional[float] = 0.0
    start_time: Optional[str] = None # HH:MM, defaults to now

def ensure_column(engine, table_name, column_name, column_type_sql):
    """Adds a column to a table if it doesn't exist (SQLite specific)."""
    with engine.connect() as conn:
        try:
            # Check if column exists
            columns = inspect(engine).get_columns(table_name)
            column_names = [c["name"] for c in columns]
            if column_name not in column_names:
                logger.info(f"Adding column {column_name} to table {table_name}")
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type_sql}"))
                conn.commit()
        except Exception as e:
            logger.error(f"Error adding column {column_name}: {e}")

def ensure_checklist_odometer_schema():
    """Adiciona coluna odometer_km ÃƒÆ’Ã‚Â  tabela transpalletchecklist se nÃƒÆ’Ã‚Â£o existir."""
    try:
        inspector = inspect(engine)
        tbl = "transpalletchecklist"
        if tbl not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns(tbl)}
        if "odometer_km" not in cols:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN odometer_km REAL"))
                conn.commit()
    except Exception as e:
        logger.error(f"ensure_checklist_odometer_schema: {e}")


def ensure_vehicle_schema():
    """Adiciona colunas in_workshop, sale_value, sold_at ÃƒÆ’Ã‚Â  tabela vehicle se nÃƒÆ’Ã‚Â£o existirem."""
    try:
        inspector = inspect(engine)
        if "vehicle" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("vehicle")}
        with engine.connect() as conn:
            if "in_workshop" not in cols:
                conn.execute(text("ALTER TABLE vehicle ADD COLUMN in_workshop INTEGER DEFAULT 0"))
                conn.commit()
            if "sale_value" not in cols:
                conn.execute(text("ALTER TABLE vehicle ADD COLUMN sale_value REAL"))
                conn.commit()
            if "sold_at" not in cols:
                conn.execute(text("ALTER TABLE vehicle ADD COLUMN sold_at TIMESTAMP"))
                conn.commit()
            if "odometer_km" not in cols:
                conn.execute(text("ALTER TABLE vehicle ADD COLUMN odometer_km REAL"))
                conn.commit()
    except Exception as e:
        logger.error(f"ensure_vehicle_schema: {e}")


def ensure_client_schema():
    """Adiciona colunas extras de cadastro ÃƒÆ’Ã‚Â  tabela client se nÃƒÆ’Ã‚Â£o existirem."""
    try:
        inspector = inspect(engine)
        if "client" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("client")}
        missing = {
            "nb": "VARCHAR(64)",
            "setor": "VARCHAR(128)",
            "me": "VARCHAR(64)",
            "sa": "VARCHAR(128)",
            "visita": "VARCHAR(64)",
            "nome_fantasia": "VARCHAR(255)",
            "razao_social": "VARCHAR(255)",
            "municipio": "VARCHAR(128)",
            "bairro": "VARCHAR(128)",
            "endereco": "VARCHAR(255)",
            "fone": "VARCHAR(64)",
            "fone_e164": "VARCHAR(32)",
            "endereco_normalizado": "VARCHAR(255)",
            "segmento": "VARCHAR(128)",
            "status_cliente": "VARCHAR(64)",
            "status_operacional": "VARCHAR(32)",
            "logradouro": "VARCHAR(255)",
            "numero": "VARCHAR(32)",
            "complemento": "VARCHAR(128)",
            "referencia": "VARCHAR(255)",
            "observacoes_acesso": "TEXT",
            "fone_alternativo": "VARCHAR(64)",
            "observacoes_contato": "TEXT",
            "janela_dias_semana": "TEXT",
            "janela_horario_inicio": "VARCHAR(8)",
            "janela_horario_fim": "VARCHAR(8)",
            "prioridade_logistica": "VARCHAR(4)",
            "lgpd_nao_contatar": "BOOLEAN DEFAULT FALSE",
            "lgpd_restricao_dados": "BOOLEAN DEFAULT FALSE",
            "updated_at": "TIMESTAMP",
        }
        with engine.connect() as conn:
            for col_name, col_type in missing.items():
                if col_name not in cols:
                    try:
                        conn.execute(text(f"ALTER TABLE client ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                        logger.info(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Coluna {col_name} adicionada ÃƒÆ’Ã‚Â  tabela client")
                    except Exception as col_err:
                        logger.error(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao adicionar coluna {col_name}: {col_err}")
    except Exception as e:
        logger.error(f"ensure_client_schema: {e}")


def ensure_route_schema():
    """Adiciona colunas auxiliares da tabela route (separaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o + entregas)."""
    try:
        inspector = inspect(engine)
        if "route" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("route")}
        missing = {
            "type": "VARCHAR(32) DEFAULT 'separation'",
            "valor_financeiro": "REAL",
            "devolucao_volume": "REAL",
            "valor_devolucao": "REAL",
            "delivery_status": "VARCHAR(32)",
            "delivery_route_code": "VARCHAR(64)",
            "delivery_order_number": "VARCHAR(64)",
            "delivery_client_code": "VARCHAR(64)",
            "delivery_vehicle_plate": "VARCHAR(32)",
            "delivery_cep": "VARCHAR(24)",
            "delivery_address": "TEXT",
            "delivery_neighborhood": "VARCHAR(120)",
            "delivery_city": "VARCHAR(120)",
            "delivery_state": "VARCHAR(8)",
            "delivery_type": "VARCHAR(32)",
            "delivery_total_weight": "REAL",
            "delivery_order_date": "VARCHAR(10)",
            "delivery_source_file": "VARCHAR(255)",
            "delivery_return_category": "VARCHAR(64)",
            "delivery_return_reason": "TEXT",
            "delivery_started_at": "VARCHAR(5)",
            "delivery_finished_at": "VARCHAR(5)",
            "delivery_canceled_at": "VARCHAR(5)",
            "delivery_returned_at": "VARCHAR(5)",
            "delivery_time_log": "TEXT",
            "delivery_reopen_count": "INTEGER DEFAULT 0",
            "delivery_helpers_json": "TEXT",
        }
        with engine.connect() as conn:
            for col_name, col_type in missing.items():
                if col_name not in cols:
                    conn.execute(text(f"ALTER TABLE route ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
    except Exception as e:
        logger.error(f"ensure_route_schema: {e}")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    ensure_default_admin()
    ensure_pallet_count_schema()
    ensure_vehicle_schema()
    ensure_checklist_odometer_schema()
    # Migration for new column
    ensure_column(engine, "employee", "mobile_access_admin_start", "BOOLEAN DEFAULT FALSE")
    ensure_column(engine, "employee", "seller_code", "VARCHAR(64)")

@app.get("/api/admin/clients", dependencies=[Depends(require_leader)])
async def api_get_admin_clients(session: Session = Depends(get_session)):
    """Get all clients for admin purposes."""
    clients = session.exec(select(models.Client)).all()
    return [client.model_dump() for client in clients]

@app.post("/mobile/route/{route_id}/delete", response_class=JSONResponse)
async def mobile_route_delete(
    request: Request, 
    route_id: int, 
    payload: MobileDeletePayload,
    session: Session = Depends(get_session)
):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)

        employee = session.get(models.Employee, user_id)
        if not employee:
            return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
        
        # Verificar MatrÃƒÆ’Ã‚Â­cula para confirmaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de seguranÃƒÆ’Ã‚Â§a
        # Remove zeros a esquerda para comparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o flexÃƒÆ’Ã‚Â­vel se necessÃƒÆ’Ã‚Â¡rio, ou validaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o exata
        if payload.registration_id.strip() != employee.registration_id.strip():
             return JSONResponse({"error": "MatrÃƒÆ’Ã‚Â­cula incorreta. A exclusÃƒÆ’Ã‚Â£o requer sua confirmaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o."}, status_code=403)

        route = session.get(models.Route, route_id)
        if not route:
             return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
             
        if route.employee_id != user_id:
             return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado: Rota pertence a outro colaborador"}, status_code=403)
        
        if route.status == "completed":
             return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© possÃƒÆ’Ã‚Â­vel excluir uma rota jÃƒÆ’Ã‚Â¡ finalizada."}, status_code=400)

        # Deletar
        session.delete(route)
        session.commit()
        
        return JSONResponse({"success": True})
    except Exception as e:
        logger.exception(f"Error deleting route {route_id}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/mobile/route/{route_id}/update", response_class=JSONResponse)
async def mobile_route_update(
    request: Request,
    route_id: int,
    payload: MobileUpdatePayload,
    session: Session = Depends(get_session)
):
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)

        route = session.get(models.Route, route_id)
        if not route:
             return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)

        if route.employee_id != user_id:
             return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=403)

        if route.status == "completed":
             return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© possÃƒÆ’Ã‚Â­vel editar uma rota jÃƒÆ’Ã‚Â¡ finalizada."}, status_code=400)

        # Atualizar campos se fornecidos
        if payload.client_id:
            client = session.get(models.Client, payload.client_id)
            if not client:
                return JSONResponse({"error": "Cliente invÃƒÆ’Ã‚Â¡lido"}, status_code=404)
            route.client_id = payload.client_id

        if payload.tonnage is not None:
            if payload.tonnage <= 0:
                 return JSONResponse({"error": "Peso deve ser maior que zero"}, status_code=400)
            route.tonnage = payload.tonnage

        session.add(route)
        session.commit()

        return JSONResponse({"success": True})
    except Exception as e:
        logger.exception(f"Error updating route {route_id}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/mobile/delivery/my-routes", response_class=JSONResponse)
async def api_mobile_delivery_my_routes(
    request: Request,
    session: Session = Depends(get_session)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)

    today_str = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    routes = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.employee_id == user_id)
        .where(models.Route.delivery_status.in_(["pendente", "iniciada", "reaberta", "entregue", "devolucao"]))
        .order_by(models.Route.date, models.Route.id)
    ).all()
    client_ids = list({r.client_id for r in routes})
    clients = session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all() if client_ids else []
    client_map = {c.id: c for c in clients}

    session_open = session.exec(
        select(models.DeliverySession)
        .where(models.DeliverySession.employee_id == user_id)
        .where(models.DeliverySession.date == today_str)
        .where(models.DeliverySession.status == "open")
        .order_by(models.DeliverySession.id.desc())
    ).first()

    payload = []
    grouped = {}
    for r in routes:
        c = client_map.get(r.client_id)
        item = {
            "id": r.id,
            "date": r.date,
            "client_name": (c.razao_social if c and c.razao_social else (c.name if c else "Cliente")),
            "client_secondary": (c.nome_fantasia if c and c.nome_fantasia else (c.name if c else "")),
            "address": r.delivery_address or "",
            "city": r.delivery_city or "",
            "bairro": r.delivery_neighborhood or "",
            "state": r.delivery_state or "",
            "cep": r.delivery_cep or "",
            "maps_url": _maps_link(r.delivery_address, r.delivery_neighborhood, r.delivery_city, r.delivery_state, r.delivery_cep),
            "weight": r.tonnage or 0.0,
            "value": r.valor_financeiro or 0.0,
            "status": (r.delivery_status or "pendente"),
            "started_at": r.delivery_started_at,
            "finished_at": r.delivery_finished_at,
            "returned_at": r.delivery_returned_at,
            "reopen_count": r.delivery_reopen_count or 0,
            "vehicle_plate": r.delivery_vehicle_plate or "",
            "order_number": r.delivery_order_number or "",
            "client_code": r.delivery_client_code or "",
        }
        payload.append(item)
        grouped.setdefault(r.date, []).append(item)

    assigned_plates = []
    for r in routes:
        if r.delivery_vehicle_plate and r.delivery_vehicle_plate not in assigned_plates:
            assigned_plates.append(r.delivery_vehicle_plate)

    day_cards = []
    for d, items in grouped.items():
        try:
            d_fmt = datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m")
        except Exception:
            d_fmt = d
        day_cards.append({
            "date": d,
            "label": f"Entregas do Dia {d_fmt}",
            "count": len(items),
            "routes": items,
        })
    day_cards.sort(key=lambda x: x["date"])

    return JSONResponse({
        "success": True,
        "date": today_str,
        "assigned_plate": assigned_plates[0] if assigned_plates else "",
        "assigned_plates": assigned_plates,
        "session_open": bool(session_open),
        "session": {
            "id": session_open.id if session_open else None,
            "km_departure": session_open.km_departure if session_open else None,
            "vehicle_plate": session_open.vehicle_plate if session_open else None,
        } if session_open else None,
        "routes": payload,
        "day_cards": day_cards,
        "return_reasons": DELIVERY_RETURN_REASONS_FLAT,
    })


@app.post("/api/mobile/delivery/session/start", response_class=JSONResponse)
async def api_mobile_delivery_session_start(
    request: Request,
    payload: MobileDeliverySessionStartPayload,
    session: Session = Depends(get_session)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
    today_str = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")

    routes = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.employee_id == user_id)
        .where(models.Route.delivery_status.in_(["pendente", "iniciada", "reaberta"]))
    ).all()
    if not routes:
        return JSONResponse({"error": "Sem entregas planejadas para hoje."}, status_code=400)

    assigned_plates = sorted({r.delivery_vehicle_plate for r in routes if r.delivery_vehicle_plate})
    if not assigned_plates:
        return JSONResponse({"error": "CaminhÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o definido no planejamento."}, status_code=400)

    if _norm_plate(payload.plate) not in {_norm_plate(p) for p in assigned_plates}:
        return JSONResponse({"error": f"Placa invÃƒÆ’Ã‚Â¡lida. Placa(s) planejada(s): {', '.join(assigned_plates)}."}, status_code=400)

    existing = session.exec(
        select(models.DeliverySession)
        .where(models.DeliverySession.employee_id == user_id)
        .where(models.DeliverySession.date == today_str)
        .where(models.DeliverySession.status == "open")
    ).first()
    if existing:
        return JSONResponse({"error": "Rotina de entrega jÃƒÆ’Ã‚Â¡ iniciada."}, status_code=400)

    helper_names: List[str] = []
    seen_helpers = set()
    for h in (payload.helpers or []):
        clean = (h or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen_helpers:
            continue
        seen_helpers.add(key)
        helper_names.append(clean)

    new_session = models.DeliverySession(
        date=today_str,
        employee_id=user_id,
        status="open",
        vehicle_plate=payload.plate.strip().upper(),
        helpers_json=json.dumps(helper_names),
        km_departure=payload.km_departure,
    )
    session.add(new_session)
    session.commit()
    return JSONResponse({"success": True})


@app.post("/api/mobile/delivery/session/end", response_class=JSONResponse)
async def api_mobile_delivery_session_end(
    request: Request,
    payload: MobileDeliverySessionEndPayload,
    session: Session = Depends(get_session)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
    today_str = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    ds = session.exec(
        select(models.DeliverySession)
        .where(models.DeliverySession.employee_id == user_id)
        .where(models.DeliverySession.date == today_str)
        .where(models.DeliverySession.status == "open")
        .order_by(models.DeliverySession.id.desc())
    ).first()
    if not ds:
        return JSONResponse({"error": "Nenhuma rotina aberta."}, status_code=400)
    if payload.km_return <= 0:
        return JSONResponse({"error": "KM de chegada invÃƒÆ’Ã‚Â¡lido."}, status_code=400)

    pending = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == today_str)
        .where(models.Route.employee_id == user_id)
        .where(models.Route.delivery_status.in_(["pendente", "iniciada", "reaberta"]))
    ).all()
    if pending:
        return JSONResponse({"error": "Ainda existem entregas em aberto. Finalize/devolva antes de encerrar."}, status_code=400)

    ds.km_return = payload.km_return
    ds.status = "closed"
    ds.ended_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    session.add(ds)
    session.commit()
    return JSONResponse({"success": True})


@app.post("/api/mobile/delivery/route/{route_id}/action", response_class=JSONResponse)
async def api_mobile_delivery_route_action(
    request: Request,
    route_id: int,
    payload: MobileDeliveryActionPayload,
    session: Session = Depends(get_session)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
    route = session.get(models.Route, route_id)
    if not route or route.type != "delivery" or route.employee_id != user_id:
        return JSONResponse({"error": "Rota invÃƒÆ’Ã‚Â¡lida."}, status_code=404)

    today_str = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    ds = session.exec(
        select(models.DeliverySession)
        .where(models.DeliverySession.employee_id == user_id)
        .where(models.DeliverySession.date == today_str)
        .where(models.DeliverySession.status == "open")
    ).first()
    if not ds:
        return JSONResponse({"error": "Inicie a rotina (placa/KM) antes de operar entregas."}, status_code=400)

    action = (payload.action or "").lower().strip()
    now = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M")
    if action == "iniciar":
        existing_started = session.exec(
            select(models.Route)
            .where(models.Route.type == "delivery")
            .where(models.Route.date == route.date)
            .where(models.Route.employee_id == user_id)
            .where(models.Route.delivery_status == "iniciada")
            .where(models.Route.id != route.id)
        ).first()
        if existing_started:
            return JSONResponse({"error": "JÃƒÆ’Ã‚Â¡ existe uma entrega iniciada."}, status_code=400)
        if (route.delivery_status or "").lower() in ("entregue", "devolucao"):
            return JSONResponse({"error": "Rota concluÃƒÆ’Ã‚Â­da. Reabra para iniciar novamente."}, status_code=400)
        route.delivery_status = "iniciada"
        route.start_time = now
        if not route.delivery_started_at:
            route.delivery_started_at = now
        _append_delivery_event(route, "iniciar", now)

    elif action == "finalizar":
        if (route.delivery_status or "").lower() != "iniciada":
            return JSONResponse({"error": "SÃƒÆ’Ã‚Â³ pode finalizar rota iniciada."}, status_code=400)
        route.delivery_status = "entregue"
        route.status = "completed"
        route.end_time = now
        if not route.delivery_finished_at:
            route.delivery_finished_at = now
        route.delivery_return_category = None
        route.delivery_return_reason = None
        _append_delivery_event(route, "finalizar", now)

    elif action == "devolucao":
        if (route.delivery_status or "").lower() != "iniciada":
            return JSONResponse({"error": "Inicie a entrega antes de devolver."}, status_code=400)
        if not payload.return_reason:
            return JSONResponse({"error": "Informe o motivo da devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o."}, status_code=400)
        if payload.return_reason not in DELIVERY_RETURN_REASONS_FLAT:
            return JSONResponse({"error": "Motivo de devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o invÃƒÆ’Ã‚Â¡lido."}, status_code=400)
        route.delivery_status = "devolucao"
        route.status = "completed"
        route.end_time = now
        if not route.delivery_returned_at:
            route.delivery_returned_at = now
        if not route.delivery_finished_at:
            route.delivery_finished_at = now
        route.delivery_return_category = "MOBILE"
        route.delivery_return_reason = payload.return_reason
        if payload.return_is_partial:
            w = float(payload.return_partial_weight or 0.0)
            v = float(payload.return_partial_value or 0.0)
            if w <= 0 and v <= 0:
                return JSONResponse({"error": "Para devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o parcial informe peso e/ou valor."}, status_code=400)
            route.devolucao_volume = min(w, float(route.tonnage or 0.0)) if w > 0 else 0.0
            route.valor_devolucao = min(v, float(route.valor_financeiro or 0.0)) if v > 0 else 0.0
        else:
            route.devolucao_volume = route.tonnage or 0.0
            route.valor_devolucao = route.valor_financeiro or 0.0
        _append_delivery_event(route, "devolucao", now, note=payload.return_reason)

    elif action == "reabrir":
        if (route.delivery_status or "").lower() not in ("entregue", "devolucao"):
            return JSONResponse({"error": "Somente rotas concluÃƒÆ’Ã‚Â­das podem ser reabertas."}, status_code=400)
        existing_started = session.exec(
            select(models.Route)
            .where(models.Route.type == "delivery")
            .where(models.Route.date == route.date)
            .where(models.Route.employee_id == user_id)
            .where(models.Route.delivery_status == "iniciada")
            .where(models.Route.id != route.id)
        ).first()
        if existing_started:
            return JSONResponse({"error": "JÃƒÆ’Ã‚Â¡ existe uma entrega iniciada."}, status_code=400)
        route.delivery_status = "reaberta"
        route.status = "pending"
        route.end_time = None
        route.delivery_reopen_count = (route.delivery_reopen_count or 0) + 1
        _append_delivery_event(route, "reabrir", now)

    else:
        return JSONResponse({"error": "AÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o invÃƒÆ’Ã‚Â¡lida."}, status_code=400)

    session.add(route)
    session.commit()
    return JSONResponse({"success": True})

# --- ADMIN ROUTE MANAGEMENT ---

@app.post("/api/admin/employees/{employee_id}/start-route", response_class=JSONResponse)
async def api_admin_start_route(
    request: Request,
    employee_id: int,
    payload: AdminStartRoutePayload,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    try:
        employee = session.get(models.Employee, employee_id)
        if not employee:
            return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
            
        if not employee.mobile_access_admin_start:
             return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o possui permissÃƒÆ’Ã‚Â£o para abertura manual por lÃƒÆ’Ã‚Â­der."}, status_code=403)

        from datetime import datetime
        now = datetime.now(ZoneInfo("America/Sao_Paulo"))
        today_str = now.strftime("%Y-%m-%d")
        
        # Check for existing routine
        routine = session.exec(select(models.EmployeeRoutine).where(
            models.EmployeeRoutine.employee_id == employee.id,
            models.EmployeeRoutine.date == today_str
        )).first()
        
        if not routine:
            # Create Routine
            routine = models.EmployeeRoutine(
                employee_id=employee.id,
                date=today_str,
                shift=employee.work_shift or "ManhÃƒÆ’Ã‚Â£",
                status="present",
                arrival_time=payload.start_time or now.strftime("%H:%M")
            )
            session.add(routine)
            session.commit()
            session.refresh(routine)
            
        # Create Route
        start_time = payload.start_time or now.strftime("%H:%M")
        
        # Check if already has active route?
        active_route = session.exec(select(models.Route).where(
            models.Route.employee_id == employee.id,
            models.Route.status == "pending"
        )).first()
        
        if active_route:
             return JSONResponse({"error": "Colaborador jÃƒÆ’Ã‚Â¡ possui uma rota ativa."}, status_code=400)
             
        new_route = models.Route(
            date=today_str,
            shift=routine.shift,
            employee_id=employee.id,
            client_id=payload.client_id,
            start_time=start_time,
            tonnage=payload.tonnage or 0.0,
            status="pending"
        )
        session.add(new_route)
        
        # Log event
        log = models.Event(
            type="routine_change",
            text=f"Rota MANUAL iniciada por lÃƒÆ’Ã‚Â­der({user['username']}) para {employee.name}",
            category="processo",
            sector="expedicao",
            impact="low",
            employee_id=employee.id
        )
        session.add(log)
        
        session.commit()
        
        return JSONResponse({"success": True})
    except Exception as e:
        logger.exception(f"Error starting manual route for emp {employee_id}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/admin/routes/{route_id}/delete", response_class=JSONResponse)
async def api_admin_delete_route(
    route_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    try:
        route = session.get(models.Route, route_id)
        if not route:
             return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
        
        session.delete(route)
        session.commit()
        return JSONResponse({"success": True})
    except Exception as e:
        logger.exception(f"Error deleting route {route_id} (admin): {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/admin/routes/{route_id}/update", response_class=JSONResponse)
async def api_admin_update_route(
    route_id: int,
    payload: MobileUpdatePayload,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    try:
        route = session.get(models.Route, route_id)
        if not route:
             return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
             
        if payload.client_id:
             client = session.get(models.Client, payload.client_id)
             if not client: return JSONResponse({"error": "Cliente invÃƒÆ’Ã‚Â¡lido"}, status_code=400)
             route.client_id = payload.client_id
             
        if payload.tonnage is not None:
             if payload.tonnage < 0: return JSONResponse({"error": "Peso deve ser positivo"}, status_code=400)
             route.tonnage = payload.tonnage
             
        session.add(route)
        session.commit()
        return JSONResponse({"success": True})
    except Exception as e:
        logger.exception(f"Error updating route {route_id} (admin): {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

class MobileAllocationItem(BaseModel):
    client_id: int
    weight: float

class MobileStartPayload(BaseModel):
    allocations: List[MobileAllocationItem]

@app.post("/mobile/routine/start_with_allocation", response_class=JSONResponse)
async def mobile_routine_start_with_allocation(
    request: Request,
    payload: MobileStartPayload,
    session: Session = Depends(get_session)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)

    employee = session.get(models.Employee, user_id)
    if not employee:
        return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    try:
        require_mobile_module(employee, "separation")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return JSONResponse({"detail": exc.detail}, status_code=403)
        raise
        
    # FORCE TIMEZONE to prevent UTC/Server mismatches
    br_tz = ZoneInfo("America/Sao_Paulo")
    now_br = datetime.now(br_tz)
    
    today_str = now_br.strftime("%Y-%m-%d")
    now_time = now_br.strftime("%H:%M")
    
    # 1. Start Routine (if not exists)
    stmt = select(models.EmployeeRoutine).where(
        models.EmployeeRoutine.employee_id == user_id,
        models.EmployeeRoutine.date == today_str
    )
    routine = session.exec(stmt).first()
    
    if not routine:
        routine = models.EmployeeRoutine(
            date=today_str,
            shift="ManhÃƒÆ’Ã‚Â£", # Placeholder
            employee_id=user_id,
            routine="present",
            start_time=now_time,
            status="open"
        )
        session.add(routine)
        session.commit()
    elif routine.status == "closed":
         # Auto-Reopen routine requested by user
         routine.status = "open"
         routine.end_time = None # Clear end time
         session.add(routine)
         session.commit()
         # return JSONResponse({"error": "Rotina jÃƒÆ’Ã‚Â¡ encerrada hoje."}, status_code=400) # Removed limitation
         
    # 2. Add Allocations
    for item in payload.allocations:
        # Allow checking in without weight (placeholder) or with weight
        route = models.Route(
            date=today_str,
            employee_id=user_id,
            client_id=item.client_id,
            tonnage=item.weight,
            start_time=now_time,
            status="pending" 
        )
        session.add(route)
            
    session.commit()
    
    return JSONResponse({"success": True})

# --- Helpers ---
def add_xp_transaction(session: Session, employee_id: int, points: float, type: str, reference_id: str = None, note: str = None):
    """Adds XP to ledger and updates employee total."""
    # 1. Create Ledger Entry
    ledger = models.XPLedger(
        employee_id=employee_id,
        transaction_type=type,
        points=points,
        reference_id=reference_id,
        note=note,
        created_at=datetime.now(ZoneInfo("America/Sao_Paulo"))
    )
    session.add(ledger)
    
    # 2. Update Employee Cache
    emp = session.get(models.Employee, employee_id)
    if emp:
        emp.total_xp += points
        session.add(emp)
    
    return ledger

# --- Mobile Routes ---
@app.post("/mobile/routine/start", response_class=RedirectResponse)
async def mobile_routine_start(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    user_id = user.get("id")
    employee = session.get(models.Employee, user_id)
    if not employee:
        return RedirectResponse(url="/mobile/login", status_code=303)
    try:
        require_mobile_module(employee, "separation")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return RedirectResponse(url="/mobile/dashboard?module=separation", status_code=303)
        raise
    
    br_tz = ZoneInfo("America/Sao_Paulo")
    now_br = datetime.now(br_tz)
    
    today_str = now_br.strftime("%Y-%m-%d")
    now_time = now_br.strftime("%H:%M")
    
    # Check if already exists
    stmt = select(models.EmployeeRoutine).where(
        models.EmployeeRoutine.employee_id == user_id,
        models.EmployeeRoutine.date == today_str
    )
    existing = session.exec(stmt).first()
    
    if existing:
        if existing.status == "closed":
            # LOCKED: Cannot re-open
            # TODO: Show error message nicely
            pass 
    else:
        # Create New
        # Determine shift based on time? For now placeholder
        current_shift = "ManhÃƒÆ’Ã‚Â£" 
        routine = models.EmployeeRoutine(
            date=today_str,
            shift=current_shift, # Placeholder
            employee_id=user_id,
            routine="present",
            start_time=now_time,
            status="open"
        )
        session.add(routine)
        session.commit()
    
    return RedirectResponse(url="/mobile/dashboard", status_code=303)

@app.post("/mobile/routine/stop", response_class=RedirectResponse)
async def mobile_routine_stop(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
         return RedirectResponse(url="/mobile/login", status_code=303)
         
    user_id = user.get("id")
    employee = session.get(models.Employee, user_id)
    if not employee:
        return RedirectResponse(url="/mobile/login", status_code=303)
    try:
        require_mobile_module(employee, "separation")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return RedirectResponse(url="/mobile/dashboard?module=separation", status_code=303)
        raise
    
    br_tz = ZoneInfo("America/Sao_Paulo")
    now_br = datetime.now(br_tz)
    
    today_str = now_br.strftime("%Y-%m-%d")
    now_time = now_br.strftime("%H:%M")

    # 1. Close Routine
    stmt = select(models.EmployeeRoutine).where(
        models.EmployeeRoutine.employee_id == user_id,
        models.EmployeeRoutine.date == today_str
    )
    routine = session.exec(stmt).first()
    
    if routine and routine.status != "closed":
        routine.end_time = now_time
        routine.status = "closed"
        session.add(routine)
    
    # 2. Force Close Pending Routes (Fail-safe as per user request to sync)
    # User said "must finish also on separacao page", which implies setting status=completed
    pending_routes = session.exec(
        select(models.Route).where(
            models.Route.employee_id == user_id,
            models.Route.date == today_str,
            models.Route.status == "pending"
        )
    ).all()
    
    for r in pending_routes:
        r.end_time = now_time
        r.status = "completed"
        session.add(r)
        
    session.commit()
    
    # Trigger XP calculation for today
    try:
        from gamification_engine import calculate_daily_xp
        calculate_daily_xp(session, today_str)
    except Exception as e:
        logger.error(f"Error calculating XP on routine end: {e}")
    
    # Redirect to Separacao as per last request? Or stay on Dashboard (which will likely redirect or show closed state)?
    # User: "Quando eu clicar encerrar o dia no botÃƒÆ’Ã‚Â£o deve se finalizar e encerrar tambem na pagina /separacao"
    # User previously said: "Quando confirmar tem que ir para /separacao" for START.
    # For STOP, usually they log out or see a summary.
    # I'll stick to redirecting to dashboard or login, but the DATA is synced.
    
    return RedirectResponse(url="/mobile/logout", status_code=303)
         
    tz = ZoneInfo("America/Sao_Paulo")
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    now_time = datetime.now(tz).strftime("%H:%M")
    
    stmt = select(models.EmployeeRoutine).where(
        models.EmployeeRoutine.employee_id == user_id,
        models.EmployeeRoutine.date == today_str
    )
    routine = session.exec(stmt).first()
    
    if routine and routine.status == "open":
        routine.end_time = now_time
        routine.status = "closed"
        session.add(routine)
        
        # --- Gamification: XP for Completing Day ---
        add_xp_transaction(
            session, 
            employee_id=user_id, 
            points=10.0, 
            type="SHIFT_CLOSED", 
            reference_id=f"shift_{routine.id}", 
            note="Rotina encerrada"
        )
        
        # --- Gamification: Check Production Record (Bonus) ---
        # 1. Calc Today's Production
        prod_stmt = select(func.sum(models.Route.tonnage)).where(
            models.Route.employee_id == user_id,
            models.Route.date == today_str
        )
        today_prod = session.exec(prod_stmt).one() or 0.0
        
        # 2. Check Threshold (Placeholder 5000kg)
        # TODO: Real logic for "Record"
        if today_prod > 5000:
             add_xp_transaction(
                session, 
                employee_id=user_id, 
                points=100.0, 
                type="RECORD_BONUS", 
                reference_id=f"shift_{routine.id}_bonus", 
                note=f"Superou 5000kg ({today_prod}kg)"
            )
            # Log Event
             event = models.Event(
                date=today_str,
                employee_id=user_id,
                event_type="conquista",
                description=f"Quebrou recorde diÃƒÆ’Ã‚Â¡rio: {today_prod}kg",
                severity="info"
            )
             session.add(event)
             
        session.commit()
        
        # Logout after stopping routine? Or just stay on dashboard locked?
        # User requested: "encerrar operaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o e travar"
        # Let's logout to be safe/clear
    return RedirectResponse(url="/mobile/dashboard", status_code=303)

# --- Admin Routes ---
@app.post("/admin/routine/reopen/{routine_id}", response_class=RedirectResponse)
async def admin_reopen_routine(
    request: Request,
    routine_id: int, 
    reason: str = Form(...),
    session: Session = Depends(get_session)
):
    user = require_login(request)
    # TODO: Verify if user is actually admin/manager logic (currently relying on simple require_login)
    
    routine = session.get(models.EmployeeRoutine, routine_id)
    if routine and routine.status == "closed":
        routine.status = "open"
        routine.end_time = None # Reset end time? Or keep history?
        # User requested: "reopened_by / reopened_reason / reopened_at"
        routine.reopened_by = actor_label
        routine.reopened_reason = reason
        routine.reopened_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
        
        session.add(routine)
        
        # Log Event
        session.add(models.Event(
            date=datetime.now().strftime("%Y-%m-%d"),
            employee_id=routine.employee_id,
            event_type="info",
            description=f"Rotina reaberta por {actor_label}: {reason}",
            severity="warning"
        ))
        session.commit()
    
    # Redirect back to Employee Detail
    return RedirectResponse(url=f"/employees/{routine.employee_id}", status_code=status.HTTP_303_SEE_OTHER)

# --- Checklist Operacional (Transpaleteira) ---
def apply_checklist_review(
    session: Session,
    checklist: models.TranspalletChecklist,
    reviewer: str,
    action: str,
    comment: Optional[str]
):
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    comment_text = (comment or "").strip()

    def reject_tx_missing_evidence(detail: str):
        if checklist.xp_transaction_id:
            tx = session.get(models.GameXPTransaction, checklist.xp_transaction_id)
            if tx and tx.status != "rejected":
                tx.status = "rejected"
                session.add(tx)
                session.commit()
        raise HTTPException(status_code=400, detail=detail)

    if action == "reject" and not comment_text:
        raise HTTPException(status_code=400, detail="ComentÃƒÆ’Ã‚Â¡rio obrigatÃƒÆ’Ã‚Â³rio para rejeiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o.")
    if action == "approve":
        if checklist.critical_flag and (not comment_text or not checklist.images):
            reject_tx_missing_evidence(
                "AprovaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o exige comentÃƒÆ’Ã‚Â¡rio e evidÃƒÆ’Ã‚Âªncia para itens crÃƒÆ’Ã‚Â­ticos. TransaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o XP rejeitada por falta de evidÃƒÆ’Ã‚Âªncia."
            )
        if checklist.nonconforming_keys and not comment_text:
            reject_tx_missing_evidence(
                "ComentÃƒÆ’Ã‚Â¡rio obrigatÃƒÆ’Ã‚Â³rio quando houver nÃƒÆ’Ã‚Â£o conformidades. TransaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o XP rejeitada por falta de evidÃƒÆ’Ã‚Âªncia."
            )

    if action == "review":
        checklist.status = "reviewed"
    elif action == "approve":
        checklist.status = "approved"
    elif action == "reject":
        checklist.status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="AÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o invÃƒÆ’Ã‚Â¡lida.")

    checklist.reviewed_by = reviewer
    checklist.reviewed_at = now
    if comment_text:
        checklist.review_comment = comment_text

    if checklist.xp_transaction_id:
        tx = session.get(models.GameXPTransaction, checklist.xp_transaction_id)
        if tx:
            if action == "approve" and tx.status != "confirmed":
                tx.status = "confirmed"
                tx.confirmed_at = now
                tx.manager_id = reviewer
                emp = session.get(models.Employee, checklist.employee_id)
                if emp:
                    emp.total_xp += tx.amount
                    session.add(emp)
                session.add(tx)
            if action == "reject" and tx.status != "rejected":
                tx.status = "rejected"
                session.add(tx)

    session.add(checklist)


@app.get("/mobile/routine/history", response_class=HTMLResponse)
async def mobile_checklist_history(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
    employee_id = user.get("id")
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    # Fetch History (Last 30 days)
    history_start = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=30)).strftime("%Y-%m-%d")
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    # Checklists com problemas (critical_flag ou nonconforming_keys)
    checklists = session.exec(
        select(models.TranspalletChecklist)
        .where(models.TranspalletChecklist.employee_id == employee_id)
        .where(models.TranspalletChecklist.date >= history_start)
        .order_by(models.TranspalletChecklist.submitted_at.desc())
    ).all()
    
    # Filtrar apenas checklists com problemas
    checklists_with_issues = [c for c in checklists if c.critical_flag or c.nonconforming_keys]
    
    history_view = []
    for c in checklists_with_issues:
        is_fail = c.critical_flag or c.nonconforming_keys
        history_view.append({
            "equipment_code": c.equipment_code,
            "submitted_at_date": c.submitted_at.strftime("%d/%m") if c.submitted_at else "-",
            "submitted_at_time": c.submitted_at.strftime("%H:%M") if c.submitted_at else "-",
            "status_dot": "bg-red-500",
            "status_badge_class": "bg-red-500/10 text-red-400 border border-red-500/20",
            "status_label": "Com Problemas",
            "original": c,
            "type": "checklist"
        })
    
    # Buscar chamados abertos do colaborador (ÃƒÆ’Ã‚Âºltimos 30 dias)
    three_days_ago = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=30)
    open_tickets = session.exec(
        select(models.EquipmentTicket)
        .where(models.EquipmentTicket.employee_id == employee_id)
        .where(models.EquipmentTicket.status == "open")
        .where(models.EquipmentTicket.created_at >= three_days_ago)
        .order_by(models.EquipmentTicket.created_at.desc())
    ).all()
    
    # Adicionar chamados abertos ao histÃƒÆ’Ã‚Â³rico
    for ticket in open_tickets:
        history_view.append({
            "equipment_code": ticket.equipment_code,
            "submitted_at_date": ticket.created_at.strftime("%d/%m") if ticket.created_at else "-",
            "submitted_at_time": ticket.created_at.strftime("%H:%M") if ticket.created_at else "-",
            "status_dot": "bg-amber-500",
            "status_badge_class": "bg-amber-500/10 text-amber-400 border border-amber-500/20",
            "status_label": "Chamado Aberto",
            "ticket_id": ticket.id,
            "description": ticket.description[:50] + "..." if len(ticket.description) > 50 else ticket.description,
            "type": "ticket"
        })
    
    # Ordenar por data (mais recente primeiro)
    history_view.sort(key=lambda x: x.get("submitted_at_date", "") + " " + x.get("submitted_at_time", ""), reverse=True)
        
    return templates.TemplateResponse("mobile/routine_history.html", {
        "request": request,
        "employee": employee,
        "history_checklists": history_view
    })

@app.get("/mobile/routine/checklist", response_class=HTMLResponse)
async def mobile_checklist_page(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)

    employee_id = user.get("id")
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/mobile/login", status_code=303)
    try:
        require_mobile_module(employee, "checklist")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return RedirectResponse(url="/mobile/dashboard?module=checklist", status_code=303)
        raise

    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    # 1. Checklists do Dia (Mantido)
    checklists = session.exec(
        select(models.TranspalletChecklist)
        .where(models.TranspalletChecklist.employee_id == employee_id)
        .where(models.TranspalletChecklist.date == today)
        .order_by(models.TranspalletChecklist.submitted_at.desc())
    ).all()
    
    # helper for PT-BR date
    def fmt_br(dt_obj):
        if not dt_obj: return "-"
        if isinstance(dt_obj, str): return dt_obj # fallback
        return dt_obj.strftime("%d/%m/%Y %H:%M")

    checklists_view = []
    for c in checklists:
        checklists_view.append({
            "equipment_code": c.equipment_code,
            "submitted_at_fmt": c.submitted_at.strftime("%H:%M") if c.submitted_at else "-",
            "status_class": "bg-red-500/10 text-red-400" if (c.critical_flag or c.nonconforming_keys) else "bg-emerald-500/10 text-emerald-400",
            "status_label": "Falha" if c.critical_flag else ("AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o" if c.nonconforming_keys else "OK"),
            "original": c
        })

    # 4. Alertas de Dias Pendentes (Missing Days)
    # Regra: Work Days - Absences - Done Days
    missing_days = []
    
    # Janela de anÃƒÆ’Ã‚Â¡lise: ÃƒÆ’Ã…Â¡ltimos 14 dias atÃƒÆ’Ã‚Â© ontem
    analysis_end = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)).date()
    analysis_start = analysis_end - timedelta(days=13) # 14 dias total
    
    # Buscar Checklists feitos no perÃƒÆ’Ã‚Â­odo (extrair valores: Row/tuple usa r[0], escalar usa r)
    rows_raw = session.exec(
        select(models.TranspalletChecklist.date)
        .where(models.TranspalletChecklist.employee_id == employee_id)
        .where(models.TranspalletChecklist.date >= analysis_start.strftime("%Y-%m-%d"))
        .where(models.TranspalletChecklist.date <= analysis_end.strftime("%Y-%m-%d"))
    ).all()
    done_dates = set()
    for r in rows_raw:
        val = r[0] if hasattr(r, "__getitem__") and not isinstance(r, str) else r
        if val is not None:
            done_dates.add(str(val))
    
    # Buscar AusÃƒÆ’Ã‚Âªncias (EmployeeRoutine != present)
    absences = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.employee_id == employee_id)
        .where(models.EmployeeRoutine.date >= analysis_start.strftime("%Y-%m-%d"))
        .where(models.EmployeeRoutine.date <= analysis_end.strftime("%Y-%m-%d"))
        .where(models.EmployeeRoutine.routine != "present")
    ).all()
    absence_map = {a.date: a.routine for a in absences} # data str -> motivo

    # Parse Work Days
    import json
    work_days_list = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    try:
        if employee.work_days:
            work_days_list = json.loads(employee.work_days)
    except: pass
    
    current_d = analysis_start
    while current_d <= analysis_end:
        d_str = current_d.strftime("%Y-%m-%d")
        week_day_name = current_d.strftime("%A") # English names matches default list
        
        # Se for dia de trabalho...
        if week_day_name in work_days_list:
            # E nÃƒÆ’Ã‚Â£o tiver ausÃƒÆ’Ã‚Âªncia registrada...
            if d_str not in absence_map:
                # E nÃƒÆ’Ã‚Â£o tiver checklist feito...
                if d_str not in done_dates:
                    # ENTÃƒÆ’Ã†â€™O ÃƒÆ’Ã‚Â© pendente
                    missing_days.append({
                        "date": current_d.strftime("%d/%m"),
                        "full_date": d_str,
                        "weekday": week_day_name
                    })
        
        current_d += timedelta(days=1)
    
    # Ordenar decrescente (mais recente primeiro)
    missing_days.sort(key=lambda x: x["full_date"], reverse=True)

    # Weekday Translation
    weekday_map = {
        "Monday": "Segunda-feira",
        "Tuesday": "TerÃƒÆ’Ã‚Â§a-feira",
        "Wednesday": "Quarta-feira",
        "Thursday": "Quinta-feira",
        "Friday": "Sexta-feira",
        "Saturday": "SÃƒÆ’Ã‚Â¡bado",
        "Sunday": "Domingo"
    }

    # Format missing days
    missing_days_view = []
    for idx, day in enumerate(missing_days):
        # day has {date: "dd/mm", full_date: "YYYY-MM-DD", weekday: "Monday"}
        pt_weekday = weekday_map.get(day["weekday"], day["weekday"])
        missing_days_view.append({
            "date_fmt": day["date"],
            "full_date": day["full_date"],
            "weekday_pt": pt_weekday
        })
    
    # 5. Lista de caminhÃƒÆ’Ã‚Âµes (sÃƒÆ’Ã‚Â³ veÃƒÆ’Ã‚Â­culos tipo caminhÃƒÆ’Ã‚Â£o) para o select + ÃƒÆ’Ã‚Âºltimo KM
    equipment_list = []
    try:
        trucks = session.exec(
            select(models.Vehicle)
            .where(models.Vehicle.vehicle_type == "caminhao")
            .where(models.Vehicle.is_active == True)
            .order_by(models.Vehicle.placa)
        ).all()
        for v in trucks:
            # Preferir KM do veÃƒÆ’Ã‚Â­culo (atualizado por checklist/ediÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o); senÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Âºltimo checklist
            last_km = getattr(v, "odometer_km", None)
            if last_km is None:
                last_check = session.exec(
                    select(models.TranspalletChecklist)
                    .where(models.TranspalletChecklist.equipment_code == v.placa)
                    .order_by(desc(models.TranspalletChecklist.date), desc(models.TranspalletChecklist.submitted_at))
                ).first()
                last_km = last_check.odometer_km if last_check and last_check.odometer_km is not None else None
            marca = getattr(v, "marca", "") or ""
            modelo = getattr(v, "modelo", "") or ""
            equipment_list.append({
                "code": v.placa,
                "label": f"{v.placa} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {marca} {modelo}".strip() or v.placa,
                "last_km": last_km
            })
    except Exception as eq_err:
        logger.warning(f"mobile_checklist: erro ao carregar veÃƒÆ’Ã‚Â­culos: {eq_err}")

    equipment_last_km = {eq["code"]: eq["last_km"] for eq in equipment_list if eq.get("last_km") is not None}

    return templates.TemplateResponse(
        "mobile/routine_checklist.html",
        {
            "equipment_list": equipment_list,
            "equipment_last_km": equipment_last_km,
            "request": request,
            "employee": employee,
            "items": CHECKLIST_ITEMS,
            "today": today,
            "checklists": checklists_view,
            "missing_days": missing_days_view
        }
    )

@app.get("/mobile/equipment/tickets", response_class=HTMLResponse)
async def mobile_tickets_list(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
    employee = session.get(models.Employee, user.get("id"))
    try:
        require_mobile_module(employee, "checklist")
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            return RedirectResponse(url="/mobile/dashboard?module=checklist", status_code=303)
        raise

    # Buscar todos os tickets do colaborador
    all_tickets = session.exec(
        select(models.EquipmentTicket)
        .where(models.EquipmentTicket.employee_id == employee.id)
        .order_by(desc(models.EquipmentTicket.created_at))
        .limit(100)
    ).all()
    
    # Separar por status
    open_tickets = [t for t in all_tickets if t.status == "open"]
    closed_tickets = [t for t in all_tickets if t.status != "open"]
    
    # EstatÃƒÆ’Ã‚Â­sticas
    total_tickets = len(all_tickets)
    open_count = len(open_tickets)
    closed_count = len(closed_tickets)
    high_severity_count = len([t for t in all_tickets if t.severity == "high"])
    
    # Tickets recentes (ÃƒÆ’Ã‚Âºltimos 7 dias)
    seven_days_ago = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=7)
    # Converter para naive datetime para comparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o (created_at geralmente ÃƒÆ’Ã‚Â© naive no banco)
    seven_days_ago_naive = seven_days_ago.replace(tzinfo=None)
    recent_tickets = []
    for t in all_tickets:
        if t.created_at:
            # Normalizar created_at para naive se necessÃƒÆ’Ã‚Â¡rio
            ticket_date = t.created_at.replace(tzinfo=None) if t.created_at.tzinfo else t.created_at
            if ticket_date >= seven_days_ago_naive:
                recent_tickets.append(t)
    
    # Tickets por equipamento (agrupar)
    tickets_by_equipment = {}
    for ticket in all_tickets:
        if ticket.equipment_code not in tickets_by_equipment:
            tickets_by_equipment[ticket.equipment_code] = []
        tickets_by_equipment[ticket.equipment_code].append(ticket)

    return templates.TemplateResponse("mobile/tickets_list.html", {
        "request": request, 
        "tickets": all_tickets,  # Mantido para compatibilidade
        "all_tickets": all_tickets,
        "open_tickets": open_tickets,
        "closed_tickets": closed_tickets,
        "employee": employee,
        "stats": {
            "total": total_tickets,
            "open": open_count,
            "closed": closed_count,
            "high_severity": high_severity_count,
            "recent": len(recent_tickets)
        },
        "tickets_by_equipment": tickets_by_equipment
    })

@app.get("/mobile/equipment/tickets/new", response_class=HTMLResponse)
async def mobile_ticket_new(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
    
    employee_id = user.get("id")
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/mobile/login", status_code=303)
    
    equipment_list = session.exec(
        select(models.TranspalletEquipment).order_by(models.TranspalletEquipment.code)
    ).all()
    
    # Buscar chamados abertos dos ÃƒÆ’Ã‚Âºltimos 3 dias
    three_days_ago = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=3)
    open_tickets = session.exec(
        select(models.EquipmentTicket, models.Employee)
        .join(models.Employee, models.EquipmentTicket.employee_id == models.Employee.id)
        .where(models.EquipmentTicket.status == "open")
        .where(models.EquipmentTicket.created_at >= three_days_ago)
        .order_by(models.EquipmentTicket.created_at.desc())
    ).all()
    
    open_tickets_list = []
    for ticket, emp in open_tickets:
        open_tickets_list.append({
            "id": ticket.id,
            "equipment_code": ticket.equipment_code,
            "employee_name": emp.name,
            "created_at": ticket.created_at.strftime("%d/%m/%Y %H:%M"),
            "description": ticket.description[:50] + "..." if len(ticket.description) > 50 else ticket.description
        })
    
    return templates.TemplateResponse(
        "mobile/equipment_ticket_new.html",
        {
            "request": request,
            "employee": employee,
            "equipment_list": equipment_list,
            "open_tickets": open_tickets_list
        }
    )

@app.get("/mobile/equipment/tickets/{ticket_id}", response_class=HTMLResponse)
async def mobile_ticket_detail(request: Request, ticket_id: int, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
    
    employee = session.get(models.Employee, user.get("id"))
    if not employee:
        return RedirectResponse(url="/mobile/login", status_code=303)
    
    ticket = session.get(models.EquipmentTicket, ticket_id)
    if not ticket:
        return HTMLResponse("Chamado nÃƒÆ’Ã‚Â£o encontrado", status_code=404)
    
    # Verificar se o ticket pertence ao colaborador ou se ÃƒÆ’Ã‚Â© admin
    if ticket.employee_id != employee.id:
        return HTMLResponse("Acesso negado", status_code=403)
    
    images = [f"/static/uploads/tickets/{img}" for img in (ticket.images or [])]
    
    return templates.TemplateResponse("mobile/tickets_detail.html", {
        "request": request,
        "ticket": ticket,
        "images": images
    })

@app.post("/mobile/equipment/tickets", response_class=JSONResponse)
async def mobile_ticket_create(
    request: Request,
    equipment_code: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    priority: str = Form("medium"),
    files: List[UploadFile] = File([]),
    session: Session = Depends(get_session)
):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
    
    employee_id = user.get("id")
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
    
    equipment_code = equipment_code.strip().upper()
    images = []
    if files:
        images = await save_ticket_images(files)
    
    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    actor_label = format_user_label(user)
    actor_label = format_user_label(user)
    
    ticket = models.EquipmentTicket(
        employee_id=employee_id,
        equipment_code=equipment_code,
        title=title.strip(),
        description=description.strip(),
        priority=priority,
        status="open",
        images=images,
        created_at=now_br
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    
    # Enviar e-mail
    try:
        recipient_emails = get_maintenance_recipient_emails(session)
        
        if recipient_emails:
            ticket_link = f"{APP_BASE_URL}/admin/equipment/tickets/{ticket.id}" if APP_BASE_URL else f"/admin/equipment/tickets/{ticket.id}"
            priority_labels = {"low": "Baixa", "medium": "MÃƒÆ’Ã‚Â©dia", "high": "Alta", "critical": "CrÃƒÆ’Ã‚Â­tica"}
            date_br = now_br.strftime('%d/%m/%Y')
            
            subject = f"ManutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o Equipamento {equipment_code} - {date_br}"
            body_lines = [
                "OlÃƒÆ’Ã‚Â¡! Espero que se encontrem bem.",
                "",
                f"Segue para manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o o equipamento {equipment_code}.",
                "",
                f"Operador: {employee.name} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â MatrÃƒÆ’Ã‚Â­cula: {employee.registration_id or '-'}",
                f"Data/Hora: {now_br.strftime('%d/%m/%Y %H:%M')}",
                f"Prioridade: {priority_labels.get(priority, priority)}",
                "",
                "DescriÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o do problema:",
                description,
                "",
                "Atenciosamente,",
                "Sistema de OperaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o Inteligente"
            ]
            if images:
                image_list = [f"/static/uploads/tickets/{img}" for img in images]
                body_lines.insert(-3, "")
                body_lines.insert(-3, f"Imagens anexadas: {len(images)}")
            
            body = "\n".join(body_lines)
            report_data = {
                "subject": subject,
                "body": body,
                "image_list": [f"/static/uploads/tickets/{img}" for img in images] if images else []
            }
            sent, error = send_maintenance_email(report_data, recipient_emails)
            if sent:
                ticket.email_sent_at = now_br
            else:
                ticket.email_error = error or "Falha ao enviar e-mail"
        else:
            ticket.email_error = "Nenhum destinatÃƒÆ’Ã‚Â¡rio configurado"
    except Exception as exc:
        ticket.email_error = str(exc)
        logger.exception(f"Erro ao enviar e-mail de ticket {ticket.id}")
    
    session.add(ticket)
    session.commit()
    
    return {"success": True, "id": ticket.id}


@app.get("/admin/routine/checklists/dashboard", response_class=HTMLResponse)
async def admin_checklists_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    days_param = request.query_params.get("days", "30")
    period_days = parse_int_env(days_param, 30)
    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    start_date = now_br - timedelta(days=period_days)

    # CHECKLISTS DATA
    checklist_query = (
        select(models.TranspalletChecklist)
        .where(models.TranspalletChecklist.submitted_at >= start_date)
        .order_by(desc(models.TranspalletChecklist.submitted_at))
    )
    checklists = session.exec(checklist_query).all()

    total_count = len(checklists)
    critical_count = sum(1 for c in checklists if c.critical_flag)
    nonconforming_count = sum(1 for c in checklists if c.nonconforming_keys)

    shift_counts = session.exec(
        select(models.TranspalletChecklist.shift, func.count())
        .where(models.TranspalletChecklist.submitted_at >= start_date)
        .group_by(models.TranspalletChecklist.shift)
    ).all()
    # Agrupar por turno normalizado para evitar duplicatas (ex.: ManhÃƒÆ’Ã‚Â£ vs Manh? por encoding)
    by_norm = {}
    for shift, count in shift_counts:
        norm = normalize_shift(shift)
        by_norm[norm] = by_norm.get(norm, 0) + count
    shift_stats = []
    for norm, count in sorted(by_norm.items(), key=lambda x: x[1], reverse=True):
        pct = round((count / total_count) * 100, 1) if total_count else 0
        shift_stats.append({"shift": shift_display_label(norm), "count": count, "percent": pct})

    item_counter = Counter()
    for checklist in checklists:
        for key in (checklist.nonconforming_keys or []):
            item_counter[key] += 1
    label_map = checklist_item_label_map()
    top_items = [
        {
            "key": key,
            "label": label_map.get(key, key),
            "count": count,
            "critical": key in CHECKLIST_CRITICAL_KEYS
        }
        for key, count in item_counter.most_common(10)
    ]

    equipment_counter = Counter()
    for checklist in checklists:
        if checklist.nonconforming_keys:
            equipment_counter[checklist.equipment_code] += 1
    top_equipment = [
        {"equipment_code": code, "count": count}
        for code, count in equipment_counter.most_common(10)
    ]

    # TICKETS DATA (Stats)
    ticket_query = (
        select(models.EquipmentTicket)
        .where(models.EquipmentTicket.created_at >= start_date)
    )
    tickets = session.exec(ticket_query).all()
    
    ticket_stats = {
        "total": len(tickets),
        "open": sum(1 for t in tickets if t.status == "open"),
        "high": sum(1 for t in tickets if t.severity == "high"),
        "avg_resolution": 0 # Logic removed/Mocked
    }
    
    # Ticket top equipment
    t_eq_counter = Counter([t.equipment_code for t in tickets])
    ticket_top_eq = [{"code": k, "count": v} for k,v in t_eq_counter.most_common(10)]

    # Drill-down URLs
    # Dates are handled by period_days in list view (we will add support)
    card_urls = {
        "total": f"/admin/routine/checklists?period_days={period_days}",
        "nonconforming": f"/admin/routine/checklists?period_days={period_days}&nonconforming=1",
        "critical": f"/admin/routine/checklists?period_days={period_days}&critical=1",
        "tickets_total": f"/admin/equipment/tickets?days={period_days}",
        "tickets_open": f"/admin/equipment/tickets?days={period_days}&status=open",
        "tickets_high": f"/admin/equipment/tickets?days={period_days}&severity=high&status=open",
    }

    # Chamados abertos (checklists crÃƒÆ’Ã‚Â­ticos pendentes)
    open_calls_query = (
        select(models.TranspalletChecklist, models.Employee)
        .join(models.Employee, models.Employee.id == models.TranspalletChecklist.employee_id)
        .where(models.TranspalletChecklist.critical_flag == True)
        .where(models.TranspalletChecklist.status.in_(["submitted", "reviewed"]))
        .order_by(desc(models.TranspalletChecklist.submitted_at))
        .limit(10)
    )
    open_calls_rows = session.exec(open_calls_query).all()
    open_calls = []
    label_map = checklist_item_label_map()
    for checklist, employee in open_calls_rows:
        blocked_items = ", ".join([label_map.get(k, k) for k in (checklist.nonconforming_keys or [])])
        open_calls.append({
            "checklist_id": checklist.id,
            "equipment_code": checklist.equipment_code,
            "employee_name": employee.name,
            "date_br": fmt_ddmmyyyy(checklist.date),
            "blocked_items": blocked_items
        })

    return templates.TemplateResponse(
        "admin_routine_checklists_dashboard.html",
        {
            "request": request,
            "period_days": period_days,
            "total_count": total_count,
            "critical_count": critical_count,
            "nonconforming_count": nonconforming_count,
            "avg_resolution_hours": None,
            "shift_stats": shift_stats,
            "top_items": top_items,
            "top_equipment": top_equipment,
            "ticket_stats": ticket_stats,
            "ticket_top_eq": ticket_top_eq,
            "card_urls": card_urls,
            "open_calls": open_calls
        }
    )

@app.get("/admin/equipment/tickets", response_class=HTMLResponse)
async def admin_equipment_tickets(
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    message = request.query_params.get("message")
    level = request.query_params.get("level", "success")
    ticket_status_filter = request.query_params.get("status") or ""
    severity_filter = request.query_params.get("severity") or ""
    equipment_filter = request.query_params.get("equipment") or ""

    query = (
        select(models.EquipmentTicket, models.Employee)
        .join(models.Employee, models.Employee.id == models.EquipmentTicket.employee_id)
        .order_by(models.EquipmentTicket.created_at.desc())
    )
    if ticket_status_filter:
        query = query.where(models.EquipmentTicket.status == ticket_status_filter)
    if severity_filter:
        query = query.where(models.EquipmentTicket.severity == severity_filter)
    if equipment_filter:
        query = query.where(models.EquipmentTicket.equipment_code.ilike(f"%{equipment_filter}%"))

    rows = session.exec(query).all()
    tickets = []
    for ticket, employee in rows:
        imgs = ticket.images or []
        if not isinstance(imgs, list):
            imgs = [] # Defensive: ignore malformed json
        image_urls = [f"/static/uploads/tickets/{img}" for img in imgs]
        
        # Defensive datetime
        created_at_br = "-"
        if ticket.created_at:
            created_at_br = fmt_datetime_br(ticket.created_at)

        tickets.append({
            "ticket": ticket,
            "employee": employee,
            "created_at_br": created_at_br,
            "image_urls": image_urls
        })
    
    # KPI Stats
    total_count = len(tickets)
    open_count = len([t for t in tickets if t["ticket"].status == "open"])
    high_count = len([t for t in tickets if t["ticket"].severity == "high" and t["ticket"].status == "open"])
    
    now_7d = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=7)
    # Fix TZ: Make comparison robust (ignoring TZ for count or ensuring both aligned)
    # Simplify: convert both to naive or aware.
    now_7d_naive = now_7d.replace(tzinfo=None)
    
    recent_count = 0
    for t in tickets:
        dt = t["ticket"].created_at
        if dt:
            # If naive, compare with naive. If aware, compare with aware?
            # Safest is to strip TZ for this "recent" check as 7 days is rough.
            dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
            if dt_naive >= now_7d_naive:
                recent_count += 1

    return templates.TemplateResponse(
        "admin_equipment_tickets.html",
        {
            "request": request,
            "message": message,
            "level": level,
            "tickets": tickets,
            "stats": {
                "total": total_count,
                "open": open_count,
                "high": high_count,
                "recent": recent_count
            },
            "filters": {
                "status": ticket_status_filter,
                "severity": severity_filter,
                "equipment": equipment_filter
            }
        }
    )

@app.post("/admin/equipment/tickets/{ticket_id}/close", response_class=RedirectResponse)
async def admin_equipment_ticket_close(
    request: Request,
    ticket_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    ticket = session.get(models.EquipmentTicket, ticket_id)
    if not ticket:
        query = urlencode({"message": "Chamado nÃƒÆ’Ã‚Â£o encontrado.", "level": "error"})
        return RedirectResponse(url=f"/admin/equipment/tickets?{query}", status_code=status.HTTP_303_SEE_OTHER)
    if ticket.status == "closed":
        query = urlencode({"message": "Chamado jÃƒÆ’Ã‚Â¡ encerrado.", "level": "error"})
        return RedirectResponse(url=f"/admin/equipment/tickets?{query}", status_code=status.HTTP_303_SEE_OTHER)

    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    ticket.status = "closed"
    ticket.closed_at = now_br
    actor_label = format_user_label(user)
    ticket.closed_by = actor_label
    session.add(ticket)
    session.add(models.Event(
        timestamp=now_br,
        text=f"Chamado #{ticket.id} encerrado por {actor_label}.",
        type="ticket_close",
        category="processo",
        sector=ticket.equipment_code,
        impact="low",
        reference_type="ticket",
        reference_id=ticket.id,
        employee_id=ticket.employee_id
    ))
    session.commit()
    query = urlencode({"message": "Chamado encerrado.", "level": "success"})
    return RedirectResponse(url=f"/admin/equipment/tickets?{query}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/routine/checklists/settings", response_class=HTMLResponse)
async def admin_checklists_settings(
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    message = request.query_params.get("message")
    level = request.query_params.get("level", "success")
    equipment_list = session.exec(
        select(models.TranspalletEquipment).order_by(models.TranspalletEquipment.code)
    ).all()

    return templates.TemplateResponse(
        "admin_routine_checklists_settings.html",
        {
            "request": request,
            "message": message,
            "level": level,
            "equipment_list": equipment_list
        }
    )

@app.post("/admin/routine/checklists/settings/emails", response_class=RedirectResponse)
async def admin_checklists_add_email(
    request: Request,
    email: str = Form(...),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    email_norm = normalize_email(email)
    if not email_norm or "@" not in email_norm:
        return admin_checklists_settings_redirect("E-mail invÃƒÆ’Ã‚Â¡lido.", "error")

    existing = session.exec(
        select(models.ChecklistEmailRecipient)
        .where(models.ChecklistEmailRecipient.email == email_norm)
    ).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            session.add(existing)
            session.commit()
        return admin_checklists_settings_redirect("E-mail reativado.", "success")

    recipient = models.ChecklistEmailRecipient(email=email_norm, is_active=True)
    session.add(recipient)
    session.commit()
    return admin_checklists_settings_redirect("E-mail cadastrado com sucesso.", "success")

@app.post("/admin/routine/checklists/settings/emails/{recipient_id}/delete", response_class=RedirectResponse)
async def admin_checklists_remove_email(
    request: Request,
    recipient_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    recipient = session.get(models.AbsenceAlertRecipient, recipient_id)
    if not recipient:
        return admin_checklists_settings_redirect("E-mail nÃƒÆ’Ã‚Â£o encontrado.", "error")
    if recipient.is_active:
        recipient.is_active = False
        session.add(recipient)
        session.commit()
    return admin_checklists_settings_redirect("E-mail removido.", "success")

@app.post("/admin/routine/checklists/settings/equipment", response_class=RedirectResponse)
async def admin_checklists_add_equipment(
    request: Request,
    code: str = Form(...),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    code_norm = (code or "").strip()
    if not code_norm:
        return admin_checklists_settings_redirect("Informe o cÃƒÆ’Ã‚Â³digo do equipamento.", "error")

    existing = session.exec(
        select(models.TranspalletEquipment)
        .where(models.TranspalletEquipment.code == code_norm)
    ).first()
    if existing:
        return admin_checklists_settings_redirect("Equipamento jÃƒÆ’Ã‚Â¡ cadastrado.", "error")

    equipment = models.TranspalletEquipment(code=code_norm, status="available")
    session.add(equipment)
    session.commit()
    return admin_checklists_settings_redirect("Equipamento cadastrado com sucesso.", "success")

@app.post("/admin/routine/checklists/settings/equipment/{equipment_id}/delete", response_class=RedirectResponse)
async def admin_checklists_remove_equipment(
    request: Request,
    equipment_id: int,
    force_delete: Optional[str] = Form(None),
    comment: str = Form(""),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    equipment = session.get(models.TranspalletEquipment, equipment_id)
    if not equipment:
        return admin_checklists_settings_redirect("Equipamento nÃƒÆ’Ã‚Â£o encontrado.", "error")
    if equipment.status == "blocked":
        if force_delete != "true":
            reason = equipment.blocked_reason or "Equipamento bloqueado."
            if equipment.last_checklist_id:
                reason = f"{reason} (Checklist #{equipment.last_checklist_id})"
            return admin_checklists_settings_redirect(
                f"Equipamento bloqueado nÃƒÆ’Ã‚Â£o pode ser removido. {reason}",
                "error"
            )
        comment = (comment or "").strip()
        if not comment:
            return admin_checklists_settings_redirect(
                "ComentÃƒÆ’Ã‚Â¡rio obrigatÃƒÆ’Ã‚Â³rio para forÃƒÆ’Ã‚Â§ar remoÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de equipamento bloqueado.",
                "error"
            )

    usage_count = session.exec(
        select(func.count(models.TranspalletChecklist.id))
        .where(models.TranspalletChecklist.equipment_code == equipment.code)
    ).one() or 0
    if usage_count and equipment.status != "blocked":
        return admin_checklists_settings_redirect(
            "Equipamento com checklists registrados nÃƒÆ’Ã‚Â£o pode ser removido.",
            "error"
        )

    if equipment.status == "blocked" and force_delete == "true":
        session.add(models.Event(
            timestamp=datetime.now(ZoneInfo("America/Sao_Paulo")),
            text=f"Equipamento {equipment.code} removido ÃƒÆ’Ã‚Â  forÃƒÆ’Ã‚Â§a. Motivo: {comment}",
            type="equipment_force_remove",
            category="infraestrutura",
            sector=equipment.code,
            impact="high",
            reference_type="equipment",
            reference_id=equipment.id
        ))
    session.delete(equipment)
    session.commit()
    if equipment.status == "blocked" and force_delete == "true":
        return admin_checklists_settings_redirect("Equipamento bloqueado removido com sucesso.", "success")
    return admin_checklists_settings_redirect("Equipamento removido.", "success")

@app.get("/admin/routine/checklists", response_class=HTMLResponse)
async def admin_checklists_page(
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    date_filter = request.query_params.get("date")
    status_filter = request.query_params.get("status")
    equipment_filter = request.query_params.get("equipment")
    employee_filter = request.query_params.get("employee_id")
    
    # New filters for drill-down
    period_days_param = request.query_params.get("period_days")
    nonconforming_param = request.query_params.get("nonconforming")
    critical_param = request.query_params.get("critical")
    item_key_param = request.query_params.get("item_key")
    
    employee_filter_id = None
    if employee_filter:
        try:
            employee_filter_id = int(employee_filter)
        except:
            employee_filter_id = None

    query = (
        select(models.TranspalletChecklist, models.Employee)
        .join(models.Employee, models.Employee.id == models.TranspalletChecklist.employee_id)
        .order_by(models.TranspalletChecklist.submitted_at.desc())
    )
    
    # Priority: Specific date > Period
    if date_filter:
        query = query.where(models.TranspalletChecklist.date == date_filter)
    elif period_days_param:
        try:
            days = int(period_days_param)
            start_d = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=days)
            query = query.where(models.TranspalletChecklist.submitted_at >= start_d)
        except: pass
        
    if status_filter:
        query = query.where(models.TranspalletChecklist.status == status_filter)
    if equipment_filter:
        query = query.where(models.TranspalletChecklist.equipment_code.ilike(f"%{equipment_filter}%"))
    if employee_filter_id:
        query = query.where(models.TranspalletChecklist.employee_id == employee_filter_id)
        
    # Drill-down logic
    # Filter in python or SQL? SQL is better but nonconforming_keys is JSON/Column.
    # Check model definition. If it's JSON, SQL filtering depends on DB.
    # We will filter in Python if needed, but SQLModel check is safer if supported.
    # For now, let's filter in Python for complex JSON checks if we can't trust SQL support.
    # BUT fetching all and filtering is slow.
    # If `nonconforming_keys` is not None/empty.
    # query = query.where(models.TranspalletChecklist.nonconforming_keys != None) # might not work on all DBs
    
    # Let's fetch and filter in python for these specific drill-downs as dataset is small enough (<10k?). 
    # Or apply simple SQL checks.
    
    rows = session.exec(query).all()
    
    # APPLY PYTHON FILTERS (Drill-down)
    filtered_rows = []
    for checklist, employee in rows:
        include = True
        
        if nonconforming_param == "1":
            if not checklist.nonconforming_keys:
                include = False
                
        if critical_param == "1":
            if not checklist.critical_flag:
                include = False
        
        if item_key_param:
            if item_key_param not in (checklist.nonconforming_keys or []):
                include = False

        if include:
            filtered_rows.append((checklist, employee))
            
    rows = filtered_rows

    equipment_codes = {c.equipment_code for c, _ in rows}
    equipment_map = {}
    if equipment_codes:
        equipment_rows = session.exec(
            select(models.TranspalletEquipment).where(models.TranspalletEquipment.code.in_(equipment_codes))
        ).all()
        equipment_map = {e.code: e for e in equipment_rows}

    status_labels = {
        "submitted": "Enviado",
        "reviewed": "Em revisÃƒÆ’Ã‚Â£o",
        "approved": "Aprovado",
        "rejected": "Rejeitado"
    }
    equipment_labels = {
        "blocked": "Bloqueado",
        "available": "DisponÃƒÆ’Ã‚Â­vel"
    }

    checklist_rows = []
    summary = {
        "total": 0,
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "blocked": 0,
        "nonconforming": 0
    }
    for checklist, employee in rows:
        equipment = equipment_map.get(checklist.equipment_code)
        status_value = checklist.status or "submitted"
        equipment_status = equipment.status if equipment else "available"
        nonconforming_count = len(checklist.nonconforming_keys or [])
        summary["total"] += 1
        summary["nonconforming"] += nonconforming_count
        if status_value in ["submitted", "reviewed"]:
            summary["pending"] += 1
        elif status_value == "approved":
            summary["approved"] += 1
        elif status_value == "rejected":
            summary["rejected"] += 1
        if equipment_status == "blocked":
            summary["blocked"] += 1
        checklist_rows.append({
            "checklist": checklist,
            "employee": employee,
            "equipment_status": equipment_status,
            "equipment_status_label": equipment_labels.get(equipment_status, equipment_status),
            "status_label": status_labels.get(status_value, status_value),
            "date_br": fmt_ddmmyyyy(checklist.date),
            "time_br": fmt_hhmm(checklist.submitted_at),
            "nonconforming_count": nonconforming_count
        })

    employees = session.exec(select(models.Employee).order_by(models.Employee.name)).all()

    return templates.TemplateResponse(
        "admin_routine_checklists.html",
        {
            "request": request,
            "rows": checklist_rows,
            "employees": employees,
            "status_options": ["submitted", "reviewed", "approved", "rejected"],
            "status_labels": status_labels,
            "filters": {
                "date": date_filter or "",
                "status": status_filter or "",
                "equipment": equipment_filter or "",
                "employee_id": employee_filter_id,
                "period_days": period_days_param,
                "nonconforming": nonconforming_param,
                "critical": critical_param
            },
            "summary": {
                "total": format_int_br(summary["total"]),
                "pending": format_int_br(summary["pending"]),
                "approved": format_int_br(summary["approved"]),
                "rejected": format_int_br(summary["rejected"]),
                "blocked": format_int_br(summary["blocked"]),
                "nonconforming": format_int_br(summary["nonconforming"])
            }
        }
    )

@app.get("/admin/routine/checklists/{checklist_id}", response_class=HTMLResponse)
async def admin_checklist_detail(
    checklist_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")
    employee = session.get(models.Employee, checklist.employee_id)
    equipment = session.exec(
        select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == checklist.equipment_code)
    ).first()

    label_map = checklist_item_label_map()
    return templates.TemplateResponse(
        "admin_routine_checklist_detail.html",
        {
            "request": request,
            "checklist": checklist,
            "employee": employee,
            "employee_name": employee.name if employee else "Desconhecido",
            "employee_registration_id": employee.registration_id if employee else "-",
            "equipment": equipment,
            "label_map": label_map,
            "items": CHECKLIST_ITEMS
        }
    )

@app.post("/admin/routine/checklists/{checklist_id}/delete", response_class=RedirectResponse)
async def admin_checklist_delete(
    request: Request,
    checklist_id: int,
    confirm_delete: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")

    if checklist.status == "approved" and confirm_delete != "true":
        raise HTTPException(status_code=400, detail="ConfirmaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o obrigatÃƒÆ’Ã‚Â³ria para excluir checklist aprovado.")

    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    if checklist.xp_transaction_id:
        tx = session.get(models.GameXPTransaction, checklist.xp_transaction_id)
        if tx:
            # Se a transaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o foi confirmada/aprovada, remover XP do total do colaborador
            if tx.status in ["approved", "confirmed"]:
                emp = session.get(models.Employee, checklist.employee_id)
                if emp and tx.amount:
                    # Deduzir XP do total do colaborador
                    emp.total_xp = max(0, emp.total_xp - abs(tx.amount))
                    session.add(emp)
            
            note = "Checklist excluÃƒÆ’Ã‚Â­do por admin"
            tx.status = "rejected"
            if tx.reason:
                if note not in tx.reason:
                    tx.reason = f"{tx.reason} | {note}"
            else:
                tx.reason = note
            session.add(tx)

    # Formata quem realizou a exclusÃƒÆ’Ã‚Â£o de forma mais legÃƒÆ’Ã‚Â­vel
    try:
        if isinstance(user, dict):
            user_label = user.get("email") or user.get("id") or "usuÃƒÆ’Ã‚Â¡rio"
        else:
            user_label = getattr(user, "email", None) or getattr(user, "name", None) or str(user)
    except Exception:
        user_label = "usuÃƒÆ’Ã‚Â¡rio"

    session.add(models.Event(
        timestamp=now_br,
        text=f"Checklist #{checklist.id} excluÃƒÆ’Ã‚Â­do por {user_label}.",
        type="checklist_delete",
        category="processo",
        sector=checklist.equipment_code,
        impact="high",
        reference_type="checklist",
        reference_id=checklist.id,
        employee_id=checklist.employee_id
    ))

    session.delete(checklist)
    session.commit()
    return RedirectResponse(url="/admin/routine/checklists", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/routine/checklists/bulk-delete", response_class=RedirectResponse)
async def admin_checklist_bulk_delete(
    request: Request,
    checklist_ids: List[int] = Form(...),
    session: Session = Depends(get_session),
    user = Depends(require_leader)
):
    if not checklist_ids:
        return RedirectResponse(url="/admin/routine/checklists", status_code=status.HTTP_303_SEE_OTHER)

    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    
    # Process each checklist
    for cid in checklist_ids:
        checklist = session.get(models.TranspalletChecklist, cid)
        if not checklist:
            continue
            
        # If equipment was blocked by this checklist, release it
        eq = session.exec(select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == checklist.equipment_code)).first()
        if eq and eq.status == "blocked" and eq.last_checklist_id == checklist.id:
            eq.status = "available"
            eq.blocked_reason = None
            eq.last_checklist_id = None
            session.add(eq)
        
        # If checklist gave XP, revoke it and remove from employee total
        if checklist.xp_transaction_id:
            tx = session.get(models.GameXPTransaction, checklist.xp_transaction_id)
            if tx:
                # Se a transaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o foi confirmada/aprovada, remover XP do total do colaborador
                if tx.status in ["approved", "confirmed"]:
                    emp = session.get(models.Employee, checklist.employee_id)
                    if emp and tx.amount:
                        # Deduzir XP do total do colaborador
                        emp.total_xp = max(0, emp.total_xp - abs(tx.amount))
                        session.add(emp)
                
                # Revogar a transaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
                tx.status = "rejected"
                if tx.reason:
                    tx.reason = f"{tx.reason} | Revogado: Checklist #{checklist.id} excluÃƒÆ’Ã‚Â­do em lote."
                else:
                    tx.reason = f"Revogado: Checklist #{checklist.id} excluÃƒÆ’Ã‚Â­do em lote."
                session.add(tx)

        # Formata quem realizou a exclusÃƒÆ’Ã‚Â£o em lote de forma mais legÃƒÆ’Ã‚Â­vel
        user_label = format_user_label(user)

        session.add(models.Event(
            timestamp=now_br,
            text=f"Checklist #{checklist.id} excluÃƒÆ’Ã‚Â­do em lote por {user_label}.",
            type="checklist_delete",
            category="processo",
            sector=checklist.equipment_code,
            impact="high",
            reference_type="checklist",
            reference_id=checklist.id,
            employee_id=checklist.employee_id
        ))
        
        session.delete(checklist)
    
    session.commit()
    return RedirectResponse(url="/admin/routine/checklists", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/routine/checklists/{checklist_id}/edit", response_class=RedirectResponse)
async def admin_checklist_edit(
    request: Request,
    checklist_id: int,
    equipment_code: str = Form(...),
    observations: str = Form(""),
    edit_comment: str = Form(...),
    files: List[UploadFile] = File([]),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")

    comment = (edit_comment or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="ComentÃƒÆ’Ã‚Â¡rio obrigatÃƒÆ’Ã‚Â³rio para ediÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o.")

    new_equipment = (equipment_code or "").strip().upper()
    if not new_equipment:
        raise HTTPException(status_code=400, detail="Equipamento obrigatÃƒÆ’Ã‚Â³rio.")

    new_observations = (observations or "").strip()
    old_equipment = checklist.equipment_code
    old_observations = checklist.observations or ""

    new_images = []
    if files:
        new_images = await save_checklist_images(files)

    changes = []
    if new_equipment != old_equipment:
        checklist.previous_equipment_code = old_equipment
        checklist.equipment_code = new_equipment
        resolve_equipment(session, new_equipment)
        changes.append(f"Equipamento: {old_equipment} -> {new_equipment}")

    if new_observations != old_observations:
        checklist.previous_observations = old_observations
        checklist.observations = new_observations
        changes.append("ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes atualizadas")

    if new_images:
        checklist.images = (checklist.images or []) + new_images
        changes.append(f"Imagens adicionadas: {len(new_images)}")

    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    actor_label = format_user_label(user)
    checklist.edited_at = now_br
    checklist.edited_by = actor_label
    checklist.edit_comment = comment

    if changes:
        session.add(models.Event(
            timestamp=now_br,
            text=f"Checklist #{checklist.id} editado por {actor_label}. Motivo: {comment}. AlteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {', '.join(changes)}.",
            type="checklist_edit",
            category="processo",
            sector=checklist.equipment_code,
            impact="medium",
            reference_type="checklist",
            reference_id=checklist.id,
            employee_id=checklist.employee_id
        ))

    session.add(checklist)
    session.commit()
    return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/tools/cleanup/checklists", response_class=RedirectResponse)
async def admin_cleanup_all_checklists(
    request: Request,
    confirm_phrase: str = Form(...),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """
    Remove TODOS os checklists operacionais (TranspalletChecklist),
    limpa histÃƒÆ’Ã‚Â³rico em todas as pÃƒÆ’Ã‚Â¡ginas (por exclusÃƒÆ’Ã‚Â£o no banco) e
    remove automaticamente o XP jÃƒÆ’Ã‚Â¡ creditado.

    Uso exclusivo para admin/lÃƒÆ’Ã‚Â­der, com confirmaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o forte.
    """
    phrase = (confirm_phrase or "").strip().lower()
    expected = "apagar todos os checklists"
    if phrase != expected:
        return RedirectResponse(
            url="/admin/routine/checklists/settings?message=Frase+de+confirma%C3%A7%C3%A3o+inv%C3%A1lida.&level=error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))

    # Buscar todos os checklists
    checklists = session.exec(select(models.TranspalletChecklist)).all()

    for checklist in checklists:
        # Liberar equipamento se bloqueado por este checklist
        if checklist.equipment_code:
            eq = session.exec(
                select(models.TranspalletEquipment).where(
                    models.TranspalletEquipment.code == checklist.equipment_code
                )
            ).first()
            if eq and eq.status == "blocked" and eq.last_checklist_id == checklist.id:
                eq.status = "available"
                eq.blocked_reason = None
                eq.last_checklist_id = None
                session.add(eq)

        # Remover XP se houve transaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
        if checklist.xp_transaction_id:
            tx = session.get(models.GameXPTransaction, checklist.xp_transaction_id)
            if tx:
                if tx.status in ["approved", "confirmed"]:
                    emp = session.get(models.Employee, checklist.employee_id)
                    if emp and tx.amount:
                        emp.total_xp = max(0, emp.total_xp - abs(tx.amount))
                        session.add(emp)

                tx.status = "rejected"
                note = f"Revogado: Checklist #{checklist.id} exclu%C3%ADdo+no+cleanup+global."
                if tx.reason:
                    if "Revogado: Checklist" not in tx.reason:
                        tx.reason = f"{tx.reason} | {note}"
                else:
                    tx.reason = note
                session.add(tx)

        # Evento de auditoria
        session.add(
            models.Event(
                timestamp=now_br,
                text=f"Checklist #{checklist.id} excluÃƒÆ’Ã‚Â­do em limpeza global por {actor_label}.",
                type="checklist_delete",
                category="processo",
                sector=checklist.equipment_code,
                impact="high",
                reference_type="checklist",
                reference_id=checklist.id,
                employee_id=checklist.employee_id,
            )
        )

        session.delete(checklist)

    session.commit()
    return RedirectResponse(
        url="/admin/routine/checklists/settings?message=Todos+os+checklists+foram+apagados+com+sucesso.&level=success",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/tools/cleanup/tickets", response_class=RedirectResponse)
async def admin_cleanup_all_tickets(
    request: Request,
    confirm_phrase: str = Form(...),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """
    Remove TODOS os chamados de equipamento (EquipmentTicket) e seus eventos
    de histÃƒÆ’Ã‚Â³rico. Uso exclusivo para admin/lÃƒÆ’Ã‚Â­der, com confirmaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o forte.
    """
    phrase = (confirm_phrase or "").strip().lower()
    expected = "apagar todos os chamados"
    if phrase != expected:
        return RedirectResponse(
            url="/admin/equipment/tickets?message=Frase+de+confirma%C3%A7%C3%A3o+inv%C3%A1lida.&level=error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    actor_label = format_user_label(user)

    # Buscar todos os tickets
    tickets = session.exec(select(models.EquipmentTicket)).all()

    for ticket in tickets:
        # Remover eventos de histÃƒÆ’Ã‚Â³rico deste ticket, se modelo existir
        try:
            events = session.exec(
                select(models.EquipmentTicketEvent).where(
                    models.EquipmentTicketEvent.ticket_id == ticket.id
                )
            ).all()
            for ev in events:
                session.delete(ev)
        except AttributeError:
            # Se nÃƒÆ’Ã‚Â£o existir EquipmentTicketEvent no modelo, ignora silenciosamente
            pass

        # NÃƒÆ’Ã‚Â£o hÃƒÆ’Ã‚Â¡ XP direto amarrado ao ticket, entÃƒÆ’Ã‚Â£o apenas deletamos
        session.delete(ticket)

    session.commit()
    return RedirectResponse(
        url="/admin/equipment/tickets?message=Todos+os+chamados+foram+apagados+com+sucesso.&level=success",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@app.post("/admin/routine/checklists/{checklist_id}/approve", response_class=RedirectResponse)
async def admin_checklist_approve(
    request: Request,
    checklist_id: int,
    comment: str = Form(""),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")
    reviewer = format_user_label(user)
    apply_checklist_review(session, checklist, reviewer, "approve", comment)
    session.commit()
    return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/routine/checklists/{checklist_id}/reject", response_class=RedirectResponse)
async def admin_checklist_reject(
    request: Request,
    checklist_id: int,
    comment: str = Form(...),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")
    reviewer = format_user_label(user)
    apply_checklist_review(session, checklist, reviewer, "reject", comment)
    session.commit()
    return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/routine/checklists/{checklist_id}/review", response_class=RedirectResponse)
async def admin_checklist_review(
    request: Request,
    checklist_id: int,
    comment: str = Form(""),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")
    reviewer = format_user_label(user)
    apply_checklist_review(session, checklist, reviewer, "review", comment)
    session.commit()
    return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/routine/checklists/{checklist_id}/release", response_class=RedirectResponse)
async def admin_checklist_release_equipment(
    request: Request,
    checklist_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")
    equipment = session.exec(
        select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == checklist.equipment_code)
    ).first()
    if equipment:
        release_equipment(session, equipment, str(user))
        session.commit()
    return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/routine/checklists/{checklist_id}/resend-email", response_class=RedirectResponse)
async def admin_checklist_resend_email(
    request: Request,
    checklist_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """Reenviar e-mail de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o do checklist"""
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        raise HTTPException(status_code=404, detail="Checklist nÃƒÆ’Ã‚Â£o encontrado.")
    
    employee = session.get(models.Employee, checklist.employee_id)
    equipment = session.exec(
        select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == checklist.equipment_code)
    ).first()
    
    # Buscar destinatÃƒÆ’Ã‚Â¡rios
    recipient_emails = get_maintenance_recipient_emails(session)
    
    if not recipient_emails:
        checklist.maintenance_email_error = "Nenhum destinatÃƒÆ’Ã‚Â¡rio configurado"
        session.add(checklist)
        session.commit()
        return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}?message=Nenhum+destinatÃƒÆ’Ã‚Â¡rio+configurado&level=error", status_code=status.HTTP_303_SEE_OTHER)
    
    # Montar relatÃƒÆ’Ã‚Â³rio
    label_map = checklist_item_label_map()
    nonconforming_items = checklist_nonconforming_items(checklist.nonconforming_keys)
    
    # Montar corpo do e-mail
    nonconforming_lines = []
    for item in nonconforming_items:
        critical_tag = " [CRÃƒÆ’Ã‚ÂTICO]" if item.get("critical") else ""
        nonconforming_lines.append(f"  ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ {item.get('label', item.get('key', ''))}{critical_tag}")
    
    checklist_link = f"{APP_BASE_URL}/admin/routine/checklists/{checklist.id}" if APP_BASE_URL else f"/admin/routine/checklists/{checklist.id}"
    date_br = datetime.strptime(checklist.date, "%Y-%m-%d").strftime("%d/%m/%Y") if checklist.date else now_br.strftime("%d/%m/%Y")
    
    body_lines = [
        "OlÃƒÆ’Ã‚Â¡! Espero que se encontrem bem.",
        "",
        f"Segue para manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o o equipamento {checklist.equipment_code}.",
        "",
        f"Operador: {employee.name if employee else 'Desconhecido'} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â MatrÃƒÆ’Ã‚Â­cula: {employee.registration_id if employee else '-'}",
        f"Data: {date_br}",
        f"Turno: {checklist.shift}",
        "",
        "Itens que requerem atenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o:",
        *nonconforming_lines,
        "",
        f"ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {checklist.observations or '-'}",
        "",
        "Atenciosamente,",
        "Sistema de OperaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o Inteligente"
    ]
    
    report = {
        "employee_name": employee.name if employee else "Desconhecido",
        "equipment_code": checklist.equipment_code,
        "date": checklist.date,
        "shift": checklist.shift,
        "nonconforming_items": nonconforming_items,
        "critical": checklist.critical_flag,
        "observations": checklist.observations or "",
        "images": [f"/static/uploads/checklists/{img}" for img in (checklist.images or [])],
        "subject": f"ManutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o Equipamento {checklist.equipment_code} - {date_br}",
        "body": "\n".join(body_lines)
    }
    
    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    sent, error = send_maintenance_email(report, recipient_emails)
    
    if sent:
        checklist.maintenance_email_sent_at = now_br
        checklist.maintenance_email_error = None
        session.add(checklist)
        session.commit()
        return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}?message=E-mail+reenviado+com+sucesso&level=success", status_code=status.HTTP_303_SEE_OTHER)
    else:
        checklist.maintenance_email_error = error or "Falha ao enviar e-mail"
        session.add(checklist)
        session.commit()
        return RedirectResponse(url=f"/admin/routine/checklists/{checklist_id}?message=Erro+ao+reenviar+e-mail&level=error", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/routine/checklists")
async def api_create_checklist(
    request: Request,
    equipment_code: str = Form(...),
    odometer_km: Optional[str] = Form(None),
    items: str = Form(...),
    observations: str = Form(""),
    date: Optional[str] = Form(None),
    shift: Optional[str] = Form(None),
    files: List[UploadFile] = File([]),
    session: Session = Depends(get_session)
):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)

    employee_id = user.get("id")
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    require_mobile_module(employee, "checklist")

    equipment_code = (equipment_code or "").strip().upper()
    if not equipment_code:
        return JSONResponse({"error": "Equipamento obrigatÃƒÆ’Ã‚Â³rio."}, status_code=400)
    # Aceita TranspalletEquipment OU Vehicle (caminhÃƒÆ’Ã‚Â£o por placa)
    equipment = session.exec(
        select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == equipment_code)
    ).first()
    is_truck = False
    if not equipment:
        truck = session.exec(
            select(models.Vehicle)
            .where(models.Vehicle.placa == equipment_code)
            .where(models.Vehicle.vehicle_type == "caminhao")
            .where(models.Vehicle.is_active == True)
        ).first()
        if not truck:
            return JSONResponse({"error": "Equipamento nÃƒÆ’Ã‚Â£o cadastrado."}, status_code=400)
        is_truck = True

    # ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o KM (obrigatÃƒÆ’Ã‚Â³rio apenas para caminhÃƒÆ’Ã‚Â£o)
    try:
        km_val = float((odometer_km or "").strip().replace(",", ".")) if odometer_km else None
    except (ValueError, TypeError):
        km_val = None
    if is_truck and (km_val is None or km_val < 0):
        return JSONResponse({"error": "Informe o KM do hodÃƒÆ’Ã‚Â´metro para caminhÃƒÆ’Ã‚Â£o."}, status_code=400)
    last_check = session.exec(
        select(models.TranspalletChecklist)
        .where(models.TranspalletChecklist.equipment_code == equipment_code)
        .order_by(desc(models.TranspalletChecklist.date), desc(models.TranspalletChecklist.submitted_at))
    ).first()
    # ReferÃƒÆ’Ã‚Âªncia de KM: veÃƒÆ’Ã‚Â­culo (se caminhÃƒÆ’Ã‚Â£o e tiver) ou ÃƒÆ’Ã‚Âºltimo checklist
    last_km_ref = None
    if is_truck and truck and getattr(truck, "odometer_km", None) is not None:
        last_km_ref = float(truck.odometer_km)
    elif last_check and last_check.odometer_km is not None:
        last_km_ref = float(last_check.odometer_km)
    if km_val is not None and last_km_ref is not None:
        last_km = last_km_ref
        if km_val <= last_km:
            return JSONResponse({"error": f"KM deve ser maior que o anterior ({last_km:,.0f})."}, status_code=400)  # noqa: E501
        if km_val > last_km + 1000:
            return JSONResponse({"error": f"MÃƒÆ’Ã‚Â¡ximo 1000 km/dia. KM anterior: {last_km:,.0f}. MÃƒÆ’Ã‚Â¡x hoje: {last_km + 1000:,.0f}."}, status_code=400)  # noqa: E501

    payload_items = parse_items_payload(items)
    if not payload_items or len(payload_items) != len(CHECKLIST_ITEM_KEYS):
        return JSONResponse({"error": "Checklist incompleto."}, status_code=400)

    nonconforming_keys = [k for k, v in payload_items.items() if not v]
    observations = (observations or "").strip()
    files = files or []
    if nonconforming_keys:
        if not observations:
            return JSONResponse({"error": "ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o obrigatÃƒÆ’Ã‚Â³ria para nÃƒÆ’Ã‚Â£o conformidade."}, status_code=400)
        if not files:
            return JSONResponse({"error": "Imagem obrigatÃƒÆ’Ã‚Â³ria para nÃƒÆ’Ã‚Â£o conformidade."}, status_code=400)

    critical_flag = any(k in CHECKLIST_CRITICAL_KEYS for k in nonconforming_keys)
    images = []
    if files:
        images = await save_checklist_images(files)

    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    date_val = date or now_br.strftime("%Y-%m-%d")
    shift_val = shift or employee.work_shift or "ManhÃƒÆ’Ã‚Â£"

    checklist = models.TranspalletChecklist(
        employee_id=employee_id,
        equipment_code=equipment_code,
        odometer_km=km_val,
        date=date_val,
        shift=shift_val,
        status="submitted",
        items=payload_items,
        nonconforming_keys=nonconforming_keys,
        observations=observations,
        images=images,
        critical_flag=critical_flag,
        submitted_at=now_br
    )
    session.add(checklist)
    session.commit()
    session.refresh(checklist)

    # Atualizar ÃƒÆ’Ã‚Âºltimo KM do veÃƒÆ’Ã‚Â­culo quando checklist for de caminhÃƒÆ’Ã‚Â£o
    if is_truck and km_val is not None and truck:
        truck.odometer_km = km_val
        truck.updated_at = now_br
        session.add(truck)
        session.commit()

    if critical_flag:
        blocked_items = ", ".join([checklist_item_label_map().get(k, k) for k in nonconforming_keys])
        if equipment:
            block_equipment(session, equipment, f"Itens crÃƒÆ’Ã‚Â­ticos: {blocked_items}", checklist.id)
        session.add(models.Event(
            timestamp=now_br,
            text=f"Checklist crÃƒÆ’Ã‚Â­tico {equipment_code}: {blocked_items}",
            type="checklist",
            category="infraestrutura",
            sector=equipment_code,
            impact="high",
            reference_type="checklist",
            reference_id=checklist.id,
            employee_id=employee_id
        ))
        session.commit()

    if nonconforming_keys:
        report_items = checklist_nonconforming_items(nonconforming_keys)
        image_list = [f"/static/uploads/checklists/{img}" for img in images]
        checklist_link = f"{APP_BASE_URL}/admin/routine/checklists/{checklist.id}" if APP_BASE_URL else f"/admin/routine/checklists/{checklist.id}"
        submitted_at = checklist.submitted_at.strftime("%d/%m/%Y %H:%M") if checklist.submitted_at else now_br.strftime("%d/%m/%Y %H:%M")
        email_date_br = now_br.strftime("%d/%m/%Y")
        report = {
            "subject": f"ManutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o Equipamento {equipment_code} - {email_date_br}",
            "checklist_id": checklist.id,
            "operator_name": employee.name,
            "operator_id": employee.registration_id or "-",
            "submitted_at": submitted_at,
            "shift": shift_val,
            "equipment_code": equipment_code,
            "nonconforming_items": report_items,
            "observations": observations or "-",
            "checklist_link": checklist_link,
            "image_list": image_list,
            "generated_at": now_br.strftime("%d/%m/%Y %H:%M")
        }
        nonconforming_lines = []
        for item in report_items:
            critical_tag = " [CRÃƒÆ’Ã‚ÂTICO]" if item["critical"] else ""
            nonconforming_lines.append(f"  ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ {item['label']}{critical_tag}")
        
        body_lines = [
            "OlÃƒÆ’Ã‚Â¡! Espero que se encontrem bem.",
            "",
            f"Segue para manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o o equipamento {report['equipment_code']}.",
            "",
            f"Operador: {report['operator_name']} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â MatrÃƒÆ’Ã‚Â­cula: {report['operator_id']}",
            f"Data/Hora: {report['submitted_at']}",
            f"Turno: {report['shift']}",
            "",
            "Itens que requerem atenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o:",
            *nonconforming_lines,
            "",
            f"ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {report['observations']}",
            "",
            "Atenciosamente,",
            "Sistema de OperaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o Inteligente"
        ]
        if image_list:
            body_lines.insert(-3, "")
            body_lines.insert(-3, f"Imagens anexadas: {len(image_list)}")
        report["body"] = "\n".join(body_lines)
        report["pdf_filename"] = f"checklist_{checklist.id}_{date_val}.pdf"

        pdf_error = None
        try:
            report["pdf_bytes"] = build_checklist_pdf(report)
        except Exception as exc:
            pdf_error = str(exc)

        maintenance_error = None
        try:
            recipient_emails = get_maintenance_recipient_emails(session)
            sent, error = send_maintenance_email(report, recipient_emails)
            if sent:
                checklist.maintenance_email_sent_at = now_br
                if pdf_error:
                    maintenance_error = f"PDF nÃƒÆ’Ã‚Â£o gerado ({pdf_error}). E-mail enviado sem anexo."
            else:
                maintenance_error = error or "Falha ao enviar e-mail."
        except Exception as exc:
            maintenance_error = str(exc)
            logger.exception(f"Erro ao enviar e-mail de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o (checklist {checklist.id})")
        if maintenance_error:
            checklist.maintenance_email_error = maintenance_error
        session.add(checklist)
        session.commit()

    shift_ok = normalize_shift(shift_val) == normalize_shift(employee.work_shift)
    if shift_ok:
        tx = models.GameXPTransaction(
            employee_id=employee_id,
            amount=CHECKLIST_XP,
            source_type="checklist",
            status="provisional",
            reason=f"Checklist Transpaleteira {equipment_code} | {date_val}",
            created_at=now_br
        )
        session.add(tx)
        session.commit()
        checklist.xp_transaction_id = tx.id
        session.add(checklist)
        session.commit()

    return {"success": True, "id": checklist.id}

@app.post("/api/equipment/tickets")
async def api_create_ticket(
    request: Request,
    equipment_code: str = Form(...),
    description: str = Form(...),

    files: List[UploadFile] = File([]),
    session: Session = Depends(get_session)
):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)

    employee = session.get(models.Employee, user.get("id"))
    if not employee:
        return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    
    # Gating
    try:
        require_mobile_module(employee, "checklist")
    except HTTPException:
        return JSONResponse({"error": "Acesso nÃƒÆ’Ã‚Â£o autorizado ao mÃƒÆ’Ã‚Â³dulo de checklist."}, status_code=403)

    equipment_code = (equipment_code or "").strip().upper()
    description = (description or "").strip()

    if not equipment_code:
        return JSONResponse({"error": "Equipamento obrigatÃƒÆ’Ã‚Â³rio."}, status_code=400)
    if not description:
        return JSONResponse({"error": "DescriÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o obrigatÃƒÆ’Ã‚Â³ria."}, status_code=400)

    # Verificar se existe chamado aberto no mesmo dia (apenas para aviso, nÃƒÆ’Ã‚Â£o bloqueia)
    today_start = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    existing_ticket = session.exec(
        select(models.EquipmentTicket)
        .where(models.EquipmentTicket.equipment_code == equipment_code)
        .where(models.EquipmentTicket.status == "open")
        .where(models.EquipmentTicket.created_at >= today_start)
        .where(models.EquipmentTicket.created_at < today_end)
    ).first()
    
    # NÃƒÆ’Ã‚Â£o bloqueia mais, apenas armazena para mencionar no email


    # Auto Severity Logic
    severity_norm = "low"
    critical_keywords = ["freio", "vazamento", "direcao", "hidraulico", "bateria", "nao liga", "travado", "quebrado"]
    desc_lower = description.lower()
    
    # Rule: High if photo exists or critical keyword found
    # (images check happens later, so we init strict first)
    if any(k in desc_lower for k in critical_keywords):
        severity_norm = "high"

    images = []
    if files:
        images = await save_ticket_images(files)
        # If photo provided, automatically HIGH (as per rule)
        severity_norm = "high"

    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    shift_val = employee.work_shift or "ManhÃƒÆ’Ã‚Â£"

    ticket = models.EquipmentTicket(
        equipment_code=equipment_code,
        employee_id=employee.id,
        created_at=now_br,
        shift=shift_val,
        description=description,
        severity=severity_norm,
        images=images,
        status="open"
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)

    impact = "high" if severity_norm == "high" else "medium"
    event_text = f"Chamado aberto para {equipment_code} por {employee.name}: {description}"
    if severity_norm == "high":
        event_text += " (CRITICO)"
    session.add(models.Event(
        timestamp=now_br,
        text=event_text,
        type="ticket",
        category="infraestrutura",
        sector=equipment_code,
        impact=impact,
        reference_type="ticket",
        reference_id=ticket.id,
        employee_id=employee.id
    ))

    if severity_norm == "high":
        equipment = resolve_equipment(session, equipment_code)
        block_equipment(session, equipment, f"Chamado crÃƒÆ’Ã‚Â­tico #{ticket.id}", None)
        session.add(equipment)

    # --- Email Notification ---
    try:
        pdf_bytes = build_ticket_pdf({
            "ticket_id": ticket.id,
            "employee_id": employee.registration_id,
            "employee_name": employee.name,
            "created_at": now_br.strftime("%d/%m/%Y %H:%M"),
            "shift": shift_val,
            "equipment_code": equipment_code,
            "severity": severity_norm,
            "description": description,
            "image_list": images,
            "ticket_link": f"/admin/equipment/tickets", # Fallback link
            "generated_at": now_br.strftime("%d/%m/%Y %H:%M:%S")
        })
        
        # Preparar corpo do email
        email_body_lines = [
            f"Novo chamado de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o registrado.\n",
            f"Equipamento: {equipment_code}",
            f"Severidade: {severity_norm.upper()}",
            f"Solicitante: {employee.name} ({employee.registration_id})",
            f"Turno: {shift_val}",
            f"Data/Hora: {now_br.strftime('%d/%m/%Y %H:%M')}\n",
            f"DescriÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o:\n{description}\n"
        ]
        
        # Mencionar chamado existente se houver
        if existing_ticket:
            email_body_lines.insert(1, f"\nÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â ATENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O: JÃƒÆ’Ã‚Â¡ existe um chamado ABERTO hoje para este equipamento (Chamado #{existing_ticket.id}).")
            email_body_lines.insert(2, f"Este ÃƒÆ’Ã‚Â© um chamado adicional registrado no mesmo dia.\n")
        
        email_body_lines.append("\nVerifique o anexo PDF para mais detalhes e imagens.")
        
        email_report = {
            "subject": f"ALERTA MANUTENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {now_br.strftime('%Y-%m-%d')} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Equipamento {equipment_code}",
            "body": "\n".join(email_body_lines),
            "pdf_bytes": pdf_bytes,
            "pdf_filename": f"chamado_{ticket.id}_{equipment_code}.pdf"
        }
        
        sent, error = send_maintenance_email(email_report)
        if sent:
            ticket.maintenance_email_sent_at = now_br
        else:
            ticket.maintenance_email_error = str(error)
            logger.error(f"Failed to send ticket email: {error}")
            
    except Exception as e:
        logger.exception(f"Error generating ticket email/PDF: {e}")
        ticket.maintenance_email_error = str(e)

    session.add(ticket)
    session.commit()
    return {"success": True, "id": ticket.id}

@app.get("/admin/tools/email-test", response_class=HTMLResponse)
async def admin_email_test(request: Request, session: Session = Depends(get_session), user=Depends(require_leader)):
    now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
    report = {
        "subject": f"ALERTA MANUTENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {now_br.strftime('%Y-%m-%d')} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Equipamento TESTE",
        "body": "Teste de envio SMTP do sistema de checklists.",
        "pdf_bytes": None
    }
    recipient_emails = get_maintenance_recipient_emails(session)
    sent, error = send_maintenance_email(report, recipient_emails)
    return templates.TemplateResponse(
        "admin_email_test.html",
        {
            "request": request,
            "sent": sent,
            "error": error,
            "recipients": recipient_emails
        }
    )

@app.get("/api/routine/checklists")
async def api_list_checklists(
    request: Request,
    date: Optional[str] = None,
    status: Optional[str] = None,
    equipment: Optional[str] = None,
    employee_id: Optional[int] = None,
    session: Session = Depends(get_session)
):
    try:
        user = require_login(request)
        current_user = get_current_user(request)

        if isinstance(current_user, dict) and current_user.get("type") == "employee":
            employee = session.get(models.Employee, current_user.get("id"))
            if not employee:
                return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
            require_mobile_module(employee, "checklist")

        query = (
            select(models.TranspalletChecklist, models.Employee)
            .join(models.Employee, models.Employee.id == models.TranspalletChecklist.employee_id)
            .order_by(models.TranspalletChecklist.submitted_at.desc())
        )
        if date:
            query = query.where(models.TranspalletChecklist.date == date)
        if status:
            query = query.where(models.TranspalletChecklist.status == status)
        if equipment:
            query = query.where(models.TranspalletChecklist.equipment_code.ilike(f"%{equipment}%"))

        if isinstance(current_user, dict) and current_user.get("type") == "employee":
            query = query.where(models.TranspalletChecklist.employee_id == current_user.get("id"))
        elif employee_id:
            query = query.where(models.TranspalletChecklist.employee_id == employee_id)

        rows = session.exec(query).all()
        result = []
        for checklist, emp in rows:
            submitted_at_val = getattr(checklist, "submitted_at", None)
            if submitted_at_val is None:
                submitted_at_iso = None
            elif hasattr(submitted_at_val, "isoformat"):
                submitted_at_iso = submitted_at_val.isoformat()
            else:
                submitted_at_iso = str(submitted_at_val)
            nkeys = checklist.nonconforming_keys
            nonconforming_count = len(nkeys) if isinstance(nkeys, (list, tuple)) else 0
            result.append({
                "id": checklist.id,
                "employee_id": emp.id,
                "employee_name": emp.name,
                "registration_id": emp.registration_id,
                "equipment_code": checklist.equipment_code,
                "date": checklist.date,
                "shift": checklist.shift,
                "status": checklist.status,
                "critical": getattr(checklist, "critical_flag", False),
                "nonconforming_count": nonconforming_count,
                "submitted_at": submitted_at_iso
            })
        return {"success": True, "items": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("api_list_checklists error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/routine/checklists/{checklist_id}")
async def api_get_checklist(
    checklist_id: int,
    request: Request,
    session: Session = Depends(get_session)
):
    require_login(request)
    current_user = get_current_user(request)
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        return JSONResponse({"error": "Checklist nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    if isinstance(current_user, dict) and current_user.get("type") == "employee":
        employee = session.get(models.Employee, current_user.get("id"))
        if not employee:
            return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
        require_mobile_module(employee, "checklist")
        if checklist.employee_id != current_user.get("id"):
            return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=403)

    employee = session.get(models.Employee, checklist.employee_id)
    image_urls = [f"/static/uploads/checklists/{img}" for img in (checklist.images or [])]
    submitted_at_val = checklist.submitted_at
    if submitted_at_val is None:
        submitted_at_iso = None
    elif hasattr(submitted_at_val, "isoformat"):
        submitted_at_iso = submitted_at_val.isoformat()
    else:
        submitted_at_iso = str(submitted_at_val)

    reviewed_at_val = checklist.reviewed_at
    if reviewed_at_val is None:
        reviewed_at_iso = None
    elif hasattr(reviewed_at_val, "isoformat"):
        reviewed_at_iso = reviewed_at_val.isoformat()
    else:
        reviewed_at_iso = str(reviewed_at_val)

    employee_payload = {
        "id": employee.id if employee else checklist.employee_id,
        "name": employee.name if employee else "Desconhecido",
        "registration_id": employee.registration_id if employee else "-"
    }
    return {
        "success": True,
        "item": {
            "id": checklist.id,
            "employee": employee_payload,
            "equipment_code": checklist.equipment_code,
            "date": checklist.date,
            "shift": checklist.shift,
            "status": checklist.status,
            "items": checklist.items,
            "nonconforming_keys": checklist.nonconforming_keys,
            "observations": checklist.observations,
            "images": image_urls,
            "critical": checklist.critical_flag,
            "submitted_at": submitted_at_iso,
            "reviewed_at": reviewed_at_iso,
            "reviewed_by": checklist.reviewed_by,
            "review_comment": checklist.review_comment
        }
    }

@app.post("/api/routine/checklists/{checklist_id}/review")
async def api_review_checklist(
    checklist_id: int,
    request: Request,
    comment: str = Form(""),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        return JSONResponse({"error": "Checklist nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    reviewer = format_user_label(user)
    apply_checklist_review(session, checklist, reviewer, "review", comment)
    session.commit()
    return {"success": True}

@app.post("/api/routine/checklists/{checklist_id}/approve")
async def api_approve_checklist(
    checklist_id: int,
    request: Request,
    comment: str = Form(""),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        return JSONResponse({"error": "Checklist nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    reviewer = format_user_label(user)
    apply_checklist_review(session, checklist, reviewer, "approve", comment)
    session.commit()
    return {"success": True}

@app.post("/api/routine/checklists/{checklist_id}/reject")
async def api_reject_checklist(
    checklist_id: int,
    request: Request,
    comment: str = Form(...),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        return JSONResponse({"error": "Checklist nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    reviewer = format_user_label(user)
    apply_checklist_review(session, checklist, reviewer, "reject", comment)
    session.commit()
    return {"success": True}

@app.post("/api/routine/checklists/{checklist_id}/release")
async def api_release_equipment(
    checklist_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    checklist = session.get(models.TranspalletChecklist, checklist_id)
    if not checklist:
        return JSONResponse({"error": "Checklist nÃƒÆ’Ã‚Â£o encontrado."}, status_code=404)
    equipment = session.exec(
        select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == checklist.equipment_code)
    ).first()
    if equipment:
        release_equipment(session, equipment, str(user))
        session.commit()
    return {"success": True}

@app.get("/mobile/api/ai/today")
async def mobile_ai_today(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
         return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
         
    user_id = user.get("id")
    today = datetime.now().date()
    
    # 1. Calculate Average Productivity (Last 10 Days)
    # Placeholder logic
    avg_prod = 1500.0 # kg/h
    target = round(avg_prod * 1.05, 0)
    
    return {
        "avg_prod": avg_prod,
        "target_prod": target,
        "message": f"Ontem vocÃƒÆ’Ã‚Âª fez X. Hoje sua meta ÃƒÆ’Ã‚Â© {target}kg/h."
    }


# --- Client Routes ---
def _opt_form(v) -> Optional[str]:
    """Converte Form() vazio em None."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return str(v).strip() or None


@app.post("/clients/add", response_class=RedirectResponse)
async def add_client(
    request: Request,
    name: str = Form(...),
    nb: Optional[str] = Form(None),
    setor: Optional[str] = Form(None),
    me: Optional[str] = Form(None),
    sa: Optional[str] = Form(None),
    visita: Optional[str] = Form(None),
    nome_fantasia: Optional[str] = Form(None),
    razao_social: Optional[str] = Form(None),
    municipio: Optional[str] = Form(None),
    bairro: Optional[str] = Form(None),
    endereco: Optional[str] = Form(None),
    fone: Optional[str] = Form(None),
    segmento: Optional[str] = Form(None),
    status_cliente: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    require_login(request)
    try:
        existing = session.exec(select(models.Client).where(models.Client.name == name.strip())).first()
        if not existing:
            fone_val = _opt_form(fone)
            fone_e164_val, _ = normalize_phone_br(fone_val)
            endereco_val = _opt_form(endereco)
            endereco_norm_val = normalize_address(endereco_val).upper().replace(" ", "") if endereco_val and len(endereco_val) >= 10 else None
            new_client = models.Client(
                name=name.strip(),
                nb=_opt_form(nb),
                setor=_opt_form(setor),
                me=_opt_form(me),
                sa=_opt_form(sa),
                visita=_opt_form(visita),
                nome_fantasia=_opt_form(nome_fantasia),
                razao_social=_opt_form(razao_social),
                municipio=_opt_form(municipio),
                bairro=_opt_form(bairro),
                endereco=endereco_val,
                endereco_normalizado=endereco_norm_val,
                fone=fone_val,
                fone_e164=fone_e164_val,
                segmento=_opt_form(segmento),
                status_cliente=_opt_form(status_cliente),
                status_operacional="ATIVO",
            )
            session.add(new_client)
            session.commit()
    except Exception as e:
        logger.exception(f"Error adding client: {e}")
    return RedirectResponse(url="/clients", status_code=status.HTTP_303_SEE_OTHER)
def _is_ativo(c: models.Client) -> bool:
    st_op = ((c.status_operacional or "") or "").upper()
    st_cli = ((c.status_cliente or "") or "").upper()
    if "FECHOU" in st_op or "FECHOU" in st_cli:
        return False
    if "INATIVO" in st_op or "INATIVO" in st_cli:
        return False
    if "INVALIDOS" in st_cli:
        return False
    return True

def _is_fechou(c: models.Client) -> bool:
    st_op = ((c.status_operacional or "") or "").upper()
    st_cli = ((c.status_cliente or "") or "").upper()
    return "FECHOU" in st_op or "FECHOU" in st_cli

def _is_inativo(c: models.Client) -> bool:
    st_op = ((c.status_operacional or "") or "").upper()
    st_cli = ((c.status_cliente or "") or "").upper()
    return "INATIVO" in st_op or "INATIVO" in st_cli

@app.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    status_filter = request.query_params.get("status", "ativos")
    search = (request.query_params.get("q") or "").strip()

    try:
        all_clients = list(session.exec(select(models.Client)).all())
    except Exception as e:
        logger.exception(f"clients_page query error: {e}")
        all_clients = []

    if status_filter == "ativos":
        clients = [c for c in all_clients if _is_ativo(c)]
    elif status_filter == "fechou":
        clients = [c for c in all_clients if _is_fechou(c)]
    elif status_filter == "inativo":
        clients = [c for c in all_clients if _is_inativo(c)]
    elif status_filter == "em_validacao":
        clients = [c for c in all_clients if (c.status_operacional or "").upper() == "EM_VALIDACAO"]
    else:
        clients = all_clients

    if search:
        q = search.lower()
        clients = [c for c in clients if (
            (c.name and q in (c.name or "").lower()) or
            (c.razao_social and q in (c.razao_social or "").lower()) or
            (c.nome_fantasia and q in (c.nome_fantasia or "").lower()) or
            (c.nb and q in (c.nb or "").lower()) or
            (c.municipio and q in (c.municipio or "").lower())
        )]

    return templates.TemplateResponse("clients.html", {
        "request": request,
        "user": user,
        "clients": clients,
        "status_filter": status_filter,
        "search": search,
    })
@app.get("/clients/list", response_class=JSONResponse)
async def list_clients(session: Session = Depends(get_session)):
    clients = session.exec(select(models.Client)).all()
    return {"clients": [c.name for c in clients]}
@app.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_details(request: Request, client_id: int, session: Session = Depends(get_session)):
    user = require_login(request)
    client = session.get(models.Client, client_id)
    if not client:
        return RedirectResponse(url="/clients")
        
    # Fetch all routes for this client
    routes = session.exec(
        select(models.Route)
        .where(models.Route.client_id == client_id)
        .order_by(models.Route.date.desc(), models.Route.start_time.desc())
    ).all()
    
    # --- Metrics Logic ---
    total_tonnage = 0.0
    total_duration_secs = 0.0
    count_duration = 0
    
    # Period Stats (tonnage)
    today = datetime.now().date()
    stats_today = 0.0
    stats_week = 0.0
    stats_month = 0.0
    stats_year = 0.0
    # Period Stats (valor financeiro R$)
    valor_today, valor_week, valor_month, valor_year = 0.0, 0.0, 0.0, 0.0
    # Period Stats (devolucao volume ton e valor R$)
    dev_vol_today, dev_vol_week, dev_vol_month, dev_vol_year = 0.0, 0.0, 0.0, 0.0
    valor_dev_today, valor_dev_week, valor_dev_month, valor_dev_year = 0.0, 0.0, 0.0, 0.0

    # Employee Stats
    emp_counter = {}
    
    emp_map = {e.id: e.name for e in session.exec(select(models.Employee)).all()}
    
    history = []
    
    for r in routes:
        t = r.tonnage or 0.0
        total_tonnage += t
        
        # Date Parsing
        try:
            r_date = datetime.strptime(r.date, "%Y-%m-%d").date()
        except:
            continue
            
        # Periods
        if r_date == today:
            stats_today += t
        
        # Week (Start of week usually Monday)
        # Simple iso calendar check
        if r_date.isocalendar()[1] == today.isocalendar()[1] and r_date.year == today.year:
            stats_week += t
            
        if r_date.month == today.month and r_date.year == today.year:
            stats_month += t
            
        if r_date.year == today.year:
            stats_year += t

        vf = getattr(r, "valor_financeiro", None) or 0.0
        dv = getattr(r, "devolucao_volume", None) or 0.0
        vdev = getattr(r, "valor_devolucao", None) or 0.0
        if r_date == today:
            valor_today += vf
            dev_vol_today += dv
            valor_dev_today += vdev
        if r_date.isocalendar()[1] == today.isocalendar()[1] and r_date.year == today.year:
            valor_week += vf
            dev_vol_week += dv
            valor_dev_week += vdev
        if r_date.month == today.month and r_date.year == today.year:
            valor_month += vf
            dev_vol_month += dv
            valor_dev_month += vdev
        if r_date.year == today.year:
            valor_year += vf
            dev_vol_year += dv
            valor_dev_year += vdev

        # Employee Count
        eid = r.employee_id
        if eid not in emp_counter: emp_counter[eid] = {'count': 0, 'tonnage': 0.0}
        emp_counter[eid]['count'] += 1
        emp_counter[eid]['tonnage'] += t
        
        # Duration
        dur_str = None
        prod = 0.0
        if r.start_time and r.end_time:
            try:
                s = datetime.strptime(r.start_time, "%H:%M")
                e = datetime.strptime(r.end_time, "%H:%M")
                diff = (e - s).total_seconds()
                if diff > 0:
                    total_duration_secs += diff
                    count_duration += 1
                    dur_str = f"{int(diff//3600)}h {int((diff%3600)//60)}m"
                    # Productivity (kg/h)
                    hours = diff / 3600
                    prod = round(t / hours, 2)
            except:
                pass
                
        # History Row
        history.append({
            "date_fmt": r_date.strftime("%d/%m/%Y"),
            "shift": r.shift,
            "employee_name": emp_map.get(r.employee_id, "Desconhecido"),
            "tonnage_fmt": f"{t:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "duration_fmt": dur_str,
            "productivity": prod,
            "productivity_fmt": f"{prod:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        })
        
    # Aggregates
    avg_duration_str = "-"
    avg_prod_val = 0.0
    if count_duration > 0:
        avg_sec = total_duration_secs / count_duration
        avg_duration_str = f"{int(avg_sec//3600)}h {int((avg_sec%3600)//60)}m"
        # Rough average productivity
        # Total Tonnage / Total Hours (Weighted Average)
        total_hours = total_duration_secs / 3600
        if total_hours > 0:
            avg_prod_val = total_tonnage / total_hours
            
    # Top Employee
    top_emp_name = "-"
    top_emp_count = 0
    if emp_counter:
        best_id = max(emp_counter, key=lambda k: emp_counter[k]['tonnage']) # Ranking by Tonnage
        top_emp_name = emp_map.get(best_id, "-")
        top_emp_count = emp_counter[best_id]['count']
        
    # Last Op
    last_op_date = "-"
    last_op_days_ago = 0
    if routes:
        last_r = routes[0] # Sorted desc
        try:
            l_date = datetime.strptime(last_r.date, "%Y-%m-%d").date()
            last_op_date = l_date.strftime("%d/%m/%Y")
            last_op_days_ago = (today - l_date).days
        except:
            pass
            
    def fmt(n): return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    try:
        audit_logs = list(session.exec(
            select(models.ClientAuditLog)
            .where(models.ClientAuditLog.client_id == client_id)
            .order_by(models.ClientAuditLog.changed_at.desc())
            .limit(50)
        ).all())
    except Exception:
        audit_logs = []

    endereco_display = normalize_address(client.endereco or "") if client.endereco else ""
    return templates.TemplateResponse("client_details.html", {
        "request": request,
        "user": user,
        "client": client,
        "endereco_display": endereco_display or client.endereco,
        "audit_logs": audit_logs,
        "stats": {
            "total_tonnage_fmt": fmt(total_tonnage),
            "avg_duration_fmt": avg_duration_str,
            "last_op_date": last_op_date,
            "last_op_days_ago": last_op_days_ago,
            "top_employee": top_emp_name,
            "top_employee_count": top_emp_count,
            "total_routes": len(routes),
            "avg_tonnage_per_route_fmt": fmt(total_tonnage / len(routes)) if routes else "0,00",
            "avg_productivity_fmt": fmt(avg_prod_val)
        },
        "periods": {
            "today_fmt": fmt(stats_today),
            "week_fmt": fmt(stats_week),
            "month_fmt": fmt(stats_month),
            "year_fmt": fmt(stats_year),
        },
        "periods_valor": {
            "today_fmt": f"R$ {fmt(valor_today)}",
            "week_fmt": f"R$ {fmt(valor_week)}",
            "month_fmt": f"R$ {fmt(valor_month)}",
            "year_fmt": f"R$ {fmt(valor_year)}",
        },
        "periods_devolucao_vol": {
            "today_fmt": fmt(dev_vol_today),
            "week_fmt": fmt(dev_vol_week),
            "month_fmt": fmt(dev_vol_month),
            "year_fmt": fmt(dev_vol_year),
        },
        "periods_valor_devolucao": {
            "today_fmt": f"R$ {fmt(valor_dev_today)}",
            "week_fmt": f"R$ {fmt(valor_dev_week)}",
            "month_fmt": f"R$ {fmt(valor_dev_month)}",
            "year_fmt": f"R$ {fmt(valor_dev_year)}",
        },
        "chart_devolucao": {
            "pct_volume": round(100 * dev_vol_year / stats_year, 1) if stats_year > 0 else 0,
            "pct_valor": round(100 * valor_dev_year / valor_year, 1) if valor_year > 0 else 0,
        },
        "history": history
    })

@app.post("/clients/{client_id}/update", response_class=RedirectResponse)
async def update_client(
    request: Request,
    client_id: int,
    name: str = Form(...),
    nb: Optional[str] = Form(None),
    setor: Optional[str] = Form(None),
    me: Optional[str] = Form(None),
    sa: Optional[str] = Form(None),
    visita: Optional[str] = Form(None),
    nome_fantasia: Optional[str] = Form(None),
    razao_social: Optional[str] = Form(None),
    municipio: Optional[str] = Form(None),
    bairro: Optional[str] = Form(None),
    endereco: Optional[str] = Form(None),
    fone: Optional[str] = Form(None),
    segmento: Optional[str] = Form(None),
    status_cliente: Optional[str] = Form(None),
    status_operacional: Optional[str] = Form(None),
    logradouro: Optional[str] = Form(None),
    numero: Optional[str] = Form(None),
    complemento: Optional[str] = Form(None),
    referencia: Optional[str] = Form(None),
    observacoes_acesso: Optional[str] = Form(None),
    fone_alternativo: Optional[str] = Form(None),
    observacoes_contato: Optional[str] = Form(None),
    janela_dias_semana: Optional[str] = Form(None),
    janela_horario_inicio: Optional[str] = Form(None),
    janela_horario_fim: Optional[str] = Form(None),
    prioridade_logistica: Optional[str] = Form(None),
    lgpd_nao_contatar: Optional[str] = Form(None),
    lgpd_restricao_dados: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    require_login(request)
    client = session.get(models.Client, client_id)
    if client:
        old_name, old_nb, old_setor, old_razao, old_status_op = (
            client.name, client.nb, client.setor, client.razao_social, client.status_operacional
        )
        fone_val = _opt_form(fone)
        fone_e164_val, _ = normalize_phone_br(fone_val)
        endereco_val = _opt_form(endereco)
        endereco_clean = normalize_address(endereco_val) if endereco_val else None
        endereco_norm_val = endereco_clean.upper().replace(" ", "") if endereco_clean and len(endereco_clean) >= 10 else None
        client.name = name.strip()
        client.nb = _opt_form(nb)
        client.setor = _opt_form(setor)
        client.me = _opt_form(me)
        client.sa = _opt_form(sa)
        client.visita = _opt_form(visita)
        client.nome_fantasia = _opt_form(nome_fantasia)
        client.razao_social = _opt_form(razao_social)
        client.municipio = _opt_form(municipio)
        client.bairro = _opt_form(bairro)
        client.endereco = endereco_clean or endereco_val
        client.endereco_normalizado = endereco_norm_val
        client.fone = fone_val
        client.fone_e164 = fone_e164_val
        client.segmento = _opt_form(segmento)
        client.status_cliente = _opt_form(status_cliente)
        client.status_operacional = _opt_form(status_operacional) or "ATIVO"
        client.logradouro = _opt_form(logradouro)
        client.numero = _opt_form(numero)
        client.complemento = _opt_form(complemento)
        client.referencia = _opt_form(referencia)
        client.observacoes_acesso = _opt_form(observacoes_acesso)
        client.fone_alternativo = _opt_form(fone_alternativo)
        client.observacoes_contato = _opt_form(observacoes_contato)
        client.janela_dias_semana = _opt_form(janela_dias_semana)
        client.janela_horario_inicio = _opt_form(janela_horario_inicio)
        client.janela_horario_fim = _opt_form(janela_horario_fim)
        client.prioridade_logistica = _opt_form(prioridade_logistica)
        client.lgpd_nao_contatar = (lgpd_nao_contatar or "").strip().lower() in ("on", "1", "true", "sim", "sim")
        client.lgpd_restricao_dados = (lgpd_restricao_dados or "").strip().lower() in ("on", "1", "true", "sim", "sim")
        client.updated_at = datetime.now()
        username = request.session.get("username", "sistema")
        new_name = name.strip()
        new_nb = _opt_form(nb)
        new_setor = _opt_form(setor)
        new_razao = _opt_form(razao_social)
        new_status_op = _opt_form(status_operacional) or "ATIVO"
        audit_fields = [
            ("name", old_name, new_name),
            ("nb", old_nb, new_nb),
            ("setor", old_setor, new_setor),
            ("razao_social", old_razao, new_razao),
            ("status_operacional", old_status_op, new_status_op),
        ]
        for field_name, old_val, new_val in audit_fields:
            if str(old_val or "") != str(new_val or ""):
                log_entry = models.ClientAuditLog(
                    client_id=client_id,
                    changed_by=username,
                    field_name=field_name,
                    old_value=str(old_val)[:500] if old_val else None,
                    new_value=str(new_val)[:500] if new_val else None,
                    action="update",
                )
                session.add(log_entry)
        session.add(client)
        session.commit()
    return RedirectResponse(url=f"/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/clients/{client_id}/delete", response_class=RedirectResponse)
async def delete_client(request: Request, client_id: int, session: Session = Depends(get_session)):
    require_login(request)
    client = session.get(models.Client, client_id)
    if client:
        # Cascade Delete: Remove allocations/routes first
        # WARN: This removes historical production data for this client!
        session.exec(delete(models.Route).where(models.Route.client_id == client_id))
        
        session.delete(client)
        session.commit()
    return RedirectResponse(url="/clients", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/clients/template")
async def clients_template(request: Request):
    """Retorna planilha Excel modelo para importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de clientes."""
    import pandas as pd
    require_login(request)
    df = pd.DataFrame([
        {
            "NB": "001",
            "SETOR": "Varejo",
            "ME": "01",
            "SA": "Norte",
            "VISITA": "Semanal",
            "FANTAS": "Supermercado ABC",
            "RazÃƒÆ’Ã‚Â£o Social": "ABC ComÃƒÆ’Ã‚Â©rcio Ltda",
            "MUNICÃƒÆ’Ã‚ÂPIO": "SÃƒÆ’Ã‚Â£o Paulo",
            "BAIRRO": "Centro",
            "ENDEREÃƒÆ’Ã¢â‚¬Â¡O": "Rua Exemplo, 100",
            "FONE": "(11) 3333-4444",
            "SEGMENTO": "AlimentÃƒÆ’Ã‚Â­cio",
            "STATUS": "Ativo",
        },
        {
            "NB": "002",
            "SETOR": "Atacado",
            "ME": "02",
            "SA": "Sul",
            "VISITA": "Quinzenal",
            "FANTAS": "AtacadÃƒÆ’Ã‚Â£o XYZ",
            "RazÃƒÆ’Ã‚Â£o Social": "XYZ Distribuidora S.A.",
            "MUNICÃƒÆ’Ã‚ÂPIO": "Curitiba",
            "BAIRRO": "Industrial",
            "ENDEREÃƒÆ’Ã¢â‚¬Â¡O": "Av. IndÃƒÆ’Ã‚Âºstria, 500",
            "FONE": "(41) 99999-0000",
            "SEGMENTO": "LogÃƒÆ’Ã‚Â­stica",
            "STATUS": "Ativo",
        },
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=planilha_clientes_modelo.xlsx"},
    )


@app.get("/clients/import")
async def clients_import_get(request: Request):
    """Redireciona para /clients se acessar /clients/import via GET."""
    require_login(request)
    return RedirectResponse(url="/clients", status_code=status.HTTP_303_SEE_OTHER)


def _load_clients_dataframe(content: bytes, filename: str):
    """Carrega CSV ou Excel em DataFrame."""
    import pandas as pd
    ext = (filename or "").lower()
    if ext.endswith(".csv"):
        try:
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig", sep=None, engine="python")
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(content), encoding="latin-1", sep=None, engine="python")
    elif ext.endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl", header=0)
    elif ext.endswith(".xls"):
        df = pd.read_excel(io.BytesIO(content), engine="xlrd", header=0)
    else:
        raise ValueError("Formato invÃƒÆ’Ã‚Â¡lido")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _opt_val(v) -> Optional[str]:
    """Converte valor da planilha em string ou None."""
    import pandas as pd
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


@app.post("/clients/import", response_class=RedirectResponse)
async def clients_import(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    """ImportaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o com normalizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o e deduplicaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o. Redireciona para tela de conflitos se houver duplicados."""
    require_login(request)
    user = request.session.get("username", "")
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        return RedirectResponse(url="/clients?error=invalid_file", status_code=status.HTTP_303_SEE_OTHER)
    try:
        import pandas as pd
        content = await file.read()
        df = _load_clients_dataframe(content, file.filename)
        col_map = find_client_col_map(list(df.columns))

        name_col = col_map.get("fantas") or col_map.get("razao_social")
        if name_col is None and len(df.columns) >= 1:
            name_col = df.columns[0]
        if name_col is None:
            return RedirectResponse(url="/clients?error=missing_columns", status_code=status.HTTP_303_SEE_OTHER)

        # ÃƒÆ’Ã‚Ândices para dedup (fone_e164, endereco_normalizado, razao+bairro)
        all_clients = list(session.exec(select(models.Client)).all())
        existing_by_fone = {}
        existing_by_endereco = {}
        existing_by_razao_bairro_key = {}
        for c in all_clients:
            fe164 = c.fone_e164
            if not fe164 and c.fone:
                fe164, _ = normalize_phone_br(c.fone)
            if fe164:
                existing_by_fone[fe164] = c.id
            eaddr = c.endereco_normalizado or (normalize_address(c.endereco).upper().replace(" ", "") if c.endereco and len(c.endereco) >= 10 else None)
            if eaddr:
                existing_by_endereco[eaddr] = c.id
            rk, bk = normalize_key(c.razao_social or c.name or ""), normalize_key(c.bairro or "")
            if rk and bk:
                existing_by_razao_bairro_key[(rk, bk)] = c.id
        existing_names = {n[0].strip().lower() for n in session.exec(select(models.Client.name)).all()}

        batch = models.ClientImportBatch(filename=file.filename, created_by=user)
        session.add(batch)
        session.flush()

        rows_clean = []
        rows_conflict = []

        for idx, row in df.iterrows():
            name_raw = row.get(name_col)
            if pd.isna(name_raw):
                continue
            name = _opt_val(name_raw)
            if not name or len(name) < 2:
                continue

            nb = _opt_val(row.get(col_map.get("nb"))) if "nb" in col_map else None
            setor = _opt_val(row.get(col_map.get("setor"))) if "setor" in col_map else None
            me = _opt_val(row.get(col_map.get("me"))) if "me" in col_map else None
            sa = _opt_val(row.get(col_map.get("sa"))) if "sa" in col_map else None
            visita = _opt_val(row.get(col_map.get("visita"))) if "visita" in col_map else None
            nome_fantasia = _opt_val(row.get(col_map.get("fantas"))) if "fantas" in col_map else None
            razao_social = _opt_val(row.get(col_map.get("razao_social"))) if "razao_social" in col_map else None
            municipio = _opt_val(row.get(col_map.get("municipio"))) if "municipio" in col_map else None
            bairro = _opt_val(row.get(col_map.get("bairro"))) if "bairro" in col_map else None
            endereco_raw = _opt_val(row.get(col_map.get("endereco"))) if "endereco" in col_map else None
            fone_raw = _opt_val(row.get(col_map.get("fone"))) if "fone" in col_map else None
            segmento = _opt_val(row.get(col_map.get("segmento"))) if "segmento" in col_map else None
            status_cliente = _opt_val(row.get(col_map.get("status"))) if "status" in col_map else None

            endereco = normalize_address(endereco_raw) if endereco_raw else None
            endereco_norm = normalize_address(endereco_raw).upper().replace(" ", "") if endereco_raw else None
            fone_e164, fone_amigavel = normalize_phone_br(fone_raw)
            fone = fone_amigavel or fone_raw
            municipio_key = normalize_key(municipio)
            bairro_key = normalize_key(bairro)
            razao_key = normalize_key(razao_social or name)

            conflict_type = None
            conflict_client_id = None
            if fone_e164 and fone_e164 in existing_by_fone:
                conflict_type = "fone"
                conflict_client_id = existing_by_fone.get(fone_e164)
            elif endereco_norm and len(endereco_norm) >= 10 and endereco_norm in existing_by_endereco:
                conflict_type = "endereco"
                conflict_client_id = existing_by_endereco.get(endereco_norm)
            elif razao_key and bairro_key and (razao_key, bairro_key) in existing_by_razao_bairro_key:
                conflict_type = "razao_bairro"
                conflict_client_id = existing_by_razao_bairro_key.get((razao_key, bairro_key))

            if name.lower() in existing_names and not conflict_type:
                conflict_type = "nome"
                conflict_client_id = None

            staging = models.ClientImportStaging(
                batch_id=batch.id,
                row_index=int(idx),
                name=name,
                nb=nb,
                setor=setor,
                me=me,
                sa=sa,
                visita=visita,
                nome_fantasia=nome_fantasia,
                razao_social=razao_social,
                municipio=municipio,
                bairro=bairro,
                endereco=endereco or endereco_raw,
                endereco_normalizado=endereco_norm,
                fone=fone,
                fone_e164=fone_e164,
                segmento=segmento,
                status_cliente=status_cliente,
                municipio_key=municipio_key,
                bairro_key=bairro_key,
                conflict_type=conflict_type,
                conflict_client_id=conflict_client_id,
                action="create" if not conflict_type else "pending",
            )
            session.add(staging)
            if conflict_type:
                rows_conflict.append(staging)
            else:
                rows_clean.append(staging)

        session.commit()

        if rows_conflict:
            return RedirectResponse(url=f"/clients/import/conflicts/{batch.id}", status_code=status.HTTP_303_SEE_OTHER)

        log_created, log_rejected = 0, 0
        for s in rows_clean:
            if s.name.lower() in existing_names:
                log_rejected += 1
                continue
            c = models.Client(
                name=s.name,
                nb=s.nb,
                setor=s.setor,
                me=s.me,
                sa=s.sa,
                visita=s.visita,
                nome_fantasia=s.nome_fantasia,
                razao_social=s.razao_social,
                municipio=s.municipio,
                bairro=s.bairro,
                endereco=s.endereco,
                endereco_normalizado=s.endereco_normalizado,
                fone=s.fone,
                fone_e164=s.fone_e164,
                segmento=s.segmento,
                status_cliente=s.status_cliente,
            )
            session.add(c)
            existing_names.add(s.name.lower())
            log_created += 1
        batch.status = "completed"
        batch.log_created = log_created
        batch.log_rejected = log_rejected
        session.add(batch)
        session.exec(delete(models.ClientImportStaging).where(models.ClientImportStaging.batch_id == batch.id))
        session.commit()
        return RedirectResponse(
            url=f"/clients?message=import_success&created={log_created}&rejected={log_rejected}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except ValueError as e:
        return RedirectResponse(url=f"/clients?error=invalid_file", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        logger.exception(f"Clients import error: {e}")
        return RedirectResponse(url="/clients?error=import_failed", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/clients/import/conflicts/{batch_id}", response_class=HTMLResponse)
async def clients_import_conflicts(request: Request, batch_id: int, session: Session = Depends(get_session)):
    require_login(request)
    batch = session.get(models.ClientImportBatch, batch_id)
    if not batch or batch.status != "pending":
        return RedirectResponse(url="/clients", status_code=status.HTTP_303_SEE_OTHER)
    rows = session.exec(
        select(models.ClientImportStaging)
        .where(models.ClientImportStaging.batch_id == batch_id)
        .order_by(models.ClientImportStaging.row_index)
    ).all()
    conflict_rows = [r for r in rows if r.conflict_type]
    conflict_map = {}
    for r in conflict_rows:
        if r.conflict_client_id:
            c = session.get(models.Client, r.conflict_client_id)
            if c:
                conflict_map[r.id] = c
    return templates.TemplateResponse("clients_import_conflicts.html", {
        "request": request,
        "user": request.session.get("username", ""),
        "batch": batch,
        "rows": rows,
        "conflict_rows": conflict_rows,
        "conflict_map": conflict_map,
    })


@app.post("/clients/import/confirm/{batch_id}", response_class=RedirectResponse)
async def clients_import_confirm(
    request: Request,
    batch_id: int,
    session: Session = Depends(get_session)
):
    require_login(request)
    batch = session.get(models.ClientImportBatch, batch_id)
    if not batch or batch.status != "pending":
        return RedirectResponse(url="/clients", status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    form_actions = {k.replace("action_", ""): v for k, v in form.items() if k.startswith("action_")}
    log_created, log_updated, log_skipped, log_rejected = 0, 0, 0, 0
    existing_names = {n[0].strip().lower() for n in session.exec(select(models.Client.name)).all()}
    rows = session.exec(
        select(models.ClientImportStaging).where(models.ClientImportStaging.batch_id == batch_id).order_by(models.ClientImportStaging.row_index)
    ).all()
    for row in rows:
        action = form_actions.get(str(row.id), row.action)
        if action == "skip":
            log_skipped += 1
            continue
        if action == "merge" and row.conflict_client_id:
            client = session.get(models.Client, row.conflict_client_id)
            if client:
                client.nb = row.nb or client.nb
                client.setor = row.setor or client.setor
                client.me = row.me or client.me
                client.sa = row.sa or client.sa
                client.visita = row.visita or client.visita
                client.nome_fantasia = row.nome_fantasia or client.nome_fantasia
                client.razao_social = row.razao_social or client.razao_social
                client.municipio = row.municipio or client.municipio
                client.bairro = row.bairro or client.bairro
                client.endereco = row.endereco or client.endereco
                client.endereco_normalizado = row.endereco_normalizado or client.endereco_normalizado
                client.fone = row.fone or client.fone
                client.fone_e164 = row.fone_e164 or client.fone_e164
                client.segmento = row.segmento or client.segmento
                client.status_cliente = row.status_cliente or client.status_cliente
                session.add(client)
                log_updated += 1
        elif action == "create":
            if row.name.lower() in existing_names:
                log_rejected += 1
            else:
                c = models.Client(
                    name=row.name,
                    nb=row.nb,
                    setor=row.setor,
                    me=row.me,
                    sa=row.sa,
                    visita=row.visita,
                    nome_fantasia=row.nome_fantasia,
                    razao_social=row.razao_social,
                    municipio=row.municipio,
                    bairro=row.bairro,
                    endereco=row.endereco,
                    endereco_normalizado=row.endereco_normalizado,
                    fone=row.fone,
                    fone_e164=row.fone_e164,
                    segmento=row.segmento,
                    status_cliente=row.status_cliente,
                )
                session.add(c)
                existing_names.add(row.name.lower())
                log_created += 1
    batch.status = "completed"
    batch.log_created = log_created
    batch.log_updated = log_updated
    batch.log_skipped = log_skipped
    batch.log_rejected = log_rejected
    session.add(batch)
    session.exec(delete(models.ClientImportStaging).where(models.ClientImportStaging.batch_id == batch_id))
    session.commit()
    return RedirectResponse(
        url=f"/clients?message=import_confirm&created={log_created}&updated={log_updated}&skipped={log_skipped}&rejected={log_rejected}",
        status_code=status.HTTP_303_SEE_OTHER
    )


# --- Vehicle (Frota) Routes ---
@app.get("/vehicles", response_class=HTMLResponse)
async def vehicles_page(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    vehicles = session.exec(select(models.Vehicle).order_by(models.Vehicle.placa)).all()
    total = len(vehicles)
    by_type = {"caminhao": 0, "moto": 0, "carro": 0}
    for v in vehicles:
        t = (v.vehicle_type or "").lower()
        if t in by_type:
            by_type[t] += 1
    pct_c = round(100 * by_type["caminhao"] / total, 1) if total else 0
    pct_m = round(100 * by_type["moto"] / total, 1) if total else 0
    pct_r = round(100 * by_type["carro"] / total, 1) if total else 0
    stats = {
        "total": total,
        "caminhao_count": by_type["caminhao"],
        "moto_count": by_type["moto"],
        "carro_count": by_type["carro"],
        "caminhao_pct": pct_c,
        "moto_pct": pct_m,
        "carro_pct": pct_r,
    }
    # Segmentos do grÃƒÆ’Ã‚Â¡fico pizza (SVG) para tooltip no hover: ÃƒÆ’Ã‚Â¢ngulo comeÃƒÆ’Ã‚Â§a no topo (-90Ãƒâ€šÃ‚Â°)
    def deg2xy(deg):
        rad = math.radians(deg - 90)
        return (50 + 40 * math.cos(rad), 50 + 40 * math.sin(rad))
    a0, a1 = 0, 360 * (by_type["caminhao"] / total) if total else 0
    a2 = a1 + 360 * (by_type["moto"] / total) if total else 0
    pie_slices = []
    for (start, end, fill, label, count, pct) in [
        (a0, a1, "#f59e0b", "CaminhÃƒÆ’Ã‚Âµes", by_type["caminhao"], pct_c),
        (a1, a2, "#10b981", "Motos", by_type["moto"], pct_m),
        (a2, 360, "#3b82f6", "Carros", by_type["carro"], pct_r),
    ]:
        x1, y1 = deg2xy(start)
        x2, y2 = deg2xy(end)
        large = 1 if (end - start) > 180 else 0
        d = f"M 50 50 L {x1:.2f} {y1:.2f} A 40 40 0 {large} 1 {x2:.2f} {y2:.2f} Z"
        pie_slices.append({"d": d, "fill": fill, "title": f"{label}: {count} ({pct}%)"})
    return templates.TemplateResponse(
        "vehicles.html",
        {"request": request, "user": user, "vehicles": vehicles, "stats": stats, "pie_slices": pie_slices}
    )


@app.get("/vehicles/new", response_class=HTMLResponse)
async def vehicle_new_page(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    return templates.TemplateResponse("vehicle_detail.html", {"request": request, "user": user, "vehicle": None})


@app.post("/vehicles/add", response_class=RedirectResponse)
async def add_vehicle(
    request: Request,
    placa: str = Form(...),
    vehicle_type: str = Form(...),
    marca: str = Form(...),
    modelo: str = Form(...),
    renavam: Optional[str] = Form(default=None),
    ano: Optional[str] = Form(default=None),
    crv_number: Optional[str] = Form(default=None),
    chassi: Optional[str] = Form(default=None),
    session: Session = Depends(get_session)
):
    require_login(request)
    placa = placa.strip().upper()
    if vehicle_type not in ("caminhao", "moto", "carro"):
        return RedirectResponse(url="/vehicles/new?error=invalid_type", status_code=status.HTTP_303_SEE_OTHER)
    existing = session.exec(select(models.Vehicle).where(models.Vehicle.placa == placa)).first()
    if existing:
        return RedirectResponse(url="/vehicles/new?error=placa_exists", status_code=status.HTTP_303_SEE_OTHER)
    def _opt(s): return (s or "").strip() or None
    new_vehicle = models.Vehicle(
        placa=placa, vehicle_type=vehicle_type, marca=marca, modelo=modelo,
        renavam=_opt(renavam), ano=_opt(ano), crv_number=_opt(crv_number), chassi=_opt(chassi)
    )
    session.add(new_vehicle)
    session.commit()
    return RedirectResponse(url="/vehicles?message=vehicle_created", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/vehicles/template")
async def vehicles_template(request: Request):
    """Retorna planilha Excel modelo para importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de veÃƒÆ’Ã‚Â­culos."""
    import io
    import pandas as pd
    require_login(request)
    df = pd.DataFrame([{
        "Placa": "ABC1234",
        "VeÃƒÆ’Ã‚Â­culo": "CaminhÃƒÆ’Ã‚Â£o",
        "Marca": "FORD",
        "Modelo": "CARGO 815/E",
        "Renavam": "306637642",
        "Ano": "2010/2011",
        "NÃƒâ€šÃ‚Âº do CRV": "8323093847",
        "CHASSI": "9BFVCE1NOBBB61839",
    }, {
        "Placa": "XYZ9876",
        "VeÃƒÆ’Ã‚Â­culo": "Moto",
        "Marca": "HONDA",
        "Modelo": "CG 160 CARGO",
        "Renavam": "1203972285",
        "Ano": "2021/2022",
        "NÃƒâ€šÃ‚Âº do CRV": "14946217335",
        "CHASSI": "9BFZH55L5L8413592",
    }, {
        "Placa": "DEF4567",
        "VeÃƒÆ’Ã‚Â­culo": "Carro",
        "Marca": "TOYOTA",
        "Modelo": "ETIOS HB X VSC MT",
        "Renavam": "",
        "Ano": "2019/2019",
        "NÃƒâ€šÃ‚Âº do CRV": "",
        "CHASSI": "",
    }])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=planilha_veiculos_modelo.xlsx"},
    )


@app.get("/vehicles/import")
async def vehicles_import_get(request: Request):
    """Redireciona para /vehicles se acessar /vehicles/import via GET (ex: barra de endereÃƒÆ’Ã‚Â§o)."""
    require_login(request)
    return RedirectResponse(url="/vehicles", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/vehicles/import", response_class=RedirectResponse)
async def vehicles_import(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    require_login(request)
    if not file.filename or (not file.filename.lower().endswith((".xlsx", ".xls"))):
        return RedirectResponse(url="/vehicles?error=invalid_file", status_code=status.HTTP_303_SEE_OTHER)
    try:
        import pandas as pd
        content = await file.read()
        engine = "openpyxl" if file.filename.lower().endswith(".xlsx") else "xlrd"

        def norm(s: str) -> str:
            s = (s or "").strip().lower()
            return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")

        def find_col_map(columns) -> dict:
            col_map = {}
            keywords = {
                "placa": ["placa"],
                "veiculo": ["veiculo", "veÃƒÆ’Ã‚Â­culo"],
                "marca": ["marca"],
                "modelo": ["modelo"],
                "renavam": ["renavam"],
                "ano": ["ano"],
                "crv": ["crv", "nÃƒâ€šÃ‚Âº do crv", "numero crv"],
                "chassi": ["chassi"],
            }
            for std, kws in keywords.items():
                for c in columns:
                    cn = norm(str(c))
                    for kw in kws:
                        kn = norm(kw)
                        if cn == kn or kn in cn:
                            col_map[std] = c
                            break
                    if std in col_map:
                        break
            return col_map

        df = pd.read_excel(io=content, engine=engine, header=0)
        df.columns = [str(c).strip() for c in df.columns]
        col_map = find_col_map(df.columns)

        # Fallback: se header na linha 0 nÃƒÆ’Ã‚Â£o tem as colunas, tenta linha 1
        if ("placa" not in col_map or "veiculo" not in col_map or "marca" not in col_map or "modelo" not in col_map):
            df2 = pd.read_excel(io=content, engine=engine, header=1)
            df2.columns = [str(c).strip() for c in df2.columns]
            col_map2 = find_col_map(df2.columns)
            if all(k in col_map2 for k in ["placa", "veiculo", "marca", "modelo"]):
                df, col_map = df2, col_map2

        # Fallback: mapeamento posicional (ordem padrÃƒÆ’Ã‚Â£o: Placa, VeÃƒÆ’Ã‚Â­culo, Marca, Modelo, ...)
        if ("placa" not in col_map or "veiculo" not in col_map or "marca" not in col_map or "modelo" not in col_map):
            if len(df.columns) >= 4:
                ordem = ["placa", "veiculo", "marca", "modelo", "renavam", "ano", "crv", "chassi"]
                col_map = {ordem[i]: df.columns[i] for i in range(min(len(ordem), len(df.columns)))}

        if "placa" not in col_map or "veiculo" not in col_map or "marca" not in col_map or "modelo" not in col_map:
            return RedirectResponse(url="/vehicles?error=missing_columns", status_code=status.HTTP_303_SEE_OTHER)
        def to_type(v):
            if pd.isna(v): return "carro"
            s = str(v).strip().lower()
            if "caminh" in s or "caminhao" in s: return "caminhao"
            if "moto" in s: return "moto"
            return "carro"
        def _opt(v):
            if pd.isna(v): return None
            s = str(v).strip()
            return s if s else None
        existing_placas = {p[0] for p in session.exec(select(models.Vehicle.placa)).all()}
        imported = 0
        skipped = 0
        for _, row in df.iterrows():
            placa_raw = row.get(col_map["placa"])
            if pd.isna(placa_raw): continue
            placa = str(placa_raw).strip().upper().replace(" ", "")
            if not placa or len(placa) < 5: continue
            if placa in existing_placas:
                skipped += 1
                continue
            marca = str(row.get(col_map.get("marca"), "")).strip() or "N/A"
            modelo = str(row.get(col_map.get("modelo"), "")).strip() or "N/A"
            v = models.Vehicle(
                placa=placa,
                vehicle_type=to_type(row.get(col_map.get("veiculo"))),
                marca=marca,
                modelo=modelo,
                renavam=_opt(row.get(col_map.get("renavam"))) if "renavam" in col_map else None,
                ano=_opt(row.get(col_map.get("ano"))) if "ano" in col_map else None,
                crv_number=_opt(row.get(col_map.get("crv"))) if "crv" in col_map else None,
                chassi=_opt(row.get(col_map.get("chassi"))) if "chassi" in col_map else None,
            )
            session.add(v)
            existing_placas.add(placa)
            imported += 1
        session.commit()
        return RedirectResponse(
            url=f"/vehicles?message=import_success&imported={imported}&skipped={skipped}",
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        logger.exception(f"Vehicle import error: {e}")
        return RedirectResponse(url="/vehicles?error=import_failed", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/vehicles/{vehicle_id}", response_class=HTMLResponse)
async def vehicle_detail_page(request: Request, vehicle_id: int, session: Session = Depends(get_session)):
    user = require_login(request)
    vehicle = session.get(models.Vehicle, vehicle_id)
    if not vehicle:
        return RedirectResponse(url="/vehicles")
    return templates.TemplateResponse("vehicle_detail.html", {"request": request, "user": user, "vehicle": vehicle})


@app.get("/vehicles/{vehicle_id}/history", response_class=HTMLResponse)
async def vehicle_history_page(request: Request, vehicle_id: int, session: Session = Depends(get_session)):
    """HistÃƒÆ’Ã‚Â³rico do caminhÃƒÆ’Ã‚Â£o: checklists e futuramente manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o, motoristas."""
    user = require_login(request)
    vehicle = session.get(models.Vehicle, vehicle_id)
    if not vehicle:
        return RedirectResponse(url="/vehicles")
    placa_norm = (vehicle.placa or "").strip().upper()
    checklists = session.exec(
        select(models.TranspalletChecklist)
        .where(func.upper(models.TranspalletChecklist.equipment_code) == placa_norm)
        .order_by(desc(models.TranspalletChecklist.date), desc(models.TranspalletChecklist.submitted_at))
    ).all()
    emp_ids = {c.employee_id for c in checklists}
    emp_map = {}
    if emp_ids:
        emps = session.exec(select(models.Employee).where(col(models.Employee.id).in_(list(emp_ids)))).all()
        emp_map = {e.id: e.name for e in emps}
    rows = []
    for c in checklists:
        odom = getattr(c, "odometer_km", None)
        shift_norm = normalize_shift(getattr(c, "shift", None))
        shift_disp = shift_display_label(shift_norm)
        rows.append({
            "id": c.id,
            "date": c.date,
            "date_fmt": datetime.strptime(c.date, "%Y-%m-%d").strftime("%d/%m/%Y") if c.date else "-",
            "shift": c.shift,
            "shift_display": shift_disp,
            "employee_name": emp_map.get(c.employee_id, "Desconhecido"),
            "odometer_km": odom,
            "odometer_fmt": f"{odom:,.0f}".replace(",", ".") if odom is not None else "-",
            "status": c.status,
            "critical": c.critical_flag,
            "nonconforming": bool(c.nonconforming_keys),
            "submitted_at": c.submitted_at.strftime("%d/%m %H:%M") if c.submitted_at else "-",
        })
    # ÃƒÆ’Ã…Â¡ltimo KM: do veÃƒÆ’Ã‚Â­culo (atualizado por checklist/ediÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o) ou do ÃƒÆ’Ã‚Âºltimo checklist
    last_km = getattr(vehicle, "odometer_km", None)
    if last_km is None and rows:
        last_km = rows[0].get("odometer_km")
    last_km_fmt = f"{last_km:,.0f}".replace(",", ".") if last_km is not None else None
    return templates.TemplateResponse(
        "vehicle_history.html",
        {"request": request, "user": user, "vehicle": vehicle, "checklists": rows, "last_km": last_km, "last_km_fmt": last_km_fmt}
    )


@app.post("/vehicles/{vehicle_id}/update", response_class=RedirectResponse)
async def update_vehicle(
    request: Request,
    vehicle_id: int,
    placa: str = Form(...),
    vehicle_type: str = Form(...),
    marca: str = Form(...),
    modelo: str = Form(...),
    renavam: Optional[str] = Form(default=None),
    ano: Optional[str] = Form(default=None),
    crv_number: Optional[str] = Form(default=None),
    chassi: Optional[str] = Form(default=None),
    odometer_km: Optional[str] = Form(default=None),
    in_workshop: Optional[str] = Form(default=None),
    sale_value: Optional[str] = Form(default=None),
    sold_at: Optional[str] = Form(default=None),
    session: Session = Depends(get_session)
):
    require_login(request)
    vehicle = session.get(models.Vehicle, vehicle_id)
    if not vehicle:
        return RedirectResponse(url="/vehicles")
    placa = placa.strip().upper()
    if vehicle_type not in ("caminhao", "moto", "carro"):
        return RedirectResponse(url=f"/vehicles/{vehicle_id}?error=invalid_type", status_code=status.HTTP_303_SEE_OTHER)
    other = session.exec(select(models.Vehicle).where(models.Vehicle.placa == placa, models.Vehicle.id != vehicle_id)).first()
    if other:
        return RedirectResponse(url=f"/vehicles/{vehicle_id}?error=placa_exists", status_code=status.HTTP_303_SEE_OTHER)
    def _opt(s): return (s or "").strip() or None
    vehicle.placa = placa
    vehicle.vehicle_type = vehicle_type
    vehicle.marca = marca
    vehicle.modelo = modelo
    vehicle.renavam = _opt(renavam)
    vehicle.ano = _opt(ano)
    vehicle.crv_number = _opt(crv_number)
    vehicle.chassi = _opt(chassi)
    vehicle.in_workshop = in_workshop == "on" or in_workshop == "1"
    try:
        val = (sale_value or "").strip().replace(".", "").replace(",", ".")
        vehicle.sale_value = float(val) if val else None
    except (ValueError, TypeError):
        vehicle.sale_value = None
    if sold_at and _opt(sold_at):
        try:
            vehicle.sold_at = datetime.strptime(_opt(sold_at), "%Y-%m-%d")
        except (ValueError, TypeError):
            vehicle.sold_at = None
    elif vehicle.sale_value:
        vehicle.sold_at = vehicle.sold_at or datetime.now()
    else:
        vehicle.sold_at = None
    try:
        km_str = (odometer_km or "").strip().replace(",", ".")
        vehicle.odometer_km = float(km_str) if km_str else None
    except (ValueError, TypeError):
        vehicle.odometer_km = None
    vehicle.updated_at = datetime.now()
    session.add(vehicle)
    session.commit()
    return RedirectResponse(url=f"/vehicles/{vehicle_id}?message=vehicle_updated", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/vehicles/{vehicle_id}/workshop", response_class=RedirectResponse)
async def vehicle_toggle_workshop(request: Request, vehicle_id: int, session: Session = Depends(get_session)):
    """Alterna status 'na oficina' do veÃƒÆ’Ã‚Â­culo."""
    require_login(request)
    vehicle = session.get(models.Vehicle, vehicle_id)
    if vehicle:
        vehicle.in_workshop = not vehicle.in_workshop
        vehicle.updated_at = datetime.now()
        session.add(vehicle)
        session.commit()
    return RedirectResponse(url=request.headers.get("referer", "/vehicles"), status_code=status.HTTP_303_SEE_OTHER)


@app.post("/vehicles/{vehicle_id}/delete", response_class=RedirectResponse)
async def delete_vehicle(request: Request, vehicle_id: int, session: Session = Depends(get_session)):
    require_login(request)
    vehicle = session.get(models.Vehicle, vehicle_id)
    if vehicle:
        session.delete(vehicle)
        session.commit()
    return RedirectResponse(url="/vehicles", status_code=status.HTTP_303_SEE_OTHER)


# --- Route Management ---
# --- SeparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de Mercadorias Management ---
def _norm_text(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def _norm_plate(v: Any) -> str:
    if v is None:
        return ""
    return "".join(ch for ch in str(v).upper().strip() if ch.isalnum())


def _as_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _maps_link(address: Optional[str], bairro: Optional[str], cidade: Optional[str], estado: Optional[str], cep: Optional[str]) -> str:
    parts = [p for p in [address, bairro, cidade, estado, cep] if p]
    return "https://www.google.com/maps/search/?api=1&query=" + urlencode({"": " ".join(parts)})[1:]


DELIVERY_RETURN_REASONS = {
    "COMERCIAL": [
        "PEDIDO / PRODUTO ERRADO",
        "CLIENTE NÃƒÆ’Ã†â€™O FEZ PEDIDO",
        "PRAZO ERRADO",
        "PREÃƒÆ’Ã¢â‚¬Â¡O ERRADO",
        "SEM VASILHAME",
        "FORMA DE PAGAMENTO ERRADA",
        "VENDEDOR NÃƒÆ’Ã†â€™O PASSOU",
        "TROCAS NÃƒÆ’Ã†â€™O AUTORIZADAS",
        "TROCAS NÃƒÆ’Ã†â€™O ENVIADAS",
    ],
    "MERCADO": [
        "HORÃƒÆ’Ã‚ÂRIO ENTREGA",
        "PONTO VENDA FECHADO / AUSENTE",
        "SEM DINHEIRO / CHEQUE",
        "CLIENTE DESISTIU DA COMPRA",
    ],
    "LOGÃƒÆ’Ã‚ÂSTICA": [
        "DIFÃƒÆ’Ã‚ÂCIL ACESSO",
        "PRODUTO DANIFICADO E/OU FALTA",
        "LOCAL ENTREGA NÃƒÆ’Ã†â€™O LOCALIZADA",
        "ÃƒÆ’Ã‚ÂREA DE RISCO",
        "CAMINHÃƒÆ’Ã†â€™O QUEBRADO NA ROTA",
        "FURTO / ROUBO",
        "QUANTIDADE ERRADA CARREGAMENTO",
        "PEDIDO NÃƒÆ’Ã†â€™O ENTREGUE",
        "FALTA DE PRODUTO NO ESTOQUE",
    ],
}
DELIVERY_RETURN_REASONS_FLAT = [reason for reasons in DELIVERY_RETURN_REASONS.values() for reason in reasons]


def _validate_delivery_assignment(
    session: Session,
    date: str,
    employee_id: int,
    vehicle_plate: str,
    exclude_route_id: Optional[int] = None,
    ignore_employee_id: Optional[int] = None,
) -> Optional[str]:
    plate_norm = _norm_plate(vehicle_plate)
    if not plate_norm:
        logger.warning(f"ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â« ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o falhou: Placa invÃƒÆ’Ã‚Â¡lida '{vehicle_plate}'")
        return "Placa invÃƒÆ’Ã‚Â¡lida."

    rows = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == date)
    ).all()

    logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â Validando troca: motorista_id={employee_id}, placa={plate_norm}, data={date}, total_entregas={len(rows)}")
    logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â ParÃƒÆ’Ã‚Â¢metros: exclude_route_id={exclude_route_id}, ignore_employee_id={ignore_employee_id}")

    # Regra 1: motorista nÃƒÆ’Ã‚Â£o pode ter mais de um caminhÃƒÆ’Ã‚Â£o no mesmo dia
    driver_plates = set()
    for r in rows:
        if exclude_route_id and r.id == exclude_route_id:
            continue
        if r.employee_id == employee_id and r.delivery_vehicle_plate:
            driver_plates.add(_norm_plate(r.delivery_vehicle_plate))
    
    logger.info(f"ÃƒÂ°Ã…Â¸Ã…Â¡Ã¢â‚¬â€ CaminhÃƒÆ’Ã‚Âµes jÃƒÆ’Ã‚Â¡ vinculados ao motorista {employee_id}: {driver_plates}")
    
    if driver_plates and (len(driver_plates) > 1 or plate_norm not in driver_plates):
        existing = next(iter(driver_plates))
        error_msg = f"Motorista jÃƒÆ’Ã‚Â¡ vinculado a outro caminhÃƒÆ’Ã‚Â£o no dia ({existing})."
        logger.warning(f"ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â« Regra 1 violada: {error_msg}")
        return error_msg

    # Regra 2: caminhÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o pode estar em dois motoristas
    plate_drivers = set()
    for r in rows:
        if exclude_route_id and r.id == exclude_route_id:
            continue
        if ignore_employee_id and r.employee_id == ignore_employee_id:
            continue
        if _norm_plate(r.delivery_vehicle_plate) == plate_norm and r.employee_id:
            plate_drivers.add(r.employee_id)
    
    logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ËœÃ‚Â¥ Motoristas jÃƒÆ’Ã‚Â¡ vinculados ao caminhÃƒÆ’Ã‚Â£o {plate_norm}: {plate_drivers}")
    
    if plate_drivers and (len(plate_drivers) > 1 or employee_id not in plate_drivers):
        error_msg = "CaminhÃƒÆ’Ã‚Â£o jÃƒÆ’Ã‚Â¡ vinculado a outro motorista no dia."
        logger.warning(f"ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â« Regra 2 violada: {error_msg}")
        return error_msg
    
    logger.info(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o passou: motorista {employee_id} pode usar caminhÃƒÆ’Ã‚Â£o {plate_norm}")

    return None


def _delivery_col_map(columns: List[str]) -> dict:
    normalized = {_norm_text(c): c for c in columns}

    aliases = {
        "route_code": ["n rota", "nÃƒâ€šÃ‚Âº rota", "nÃƒâ€šÃ‚Â° rota", "no rota", "numero rota", "rota"],
        "plate": ["placa veiculo", "placa", "veiculo", "placa do veiculo"],
        "driver": ["motorista", "nome motorista"],
        "order_number": ["pedidos", "pedido", "n pedido", "numero pedido"],
        "order_date": ["data do pedido", "data pedido"],
        "client_code": ["cod cliente", "codigo cliente", "id cliente"],
        "client_name": ["razao social", "cliente", "nome cliente"],
        "cep": ["cep"],
        "address": ["endereco", "logradouro"],
        "bairro": ["bairro"],
        "city": ["cidades", "cidade", "municipio"],
        "state": ["estado", "uf"],
        "peso_pedido": ["peso pedido", "peso", "peso da entrega"],
        "peso_total": ["peso total"],
        "valor": ["valor", "valor pedido"],
        "tipo": ["tipo"],
    }

    out = {}
    for key, options in aliases.items():
        found = None
        for opt in options:
            if opt in normalized:
                found = normalized[opt]
                break
        if not found:
            for norm_name, original in normalized.items():
                compact = norm_name.replace(" ", "")
                if any(compact == opt.replace(" ", "") or norm_name.startswith(opt) for opt in options):
                    found = original
                    break
        out[key] = found
    return out


def _append_delivery_event(route: models.Route, event_type: str, time_str: str, note: Optional[str] = None) -> None:
    try:
        history = json.loads(route.delivery_time_log) if route.delivery_time_log else []
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []
    history.append({
        "event": event_type,
        "time": time_str,
        "at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
        "note": note,
    })
    route.delivery_time_log = json.dumps(history, ensure_ascii=False)


def _build_delivery_sync_token(rows: List[models.Route], date: str, shift: str) -> str:
    parts = [date or "", shift or "", str(len(rows))]
    for r in sorted(rows, key=lambda x: (x.id or 0)):
        parts.append("|".join([
            str(r.id or ""),
            str(r.employee_id or ""),
            str(r.client_id or ""),
            str(r.shift or ""),
            str(r.status or ""),
            str(r.delivery_status or ""),
            str(r.delivery_vehicle_plate or ""),
            str(r.delivery_return_category or ""),
            str(r.delivery_return_reason or ""),
            str(r.delivery_started_at or ""),
            str(r.delivery_finished_at or ""),
            str(r.delivery_returned_at or ""),
            str(r.delivery_reopen_count or 0),
            str(r.devolucao_volume if r.devolucao_volume is not None else ""),
            str(r.valor_devolucao if r.valor_devolucao is not None else ""),
            str(r.tonnage if r.tonnage is not None else ""),
            str(r.valor_financeiro if r.valor_financeiro is not None else ""),
            str(r.delivery_time_log or ""),
        ]))
    raw = "||".join(parts).encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def _find_employee_by_driver_name(name: str, employees: List[models.Employee]) -> Optional[models.Employee]:
    target = _norm_text(name)
    if not target:
        logger.debug(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â Busca motorista: nome vazio")
        return None

    logger.debug(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â Buscando motorista: '{name}' (normalizado: '{target}')")
    
    # Busca exata
    exact = None
    for emp in employees:
        if _norm_text(emp.name) == target:
            exact = emp
            break
    if exact:
        logger.debug(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Motorista encontrado (exato): {exact.name}")
        return exact

    target_tokens = {t for t in target.split() if t}
    if not target_tokens:
        logger.debug(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Nenhum token vÃƒÆ’Ã‚Â¡lido em '{target}'")
        return None

    # Caso comum de abreviaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de 1 palavra (ex.: "FERNANDO"):
    # prioriza colaborador cujo nome COMEÃƒÆ’Ã¢â‚¬Â¡A com a palavra.
    if len(target_tokens) == 1:
        token = next(iter(target_tokens))
        starts_with_matches = []
        for emp in employees:
            emp_norm = _norm_text(emp.name)
            if emp_norm.startswith(token + " ") or emp_norm == token:
                starts_with_matches.append(emp)
        if starts_with_matches:
            # Prioridade 1: cargo de motorista (ou variaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes)
            driver_matches = [
                emp for emp in starts_with_matches
                if "motorista" in _norm_text(getattr(emp, "role", "") or "")
            ]
            if len(driver_matches) == 1:
                return driver_matches[0]
            if len(driver_matches) > 1:
                # Em empate entre motoristas, usa nome mais curto (mais aderente ao nome simples da planilha)
                return sorted(driver_matches, key=lambda e: len(_norm_text(e.name)))[0]

            # Prioridade 2: se houver apenas um "comeÃƒÆ’Ã‚Â§a com", usa ele
            if len(starts_with_matches) == 1:
                return starts_with_matches[0]

            # Prioridade 3: fallback determinÃƒÆ’Ã‚Â­stico para evitar perda de importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
            return sorted(starts_with_matches, key=lambda e: len(_norm_text(e.name)))[0]

    # Caso o nome vindo da planilha seja abreviado (ex.: "GILMAR MARQUES")
    # e exista apenas um colaborador que contenha todos os tokens, associar.
    token_subset_matches = []
    for emp in employees:
        emp_tokens = {t for t in _norm_text(emp.name).split() if t}
        if target_tokens.issubset(emp_tokens):
            token_subset_matches.append(emp)
    if len(token_subset_matches) == 1:
        return token_subset_matches[0]

    best_emp = None
    best_score = 0.0
    for emp in employees:
        emp_norm = _norm_text(emp.name)
        emp_tokens = {t for t in emp_norm.split() if t}
        if not emp_tokens:
            continue
        overlap = len(target_tokens.intersection(emp_tokens))
        score = overlap / max(len(target_tokens), len(emp_tokens))
        if score > best_score:
            best_score = score
            best_emp = emp

    # threshold conservador para evitar associaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o errada
    if best_emp and best_score >= 0.75:
        logger.debug(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Motorista encontrado (similaridade {best_score:.0%}): {best_emp.name}")
        return best_emp
    
    logger.warning(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Motorista NÃƒÆ’Ã†â€™O encontrado: '{name}' (melhor match: {best_emp.name if best_emp else 'nenhum'}, score: {best_score:.0%})")
    return None


def _find_client(client_code_raw: Optional[str], client_name_raw: Optional[str], clients: List[models.Client]) -> Optional[models.Client]:
    target_name = _norm_text(client_name_raw)
    target_code = _norm_text(client_code_raw)
    target_code_nolead = _norm_text(str(client_code_raw).lstrip("0")) if client_code_raw else ""

    for c in clients:
        if c.nb:
            nb = _norm_text(c.nb)
            if target_code and (nb == target_code or nb == target_code_nolead):
                return c

    if target_code and str(client_code_raw).isdigit():
        try:
            cid = int(str(client_code_raw))
            for c in clients:
                if c.id == cid:
                    return c
        except Exception:
            pass

    for c in clients:
        names = [_norm_text(c.name), _norm_text(c.razao_social), _norm_text(c.nome_fantasia)]
        if target_name and target_name in names:
            return c

    if target_name:
        target_tokens = {t for t in target_name.split() if t}
        best_client = None
        best_score = 0.0
        for c in clients:
            candidate_name = _norm_text(c.razao_social or c.name or c.nome_fantasia)
            candidate_tokens = {t for t in candidate_name.split() if t}
            if not candidate_tokens:
                continue
            overlap = len(target_tokens.intersection(candidate_tokens))
            score = overlap / max(len(target_tokens), len(candidate_tokens))
            if score > best_score:
                best_score = score
                best_client = c
        if best_client and best_score >= 0.70:
            return best_client

    return None


@app.get("/separacao", response_class=HTMLResponse)
async def separacao_page(request: Request, date: Optional[str] = None, shift: str = "ManhÃƒÆ’Ã‚Â£", session: Session = Depends(get_session)):
    user = require_login(request)
    
    # Check for Mobile User
    current_emp_id = None
    is_mobile_user = False
    
    if isinstance(user, dict) and user.get("type") == "employee":
        current_emp_id = user.get("id")
        is_mobile_user = True
    
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    selected_date_obj = datetime.strptime(date, "%Y-%m-%d")
    suggested_input_date = (selected_date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
        
    # 1. Fetch DailyOperation
    daily_op = session.exec(
        select(models.DailyOperation)
        .where(models.DailyOperation.date == date)
        .where(models.DailyOperation.shift == shift)
    ).first()
    
    # 2. Filter Employees
    # Admin sees all active. Mobile sees only themselves.
    stmt = select(models.Employee).where(models.Employee.status != "fired")
    all_employees = session.exec(stmt).all()
    
    if is_mobile_user:
        eligible_employees = [e for e in all_employees if e.id == current_emp_id]
    else:
        # Filter by Active AND Shift
        # Note: We filter by shift loosely (if employee shift matches selected shift)
        # Assuming Employee model has a 'shift' field. If not, we just show all active.
        # Based on previous context, Employee has a shift field.
        eligible_employees = [e for e in all_employees if e.status == 'active' and e.work_shift == shift]
        eligible_employees.sort(key=lambda x: x.name)

    # 3. Fetch Clients
    clients = session.exec(select(models.Client)).all()
    cli_map = {c.id: c.name for c in clients}
    cli_display_map = {}
    cli_secondary_map = {}
    for c in clients:
        primary = c.razao_social or c.name or c.nome_fantasia or "Cliente"
        secondary_candidates = [c.nome_fantasia, c.name]
        secondary = None
        for cand in secondary_candidates:
            if cand and _norm_text(cand) != _norm_text(primary):
                secondary = cand
                break
        cli_display_map[c.id] = primary
        cli_secondary_map[c.id] = secondary

    # 4. Fetch Routes
    query = (
        select(models.Route)
        .where(models.Route.date == date)
        .where(models.Route.shift == shift)
        .where(or_(models.Route.type == None, models.Route.type == "separation"))
    )
    
    # Remove mobile restriction for viewing routes (User wants to see Team status)
    # query = query.order_by(models.Route.start_time)
    
    query = query.order_by(models.Route.start_time)
    db_routes = session.exec(query).all()

    # 5. Enrich
    # Create ID map for name lookup
    emp_map_id = {e.id: e for e in all_employees}

    # 5. Enrich
    routes_view = []
    
    def calc_productivity(start, end, tonnage):
        try:
            if not start: return 0.0
            t = tonnage if tonnage is not None else 0.0
            s = datetime.strptime(start, "%H:%M")
            if not end: return 0.0
            e = datetime.strptime(end, "%H:%M")
            diff = (e - s).total_seconds() / 3600 # hours
            if diff <= 0: diff = 0.016 # Min 1 minute (1/60 hr)
            
            # Kg/h
            if t <= 0: return 0.0
            return round(t / diff, 2)
        except Exception:
            return 0.0
            
    def fmt_num(n):
        val = n if n is not None else 0.0
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
    def calc_duration_str(start, end):
        if not start or not end: return None
        try:
            s = datetime.strptime(start, "%H:%M")
            e = datetime.strptime(end, "%H:%M")
            diff = (e - s).total_seconds()
            if diff < 0: return None
            hours = int(diff // 3600)
            mins = int((diff % 3600) // 60)
            return f"{hours:02d}h {mins:02d}m"
        except:
            return None

    for r in db_routes:
        prod = calc_productivity(r.start_time, r.end_time, r.tonnage)
        
        # Heuristic Fix for UTC Display
        display_start = r.start_time
        if r.start_time:
            try:
                # Assuming r.date is today for live view or using date from route
                # But start_time is just HH:MM. Let's assume today's date if date matches context
                # Simple check: current time vs start time
                now = datetime.now()
                s_dt = datetime.strptime(r.start_time, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                
                # If start time is 0-4h in future, correct it
                diff = (s_dt - now).total_seconds()
                if 0 < diff < 4 * 3600:
                    new_s = s_dt - timedelta(hours=3)
                    display_start = new_s.strftime("%H:%M")
            except: pass

        routes_view.append({
            "id": r.id,
            "start_time": display_start,
            "end_time": r.end_time,
            "tonnage": r.tonnage if r.tonnage is not None else 0.0,
            "tonnage_fmt": fmt_num(r.tonnage),
            "productivity": prod,
            "productivity_fmt": fmt_num(prod),
            "duration_fmt": calc_duration_str(display_start, r.end_time),
            "employee_name": emp_map_id.get(r.employee_id, models.Employee(name="Desconhecido")).name,
            "client_name": cli_map.get(r.client_id, "Desconhecido"),
            "employee_id": r.employee_id,
            "client_id": r.client_id
        })

    # Group by Employee
    from collections import defaultdict
    groups = {} 
    
    for r in routes_view:
        eid = r['employee_id']
        if eid not in groups:
            groups[eid] = {
                "employee_id": eid,
                "employee_name": r['employee_name'],
                "routes": [],
                "total_tonnage": 0.0
            }
        groups[eid]['routes'].append(r)
        groups[eid]['total_tonnage'] += r['tonnage']
        
    # Sort logical groups:
    # Split into Active (Open) vs Finished
    for group in groups.values():
         all_r = group['routes']
         
         # Active: No end_time
         active = [x for x in all_r if not x['end_time']]
         active.sort(key=lambda x: x['start_time']) # Earliest start first
         
         # Finished: Has end_time
         finished = [x for x in all_r if x['end_time']]
         finished.sort(key=lambda x: x['end_time'], reverse=True) # Latest finish first
         
         group['routes_active'] = active
         group['routes_finished'] = finished
         
    # 2. Groups display order: Active/Open first, then by Name
    grouped_routes = sorted(groups.values(), key=lambda x: (0 if x['routes_active'] else 1, x['employee_name']))

    # Determine Active Clients (In Route)
    active_client_ids = set()
    for r in routes_view:
        if not r['end_time']: # Active/Open route
            active_client_ids.add(r['client_id'])

    # Delivery list (same selected date)
    delivery_rows = session.exec(
        select(models.Route)
        .where(models.Route.date == date)
        .where(models.Route.type == "delivery")
        .order_by(models.Route.delivery_route_code, models.Route.created_at)
    ).all()
    delivery_sync_token = _build_delivery_sync_token(delivery_rows, date, shift)

    delivery_by_employee = {}
    delivery_summary = {
        "total_stops": len(delivery_rows),
        "total_weight": 0.0,
        "total_value": 0.0,
        "pending": 0,
        "started": 0,
        "returned": 0,
        "canceled": 0,
        "delivered": 0,
        "returned_weight": 0.0,
        "returned_value": 0.0,
    }

    for route in delivery_rows:
        emp = emp_map_id.get(route.employee_id)
        driver_name = emp.name if emp else "Motorista nÃƒÆ’Ã‚Â£o cadastrado"
        key = route.employee_id or 0
        if key not in delivery_by_employee:
            delivery_by_employee[key] = {
                "employee_id": route.employee_id,
                "driver_name": driver_name,
                "vehicle_plate": route.delivery_vehicle_plate or "-",
                "rows": [],
                "total_weight": 0.0,
                "total_value": 0.0,
                "pending": 0,
                "started": 0,
                "delivered": 0,
                "returned": 0,
                "opened_routines": 0,
                "completed_routines": 0,
                "returned_weight": 0.0,
                "returned_value": 0.0,
                "return_percentage": 0.0,
                "returned_weight_percentage": 0.0,
                "returned_value_percentage": 0.0,
                "has_plate_conflict": False,
                "helper_ids": [],
                "helper_names": [],
            }
        else:
            current_plate = _norm_plate(delivery_by_employee[key]["vehicle_plate"])
            route_plate = _norm_plate(route.delivery_vehicle_plate)
            if current_plate and route_plate and current_plate != route_plate:
                delivery_by_employee[key]["has_plate_conflict"] = True

        helper_ids: List[int] = []
        helper_names: List[str] = []
        try:
            parsed_helpers = json.loads(route.delivery_helpers_json) if route.delivery_helpers_json else []
            if isinstance(parsed_helpers, list):
                for helper in parsed_helpers:
                    helper_id: Optional[int] = None
                    if isinstance(helper, int):
                        helper_id = helper
                    elif isinstance(helper, str) and helper.strip().isdigit():
                        helper_id = int(helper.strip())
                    if helper_id is None or helper_id == route.employee_id:
                        continue
                    helper_ids.append(helper_id)
                    helper_emp = emp_map_id.get(helper_id)
                    if helper_emp:
                        helper_names.append(helper_emp.name)
        except Exception:
            pass

        known_helper_ids = set(delivery_by_employee[key]["helper_ids"])
        for helper_id in helper_ids:
            if helper_id not in known_helper_ids:
                known_helper_ids.add(helper_id)
                delivery_by_employee[key]["helper_ids"].append(helper_id)

        known_helper_names = {name.lower() for name in delivery_by_employee[key]["helper_names"]}
        for helper_name in helper_names:
            helper_key = helper_name.lower()
            if helper_key not in known_helper_names:
                known_helper_names.add(helper_key)
                delivery_by_employee[key]["helper_names"].append(helper_name)

        status_raw = (route.delivery_status or "pendente").lower()
        status_map = {
            "pendente": "Pendente",
            "reaberta": "Reaberta",
            "iniciada": "Iniciada",
            "cancelada": "Cancelada",
            "devolucao": "DevoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o",
            "entregue": "Entregue",
        }

        history = []
        try:
            history = json.loads(route.delivery_time_log) if route.delivery_time_log else []
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

        started_times = [h.get("time") for h in history if h.get("event") == "iniciar" and h.get("time")]
        finished_times = [h.get("time") for h in history if h.get("event") == "finalizar" and h.get("time")]
        returned_times = [h.get("time") for h in history if h.get("event") == "devolucao" and h.get("time")]
        reopened_times = [h.get("time") for h in history if h.get("event") == "reabrir" and h.get("time")]

        delivery_by_employee[key]["rows"].append({
            "id": route.id,
            "route_code": route.delivery_route_code or "-",
            "order_number": route.delivery_order_number or "-",
            "client_name": cli_display_map.get(route.client_id, cli_map.get(route.client_id, "Cliente nÃƒÆ’Ã‚Â£o cadastrado")),
            "client_secondary": cli_secondary_map.get(route.client_id),
            "client_code": route.delivery_client_code or "-",
            "address": route.delivery_address or "-",
            "bairro": route.delivery_neighborhood or "-",
            "city": route.delivery_city or "-",
            "state": route.delivery_state or "-",
            "cep": route.delivery_cep or "-",
            "weight": route.tonnage or 0.0,
            "value": route.valor_financeiro or 0.0,
            "status_raw": status_raw,
            "status_label": status_map.get(status_raw, status_raw.title()),
            "return_category": route.delivery_return_category or "",
            "return_reason": route.delivery_return_reason or "",
            "planning_date": route.date,
            "started_at": route.delivery_started_at or route.start_time or "",
            "finished_at": route.delivery_finished_at or (route.end_time or ""),
            "canceled_at": route.delivery_canceled_at or "",
            "returned_at": route.delivery_returned_at or "",
            "last_started_at": started_times[-1] if started_times else "",
            "last_finished_at": finished_times[-1] if finished_times else "",
            "last_returned_at": returned_times[-1] if returned_times else "",
            "last_reopened_at": reopened_times[-1] if reopened_times else "",
            "reopen_count": route.delivery_reopen_count or 0,
            "is_partial_return": bool(route.devolucao_volume or route.valor_devolucao),
            "return_weight": route.devolucao_volume if route.devolucao_volume is not None else (route.tonnage or 0.0),
            "return_value": route.valor_devolucao if route.valor_devolucao is not None else (route.valor_financeiro or 0.0),
            "can_start": True,
            "maps_url": _maps_link(
                route.delivery_address,
                route.delivery_neighborhood,
                route.delivery_city,
                route.delivery_state,
                route.delivery_cep,
            ),
            "helper_ids": helper_ids,
            "helper_names": helper_names,
        })

        delivery_by_employee[key]["total_weight"] += route.tonnage or 0.0
        delivery_by_employee[key]["total_value"] += route.valor_financeiro or 0.0
        delivery_summary["total_weight"] += route.tonnage or 0.0
        delivery_summary["total_value"] += route.valor_financeiro or 0.0
        if status_raw == "iniciada":
            delivery_by_employee[key]["started"] += 1
            delivery_summary["started"] += 1
        elif status_raw == "reaberta":
            delivery_by_employee[key]["pending"] += 1
            delivery_summary["pending"] += 1
        elif status_raw == "devolucao":
            returned_weight = route.devolucao_volume if route.devolucao_volume is not None else (route.tonnage or 0.0)
            returned_value = route.valor_devolucao if route.valor_devolucao is not None else (route.valor_financeiro or 0.0)
            delivery_by_employee[key]["returned"] += 1
            delivery_by_employee[key]["returned_weight"] += returned_weight
            delivery_by_employee[key]["returned_value"] += returned_value
            delivery_summary["returned"] += 1
            delivery_summary["returned_weight"] += returned_weight
            delivery_summary["returned_value"] += returned_value
        elif status_raw == "cancelada":
            delivery_summary["canceled"] += 1
        elif status_raw == "entregue":
            delivery_by_employee[key]["delivered"] += 1
            delivery_summary["delivered"] += 1
        else:
            delivery_by_employee[key]["pending"] += 1
            delivery_summary["pending"] += 1

    delivery_groups = sorted(delivery_by_employee.values(), key=lambda x: x["driver_name"])
    for group in delivery_groups:
        stops = len(group["rows"])
        group["opened_routines"] = group["started"] + group["delivered"] + group["returned"]
        group["completed_routines"] = group["delivered"] + group["returned"]
        group["return_percentage"] = round((group["returned"] / stops) * 100.0, 2) if stops else 0.0
        group["returned_weight_percentage"] = round(
            (group["returned_weight"] / group["total_weight"]) * 100.0, 2
        ) if group["total_weight"] else 0.0
        group["returned_value_percentage"] = round(
            (group["returned_value"] / group["total_value"]) * 100.0, 2
        ) if group["total_value"] else 0.0

        has_open_started = any(r.get("status_raw") == "iniciada" for r in group["rows"])
        if has_open_started:
            for r in group["rows"]:
                # Apenas a rotina jÃƒÆ’Ã‚Â¡ iniciada pode continuar ativa; as demais ficam bloqueadas para "Iniciar".
                r["can_start"] = r.get("status_raw") == "iniciada"
        else:
            for r in group["rows"]:
                r["can_start"] = r.get("status_raw") in ("pendente", "reaberta")

        # Auto-organizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o:
        # 1) Pendentes
        # 2) Iniciadas
        # 3) ConcluÃƒÆ’Ã‚Â­das (entregue/devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o)
        # Em cada grupo, ordena por horÃƒÆ’Ã‚Â¡rio crescente para refletir a rotina ao longo do dia.
        def _time_to_minutes(t: str) -> int:
            try:
                hh, mm = (t or "").split(":")
                return int(hh) * 60 + int(mm)
            except Exception:
                return 10**9

        def _row_sort_key(row: dict):
            status = row.get("status_raw")
            if status == "pendente":
                return (0, _time_to_minutes(row.get("started_at") or ""), row.get("id", 0))
            if status == "reaberta":
                return (0, _time_to_minutes(row.get("last_started_at") or ""), row.get("id", 0))
            if status == "iniciada":
                return (1, _time_to_minutes(row.get("started_at") or ""), row.get("id", 0))
            # concluÃƒÆ’Ã‚Â­das: entregue/devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
            finished_time = row.get("finished_at") or row.get("returned_at") or row.get("canceled_at") or ""
            return (2, _time_to_minutes(finished_time), row.get("id", 0))

        group["rows"] = sorted(group["rows"], key=_row_sort_key)

    total_stops = delivery_summary["total_stops"] or 0
    delivery_summary["return_percentage"] = round((delivery_summary["returned"] / total_stops) * 100.0, 2) if total_stops else 0.0
    delivery_summary["opened_routines"] = (
        delivery_summary["started"] + delivery_summary["delivered"] + delivery_summary["returned"]
    )
    delivery_summary["completed_routines"] = (
        delivery_summary["delivered"] + delivery_summary["returned"]
    )
    delivery_summary["returned_weight_percentage"] = round(
        (delivery_summary["returned_weight"] / delivery_summary["total_weight"]) * 100.0, 2
    ) if delivery_summary["total_weight"] else 0.0
    delivery_summary["returned_value_percentage"] = round(
        (delivery_summary["returned_value"] / delivery_summary["total_value"]) * 100.0, 2
    ) if delivery_summary["total_value"] else 0.0

    delivery_feedback = request.query_params.get("delivery_feedback")
    delivery_feedback_level = request.query_params.get("delivery_feedback_level", "info")
    delivery_employees = sorted(
        session.exec(select(models.Employee).where(models.Employee.status != "fired")).all(),
        key=lambda x: x.name
    )
    delivery_vehicles = sorted(
        session.exec(select(models.Vehicle).where(models.Vehicle.is_active == True)).all(),
        key=lambda x: x.placa
    )

    return templates.TemplateResponse("routes.html", {
        "request": request, 
        "user": user,
        "employees": eligible_employees, 
        "clients": clients,
        "active_client_ids": list(active_client_ids),
        "routes": routes_view, # Keep flat list for "Total" count
        "grouped_routes": grouped_routes, # New grouped structure
        "selected_date": date,
        "selected_shift": shift,
        "selected_date_fmt": selected_date_obj.strftime("%d/%m/%Y"),
        "suggested_input_date": suggested_input_date,
        "delivery_groups": delivery_groups,
        "delivery_summary": delivery_summary,
        "delivery_sync_token": delivery_sync_token,
        "delivery_feedback": delivery_feedback,
        "delivery_feedback_level": delivery_feedback_level,
        "delivery_import": None,
        "delivery_return_reasons": DELIVERY_RETURN_REASONS,
        "delivery_employees": delivery_employees,
        "delivery_vehicles": delivery_vehicles,
    })
@app.post("/separacao/add", response_class=RedirectResponse)
async def add_separacao(
    request: Request,
    date: str = Form(...),
    shift: str = Form(...),
    employee_id: int = Form(...),
    allocations: str = Form(None), # JSON string: [{"client_id": 1, "tonnage": 100}, ...]
    client_ids: str = Form(None), # Legacy fallback
    client_id: int = Form(None), # Legacy fallback
    start_time: str = Form(...),
    end_time: str = Form(None),
    tonnage: float = Form(0.0), # Legacy fallback
    session: Session = Depends(get_session)
):
    require_login(request)
    import json
    
    # 1. Parse Allocations
    items = []
    
    if allocations:
        try:
            items = json.loads(allocations)
        except Exception as e:
            print(f"Error parsing allocations: {e}")
            items = []
            
    # Fallback: Legacy Client IDs (List)
    elif client_ids:
        try:
            c_ids = json.loads(client_ids)
            # Legacy assumption: 1st client gets tonnage, others get 0
            for idx, cid in enumerate(c_ids):
                items.append({
                    "client_id": cid,
                    "tonnage": tonnage if idx == 0 else 0.0
                })
        except:
            pass

    # Fallback: Single Client
    elif client_id:
        items.append({
            "client_id": client_id,
            "tonnage": tonnage
        })

    if not items:
        # Error? Just redirect back
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}", status_code=status.HTTP_303_SEE_OTHER)

    # 2. Create Routes
    for item in items:
        cid = int(item.get('client_id'))
        weight = float(item.get('tonnage') or 0.0)
        
        route = models.Route(
            date=date,
            shift=shift,
            employee_id=employee_id,
            client_id=cid,
            start_time=start_time,
            end_time=end_time if end_time else None,
            tonnage=weight,
            type="separation"
        )
        session.add(route)
    
    session.commit()
    
    return RedirectResponse(url=f"/separacao?date={date}&shift={shift}", status_code=status.HTTP_303_SEE_OTHER)
@app.post("/separacao/delete/{route_id}", response_class=RedirectResponse)
async def delete_separacao(
    request: Request,
    route_id: int,
    session: Session = Depends(get_session)
):
    user = require_login(request)
    route = session.get(models.Route, route_id)
    if route:
        # PERMISSION CHECK: Mobile users can only delete THEIR OWN routes
        # PERMISSION CHECK: Disabled to allow Managers/Leads (logged as employees) to delete ANY route
        # if isinstance(user, dict) and user.get("type") == "employee":
        #      if route.employee_id != user.get("id"):
        #           return RedirectResponse(url=f"/separacao?date={route.date}&shift={route.shift}", status_code=status.HTTP_303_SEE_OTHER)
        
        date = route.date
        shift = route.shift
        session.delete(route)
        session.commit()
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/separacao", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/separacao/import-entregas", response_class=HTMLResponse)
async def import_entregas_separacao(
    request: Request,
    date: str = Form(...),
    shift: str = Form("ManhÃƒÆ’Ã‚Â£"),
    input_date: Optional[str] = Form(None),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    require_login(request)

    import_result = {
        "ok": False,
        "message": "",
        "created": 0,
        "issues": [],
        "warnings": [],
    }

    logger.info(f"ÃƒÂ°Ã…Â¸Ã…Â¡Ã…Â¡ Iniciando importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de entregas: {file.filename} para data {date}, turno {shift}")

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        import_result["message"] = "Arquivo invÃƒÆ’Ã‚Â¡lido. Use .xls, .xlsx ou .csv."
        logger.warning(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Arquivo invÃƒÆ’Ã‚Â¡lido: {file.filename}")
        response = await separacao_page(request=request, date=date, shift=shift, session=session)
        response.context["delivery_import"] = import_result
        return response

    try:
        import pandas as pd
        content = await file.read()
        logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Å¾ Arquivo lido: {len(content)} bytes")
        
        df = _load_clients_dataframe(content, file.filename)
        logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã…Â  DataFrame carregado: {len(df)} linhas, {len(df.columns)} colunas")
        logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹ Colunas encontradas: {list(df.columns)}")
        
        col_map = _delivery_col_map(list(df.columns))
        logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬â€Ã‚ÂºÃƒÂ¯Ã‚Â¸Ã‚Â Mapeamento de colunas: {col_map}")

        required = ["driver", "plate", "client_name", "client_code", "address", "peso_pedido", "route_code"]
        missing_required = [field for field in required if not col_map.get(field)]
        if missing_required:
            import_result["message"] = "Planilha sem colunas obrigatÃƒÆ’Ã‚Â³rias para entregas."
            import_result["issues"].append({
                "row": "-",
                "reason": f"Colunas ausentes: {', '.join(missing_required)}. Colunas encontradas: {', '.join(df.columns)}",
            })
            logger.error(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Colunas ausentes: {missing_required}")
            response = await separacao_page(request=request, date=date, shift=shift, session=session)
            response.context["delivery_import"] = import_result
            return response

        employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
        clients = session.exec(select(models.Client)).all()
        vehicles = session.exec(select(models.Vehicle).where(models.Vehicle.is_active == True)).all()
        vehicle_by_plate = {_norm_plate(v.placa): v for v in vehicles}

        # Log dos motoristas cadastrados para debug
        motoristas_cadastrados = [
            f"{emp.name} (cargo: {emp.role or 'N/A'})"
            for emp in employees
            if "motorista" in (emp.role or "").lower()
        ]
        logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ËœÃ‚Â¥ Total de funcionÃƒÆ’Ã‚Â¡rios ativos: {len(employees)}")
        logger.info(f"ÃƒÂ°Ã…Â¸Ã…Â¡Ã¢â‚¬â€ Motoristas cadastrados ({len(motoristas_cadastrados)}): {motoristas_cadastrados}")

        parsed_rows = []
        route_totals = {}

        for idx, row in df.iterrows():
            row_num = idx + 2
            route_code = _as_str(row.get(col_map["route_code"]))
            driver_name_raw = _as_str(row.get(col_map["driver"]))
            plate_raw = _as_str(row.get(col_map["plate"]))
            client_name_raw = _as_str(row.get(col_map["client_name"]))
            client_code_raw = _as_str(row.get(col_map["client_code"]))
            peso_pedido = _as_float(row.get(col_map["peso_pedido"]))
            peso_total = _as_float(row.get(col_map["peso_total"])) if col_map.get("peso_total") else 0.0
            valor = _as_float(row.get(col_map["valor"])) if col_map.get("valor") else 0.0
            pedido_num = _as_str(row.get(col_map["order_number"])) if col_map.get("order_number") else None
            pedido_data = _as_str(row.get(col_map["order_date"])) if col_map.get("order_date") else None
            address = _as_str(row.get(col_map["address"]))
            bairro = _as_str(row.get(col_map["bairro"])) if col_map.get("bairro") else None
            city = _as_str(row.get(col_map["city"])) if col_map.get("city") else None
            state = _as_str(row.get(col_map["state"])) if col_map.get("state") else None
            cep = _as_str(row.get(col_map["cep"])) if col_map.get("cep") else None
            tipo = _as_str(row.get(col_map["tipo"])) if col_map.get("tipo") else "Entrega"

            if not driver_name_raw or not client_name_raw:
                import_result["issues"].append({
                    "row": row_num,
                    "reason": "Linha sem motorista ou cliente.",
                })
                continue

            emp = _find_employee_by_driver_name(driver_name_raw, employees)
            if not emp:
                # Buscar motoristas disponÃƒÆ’Ã‚Â­veis para sugerir
                motoristas_cadastrados = [e.name for e in employees if "motorista" in (e.role or "").lower()][:5]
                sugestao = f" Motoristas cadastrados: {', '.join(motoristas_cadastrados)}" if motoristas_cadastrados else ""
                import_result["issues"].append({
                    "row": row_num,
                    "reason": f"Motorista nÃƒÆ’Ã‚Â£o encontrado: '{driver_name_raw}'.{sugestao}",
                })
                logger.warning(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Motorista nÃƒÆ’Ã‚Â£o encontrado na linha {row_num}: '{driver_name_raw}'")
                continue

            vehicle = vehicle_by_plate.get(_norm_plate(plate_raw))
            if not vehicle:
                import_result["issues"].append({
                    "row": row_num,
                    "reason": f"CaminhÃƒÆ’Ã‚Â£o/placa nÃƒÆ’Ã‚Â£o cadastrado: {plate_raw or '-'}",
                })
                continue

            client = _find_client(client_code_raw, client_name_raw, clients)

            if not client:
                import_result["issues"].append({
                    "row": row_num,
                    "reason": f"Cliente nÃƒÆ’Ã‚Â£o cadastrado: {client_name_raw} (cÃƒÆ’Ã‚Â³digo {client_code_raw or '-'})",
                })
                continue

            parsed_rows.append({
                "employee_id": emp.id,
                "client_id": client.id,
                "route_code": route_code or "-",
                "plate": plate_raw or "",
                "client_code": client_code_raw or "",
                "order_number": pedido_num or "",
                "order_date": pedido_data or input_date,
                "address": address or "",
                "bairro": bairro or "",
                "city": city or "",
                "state": state or "",
                "cep": cep or "",
                "peso_pedido": peso_pedido,
                "peso_total": peso_total,
                "valor": valor,
                "tipo": tipo or "Entrega",
            })

            route_key = route_code or f"row_{row_num}"
            if route_key not in route_totals:
                route_totals[route_key] = {"sum_pedidos": 0.0, "peso_total": 0.0}
            route_totals[route_key]["sum_pedidos"] += peso_pedido
            route_totals[route_key]["peso_total"] = max(route_totals[route_key]["peso_total"], peso_total)

        for route_code, payload in route_totals.items():
            sum_pedidos = payload["sum_pedidos"]
            peso_total = payload["peso_total"]
            if peso_total > 0 and abs(sum_pedidos - peso_total) > 1.0:
                import_result["warnings"].append({
                    "route": route_code,
                    "reason": f"Soma PESO PEDIDO ({sum_pedidos:.2f}) difere de PESO TOTAL ({peso_total:.2f}).",
                })

        if not parsed_rows:
            import_result["message"] = "Nenhuma entrega vÃƒÆ’Ã‚Â¡lida encontrada. Corrija os cadastros pendentes e tente novamente."
            response = await separacao_page(request=request, date=date, shift=shift, session=session)
            response.context["delivery_import"] = import_result
            return response

        imported_route_codes = list({row["route_code"] for row in parsed_rows if row["route_code"] and row["route_code"] != "-"})
        if imported_route_codes:
            existing = session.exec(
                select(models.Route)
                .where(models.Route.date == date)
                .where(models.Route.type == "delivery")
                .where(models.Route.delivery_route_code.in_(imported_route_codes))
            ).all()
            for old_row in existing:
                session.delete(old_row)
            session.flush()

        for row in parsed_rows:
            route = models.Route(
                date=date,
                shift=shift,
                employee_id=row["employee_id"],
                client_id=row["client_id"],
                start_time="00:00",
                end_time=None,
                tonnage=row["peso_pedido"],
                type="delivery",
                status="pending",
                valor_financeiro=row["valor"],
                delivery_status="pendente",
                delivery_route_code=row["route_code"],
                delivery_order_number=row["order_number"],
                delivery_client_code=row["client_code"],
                delivery_vehicle_plate=row["plate"],
                delivery_cep=row["cep"],
                delivery_address=row["address"],
                delivery_neighborhood=row["bairro"],
                delivery_city=row["city"],
                delivery_state=row["state"],
                delivery_type=row["tipo"],
                delivery_total_weight=row["peso_total"],
                delivery_order_date=row["order_date"],
                delivery_source_file=file.filename,
            )
            session.add(route)

        session.commit()
        import_result["ok"] = True
        import_result["created"] = len(parsed_rows)
        logger.info(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ ImportaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o concluÃƒÆ’Ã‚Â­da: {len(parsed_rows)} entregas criadas")
        
        if import_result["issues"]:
            import_result["message"] = (
                f"ImportaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o parcial concluÃƒÆ’Ã‚Â­da. {len(parsed_rows)} entregas criadas para {date}. "
                f"{len(import_result['issues'])} linha(s) pendente(s) de cadastro."
            )
        else:
            import_result["message"] = f"ImportaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o concluÃƒÆ’Ã‚Â­da com sucesso. {len(parsed_rows)} entregas criadas para {date}."
    except Exception as exc:
        import_result["message"] = f"Erro ao importar planilha: {str(exc)}"
        logger.exception(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Falha na importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de entregas: {exc}")
        import_result["issues"].append({
            "row": "-",
            "reason": f"Erro tÃƒÆ’Ã‚Â©cnico: {str(exc)}"
        })

    response = await separacao_page(request=request, date=date, shift=shift, session=session)
    response.context["delivery_import"] = import_result
    return response


@app.get("/separacao/import-entregas", response_class=RedirectResponse)
async def import_entregas_separacao_get():
    return RedirectResponse(url="/separacao", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/api/separacao/delivery/sync-token", response_class=JSONResponse)
async def separacao_delivery_sync_token(
    request: Request,
    date: Optional[str] = None,
    shift: str = "ManhÃƒÆ’Ã‚Â£",
    session: Session = Depends(get_session),
):
    require_login(request)
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    rows = session.exec(
        select(models.Route)
        .where(models.Route.date == date)
        .where(models.Route.shift == shift)
        .where(models.Route.type == "delivery")
    ).all()

    token = _build_delivery_sync_token(rows, date, shift)
    return JSONResponse({"success": True, "token": token})


@app.post("/separacao/delivery/status", response_class=RedirectResponse)
async def update_delivery_status(
    request: Request,
    route_id: int = Form(...),
    action: str = Form(...),
    date: str = Form(...),
    shift: str = Form("ManhÃƒÆ’Ã‚Â£"),
    return_category: Optional[str] = Form(None),
    return_reason: Optional[str] = Form(None),
    return_is_partial: Optional[str] = Form(None),
    return_partial_weight: Optional[float] = Form(None),
    return_partial_value: Optional[float] = Form(None),
    session: Session = Depends(get_session),
):
    require_login(request)
    route = session.get(models.Route, route_id)
    if not route or route.type != "delivery":
        return RedirectResponse(
            url=f"/separacao?date={date}&shift={shift}&delivery_feedback=Entrega%20nÃƒÆ’Ã‚Â£o%20encontrada&delivery_feedback_level=error",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    now = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M")
    action_norm = (action or "").strip().lower()
    feedback = "Status atualizado."

    if action_norm == "iniciar":
        if (route.delivery_status or "").lower() in ("entregue", "devolucao"):
            feedback_encoded = urlencode({
                "delivery_feedback": "Rotina jÃƒÆ’Ã‚Â¡ concluÃƒÆ’Ã‚Â­da. Use 'Reabrir' para iniciar novamente sem perder histÃƒÆ’Ã‚Â³rico.",
                "delivery_feedback_level": "error",
            })
            return RedirectResponse(
                url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        already_started = session.exec(
            select(models.Route)
            .where(models.Route.type == "delivery")
            .where(models.Route.date == route.date)
            .where(models.Route.employee_id == route.employee_id)
            .where(models.Route.delivery_status == "iniciada")
            .where(models.Route.id != route.id)
        ).first()
        if already_started:
            feedback_encoded = urlencode({
                "delivery_feedback": "Motorista jÃƒÆ’Ã‚Â¡ possui uma rotina iniciada. Finalize antes de iniciar outra.",
                "delivery_feedback_level": "error",
            })
            return RedirectResponse(
                url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        route.delivery_status = "iniciada"
        if not route.start_time or route.start_time == "00:00":
            route.start_time = now
        if not route.delivery_started_at:
            route.delivery_started_at = now
        _append_delivery_event(route, "iniciar", now)
        feedback = "Entrega iniciada."
    elif action_norm == "cancelar":
        feedback_encoded = urlencode({
            "delivery_feedback": "A aÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de cancelamento foi desativada.",
            "delivery_feedback_level": "error",
        })
        return RedirectResponse(
            url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    elif action_norm == "devolucao":
        if (route.delivery_status or "").lower() != "iniciada":
            feedback_encoded = urlencode({
                "delivery_feedback": "Para registrar devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o, inicie a entrega primeiro.",
                "delivery_feedback_level": "error",
            })
            return RedirectResponse(
                url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        if not return_category or not return_reason:
            feedback_encoded = urlencode({
                "delivery_feedback": "Para devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o, informe categoria e motivo.",
                "delivery_feedback_level": "error",
            })
            return RedirectResponse(
                url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        is_partial = str(return_is_partial or "").lower() in ("1", "true", "on", "yes")
        partial_weight = float(return_partial_weight or 0.0)
        partial_value = float(return_partial_value or 0.0)
        if is_partial:
            if partial_weight <= 0 and partial_value <= 0:
                feedback_encoded = urlencode({
                    "delivery_feedback": "Para devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o parcial, informe peso e/ou valor devolvido.",
                    "delivery_feedback_level": "error",
                })
                return RedirectResponse(
                    url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            total_weight = float(route.tonnage or 0.0)
            total_value = float(route.valor_financeiro or 0.0)
            if total_weight > 0 and partial_weight > total_weight:
                partial_weight = total_weight
            if total_value > 0 and partial_value > total_value:
                partial_value = total_value
            route.devolucao_volume = partial_weight if partial_weight > 0 else 0.0
            route.valor_devolucao = partial_value if partial_value > 0 else 0.0
        else:
            # DevoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o total: usa o valor/peso integral para anÃƒÆ’Ã‚Â¡lises
            route.devolucao_volume = route.tonnage or 0.0
            route.valor_devolucao = route.valor_financeiro or 0.0
        route.delivery_status = "devolucao"
        route.status = "completed"
        route.end_time = now
        if not route.delivery_returned_at:
            route.delivery_returned_at = now
        if not route.delivery_finished_at:
            route.delivery_finished_at = now
        route.delivery_return_category = return_category
        route.delivery_return_reason = return_reason
        note = f"{return_category}: {return_reason}"
        if is_partial:
            note += f" | parcial | peso={route.devolucao_volume:.2f} | valor={route.valor_devolucao:.2f}"
        _append_delivery_event(route, "devolucao", now, note=note)
        feedback = "Entrega marcada como devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o."
    elif action_norm in ["entregue", "finalizar"]:
        route.delivery_status = "entregue"
        route.status = "completed"
        route.end_time = now
        if not route.delivery_finished_at:
            route.delivery_finished_at = now
        route.delivery_return_category = None
        route.delivery_return_reason = None
        _append_delivery_event(route, "finalizar", now)
        feedback = "Entrega finalizada."

    session.add(route)
    session.commit()

    feedback_encoded = urlencode({"delivery_feedback": feedback, "delivery_feedback_level": "success"})
    return RedirectResponse(
        url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/separacao/delivery/planning-date", response_class=RedirectResponse)
async def update_delivery_planning_date(
    request: Request,
    route_id: int = Form(...),
    planning_date: str = Form(...),
    date: str = Form(...),
    shift: str = Form("ManhÃƒÆ’Ã‚Â£"),
    session: Session = Depends(get_session),
):
    require_login(request)
    route = session.get(models.Route, route_id)
    if not route or route.type != "delivery":
        feedback_encoded = urlencode({
            "delivery_feedback": "Entrega nÃƒÆ’Ã‚Â£o encontrada.",
            "delivery_feedback_level": "error",
        })
        return RedirectResponse(
            url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        datetime.strptime(planning_date, "%Y-%m-%d")
    except Exception:
        feedback_encoded = urlencode({
            "delivery_feedback": "Data de planejamento invÃƒÆ’Ã‚Â¡lida.",
            "delivery_feedback_level": "error",
        })
        return RedirectResponse(
            url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    route.date = planning_date
    session.add(route)
    session.commit()

    feedback_encoded = urlencode({
        "delivery_feedback": f"Data da entrega atualizada para {planning_date}.",
        "delivery_feedback_level": "success",
    })
    return RedirectResponse(
        url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/separacao/delivery/planning-date/bulk", response_class=RedirectResponse)
async def update_delivery_planning_date_bulk(
    request: Request,
    current_date: str = Form(...),
    planning_date: str = Form(...),
    shift: str = Form("ManhÃƒÆ’Ã‚Â£"),
    session: Session = Depends(get_session),
):
    require_login(request)
    try:
        datetime.strptime(planning_date, "%Y-%m-%d")
    except Exception:
        feedback_encoded = urlencode({
            "delivery_feedback": "Data geral invÃƒÆ’Ã‚Â¡lida.",
            "delivery_feedback_level": "error",
        })
        return RedirectResponse(
            url=f"/separacao?date={current_date}&shift={shift}&{feedback_encoded}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    rows = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == current_date)
    ).all()

    for row in rows:
        row.date = planning_date
        session.add(row)
    session.commit()

    feedback_encoded = urlencode({
        "delivery_feedback": f"Data geral atualizada para {planning_date} em {len(rows)} entrega(s).",
        "delivery_feedback_level": "success",
    })
    return RedirectResponse(
        url=f"/separacao?date={planning_date}&shift={shift}&{feedback_encoded}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/separacao/delivery/reassign", response_class=RedirectResponse)
async def reassign_delivery_stop(
    request: Request,
    route_id: int = Form(...),
    new_employee_id: int = Form(...),
    new_vehicle_plate: str = Form(...),
    date: str = Form(...),
    shift: str = Form("ManhÃƒÆ’Ã‚Â£"),
    session: Session = Depends(get_session),
):
    require_login(request)
    route = session.get(models.Route, route_id)
    if not route or route.type != "delivery":
        feedback_encoded = urlencode({
            "delivery_feedback": "Entrega nÃƒÆ’Ã‚Â£o encontrada para reatribuiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o.",
            "delivery_feedback_level": "error",
        })
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

    err = _validate_delivery_assignment(
        session=session,
        date=route.date,
        employee_id=new_employee_id,
        vehicle_plate=new_vehicle_plate,
        exclude_route_id=route.id,
        ignore_employee_id=route.employee_id,
    )
    if err:
        feedback_encoded = urlencode({"delivery_feedback": err, "delivery_feedback_level": "error"})
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

    route.employee_id = new_employee_id
    route.delivery_vehicle_plate = new_vehicle_plate
    session.add(route)
    session.commit()

    feedback_encoded = urlencode({"delivery_feedback": "Cliente movido para outra entrega.", "delivery_feedback_level": "success"})
    return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)


@app.post("/separacao/delivery/reassign-group", response_class=RedirectResponse)
async def reassign_delivery_group(
    request: Request,
    source_employee_id: int = Form(...),
    new_employee_id: int = Form(...),
    new_vehicle_plate: str = Form(...),
    helper_ids: Optional[List[int]] = Form(None),
    date: str = Form(...),
    shift: str = Form("ManhÃƒÆ’Ã‚Â£"),
    session: Session = Depends(get_session),
):
    require_login(request)
    
    # Buscar nomes para logs mais legÃƒÆ’Ã‚Â­veis
    source_emp = session.get(models.Employee, source_employee_id)
    new_emp = session.get(models.Employee, new_employee_id)
    source_name = source_emp.name if source_emp else f"ID={source_employee_id}"
    new_name = new_emp.name if new_emp else f"ID={new_employee_id}"

    normalized_helper_ids: List[int] = []
    seen_helpers = set()
    for helper_id in (helper_ids or []):
        if helper_id == new_employee_id:
            continue
        if helper_id in seen_helpers:
            continue
        seen_helpers.add(helper_id)
        normalized_helper_ids.append(helper_id)
    helpers_json = json.dumps(normalized_helper_ids) if normalized_helper_ids else None
    
    logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ¢â‚¬Å¾ Tentativa de troca de motorista: {source_name} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {new_name}, CaminhÃƒÆ’Ã‚Â£o: {new_vehicle_plate}, Data: {date}")
    
    rows = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == date)
        .where(models.Route.employee_id == source_employee_id)
    ).all()
    if not rows:
        logger.warning(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Nenhuma entrega encontrada para {source_name} na data {date}")
        feedback_encoded = urlencode({"delivery_feedback": "Nenhuma entrega encontrada para o motorista.", "delivery_feedback_level": "error"})
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

    logger.info(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â¦ Encontradas {len(rows)} entregas para transferir")

    err = _validate_delivery_assignment(
        session=session,
        date=date,
        employee_id=new_employee_id,
        vehicle_plate=new_vehicle_plate,
        ignore_employee_id=source_employee_id,
    )
    if err:
        logger.error(f"ÃƒÂ¢Ã‚ÂÃ…â€™ ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o falhou: {err}")
        feedback_encoded = urlencode({"delivery_feedback": err, "delivery_feedback_level": "error"})
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

    for r in rows:
        r.employee_id = new_employee_id
        r.delivery_vehicle_plate = new_vehicle_plate
        r.delivery_helpers_json = helpers_json
        session.add(r)
    session.commit()

    logger.info(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Troca concluÃƒÆ’Ã‚Â­da: {len(rows)} entregas transferidas de {source_name} para {new_name}")
    feedback_encoded = urlencode({"delivery_feedback": f"TransferÃƒÆ’Ã‚Âªncia concluÃƒÆ’Ã‚Â­da em {len(rows)} parada(s).", "delivery_feedback_level": "success"})
    return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)


@app.post("/separacao/delivery/reopen", response_class=RedirectResponse)
async def reopen_delivery_route(
    request: Request,
    route_id: int = Form(...),
    date: str = Form(...),
    shift: str = Form("ManhÃƒÆ’Ã‚Â£"),
    session: Session = Depends(get_session),
):
    require_login(request)
    route = session.get(models.Route, route_id)
    if not route or route.type != "delivery":
        feedback_encoded = urlencode({"delivery_feedback": "Entrega nÃƒÆ’Ã‚Â£o encontrada.", "delivery_feedback_level": "error"})
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

    if (route.delivery_status or "").lower() not in ("entregue", "devolucao"):
        feedback_encoded = urlencode({"delivery_feedback": "Somente rotinas concluÃƒÆ’Ã‚Â­das podem ser reabertas.", "delivery_feedback_level": "error"})
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

    already_started = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == route.date)
        .where(models.Route.employee_id == route.employee_id)
        .where(models.Route.delivery_status == "iniciada")
        .where(models.Route.id != route.id)
    ).first()
    if already_started:
        feedback_encoded = urlencode({
            "delivery_feedback": "Motorista jÃƒÆ’Ã‚Â¡ possui rotina iniciada. Finalize antes de reabrir outra.",
            "delivery_feedback_level": "error",
        })
        return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

    now = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M")
    route.delivery_status = "reaberta"
    route.status = "pending"
    route.end_time = None
    route.delivery_reopen_count = (route.delivery_reopen_count or 0) + 1
    _append_delivery_event(route, "reabrir", now, note=f"Reabertura #{route.delivery_reopen_count}")
    session.add(route)
    session.commit()

    feedback_encoded = urlencode({"delivery_feedback": "Rotina reaberta com sucesso.", "delivery_feedback_level": "success"})
    return RedirectResponse(url=f"/separacao?date={date}&shift={shift}&{feedback_encoded}", status_code=303)

@app.post("/separacao/update", response_class=RedirectResponse)
async def update_separacao(
    request: Request,
    route_id: int = Form(...),
    employee_id: int = Form(None), 
    client_id: int = Form(None),
    start_time: str = Form(None),
    end_time: str = Form(None),
    tonnage: Optional[float] = Form(None),
    session: Session = Depends(get_session)
):
    user = require_login(request)
    route = session.get(models.Route, route_id)
    if route:
        # PERMISSION CHECK
        if isinstance(user, dict) and user.get("type") == "employee":
             # If route is ALREADY completed, prevent edits
             if route.status == "completed" or (route.end_time and route.end_time != ""):
                 return RedirectResponse(url=f"/separacao?date={route.date}&shift={route.shift}", status_code=status.HTTP_303_SEE_OTHER)

        old_status = route.status
        
        if employee_id is not None: route.employee_id = employee_id
        if client_id is not None: route.client_id = client_id
        if start_time is not None: route.start_time = start_time
        if end_time is not None: route.end_time = end_time
        if tonnage is not None: route.tonnage = tonnage
        
        # Check for completion (XP Gain)
        # Assuming pending -> completed when end_time is present
        if end_time and route.start_time and tonnage and tonnage > 0:
             route.status = "completed"
             
             # Determine XP Gain (Only if it wasn't already credited? Simplistic: just add)
             # To be robust we should check if status changed.
             if old_status != "completed":
                 emp = session.get(models.Employee, route.employee_id)
                 if emp:
                     emp.total_xp += tonnage
                     session.add(emp)
        
        session.add(route)
        session.commit()
        return RedirectResponse(url=f"/separacao?date={route.date}&shift={route.shift}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/separacao", status_code=status.HTTP_303_SEE_OTHER)


# --- DevoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes (OcorrÃƒÆ’Ã‚Âªncias de Entrega) ---
from devolucoes_service import (
    parse_excel as devolucoes_parse_excel,
    validate_rows as devolucoes_validate_rows,
    save_batch as devolucoes_save_batch,
    get_cadastro_health as devolucoes_get_cadastro_health,
    persist_import_batch as devolucoes_persist_import_batch,
)
from devolucoes_service import _load_cadastros as devolucoes_load_cadastros
from employees_seller_code import batch_update_from_json, batch_update_from_excel
from pydantic import BaseModel as PydanticBaseModel

class DevolucaoManualPayload(PydanticBaseModel):
    data_romaneio: str
    data_entrega: str
    client_id: int
    vendedor_id: int
    motorista_id: int
    ajudante_id: Optional[int] = None
    valor: float
    motivo_id: int
    observacao: Optional[str] = None
    responsabilidade_id: int

@app.get("/devolucoes", response_class=HTMLResponse)
async def devolucoes_page(
    request: Request,
    session: Session = Depends(get_session),
):
    require_login(request)
    clients = session.exec(select(models.Client).order_by(models.Client.name)).all()
    employees = session.exec(select(models.Employee).where(models.Employee.status != "fired").order_by(models.Employee.name)).all()
    motivos = session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.is_active == True)).all()
    responsabilidades = session.exec(select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.is_active == True)).all()
    devolucoes = session.exec(
        select(models.Devolucao)
        .order_by(models.Devolucao.data_romaneio.desc(), models.Devolucao.created_at.desc())
        .limit(200)
    ).all()
    rows = []
    for dev in devolucoes:
        c = session.get(models.Client, dev.client_id)
        m = session.get(models.Employee, dev.motorista_id)
        rows.append({
            "id": dev.id,
            "data_romaneio": dev.data_romaneio,
            "valor": dev.valor,
            "cluster": dev.cluster,
            "acima_300": dev.acima_300,
            "source": dev.source,
            "client_name": c.name if c else "-",
            "motorista_name": m.name if m else "-",
        })
    return templates.TemplateResponse("devolucoes.html", {
        "request": request,
        "clients": clients,
        "employees": employees,
        "motivos": motivos,
        "responsabilidades": responsabilidades,
        "devolucoes": rows,
        "import_result": getattr(request.state, "devolucoes_import_result", None),
    })


@app.get("/devolucoes/template")
async def devolucoes_template(request: Request):
    """Retorna planilha Excel modelo para importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes."""
    import pandas as pd
    import io
    require_login(request)
    df = pd.DataFrame([
        {
            "DATA ROMANEIO": "02/02/2026",
            "DATA ENTREGA": "02/02/2026",
            "CODIGO": "61/50",
            "NOME DO CLIENTE": "FIMA CENTRAL DE COMPRA",
            "VENDEDOR": "110",
            "MOTORISTA": "GILMAR",
            "VALOR": "702,77",
            "MOTIVO": "CLIENTE DESISTIU DA COMPRA",
            "OBSERVAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O": "",
            "RESPONSABILIDADE": "MERCADO",
        },
        {
            "DATA ROMANEIO": "03/02/2026",
            "DATA ENTREGA": "03/02/2026",
            "CODIGO": "164M0",
            "NOME DO CLIENTE": "WANASINAMON",
            "VENDEDOR": "310",
            "MOTORISTA": "JOSE MARIA CESAR",
            "VALOR": "107,99",
            "MOTIVO": "PEDIDO/PRODUTO ERRADO",
            "OBSERVAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O": "",
            "RESPONSABILIDADE": "COMERCIAL",
        },
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=planilha_devolucoes_modelo.xlsx"},
    )


@app.get("/api/devolucoes/health", response_class=JSONResponse)
async def api_devolucoes_health(
    request: Request,
    session: Session = Depends(get_session),
):
    """DiagnÃƒÂ³stico dos cadastros necessÃƒÂ¡rios para importaÃƒÂ§ÃƒÂ£o de devoluÃƒÂ§ÃƒÂµes."""
    require_login(request)
    try:
        cad = devolucoes_load_cadastros(session)
        diagnostics, global_errors = devolucoes_get_cadastro_health(cad)
        problems = list(global_errors)
        return JSONResponse({
            "ok": len(problems) == 0,
            "diagnostics": diagnostics,
            "problems": problems,
            "global_errors": global_errors,
            "ok_vendedores": diagnostics.get("vendedor_by_code_size", 0) > 0,
            "ok_motivos": diagnostics.get("motivos_total", 0) > 0,
            "ok_responsabilidades": diagnostics.get("responsabilidades_total", 0) > 0,
            "ok_clientes": diagnostics.get("client_by_nb_size", 0) > 0,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/admin/seller-code/batch", response_class=JSONResponse)
async def api_admin_seller_code_batch(
    request: Request,
    file: UploadFile = File(None),
    session: Session = Depends(get_session),
):
    """
    Preenchimento em lote de seller_code.
    A) Envie arquivo Excel/CSV com colunas: registration_id OU name, seller_code.
    B) Ou envie JSON: [{"registration_id":"123","seller_code":"201"}, {"name":"JOSE MARIA","seller_code":"311"}]
    """
    require_admin(request)
    try:
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type and file and file.filename:
            content = await file.read()
            report, err = batch_update_from_excel(session, content, file.filename or "upload.xlsx")
            if err:
                return JSONResponse({"ok": False, "error": err}, status_code=400)
        else:
            body = await request.json()
            items = body if isinstance(body, list) else body.get("items", [])
            if not items:
                return JSONResponse({"ok": False, "error": "Envie JSON com array de {registration_id ou name, seller_code}"}, status_code=400)
            report = batch_update_from_json(session, items)
        session.commit()
        return JSONResponse({
            "ok": True,
            "updated": len(report.updated),
            "ignored": len(report.ignored),
            "not_found": len(report.not_found),
            "duplicates": report.duplicates,
            "report": {
                "updated": report.updated,
                "ignored": report.ignored[:20],
                "not_found": report.not_found[:20],
                "duplicates": report.duplicates,
            },
        })
    except Exception as e:
        logger.exception(f"Erro ao preencher seller_code em lote: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/devolucoes/import", response_class=JSONResponse)
async def api_devolucoes_import(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    require_login(request)
    try:
        return await _run_devolucoes_import(request, file, session)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception(f"Erro import devoluÃ§Ãµes: {e}")
        _dbg_log("devolucoes_import_500", {"error": str(e), "traceback": tb})
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def _run_devolucoes_import(request: Request, file: UploadFile, session: Session):
    MAX_SIZE = 50 * 1024 * 1024  # 50MB
    if not file or not file.filename:
        return JSONResponse({"ok": False, "error": "Nenhum arquivo enviado. Selecione um arquivo Excel (.xlsx, .xls ou .xlsm)."}, status_code=400)
    fn = (file.filename or "").lower()
    if not fn.endswith((".xlsx", ".xls", ".xlsm")):
        return JSONResponse({"ok": False, "error": "Arquivo invÃ¡lido. Use .xlsx, .xls ou .xlsm."}, status_code=400)
    content = await file.read()
    if len(content) > MAX_SIZE:
        return JSONResponse({"ok": False, "error": "Arquivo muito grande (mÃ¡x. 50MB)."}, status_code=400)
    try:
        rows, err = devolucoes_parse_excel(content, file.filename or "upload.xlsx")
    except Exception as ex:
        logger.exception(f"Erro parse Excel: {ex}")
        return JSONResponse({"ok": False, "error": f"Erro ao processar planilha: {ex}"}, status_code=400)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    valid, invalid, _, _, global_errors = devolucoes_validate_rows(rows, session, to_staging_on_invalid=False)
    if global_errors:
        return JSONResponse({
            "ok": False,
            "error": " | ".join(global_errors),
            "global_errors": global_errors,
        }, status_code=400)
    try:
        created_by = None
        if request.session.get("user_id"):
            u = session.get(models.User, request.session["user_id"])
            if u:
                created_by = u.username
        batch_id = devolucoes_persist_import_batch(
            session=session,
            filename=file.filename or "upload.xlsx",
            rows=rows,
            valid_rows=valid,
            invalid_rows=invalid,
            created_by=created_by,
            create_staging=True,
        )
        session.commit()
        return JSONResponse({
            "ok": True,
            "batch_id": batch_id,
            "total": len(rows),
            "valid_count": len(valid),
            "invalid_count": len(invalid),
            "invalid_details": invalid[:50],
            "valid_rows": valid,
            "valid_preview": valid[:10],
        })
    except Exception as e:
        logger.exception(f"Erro ao processar import de devoluÃ§Ãµes: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/devolucoes/import/commit", response_class=JSONResponse)
async def api_devolucoes_import_commit(
    request: Request,
    session: Session = Depends(get_session),
):
    require_login(request)
    try:
        body = await request.json()
        valid_rows = body.get("valid_rows", [])
        batch_id = body.get("batch_id")
        filename = body.get("filename", "import.xlsx")
        if not valid_rows:
            return JSONResponse({"ok": False, "error": "Nenhuma linha vÃƒÆ’Ã‚Â¡lida para gravar."}, status_code=400)
        created_by = None
        if request.session.get("user_id"):
            u = session.get(models.User, request.session["user_id"])
            if u:
                created_by = u.username
        created, skipped = devolucoes_save_batch(
            session,
            valid_rows,
            {"filename": filename, "batch_id": batch_id},
            source="EXCEL",
            created_by=created_by,
        )
        session.commit()
        return JSONResponse({
            "ok": True,
            "batch_id": batch_id,
            "created": created,
            "skipped": len(skipped),
        })
    except Exception as e:
        logger.exception(f"Erro ao commitar importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/devolucoes/import/{batch_id}/errors.xlsx")
async def api_devolucoes_import_errors_xlsx(
    batch_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    require_login(request)
    batch = session.get(models.DevolucaoImportBatch, batch_id)
    if not batch:
        return JSONResponse({"ok": False, "error": "Lote nÃ£o encontrado."}, status_code=404)

    errors = session.exec(
        select(models.DevolucaoImportRowError)
        .where(models.DevolucaoImportRowError.batch_id == batch_id)
        .order_by(models.DevolucaoImportRowError.row_index, models.DevolucaoImportRowError.id)
    ).all()

    try:
        from openpyxl import Workbook
    except Exception:
        return JSONResponse({"ok": False, "error": "openpyxl nÃ£o disponÃ­vel."}, status_code=500)

    wb = Workbook()
    ws = wb.active
    ws.title = "Erros Importacao"
    ws.append(["batch_id", "row_index", "column_name", "value", "reason", "raw_row_json"])
    for err in errors:
        ws.append([
            batch_id,
            err.row_index,
            err.column_name,
            err.value,
            err.reason,
            err.raw_row_json,
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=devolucoes_erros_batch_{batch_id}.xlsx"},
    )


@app.post("/api/devolucoes", response_class=JSONResponse)
async def api_devolucoes_create(
    request: Request,
    payload: DevolucaoManualPayload,
    session: Session = Depends(get_session),
):
    require_login(request)
    from devolucoes_service import (
        compute_dia, compute_semana, compute_acima_300, compute_cluster,
        make_idempotency_hash,
    )
    try:
        uid = request.session.get("user_id")
        created_by = session.get(models.User, uid).username if uid and session.get(models.User, uid) else None
        dt = datetime.strptime(payload.data_romaneio, "%Y-%m-%d")
        dia = compute_dia(dt)
        semana = compute_semana(dt)
        acima_300 = compute_acima_300(payload.valor)
        cluster = compute_cluster(payload.valor)
        h = make_idempotency_hash(
            payload.data_romaneio, payload.client_id, payload.vendedor_id,
            payload.motorista_id, payload.valor, payload.motivo_id,
        )
        dev = models.Devolucao(
            data_romaneio=payload.data_romaneio,
            data_entrega=payload.data_entrega,
            client_id=payload.client_id,
            vendedor_id=payload.vendedor_id,
            motorista_id=payload.motorista_id,
            ajudante_id=payload.ajudante_id,
            valor=payload.valor,
            motivo_id=payload.motivo_id,
            observacao=payload.observacao,
            responsabilidade_id=payload.responsabilidade_id,
            dia=dia,
            semana=semana,
            acima_300=acima_300,
            cluster=cluster,
            idempotency_hash=h,
            source="MANUAL",
            created_by=created_by,
        )
        session.add(dev)
        session.commit()
        return JSONResponse({"ok": True, "id": dev.id})
    except Exception as e:
        logger.exception(f"Erro ao criar devoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o manual: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/api/devolucoes", response_class=JSONResponse)
async def api_devolucoes_list(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
):
    require_login(request)
    q = select(models.Devolucao).order_by(models.Devolucao.data_romaneio.desc(), models.Devolucao.created_at.desc())
    if start_date:
        q = q.where(models.Devolucao.data_romaneio >= start_date)
    if end_date:
        q = q.where(models.Devolucao.data_romaneio <= end_date)
    rows = session.exec(q.limit(500)).all()
    out = []
    for d in rows:
        c = session.get(models.Client, d.client_id)
        m = session.get(models.Employee, d.motorista_id)
        v = session.get(models.Employee, d.vendedor_id)
        motivo = session.get(models.DevolucaoMotivo, d.motivo_id)
        resp = session.get(models.DevolucaoResponsabilidade, d.responsabilidade_id)
        out.append({
            "id": d.id,
            "data_romaneio": d.data_romaneio,
            "data_entrega": d.data_entrega,
            "valor": d.valor,
            "cluster": d.cluster,
            "acima_300": d.acima_300,
            "source": d.source,
            "client_name": c.name if c else "-",
            "motorista_name": m.name if m else "-",
            "vendedor_name": v.name if v else "-",
            "motivo": motivo.nome if motivo else "-",
            "responsabilidade": resp.nome if resp else "-",
        })
    return JSONResponse({"ok": True, "data": out})


@app.get("/admin/backfill_xp")
async def backfill_xp(request: Request, session: Session = Depends(get_session)):
    require_login(request)
    # Recalculate XP for all employees
    employees = session.exec(select(models.Employee)).all()
    count = 0
    
    for emp in employees:
        # Sum tonnage of all valid completed routes
        statement = select(func.sum(models.Route.tonnage)).where(
            models.Route.employee_id == emp.id,
            models.Route.tonnage > 0,
            models.Route.end_time != None
        )
        total = session.exec(statement).one() or 0.0
        
        if total != emp.total_xp:
            emp.total_xp = total
            session.add(emp)
            count += 1
            
    session.commit()
    return JSONResponse({"status": "ok", "updated_employees": count, "message": "XP recalcitrado com sucesso!"})

# --- Strategy & Gamification Routes ---

@app.get("/api/strategy")
async def api_strategy_data(request: Request, date: Optional[str] = None, shift: Optional[str] = None, session: Session = Depends(get_session)):
    try:
        user = require_login(request)
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # Fetch all *completed* routes for analysis
        all_routes = session.exec(select(models.Route).where(models.Route.tonnage > 0).order_by(models.Route.date.desc())).all()
        clients = session.exec(select(models.Client)).all()
        client_map = {c.id: c.name for c in clients}

        # 1. ABC Curve
        client_stats = {} 
        today = datetime.now().date()
        start_date = today - timedelta(days=30)
        daily_stats = {start_date + timedelta(days=i): {'tonnage': 0.0, 'duration_seconds': 0.0, 'routes': 0} for i in range(31)}
        total_sys_tonnage = 0.0

        emp_stats = {} 
        client_dur_stats = {} 
        emp_day_intervals = {} 
        
        all_emps = {e.id: e.name for e in session.exec(select(models.Employee)).all()}
        
        # Track selected day stats
        selected_day_routes = 0
        selected_day_tonnage = 0.0
        selected_day_employees = set()
        
        # Track previous day for comparison
        selected_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        previous_date = selected_date_obj - timedelta(days=1)
        previous_date_str = previous_date.strftime("%Y-%m-%d")
        prev_day_tonnage = 0.0
        prev_day_routes = 0
        prev_day_kgh_sum = 0.0
        prev_day_kgh_count = 0
        
        for r in all_routes:
            t = r.tonnage or 0.0
            
            # ABC Logic
            total_sys_tonnage += t
            cid = r.client_id
            if cid not in client_stats:
                client_stats[cid] = {"name": client_map.get(cid, f"Client {cid}"), "tonnage": 0.0, "count": 0}
            client_stats[cid]['tonnage'] += t
            client_stats[cid]['count'] += 1
            
            # Chart Logic
            try:
                if r.date:
                    r_date_obj = datetime.strptime(r.date, "%Y-%m-%d").date()
                    if start_date <= r_date_obj <= today:
                        daily_stats[r_date_obj]['routes'] += 1
                        if r.start_time and r.end_time: 
                            s = datetime.strptime(r.start_time, "%H:%M")
                            e = datetime.strptime(r.end_time, "%H:%M")
                            diff = (e - s).total_seconds()
                            if diff > 0:
                                daily_stats[r_date_obj]['tonnage'] += t
                                daily_stats[r_date_obj]['duration_seconds'] += diff
            except:
                pass
            
            # Previous day stats for comparison
            if r.date == previous_date_str:
                prev_day_tonnage += t
                prev_day_routes += 1
                if r.start_time and r.end_time and r.employee_id:
                    try:
                        s = datetime.strptime(r.start_time, "%H:%M")
                        e = datetime.strptime(r.end_time, "%H:%M")
                        dur = (e - s).total_seconds() / 3600
                        if dur > 0:
                            kgh = t / dur
                            prev_day_kgh_sum += kgh
                            prev_day_kgh_count += 1
                    except:
                        pass
            
            # Individual Stats (Selected Date)
            if r.date == date:
                # Count all routes for selected date (before shift filter)
                selected_day_routes += 1
                selected_day_tonnage += t
                
                if shift and shift != "Todos" and r.shift != shift:
                     continue
                     
                if r.employee_id and r.start_time and r.end_time:
                    selected_day_employees.add(r.employee_id)
                    try:
                        s = datetime.strptime(r.start_time, "%H:%M")
                        e = datetime.strptime(r.end_time, "%H:%M")
                        dur = (e - s).total_seconds()
                        
                        if r.client_id:
                            if r.client_id not in client_dur_stats:
                                client_dur_stats[r.client_id] = {'sum': 0, 'count': 0}
                            client_dur_stats[r.client_id]['sum'] += dur
                            client_dur_stats[r.client_id]['count'] += 1
                        
                        eid = r.employee_id
                        if eid not in emp_stats: emp_stats[eid] = {'ton': 0, 'dur': 0}
                        emp_stats[eid]['ton'] += (r.tonnage or 0)
                        emp_stats[eid]['dur'] += dur
                        
                        key = (eid, r.date)
                        if key not in emp_day_intervals: emp_day_intervals[key] = []
                        emp_day_intervals[key].append((s, e))
                    except:
                        pass
                    
        # Chart Data
        prod_chart_labels = []
        prod_chart_data = [] 
        
        for d in sorted(daily_stats.keys()):
            stats = daily_stats[d]
            t = stats['tonnage']
            sec = stats['duration_seconds']
            hours = sec / 3600
            kgh = (t / hours) if hours > 0 else 0.0
            prod_chart_labels.append(d.strftime("%d/%m"))
            prod_chart_data.append(round(kgh, 1))

        # ABC Data
        abc_data = sorted(client_stats.values(), key=lambda x: x['tonnage'], reverse=True)
        cumulative = 0.0
        for item in abc_data:
            cumulative += item['tonnage']
            item['share'] = (item['tonnage'] / total_sys_tonnage * 100) if total_sys_tonnage else 0
            item['cumulative_share'] = (cumulative / total_sys_tonnage * 100) if total_sys_tonnage else 0
            
            item['class'] = 'A' if item['cumulative_share'] <= 80 else 'B' if item['cumulative_share'] <= 95 else 'C'

        # SLA Ranking
        final_sla = []
        for cid, stats in client_dur_stats.items():
            if stats['count'] > 0:
                avg_sec = stats['sum'] / stats['count']
                avg_min = int(avg_sec / 60)
                fmt = f"{int(avg_sec//3600)}h {int((avg_sec%3600)//60)}m"
                final_sla.append({
                    "name": client_map.get(cid, "Client"),
                    "sla_min": avg_min,
                    "sla_fmt": fmt,
                    "count": stats['count']
                })
        sla_ranking = sorted(final_sla, key=lambda x: x['sla_min'], reverse=True)[:10]
        
        # Productivity & Idle
        productivity = []
        emp_objs = {e.id: e for e in session.exec(select(models.Employee)).all()}
        
        total_kgh_sum = 0
        total_kgh_count = 0
        total_idle_sum = 0
        
        for eid, s in emp_stats.items():
            real_active_hours = 0.0
            intervals = emp_day_intervals.get((eid, date), [])
            if intervals:
                intervals.sort(key=lambda x: x[0])
                merged = []
                for start, end in intervals:
                    if not merged or start > merged[-1][1]:
                        merged.append([start, end])
                    else:
                        merged[-1][1] = max(merged[-1][1], end)
                real_active_hours = sum((m[1] - m[0]).total_seconds() for m in merged) / 3600

            kgh = (s['ton'] / real_active_hours) if real_active_hours > 0 else 0
            
            if kgh > 0:
                total_kgh_sum += kgh
                total_kgh_count += 1
                
            emp = emp_objs.get(eid)
            shift_duration_hours = 8.0 
            if emp and emp.work_schedule:
                try:
                    parts = emp.work_schedule.split('-')
                    if len(parts) == 2:
                        h_start = datetime.strptime(parts[0].strip(), "%H:%M")
                        h_end = datetime.strptime(parts[1].strip(), "%H:%M")
                        if h_end < h_start: h_end += timedelta(days=1)
                        shift_duration_hours = (h_end - h_start).total_seconds() / 3600
                except:
                    pass
            
            idle_hours = max(0, shift_duration_hours - real_active_hours)
            total_idle_sum += idle_hours
            
            productivity.append({
                "name": all_emps.get(eid, "Unknown"),
                "kgh": kgh,
                "active_hours": real_active_hours,
                "idle_hours": idle_hours,
                "shift_duration": shift_duration_hours
            })
            
        productivity.sort(key=lambda x: x['kgh'], reverse=True)

        # KPI Summaries
        avg_sys_kgh = (total_kgh_sum / total_kgh_count) if total_kgh_count > 0 else 0
        avg_sys_idle = (total_idle_sum / len(productivity)) if productivity else 0
        prev_day_kgh = (prev_day_kgh_sum / prev_day_kgh_count) if prev_day_kgh_count > 0 else 0
        
        # Calculate comparison percentages
        kgh_change = ((avg_sys_kgh - prev_day_kgh) / prev_day_kgh * 100) if prev_day_kgh > 0 else 0
        tonnage_change = ((selected_day_tonnage - prev_day_tonnage) / prev_day_tonnage * 100) if prev_day_tonnage > 0 else 0
        
        # Calculate weekly average for comparison
        week_start = selected_date_obj - timedelta(days=7)
        week_kgh_values = []
        for d in sorted(daily_stats.keys()):
            if week_start <= d < selected_date_obj:
                stats = daily_stats[d]
                if stats['duration_seconds'] > 0:
                    week_kgh_values.append(stats['tonnage'] / (stats['duration_seconds'] / 3600))
        week_avg_kgh = sum(week_kgh_values) / len(week_kgh_values) if week_kgh_values else 0
        
        # Meta/Target (use week average as reference or fixed target)
        target_kgh = max(week_avg_kgh, 200)  # At least 200 Kg/h as minimum target
        meta_percent = (avg_sys_kgh / target_kgh * 100) if target_kgh > 0 else 0
        
        # Generate Alerts/Insights
        alerts = []
        
        # High idle employees
        high_idle_count = sum(1 for p in productivity if p['idle_hours'] > 2.0)
        if high_idle_count > 0:
            alerts.append({
                "type": "warning",
                "icon": "ÃƒÂ¢Ã‚ÂÃ‚Â±ÃƒÂ¯Ã‚Â¸Ã‚Â",
                "message": f"{high_idle_count} colaborador{'es' if high_idle_count > 1 else ''} com ociosidade > 2h",
                "severity": "medium"
            })
        
        # Critical SLA clients
        critical_sla = [s for s in sla_ranking if s['sla_min'] > 60]
        if critical_sla:
            alerts.append({
                "type": "danger",
                "icon": "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨",
                "message": f"{len(critical_sla)} cliente{'s' if len(critical_sla) > 1 else ''} com SLA crÃƒÆ’Ã‚Â­tico (>1h)",
                "severity": "high"
            })
        
        # Productivity comparison
        if kgh_change > 10:
            alerts.append({
                "type": "success",
                "icon": "ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‹â€ ",
                "message": f"Produtividade {kgh_change:.0f}% acima do dia anterior",
                "severity": "low"
            })
        elif kgh_change < -10:
            alerts.append({
                "type": "warning",
                "icon": "ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â°",
                "message": f"Produtividade {abs(kgh_change):.0f}% abaixo do dia anterior",
                "severity": "medium"
            })
        
        # Elite performers
        elite_count = sum(1 for p in productivity if p['kgh'] > 300)
        if elite_count > 0:
            alerts.append({
                "type": "success",
                "icon": "ÃƒÂ°Ã…Â¸Ã…Â¡Ã¢â€šÂ¬",
                "message": f"{elite_count} colaborador{'es' if elite_count > 1 else ''} com performance Elite (>300 Kg/h)",
                "severity": "low"
            })
        
        # Low performers
        low_perf_count = sum(1 for p in productivity if 0 < p['kgh'] < 150)
        if low_perf_count > 0:
            alerts.append({
                "type": "warning", 
                "icon": "ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â",
                "message": f"{low_perf_count} colaborador{'es' if low_perf_count > 1 else ''} abaixo da meta (<150 Kg/h)",
                "severity": "medium"
            })
        
        # If no alerts, add positive message
        if not alerts:
            alerts.append({
                "type": "success",
                "icon": "ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦",
                "message": "OperaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o dentro dos parÃƒÆ’Ã‚Â¢metros normais",
                "severity": "low"
            })

        return {
            "abc_data": abc_data,
            "prod_chart_labels": prod_chart_labels,
            "prod_chart_data": prod_chart_data,
            "prod_chart_target": round(target_kgh, 1),
            "total_tonnage": total_sys_tonnage,
            "kpi": {
                "global_kgh": f"{avg_sys_kgh:,.1f}".replace(".", ","),
                "global_kgh_raw": round(avg_sys_kgh, 1),
                "avg_idle": f"{avg_sys_idle:,.1f}h".replace(".", ","),
                "avg_idle_raw": round(avg_sys_idle, 2),
                "total_vol": f"{selected_day_tonnage:,.0f}".replace(",", "."),
                "total_vol_raw": round(selected_day_tonnage, 2),
                "routes_count": selected_day_routes,
                "employees_count": len(selected_day_employees),
                "kgh_change": round(kgh_change, 1),
                "tonnage_change": round(tonnage_change, 1),
                "meta_percent": round(meta_percent, 1),
                "target_kgh": round(target_kgh, 1),
                "prev_day_kgh": round(prev_day_kgh, 1),
                "week_avg_kgh": round(week_avg_kgh, 1)
            },
            "productivity": productivity,
            "sla_ranking": sla_ranking,
            "alerts": alerts,
            "selected_date": date,
            "selected_shift": shift or "Todos"
        }
    except Exception as e:
        logger.exception(f"Error in API Strategy: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/strategy", response_class=HTMLResponse)
async def strategy_page(request: Request):
    # Static Skeleton - Data loaded via API
    return templates.TemplateResponse("strategy.html", {"request": request})


@app.get("/bi", response_class=HTMLResponse)
async def bi_entry():
    return RedirectResponse(url="/bi/delivery", status_code=302)



def _build_bi_delivery_dataset(
    session: Session,
    date_from: Optional[str],
    date_to: Optional[str],
    shift: str,
    driver_id: Optional[int],
    plate: str,
    status: str,
    detail_driver_id: Optional[int] = None,
    detail_status: str = "Todos",
) -> dict:
    tz = ZoneInfo("America/Sao_Paulo")
    today = datetime.now(tz).date()

    def _parse_date(raw: Optional[str]) -> Optional[date]:
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            return None

    parsed_from = _parse_date(date_from) or (today - timedelta(days=6))
    parsed_to = _parse_date(date_to) or today
    if parsed_from > parsed_to:
        parsed_from, parsed_to = parsed_to, parsed_from

    status_norm = (status or "Todos").strip().lower()
    plate_norm = (plate or "Todos").strip().upper()
    detail_status_norm = (detail_status or "Todos").strip().lower()

    query = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= parsed_from.strftime("%Y-%m-%d"))
        .where(models.Route.date <= parsed_to.strftime("%Y-%m-%d"))
    )
    if shift and shift != "Todos":
        query = query.where(models.Route.shift == shift)
    if driver_id:
        query = query.where(models.Route.employee_id == driver_id)
    if plate_norm and plate_norm != "TODOS":
        query = query.where(models.Route.delivery_vehicle_plate == plate_norm)
    if status_norm and status_norm != "todos":
        query = query.where(func.lower(models.Route.delivery_status) == status_norm)

    routes = session.exec(query.order_by(models.Route.date, models.Route.created_at)).all()

    employee_ids = sorted({r.employee_id for r in routes if r.employee_id})
    client_ids = sorted({r.client_id for r in routes if r.client_id})
    plate_set = sorted({(r.delivery_vehicle_plate or "").strip().upper() for r in routes if (r.delivery_vehicle_plate or "").strip()})

    employee_map = {}
    if employee_ids:
        emps = session.exec(select(models.Employee).where(models.Employee.id.in_(employee_ids))).all()
        employee_map = {e.id: e for e in emps}

    client_map = {}
    if client_ids:
        clients = session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all()
        client_map = {c.id: c for c in clients}

    vehicle_map = {}
    if plate_set:
        vehicles = session.exec(select(models.Vehicle).where(models.Vehicle.placa.in_(plate_set))).all()
        vehicle_map = {v.placa.upper(): v for v in vehicles}

    def _parse_hhmm(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            hh, mm = str(value).strip().split(":")
            return int(hh) * 60 + int(mm)
        except Exception:
            return None

    def _duration_minutes(start_value: Optional[str], end_value: Optional[str]) -> Optional[int]:
        start_m = _parse_hhmm(start_value)
        end_m = _parse_hhmm(end_value)
        if start_m is None or end_m is None:
            return None
        if end_m < start_m:
            end_m += 24 * 60
        return max(0, end_m - start_m)

    per_driver = {}
    per_day = {}
    route_rows = []
    exception_rows = []
    route_durations = []
    anomaly_flags = []

    planned_stops = len(routes)
    planned_kg = 0.0
    planned_value = 0.0
    realized_stops = 0
    realized_kg = 0.0
    realized_value = 0.0
    started_stops = 0
    returned_stops = 0
    returned_kg = 0.0
    returned_value = 0.0
    reopen_routes = 0

    for r in routes:
        status_raw = (r.delivery_status or "pendente").strip().lower()
        employee = employee_map.get(r.employee_id)
        client = client_map.get(r.client_id)

        driver_name = employee.name if employee else f"Motorista #{r.employee_id}"
        truck_plate = (r.delivery_vehicle_plate or "-").upper()
        vehicle = vehicle_map.get(truck_plate)
        vehicle_label = f"{truck_plate} - {vehicle.modelo}" if vehicle else truck_plate
        planned_w = float(r.tonnage or 0.0)
        planned_v = float(r.valor_financeiro or 0.0)
        return_w = float(r.devolucao_volume if r.devolucao_volume is not None else (planned_w if status_raw == "devolucao" else 0.0))
        return_v = float(r.valor_devolucao if r.valor_devolucao is not None else (planned_v if status_raw == "devolucao" else 0.0))
        delivered_w = max(0.0, planned_w - return_w) if status_raw == "devolucao" else (planned_w if status_raw == "entregue" else 0.0)
        delivered_v = max(0.0, planned_v - return_v) if status_raw == "devolucao" else (planned_v if status_raw == "entregue" else 0.0)

        planned_kg += planned_w
        planned_value += planned_v

        is_started = status_raw in ("iniciada", "devolucao", "entregue")
        is_realized = status_raw in ("devolucao", "entregue")
        if is_started:
            started_stops += 1
        if is_realized:
            realized_stops += 1
            realized_kg += delivered_w
            realized_value += delivered_v
        if status_raw == "devolucao":
            returned_stops += 1
            returned_kg += return_w
            returned_value += return_v
        if (r.delivery_reopen_count or 0) > 0:
            reopen_routes += 1

        duration_m = _duration_minutes(r.delivery_started_at or r.start_time, r.delivery_finished_at or r.end_time)
        if duration_m is not None and is_realized:
            route_durations.append(duration_m)

        route_rows.append({
            "route_id": r.id,
            "date": r.date,
            "shift": r.shift,
            "driver_id": r.employee_id,
            "driver_name": driver_name,
            "client_id": r.client_id,
            "client_name": client.name if client else f"Cliente #{r.client_id}",
            "status": status_raw,
            "planned_kg": round(planned_w, 2),
            "planned_value": round(planned_v, 2),
            "delivered_kg": round(delivered_w, 2),
            "delivered_value": round(delivered_v, 2),
            "returned_kg": round(return_w if status_raw == "devolucao" else 0.0, 2),
            "returned_value": round(return_v if status_raw == "devolucao" else 0.0, 2),
            "reopen_count": r.delivery_reopen_count or 0,
            "duration_m": duration_m,
            "plate": truck_plate,
            "vehicle_label": vehicle_label,
            "address": r.delivery_address or "",
            "neighborhood": r.delivery_neighborhood or "",
            "city": r.delivery_city or "",
            "order_number": r.delivery_order_number or "-",
        })

        driver_bucket = per_driver.setdefault(
            driver_name,
            {
                "driver_name": driver_name,
                "driver_id": r.employee_id,
                "planned_stops": 0,
                "realized_stops": 0,
                "pending_stops": 0,
                "started_stops": 0,
                "returned_stops": 0,
                "planned_kg": 0.0,
                "realized_kg": 0.0,
                "returned_kg": 0.0,
                "planned_value": 0.0,
                "realized_value": 0.0,
                "returned_value": 0.0,
                "reopen_count": 0,
                "durations": [],
                "main_plate": truck_plate,
            },
        )
        driver_bucket["planned_stops"] += 1
        driver_bucket["planned_kg"] += planned_w
        driver_bucket["planned_value"] += planned_v
        driver_bucket["reopen_count"] += (r.delivery_reopen_count or 0)
        if is_started:
            driver_bucket["started_stops"] += 1
        if is_realized:
            driver_bucket["realized_stops"] += 1
            driver_bucket["realized_kg"] += delivered_w
            driver_bucket["realized_value"] += delivered_v
        else:
            driver_bucket["pending_stops"] += 1
        if status_raw == "devolucao":
            driver_bucket["returned_stops"] += 1
            driver_bucket["returned_kg"] += return_w
            driver_bucket["returned_value"] += return_v
        if duration_m is not None:
            driver_bucket["durations"].append(duration_m)

        day_bucket = per_day.setdefault(
            r.date,
            {
                "date": r.date,
                "planned_stops": 0,
                "started_stops": 0,
                "realized_stops": 0,
                "returned_stops": 0,
                "planned_kg": 0.0,
                "returned_kg": 0.0,
                "planned_value": 0.0,
                "returned_value": 0.0,
            },
        )
        day_bucket["planned_stops"] += 1
        day_bucket["planned_kg"] += planned_w
        day_bucket["planned_value"] += planned_v
        if is_started:
            day_bucket["started_stops"] += 1
        if is_realized:
            day_bucket["realized_stops"] += 1
        if status_raw == "devolucao":
            day_bucket["returned_stops"] += 1
            day_bucket["returned_kg"] += return_w
            day_bucket["returned_value"] += return_v

        score = 0
        if status_raw in ("pendente", "reaberta"):
            score += 25
        if status_raw == "iniciada":
            score += 20
        if status_raw == "devolucao":
            score += 55
        score += min(20, (r.delivery_reopen_count or 0) * 6)
        if duration_m is not None and duration_m > 120:
            score += 10
        if planned_w >= 500:
            score += 8

        if score >= 30:
            exception_rows.append(
                {
                    "route_id": r.id,
                    "date": r.date,
                    "shift": r.shift,
                    "driver_name": driver_name,
                    "driver_id": r.employee_id,
                    "client_name": client.name if client else f"Cliente #{r.client_id}",
                    "status": status_raw,
                    "planned_kg": round(planned_w, 2),
                    "planned_value": round(planned_v, 2),
                    "returned_kg": round(return_w if status_raw == "devolucao" else 0.0, 2),
                    "reopen_count": r.delivery_reopen_count or 0,
                    "duration_m": duration_m,
                    "score": score,
                    "vehicle_label": vehicle_label,
                }
            )

    global_return_rate = (returned_stops / planned_stops * 100.0) if planned_stops else 0.0
    avg_duration = statistics.mean(route_durations) if route_durations else 0.0

    tactical_rows = []
    for _, bucket in per_driver.items():
        avg_driver_duration = statistics.mean(bucket["durations"]) if bucket["durations"] else 0.0
        efficiency = (bucket["realized_stops"] / bucket["planned_stops"] * 100.0) if bucket["planned_stops"] else 0.0
        return_rate = (bucket["returned_stops"] / bucket["planned_stops"] * 100.0) if bucket["planned_stops"] else 0.0
        started_rate = (bucket["started_stops"] / bucket["planned_stops"] * 100.0) if bucket["planned_stops"] else 0.0
        tactical_rows.append({
            **bucket,
            "efficiency": round(efficiency, 2),
            "return_rate": round(return_rate, 2),
            "started_rate": round(started_rate, 2),
            "avg_duration": round(avg_driver_duration, 1),
        })
        if bucket["planned_stops"] >= 5 and return_rate >= (global_return_rate + 10.0):
            anomaly_flags.append(
                f"{bucket['driver_name']} com devolucao {return_rate:.1f}% (media geral {global_return_rate:.1f}%)."
            )
        if avg_driver_duration > 0 and avg_duration > 0 and avg_driver_duration >= (avg_duration * 1.8):
            anomaly_flags.append(
                f"{bucket['driver_name']} com tempo medio {avg_driver_duration:.0f} min (media geral {avg_duration:.0f} min)."
            )
    tactical_rows.sort(key=lambda x: (x["efficiency"], -x["return_rate"], x["planned_stops"]), reverse=True)

    daily_rows = []
    for day in sorted(per_day.keys()):
        row = per_day[day]
        row["started_rate"] = round((row["started_stops"] / row["planned_stops"] * 100.0), 2) if row["planned_stops"] else 0.0
        row["return_rate"] = round((row["returned_stops"] / row["planned_stops"] * 100.0), 2) if row["planned_stops"] else 0.0
        daily_rows.append(row)

    last_n = daily_rows[-7:] if len(daily_rows) >= 7 else daily_rows
    if last_n:
        forecast_stops = round(statistics.mean([x["planned_stops"] for x in last_n]), 1)
        forecast_return_rate = round(statistics.mean([x["return_rate"] for x in last_n]), 2)
    else:
        forecast_stops = 0.0
        forecast_return_rate = 0.0

    exception_rows.sort(key=lambda x: (x["score"], x["planned_kg"]), reverse=True)
    top_exceptions = exception_rows[:25]

    recommendations = []
    if global_return_rate >= 10:
        recommendations.append("Priorizar auditoria de devolucao nas rotas com maior peso e revisar motivo/cliente recorrente.")
    if tactical_rows:
        worst_return = max(tactical_rows, key=lambda x: x["return_rate"])
        if worst_return["return_rate"] >= 15 and worst_return["planned_stops"] >= 5:
            recommendations.append(
                f"Rebalancear carga de {worst_return['driver_name']} e aplicar apoio adicional para reduzir devolucao."
            )
    if started_stops < planned_stops:
        recommendations.append("Atuar na fila de pendentes com priorizacao por alto peso para reduzir risco de atraso.")
    if avg_duration >= 120:
        recommendations.append("Tempo medio elevado: revisar sequencia de paradas e pontos de congestionamento.")
    if not recommendations:
        recommendations.append("Operacao estavel no periodo; manter monitoramento diario dos alertas de devolucao.")

    filters_payload = {
        "date_from": parsed_from.strftime("%Y-%m-%d"),
        "date_to": parsed_to.strftime("%Y-%m-%d"),
        "shift": shift,
        "driver_id": driver_id,
        "plate": plate,
        "status": status,
        "detail_driver_id": detail_driver_id,
        "detail_status": detail_status,
    }

    drivers_filter = sorted(
        [{"id": d["driver_id"], "name": d["driver_name"]} for d in tactical_rows],
        key=lambda x: x["name"],
    )
    plates_filter = sorted({x["main_plate"] for x in tactical_rows if x["main_plate"] and x["main_plate"] != "-"})

    detail_rows = route_rows
    detail_tokens = []
    if detail_driver_id:
        detail_rows = [r for r in detail_rows if r["driver_id"] == detail_driver_id]
        driver_label = next((r["driver_name"] for r in detail_rows), f"Motorista #{detail_driver_id}")
        detail_tokens.append(f"Motorista: {driver_label}")
    if detail_status_norm != "todos":
        detail_rows = [r for r in detail_rows if r["status"] == detail_status_norm]
        detail_tokens.append(f"Status: {detail_status_norm.title()}")
    detail_rows = sorted(detail_rows, key=lambda x: (x["date"], x["shift"], x["driver_name"], x["route_id"]))
    detail_title = " | ".join(detail_tokens) if detail_tokens else "Todos os detalhes do periodo"

    filters_query = urlencode(
        {
            "date_from": filters_payload["date_from"],
            "date_to": filters_payload["date_to"],
            "shift": filters_payload["shift"],
            "driver_id": filters_payload["driver_id"] or "",
            "plate": filters_payload["plate"],
            "status": filters_payload["status"],
        }
    )

    kpis = {
        "planned_stops": planned_stops,
        "realized_stops": realized_stops,
        "started_stops": started_stops,
        "pending_stops": max(0, planned_stops - started_stops),
        "planned_kg": round(planned_kg, 2),
        "realized_kg": round(realized_kg, 2),
        "returned_kg": round(returned_kg, 2),
        "planned_value": round(planned_value, 2),
        "realized_value": round(realized_value, 2),
        "returned_value": round(returned_value, 2),
        "return_rate_qtd": round((returned_stops / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "return_rate_kg": round((returned_kg / planned_kg * 100.0), 2) if planned_kg else 0.0,
        "return_rate_value": round((returned_value / planned_value * 100.0), 2) if planned_value else 0.0,
        "sla_start": round((started_stops / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "sla_finish": round((realized_stops / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "reopen_index": round((reopen_routes / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "avg_duration_m": round(avg_duration, 1) if avg_duration else 0.0,
        "forecast_next_stops": forecast_stops,
        "forecast_next_return_rate": forecast_return_rate,
    }

    return {
        "filters": filters_payload,
        "kpis": kpis,
        "daily_rows": daily_rows,
        "tactical_rows": tactical_rows,
        "exception_rows": top_exceptions,
        "anomaly_flags": anomaly_flags[:10],
        "recommendations": recommendations[:6],
        "drivers_filter": drivers_filter,
        "plates_filter": plates_filter,
        "statuses_filter": ["Todos", "Pendente", "Iniciada", "Entregue", "Devolucao", "Reaberta", "Cancelada"],
        "detail_rows": detail_rows[:300],
        "detail_title": detail_title,
        "detail_total": len(detail_rows),
        "filters_query": filters_query,
        "all_route_rows": route_rows,
    }


@app.get("/bi/delivery", response_class=HTMLResponse)
async def bi_delivery_page(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    shift: str = "Todos",
    driver_id: Optional[str] = None,
    plate: str = "Todos",
    status: str = "Todos",
    detail_driver_id: Optional[str] = None,
    detail_status: str = "Todos",
    session: Session = Depends(get_session),
):
    parsed_driver_id: Optional[int] = None
    if driver_id is not None:
        raw_driver_filter = str(driver_id).strip()
        if raw_driver_filter.isdigit():
            parsed_driver_id = int(raw_driver_filter)

    parsed_detail_driver_id: Optional[int] = None
    if detail_driver_id is not None:
        raw_driver = str(detail_driver_id).strip()
        if raw_driver.isdigit():
            parsed_detail_driver_id = int(raw_driver)

    dataset = _build_bi_delivery_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift=shift,
        driver_id=parsed_driver_id,
        plate=plate,
        status=status,
        detail_driver_id=parsed_detail_driver_id,
        detail_status=detail_status,
    )
    return templates.TemplateResponse("bi_delivery.html", {"request": request, **dataset})


@app.get("/bi/delivery/export")
async def bi_delivery_export(
    format: str = "csv",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    shift: str = "Todos",
    driver_id: Optional[str] = None,
    plate: str = "Todos",
    status: str = "Todos",
    session: Session = Depends(get_session),
):
    parsed_driver_id: Optional[int] = None
    if driver_id is not None:
        raw_driver_filter = str(driver_id).strip()
        if raw_driver_filter.isdigit():
            parsed_driver_id = int(raw_driver_filter)

    dataset = _build_bi_delivery_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift=shift,
        driver_id=parsed_driver_id,
        plate=plate,
        status=status,
    )
    rows = dataset["all_route_rows"]
    timestamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M")
    fmt = (format or "csv").strip().lower()

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["rota_id", "data", "turno", "motorista", "cliente", "status", "kg_planejado", "kg_entregue", "kg_devolvido", "valor_planejado", "valor_entregue", "valor_devolvido", "reaberturas", "duracao_min", "placa", "pedido"])
        for r in rows:
            writer.writerow([r["route_id"], r["date"], r["shift"], r["driver_name"], r["client_name"], r["status"], f"{r['planned_kg']:.2f}", f"{r['delivered_kg']:.2f}", f"{r['returned_kg']:.2f}", f"{r['planned_value']:.2f}", f"{r['delivered_value']:.2f}", f"{r['returned_value']:.2f}", r["reopen_count"], r["duration_m"] or "", r["plate"], r["order_number"]])
        buffer = io.BytesIO(output.getvalue().encode("utf-8-sig"))
        filename = f"bi_entregas_{timestamp}.csv"
        return StreamingResponse(buffer, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})

    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "BI Entregas"
        ws.append(["Rota ID", "Data", "Turno", "Motorista", "Cliente", "Status", "Kg Planejado", "Kg Entregue", "Kg Devolvido", "Valor Planejado", "Valor Entregue", "Valor Devolvido", "Reaberturas", "Duracao (min)", "Placa", "Pedido"])
        for r in rows:
            ws.append([r["route_id"], r["date"], r["shift"], r["driver_name"], r["client_name"], r["status"], r["planned_kg"], r["delivered_kg"], r["returned_kg"], r["planned_value"], r["delivered_value"], r["returned_value"], r["reopen_count"], r["duration_m"] or 0, r["plate"], r["order_number"]])
        excel_buffer = io.BytesIO()
        wb.save(excel_buffer)
        excel_buffer.seek(0)
        filename = f"bi_entregas_{timestamp}.xlsx"
        return StreamingResponse(excel_buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})

    if fmt == "pdf":
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)
        width, height = A4
        y = height - 40
        c.setFont("Helvetica-Bold", 12)
        c.drawString(30, y, "BI Entregas - Relatorio Executivo")
        y -= 16
        c.setFont("Helvetica", 9)
        c.drawString(30, y, f"Periodo: {dataset['filters']['date_from']} ate {dataset['filters']['date_to']}")
        y -= 14
        c.drawString(30, y, f"Planejadas: {dataset['kpis']['planned_stops']} | Realizadas: {dataset['kpis']['realized_stops']} | Devolucao: {dataset['kpis']['return_rate_qtd']:.1f}%")
        y -= 20
        c.setFont("Helvetica-Bold", 9)
        c.drawString(30, y, "Data")
        c.drawString(95, y, "Motorista")
        c.drawString(265, y, "Cliente")
        c.drawString(450, y, "Status")
        c.drawString(500, y, "Kg")
        c.drawString(545, y, "R$")
        y -= 12
        c.setFont("Helvetica", 8)
        for r in rows[:180]:
            if y <= 30:
                c.showPage()
                y = height - 30
                c.setFont("Helvetica", 8)
            c.drawString(30, y, str(r["date"]))
            c.drawString(95, y, str(r["driver_name"])[:28])
            c.drawString(265, y, str(r["client_name"])[:32])
            c.drawString(450, y, str(r["status"])[:10])
            c.drawRightString(535, y, f"{r['planned_kg']:.1f}")
            c.drawRightString(590, y, f"{r['planned_value']:.0f}")
            y -= 10
        c.save()
        pdf_buffer.seek(0)
        filename = f"bi_entregas_{timestamp}.pdf"
        return StreamingResponse(pdf_buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})

    return JSONResponse({"error": "Formato invalido. Use csv, xlsx ou pdf."}, status_code=400)
ABSENCE_JUSTIFIED_KEYWORDS = [
    "atestado",
    "sick",
    "absence_justified",
    "justificativa",
    "medical_leave",
    "ausencia_justificada",
    "justificada",
    "medico",
    "mÃƒÆ’Ã‚Â©dico",
    "doenca",
    "doenÃƒÆ’Ã‚Â§a",
    "hospital",
    "consulta",
    "exame"
]
ABSENCE_UNJUSTIFIED_KEYWORDS = [
    "falta",
    "absent",
    "absence_unjustified",
    "no_show",
    "ausencia_injustificada",
    "injustificada"
]
ABSENCE_LEAVE_KEYWORDS = [
    "afastamento",
    "away",
    "vacation",
    "ferias",
    "inss",
    "licenca",
    "leave",
    "afastado"
]
ABSENCE_PRESENT_KEYWORDS = [
    "presenca",
    "presente",
    "present",
    "trabalhou",
    "trabalho"
]
ABSENCE_OFFDAY_KEYWORDS = [
    "folga",
    "dayoff",
    "day_off",
    "dsr",
    "compensacao",
    "offday"
]
ROUTINE_AUDIT_KEYWORDS = [
    "rotina setada",
    "rotina definida",
    "rotina alterada",
    "rotina atualizada",
    "rotina marcada"
]
# Prioridade de ausÃƒÆ’Ã‚Âªncias: maior valor = mais prioritÃƒÆ’Ã‚Â¡rio
# justified (atestado) > unjustified (falta) - atestado SEMPRE prevalece sobre falta
ABSENCE_PRIORITY = {"leave": 5, "justified": 4, "offday": 2, "unjustified": 1, "present": 0}
ROUTE_BAND_LABELS = {"Leve": "Leve", "Media": "MÃƒÆ’Ã‚Â©dia", "Pesada": "Pesada"}
TENURE_BAND_LABELS = {"Novatos": "Novatos", "Consolidacao": "ConsolidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "Veteranos": "Veteranos"}


def get_absence_priority(group: Optional[str]) -> int:
    return ABSENCE_PRIORITY.get(group, -1)


def normalize_event_label(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = str(value).strip().lower()
    cleaned = cleaned.replace("_", " ").replace("-", " ").replace("/", " ")
    cleaned = " ".join(cleaned.split())
    normalized = unicodedata.normalize("NFKD", cleaned)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(normalized.split())


def normalize_routine_status(status: Optional[str]) -> str:
    if not status:
        return "unknown"
    label = normalize_event_label(status)
    if not label:
        return "unknown"
    if any(keyword in label for keyword in ABSENCE_JUSTIFIED_KEYWORDS):
        return "justified"
    if any(keyword in label for keyword in ABSENCE_LEAVE_KEYWORDS):
        return "leave"
    if any(keyword in label for keyword in ABSENCE_OFFDAY_KEYWORDS):
        return "offday"
    if any(keyword in label for keyword in ABSENCE_PRESENT_KEYWORDS):
        return "present"
    if any(keyword in label for keyword in ABSENCE_UNJUSTIFIED_KEYWORDS):
        return "unjustified"
    return "unknown"


def normalize_event_group_from_type(event_type: Optional[str], event_category: Optional[str]) -> str:
    combined = " ".join([event_type or "", event_category or ""]).strip()
    if not combined:
        return "unknown"
    label = normalize_event_label(combined)
    if not label:
        return "unknown"
    if any(keyword in label for keyword in ABSENCE_JUSTIFIED_KEYWORDS):
        return "justified"
    if any(keyword in label for keyword in ABSENCE_UNJUSTIFIED_KEYWORDS):
        return "unjustified"
    if any(keyword in label for keyword in ABSENCE_LEAVE_KEYWORDS):
        return "leave"
    if any(keyword in label for keyword in ABSENCE_OFFDAY_KEYWORDS):
        return "offday"
    if any(keyword in label for keyword in ABSENCE_PRESENT_KEYWORDS):
        return "present"
    return "unknown"


def normalize_event_status(event_type: Optional[str], event_category: Optional[str], event_text: Optional[str]) -> str:
    group_from_type = normalize_event_group_from_type(event_type, event_category)
    if group_from_type not in ["unknown", "present"]:
        return group_from_type
    text_label = normalize_event_label(event_text)
    if not text_label:
        return "unknown"
    if any(keyword in text_label for keyword in ROUTINE_AUDIT_KEYWORDS):
        return "unknown"
    if any(keyword in text_label for keyword in ABSENCE_JUSTIFIED_KEYWORDS):
        return "justified"
    if any(keyword in text_label for keyword in ABSENCE_UNJUSTIFIED_KEYWORDS):
        return "unjustified"
    if any(keyword in text_label for keyword in ABSENCE_LEAVE_KEYWORDS):
        return "leave"
    if any(keyword in text_label for keyword in ABSENCE_OFFDAY_KEYWORDS):
        return "offday"
    if any(keyword in text_label for keyword in ABSENCE_PRESENT_KEYWORDS):
        return "present"
    return "unknown"


def classify_event_label(label: str) -> Optional[str]:
    if not label:
        return None
    for keyword in ABSENCE_LEAVE_KEYWORDS:
        if keyword in label:
            return "leave"
    for keyword in ABSENCE_JUSTIFIED_KEYWORDS:
        if keyword in label:
            return "justified"
    for keyword in ABSENCE_OFFDAY_KEYWORDS:
        if keyword in label:
            return "offday"
    for keyword in ABSENCE_UNJUSTIFIED_KEYWORDS:
        if keyword in label:
            return "unjustified"
    return None


def classify_event_record(event_type: Optional[str], event_category: Optional[str], event_text: Optional[str]) -> Optional[str]:
    group = normalize_event_status(event_type, event_category, event_text)
    if group in ["unknown", "present"]:
        return None
    return group


def classify_routine_label(routine: Optional[str]) -> Optional[str]:
    group = normalize_routine_status(routine)
    if group in ["unknown", "present"]:
        return None
    return group


def classify_event_log_group(event_type: Optional[str], event_category: Optional[str], event_text: Optional[str]) -> str:
    group = normalize_event_group_from_type(event_type, event_category)
    if group not in ["unknown", "present"]:
        return group
    text_label = normalize_event_label(event_text)
    if not text_label:
        return "unknown"
    if any(keyword in text_label for keyword in ABSENCE_JUSTIFIED_KEYWORDS):
        return "justified"
    if any(keyword in text_label for keyword in ABSENCE_UNJUSTIFIED_KEYWORDS):
        return "unjustified"
    if any(keyword in text_label for keyword in ABSENCE_LEAVE_KEYWORDS):
        return "leave"
    if any(keyword in text_label for keyword in ABSENCE_OFFDAY_KEYWORDS):
        return "offday"
    if any(keyword in text_label for keyword in ABSENCE_PRESENT_KEYWORDS):
        return "present"
    return "unknown"


def fetch_absences_agg(session: Session, employee_ids: List[int], start_dt: datetime, end_dt: datetime, include_day_map: bool = False) -> tuple:
    if not employee_ids:
        return {}, {"unknown": 0, "examples": [], "sources": {}, "debug_days": {}}

    per_employee_days = {}
    per_employee_sources = {}
    per_employee_record_ids = {}
    per_employee_debug = {}
    per_employee_routine_days = {}
    per_employee_present_days = {}  # Dias com rotina "present"
    per_employee_event_days = {}
    per_employee_vacation_periods = {}  # PerÃƒÆ’Ã‚Â­odos de fÃƒÆ’Ã‚Â©rias por colaborador
    unknown_counts = Counter()

    start_date_str = start_dt.date().strftime("%Y-%m-%d")
    end_date_str = end_dt.date().strftime("%Y-%m-%d")
    
    # Buscar perÃƒÆ’Ã‚Â­odos de fÃƒÆ’Ã‚Â©rias dos colaboradores (vacation_start/vacation_end)
    employees_with_vacation = session.exec(
        select(models.Employee.id, models.Employee.vacation_start, models.Employee.vacation_end, models.Employee.status)
        .where(models.Employee.id.in_(employee_ids))
    ).all()
    
    for emp_id, vac_start, vac_end, emp_status in employees_with_vacation:
        if vac_start and vac_end:
            vac_start_date = vac_start.date() if hasattr(vac_start, 'date') else vac_start
            vac_end_date = vac_end.date() if hasattr(vac_end, 'date') else vac_end
            per_employee_vacation_periods[emp_id] = {
                "start": vac_start_date,
                "end": vac_end_date,
                "status": emp_status
            }
    
    # PrÃƒÆ’Ã‚Â©-processar dias de fÃƒÆ’Ã‚Â©rias para cada colaborador no perÃƒÆ’Ã‚Â­odo de anÃƒÆ’Ã‚Â¡lise
    analysis_start = start_dt.date()
    analysis_end = end_dt.date()
    
    for emp_id, vac_info in per_employee_vacation_periods.items():
        vac_start = vac_info["start"]
        vac_end = vac_info["end"]
        
        # Verificar sobreposiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o com o perÃƒÆ’Ã‚Â­odo de anÃƒÆ’Ã‚Â¡lise
        if vac_end < analysis_start or vac_start > analysis_end:
            continue  # Sem sobreposiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
        
        # Marcar cada dia de fÃƒÆ’Ã‚Â©rias dentro do perÃƒÆ’Ã‚Â­odo de anÃƒÆ’Ã‚Â¡lise
        current = max(vac_start, analysis_start)
        end_mark = min(vac_end, analysis_end)
        
        while current <= end_mark:
            day_key = current.strftime("%Y-%m-%d")
            # Marcar como "leave" (fÃƒÆ’Ã‚Â©rias) - maior prioridade que unjustified
            current_group = per_employee_days.setdefault(emp_id, {}).get(day_key)
            if not current_group or get_absence_priority("leave") > get_absence_priority(current_group):
                per_employee_days[emp_id][day_key] = "leave"
                per_employee_sources.setdefault(emp_id, {})[day_key] = "vacation_period"
            current += timedelta(days=1)
    
    routine_rows = session.exec(
        select(
            models.EmployeeRoutine.id,
            models.EmployeeRoutine.employee_id,
            models.EmployeeRoutine.date,
            models.EmployeeRoutine.routine
        )
        .where(models.EmployeeRoutine.employee_id.in_(employee_ids))
        .where(models.EmployeeRoutine.date >= start_date_str)
        .where(models.EmployeeRoutine.date <= end_date_str)
    ).all()

    for routine_id, emp_id, routine_date, routine_label in routine_rows:
        day_key = str(routine_date)
        per_employee_routine_days.setdefault(emp_id, set()).add(day_key)
        group = normalize_routine_status(routine_label)
        if group == "unknown":
            label = normalize_event_label(routine_label)
            if label:
                unknown_counts[label] += 1
            if LOG_LEVEL == logging.DEBUG:
                per_employee_debug.setdefault(emp_id, {})[day_key] = {
                    "date": day_key,
                    "group": "unknown",
                    "source": "routine",
                    "record_id": routine_id
                }
            continue
        if group == "present":
            # Contar dias presente para cÃƒÆ’Ã‚Â¡lculo de presenÃƒÆ’Ã‚Â§a
            per_employee_present_days.setdefault(emp_id, set()).add(day_key)
            continue
        current = per_employee_days.setdefault(emp_id, {}).get(day_key)
        if not current or get_absence_priority(group) > get_absence_priority(current):
            per_employee_days[emp_id][day_key] = group
            per_employee_sources.setdefault(emp_id, {})[day_key] = "routine"
            per_employee_record_ids.setdefault(emp_id, {})[day_key] = routine_id
            if LOG_LEVEL == logging.DEBUG:
                per_employee_debug.setdefault(emp_id, {})[day_key] = {
                    "date": day_key,
                    "group": group,
                    "source": "routine",
                    "record_id": routine_id
                }

    try:
        rows = session.exec(
            select(
                models.Event.id,
                models.Event.employee_id,
                models.Event.type,
                models.Event.category,
                models.Event.text,
                func.date(models.Event.timestamp)
            )
            .where(models.Event.employee_id.in_(employee_ids))
            .where(models.Event.timestamp >= start_dt)
            .where(models.Event.timestamp <= end_dt)
        ).all()
    except Exception:
        rows = []

    # Tipos de eventos gerados automaticamente pelo sistema de rotinas
    # Estes nÃƒÆ’Ã‚Â£o devem ser contados como fallback porque jÃƒÆ’Ã‚Â¡ tÃƒÆ’Ã‚Âªm EmployeeRoutine correspondente
    ROUTINE_GENERATED_EVENT_TYPES = {"falta", "atestado", "afastamento", "folga", "ferias_hist", "ferias", "presenca", "routine_change"}
    
    for event_id, emp_id, ev_type, ev_category, ev_text, ev_day in rows:
        if not emp_id:
            continue
        day_key = str(ev_day)
        if day_key in per_employee_routine_days.get(emp_id, set()):
            continue
        # Ignorar eventos que sÃƒÆ’Ã‚Â£o gerados automaticamente pelo sistema de rotinas
        # Esses eventos existem para histÃƒÆ’Ã‚Â³rico mas nÃƒÆ’Ã‚Â£o devem ser contados como ausÃƒÆ’Ã‚Âªncia
        ev_type_lower = (ev_type or "").lower().strip()
        if ev_type_lower in ROUTINE_GENERATED_EVENT_TYPES:
            continue
        group = normalize_event_status(ev_type, ev_category, ev_text)
        if group == "unknown":
            label = normalize_event_label(" ".join([ev_type or "", ev_category or "", ev_text or ""]).strip())
            if label:
                unknown_counts[label] += 1
            if LOG_LEVEL == logging.DEBUG:
                per_employee_debug.setdefault(emp_id, {})[day_key] = {
                    "date": day_key,
                    "group": "unknown",
                    "source": "event_fallback",
                    "record_id": event_id
                }
            continue
        if group == "present":
            continue
        current = per_employee_days.setdefault(emp_id, {}).get(day_key)
        if not current or get_absence_priority(group) > get_absence_priority(current):
            per_employee_days[emp_id][day_key] = group
            per_employee_sources.setdefault(emp_id, {})[day_key] = "event_fallback"
            per_employee_event_days.setdefault(emp_id, set()).add(day_key)
            per_employee_record_ids.setdefault(emp_id, {})[day_key] = event_id
            if LOG_LEVEL == logging.DEBUG:
                per_employee_debug.setdefault(emp_id, {})[day_key] = {
                    "date": day_key,
                    "group": group,
                    "source": "event_fallback",
                    "record_id": event_id
                }

    absence_counts = {}
    sources_map = {}
    routine_days_map = {}
    present_days_map = {}  # Dias com status "present"
    debug_days = {}
    day_maps = {}
    for emp_id in employee_ids:
        emp_day_map = per_employee_days.get(emp_id, {})
        counts = {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0}
        for group in emp_day_map.values():
            if group in counts:
                counts[group] += 1
        absence_counts[emp_id] = counts

        routine_days_count = len(per_employee_routine_days.get(emp_id, set()))
        present_days_count = len(per_employee_present_days.get(emp_id, set()))
        event_days_count = len(per_employee_event_days.get(emp_id, set()))
        routine_days_map[emp_id] = routine_days_count
        present_days_map[emp_id] = present_days_count
        if routine_days_count > 0 and event_days_count > 0:
            sources_map[emp_id] = "mixed"
        elif routine_days_count > 0:
            sources_map[emp_id] = "routine"
        elif event_days_count > 0:
            sources_map[emp_id] = "event_fallback"
        else:
            sources_map[emp_id] = "routine"

        if include_day_map:
            entries = []
            for day_key, group in emp_day_map.items():
                entries.append({
                    "date": day_key,
                    "group": group,
                    "source": per_employee_sources.get(emp_id, {}).get(day_key),
                    "record_id": per_employee_record_ids.get(emp_id, {}).get(day_key)
                })
            day_maps[emp_id] = sorted(entries, key=lambda x: x["date"])

        if LOG_LEVEL == logging.DEBUG and per_employee_debug.get(emp_id):
            debug_days[emp_id] = sorted(
                per_employee_debug[emp_id].values(),
                key=lambda x: x["date"]
            )

    unknown_total = sum(unknown_counts.values())
    unknown_examples = [{"label": label, "count": count} for label, count in unknown_counts.most_common(10)]
    if unknown_total and LOG_LEVEL == logging.DEBUG:
        logger.debug("AusÃƒÆ’Ã‚Âªncias nÃƒÆ’Ã‚Â£o classificadas: %s | exemplos: %s", unknown_total, unknown_examples)

    return absence_counts, {
        "unknown": unknown_total,
        "examples": [entry["label"] for entry in unknown_examples],
        "unknown_labels": unknown_examples,
        "sources": sources_map,
        "routine_days": routine_days_map,
        "present_days": present_days_map,  # Dias trabalhados (rotina "present")
        "debug_days": debug_days,
        "day_map": day_maps if include_day_map else {}
    }


def fetch_absence_event_logs(
    session: Session,
    employee_ids: List[int],
    start_dt: datetime,
    end_dt: datetime,
    include_record_ids: bool = False
) -> tuple:
    if not employee_ids:
        return {}, {}, {}, {}
    counts = {}
    day_counts = {}
    record_ids = {}
    duplicate_days = {}
    seen = set()
    rows = session.exec(
        select(
            models.Event.id,
            models.Event.employee_id,
            models.Event.type,
            models.Event.category,
            models.Event.text,
            func.date(models.Event.timestamp)
        )
        .where(models.Event.employee_id.in_(employee_ids))
        .where(models.Event.timestamp >= start_dt)
        .where(models.Event.timestamp <= end_dt)
    ).all()

    for event_id, emp_id, ev_type, ev_category, ev_text, ev_day in rows:
        if not emp_id:
            continue
        group = classify_event_log_group(ev_type, ev_category, ev_text)
        if group not in ["unjustified", "justified", "leave", "offday"]:
            continue
        day_key = str(ev_day)
        text_label = normalize_event_label(ev_text)
        type_label = normalize_event_label(ev_type)
        dedupe_key = (emp_id, day_key, group, text_label or type_label or group)
        if dedupe_key in seen:
            duplicate_days.setdefault(emp_id, {}).setdefault(day_key, {}).setdefault(group, 0)
            duplicate_days[emp_id][day_key][group] += 1
            continue
        seen.add(dedupe_key)
        counts.setdefault(emp_id, {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0, "total": 0})
        counts[emp_id][group] += 1
        counts[emp_id]["total"] += 1
        day_counts.setdefault(emp_id, {})
        day_counts[emp_id].setdefault(day_key, {})
        day_counts[emp_id][day_key][group] = day_counts[emp_id][day_key].get(group, 0) + 1
        if include_record_ids:
            record_ids.setdefault(emp_id, {}).setdefault(day_key, {}).setdefault(group, []).append(event_id)

    return counts, day_counts, record_ids, duplicate_days


def diagnose_absence_sources(session: Session, employee_id: int, start_dt: datetime, end_dt: datetime) -> List[dict]:
    if LOG_LEVEL != logging.DEBUG:
        return []
    _, meta = fetch_absences_agg(session, [employee_id], start_dt, end_dt)
    return meta.get("debug_days", {}).get(employee_id, [])


def format_absence_source_label(source_key: str) -> str:
    label_map = {
        "routine": "Rotina",
        "event_fallback": "Evento (fallback)",
        "mixed": "Rotina + fallback",
        "vacation_period": "Periodo de Ferias"
    }
    return label_map.get(source_key, "Rotina")


def get_absence_summary(
    session: Session,
    employee_id: int,
    start_date: date,
    end_date: date,
    include_day_map: bool = False
) -> dict:
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    absence_counts, meta = fetch_absences_agg(
        session,
        [employee_id],
        start_dt,
        end_dt,
        include_day_map=include_day_map
    )
    log_counts, log_day_counts, log_record_ids, log_duplicates = fetch_absence_event_logs(
        session,
        [employee_id],
        start_dt,
        end_dt,
        include_record_ids=include_day_map and LOG_LEVEL == logging.DEBUG
    )
    counts = absence_counts.get(employee_id, {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0})
    logs = log_counts.get(employee_id, {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0, "total": 0})
    source_key = meta.get("sources", {}).get(employee_id, "routine")
    debug_unknown_labels = meta.get("unknown_labels", []) if LOG_LEVEL == logging.DEBUG else []
    return {
        "days": counts,
        "logs": logs,
        "source_key": source_key,
        "source_label": format_absence_source_label(source_key),
        "routine_days_logged": meta.get("routine_days", {}).get(employee_id, 0),
        "day_map": meta.get("day_map", {}).get(employee_id, []),
        "logs_day_map": log_day_counts.get(employee_id, {}),
        "logs_record_ids": log_record_ids.get(employee_id, {}) if LOG_LEVEL == logging.DEBUG else {},
        "logs_duplicates": log_duplicates.get(employee_id, {}) if LOG_LEVEL == logging.DEBUG else {},
        "debug_days": meta.get("debug_days", {}).get(employee_id, []),
        "debug_unknown_labels": debug_unknown_labels
    }


def get_absence_penalty(period: str, unjustified_days: int) -> float:
    if period == "daily":
        return max(0.75, 1.0 - 0.10 * unjustified_days)
    if period == "weekly":
        return max(0.65, 1.0 - 0.09 * unjustified_days)
    if period == "monthly":
        return max(0.60, 1.0 - 0.08 * unjustified_days)
    return max(0.60, 1.0 - 0.08 * unjustified_days)


def safe_parse_iso_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except Exception:
                continue
        try:
            return datetime.fromisoformat(text).date()
        except Exception:
            return None
    return None


def to_date(value) -> Optional[date]:
    return safe_parse_iso_date(value)

def get_period_range(target_date: date, period: str) -> tuple:
    if period == "weekly":
        week_start = target_date - timedelta(days=target_date.weekday())
        return week_start, week_start + timedelta(days=6)
    if period == "monthly":
        start_date = target_date.replace(day=1)
        last_day = calendar.monthrange(target_date.year, target_date.month)[1]
        end_date = target_date.replace(day=last_day)
        return start_date, end_date
    return target_date, target_date


def fmt_ddmm(value) -> str:
    parsed = to_date(value)
    return parsed.strftime("%d/%m") if parsed else "-"


def fmt_ddmmyyyy(value) -> str:
    parsed = to_date(value)
    return parsed.strftime("%d/%m/%Y") if parsed else "-"

def fmt_hhmm(value) -> str:
    if not value:
        return "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â"
    try:
        if isinstance(value, datetime):
            if value.tzinfo:
                value = value.astimezone(ZoneInfo("America/Sao_Paulo"))
            return value.strftime("%H:%M")
    except Exception:
        return "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â"
    return "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â"

def fmt_datetime_br(value) -> str:
    if not value:
        return "-"
    try:
        if isinstance(value, datetime):
            if value.tzinfo:
                value = value.astimezone(ZoneInfo("America/Sao_Paulo"))
            return value.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return "-"
    return "-"


def format_int_br(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return "0"


@app.get("/operations/performance", response_class=HTMLResponse)
@app.get("/rankings", response_class=HTMLResponse)
async def operations_performance_page(
    request: Request,
    date: Optional[str] = None,
    period: str = "daily",
    shift: str = "Todos",
    route_band: str = "Todos",
    tenure_band: str = "Todos",
    sort_by: str = "score",
    order: str = "desc",
    session: Session = Depends(get_session),
    user = Depends(require_leader)
):
    try:
        return await _operations_performance_impl(request, date, period, shift, route_band, tenure_band, sort_by, order, session)
    except Exception as e:
        if request.query_params.get("debug") == "1":
            import traceback
            tb = traceback.format_exc()
            return HTMLResponse(content=f"<pre style='background:#1e293b;color:#f8fafc;padding:1rem;overflow:auto;'>{tb}</pre>", status_code=500)
        raise


async def _operations_performance_impl(
    request: Request,
    date: Optional[str],
    period: str,
    shift: str,
    route_band: str,
    tenure_band: str,
    sort_by: str,
    order: str,
    session: Session
):
    OCCURRENCE_TYPES = {"erro", "alerta", "ocorrencia", "advertencia"}

    def safe_mean(values: List[float]) -> float:
        return statistics.mean(values) if values else 0.0

    def safe_stdev(values: List[float]) -> float:
        return statistics.pstdev(values) if len(values) > 1 else 0.0

    def normalize_val(value: float, min_val: float, max_val: float) -> float:
        if max_val == min_val:
            return 0.5 if max_val else 0.0
        return (value - min_val) / (max_val - min_val)

    def parse_time_value(value) -> Optional[time]:
        if value is None:
            return None
        if isinstance(value, time):
            return value
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, str):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(value.strip(), fmt).time()
                except Exception:
                    continue
        return None

    def duration_seconds(start_val, end_val) -> float:
        start_time = parse_time_value(start_val)
        end_time = parse_time_value(end_val)
        if not start_time or not end_time:
            return 0.0
        start_dt = datetime.combine(datetime.now().date(), start_time)
        end_dt = datetime.combine(datetime.now().date(), end_time)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        return max(0.0, (end_dt - start_dt).total_seconds())

    def trend_slope(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        x_mean = (len(values) - 1) / 2
        y_mean = safe_mean(values)
        numerator = sum((idx - x_mean) * (val - y_mean) for idx, val in enumerate(values))
        denominator = sum((idx - x_mean) ** 2 for idx in range(len(values)))
        return numerator / denominator if denominator else 0.0

    def pearson_corr(x_vals: List[float], y_vals: List[float]) -> float:
        if len(x_vals) < 2 or len(x_vals) != len(y_vals):
            return 0.0
        x_mean = safe_mean(x_vals)
        y_mean = safe_mean(y_vals)
        x_diff = [x - x_mean for x in x_vals]
        y_diff = [y - y_mean for y in y_vals]
        denom = (sum(d ** 2 for d in x_diff) * sum(d ** 2 for d in y_diff)) ** 0.5
        if denom == 0:
            return 0.0
        return sum(xd * yd for xd, yd in zip(x_diff, y_diff)) / denom

    def assign_band(value: float, low: float, high: float) -> str:
        if value <= low:
            return "Leve"
        if value <= high:
            return "Media"
        return "Pesada"

    def get_tenure_band(months: int) -> str:
        if months < 3:
            return "Novatos"
        if months < 12:
            return "Consolidacao"
        return "Veteranos"

    def compute_tenure_months(employee: models.Employee) -> int:
        admission_date = to_date(getattr(employee, "admission_date", None))
        if not admission_date:
            return 0
        return max(0, int((target_date - admission_date).days / 30))

    def get_weights(band: str) -> dict:
        base = {"kgh": 0.30, "tonnage": 0.25, "regularity": 0.20, "consistency": 0.15, "trend": 0.10}
        if band == "Novatos":
            return {"kgh": 0.28, "tonnage": 0.22, "regularity": 0.18, "consistency": 0.12, "trend": 0.20}
        if band == "Veteranos":
            return {"kgh": 0.28, "tonnage": 0.23, "regularity": 0.24, "consistency": 0.18, "trend": 0.07}
        return base

    def kmeans(points: List[List[float]], k: int = 3, iterations: int = 8):
        if not points:
            return [], []
        k = min(k, len(points))
        ordered_idx = sorted(range(len(points)), key=lambda i: points[i][0])
        centroids = [points[ordered_idx[int(i * (len(points) - 1) / max(k - 1, 1))]] for i in range(k)]
        for _ in range(iterations):
            clusters = [[] for _ in range(k)]
            for idx, point in enumerate(points):
                distances = [sum((p - c) ** 2 for p, c in zip(point, centroid)) for centroid in centroids]
                cluster_idx = distances.index(min(distances))
                clusters[cluster_idx].append(idx)
            new_centroids = []
            for c_idx, members in enumerate(clusters):
                if not members:
                    new_centroids.append(centroids[c_idx])
                    continue
                new_centroids.append([
                    safe_mean([points[m][dim] for m in members]) for dim in range(len(points[0]))
                ])
            if new_centroids == centroids:
                break
            centroids = new_centroids
        return clusters, centroids

    if not date:
        date = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    target_date = safe_parse_iso_date(date)
    if not target_date:
        target_date = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        date = target_date.strftime("%Y-%m-%d")
    start_date, end_date = get_period_range(target_date, period)
    total_days = (end_date - start_date).days + 1
    period_range_start = fmt_ddmmyyyy(start_date)
    period_range_end = fmt_ddmmyyyy(end_date)
    period_range_label = f"{period_range_start} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {period_range_end}"
    month_names = [
        "janeiro", "fevereiro", "marÃƒÆ’Ã‚Â§o", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
    ]
    month_label = f"{month_names[target_date.month - 1].capitalize()}/{target_date.year}"
    if period == "monthly":
        period_context_label = f"MÃƒÆ’Ã‚Âªs: {month_label}"
    elif period == "weekly":
        period_context_label = f"Semana: {period_range_start} a {period_range_end}"
    else:
        period_context_label = f"Dia: {period_range_start}"

    allowed_query = select(models.Employee).where(models.Employee.mobile_access_separation == True)
    if shift and shift not in ["Todos", "Geral", None]:
        allowed_query = allowed_query.where(models.Employee.work_shift == shift)
    allowed_employees = session.exec(allowed_query).all()
    allowed_ids = {emp.id for emp in allowed_employees if emp and emp.id}

    # --- Colaboradores elegÃƒÆ’Ã‚Â­veis (habilitados no app de SeparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o) ---
    employees_query = (
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .where(models.Employee.replaced_by.is_(None))
        .where(models.Employee.mobile_access_separation == True)
    )
    if shift and shift not in ["Todos", "Geral", None]:
        employees_query = employees_query.where(models.Employee.work_shift == shift)
    employees = session.exec(employees_query).all()
    all_employee_ids = [e.id for e in employees]

    query = (
        select(models.Route, models.Employee, models.Client)
        .join(models.Employee, models.Route.employee_id == models.Employee.id)
        .join(models.Client, models.Route.client_id == models.Client.id)
        .where(models.Route.tonnage > 0)
        .where(models.Route.date >= start_date.strftime("%Y-%m-%d"))
        .where(models.Route.date <= end_date.strftime("%Y-%m-%d"))
    )
    if shift and shift not in ["Todos", "Geral", None]:
        query = query.where(models.Route.shift == shift)
    if allowed_ids:
        query = query.where(models.Route.employee_id.in_(allowed_ids))
        routes_rows = session.exec(query).all()
    else:
        routes_rows = []

    routes = []
    for route, emp, client in routes_rows:
        if not emp:
            continue
        if allowed_ids and route.employee_id not in allowed_ids:
            continue
        tonnage = float(route.tonnage or 0)
        if tonnage <= 0:
            continue
        route_day = to_date(route.date)
        route_day_key = route_day.isoformat() if route_day else str(route.date)
        routes.append({
            "employee_id": route.employee_id,
            "employee": emp,
            "client": client,
            "date": route_day_key,
            "tonnage": tonnage,
            "start_time": route.start_time,
            "end_time": route.end_time
        })

    tonnage_values = [r["tonnage"] for r in routes]
    band_low, band_high = (0.0, 0.0)
    if tonnage_values:
        ordered_tonnage = sorted(tonnage_values)
        idx_low = max(0, int(len(ordered_tonnage) * 0.33) - 1)
        idx_high = max(0, int(len(ordered_tonnage) * 0.66) - 1)
        band_low = ordered_tonnage[idx_low]
        band_high = ordered_tonnage[idx_high]

    if route_band and route_band not in ["Todos", "Geral"]:
        routes = [r for r in routes if assign_band(r["tonnage"], band_low, band_high) == route_band]

    # IDs com rotas (podem ser subconjunto de todos os elegÃƒÆ’Ã‚Â­veis)
    employee_ids = sorted({r["employee_id"] for r in routes})
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    today_date = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    # Bulk Event Query (Optimization)
    event_query = (
        select(models.Event.employee_id, func.count())
        .where(models.Event.employee_id.is_not(None))
        .where(models.Event.timestamp >= start_dt)
        .where(models.Event.timestamp <= end_dt)
        .where(models.Event.type.in_(list(OCCURRENCE_TYPES)))
        .group_by(models.Event.employee_id)
    )
    
    # --- Contagem de ausÃƒÆ’Ã‚Âªncias usando fetch_absences_agg (obtÃƒÆ’Ã‚Â©m sources tambÃƒÆ’Ã‚Â©m) ---
    absence_counts = {}
    absences_sources = {}
    absences_debug_days = {}
    absences_present_days = {}  # Dias com rotina "present"
    if all_employee_ids:
        try:
            absence_counts, absence_meta = fetch_absences_agg(
                session,
                all_employee_ids,
                start_dt,
                end_dt,
                include_day_map=(LOG_LEVEL == logging.DEBUG)
            )
            absences_sources = absence_meta.get("sources", {})
            absences_present_days = absence_meta.get("present_days", {})
            if LOG_LEVEL == logging.DEBUG:
                absences_debug_days = absence_meta.get("debug_days", {})
        except Exception as e:
            logger.exception(f"Erro ao buscar ausÃƒÆ’Ã‚Âªncias: {e}")
            absence_counts = {}
            absences_sources = {}
            absences_present_days = {}
            absences_debug_days = {}
    
    # Fallback: se nÃƒÆ’Ã‚Â£o conseguiu buscar, usar mÃƒÆ’Ã‚Â©todo antigo (sÃƒÆ’Ã‚Â³ se absence_counts estiver vazio)
    if not absence_counts and all_employee_ids:
        routines_rows = session.exec(
            select(models.EmployeeRoutine)
            .where(models.EmployeeRoutine.employee_id.in_(all_employee_ids))
            .where(models.EmployeeRoutine.date >= start_date.strftime("%Y-%m-%d"))
            .where(models.EmployeeRoutine.date <= end_date.strftime("%Y-%m-%d"))
        ).all()

        # Usar set para contar apenas dias ÃƒÆ’Ã‚Âºnicos (evita contar 3x por turno)
        absence_days = {}  # {emp_id: {type: set(dates)}}
        for r in routines_rows:
            emp_id = r.employee_id
            r_type = (r.routine or "").lower()
            date_key = str(r.date) if r.date else None
            if not date_key:
                continue
            
            days_map = absence_days.setdefault(emp_id, {
                "unjustified": set(),
                "justified": set(),
                "leave": set(),
                "offday": set()
            })
            
            if r_type in ["absent", "falta"]:
                days_map["unjustified"].add(date_key)
            elif r_type in ["sick", "atestado"]:
                days_map["justified"].add(date_key)
            elif r_type in ["away", "afastado"]:
                days_map["leave"].add(date_key)
            elif r_type in ["dayoff", "folga"]:
                days_map["offday"].add(date_key)
            
            if emp_id not in absences_sources:
                absences_sources[emp_id] = "routine"
        
        # Converter sets para contagens
        for emp_id, days_map in absence_days.items():
            absence_counts[emp_id] = {
                "unjustified": len(days_map["unjustified"]),
                "justified": len(days_map["justified"]),
                "leave": len(days_map["leave"]),
                "offday": len(days_map["offday"])
            }
    
    # Buscar event_counts para ocorrÃƒÆ’Ã‚Âªncias
    event_counts = {}
    if all_employee_ids:
        event_query = (
            select(models.Event.employee_id, func.count())
            .where(models.Event.employee_id.is_not(None))
            .where(models.Event.timestamp >= start_dt)
            .where(models.Event.timestamp <= end_dt)
            .where(models.Event.type.in_(list(OCCURRENCE_TYPES)))
            .where(models.Event.employee_id.in_(all_employee_ids))
            .group_by(models.Event.employee_id)
        )
        try:
            event_rows = session.exec(event_query).all()
            event_counts = {eid: count for eid, count in event_rows if eid}
        except Exception:
            event_counts = {}
    
    debug_absences = None
    debug_absence_diagnostic = None
    debug_absence_employee_id = None
    debug_absence_summary = None
    if LOG_LEVEL == logging.DEBUG:
        debug_employee_id = request.query_params.get("debug_employee_id")
        if debug_employee_id:
            try:
                debug_absence_employee_id = int(debug_employee_id)
                debug_absence_diagnostic = diagnose_absence_sources(
                    session,
                    debug_absence_employee_id,
                    start_dt,
                    end_dt
                )
                absence_summary_debug = get_absence_summary(
                    session,
                    debug_absence_employee_id,
                    start_date,
                    end_date,
                    include_day_map=True
                )
                routine_count_query = (
                    select(func.count(models.EmployeeRoutine.id))
                    .where(models.EmployeeRoutine.employee_id == debug_absence_employee_id)
                    .where(models.EmployeeRoutine.date >= start_date.strftime("%Y-%m-%d"))
                    .where(models.EmployeeRoutine.date <= end_date.strftime("%Y-%m-%d"))
                )
                event_count_query = (
                    select(func.count(models.Event.id))
                    .where(models.Event.employee_id == debug_absence_employee_id)
                    .where(models.Event.timestamp >= start_dt)
                    .where(models.Event.timestamp <= end_dt)
                )
                try:
                    routine_count = session.exec(routine_count_query).one() or 0
                except Exception:
                    routine_count = 0
                try:
                    event_count = session.exec(event_count_query).one() or 0
                except Exception:
                    event_count = 0
                dup_examples = []
                for day_key, groups in absence_summary_debug.get("logs_day_map", {}).items():
                    for group, count in groups.items():
                        if count > 1:
                            dup_examples.append({
                                "date": fmt_ddmmyyyy(day_key),
                                "group": group,
                                "count": count
                            })
                debug_absence_summary = {
                    "routine_count": routine_count,
                    "event_count": event_count,
                    "source_label": absence_summary_debug.get("source_label"),
                    "days": absence_summary_debug.get("days", {}),
                    "logs": absence_summary_debug.get("logs", {}),
                    "dup_examples": dup_examples[:10]
                }
            except Exception:
                debug_absence_diagnostic = []

    stats = {}
    for emp in allowed_employees:
        if not emp or not emp.id:
            continue
        stats[emp.id] = {
            "employee": emp,
            "tonnage": 0.0,
            "secs": 0.0,
            "count": 0,
            "max_tonnage": 0.0,
            "max_kgh": 0.0,
            "complete_routes": 0,
            "days": set(),
            "daily": {},
            "clients": Counter()
        }
    for item in routes:
        eid = item["employee_id"]
        emp = item["employee"]
        client = item["client"]
        stats.setdefault(eid, {
            "employee": emp,
            "tonnage": 0.0,
            "secs": 0.0,
            "count": 0,
            "max_tonnage": 0.0,
            "max_kgh": 0.0,
            "complete_routes": 0,
            "days": set(),
            "daily": {},
            "clients": Counter()
        })
        payload = stats[eid]
        payload["tonnage"] += item["tonnage"]
        payload["count"] += 1
        payload["days"].add(item["date"])
        payload["max_tonnage"] = max(payload["max_tonnage"], item["tonnage"])
        client_name = client.name if client else "N/A"
        payload["clients"][client_name] += 1

        duration = duration_seconds(item["start_time"], item["end_time"])
        if duration:
            payload["secs"] += duration
            kgh = item["tonnage"] / (duration / 3600)
            payload["max_kgh"] = max(payload["max_kgh"], kgh)
            payload["complete_routes"] += 1

        daily_entry = payload["daily"].setdefault(item["date"], {"tonnage": 0.0, "secs": 0.0})
        daily_entry["tonnage"] += item["tonnage"]
        daily_entry["secs"] += duration

    # Incluir colaboradores elegÃƒÆ’Ã‚Â­veis sem rotas (ex.: sÃƒÆ’Ã‚Â³ com faltas/atestados)
    for emp in employees:
        if emp.id not in stats:
            stats[emp.id] = {
                "employee": emp,
                "tonnage": 0.0,
                "secs": 0.0,
                "count": 0,
                "max_tonnage": 0.0,
                "max_kgh": 0.0,
                "days": set(),
                "daily": {},
                "clients": Counter()
            }

    rows_all = []
    for eid, payload in stats.items():
        employee = payload["employee"]
        hours = payload["secs"] / 3600 if payload["secs"] else 0.0
        avg_kgh = payload["tonnage"] / hours if hours else 0.0
        avg_trip_minutes = (payload["secs"] / 60 / payload["count"]) if payload["count"] else 0.0

        daily_kgh = []
        for data in payload["daily"].values():
            if data["secs"] > 0:
                daily_kgh.append(data["tonnage"] / (data["secs"] / 3600))
        daily_kgh_sorted = [val for _, val in sorted(zip(payload["daily"].keys(), daily_kgh))]
        daily_mean = safe_mean(daily_kgh_sorted)
        daily_std = safe_stdev(daily_kgh_sorted)
        cv = (daily_std / daily_mean) if daily_mean else 0.0
        regularity = len(payload["days"]) / total_days if total_days else 0.0
        slope = trend_slope(daily_kgh_sorted)
        trend_ratio = slope / daily_mean if daily_mean else 0.0
        if trend_ratio > 0.05:
            trend_label = "Em alta"
        elif trend_ratio < -0.05:
            trend_label = "Em queda"
        else:
            trend_label = "EstÃƒÆ’Ã‚Â¡vel"

        occurrences = int(event_counts.get(eid, 0))
        penalty_factor = max(0.7, 1 - occurrences * 0.05)

        absence_data = absence_counts.get(eid, {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0})
        justified_days = absence_data["justified"]
        unjustified_days = absence_data["unjustified"]
        leave_days = absence_data["leave"]
        offday_days = absence_data["offday"]
        
        # Usar dias com rotina "present" se disponÃƒÆ’Ã‚Â­vel, senÃƒÆ’Ã‚Â£o usa dias com rotas
        present_days_from_routine = absences_present_days.get(eid, 0)
        days_with_routes = len(payload["days"])
        # Priorizar dias de rotina "present"; fallback para dias com rotas
        days_active = present_days_from_routine if present_days_from_routine > 0 else days_with_routes
        
        adjusted_denominator = max(1, total_days - justified_days - leave_days - offday_days)
        regularity_adjusted = days_active / adjusted_denominator
        absence_penalty_factor = get_absence_penalty(period, unjustified_days)
        discipline_rate = 1 - (unjustified_days / max(1, total_days))

        consistency_score = max(0.0, 1 - cv)
        top_client = payload["clients"].most_common(1)[0][0] if payload["clients"] else "-"
        top_client_count = payload["clients"].most_common(1)[0][1] if payload["clients"] else 0
        top_client_share = (top_client_count / payload["count"]) if payload["count"] else 0.0
        avg_route_tonnage = payload["tonnage"] / payload["count"] if payload["count"] else 0.0

        tenure_months = compute_tenure_months(employee)
        tenure_group = get_tenure_band(tenure_months)
        route_band_value = assign_band(avg_route_tonnage, band_low, band_high) if avg_route_tonnage else "Leve"
        tenure_band_label = TENURE_BAND_LABELS.get(tenure_group, tenure_group)
        route_band_label = ROUTE_BAND_LABELS.get(route_band_value, route_band_value)
        completeness_rate = (payload["complete_routes"] / payload["count"]) if payload["count"] else 0.0
        sample_days = len(payload["days"])
        sample_small = sample_days < 3
        absences_source = absences_sources.get(eid, "routine")
        debug_absence_days = absences_debug_days.get(eid, []) if LOG_LEVEL == logging.DEBUG else []

        row = {
            "id": eid,
            "name": employee.name if employee else "N/A",
            "photo": employee.photo_url if employee else None,
            "shift": employee.work_shift if employee else None,
            "total_tonnage": payload["tonnage"],
            "total_hours": hours,
            "count": payload["count"],
            "avg_kgh": avg_kgh,
            "avg_trip_minutes": avg_trip_minutes,
            "regularity": regularity,
            "regularity_adjusted": min(1.0, regularity_adjusted),
            "daily_std": daily_std,
            "cv": cv,
            "consistency_score": consistency_score,
            "trend_slope": slope,
            "trend_label": trend_label,
            "trend_ratio": trend_ratio,
            "occurrences": occurrences,
            "penalty_factor": penalty_factor,
            "absence_penalty_factor": absence_penalty_factor,
            "justified_absences": justified_days,
            "unjustified_absences": unjustified_days,
            "leave_absences": leave_days,
            "offday_absences": offday_days,
            "presence_rate": min(1.0, regularity_adjusted),
            "discipline_rate": max(0.0, discipline_rate),
            "top_client": top_client,
            "top_client_share": top_client_share,
            "avg_route_tonnage": avg_route_tonnage,
            "route_band": route_band_value,
            "route_band_label": route_band_label,
            "sample_days": sample_days,
            "sample_small": sample_small,
            "completeness_rate": completeness_rate,
            "tenure_months": tenure_months,
            "tenure_band": tenure_group,
            "tenure_band_label": tenure_band_label,
            "absences_source": absences_source
        }
        if LOG_LEVEL == logging.DEBUG:
            row["debug_absence_days"] = debug_absence_days
        rows_all.append(row)

    if not rows_all:
        return templates.TemplateResponse(
            "rankings.html",
            {
                "request": request,
                "rows": [],
                "filters": {
                    "date": date,
                    "period": period,
                    "shift": shift,
                    "route_band": route_band,
                    "tenure_band": tenure_band,
                    "sort_by": sort_by,
                    "order": order
                },
                "period_range_start": period_range_start,
                "period_range_end": period_range_end,
                "period_range_label": period_range_label,
                "period_context_label": period_context_label,
                "period_range_start": period_range_start,
                "period_range_end": period_range_end,
                "period_range_label": period_range_label,
                "period_context_label": period_context_label,
                "band_labels": {"Leve": "-", "Media": "-", "Pesada": "-"},
                "team_stats": {
                    "total_tonnage": 0,
                    "avg_kgh": 0,
                    "avg_trip_minutes": 0,
                    "total_routes": 0,
                    "active_employees": 0,
                    "avg_presence_adjusted": 0,
                    "discipline_rate": 0,
                    "unjustified_total": 0
                },
                "insights": {},
                "top_performers": [],
                "clusters": [],
                "outliers": [],
                "feature_drivers": [],
                "route_band": route_band,
                "absence_totals": {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0},
                "league_rankings": [],
                "debug_absences": debug_absences,
                "debug_absence_diagnostic": debug_absence_diagnostic,
                "debug_absence_employee_id": debug_absence_employee_id,
                "debug_absence_summary": debug_absence_summary
            }
        )

    rows_filtered = [r for r in rows_all if tenure_band in ["Todos", None, "Geral"] or r["tenure_band"] == tenure_band]
    if not rows_filtered:
        return templates.TemplateResponse(
            "rankings.html",
            {
                "request": request,
                "rows": [],
                "filters": {
                    "date": date,
                    "period": period,
                    "shift": shift,
                    "route_band": route_band,
                    "tenure_band": tenure_band,
                    "sort_by": sort_by,
                    "order": order
                },
                "period_range_start": period_range_start,
                "period_range_end": period_range_end,
                "period_range_label": period_range_label,
                "period_context_label": period_context_label,
                "band_labels": {"Leve": "-", "Media": "-", "Pesada": "-"},
                "team_stats": {
                    "total_tonnage": 0,
                    "avg_kgh": 0,
                    "avg_trip_minutes": 0,
                    "total_routes": 0,
                    "active_employees": 0,
                    "avg_presence_adjusted": 0,
                    "discipline_rate": 0,
                    "unjustified_total": 0
                },
                "insights": {},
                "top_performers": [],
                "clusters": [],
                "outliers": [],
                "feature_drivers": [],
                "route_band": route_band,
                "absence_totals": {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0},
                "league_rankings": [],
                "debug_absences": debug_absences,
                "debug_absence_diagnostic": debug_absence_diagnostic,
                "debug_absence_employee_id": debug_absence_employee_id,
                "debug_absence_summary": debug_absence_summary
            }
        )

    def clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    def get_pillar_weights(tenure_band: str) -> dict:
        base = {
            "productivity": 0.35,
            "quality": 0.20,
            "discipline": 0.20,
            "evolution": 0.15,
            "context": 0.10
        }
        if tenure_band == "Novatos":
            return {
                "productivity": 0.30,
                "quality": 0.18,
                "discipline": 0.18,
                "evolution": 0.22,
                "context": 0.12
            }
        if tenure_band == "Veteranos":
            return {
                "productivity": 0.30,
                "quality": 0.24,
                "discipline": 0.24,
                "evolution": 0.12,
                "context": 0.10
            }
        return base

    def compute_context_score(route_norm: float, top_client_share: float) -> float:
        client_variation = clamp01(1 - (top_client_share or 0.0))
        return clamp01(0.7 * route_norm + 0.3 * client_variation)

    def percentile_rank(values: List[float], value: float) -> float:
        if not values:
            return 0.0
        total = len(values)
        less = sum(1 for v in values if v < value)
        equal = sum(1 for v in values if v == value)
        return (less + 0.5 * equal) / total

    def apply_scores(rows_subset: List[dict]) -> None:
        if not rows_subset:
            return
        kgh_values = [r["avg_kgh"] for r in rows_subset]
        tonnage_values = [r["total_tonnage"] for r in rows_subset]
        trip_values = [r["avg_trip_minutes"] for r in rows_subset]
        regularity_values = [r["regularity_adjusted"] for r in rows_subset]
        consistency_values = [r["consistency_score"] for r in rows_subset]
        trend_values = [r["trend_slope"] for r in rows_subset]
        route_values = [r["avg_route_tonnage"] for r in rows_subset]

        min_kgh, max_kgh = min(kgh_values), max(kgh_values)
        min_tonnage, max_tonnage = min(tonnage_values), max(tonnage_values)
        min_trip, max_trip = min(trip_values), max(trip_values)
        min_reg, max_reg = min(regularity_values), max(regularity_values)
        min_cons, max_cons = min(consistency_values), max(consistency_values)
        min_trend, max_trend = min(trend_values), max(trend_values)
        min_route, max_route = min(route_values), max(route_values)

        for row in rows_subset:
            kgh_norm = normalize_val(row["avg_kgh"], min_kgh, max_kgh)
            tonnage_norm = normalize_val(row["total_tonnage"], min_tonnage, max_tonnage)
            trip_norm = 1 - normalize_val(row["avg_trip_minutes"], min_trip, max_trip)
            regularity_norm = normalize_val(row["regularity_adjusted"], min_reg, max_reg)
            consistency_norm = normalize_val(row["consistency_score"], min_cons, max_cons)
            trend_norm = normalize_val(row["trend_slope"], min_trend, max_trend)
            route_norm = normalize_val(row["avg_route_tonnage"], min_route, max_route)

            completeness_rate = row.get("completeness_rate", 1.0)
            if completeness_rate < 0.7:
                prod_weights = {"kgh": 0.35, "tonnage": 0.50, "trip": 0.15}
                row["time_estimated"] = True
            else:
                prod_weights = {"kgh": 0.50, "tonnage": 0.30, "trip": 0.20}
                row["time_estimated"] = False

            raw_productivity = clamp01(
                prod_weights["kgh"] * kgh_norm
                + prod_weights["tonnage"] * tonnage_norm
                + prod_weights["trip"] * trip_norm
            )

            row["productivity_raw"] = raw_productivity
            row["productivity_subweights"] = prod_weights
            row["_quality_score"] = clamp01(0.6 * regularity_norm + 0.4 * consistency_norm)
            row["_discipline_score"] = clamp01(
                row["discipline_rate"] * row["absence_penalty_factor"] * row["penalty_factor"]
            )
            row["_evolution_score"] = clamp01(trend_norm)
            row["_context_score"] = compute_context_score(route_norm, row.get("top_client_share", 0.0))

            row["pillar_sources"] = {
                "productivity": "EstatÃƒÆ’Ã‚Â­stica",
                "quality": "EstatÃƒÆ’Ã‚Â­stica",
                "discipline": "Regras",
                "evolution": "EstatÃƒÆ’Ã‚Â­stica",
                "context": "Regras"
            }
            row["pillar_weights"] = get_pillar_weights(row["tenure_band"])
            row["group_key"] = f"{row.get('route_band', '-')}/{row.get('shift') or '-'}"

        group_map = {}
        for row in rows_subset:
            group_map.setdefault(row["group_key"], []).append(row)

        for group_rows in group_map.values():
            prod_values = [r["productivity_raw"] for r in group_rows]
            for row in group_rows:
                row["productivity_percentile_group"] = percentile_rank(prod_values, row["productivity_raw"])

        for row in rows_subset:
            productivity_score = clamp01(
                0.65 * row.get("productivity_percentile_group", 0.0)
                + 0.35 * row.get("productivity_raw", 0.0)
            )
            quality_score = row.get("_quality_score", 0.0)
            discipline_score = row.get("_discipline_score", 0.0)
            evolution_score = row.get("_evolution_score", 0.0)
            context_score = row.get("_context_score", 0.0)

            weights = row.get("pillar_weights", get_pillar_weights(row["tenure_band"]))
            base_score = (
                weights["productivity"] * productivity_score
                + weights["quality"] * quality_score
                + weights["discipline"] * discipline_score
                + weights["evolution"] * evolution_score
                + weights["context"] * context_score
            )
            row["score"] = round(base_score * 100, 2)
            row["weighted_score"] = row["score"]
            row["pillar_scores"] = {
                "productivity": round(productivity_score * 100, 1),
                "quality": round(quality_score * 100, 1),
                "discipline": round(discipline_score * 100, 1),
                "evolution": round(evolution_score * 100, 1),
                "context": round(context_score * 100, 1)
            }

        for group_rows in group_map.values():
            score_values_group = [r.get("score", 0.0) for r in group_rows]
            for row in group_rows:
                row["score_percentile_group"] = percentile_rank(score_values_group, row.get("score", 0.0))

        score_values = [r["score"] for r in rows_subset]
        score_values_sorted = sorted(score_values, reverse=True)
        for row in rows_subset:
            rank_index = score_values_sorted.index(row["score"])
            if len(score_values_sorted) > 1:
                row["percentile"] = int(100 * (1 - rank_index / (len(score_values_sorted) - 1)))
            else:
                row["percentile"] = 100

    apply_scores(rows_filtered)

    def build_league_rankings(rows_source: List[dict]) -> List[dict]:
        league_cards = []
        for band_name in ["Novatos", "Consolidacao", "Veteranos"]:
            band_rows = [dict(r) for r in rows_source if r["tenure_band"] == band_name]
            apply_scores(band_rows)
            band_rows.sort(key=lambda x: x["score"], reverse=True)
            league_cards.append({
                "band": band_name,
                "band_label": TENURE_BAND_LABELS.get(band_name, band_name),
                "top": band_rows[:3]
            })
        return league_cards

    league_rankings = build_league_rankings(rows_all)

    team_avg_kgh = safe_mean([r["avg_kgh"] for r in rows_filtered])
    team_avg_tonnage = safe_mean([r["total_tonnage"] for r in rows_filtered])
    team_avg_trip_minutes = safe_mean([r["avg_trip_minutes"] for r in rows_filtered])
    team_avg_presence_adjusted = safe_mean([r["regularity_adjusted"] for r in rows_filtered])

    # Disciplina do time: considerar todos os colaboradores elegÃƒÆ’Ã‚Â­veis (nÃƒÆ’Ã‚Â£o sÃƒÆ’Ã‚Â³ quem teve rota)
    def get_absences_for_emp(emp_id: int) -> dict:
        return absence_counts.get(emp_id, {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0})

    eligible_emp_ids = [e.id for e in employees if e and e.id]
    team_unjustified_total = sum(get_absences_for_emp(eid)["unjustified"] for eid in eligible_emp_ids)
    employee_base = max(1, len(eligible_emp_ids))
    discipline_rate = 1 - (team_unjustified_total / max(1, total_days * employee_base))

    kgh_values = [r["avg_kgh"] for r in rows_filtered]
    tonnage_values = [r["total_tonnage"] for r in rows_filtered]
    regularity_values = [r["regularity_adjusted"] for r in rows_filtered]
    consistency_values = [r["consistency_score"] for r in rows_filtered]
    trend_values = [r["trend_slope"] for r in rows_filtered]
    score_values = [r["score"] for r in rows_filtered]

    median_score = sorted(score_values)[len(score_values) // 2] if score_values else 0

    def badge_meta(label: str) -> dict:
        styles = {
            "ReferÃƒÆ’Ã‚Âªncia": "bg-emerald-500/20 text-emerald-200 border-emerald-500/30",
            "Em evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o": "bg-blue-500/20 text-blue-200 border-blue-500/30",
            "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o": "bg-red-500/20 text-red-200 border-red-500/30",
            "Potencial": "bg-amber-500/20 text-amber-200 border-amber-500/30"
        }
        return {"label": label, "class": styles.get(label, styles["Potencial"])}

    def build_badge(row: dict) -> dict:
        sample_small = row.get("sample_small", False)
        if row["score"] >= 85 and row["discipline_rate"] >= 0.95 and row["regularity_adjusted"] >= 0.8 and not sample_small:
            return {
                "label": "ReferÃƒÆ’Ã‚Âªncia",
                "reason": "Alta entrega com disciplina consistente.",
                "rule": "Score>=85, Disciplina>=95%, PresenÃƒÆ’Ã‚Â§a>=80%, dias>=3"
            }
        if row["trend_ratio"] > 0.05:
            return {
                "label": "Em evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o",
                "reason": "TendÃƒÆ’Ã‚Âªncia de melhora no perÃƒÆ’Ã‚Â­odo.",
                "rule": "TendÃƒÆ’Ã‚Âªncia>0,05"
            }
        attention_trigger = row["unjustified_absences"] > 0 or row["avg_kgh"] < team_avg_kgh * 0.85
        if attention_trigger:
            if sample_small and row["unjustified_absences"] == 0:
                return {
                    "label": "Potencial",
                    "reason": "Amostra pequena; evite conclusÃƒÆ’Ã‚Âµes fortes.",
                    "rule": "Amostra<3 dias -> selo rebaixado"
                }
            return {
                "label": "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o",
                "reason": "Queda de eficiÃƒÆ’Ã‚Âªncia ou faltas nÃƒÆ’Ã‚Â£o justificadas.",
                "rule": "Falta(s) nÃƒÆ’Ã‚Â£o justificadas ou kg/h < 85% da mÃƒÆ’Ã‚Â©dia"
            }
        if row["regularity_adjusted"] >= 0.8 and row["score"] <= median_score:
            return {
                "label": "Potencial",
                "reason": "PresenÃƒÆ’Ã‚Â§a alta com performance abaixo do potencial.",
                "rule": "PresenÃƒÆ’Ã‚Â§a>=80% e score abaixo da mediana"
            }
        if sample_small:
            return {
                "label": "Potencial",
                "reason": "Amostra pequena; dados insuficientes.",
                "rule": "Amostra<3 dias"
            }
        return {
            "label": "Potencial",
            "reason": "Margem clara para evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o com ajustes operacionais.",
            "rule": "Sem sinais fortes de destaque"
        }

    def build_reasons(row: dict) -> List[str]:
        reasons = []
        sample_small = row.get("sample_small", False)
        if sample_small:
            reasons.append("Amostra pequena (indÃƒÆ’Ã‚Â­cios, dados insuficientes)")
        if row["avg_kgh"] > team_avg_kgh * 1.1:
            reasons.append("IndÃƒÆ’Ã‚Â­cios de velocidade acima da mÃƒÆ’Ã‚Â©dia" if sample_small else "Velocidade acima da mÃƒÆ’Ã‚Â©dia do time")
        if row.get("delta_expected_context") is not None:
            if row["delta_expected_context"] > team_avg_kgh * 0.05:
                reasons.append("IndÃƒÆ’Ã‚Â­cios acima do esperado para rota/turno" if sample_small else "Acima do esperado para rota/turno")
            elif row["delta_expected_context"] < -team_avg_kgh * 0.05:
                reasons.append("IndÃƒÆ’Ã‚Â­cios abaixo do esperado para rota/turno" if sample_small else "Abaixo do esperado para rota/turno")
        if row["avg_trip_minutes"] > team_avg_trip_minutes * 1.15:
            reasons.append("IndÃƒÆ’Ã‚Â­cios de tempo por viagem acima da mÃƒÆ’Ã‚Â©dia" if sample_small else "Tempo por viagem acima da mÃƒÆ’Ã‚Â©dia")
        if row["regularity_adjusted"] >= 0.8:
            reasons.append("PresenÃƒÆ’Ã‚Â§a consistente no perÃƒÆ’Ã‚Â­odo")
        if row["trend_ratio"] > 0.05:
            reasons.append("IndÃƒÆ’Ã‚Â­cios de melhora" if sample_small else "TendÃƒÆ’Ã‚Âªncia de melhora")
        if row["trend_ratio"] < -0.05:
            reasons.append("IndÃƒÆ’Ã‚Â­cios de queda" if sample_small else "TendÃƒÆ’Ã‚Âªncia de queda")
        if row["unjustified_absences"] > 0:
            reasons.append(f"{row['unjustified_absences']} falta(s) nÃƒÆ’Ã‚Â£o justificadas")
        if row["occurrences"] > 0:
            reasons.append(f"{row['occurrences']} ocorrÃƒÆ’Ã‚Âªncia(s) operacional(is)")
        if row["top_client"] and row["top_client"] != "-":
            reasons.append(f"Cliente recorrente: {row['top_client']}")
        return reasons[:4]

    for row in rows_filtered:
        badge = build_badge(row)
        meta = badge_meta(badge["label"])
        row["badge"] = meta["label"]
        row["badge_class"] = meta["class"]
        row["badge_reason"] = badge["reason"]
        row["badge_rule"] = badge.get("rule", "")
        row["analysis_reasons"] = build_reasons(row)
        row["score_source"] = "EstatÃƒÆ’Ã‚Â­stica"
        row["group_label"] = f"Rota {row.get('route_band_label', row.get('route_band', '-'))} / Turno {row.get('shift') or '-'}"
        row["sample_note"] = "Amostra pequena; dados insuficientes." if row.get("sample_small") else ""

    if len(rows_filtered) > 1:
        x_vals = [r["regularity_adjusted"] for r in rows_filtered]
        y_vals = [r["avg_kgh"] for r in rows_filtered]
        x_mean = safe_mean(x_vals)
        y_mean = safe_mean(y_vals)
        denom = sum((x - x_mean) ** 2 for x in x_vals)
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals)) / denom if denom else 0.0
        intercept = y_mean - slope * x_mean
    else:
        slope = 0.0
        intercept = rows_filtered[0]["avg_kgh"]
    for row in rows_filtered:
        row["expected_kgh"] = max(0.0, intercept + slope * row["regularity_adjusted"])
        row["delta_expected"] = row["avg_kgh"] - row["expected_kgh"]

    expected_map = {}
    for row in rows_filtered:
        key = (row.get("route_band"), row.get("shift"))
        expected_map.setdefault(key, []).append(row["avg_kgh"])
    expected_map = {key: safe_mean(vals) for key, vals in expected_map.items()}
    for row in rows_filtered:
        key = (row.get("route_band"), row.get("shift"))
        expected_context = expected_map.get(key, team_avg_kgh)
        row["expected_kgh_context"] = expected_context
        row["delta_expected_context"] = row["avg_kgh"] - expected_context

    feature_drivers = []
    for label, values in [
        ("Velocidade (kg/h)", kgh_values),
        ("Volume (kg)", tonnage_values),
        ("Regularidade ajustada", regularity_values),
        ("ConsistÃƒÆ’Ã‚Âªncia", consistency_values),
        ("TendÃƒÆ’Ã‚Âªncia", trend_values)
    ]:
        corr = pearson_corr(values, score_values)
        feature_drivers.append({"label": label, "corr": corr})
    feature_drivers.sort(key=lambda x: abs(x["corr"]), reverse=True)

    outliers = []
    if len(rows_filtered) >= 8:
        kgh_mean = team_avg_kgh
        kgh_std = safe_stdev(kgh_values)
        if kgh_std:
            for row in rows_filtered:
                z = (row["avg_kgh"] - kgh_mean) / kgh_std
                if abs(z) >= 2:
                    outliers.append({"name": row["name"], "kgh": row["avg_kgh"], "zscore": z})

    clusters = []
    if len(rows_filtered) >= 12:
        min_kgh, max_kgh = min(kgh_values), max(kgh_values)
        min_cons, max_cons = min(consistency_values), max(consistency_values)
        min_reg, max_reg = min(regularity_values), max(regularity_values)
        cluster_points = [
            [
                normalize_val(r["avg_kgh"], min_kgh, max_kgh),
                normalize_val(r["consistency_score"], min_cons, max_cons),
                normalize_val(r["regularity_adjusted"], min_reg, max_reg)
            ]
            for r in rows_filtered
        ]
        raw_clusters, centroids = kmeans(cluster_points, k=3)
        for idx, members in enumerate(raw_clusters):
            if not members:
                continue
            centroid = centroids[idx]
            label = "Ritmo moderado"
            if centroid[0] > 0.65 and centroid[1] > 0.6:
                label = "Rapido e constante"
            elif centroid[0] > 0.65 and centroid[1] <= 0.6:
                label = "Rapido e instavel"
            elif centroid[0] <= 0.45 and centroid[1] > 0.6:
                label = "Constante e gradual"
            clusters.append({
                "label": label,
                "members": [rows_filtered[m]["name"] for m in members][:6],
                "count": len(members),
                "avg_kgh": safe_mean([rows_filtered[m]["avg_kgh"] for m in members]),
                "avg_regularity": safe_mean([rows_filtered[m]["regularity_adjusted"] for m in members]),
                "avg_consistency": safe_mean([rows_filtered[m]["consistency_score"] for m in members])
            })
    else:
        rule_clusters = {
            "Rapido e constante": [],
            "Rapido e instavel": [],
            "Lento e constante": [],
            "Ritmo moderado": []
        }
        for row in rows_filtered:
            if row["avg_kgh"] >= team_avg_kgh * 1.1 and row["cv"] <= 0.25:
                rule_clusters["Rapido e constante"].append(row)
            elif row["avg_kgh"] >= team_avg_kgh * 1.1 and row["cv"] > 0.25:
                rule_clusters["Rapido e instavel"].append(row)
            elif row["avg_kgh"] <= team_avg_kgh * 0.9 and row["cv"] <= 0.25:
                rule_clusters["Lento e constante"].append(row)
            else:
                rule_clusters["Ritmo moderado"].append(row)
        for label, members in rule_clusters.items():
            if not members:
                continue
            clusters.append({
                "label": label,
                "members": [m["name"] for m in members][:6],
                "count": len(members),
                "avg_kgh": safe_mean([m["avg_kgh"] for m in members]),
                "avg_regularity": safe_mean([m["regularity_adjusted"] for m in members]),
                "avg_consistency": safe_mean([m["consistency_score"] for m in members])
            })

    sort_reverse = order != "asc"
    sort_map = {
        "score": "score",
        "kgh": "avg_kgh",
        "tonnage": "total_tonnage",
        "consistency": "consistency_score",
        "trend": "trend_slope"
    }
    sort_key = sort_map.get(sort_by, "score")
    rows_filtered.sort(key=lambda x: x[sort_key], reverse=sort_reverse)

    top_performers = []
    for row in rows_filtered[:5]:
        top_performers.append({
            "name": row["name"],
            "score": row["score"],
            "percentile": row["percentile"],
            "reasons": row.get("analysis_reasons", [])[:3],
            "id": row["id"],
            "badge": row.get("badge")
        })

    insights = {}
    best = rows_filtered[0] if rows_filtered else None
    if best:
        score_label = f"{best['score']:.2f}".replace(".", ",")
        percentile_label = format_int_br(best["percentile"])
        insights["best"] = {"name": best["name"], "detail": f"Score {score_label} | {percentile_label}%"}
    most_improved = max(rows_filtered, key=lambda x: x["trend_slope"], default=None)
    if most_improved:
        insights["improved"] = {"name": most_improved["name"], "detail": most_improved["trend_label"]}
    most_consistent = min(rows_filtered, key=lambda x: x["cv"], default=None)
    if most_consistent:
        cv_label = f"{most_consistent['cv']:.2f}".replace(".", ",")
        insights["consistent"] = {"name": most_consistent["name"], "detail": f"CV {cv_label}"}
    bottleneck = max(rows_filtered, key=lambda x: x["avg_trip_minutes"], default=None)
    if bottleneck:
        bottleneck_label = f"{bottleneck['avg_trip_minutes']:.1f}".replace(".", ",")
        insights["bottleneck"] = {"name": bottleneck["name"], "detail": f"{bottleneck_label} min/viagem"}
    best_presence = max(rows_filtered, key=lambda x: x["regularity_adjusted"], default=None)
    if best_presence:
        insights["presence"] = {"name": best_presence["name"], "detail": f"{best_presence['regularity_adjusted']:.0%} presenÃƒÆ’Ã‚Â§a"}
    most_absences = max(rows_filtered, key=lambda x: x["unjustified_absences"], default=None)
    if most_absences and most_absences["unjustified_absences"] > 0:
        insights["absences"] = {"name": most_absences["name"], "detail": f"{most_absences['unjustified_absences']} faltas"}
    learning_candidates = [r for r in rows_filtered if r["tenure_band"] == "Novatos"]
    if learning_candidates:
        best_learning = max(learning_candidates, key=lambda x: x["trend_slope"], default=None)
        if best_learning:
            insights["learning"] = {"name": best_learning["name"], "detail": "Curva positiva"}
    veteran_candidates = [r for r in rows_filtered if r["tenure_band"] == "Veteranos"]
    if veteran_candidates:
        veteran_ref = max(veteran_candidates, key=lambda x: (x["score"], -x["cv"]), default=None)
        if veteran_ref:
            insights["veteran"] = {"name": veteran_ref["name"], "detail": "ReferÃƒÆ’Ã‚Âªncia de consistÃƒÆ’Ã‚Âªncia"}
    potential = None
    if rows_filtered:
        median_score = sorted(score_values)[len(score_values) // 2]
        candidates = [r for r in rows_filtered if r["regularity_adjusted"] >= 0.8 and r["score"] <= median_score]
        if candidates:
            potential = max(candidates, key=lambda x: x["regularity_adjusted"])
    if potential:
        insights["potential"] = {"name": potential["name"], "detail": "Alta presenÃƒÆ’Ã‚Â§a, ganho possÃƒÆ’Ã‚Â­vel"}

    band_labels = {
        "Leve": f"<= {format_int_br(band_low)} kg" if band_low else "-",
        "Media": f"{format_int_br(band_low)} - {format_int_br(band_high)} kg" if band_high else "-",
        "Pesada": f">= {format_int_br(band_high)} kg" if band_high else "-"
    }

    # Totais de ausÃƒÆ’Ã‚Âªncias do time (dias ÃƒÆ’Ã‚Âºnicos) usando o mesmo agrupamento de ausÃƒÆ’Ã‚Âªncias
    absence_totals = {
        "justified": sum(get_absences_for_emp(eid)["justified"] for eid in eligible_emp_ids),
        "unjustified": team_unjustified_total,
        "leave": sum(get_absences_for_emp(eid)["leave"] for eid in eligible_emp_ids),
        "offday": sum(get_absences_for_emp(eid)["offday"] for eid in eligible_emp_ids),
    }

    # ============================================
    # DEBUG CÃƒÆ’Ã‚ÂLCULOS - DocumentaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de todas as fÃƒÆ’Ã‚Â³rmulas
    # ============================================
    calculation_debug = None
    try:
        calculation_debug = {
            "period_info": {
                "total_days": total_days,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "period_type": period
            },
            "formulas": {
                "presence_adjusted": {
                    "name": "PresenÃƒÆ’Ã‚Â§a Ajustada",
                    "formula": "dias_trabalhados / (total_dias - atestados - afastamentos - folgas)",
                    "description": "Percentual de presenÃƒÆ’Ã‚Â§a considerando apenas os dias que o colaborador deveria trabalhar",
                    "example": "Se trabalhou 15 dias em perÃƒÆ’Ã‚Â­odo de 30 dias, com 5 folgas e 2 atestados: 15 / (30-2-0-5) = 65%"
                },
                "discipline_rate": {
                    "name": "Taxa de Disciplina",
                    "formula": "1 - (faltas_nao_justificadas / total_dias)",
                    "description": "Percentual de dias sem falta nÃƒÆ’Ã‚Â£o justificada no perÃƒÆ’Ã‚Â­odo",
                    "example": "Se teve 2 faltas em 30 dias: 1 - (2/30) = 93%"
                },
                "consistency_score": {
                    "name": "ConsistÃƒÆ’Ã‚Âªncia",
                    "formula": "1 - CV (Coeficiente de VariaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o)",
                    "description": "Quanto menor a variaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o do Kg/h diÃƒÆ’Ã‚Â¡rio, maior a consistÃƒÆ’Ã‚Âªncia",
                    "example": "Se CV = 0.25, consistÃƒÆ’Ã‚Âªncia = 75%"
                },
                "avg_kgh": {
                    "name": "MÃƒÆ’Ã‚Â©dia Kg/h",
                    "formula": "total_tonelagem / total_horas",
                    "description": "Quilos movimentados por hora trabalhada"
                },
                "score": {
                    "name": "Score Geral",
                    "formula": "PÃƒÆ’Ã¢â‚¬â€35% + QÃƒÆ’Ã¢â‚¬â€20% + DÃƒÆ’Ã¢â‚¬â€20% + EÃƒÆ’Ã¢â‚¬â€10% + CÃƒÆ’Ã¢â‚¬â€15%",
                    "description": "Nota ponderada dos 5 pilares",
                    "weights": {"P": 35, "Q": 20, "D": 20, "E": 10, "C": 15}
                }
            },
            "team_calculations": {
                "total_days": total_days,
                "total_employees": len(rows_filtered) if rows_filtered else 0,
                "avg_presence_adjusted": team_avg_presence_adjusted if team_avg_presence_adjusted is not None else 0,
                "avg_presence_calculation": f"mÃƒÆ’Ã‚Â©dia de {len(rows_filtered)} colaboradores",
                "total_unjustified": team_unjustified_total or 0,
                "discipline_rate": discipline_rate if discipline_rate is not None else 0,
                "discipline_calculation": f"1 - ({team_unjustified_total or 0} / max(1, {total_days}))",
                "sum_regularity_adjusted": sum(r.get("regularity_adjusted", 0) for r in rows_filtered) if rows_filtered else 0
            },
            "employees": []
        }
        # Adicionar dados de cada colaborador
        for row in rows_filtered:
            calculation_debug["employees"].append({
                "id": row["id"],
                "name": row["name"],
                "calculations": {
                    "presence": {
                        "days_active": row.get("sample_days", 0),
                        "total_days": total_days,
                        "justified_days": row.get("justified_absences", 0),
                        "leave_days": row.get("leave_absences", 0),
                        "offday_days": row.get("offday_absences", 0),
                        "unjustified_days": row.get("unjustified_absences", 0),
                        "regularity_adjusted": row.get("regularity_adjusted", 0),
                        "formula_applied": f"{row.get('sample_days', 0)} / (dias - ausencias) = {row.get('regularity_adjusted', 0):.2%}"
                    },
                    "discipline": {
                        "unjustified_days": row.get("unjustified_absences", 0),
                        "discipline_rate": row.get("discipline_rate", 0),
                        "formula_applied": f"1 - ({row.get('unjustified_absences', 0)}/{total_days}) = {row.get('discipline_rate', 0):.2%}"
                    },
                    "productivity": {
                        "total_tonnage": row.get("total_tonnage", 0),
                        "total_hours": row.get("total_hours", 0),
                        "avg_kgh": row.get("avg_kgh", 0),
                        "formula_applied": f"{row.get('total_tonnage', 0):.0f}kg / {row.get('total_hours', 0):.1f}h = {row.get('avg_kgh', 0):.0f} kg/h"
                    },
                    "consistency": {
                        "cv": row.get("cv", 0),
                        "daily_std": row.get("daily_std", 0),
                        "consistency_score": row.get("consistency_score", 0),
                        "formula_applied": f"1 - {row.get('cv', 0):.2f} = {row.get('consistency_score', 0):.2%}"
                    },
                    "score": {
                        "final_score": row.get("score", 0),
                        "pillar_scores": row.get("pillar_scores", {}),
                        "badge": row.get("badge", ""),
                        "badge_reason": row.get("badge_reason", "")
                    }
                }
            })
    except Exception as e:
        print(f"[DEBUG] Erro ao criar calculation_debug: {e}")
        calculation_debug = None

    return templates.TemplateResponse(
        "rankings.html",
        {
            "request": request,
            "rows": rows_filtered,
            "filters": {
                "date": date,
                "period": period,
                "shift": shift,
                "route_band": route_band,
                "tenure_band": tenure_band,
                "sort_by": sort_by,
                "order": order
            },
            "period_range_start": period_range_start,
            "period_range_end": period_range_end,
            "period_range_label": period_range_label,
            "period_context_label": period_context_label,
            "band_labels": band_labels,
            "team_stats": {
                "total_tonnage": sum(tonnage_values),
                "avg_kgh": team_avg_kgh,
                "avg_trip_minutes": team_avg_trip_minutes,
                "total_routes": sum(r["count"] for r in rows_filtered),
                "active_employees": len(rows_filtered),
                "avg_presence_adjusted": team_avg_presence_adjusted,
                "discipline_rate": max(0.0, discipline_rate),
                "unjustified_total": team_unjustified_total
            },
            "insights": insights,
            "top_performers": top_performers,
            "clusters": clusters,
            "outliers": outliers,
            "feature_drivers": feature_drivers[:4],
            "route_band": route_band,
            "absence_totals": absence_totals,
            "league_rankings": league_rankings,
            "debug_absences": debug_absences,
            "debug_absence_diagnostic": debug_absence_diagnostic,
            "debug_absence_employee_id": debug_absence_employee_id,
            "debug_absence_summary": debug_absence_summary,
            "calculation_debug": calculation_debug
        }
    )
@app.get("/api/rankings/employee/{employee_id}/details")
async def get_ranking_details(
    request: Request,
    employee_id: int,
    date: str,
    period: str = "daily",
    shift: Optional[str] = None,
    route_band: str = "Todos",
    tenure_band: str = "Todos",
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    try:
        target_date = safe_parse_iso_date(date)
        if not target_date:
            target_date = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        start_date_obj, end_date_obj = get_period_range(target_date, period)

        start_date_str = start_date_obj.strftime("%Y-%m-%d")
        end_date_str = end_date_obj.strftime("%Y-%m-%d")
        total_days = (end_date_obj - start_date_obj).days + 1
        debug_absence = LOG_LEVEL == logging.DEBUG
            
        employee = session.exec(select(models.Employee).where(models.Employee.id == employee_id)).first()
        employee_shift = employee.work_shift if employee else "-"
        tenure_months = 0
        tenure_band_value = "Novatos"
        admission_date = to_date(getattr(employee, "admission_date", None))
        if admission_date:
            tenure_months = max(0, int((target_date - admission_date).days / 30))
            if tenure_months < 3:
                tenure_band_value = "Novatos"
            elif tenure_months < 12:
                tenure_band_value = "Consolidacao"
            else:
                tenure_band_value = "Veteranos"

        tenure_filter_mismatch = (
            tenure_band not in ["Todos", "Geral", None, "null"] and tenure_band != tenure_band_value
        )

        OCCURRENCE_TYPES = {"erro", "alerta", "ocorrencia", "advertencia"}

        def safe_mean(values: List[float]) -> float:
            return statistics.mean(values) if values else 0.0

        def safe_stdev(values: List[float]) -> float:
            return statistics.pstdev(values) if len(values) > 1 else 0.0

        def clamp01(value: float) -> float:
            return max(0.0, min(1.0, value))

        def percentile_rank(values: List[float], value: float) -> float:
            if not values:
                return 0.0
            total = len(values)
            less = sum(1 for v in values if v < value)
            equal = sum(1 for v in values if v == value)
            return (less + 0.5 * equal) / total

        def normalize_val(value: float, min_val: float, max_val: float) -> float:
            if max_val == min_val:
                return 0.5 if max_val else 0.0
            return (value - min_val) / (max_val - min_val)

        def parse_time_value(value) -> Optional[time]:
            if value is None:
                return None
            if isinstance(value, time):
                return value
            if isinstance(value, datetime):
                return value.time()
            if isinstance(value, str):
                for fmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        return datetime.strptime(value.strip(), fmt).time()
                    except Exception:
                        continue
            return None

        def duration_seconds(start_val, end_val) -> float:
            start_time = parse_time_value(start_val)
            end_time = parse_time_value(end_val)
            if not start_time or not end_time:
                return 0.0
            start_dt = datetime.combine(datetime.now().date(), start_time)
            end_dt = datetime.combine(datetime.now().date(), end_time)
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
            return max(0.0, (end_dt - start_dt).total_seconds())

        def trend_slope(values: List[float]) -> float:
            if len(values) < 2:
                return 0.0
            x_mean = (len(values) - 1) / 2
            y_mean = safe_mean(values)
            numerator = sum((idx - x_mean) * (val - y_mean) for idx, val in enumerate(values))
            denominator = sum((idx - x_mean) ** 2 for idx in range(len(values)))
            return numerator / denominator if denominator else 0.0

        def assign_band(value: float, low: float, high: float) -> str:
            if value <= low:
                return "Leve"
            if value <= high:
                return "Media"
            return "Pesada"

        band_low, band_high = (0.0, 0.0)
        tonnage_values = []
        if route_band and route_band not in ["Todos", "Geral", None, "null"]:
            tonnage_query = (
                select(models.Route.tonnage)
                .where(models.Route.tonnage > 0)
                .where(models.Route.date >= start_date_str)
                .where(models.Route.date <= end_date_str)
            )
            if shift and shift not in ['Geral', 'Todos', None, 'null']:
                tonnage_query = tonnage_query.where(models.Route.shift == shift)
            tonnage_rows = session.exec(tonnage_query).all()
            tonnage_values = []
            for val in tonnage_rows:
                if isinstance(val, (list, tuple)):
                    val = val[0] if val else None
                if val:
                    tonnage_values.append(float(val))
            if tonnage_values:
                ordered_tonnage = sorted(tonnage_values)
                idx_low = max(0, int(len(ordered_tonnage) * 0.33) - 1)
                idx_high = max(0, int(len(ordered_tonnage) * 0.66) - 1)
                band_low = ordered_tonnage[idx_low]
                band_high = ordered_tonnage[idx_high]

        results = []
        if not tenure_filter_mismatch:
            query = select(models.Route, models.Client).join(models.Client, models.Route.client_id == models.Client.id)
            query = query.where(models.Route.employee_id == employee_id)
            query = query.where(models.Route.tonnage > 0)
            query = query.where(models.Route.date >= start_date_str)
            query = query.where(models.Route.date <= end_date_str)

            if shift and shift not in ['Geral', 'Todos', None, 'null']:
                query = query.where(models.Route.shift == shift)

            results = session.exec(query).all() # List of (Route, Client)
            if route_band and route_band not in ["Todos", "Geral", None, "null"]:
                if tonnage_values:
                    results = [
                        (r, c) for r, c in results
                        if assign_band(float(r.tonnage or 0), band_low, band_high) == route_band
                    ]
                else:
                    results = []

        routes_data = []
        total_tonnage = 0
        total_secs = 0
        max_kgh = 0
        complete_routes = 0
        active_days = set()
        daily = {}
        daily_route_counts = {}
        client_counts = Counter()
        
        for r, c in results:
            tonnage = r.tonnage or 0
            duration_fmt = "-"
            kgh = 0
            diff = 0
            
            # Duration logic
            try:
                diff = duration_seconds(r.start_time, r.end_time)
                if diff > 0:
                    total_secs += diff
                    duration_fmt = f"{int(diff//3600):02d}:{int((diff%3600)//60):02d}"
                    kgh = tonnage / (diff/3600)
                    if kgh > max_kgh:
                        max_kgh = kgh
                    complete_routes += 1
            except Exception:
                pass
            
            total_tonnage += tonnage
            route_day = to_date(r.date)
            route_day_key = route_day.isoformat() if route_day else str(r.date)
            active_days.add(route_day_key)
            daily_route_counts[route_day_key] = daily_route_counts.get(route_day_key, 0) + 1
            route_date_str = fmt_ddmm(r.date)
            client_name = c.name if c else "N/A"
            client_counts[client_name] += 1

            if diff > 0:
                day_entry = daily.setdefault(route_day_key, {"tonnage": 0.0, "secs": 0.0})
                day_entry["tonnage"] += tonnage
                day_entry["secs"] += diff

            routes_data.append({
                "client": client_name,
                "tonnage": int(tonnage),
                "start": r.start_time,
                "end": r.end_time or "-",
                "duration": duration_fmt,
                "kgh": int(kgh),
                "date": route_date_str
            })

        daily_kgh = []
        for data in daily.values():
            if data["secs"] > 0:
                daily_kgh.append(data["tonnage"] / (data["secs"] / 3600))
        daily_kgh_sorted = [val for _, val in sorted(zip(daily.keys(), daily_kgh))] if daily_kgh else []
        timeline_kgh = []
        for day_key, data in sorted(daily.items()):
            if data["secs"] > 0:
                kgh_val = data["tonnage"] / (data["secs"] / 3600)
                timeline_kgh.append({"date": fmt_ddmm(day_key), "kgh": round(kgh_val, 1)})
            else:
                timeline_kgh.append({"date": fmt_ddmm(day_key), "kgh": None})
        daily_mean = safe_mean(daily_kgh_sorted)
        daily_std = safe_stdev(daily_kgh_sorted)
        cv = (daily_std / daily_mean) if daily_mean else 0.0
        slope = trend_slope(daily_kgh_sorted)
        trend_ratio = slope / daily_mean if daily_mean else 0.0
        if trend_ratio > 0.05:
            trend_label = "Em alta"
        elif trend_ratio < -0.05:
            trend_label = "Em queda"
        else:
            trend_label = "EstÃƒÆ’Ã‚Â¡vel"

        top_client = client_counts.most_common(1)[0][0] if client_counts else "-"
        top_client_count = client_counts.most_common(1)[0][1] if client_counts else 0
        top_client_share = (top_client_count / len(routes_data)) if routes_data else 0.0
        avg_route_tonnage = total_tonnage / len(routes_data) if routes_data else 0.0
        avg_trip_minutes = (total_secs / 60 / len(routes_data)) if routes_data else 0.0
        route_band_value = assign_band(avg_route_tonnage, band_low, band_high) if avg_route_tonnage else "Leve"
        routes_count = len(routes_data)
        completeness_rate = (complete_routes / routes_count) if routes_count else 0.0
        route_days_active = len(active_days)
        sample_days = route_days_active
        sample_small = sample_days < 3
            
        # Summary
        avg_kgh = 0
        hours = total_secs / 3600
        if hours > 0:
            avg_kgh = total_tonnage / hours
            
        # --- Contagem de ausÃƒÆ’Ã‚Âªncias usando get_absence_summary (fonte ÃƒÆ’Ã‚Âºnica e consistente) ---
        # Esta funÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o usa fetch_absences_agg internamente e garante consistÃƒÆ’Ã‚Âªncia
        absence_summary = get_absence_summary(
            session,
            employee_id,
            start_date_obj,
            end_date_obj,
            include_day_map=True
        )
        
        # Extrair contagens do resumo
        absence_days = absence_summary.get("days", {})
        justified_days = absence_days.get("justified", 0)
        unjustified_days = absence_days.get("unjustified", 0)
        leave_days = absence_days.get("leave", 0)
        offday_days = absence_days.get("offday", 0)
        
        # Extrair logs de ausÃƒÆ’Ã‚Âªncia
        absence_logs = absence_summary.get("logs", {})
        absence_events = {
            "justified": absence_logs.get("justified", 0),
            "unjustified": absence_logs.get("unjustified", 0),
            "leave": absence_logs.get("leave", 0),
            "offday": absence_logs.get("offday", 0),
            "total": absence_logs.get("total", 0)
        }
        
        # Obter day_map e logs_day_map para timeline
        absence_event_day_map = absence_summary.get("logs_day_map", {})
        absence_event_record_map = absence_summary.get("logs_record_ids", {})
        
        # Buscar rotinas para timeline (fallback se day_map nÃƒÆ’Ã‚Â£o estiver disponÃƒÆ’Ã‚Â­vel)
        routines_rows = session.exec(
            select(models.EmployeeRoutine.date, models.EmployeeRoutine.routine)
            .where(models.EmployeeRoutine.employee_id == employee_id)
            .where(models.EmployeeRoutine.date >= start_date_str)
            .where(models.EmployeeRoutine.date <= end_date_str)
        ).all()
        adjusted_denominator = max(1, total_days - justified_days - leave_days - offday_days)
        regularity_adjusted = len(active_days) / adjusted_denominator
        absence_penalty_factor = get_absence_penalty(period, unjustified_days)
        discipline_rate = 1 - (unjustified_days / max(1, total_days))

        # Converter datas para datetime para filtro de eventos
        start_datetime = datetime.combine(start_date_obj, datetime.min.time())
        end_datetime = datetime.combine(end_date_obj, datetime.max.time())
        
        event_query = (
            select(func.count(models.Event.id))
            .where(models.Event.employee_id == employee_id)
            .where(models.Event.timestamp >= start_datetime)
            .where(models.Event.timestamp <= end_datetime)
            .where(models.Event.type.in_(list(OCCURRENCE_TYPES)))
        )
        try:
            occurrences = session.exec(event_query).one() or 0
        except Exception:
            occurrences = 0
        penalty_factor = max(0.7, 1 - occurrences * 0.05)

        team_query = (
            select(models.Route)
            .where(models.Route.tonnage > 0)
            .where(models.Route.date >= start_date_str)
            .where(models.Route.date <= end_date_str)
        )
        if shift and shift not in ["Geral", "Todos", None, "null"]:
            team_query = team_query.where(models.Route.shift == shift)
        team_rows = session.exec(team_query).all()

        group_tonnage_values = [float(r.tonnage or 0) for r in team_rows if r.tonnage]
        band_low_group, band_high_group = (0.0, 0.0)
        if group_tonnage_values:
            ordered_tonnage = sorted(group_tonnage_values)
            idx_low = max(0, int(len(ordered_tonnage) * 0.33) - 1)
            idx_high = max(0, int(len(ordered_tonnage) * 0.66) - 1)
            band_low_group = ordered_tonnage[idx_low]
            band_high_group = ordered_tonnage[idx_high]
            route_band_value = assign_band(avg_route_tonnage, band_low_group, band_high_group) if avg_route_tonnage else "Leve"

        group_stats = {}
        for route in team_rows:
            if not route.employee_id:
                continue
            tonnage_val = float(route.tonnage or 0)
            if tonnage_val <= 0:
                continue
            if group_tonnage_values:
                if assign_band(tonnage_val, band_low_group, band_high_group) != route_band_value:
                    continue
            if employee_shift not in ["-", None] and route.shift != employee_shift:
                continue
            entry = group_stats.setdefault(route.employee_id, {
                "tonnage": 0.0,
                "secs": 0.0,
                "count": 0,
                "complete_routes": 0,
                "days": set(),
                "daily": {},
                "clients": Counter()
            })
            entry["tonnage"] += tonnage_val
            entry["count"] += 1
            entry["days"].add(str(route.date))
            entry["clients"][str(route.client_id or "N/A")] += 1
            diff = duration_seconds(route.start_time, route.end_time)
            if diff > 0:
                entry["secs"] += diff
                entry["complete_routes"] += 1
            day_entry = entry["daily"].setdefault(str(route.date), {"tonnage": 0.0, "secs": 0.0})
            day_entry["tonnage"] += tonnage_val
            day_entry["secs"] += diff

        if not group_stats and routes_count:
            group_stats[employee_id] = {
                "tonnage": total_tonnage,
                "secs": total_secs,
                "count": routes_count,
                "complete_routes": complete_routes,
                "days": set(active_days),
                "daily": dict(daily),
                "clients": Counter(client_counts)
            }

        group_employee_ids = list(group_stats.keys())
        group_absence_counts, _group_absence_unknown = fetch_absences_agg(
            session,
            group_employee_ids,
            start_datetime,
            end_datetime
        ) if group_employee_ids else ({}, {})

        group_event_counts = {}
        if group_employee_ids:
            group_event_query = (
                select(models.Event.employee_id, func.count())
                .where(models.Event.employee_id.is_not(None))
                .where(models.Event.timestamp >= start_datetime)
                .where(models.Event.timestamp <= end_datetime)
                .where(models.Event.type.in_(list(OCCURRENCE_TYPES)))
                .where(models.Event.employee_id.in_(group_employee_ids))
                .group_by(models.Event.employee_id)
            )
            try:
                group_event_rows = session.exec(group_event_query).all()
                group_event_counts = {eid: count for eid, count in group_event_rows if eid}
            except Exception:
                group_event_counts = {}

        group_employees = session.exec(
            select(models.Employee).where(models.Employee.id.in_(group_employee_ids))
        ).all() if group_employee_ids else []
        group_emp_map = {emp.id: emp for emp in group_employees}

        def get_pillar_weights(tenure_band: str) -> dict:
            base = {
                "productivity": 0.35,
                "quality": 0.20,
                "discipline": 0.20,
                "evolution": 0.15,
                "context": 0.10
            }
            if tenure_band == "Novatos":
                return {
                    "productivity": 0.30,
                    "quality": 0.18,
                    "discipline": 0.18,
                    "evolution": 0.22,
                    "context": 0.12
                }
            if tenure_band == "Veteranos":
                return {
                    "productivity": 0.30,
                    "quality": 0.24,
                    "discipline": 0.24,
                    "evolution": 0.12,
                    "context": 0.10
                }
            return base

        def compute_context_score(route_norm: float, top_client_share: float) -> float:
            client_variation = clamp01(1 - (top_client_share or 0.0))
            return clamp01(0.7 * route_norm + 0.3 * client_variation)

        group_rows = []
        for eid, payload in group_stats.items():
            hours_val = payload["secs"] / 3600 if payload["secs"] else 0.0
            avg_kgh_val = payload["tonnage"] / hours_val if hours_val else 0.0
            avg_trip_val = (payload["secs"] / 60 / payload["count"]) if payload["count"] else 0.0
            avg_route_val = payload["tonnage"] / payload["count"] if payload["count"] else 0.0

            daily_vals = []
            for data in payload["daily"].values():
                if data["secs"] > 0:
                    daily_vals.append(data["tonnage"] / (data["secs"] / 3600))
            daily_vals_sorted = sorted(daily_vals)
            daily_mean_val = safe_mean(daily_vals_sorted)
            daily_std_val = safe_stdev(daily_vals_sorted)
            cv_val = (daily_std_val / daily_mean_val) if daily_mean_val else 0.0
            slope_val = trend_slope(daily_vals_sorted)
            trend_ratio_val = slope_val / daily_mean_val if daily_mean_val else 0.0

            absence_data_group = group_absence_counts.get(eid, {"justified": 0, "unjustified": 0, "leave": 0, "offday": 0})
            justified_g = absence_data_group["justified"]
            unjustified_g = absence_data_group["unjustified"]
            leave_g = absence_data_group["leave"]
            offday_g = absence_data_group["offday"]
            adjusted_denominator_g = max(1, total_days - justified_g - leave_g - offday_g)
            regularity_adj_g = len(payload["days"]) / adjusted_denominator_g
            absence_penalty_g = get_absence_penalty(period, unjustified_g)
            discipline_rate_g = 1 - (unjustified_g / max(1, total_days))
            occurrences_g = int(group_event_counts.get(eid, 0))
            penalty_factor_g = max(0.7, 1 - occurrences_g * 0.05)

            top_client_count_g = max(payload["clients"].values()) if payload["clients"] else 0
            top_client_share_g = (top_client_count_g / payload["count"]) if payload["count"] else 0.0
            completeness_rate_g = (payload["complete_routes"] / payload["count"]) if payload["count"] else 0.0

            emp_obj = group_emp_map.get(eid)
            tenure_months_g = 0
            tenure_band_g = "Novatos"
            admission_g = to_date(getattr(emp_obj, "admission_date", None)) if emp_obj else None
            if admission_g:
                tenure_months_g = max(0, int((target_date - admission_g).days / 30))
                if tenure_months_g < 3:
                    tenure_band_g = "Novatos"
                elif tenure_months_g < 12:
                    tenure_band_g = "Consolidacao"
                else:
                    tenure_band_g = "Veteranos"

            group_rows.append({
                "employee_id": eid,
                "avg_kgh": avg_kgh_val,
                "total_tonnage": payload["tonnage"],
                "avg_trip_minutes": avg_trip_val,
                "regularity_adjusted": min(1.0, regularity_adj_g),
                "consistency_score": max(0.0, 1 - cv_val),
                "trend_slope": slope_val,
                "trend_ratio": trend_ratio_val,
                "avg_route_tonnage": avg_route_val,
                "top_client_share": top_client_share_g,
                "discipline_rate": max(0.0, discipline_rate_g),
                "absence_penalty_factor": absence_penalty_g,
                "penalty_factor": penalty_factor_g,
                "completeness_rate": completeness_rate_g,
                "tenure_band": tenure_band_g
            })

        group_trip_values = [r["avg_trip_minutes"] for r in group_rows if r.get("avg_trip_minutes")]
        group_trip_avg = safe_mean(group_trip_values) if group_trip_values else 0.0

        kgh_group_values = [r["avg_kgh"] for r in group_rows] or [0.0]
        tonnage_group_values = [r["total_tonnage"] for r in group_rows] or [0.0]
        trip_group_values = [r["avg_trip_minutes"] for r in group_rows] or [0.0]
        reg_group_values = [r["regularity_adjusted"] for r in group_rows] or [0.0]
        cons_group_values = [r["consistency_score"] for r in group_rows] or [0.0]
        trend_group_values = [r["trend_slope"] for r in group_rows] or [0.0]
        route_group_values = [r["avg_route_tonnage"] for r in group_rows] or [0.0]

        min_kgh_g, max_kgh_g = min(kgh_group_values), max(kgh_group_values)
        min_ton_g, max_ton_g = min(tonnage_group_values), max(tonnage_group_values)
        min_trip_g, max_trip_g = min(trip_group_values), max(trip_group_values)
        min_reg_g, max_reg_g = min(reg_group_values), max(reg_group_values)
        min_cons_g, max_cons_g = min(cons_group_values), max(cons_group_values)
        min_trend_g, max_trend_g = min(trend_group_values), max(trend_group_values)
        min_route_g, max_route_g = min(route_group_values), max(route_group_values)

        for row in group_rows:
            kgh_norm = normalize_val(row["avg_kgh"], min_kgh_g, max_kgh_g)
            tonnage_norm = normalize_val(row["total_tonnage"], min_ton_g, max_ton_g)
            trip_norm = 1 - normalize_val(row["avg_trip_minutes"], min_trip_g, max_trip_g)
            regularity_norm = normalize_val(row["regularity_adjusted"], min_reg_g, max_reg_g)
            consistency_norm = normalize_val(row["consistency_score"], min_cons_g, max_cons_g)
            trend_norm = normalize_val(row["trend_slope"], min_trend_g, max_trend_g)
            route_norm = normalize_val(row["avg_route_tonnage"], min_route_g, max_route_g)

            if row["completeness_rate"] < 0.7:
                prod_weights = {"kgh": 0.35, "tonnage": 0.50, "trip": 0.15}
            else:
                prod_weights = {"kgh": 0.50, "tonnage": 0.30, "trip": 0.20}

            raw_productivity = clamp01(
                prod_weights["kgh"] * kgh_norm
                + prod_weights["tonnage"] * tonnage_norm
                + prod_weights["trip"] * trip_norm
            )
            row["productivity_raw"] = raw_productivity
            row["productivity_subweights"] = prod_weights
            row["quality_score"] = clamp01(0.6 * regularity_norm + 0.4 * consistency_norm)
            row["discipline_score"] = clamp01(
                row["discipline_rate"] * row["absence_penalty_factor"] * row["penalty_factor"]
            )
            row["evolution_score"] = clamp01(trend_norm)
            row["context_score"] = compute_context_score(route_norm, row.get("top_client_share", 0.0))

        prod_values_group = [r["productivity_raw"] for r in group_rows]
        for row in group_rows:
            row["productivity_percentile_group"] = percentile_rank(prod_values_group, row["productivity_raw"])
            row["productivity_score"] = clamp01(
                0.65 * row["productivity_percentile_group"] + 0.35 * row["productivity_raw"]
            )
            weights = get_pillar_weights(row["tenure_band"])
            row["pillar_weights"] = weights
            base_score = (
                weights["productivity"] * row["productivity_score"]
                + weights["quality"] * row["quality_score"]
                + weights["discipline"] * row["discipline_score"]
                + weights["evolution"] * row["evolution_score"]
                + weights["context"] * row["context_score"]
            )
            row["score"] = round(base_score * 100, 2)

        score_values_group = [r["score"] for r in group_rows]
        median_score_group = sorted(score_values_group)[len(score_values_group) // 2] if score_values_group else 0
        for row in group_rows:
            row["score_percentile_group"] = percentile_rank(score_values_group, row["score"])

        target_row = next((r for r in group_rows if r["employee_id"] == employee_id), None)
        if target_row:
            productivity_score = target_row["productivity_score"]
            quality_score = target_row["quality_score"]
            discipline_score = target_row["discipline_score"]
            evolution_score = target_row["evolution_score"]
            context_score = target_row["context_score"]
            pillar_weights = target_row["pillar_weights"]
            productivity_percentile_group = target_row.get("productivity_percentile_group", 0.0)
            score_percentile_group = target_row.get("score_percentile_group", 0.0)
            product_subweights = target_row.get("productivity_subweights", {"kgh": 0.5, "tonnage": 0.3, "trip": 0.2})
        else:
            productivity_score = 0.0
            quality_score = 0.0
            discipline_score = 0.0
            evolution_score = 0.0
            context_score = 0.0
            pillar_weights = get_pillar_weights(tenure_band_value)
            productivity_percentile_group = 0.0
            score_percentile_group = 0.0
            product_subweights = {"kgh": 0.5, "tonnage": 0.3, "trip": 0.2}

        route_band_label = ROUTE_BAND_LABELS.get(route_band_value, route_band_value)
        tenure_band_label = TENURE_BAND_LABELS.get(tenure_band_value, tenure_band_value)
        group_label = f"Rota {route_band_label} / Turno {employee_shift}"

        def build_badge() -> dict:
            sample_small_local = sample_small
            if productivity_score == 0 and quality_score == 0 and discipline_score == 0:
                return {"label": "Potencial", "reason": "Sem dados suficientes.", "rule": "Sem produÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o no perÃƒÆ’Ã‚Â­odo"}
            if weighted_score >= 85 and discipline_rate >= 0.95 and regularity_adjusted >= 0.8 and not sample_small_local:
                return {"label": "ReferÃƒÆ’Ã‚Âªncia", "reason": "Alta entrega com disciplina consistente.", "rule": "Score>=85, Disciplina>=95%, PresenÃƒÆ’Ã‚Â§a>=80%, dias>=3"}
            if trend_ratio > 0.05:
                return {"label": "Em evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "reason": "TendÃƒÆ’Ã‚Âªncia de melhora no perÃƒÆ’Ã‚Â­odo.", "rule": "TendÃƒÆ’Ã‚Âªncia>0,05"}
            if unjustified_days > 0 or (group_rows and avg_kgh < safe_mean([r["avg_kgh"] for r in group_rows]) * 0.85):
                if sample_small_local and unjustified_days == 0:
                    return {"label": "Potencial", "reason": "Amostra pequena; evite conclusÃƒÆ’Ã‚Âµes fortes.", "rule": "Amostra<3 dias -> selo rebaixado"}
                return {"label": "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "reason": "Queda de eficiÃƒÆ’Ã‚Âªncia ou faltas nÃƒÆ’Ã‚Â£o justificadas.", "rule": "Falta(s) nÃƒÆ’Ã‚Â£o justificadas ou kg/h < 85% da mÃƒÆ’Ã‚Â©dia"}
            if regularity_adjusted >= 0.8 and weighted_score <= median_score_group:
                return {"label": "Potencial", "reason": "PresenÃƒÆ’Ã‚Â§a alta com performance abaixo do potencial.", "rule": "PresenÃƒÆ’Ã‚Â§a>=80% e score abaixo da mediana"}
            if sample_small_local:
                return {"label": "Potencial", "reason": "Amostra pequena; dados insuficientes.", "rule": "Amostra<3 dias"}
            return {"label": "Potencial", "reason": "Margem clara para evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o com ajustes operacionais.", "rule": "Sem sinais fortes de destaque"}

        def build_strengths() -> List[str]:
            items = []
            if sample_small:
                items.append("Amostra pequena: indÃƒÆ’Ã‚Â­cios limitados")
            if group_rows and avg_kgh > safe_mean([r["avg_kgh"] for r in group_rows]) * 1.1:
                items.append("Velocidade acima da mÃƒÆ’Ã‚Â©dia do grupo")
            if regularity_adjusted >= 0.8:
                items.append("PresenÃƒÆ’Ã‚Â§a consistente no perÃƒÆ’Ã‚Â­odo")
            if trend_ratio > 0.05:
                items.append("TendÃƒÆ’Ã‚Âªncia de melhora no perÃƒÆ’Ã‚Â­odo")
            if discipline_rate >= 0.95 and unjustified_days == 0:
                items.append("Disciplina alta sem faltas")
            return items or ["Sem sinais fortes de destaque no perÃƒÆ’Ã‚Â­odo"]

        def build_losses() -> List[str]:
            items = []
            if sample_small:
                items.append("Amostra pequena: dados insuficientes")
            if group_rows and avg_trip_minutes > safe_mean([r["avg_trip_minutes"] for r in group_rows]) * 1.15:
                items.append("Tempo mÃƒÆ’Ã‚Â©dio por viagem acima da mÃƒÆ’Ã‚Â©dia")
            if unjustified_days > 0:
                items.append(f"{unjustified_days} falta(s) nÃƒÆ’Ã‚Â£o justificadas")
            if occurrences:
                items.append(f"{occurrences} ocorrÃƒÆ’Ã‚Âªncia(s) operacional(is)")
            if group_rows and avg_kgh < safe_mean([r["avg_kgh"] for r in group_rows]) * 0.9:
                items.append("Velocidade abaixo da mÃƒÆ’Ã‚Â©dia do grupo")
            return items or ["Sem perdas crÃƒÆ’Ã‚Â­ticas detectadas no perÃƒÆ’Ã‚Â­odo"]

        def build_how_works() -> List[str]:
            items = [
                f"Liga: {tenure_band_label} ({tenure_months}m)",
                f"Tipo de rota: {route_band_label}",
                f"Turno: {employee_shift}"
            ]
            if top_client and top_client != "-":
                items.append(f"Cliente recorrente: {top_client}")
            return items

        def build_replicable() -> List[str]:
            items = []
            if max(0.0, 1 - cv) >= 0.7:
                items.append("Ritmo estÃƒÆ’Ã‚Â¡vel ao longo do perÃƒÆ’Ã‚Â­odo")
            if discipline_rate >= 0.95 and unjustified_days == 0:
                items.append("Disciplina operacional consistente")
            if group_rows and avg_kgh > safe_mean([r["avg_kgh"] for r in group_rows]) * 1.1:
                items.append("Velocidade acima da mÃƒÆ’Ã‚Â©dia replicÃƒÆ’Ã‚Â¡vel com padronizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o")
            return items or ["Sem padrÃƒÆ’Ã‚Â£o claro para replicaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o no perÃƒÆ’Ã‚Â­odo"]

        weighted_score = target_row["score"] if target_row else 0.0
        productivity_percentile_group_pct = round(productivity_percentile_group * 100, 1)
        score_percentile_group_pct = round(score_percentile_group * 100, 1)
        time_reliability_rate = round(completeness_rate * 100, 1)
        time_estimated = completeness_rate < 0.7
        pillar_sources = {
            "productivity": "EstatÃƒÆ’Ã‚Â­stica",
            "quality": "EstatÃƒÆ’Ã‚Â­stica",
            "discipline": "Regras",
            "evolution": "EstatÃƒÆ’Ã‚Â­stica",
            "context": "Regras"
        }

        badge = build_badge()

        # Extrair source das ausÃƒÆ’Ã‚Âªncias (jÃƒÆ’Ã‚Â¡ obtido acima)
        absences_source = absence_summary.get("source_key", "routine")
        absences_source_label = absence_summary.get("source_label", format_absence_source_label(absences_source))

        # Obter routine_days_logged do absence_summary (jÃƒÆ’Ã‚Â¡ calculado)
        routine_days_logged = absence_summary.get("routine_days_logged", 0)
        
        # Buscar rotinas para verificar routine_missing
        routine_rows = session.exec(
            select(models.EmployeeRoutine.date, models.EmployeeRoutine.routine)
            .where(models.EmployeeRoutine.employee_id == employee_id)
            .where(models.EmployeeRoutine.date >= start_date_str)
            .where(models.EmployeeRoutine.date <= end_date_str)
        ).all()
        routine_days = {str(r_date) for r_date, _ in routine_rows}
        if period == "daily":
            routine_missing = start_date_str not in routine_days
            routine_missing_label = "Sem rotina lanÃƒÆ’Ã‚Â§ada no dia"
        else:
            routine_missing = routine_days_logged == 0
            routine_missing_label = "Sem rotina lanÃƒÆ’Ã‚Â§ada no perÃƒÆ’Ã‚Â­odo"
        absence_timeline = []
        label_map = {
            "unjustified": "Falta",
            "justified": "Atestado",
            "leave": "Afastamento",
            "offday": "Folga"
        }
        day_entries = absence_summary.get("day_map", [])
        logs_day_map = absence_event_day_map or {}
        logs_record_map = absence_event_record_map or {}
        if day_entries:
            for entry in day_entries:
                group = entry.get("group")
                if group not in label_map:
                    continue
                day_key = entry.get("date")
                logs_count = logs_day_map.get(day_key, {}).get(group, 0)
                record_ids = logs_record_map.get(day_key, {}).get(group, [])
                timeline_entry = {
                    "date_br": fmt_ddmmyyyy(day_key),
                    "type_label": label_map.get(group, group),
                    "source_label": format_absence_source_label(entry.get("source")),
                    "logs_count": logs_count
                }
                if LOG_LEVEL == logging.DEBUG and record_ids:
                    timeline_entry["record_ids"] = record_ids
                absence_timeline.append(timeline_entry)
        else:
            for r_date, r_routine in sorted(routine_rows, key=lambda x: x[0]):
                group = normalize_routine_status(r_routine)
                if group not in label_map:
                    continue
                day_key = str(r_date)
                logs_count = logs_day_map.get(day_key, {}).get(group, 0)
                record_ids = logs_record_map.get(day_key, {}).get(group, [])
                timeline_entry = {
                    "date_br": fmt_ddmmyyyy(r_date),
                    "type_label": label_map.get(group, group),
                    "source_label": format_absence_source_label("routine"),
                    "logs_count": logs_count
                }
                if LOG_LEVEL == logging.DEBUG and record_ids:
                    timeline_entry["record_ids"] = record_ids
                absence_timeline.append(timeline_entry)

        def compute_confidence_level(route_days: int, routine_days: int) -> str:
            if route_days >= 10 or routine_days >= 15:
                return "Alta"
            if route_days < 4 and routine_days < 8:
                return "Baixa"
            return "MÃƒÆ’Ã‚Â©dia"

        confidence_level = compute_confidence_level(route_days_active, routine_days_logged)
        confidence_note_map = {
            "Baixa": "Poucos dias no perÃƒÆ’Ã‚Â­odo; use como sinal, nÃƒÆ’Ã‚Â£o como decisÃƒÆ’Ã‚Â£o.",
            "MÃƒÆ’Ã‚Â©dia": "Sinal moderado; confirme com a lideranÃƒÆ’Ã‚Â§a.",
            "Alta": "Sinal consistente no perÃƒÆ’Ã‚Â­odo."
        }
        confidence_note = confidence_note_map.get(confidence_level, "")

        daily_kgh_values = []
        for data in daily.values():
            if data["secs"] > 0:
                daily_kgh_values.append(data["tonnage"] / (data["secs"] / 3600))
        median_kgh = sorted(daily_kgh_values)[len(daily_kgh_values) // 2] if daily_kgh_values else 0.0
        kgh_above_median_days = sum(1 for val in daily_kgh_values if median_kgh and val >= median_kgh)

        def fetch_route_results_for_range(range_start: date, range_end: date) -> List[tuple]:
            if tenure_filter_mismatch:
                return []
            start_str = range_start.strftime("%Y-%m-%d")
            end_str = range_end.strftime("%Y-%m-%d")
            base_query = select(models.Route, models.Client).join(models.Client, models.Route.client_id == models.Client.id)
            base_query = base_query.where(models.Route.employee_id == employee_id)
            base_query = base_query.where(models.Route.tonnage > 0)
            base_query = base_query.where(models.Route.date >= start_str)
            base_query = base_query.where(models.Route.date <= end_str)
            if shift and shift not in ['Geral', 'Todos', None, 'null']:
                base_query = base_query.where(models.Route.shift == shift)
            base_results = session.exec(base_query).all()
            if route_band and route_band not in ["Todos", "Geral", None, "null"]:
                if tonnage_values:
                    base_results = [
                        (r, c) for r, c in base_results
                        if assign_band(float(r.tonnage or 0), band_low, band_high) == route_band
                    ]
                else:
                    return []
            return base_results

        def compute_kgh_stats(route_results: List[tuple]) -> dict:
            daily_map = {}
            total_secs_local = 0.0
            total_routes_local = 0
            for r, _ in route_results:
                tonnage = r.tonnage or 0
                diff = duration_seconds(r.start_time, r.end_time)
                total_routes_local += 1
                if diff > 0:
                    total_secs_local += diff
                    route_day = to_date(r.date)
                    day_key = route_day.isoformat() if route_day else str(r.date)
                    entry = daily_map.setdefault(day_key, {"tonnage": 0.0, "secs": 0.0})
                    entry["tonnage"] += tonnage
                    entry["secs"] += diff
            kgh_values = []
            for data in daily_map.values():
                if data["secs"] > 0:
                    kgh_values.append(data["tonnage"] / (data["secs"] / 3600))
            avg_kgh = safe_mean(kgh_values) if kgh_values else 0.0
            avg_trip_minutes_local = (total_secs_local / 60 / total_routes_local) if total_routes_local else 0.0
            return {
                "kgh_values": kgh_values,
                "avg_kgh": avg_kgh,
                "avg_trip_minutes": avg_trip_minutes_local
            }

        def build_pattern_change() -> dict:
            status = "Sem dados suficientes"
            summary = "Sem dados suficientes para avaliar mudanÃƒÆ’Ã‚Â§a de padrÃƒÆ’Ã‚Â£o no perÃƒÆ’Ã‚Â­odo."
            evidence = []
            delta_pct = 0.0
            delta_trip = 0.0
            delta_cv = 0.0
            latest_kgh = None
            baseline = None
            current_label = ""
            baseline_label = ""
            current_trip_minutes = None
            baseline_trip_minutes = None
            focus_date = target_date

            current_kgh_values = []
            baseline_kgh_values = []

            if period == "daily":
                focus_key = target_date.isoformat()
                latest_entry = daily.get(focus_key)
                if latest_entry and latest_entry["secs"] > 0:
                    latest_kgh = latest_entry["tonnage"] / (latest_entry["secs"] / 3600)
                    current_kgh_values = [latest_kgh]
                current_trip_minutes = avg_trip_minutes
                baseline_start = target_date - timedelta(days=7)
                baseline_end = target_date - timedelta(days=1)
                if baseline_start <= baseline_end:
                    baseline_results = fetch_route_results_for_range(baseline_start, baseline_end)
                    baseline_stats = compute_kgh_stats(baseline_results)
                    baseline_kgh_values = baseline_stats["kgh_values"]
                    baseline_trip_minutes = baseline_stats["avg_trip_minutes"]
                current_label = "No dia base"
                baseline_label = "mÃƒÆ’Ã‚Â©dia dos ÃƒÆ’Ã‚Âºltimos 7 dias"
            elif period == "weekly":
                current_kgh_values = daily_kgh_sorted
                latest_kgh = safe_mean(current_kgh_values) if current_kgh_values else None
                current_trip_minutes = avg_trip_minutes
                baseline_start = start_date_obj - timedelta(days=7)
                baseline_end = start_date_obj - timedelta(days=1)
                if baseline_start <= baseline_end:
                    baseline_results = fetch_route_results_for_range(baseline_start, baseline_end)
                    baseline_stats = compute_kgh_stats(baseline_results)
                    baseline_kgh_values = baseline_stats["kgh_values"]
                    baseline_trip_minutes = baseline_stats["avg_trip_minutes"]
                current_label = "Na semana atual"
                baseline_label = "mÃƒÆ’Ã‚Â©dia da semana anterior"
            else:
                first_half_kgh = []
                second_half_kgh = []
                for day_key, data in daily.items():
                    day_obj = to_date(day_key)
                    if not day_obj or data.get("secs", 0) <= 0:
                        continue
                    kgh_val = data["tonnage"] / (data["secs"] / 3600)
                    if day_obj.day <= 15:
                        first_half_kgh.append(kgh_val)
                    else:
                        second_half_kgh.append(kgh_val)
                first_half_secs = 0.0
                first_half_routes = 0
                second_half_secs = 0.0
                second_half_routes = 0
                for day_key, route_count in daily_route_counts.items():
                    day_obj = to_date(day_key)
                    if not day_obj:
                        continue
                    day_secs = daily.get(day_key, {}).get("secs", 0.0)
                    if day_obj.day <= 15:
                        first_half_secs += day_secs
                        first_half_routes += route_count
                    else:
                        second_half_secs += day_secs
                        second_half_routes += route_count
                first_half_trip = (first_half_secs / 60 / first_half_routes) if first_half_routes else 0.0
                second_half_trip = (second_half_secs / 60 / second_half_routes) if second_half_routes else 0.0
                if target_date.day <= 15:
                    current_kgh_values = first_half_kgh
                    baseline_kgh_values = second_half_kgh
                    current_trip_minutes = first_half_trip
                    baseline_trip_minutes = second_half_trip
                    current_label = "Na 1Ãƒâ€šÃ‚Âª quinzena"
                    baseline_label = "mÃƒÆ’Ã‚Â©dia da 2Ãƒâ€šÃ‚Âª quinzena"
                else:
                    current_kgh_values = second_half_kgh
                    baseline_kgh_values = first_half_kgh
                    current_trip_minutes = second_half_trip
                    baseline_trip_minutes = first_half_trip
                    current_label = "Na 2Ãƒâ€šÃ‚Âª quinzena"
                    baseline_label = "mÃƒÆ’Ã‚Â©dia da 1Ãƒâ€šÃ‚Âª quinzena"
                latest_kgh = safe_mean(current_kgh_values) if current_kgh_values else None

            if latest_kgh and baseline_kgh_values:
                baseline = safe_mean(baseline_kgh_values)
            if latest_kgh and baseline:
                delta_pct = (latest_kgh - baseline) / baseline
                direction = "acima" if delta_pct > 0 else "abaixo"
                summary = f"{current_label} ficou {fmt_br_pct(abs(delta_pct))} {direction} da {baseline_label} para {group_label}."
                sign_pct = "+" if delta_pct >= 0 else "-"
                evidence.append(f"Kg/h: {fmt_br_2(latest_kgh)} vs {fmt_br_2(baseline)} ({sign_pct}{fmt_br_pct(abs(delta_pct))})")
            if current_kgh_values and baseline_kgh_values:
                current_mean = safe_mean(current_kgh_values)
                baseline_mean = safe_mean(baseline_kgh_values)
                current_cv = (safe_stdev(current_kgh_values) / current_mean) if current_mean else 0.0
                baseline_cv = (safe_stdev(baseline_kgh_values) / baseline_mean) if baseline_mean else 0.0
                delta_cv = current_cv - baseline_cv
                if delta_cv >= 0.15:
                    evidence.append(f"OscilaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o maior no perÃƒÆ’Ã‚Â­odo (+{fmt_br_2(delta_cv)})")
            if current_trip_minutes and baseline_trip_minutes:
                delta_trip = current_trip_minutes - baseline_trip_minutes
                sign = "+" if delta_trip >= 0 else "-"
                evidence.append(f"Tempo/viagem: {fmt_br_2(current_trip_minutes)} vs {fmt_br_2(baseline_trip_minutes)} ({sign}{fmt_br_2(abs(delta_trip))} min)")
            elif group_trip_avg:
                delta_trip = avg_trip_minutes - group_trip_avg
                sign = "+" if delta_trip >= 0 else "-"
                evidence.append(f"Tempo/viagem {sign}{fmt_br(abs(delta_trip))} min vs mÃƒÆ’Ã‚Â©dia do grupo")

            focus_date_label = fmt_ddmm(focus_date)
            if focus_date_label and routes_data:
                latest_clients = [r["client"] for r in routes_data if r.get("date") == focus_date_label]
                if latest_clients:
                    latest_client = Counter(latest_clients).most_common(1)[0][0]
                    if latest_client != top_client:
                        evidence.append(f"Cliente no dia: {latest_client} (padrÃƒÆ’Ã‚Â£o: {top_client})")
                    else:
                        evidence.append(f"Cliente predominante no dia: {latest_client}")

            absence_days_set = {entry.get("date") for entry in day_entries if entry.get("date")}
            if focus_date and absence_days_set:
                prev_day = (focus_date - timedelta(days=1)).isoformat()
                next_day = (focus_date + timedelta(days=1)).isoformat()
                if prev_day in absence_days_set or next_day in absence_days_set:
                    evidence.append("AusÃƒÆ’Ã‚Âªncia prÃƒÆ’Ã‚Â³xima no calendÃƒÆ’Ã‚Â¡rio (dia anterior/posterior)")

            reliability_label = fmt_br_pct(completeness_rate)
            if completeness_rate < 0.7:
                reliability_label = f"{reliability_label} (estimado)"
            evidence.append(f"Confiabilidade do tempo: {reliability_label}")
            if routine_missing:
                evidence.append(routine_missing_label)

            if latest_kgh and baseline:
                if abs(delta_pct) >= 0.15 or abs(delta_trip) >= 8 or delta_cv >= 0.15:
                    status = "Sinal de atenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o" if delta_pct < -0.15 else "MudanÃƒÆ’Ã‚Â§a de contexto"
                else:
                    status = "VariaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o normal"

            return {
                "label": status,
                "summary": summary,
                "evidence": evidence[:4],
                "delta_pct": delta_pct,
                "delta_trip_minutes": delta_trip,
                "latest_kgh": latest_kgh,
                "baseline_kgh": baseline
            }

        pattern_change = build_pattern_change()
        pattern_change_delta = pattern_change.get("delta_pct", 0.0) or 0.0

        def build_recommendations() -> dict:
            promotion = []
            training = []
            risk = []

            promotion_condition = (
                confidence_level == "Alta"
                and (score_percentile_group >= 0.8 or weighted_score >= 80)
                and unjustified_days == 0
                and completeness_rate >= 0.85
                and pattern_change.get("label") != "Sinal de atenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"
            )
            if promotion_condition:
                promo_evidence = []
                if score_percentile_group >= 0.8:
                    promo_evidence.append("Score no top 20% da liga")
                else:
                    promo_evidence.append(f"Score ponderado {fmt_br_2(weighted_score)}")
                promo_evidence.append("0 faltas no perÃƒÆ’Ã‚Â­odo")
                if kgh_above_median_days:
                    promo_evidence.append(f"Produtividade acima da mediana por {kgh_above_median_days} dias")
                promotion.append({
                    "label": "ElegÃƒÆ’Ã‚Â­vel para promoÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o",
                    "evidence": promo_evidence[:3],
                    "confidence": confidence_level
                })

            training_condition = (
                confidence_level != "Baixa"
                and unjustified_days <= 1
                and (
                    (productivity_percentile_group <= 0.3 and regularity_adjusted >= 0.80)
                    or (regularity_adjusted < 0.70)
                    or (cv > 0.35)
                )
            )
            training_focus = ""
            training_evidence = []
            if productivity_percentile_group <= 0.3:
                training_evidence.append(f"Kg/h abaixo do grupo ({fmt_br_pct(productivity_percentile_group)})")
                training_focus = "Treino de mÃƒÆ’Ã‚Â©todo (sequÃƒÆ’Ã‚Âªncia e padrÃƒÆ’Ã‚Â£o)"
            if regularity_adjusted < 0.70 and unjustified_days == 0:
                training_evidence.append("Regularidade abaixo do esperado")
                training_focus = "Treino de rotina (constÃƒÆ’Ã‚Â¢ncia e organizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o)"
            if cv > 0.35:
                training_evidence.append(f"OscilaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o alta (CV {fmt_br_2(cv)})")
                if not training_focus:
                    training_focus = "Treino de padrÃƒÆ’Ã‚Â£o para estabilidade"
            if training_condition:
                training.append({
                    "label": "Treinamento direcionado",
                    "evidence": training_evidence[:3],
                    "confidence": confidence_level,
                    "action": training_focus
                })

            risk_triggers = (
                unjustified_days >= 2
                or score_percentile_group <= 0.20
                or (pattern_change_delta <= -0.15)
            )
            risk_status = "Sem alerta"
            risk_evidence = []
            if risk_triggers:
                if unjustified_days >= 2:
                    risk_evidence.append(f"Faltas nÃƒÆ’Ã‚Â£o justificadas: {unjustified_days}")
                if score_percentile_group <= 0.20:
                    risk_evidence.append(f"Score abaixo do percentil 20 ({fmt_br_pct(score_percentile_group)})")
                if pattern_change_delta <= -0.15:
                    risk_evidence.append(f"Queda diÃƒÆ’Ã‚Â¡ria relevante ({fmt_br_pct(abs(pattern_change_delta))})")
                if confidence_level == "Baixa":
                    risk_evidence.append("Sinal fraco por baixa amostra")
                    risk_status = "Sinal fraco (baixa amostra)"
                else:
                    risk_status = "Risco operacional (revisÃƒÆ’Ã‚Â£o humana)" if unjustified_days >= 2 else "Alerta precoce"
                risk.append({
                    "label": risk_status,
                    "evidence": risk_evidence[:3],
                    "confidence": confidence_level
                })

            if promotion_condition:
                readiness_for_promotion = "ElegÃƒÆ’Ã‚Â­vel para promoÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"
            elif risk_triggers and confidence_level != "Baixa":
                readiness_for_promotion = "NÃƒÆ’Ã‚Â£o recomendado para promoÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o no momento"
            elif training_condition:
                readiness_for_promotion = "ElegÃƒÆ’Ã‚Â­vel para desenvolvimento"
            else:
                readiness_for_promotion = "Requer acompanhamento"

            if training_condition:
                training_priority = "Alta" if len(training_evidence) >= 2 else "MÃƒÆ’Ã‚Â©dia"
            else:
                training_priority = "Baixa"

            return {
                "promotion": promotion,
                "training": training,
                "risk": risk,
                "readiness_for_promotion": readiness_for_promotion,
                "training_priority": training_priority,
                "risk_flag": risk_status,
                "confidence_level": confidence_level,
                "confidence_note": confidence_note
            }

        recommendations = build_recommendations()

        model_origin = "EstatÃƒÆ’Ã‚Â­stica" if len(group_rows) >= 12 else "Regras"
        model_notes = {
            "sees": [
                f"Percentil do grupo: {fmt_br_pct(score_percentile_group)}",
                f"Disciplina: {fmt_br_pct(discipline_rate)}",
                f"ConsistÃƒÆ’Ã‚Âªncia (CV): {fmt_br_2(cv)}"
            ],
            "not_conclude": [
                "CorrelaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o indica causa",
                "NÃƒÆ’Ã‚Â£o substitui avaliaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o do lÃƒÆ’Ã‚Â­der",
                "NÃƒÆ’Ã‚Â£o considera fatores pessoais fora do perÃƒÆ’Ã‚Â­odo"
            ]
        }


            
        payload = {
            "employee": {
                "name": employee.name if employee else "Desconhecido",
                "photo": employee.photo_url if employee else None
            },
            "summary": {
                "total_tonnage": int(total_tonnage),
                "avg_kgh": int(avg_kgh),
                "total_hours": f"{int(hours):02d}:{int((hours*60)%60):02d}",
                "count": len(routes_data),
                "route_days_active": route_days_active,
                "routine_days_logged": routine_days_logged,
                "absences": {
                    "days": {
                        "justified": justified_days,
                        "unjustified": unjustified_days,
                        "leave": leave_days,
                        "offday": offday_days,
                        "total": justified_days + unjustified_days + leave_days + offday_days
                    },
                    "logs": {
                        "justified": absence_events.get("justified", 0),
                        "unjustified": absence_events.get("unjustified", 0),
                        "leave": absence_events.get("leave", 0),
                        "offday": absence_events.get("offday", 0),
                        "total": absence_events.get("total", 0)
                    },
                    "source": absences_source,
                    "source_label": absences_source_label
                },
                "absences_days": {
                    "justified": justified_days,
                    "unjustified": unjustified_days,
                    "leave": leave_days,
                    "offday": offday_days,
                    "total": justified_days + unjustified_days + leave_days + offday_days
                },
                "absences_logs": {
                    "justified": absence_events.get("justified", 0),
                    "unjustified": absence_events.get("unjustified", 0),
                    "leave": absence_events.get("leave", 0),
                    "offday": absence_events.get("offday", 0),
                    "total": absence_events.get("total", 0)
                },
                "absences_events": {
                    "justified": absence_events.get("justified", 0),
                    "unjustified": absence_events.get("unjustified", 0),
                    "leave": absence_events.get("leave", 0),
                    "offday": absence_events.get("offday", 0),
                    "total": absence_events.get("total", 0)
                },
                "absences_source": absences_source,
                "absences_source_label": absences_source_label,
                "justified_days": justified_days,
                "unjustified_days": unjustified_days,
                "leave_days": leave_days,
                "offday_days": offday_days,
                "regularity_adjusted": min(1.0, regularity_adjusted),
                "absence_penalty_factor": absence_penalty_factor,
                "presence_rate": min(1.0, regularity_adjusted),
                "discipline_rate": max(0.0, discipline_rate),
                "tenure_months": tenure_months,
                "tenure_band": tenure_band_label
            },
            "analysis": {
                "badge": badge["label"],
                "badge_reason": badge["reason"],
                "badge_rule": badge.get("rule", ""),
                "absences_source": absences_source,
                "absences_source_label": absences_source_label,
                "weighted_score": round(weighted_score, 2),
                "pillars": {
                    "productivity": round(productivity_score * 100, 1),
                    "quality": round(quality_score * 100, 1),
                    "discipline": round(discipline_score * 100, 1),
                    "evolution": round(evolution_score * 100, 1),
                    "context": round(context_score * 100, 1)
                },
                "pillar_weights": {
                    "productivity": round(pillar_weights["productivity"] * 100, 1),
                    "quality": round(pillar_weights["quality"] * 100, 1),
                    "discipline": round(pillar_weights["discipline"] * 100, 1),
                    "evolution": round(pillar_weights["evolution"] * 100, 1),
                    "context": round(pillar_weights["context"] * 100, 1)
                },
                "pillar_sources": pillar_sources,
                "productivity_percentile_group": productivity_percentile_group_pct,
                "score_percentile_group": score_percentile_group_pct,
                "group_label": group_label,
                "sample_days": sample_days,
                "sample_small": sample_small,
                "sample_note": "Amostra pequena; dados insuficientes." if sample_small else "",
                "time_reliability_rate": time_reliability_rate,
                "time_estimated": time_estimated,
                "productivity_subweights": {
                    "kgh": round(product_subweights.get("kgh", 0.0) * 100, 1),
                    "tonnage": round(product_subweights.get("tonnage", 0.0) * 100, 1),
                    "trip": round(product_subweights.get("trip", 0.0) * 100, 1)
                },
                "how_works": build_how_works(),
                "losses": build_losses(),
                "strengths": build_strengths(),
                "replicable": build_replicable(),
                "timeline": {
                    "kgh_by_day": timeline_kgh,
                    "absences_by_day": absence_timeline
                },
                "recommendations": recommendations,
                "readiness_for_promotion": recommendations.get("readiness_for_promotion"),
                "training_priority": recommendations.get("training_priority"),
                "risk_flag": recommendations.get("risk_flag"),
                "confidence_level": recommendations.get("confidence_level"),
                "confidence_note": recommendations.get("confidence_note"),
                "model_origin": model_origin,
                "model_notes": model_notes,
                "pattern_change": pattern_change,
                "routine_missing": routine_missing,
                "routine_missing_label": routine_missing_label if routine_missing else "",
                "context": {
                    "route_band": route_band_label,
                    "top_client": top_client,
                    "top_client_share": round(top_client_share * 100, 1),
                    "shift": employee_shift
                },
                "sources": {
                    "score": "EstatÃƒÆ’Ã‚Â­stica",
                    "trend": "EstatÃƒÆ’Ã‚Â­stica",
                    "context": "Regras"
                }
            },
            "routes": sorted(routes_data, key=lambda x: x['start'] or "", reverse=True)
        }
        if debug_absence:
            payload["analysis"]["debug_absence_days"] = debug_absence_days
            payload["analysis"]["debug_unknown_labels"] = absence_summary.get("debug_unknown_labels", [])
        return payload
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"Erro: {str(e)}", status_code=500)


@app.post("/api/rankings/ai-report")
async def generate_ai_report(
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """
    Gera relatÃƒÆ’Ã‚Â³rios de performance usando IA (OpenAI GPT-4o-mini).
    
    Tipos de relatÃƒÆ’Ã‚Â³rio:
    - executive: Resumo executivo para diretoria (1-2 parÃƒÆ’Ã‚Â¡grafos)
    - detailed: RelatÃƒÆ’Ã‚Â³rio detalhado por setor/turno
    - individual: AnÃƒÆ’Ã‚Â¡lise individual de um colaborador
    - recommendations: RecomendaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de aÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o prioritÃƒÆ’Ã‚Â¡rias
    """
    if not gemini_client:
        return JSONResponse(
            {"error": "ServiÃƒÆ’Ã‚Â§o de IA nÃƒÆ’Ã‚Â£o configurado. Configure GEMINI_API_KEY no ambiente."},
            status_code=503
        )
    
    try:
        data = await request.json()
        report_type = data.get("report_type", "executive")
        employee_id = data.get("employee_id")
        date_str = data.get("date")
        period = data.get("period", "weekly")
        shift = data.get("shift", "Todos")
        team_stats = data.get("team_stats", {})
        rows = data.get("rows", [])
        insights = data.get("insights", {})
        
        # Preparar dados para os prompts (fora das f-strings para evitar erros de sintaxe)
        top5_data = json.dumps([{"nome": r.get("name"), "score": r.get("score"), "badge": r.get("badge")} for r in rows[:5]], ensure_ascii=False, indent=2)
        top10_data = json.dumps([{"nome": r.get("name"), "score": r.get("score"), "kgh": r.get("avg_kgh"), "badge": r.get("badge"), "tendencia": r.get("trend_label")} for r in rows[:10]], ensure_ascii=False, indent=2)
        badge_counts = json.dumps({badge: len([r for r in rows if r.get("badge") == badge]) for badge in ["ReferÃƒÆ’Ã‚Âªncia", "Em evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "Potencial", "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"]}, ensure_ascii=False)
        atencao_data = json.dumps([{"nome": r.get("name"), "score": r.get("score"), "faltas": r.get("unjustified_absences"), "motivo": r.get("badge_reason")} for r in rows if r.get("badge") == "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"][:5], ensure_ascii=False, indent=2)
        referencia_data = json.dumps([{"nome": r.get("name"), "score": r.get("score"), "motivo": r.get("badge_reason")} for r in rows if r.get("badge") == "ReferÃƒÆ’Ã‚Âªncia"][:5], ensure_ascii=False, indent=2)
        evolucao_data = json.dumps([{"nome": r.get("name"), "score": r.get("score"), "tendencia": r.get("trend_label")} for r in rows if r.get("badge") == "Em evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"][:5], ensure_ascii=False, indent=2)
        atencao_full_data = json.dumps([{"nome": r.get("name"), "score": r.get("score"), "faltas": r.get("unjustified_absences"), "kgh": r.get("avg_kgh"), "motivo": r.get("badge_reason")} for r in rows if r.get("badge") == "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"], ensure_ascii=False, indent=2)
        insights_data = json.dumps(insights, ensure_ascii=False, indent=2)
        
        # Prompts especÃƒÆ’Ã‚Â­ficos para cada tipo de relatÃƒÆ’Ã‚Â³rio
        prompts = {
            "executive": f"""VocÃƒÆ’Ã‚Âª ÃƒÆ’Ã‚Â© um analista de operaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes logÃƒÆ’Ã‚Â­sticas gerando um RESUMO EXECUTIVO para a diretoria.

DADOS DO PERÃƒÆ’Ã‚ÂODO ({period}):
- Volume total: {team_stats.get('total_tonnage', 0):,.0f} kg
- MÃƒÆ’Ã‚Â©dia Kg/h: {team_stats.get('avg_kgh', 0):,.0f}
- Colaboradores ativos: {team_stats.get('active_employees', 0)}
- Taxa de presenÃƒÆ’Ã‚Â§a: {team_stats.get('avg_presence_adjusted', 0)*100:.1f}%
- Taxa de disciplina: {team_stats.get('discipline_rate', 0)*100:.1f}%
- Faltas nÃƒÆ’Ã‚Â£o justificadas: {team_stats.get('unjustified_total', 0)}

DESTAQUES:
{insights_data}

TOP 5 COLABORADORES:
{top5_data}

Gere um resumo executivo de 2-3 parÃƒÆ’Ã‚Â¡grafos em portuguÃƒÆ’Ã‚Âªs brasileiro, profissional e objetivo, destacando:
1. Performance geral do perÃƒÆ’Ã‚Â­odo
2. Pontos positivos e conquistas
3. Pontos de atenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o que requerem aÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o

NÃƒÆ’Ã‚Â£o use markdown, apenas texto corrido.""",

            "detailed": f"""VocÃƒÆ’Ã‚Âª ÃƒÆ’Ã‚Â© um analista de operaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes logÃƒÆ’Ã‚Â­sticas gerando um RELATÃƒÆ’Ã¢â‚¬Å“RIO DETALHADO.

DADOS DO PERÃƒÆ’Ã‚ÂODO ({period}) - Turno: {shift}:
- Volume total: {team_stats.get('total_tonnage', 0):,.0f} kg
- MÃƒÆ’Ã‚Â©dia Kg/h: {team_stats.get('avg_kgh', 0):,.0f}
- Tempo mÃƒÆ’Ã‚Â©dio/viagem: {team_stats.get('avg_trip_minutes', 0):.1f} min
- Colaboradores ativos: {team_stats.get('active_employees', 0)}
- Taxa de presenÃƒÆ’Ã‚Â§a: {team_stats.get('avg_presence_adjusted', 0)*100:.1f}%
- Taxa de disciplina: {team_stats.get('discipline_rate', 0)*100:.1f}%

ANÃƒÆ’Ã‚ÂLISE POR BADGE:
{badge_counts}

TOP 10 COLABORADORES:
{top10_data}

COLABORADORES QUE PRECISAM DE ATENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O:
{atencao_data}

Gere um relatÃƒÆ’Ã‚Â³rio detalhado em portuguÃƒÆ’Ã‚Âªs brasileiro com seÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes:
1. VISÃƒÆ’Ã†â€™O GERAL DO PERÃƒÆ’Ã‚ÂODO
2. ANÃƒÆ’Ã‚ÂLISE DE PRODUTIVIDADE
3. ANÃƒÆ’Ã‚ÂLISE DE DISCIPLINA E PRESENÃƒÆ’Ã¢â‚¬Â¡A
4. DESTAQUES POSITIVOS
5. PONTOS DE ATENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O
6. RECOMENDAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã¢â‚¬Â¢ES

Use formataÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o clara com tÃƒÆ’Ã‚Â­tulos em MAIÃƒÆ’Ã…Â¡SCULAS e bullet points (ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢).""",

            "recommendations": f"""VocÃƒÆ’Ã‚Âª ÃƒÆ’Ã‚Â© um consultor de gestÃƒÆ’Ã‚Â£o de pessoas gerando RECOMENDAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã¢â‚¬Â¢ES DE AÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O.

CONTEXTO:
- PerÃƒÆ’Ã‚Â­odo: {period}
- Colaboradores ativos: {team_stats.get('active_employees', 0)}
- Taxa de disciplina: {team_stats.get('discipline_rate', 0)*100:.1f}%
- Faltas nÃƒÆ’Ã‚Â£o justificadas: {team_stats.get('unjustified_total', 0)}

COLABORADORES REFERÃƒÆ’Ã…Â NCIA (para reconhecer):
{referencia_data}

COLABORADORES EM EVOLUÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O (para acompanhar):
{evolucao_data}

COLABORADORES QUE PRECISAM DE ATENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O (aÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o urgente):
{atencao_full_data}

Gere recomendaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes prÃƒÆ’Ã‚Â¡ticas em portuguÃƒÆ’Ã‚Âªs brasileiro:
1. AÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã¢â‚¬Â¢ES IMEDIATAS (esta semana)
2. RECONHECIMENTOS E FEEDBACK POSITIVO
3. CONVERSAS INDIVIDUAIS NECESSÃƒÆ’Ã‚ÂRIAS
4. TREINAMENTOS SUGERIDOS
5. ALERTAS DE RISCO

Seja especÃƒÆ’Ã‚Â­fico, mencione nomes quando relevante. Use bullet points (ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢)."""
        }
        
        # Prompt para relatÃƒÆ’Ã‚Â³rio individual
        if report_type == "individual" and employee_id:
            emp_data = next((r for r in rows if r.get("id") == employee_id), None)
            if emp_data:
                prompts["individual"] = f"""VocÃƒÆ’Ã‚Âª ÃƒÆ’Ã‚Â© um gestor gerando uma AVALIAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O INDIVIDUAL para feedback.

COLABORADOR: {emp_data.get("name")}
PERÃƒÆ’Ã‚ÂODO: {period}

INDICADORES:
- Score geral: {emp_data.get("score", 0):.1f}
- Badge: {emp_data.get("badge")}
- Kg/h mÃƒÆ’Ã‚Â©dio: {emp_data.get("avg_kgh", 0):,.0f}
- Volume total: {emp_data.get("total_tonnage", 0):,.0f} kg
- Viagens: {emp_data.get("count", 0)}
- PresenÃƒÆ’Ã‚Â§a ajustada: {emp_data.get("regularity_adjusted", 0)*100:.1f}%
- ConsistÃƒÆ’Ã‚Âªncia (CV): {emp_data.get("cv", 0):.2f}
- TendÃƒÆ’Ã‚Âªncia: {emp_data.get("trend_label")}
- Faltas nÃƒÆ’Ã‚Â£o justificadas: {emp_data.get("unjustified_absences", 0)}
- Tempo de casa: {emp_data.get("tenure_months", 0)} meses
- Liga: {emp_data.get("tenure_band")}

CONTEXTO:
- MÃƒÆ’Ã‚Â©dia Kg/h do time: {team_stats.get('avg_kgh', 0):,.0f}
- PosiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o no ranking: {rows.index(emp_data) + 1 if emp_data in rows else 'N/A'} de {len(rows)}

Gere uma avaliaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o individual em portuguÃƒÆ’Ã‚Âªs brasileiro com:
1. RESUMO DO DESEMPENHO (2-3 frases)
2. PONTOS FORTES (bullets)
3. ÃƒÆ’Ã‚ÂREAS DE MELHORIA (bullets)
4. SUGESTÃƒÆ’Ã¢â‚¬Â¢ES DE DESENVOLVIMENTO (bullets)
5. PRÃƒÆ’Ã¢â‚¬Å“XIMOS PASSOS RECOMENDADOS

Tom: profissional mas construtivo, focado em desenvolvimento."""
        
        prompt = prompts.get(report_type, prompts["executive"])
        
        # Chamar Google Gemini
        system_instruction = "VocÃƒÆ’Ã‚Âª ÃƒÆ’Ã‚Â© um analista de operaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes logÃƒÆ’Ã‚Â­sticas especializado em gestÃƒÆ’Ã‚Â£o de pessoas e performance operacional. Responda sempre em portuguÃƒÆ’Ã‚Âªs brasileiro."
        full_prompt = f"{system_instruction}\n\n{prompt}"
        
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=full_prompt
        )
        report_text = response.text
        
        return JSONResponse({
            "success": True,
            "report_type": report_type,
            "report": report_text,
            "generated_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
            "model": "gemini-2.0-flash"
        })
        
    except Exception as e:
        logger.error(f"Erro ao gerar relatÃƒÆ’Ã‚Â³rio IA: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"error": f"Erro ao gerar relatÃƒÆ’Ã‚Â³rio: {str(e)}"},
            status_code=500
        )


@app.get("/operations/performance/report", response_class=HTMLResponse)
async def export_performance_report(
    request: Request,
    date: Optional[str] = None,
    period: str = "weekly",
    shift: str = "Todos",
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """
    Gera relatÃƒÆ’Ã‚Â³rio PDF de performance operacional.
    Reutiliza a lÃƒÆ’Ã‚Â³gica da pÃƒÆ’Ã‚Â¡gina principal de rankings.
    """
    from collections import Counter
    
    def parse_time_value(value) -> Optional[time]:
        """Parse time from various formats"""
        if value is None:
            return None
        if isinstance(value, time):
            return value
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, str):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(value.strip(), fmt).time()
                except Exception:
                    continue
        return None
    
    def duration_seconds(start_val, end_val) -> float:
        """Calculate duration in seconds between two time values"""
        start_time = parse_time_value(start_val)
        end_time = parse_time_value(end_val)
        if not start_time or not end_time:
            return 0.0
        start_dt = datetime.combine(datetime.now().date(), start_time)
        end_dt = datetime.combine(datetime.now().date(), end_time)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        return max(0.0, (end_dt - start_dt).total_seconds())
    
    # Parsear data
    target_date = safe_parse_iso_date(date) if date else datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start_date, end_date = get_period_range(target_date, period)
    total_days = (end_date - start_date).days + 1
    
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    
    # Labels do perÃƒÆ’Ã‚Â­odo
    period_label_map = {'daily': 'DiÃƒÆ’Ã‚Â¡rio', 'weekly': 'Semanal', 'monthly': 'Mensal'}
    period_label = period_label_map.get(period, period)
    period_range_label = f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
    
    # Buscar colaboradores elegÃƒÆ’Ã‚Â­veis (habilitados no app de SeparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o)
    allowed_query = select(models.Employee).where(models.Employee.mobile_access_separation == True)
    if shift and shift not in ["Todos", "Geral", None]:
        allowed_query = allowed_query.where(models.Employee.work_shift == shift)
    allowed_employees = session.exec(allowed_query).all()
    allowed_ids = {emp.id for emp in allowed_employees if emp and emp.id}
    
    # Buscar rotas apenas de colaboradores elegÃƒÆ’Ã‚Â­veis
    query = (
        select(models.Route)
        .where(models.Route.tonnage > 0)
        .where(models.Route.date >= start_date.strftime("%Y-%m-%d"))
        .where(models.Route.date <= end_date.strftime("%Y-%m-%d"))
    )
    if shift and shift not in ["Todos", "Geral", None]:
        query = query.where(models.Route.shift == shift)
    if allowed_ids:
        query = query.where(models.Route.employee_id.in_(allowed_ids))
    
    routes = session.exec(query).all()
    
    # Agrupar por colaborador
    stats = {}
    for route in routes:
        if not route.employee_id:
            continue
        if allowed_ids and route.employee_id not in allowed_ids:
            continue
        tonnage = float(route.tonnage or 0)
        if tonnage <= 0:
            continue
        
        entry = stats.setdefault(route.employee_id, {
            "tonnage": 0.0,
            "secs": 0.0,
            "count": 0,
            "complete_routes": 0,
            "days": set(),
            "daily": {},
        })
        entry["tonnage"] += tonnage
        entry["count"] += 1
        entry["days"].add(str(route.date))
        
        # Calcular tempo usando funÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o robusta
        diff = duration_seconds(route.start_time, route.end_time)
        
        if diff > 0:
            entry["secs"] += diff
            entry["complete_routes"] += 1
        
        day_key = str(route.date)
        day_entry = entry["daily"].setdefault(day_key, {"tonnage": 0.0, "secs": 0.0})
        day_entry["tonnage"] += tonnage
        day_entry["secs"] += diff
    
    # Buscar colaboradores
    emp_ids = list(stats.keys())
    employees = {}
    if emp_ids:
        emps = session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all()
        employees = {e.id: e for e in emps}
    
    # Calcular mÃƒÆ’Ã‚Â©tricas
    rows = []
    for emp_id, data in stats.items():
        emp = employees.get(emp_id)
        if not emp:
            continue
        
        # Kg/h mÃƒÆ’Ã‚Â©dio
        daily_kgh = []
        for day_data in data["daily"].values():
            if day_data["secs"] > 0:
                daily_kgh.append(day_data["tonnage"] / (day_data["secs"] / 3600))
        avg_kgh = statistics.mean(daily_kgh) if daily_kgh else 0
        
        # CV
        cv = (statistics.pstdev(daily_kgh) / avg_kgh) if avg_kgh and len(daily_kgh) > 1 else 0
        
        # Tempo mÃƒÆ’Ã‚Â©dio por viagem
        avg_trip_minutes = (data["secs"] / 60 / data["count"]) if data["count"] else 0
        
        # PresenÃƒÆ’Ã‚Â§a
        active_days = len(data["days"])
        regularity = active_days / max(1, total_days)
        
        # TendÃƒÆ’Ã‚Âªncia
        if len(daily_kgh) >= 3:
            half = len(daily_kgh) // 2
            first_half = statistics.mean(daily_kgh[:half]) if daily_kgh[:half] else 0
            second_half = statistics.mean(daily_kgh[half:]) if daily_kgh[half:] else 0
            trend = (second_half - first_half) / first_half if first_half else 0
        else:
            trend = 0
        
        if trend > 0.05:
            trend_label = f"ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬Ëœ +{trend*100:.0f}%"
        elif trend < -0.05:
            trend_label = f"ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬Å“ {trend*100:.0f}%"
        else:
            trend_label = "ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ EstÃƒÆ’Ã‚Â¡vel"
        
        # Score simples
        score = min(100, (avg_kgh / 800 * 50) + (regularity * 30) + ((1 - cv) * 20))
        
        # Badge
        if score >= 85 and regularity >= 0.8:
            badge = "ReferÃƒÆ’Ã‚Âªncia"
            badge_reason = "Alta entrega com presenÃƒÆ’Ã‚Â§a consistente"
        elif trend > 0.05:
            badge = "Em evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"
            badge_reason = "TendÃƒÆ’Ã‚Âªncia positiva no perÃƒÆ’Ã‚Â­odo"
        elif score < 50 or regularity < 0.5:
            badge = "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"
            badge_reason = "Performance abaixo do esperado"
        else:
            badge = "Potencial"
            badge_reason = "Margem para evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"
        
        rows.append({
            "id": emp_id,
            "name": emp.name,
            "score": score,
            "avg_kgh": avg_kgh,
            "total_tonnage": data["tonnage"],
            "count": data["count"],
            "regularity_adjusted": regularity,
            "cv": cv,
            "trend_label": trend_label,
            "badge": badge,
            "badge_reason": badge_reason,
            "unjustified_absences": 0,  # Simplificado
            "pillar_scores": {
                "productivity": min(100, avg_kgh / 8),
                "quality": min(100, (1 - cv) * 100),
                "discipline": min(100, regularity * 100),
                "evolution": min(100, 50 + trend * 100),
                "context": 50
            }
        })
    
    # Ordenar por score
    rows.sort(key=lambda x: x["score"], reverse=True)
    
    # Calcular estatÃƒÆ’Ã‚Â­sticas do time
    team_stats = {
        "total_tonnage": sum(r["total_tonnage"] for r in rows),
        "avg_kgh": statistics.mean([r["avg_kgh"] for r in rows]) if rows else 0,
        "avg_trip_minutes": statistics.mean([r.get("avg_trip_minutes", 0) for r in rows]) if rows else 0,
        "active_employees": len(rows),
        "avg_presence_adjusted": statistics.mean([r["regularity_adjusted"] for r in rows]) if rows else 0,
        "discipline_rate": 0.95,  # Placeholder
        "unjustified_total": 0
    }
    
    # Contagem de badges
    badge_counts = {
        "referencia": len([r for r in rows if r["badge"] == "ReferÃƒÆ’Ã‚Âªncia"]),
        "evolucao": len([r for r in rows if r["badge"] == "Em evoluÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"]),
        "potencial": len([r for r in rows if r["badge"] == "Potencial"]),
        "atencao": len([r for r in rows if r["badge"] == "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"])
    }
    
    # Insights
    insights = {}
    if rows:
        insights["best"] = {"name": rows[0]["name"], "detail": f"Score {rows[0]['score']:.1f}"}
        improved = max(rows, key=lambda x: float(x["trend_label"].replace("ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬Ëœ +", "").replace("ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬Å“ ", "").replace("ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ EstÃƒÆ’Ã‚Â¡vel", "0").replace("%", "") or 0), default=None)
        if improved:
            insights["improved"] = {"name": improved["name"], "detail": improved["trend_label"]}
        best_presence = max(rows, key=lambda x: x["regularity_adjusted"], default=None)
        if best_presence:
            insights["presence"] = {"name": best_presence["name"], "detail": f"{best_presence['regularity_adjusted']*100:.0f}% presenÃƒÆ’Ã‚Â§a"}
        most_consistent = min(rows, key=lambda x: x["cv"], default=None)
        if most_consistent:
            insights["consistent"] = {"name": most_consistent["name"], "detail": f"CV {most_consistent['cv']:.2f}"}
    
    # Lista de atenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
    attention_list = [r for r in rows if r["badge"] == "AtenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"]
    
    return templates.TemplateResponse(
        "rankings_report_pdf.html",
        {
            "request": request,
            "rows": rows,
            "team_stats": team_stats,
            "badge_counts": badge_counts,
            "insights": insights,
            "attention_list": attention_list,
            "filters": {"shift": shift, "period": period, "date": date},
            "period_label": period_label,
            "period_range_label": period_range_label,
            "generated_at": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M"),
            "ai_report": None  # Pode ser preenchido se houver relatÃƒÆ’Ã‚Â³rio IA em cache
        }
    )


@app.get("/operations/performance/analysis", response_class=HTMLResponse)
async def operations_performance_analysis_report(
    request: Request,
    date: Optional[str] = None,
    period: str = "weekly",
    shift: str = "Todos",
    limit: int = 20,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """
    RelatÃƒÆ’Ã‚Â³rio completo de anÃƒÆ’Ã‚Â¡lise de performance operacional.
    Inclui: faltas, atestados, advertÃƒÆ’Ã‚Âªncias, demora em conclusÃƒÆ’Ã‚Â£o, grÃƒÆ’Ã‚Â¡ficos comparativos.
    Filtros: diÃƒÆ’Ã‚Â¡rio, semanal, mensal.
    """
    from zoneinfo import ZoneInfo
    
    # Parsear data
    target_date = safe_parse_iso_date(date) if date else datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    start_date, end_date = get_period_range(target_date, period)
    total_days = (end_date - start_date).days + 1
    
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    
    # Labels do perÃƒÆ’Ã‚Â­odo
    period_label_map = {'daily': 'DiÃƒÆ’Ã‚Â¡rio', 'weekly': 'Semanal', 'monthly': 'Mensal'}
    period_label = period_label_map.get(period, period)
    period_range_label = f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
    
    # Buscar colaboradores ativos COM acesso ao App de SeparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
    employees_query = (
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .where(models.Employee.replaced_by.is_(None))
        .where(models.Employee.mobile_access_separation == True)
    )
    if shift and shift not in ["Todos", "Geral", None]:
        employees_query = employees_query.where(models.Employee.work_shift == shift)
    
    employees = session.exec(employees_query).all()
    total_headcount = len(employees)
    employee_ids = {e.id for e in employees}
    emp_map = {e.id: e for e in employees}
    
    # --- Buscar Rotinas (faltas, atestados) ---
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date >= start_date.strftime("%Y-%m-%d"))
        .where(models.EmployeeRoutine.date <= end_date.strftime("%Y-%m-%d"))
    ).all()
    
    routines = [r for r in routines if r.employee_id in employee_ids]
    
    # Agrupar por dia ÃƒÆ’Ã‚Âºnico para evitar contagem duplicada
    unique_days = {}
    for r in routines:
        key = (r.employee_id, str(r.date))
        r_type = r.routine
        if r_type in ['absent', 'falta']:
            normalized = 'falta'
        elif r_type in ['sick', 'atestado']:
            normalized = 'atestado'
        elif r_type in ['away', 'afastado']:
            normalized = 'afastamento'
        else:
            continue
        
        if key not in unique_days:
            unique_days[key] = normalized
        else:
            priority = {'falta': 3, 'atestado': 2, 'afastamento': 1}
            if priority.get(normalized, 0) > priority.get(unique_days[key], 0):
                unique_days[key] = normalized
    
    # Contadores gerais
    total_absences = sum(1 for v in unique_days.values() if v == 'falta')
    total_sick = sum(1 for v in unique_days.values() if v == 'atestado')
    
    # --- Buscar AdvertÃƒÆ’Ã‚Âªncias (da tabela Event) ---
    warnings_query = (
        select(models.Event)
        .where(models.Event.timestamp >= start_dt)
        .where(models.Event.timestamp <= end_dt)
        .where(models.Event.type == 'advertencia')
    )
    warnings = session.exec(warnings_query).all()
    warnings = [w for w in warnings if w.employee_id in employee_ids]
    total_warnings = len(warnings)
    
    # --- Buscar Tarefas para calcular demora ---
    # Usando OperationalTaskExecution para medir tempo de conclusÃƒÆ’Ã‚Â£o
    task_executions = session.exec(
        select(models.OperationalTaskExecution)
        .where(models.OperationalTaskExecution.scheduled_date >= start_date.strftime("%Y-%m-%d"))
        .where(models.OperationalTaskExecution.scheduled_date <= end_date.strftime("%Y-%m-%d"))
        .where(models.OperationalTaskExecution.status == 'completed')
    ).all()
    
    # Calcular demora por colaborador
    delay_by_employee = {}
    for exec in task_executions:
        if exec.user_id and exec.started_at and exec.completed_at:
            # Tempo de execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o em minutos
            duration = (exec.completed_at - exec.started_at).total_seconds() / 60
            if exec.user_id not in delay_by_employee:
                delay_by_employee[exec.user_id] = []
            delay_by_employee[exec.user_id].append(duration)
    
    # --- Buscar Rotas para calcular kg/h ---
    def parse_time_value(value):
        if value is None:
            return None
        if isinstance(value, time):
            return value
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, str):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(value.strip(), fmt).time()
                except Exception:
                    continue
        return None
    
    def duration_seconds(start_val, end_val) -> float:
        start_time = parse_time_value(start_val)
        end_time = parse_time_value(end_val)
        if not start_time or not end_time:
            return 0.0
        start_dt_local = datetime.combine(datetime.now().date(), start_time)
        end_dt_local = datetime.combine(datetime.now().date(), end_time)
        if end_dt_local < start_dt_local:
            end_dt_local += timedelta(days=1)
        return max(0.0, (end_dt_local - start_dt_local).total_seconds())
    
    routes_query = (
        select(models.Route)
        .where(models.Route.tonnage > 0)
        .where(models.Route.date >= start_date.strftime("%Y-%m-%d"))
        .where(models.Route.date <= end_date.strftime("%Y-%m-%d"))
    )
    if shift and shift not in ["Todos", "Geral", None]:
        routes_query = routes_query.where(models.Route.shift == shift)
    
    routes = session.exec(routes_query).all()
    
    # Calcular kg/h por colaborador
    route_stats_by_employee = {}
    for route in routes:
        if not route.employee_id:
            continue
        tonnage = float(route.tonnage or 0)
        if tonnage <= 0:
            continue
        
        diff = duration_seconds(route.start_time, route.end_time)
        hours = diff / 3600 if diff > 0 else 0
        
        if route.employee_id not in route_stats_by_employee:
            route_stats_by_employee[route.employee_id] = {
                'total_tonnage': 0.0,
                'total_hours': 0.0,
                'route_count': 0
            }
        
        route_stats_by_employee[route.employee_id]['total_tonnage'] += tonnage
        route_stats_by_employee[route.employee_id]['total_hours'] += hours
        route_stats_by_employee[route.employee_id]['route_count'] += 1
    
    # --- Calcular estatÃƒÆ’Ã‚Â­sticas por colaborador ---
    emp_stats = {}
    for emp in employees:
        emp_stats[emp.id] = {
            'employee_id': emp.id,
            'name': emp.name,
            'sector': emp.cost_center or "Geral",
            'falta': 0,
            'atestado': 0,
            'advertencia': 0,
            'afastamento': 0,
            'avg_delay': 0,
            'tenure_months': 0,
            'expected_work_days': 0,
            'actual_work_days': 0,
            'utilization_rate': 0,
            'risk_score': 0,
            'kgh': 0.0,
            'total_tonnage': 0.0,
            'route_count': 0
        }
        if emp.admission_date:
            delta = datetime.now(ZoneInfo("America/Sao_Paulo")) - emp.admission_date.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
            emp_stats[emp.id]['tenure_months'] = int(delta.days / 30)
        
        # Adicionar dados de rotas
        if emp.id in route_stats_by_employee:
            rs = route_stats_by_employee[emp.id]
            emp_stats[emp.id]['total_tonnage'] = round(rs['total_tonnage'], 1)
            emp_stats[emp.id]['route_count'] = rs['route_count']
            if rs['total_hours'] > 0:
                emp_stats[emp.id]['kgh'] = round(rs['total_tonnage'] / rs['total_hours'], 1)
    
    # Contar dias ÃƒÆ’Ã‚Âºnicos por colaborador
    for (emp_id, day), routine_type in unique_days.items():
        if emp_id in emp_stats:
            emp_stats[emp_id][routine_type] += 1
    
    # Contar advertÃƒÆ’Ã‚Âªncias por colaborador
    for w in warnings:
        if w.employee_id in emp_stats:
            emp_stats[w.employee_id]['advertencia'] += 1
    
    # Calcular demora mÃƒÆ’Ã‚Â©dia por colaborador
    for emp_id, delays in delay_by_employee.items():
        if emp_id in emp_stats and delays:
            emp_stats[emp_id]['avg_delay'] = round(sum(delays) / len(delays), 1)
    
    # --- Calcular dias esperados e taxa de aproveitamento ---
    for emp_id, stats in emp_stats.items():
        emp = emp_map.get(emp_id)
        if emp:
            calc_start = start_dt
            if emp.admission_date:
                try:
                    admission_dt = emp.admission_date.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
                    if admission_dt > start_dt:
                        calc_start = admission_dt
                except:
                    pass
            
            expected_days = calculate_expected_work_days(
                emp.work_days or '[]',
                calc_start.replace(tzinfo=None),
                end_dt.replace(tzinfo=None),
                vacation_start=emp.vacation_start,
                vacation_end=emp.vacation_end
            )
            
            stats['expected_work_days'] = expected_days
            combined_events = stats['falta'] + stats['atestado']
            stats['actual_work_days'] = max(0, expected_days - combined_events)
            stats['utilization_rate'] = round(
                (stats['actual_work_days'] / stats['expected_work_days']) * 100, 1
            ) if stats['expected_work_days'] > 0 else 100
            
            # Score de risco: quanto maior, pior o colaborador
            # Peso: falta (3), atestado (2), advertÃƒÆ’Ã‚Âªncia (4), demora (1 por 10min)
            risk_score = (stats['falta'] * 3) + (stats['atestado'] * 2) + (stats['advertencia'] * 4) + (stats['avg_delay'] / 10)
            stats['risk_score'] = round(risk_score, 1)
    
    # --- Ordenar por score de risco (pior primeiro) ---
    employees_ranking = sorted(emp_stats.values(), key=lambda x: x['risk_score'], reverse=True)
    
    # Aplicar limite
    if limit and limit < len(employees_ranking):
        employees_ranking = employees_ranking[:limit]
    
    # --- Calcular estatÃƒÆ’Ã‚Â­sticas por setor ---
    sector_stats = {}
    for stats in emp_stats.values():
        sec = stats['sector']
        if sec not in sector_stats:
            sector_stats[sec] = {'name': sec, 'falta': 0, 'atestado': 0, 'advertencia': 0, 'headcount': 0}
        sector_stats[sec]['falta'] += stats['falta']
        sector_stats[sec]['atestado'] += stats['atestado']
        sector_stats[sec]['advertencia'] += stats['advertencia']
        sector_stats[sec]['headcount'] += 1
    
    sectors = []
    for sec, data in sector_stats.items():
        if data['headcount'] > 0:
            data['risk_index'] = round((data['falta'] + data['atestado'] + data['advertencia']) / data['headcount'], 2)
            sectors.append(data)
    
    sectors.sort(key=lambda x: x['risk_index'], reverse=True)
    
    # --- Recalcular totais de ausÃƒÆ’Ã‚Âªncias dos emp_stats (garantir consistÃƒÆ’Ã‚Âªncia) ---
    total_absences = sum(s['falta'] for s in emp_stats.values())
    total_sick = sum(s['atestado'] for s in emp_stats.values())
    total_warnings = sum(s['advertencia'] for s in emp_stats.values())
    
    # --- Calcular taxa de presenÃƒÆ’Ã‚Â§a ---
    total_expected = sum(s['expected_work_days'] for s in emp_stats.values())
    total_events = total_absences + total_sick
    presence_rate = round((1 - (total_events / max(1, total_expected))) * 100, 1) if total_expected > 0 else 100
    
    # Contar colaboradores crÃƒÆ’Ã‚Â­ticos (score >= 10)
    critical_count = len([e for e in emp_stats.values() if e['risk_score'] >= 10])
    
    # --- Preparar dados para grÃƒÆ’Ã‚Â¡ficos ---
    top_10_worst = employees_ranking[:10]
    
    # Ranking de kg/h (apenas colaboradores com rotas, ordenado por kg/h)
    employees_with_routes = [e for e in emp_stats.values() if e['route_count'] > 0]
    employees_kgh_ranking = sorted(employees_with_routes, key=lambda x: x['kgh'], reverse=True)
    
    chart_data = {
        'worst_employees': {
            'labels': [e['name'][:15] for e in top_10_worst],
            'faltas': [e['falta'] for e in top_10_worst],
            'atestados': [e['atestado'] for e in top_10_worst],
            'advertencias': [e['advertencia'] for e in top_10_worst]
        },
        'distribution': {
            'faltas': total_absences,
            'atestados': total_sick,
            'advertencias': total_warnings
        },
        'all_employees': {
            'labels': [e['name'][:12] for e in employees_ranking[:20]],
            'faltas': [e['falta'] for e in employees_ranking[:20]],
            'atestados': [e['atestado'] for e in employees_ranking[:20]],
            'advertencias': [e['advertencia'] for e in employees_ranking[:20]]
        },
        'kgh_ranking': {
            'labels': [e['name'][:15] for e in employees_kgh_ranking],
            'kgh': [e['kgh'] for e in employees_kgh_ranking],
            'tonnage': [e['total_tonnage'] for e in employees_kgh_ranking],
            'routes': [e['route_count'] for e in employees_kgh_ranking]
        }
    }
    
    # Calcular mÃƒÆ’Ã‚Â©dia de kg/h para referÃƒÆ’Ã‚Âªncia
    avg_kgh = round(sum(e['kgh'] for e in employees_kgh_ranking) / len(employees_kgh_ranking), 1) if employees_kgh_ranking else 0
    
    # --- ANÃƒÆ’Ã‚ÂLISE DE CORRELAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O E IMPACTO ---
    
    # 1. CorrelaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o: AusÃƒÆ’Ã‚Âªncias vs Produtividade
    # Separar colaboradores em grupos: com ausÃƒÆ’Ã‚Âªncias vs sem ausÃƒÆ’Ã‚Âªncias
    employees_with_absences = [e for e in employees_with_routes if (e['falta'] + e['atestado']) > 0]
    employees_without_absences = [e for e in employees_with_routes if (e['falta'] + e['atestado']) == 0]
    
    avg_kgh_with_absences = round(sum(e['kgh'] for e in employees_with_absences) / len(employees_with_absences), 1) if employees_with_absences else 0
    avg_kgh_without_absences = round(sum(e['kgh'] for e in employees_without_absences) / len(employees_without_absences), 1) if employees_without_absences else 0
    
    # DiferenÃƒÆ’Ã‚Â§a percentual de produtividade
    productivity_diff = round(((avg_kgh_without_absences - avg_kgh_with_absences) / avg_kgh_with_absences) * 100, 1) if avg_kgh_with_absences > 0 else 0
    
    # 2. AnÃƒÆ’Ã‚Â¡lise de MÃƒÆ’Ã‚Â£o de Obra Perdida
    # Cada ausÃƒÆ’Ã‚Âªncia = 1 dia de trabalho perdido (assumindo 8h/dia)
    total_man_days_lost = total_absences + total_sick
    total_man_hours_lost = total_man_days_lost * 8  # 8 horas por dia
    
    # Estimativa de tonelagem perdida (usando mÃƒÆ’Ã‚Â©dia de kg/h)
    estimated_tonnage_lost = round((avg_kgh * total_man_hours_lost) / 1000, 2)  # em toneladas
    
    # 3. Taxa de AbsenteÃƒÆ’Ã‚Â­smo
    absenteeism_rate = round((total_man_days_lost / max(1, total_expected)) * 100, 2)
    
    # 4. AnÃƒÆ’Ã‚Â¡lise por Dia (agrupar rotas e ausÃƒÆ’Ã‚Âªncias por data)
    routes_by_date = {}
    for route in routes:
        date_key = str(route.date)
        if date_key not in routes_by_date:
            routes_by_date[date_key] = {'tonnage': 0, 'hours': 0, 'count': 0}
        tonnage = float(route.tonnage or 0)
        diff = duration_seconds(route.start_time, route.end_time)
        hours = diff / 3600 if diff > 0 else 0
        routes_by_date[date_key]['tonnage'] += tonnage
        routes_by_date[date_key]['hours'] += hours
        routes_by_date[date_key]['count'] += 1
    
    absences_by_date = {}
    for (emp_id, day), routine_type in unique_days.items():
        if day not in absences_by_date:
            absences_by_date[day] = {'falta': 0, 'atestado': 0, 'total': 0}
        absences_by_date[day][routine_type] += 1
        absences_by_date[day]['total'] += 1
    
    # Calcular produtividade por dia - TODOS os dias do perÃƒÆ’Ã‚Â­odo (nÃƒÆ’Ã‚Â£o sÃƒÆ’Ã‚Â³ os com rotas)
    daily_analysis = []
    current_day = start_date
    while current_day <= end_date:
        date_key = current_day.strftime("%Y-%m-%d")
        route_data = routes_by_date.get(date_key, {'tonnage': 0, 'hours': 0, 'count': 0})
        absence_data = absences_by_date.get(date_key, {'falta': 0, 'atestado': 0, 'total': 0})
        kgh = round(route_data['tonnage'] / route_data['hours'], 1) if route_data['hours'] > 0 else 0
        daily_analysis.append({
            'date': date_key,
            'date_formatted': current_day.strftime("%d/%m"),
            'kgh': kgh,
            'tonnage': round(route_data['tonnage'], 1),
            'routes': route_data['count'],
            'absences': absence_data['total'],
            'faltas': absence_data['falta'],
            'atestados': absence_data['atestado'],
            'workforce_available': total_headcount - absence_data['total']
        })
        current_day += timedelta(days=1)
    
    # 5. Calcular correlaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o estatÃƒÆ’Ã‚Â­stica (Pearson simplificado)
    if len(daily_analysis) >= 3:
        absences_list = [d['absences'] for d in daily_analysis]
        kgh_list = [d['kgh'] for d in daily_analysis]
        
        # MÃƒÆ’Ã‚Â©dia
        mean_abs = sum(absences_list) / len(absences_list)
        mean_kgh = sum(kgh_list) / len(kgh_list)
        
        # CovariÃƒÆ’Ã‚Â¢ncia e desvios
        numerator = sum((a - mean_abs) * (k - mean_kgh) for a, k in zip(absences_list, kgh_list))
        denom_abs = sum((a - mean_abs) ** 2 for a in absences_list) ** 0.5
        denom_kgh = sum((k - mean_kgh) ** 2 for k in kgh_list) ** 0.5
        
        correlation = round(numerator / (denom_abs * denom_kgh), 2) if (denom_abs * denom_kgh) > 0 else 0
    else:
        correlation = 0
    
    # 6. Identificar dias crÃƒÆ’Ã‚Â­ticos (alta ausÃƒÆ’Ã‚Âªncia + baixa produtividade)
    critical_days = [d for d in daily_analysis if d['absences'] >= 2 and d['kgh'] < avg_kgh]
    
    # 7. DiagnÃƒÆ’Ã‚Â³stico automÃƒÆ’Ã‚Â¡tico
    diagnostics = []
    
    if absenteeism_rate > 10:
        diagnostics.append({
            'type': 'critical',
            'icon': 'ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨',
            'title': 'Taxa de AbsenteÃƒÆ’Ã‚Â­smo CrÃƒÆ’Ã‚Â­tica',
            'description': f'Taxa de {absenteeism_rate}% estÃƒÆ’Ã‚Â¡ muito acima do aceitÃƒÆ’Ã‚Â¡vel (5%). Impacto direto na operaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o.',
            'impact': f'{total_man_hours_lost}h de trabalho perdidas'
        })
    elif absenteeism_rate > 5:
        diagnostics.append({
            'type': 'warning',
            'icon': 'ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â',
            'title': 'Taxa de AbsenteÃƒÆ’Ã‚Â­smo Elevada',
            'description': f'Taxa de {absenteeism_rate}% requer atenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o. Meta: abaixo de 5%.',
            'impact': f'{total_man_hours_lost}h de trabalho perdidas'
        })
    
    if correlation < -0.3:
        diagnostics.append({
            'type': 'critical',
            'icon': 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â°',
            'title': 'CorrelaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o Negativa Comprovada',
            'description': f'CorrelaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de {correlation} entre ausÃƒÆ’Ã‚Âªncias e produtividade. Mais ausÃƒÆ’Ã‚Âªncias = MENOR produtividade.',
            'impact': f'Queda de {productivity_diff}% na produtividade de quem falta'
        })
    
    if len(employees_with_absences) > len(employees_without_absences) * 0.5:
        diagnostics.append({
            'type': 'warning',
            'icon': 'ÃƒÂ°Ã…Â¸Ã¢â‚¬ËœÃ‚Â¥',
            'title': 'Problema Generalizado de AusÃƒÆ’Ã‚Âªncias',
            'description': f'{len(employees_with_absences)} de {len(employees_with_routes)} colaboradores com rotas tiveram ausÃƒÆ’Ã‚Âªncias no perÃƒÆ’Ã‚Â­odo.',
            'impact': 'Afeta mais da metade da equipe operacional'
        })
    
    if estimated_tonnage_lost > 10:
        diagnostics.append({
            'type': 'critical',
            'icon': 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â¦',
            'title': 'Perda Significativa de Tonelagem',
            'description': f'Estimativa de {estimated_tonnage_lost} toneladas deixaram de ser movimentadas.',
            'impact': 'Perda de produÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o por falta de mÃƒÆ’Ã‚Â£o de obra'
        })
    
    if len(critical_days) > 0:
        diagnostics.append({
            'type': 'warning',
            'icon': 'ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¦',
            'title': f'{len(critical_days)} Dias CrÃƒÆ’Ã‚Â­ticos Identificados',
            'description': 'Dias com alta ausÃƒÆ’Ã‚Âªncia e produtividade abaixo da mÃƒÆ’Ã‚Â©dia.',
            'impact': ', '.join([d['date_formatted'] for d in critical_days[:5]])
        })
    
    if avg_kgh_with_absences < avg_kgh_without_absences:
        diagnostics.append({
            'type': 'info',
            'icon': 'ÃƒÂ°Ã…Â¸Ã¢â‚¬â„¢Ã‚Â¡',
            'title': 'EvidÃƒÆ’Ã‚Âªncia de Impacto nas AusÃƒÆ’Ã‚Âªncias',
            'description': f'Colaboradores sem ausÃƒÆ’Ã‚Âªncias produzem {avg_kgh_without_absences} kg/h vs {avg_kgh_with_absences} kg/h dos que faltam.',
            'impact': f'DiferenÃƒÆ’Ã‚Â§a de {productivity_diff}% na produtividade'
        })
    
    # Adicionar dados de correlaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o ao chart_data
    chart_data['correlation'] = {
        'with_absences': {
            'label': 'Com AusÃƒÆ’Ã‚Âªncias',
            'kgh': avg_kgh_with_absences,
            'count': len(employees_with_absences)
        },
        'without_absences': {
            'label': 'Sem AusÃƒÆ’Ã‚Âªncias',
            'kgh': avg_kgh_without_absences,
            'count': len(employees_without_absences)
        }
    }
    
    chart_data['daily_analysis'] = {
        'labels': [d['date_formatted'] for d in daily_analysis],
        'kgh': [d['kgh'] for d in daily_analysis],
        'absences': [d['absences'] for d in daily_analysis],
        'workforce': [d['workforce_available'] for d in daily_analysis],
        'tonnage': [d['tonnage'] for d in daily_analysis]
    }
    
    # Dados para scatter plot de correlaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o individual
    chart_data['scatter_correlation'] = {
        'data': [
            {'x': e['falta'] + e['atestado'], 'y': e['kgh'], 'name': e['name'][:15]}
            for e in employees_with_routes
        ]
    }
    
    # --- Overview ---
    overview = {
        'headcount': total_headcount,
        'total_absences': total_absences,
        'total_sick': total_sick,
        'total_warnings': total_warnings,
        'presence_rate': presence_rate,
        'critical_count': critical_count,
        'avg_kgh': avg_kgh,
        'total_routes': sum(e['route_count'] for e in employees_kgh_ranking),
        'employees_with_routes': len(employees_kgh_ranking),
        # Novos indicadores de impacto
        'absenteeism_rate': absenteeism_rate,
        'man_days_lost': total_man_days_lost,
        'man_hours_lost': total_man_hours_lost,
        'estimated_tonnage_lost': estimated_tonnage_lost,
        'correlation': correlation,
        'avg_kgh_with_absences': avg_kgh_with_absences,
        'avg_kgh_without_absences': avg_kgh_without_absences,
        'productivity_diff': productivity_diff,
        'employees_with_absences': len(employees_with_absences),
        'employees_without_absences': len(employees_without_absences),
        'critical_days_count': len(critical_days)
    }
    
    # AnÃƒÆ’Ã‚Â¡lise de impacto
    impact_analysis = {
        'diagnostics': diagnostics,
        'critical_days': critical_days,
        'daily_analysis': daily_analysis
    }
    
    return templates.TemplateResponse(
        "operations_performance_report.html",
        {
            "request": request,
            "user": user,
            "overview": overview,
            "employees_ranking": employees_ranking,
            "sectors": sectors,
            "chart_data": chart_data,
            "impact_analysis": impact_analysis,
            "period": period,
            "period_label": period_label,
            "period_range_label": period_range_label,
            "shift": shift,
            "date": date or target_date.strftime("%Y-%m-%d"),
            "limit": limit,
            "generated_at": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
        }
    )


# --- Smart Flow Routes ---
@app.get("/smart-flow", response_class=HTMLResponse)
async def smart_flow_page(request: Request, shift: str = "ManhÃƒÆ’Ã‚Â£", date: Optional[str] = None, session: Session = Depends(get_session)):
    try:
        user = require_login(request)
        # Get Employees for "Available Pool" (Active, Sick, Vacation, Away - Everyone except Fired)
        # Auto-Update Vacation Status Check
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
        if date:
            try:
                update_vacation_statuses(session, datetime.strptime(date, "%Y-%m-%d"))
            except Exception as e:
                print(f"Error checking vacation dates: {e}")
                
        employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
        emp_map = {e.registration_id: e for e in employees}
        
        # Get Daily Op
        if not date:
            date = get_effective_shift_date(shift, now_br).strftime("%Y-%m-%d")
        else:
            date = normalize_shift_date(date, shift, now_br)
            
        daily_op = session.exec(
            select(models.DailyOperation)
            .where(models.DailyOperation.date == date)
            .where(models.DailyOperation.shift == shift)
        ).first()
        if not daily_op:
            # Logic: Smart Copy from Last Operation
            last_op = session.exec(
                select(models.DailyOperation)
                .where(models.DailyOperation.shift == shift)
                .where(models.DailyOperation.date < date)
                .order_by(models.DailyOperation.date.desc())
            ).first()
            
            initial_log = {}
            if last_op and last_op.attendance_log:
                for reg_id, entry in last_op.attendance_log.items():
                    # Only copy if employee is still active
                    if reg_id in emp_map:
                        emp_record = emp_map[reg_id]
                        # Reset daily status to 'present' ONLY if their permanent status is active.
                        new_entry = entry.copy()
                        
                        if emp_record.status == 'vacation':
                            new_entry['status'] = 'vacation'
                        elif emp_record.status == 'sick':
                            new_entry['status'] = 'sick'
                        elif emp_record.status == 'away':
                            new_entry['status'] = 'away'
                        else:
                            new_entry['status'] = 'present'
                            
                        initial_log[reg_id] = new_entry
                        
            daily_op = models.DailyOperation(date=date, shift=shift, attendance_log=initial_log) # Transient

        def _default_attendance_status(emp_status: Optional[str]) -> str:
            normalized = (emp_status or '').lower()
            if normalized in {'vacation', 'fÃƒÆ’Ã‚Â©rias', 'ferias'}:
                return 'vacation'
            if normalized in {'sick', 'atestado'}:
                return 'sick'
            if normalized in {'away', 'afastado'}:
                return 'away'
            if normalized in {'dayoff', 'folga'}:
                return 'dayoff'
            return 'present'

        def _fill_default_log_entries(log: dict):
            for emp in employees:
                registration_id = emp.registration_id
                if registration_id is None:
                    continue
                key = str(registration_id)
                if key in log:
                    continue
                log[key] = {
                    "status": _default_attendance_status(emp.status),
                    "sector": None,
                    "sector_name": None,
                    "subsector_name": None,
                    "activity": None,
                    "observation": None
                }

        attendance_log_snapshot = dict(daily_op.attendance_log or {})
        _fill_default_log_entries(attendance_log_snapshot)
        daily_op.attendance_log = attendance_log_snapshot

        # Get Targets (Headcount) - Official HR Target
        targets_db = session.exec(select(models.HeadcountTarget).where(models.HeadcountTarget.shift_name == shift)).first()
        shift_target_hr = targets_db.target_value if targets_db else 0
        
        # Get Sector Configuration
        sector_config_db = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == shift)).first()
        
        sector_config = {}
        if sector_config_db and sector_config_db.config_json:
            sector_config = sector_config_db.config_json
            if isinstance(sector_config, str):
                try:
                    sector_config = json.loads(sector_config)
                except:
                    sector_config = {}
        
        if not sector_config or not isinstance(sector_config, dict) or "sectors" not in sector_config:
            # Default Seed (Targets initialized to 0 to avoid confusion with HR Target)
            sector_config = {
                "sectors": [
                    { "key": "recebimento", "label": "Recebimento", "target": 0, "subsectors": ["Doca 1", "Doca 2", "PaletizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"] },
                    { "key": "camara_fria", "label": "CÃƒÆ’Ã‚Â¢mara Fria", "target": 0, "subsectors": ["Armazenagem", "Abastecimento"] },
                    { "key": "selecao", "label": "SeleÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "target": 0, "subsectors": ["Linha 1", "Linha 2"] },
                    { "key": "expedicao", "label": "ExpediÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "target": 0, "subsectors": ["SeparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "Carregamento"] }
                ]
            }
    
        # Calculate Total Target from Config (Operational Demand)
        sectors_total_demand = sum(s.get("target", 0) for s in sector_config.get("sectors", []) if isinstance(s, dict))
        # Calculate Real Tonnage from Routes
        routes_in_shift = session.exec(
            select(models.Route)
            .where(models.Route.date == date)
            .where(models.Route.shift == shift)
        ).all()
        total_tonnage_real = sum(r.tonnage for r in routes_in_shift if r.tonnage)
        if daily_op.tonnage and daily_op.tonnage > 0:
            total_tonnage_real = daily_op.tonnage
            
        # Format Tonnage
        def fmt_num(n):
            val = n if n is not None else 0.0
            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
        today_date = now_br.date()
        reg_map = {
            str(e.registration_id): e
            for e in employees
            if e.registration_id is not None
        }

        def first_last(full_name: Optional[str]) -> str:
            if not full_name:
                return "Colaborador"
            parts = [p for p in full_name.strip().split() if p]
            if len(parts) >= 2:
                return f"{parts[0]} {parts[-1]}"
            return parts[0]

        status_labels = {
            "absent": "Falta",
            "sick": "Atestado",
            "away": "Afastado"
        }

        log_entries = daily_op.attendance_log or {}
        absence_entries: List[dict] = []
        for reg_id, entry in log_entries.items():
            status = (entry.get("status") or "").lower()
            if status not in {"absent", "sick", "away"}:
                continue
            emp = reg_map.get(str(reg_id))
            if not emp:
                continue
            shift_label = entry.get("shift") or emp.work_shift or shift or "-"
            absence_entries.append({
                "name": first_last(emp.name),
                "shift": shift_label,
                "status_label": status_labels.get(status, status.title()),
                "status": status
            })

        upcoming_vacations: List[dict] = []
        active_vacations: List[dict] = []
        for emp in employees:
            if not emp.vacation_start or not emp.vacation_end:
                continue
            try:
                v_start_date = emp.vacation_start.date()
                v_end_date = emp.vacation_end.date()
            except Exception:
                continue

            shift_label = emp.work_shift or getattr(emp, "shift", None) or "-"
            if v_start_date > today_date:
                days_until = (v_start_date - today_date).days
                upcoming_vacations.append({
                    "name": first_last(emp.name),
                    "shift": shift_label,
                    "start_in": f"{days_until}d" if days_until > 0 else "Hoje",
                    "start_date": v_start_date.strftime("%d/%m"),
                    "days_until": days_until
                })
            elif v_start_date <= today_date <= v_end_date:
                days_left = (v_end_date - today_date).days + 1
                active_vacations.append({
                    "name": first_last(emp.name),
                    "shift": shift_label,
                    "end_date": v_end_date.strftime("%d/%m"),
                    "days_left": f"{days_left}d",
                    "days_left_count": days_left
                })

        upcoming_vacations.sort(key=lambda x: x["days_until"])
        active_vacations.sort(key=lambda x: x["days_left_count"])

        absence_preview = absence_entries[:5]
        absence_more = max(0, len(absence_entries) - len(absence_preview))
        upcoming_preview = upcoming_vacations[:5]
        upcoming_more = max(0, len(upcoming_vacations) - len(upcoming_preview))
        active_preview = active_vacations[:5]
        active_more = max(0, len(active_vacations) - len(active_preview))

        # Get employees who are substituted (for Dashboard "SubstituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o" KPI)
        # Logic: Events where text contains "SubstituÃƒÆ’Ã‚Â­do por"
        sub_events = session.exec(select(models.Event).where(col(models.Event.text).contains("SubstituÃƒÆ’Ã‚Â­do por"))).all()
        substituted_ids = {e.employee_id for e in sub_events}

        return templates.TemplateResponse("smart_flow.html", {
            "request": request,
            "user": user,
            "daily_op": daily_op,
            "employees_list": employees,
            "current_shift": shift,
            "current_date": date,
            "total_target": sectors_total_demand, 
            "shift_target_hr": shift_target_hr, # Passed for KPI
            "sector_config": sector_config,
            "total_tonnage_fmt": fmt_num(total_tonnage_real),
            "total_tonnage_raw": total_tonnage_real, # Raw for JS calc
            "manual_tonnage": daily_op.tonnage or 0, # Pass raw manual value for frontend to know
            "substituted_ids": list(substituted_ids),
            "absence_alerts": absence_preview,
            "absence_more": absence_more,
            "absence_total": len(absence_entries),
            "vacations_upcoming": upcoming_preview,
            "vacations_upcoming_more": upcoming_more,
            "vacations_upcoming_count": len(upcoming_vacations),
            "vacations_active": active_preview,
            "vacations_active_more": active_more,
            "vacations_active_count": len(active_vacations),
            # JSON data for JavaScript modules
            "employees_json": json.dumps(daily_op.attendance_log or {}),
            "config_json": json.dumps(sector_config),
            "all_employees_json": json.dumps([{
                "id": e.registration_id,
                "name": e.name,
                "role": e.role,
                "shift": e.work_shift,
                "cost_center": e.cost_center,
                "status": e.status,
                "birthday": e.birthday.isoformat() if e.birthday else None,
                "admission_date": e.admission_date.isoformat() if e.admission_date else None,
                "is_substituted": e.registration_id in substituted_ids,
                "mobile_access": e.mobile_access, # IMPORTANT for Sector Management
                "db_id": e.id
            } for e in employees])
        })
    except Exception as e:
        logger.exception("Error in smart_flow_page")
        raise e
    # Valid return is above
@app.post("/employees/vacation", response_class=JSONResponse)
async def schedule_vacation(
    request: Request,
    data: VacationSchedule,
    session: Session = Depends(get_session)
):
    require_login(request)
    emp = session.exec(select(models.Employee).where(models.Employee.registration_id == data.registration_id)).first()
    if not emp:
        return JSONResponse({"error": "Employee not found"}, status_code=404)
    try:
        # Parse YYYY-MM-DD
        emp.vacation_start = datetime.strptime(data.start_date, "%Y-%m-%d")
        emp.vacation_end = datetime.strptime(data.end_date, "%Y-%m-%d")
        
        # Immediate check
        today = datetime.now()
        v_start = emp.vacation_start.replace(hour=0, minute=0, second=0, microsecond=0)
        v_end = emp.vacation_end.replace(hour=23, minute=59, second=59, microsecond=999)
        
        if v_start <= today <= v_end:
            emp.status = 'vacation'
        else:
            if emp.status == 'vacation':
                emp.status = 'active'
                
        # LOG EVENT (New)
        # Format dates to BR
        fmt_start = datetime.strptime(data.start_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        fmt_end = datetime.strptime(data.end_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        
        evt_text = f"FÃƒÆ’Ã‚Â©rias Agendadas: {fmt_start} a {fmt_end}"
        new_event = models.Event(
            employee_id=emp.id,
            type="ferias_hist",
            text=evt_text,
            timestamp=datetime.now(),
            category="pessoas",
            sector="RH"
        )
        session.add(new_event)
        
        session.add(emp)
        session.commit()
        return JSONResponse({"message": "Vacation scheduled and status updated."})
    except ValueError:
        return JSONResponse({"error": "Invalid date format"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
class BulkVacationItem(BaseModel):
    registration_id: str
    start_date: str
    end_date: str
@app.post("/employees/vacation/bulk", response_class=JSONResponse)
async def bulk_schedule_vacation(
    request: Request,
    items: List[BulkVacationItem],
    session: Session = Depends(get_session)
):
    require_login(request)
    updated_count = 0
    errors = []
    today = datetime.now()
    for item in items:
        # Find by Registration ID
        emp = session.exec(select(models.Employee).where(models.Employee.registration_id == str(item.registration_id))).first()
        if not emp:
            errors.append(f"MatrÃƒÆ’Ã‚Â­cula {item.registration_id} nÃƒÆ’Ã‚Â£o encontrada.")
            continue
            
        try:
            # Flexible Date Parsing? No, frontend should standardize to YYYY-MM-DD
            v_start = datetime.strptime(item.start_date, "%Y-%m-%d")
            v_end = datetime.strptime(item.end_date, "%Y-%m-%d")
            
            emp.vacation_start = v_start
            emp.vacation_end = v_end
            
            # Status Check
            check_start = v_start.replace(hour=0, minute=0, second=0, microsecond=0)
            check_end = v_end.replace(hour=23, minute=59, second=59, microsecond=999)
            
            if check_start <= today <= check_end:
                emp.status = 'vacation'
            else:
                if emp.status == 'vacation':
                    emp.status = 'active'
                    
            # Create History Event
            hist_event = models.Event(
                employee_id=emp.id,
                type="ferias_hist",
                text=f"FÃƒÆ’Ã‚Â©rias Agendadas: {item.start_date} a {item.end_date}",
                category="pessoas",
                sector=emp.cost_center or "Geral",
                timestamp=datetime.now()
            )
            session.add(hist_event)
            
            session.add(emp)
            updated_count += 1
            
        except ValueError:
            errors.append(f"Data invÃƒÆ’Ã‚Â¡lida para matrÃƒÆ’Ã‚Â­cula {item.registration_id}")
        except Exception as e:
            errors.append(f"Erro ao processar matrÃƒÆ’Ã‚Â­cula {item.registration_id}: {str(e)}")

    session.commit()
    msg = f"{updated_count} colaboradores atualizados/agendados."
    if errors:
        msg += f" Erros: {'; '.join(errors)}"
    
    return JSONResponse({"message": msg, "errors": errors})

# --- Medical Certificate Bulk Import ---
@app.post("/api/import-medical-certificates", response_class=JSONResponse)
async def import_medical_certificates(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    """
    Importa atestados mÃƒÆ’Ã‚Â©dicos em lote a partir de planilha Excel/CSV
    
    Formato esperado:
    - Coluna 1: MatrÃƒÆ’Ã‚Â­cula
    - Coluna 2: Data InÃƒÆ’Ã‚Â­cio (YYYY-MM-DD ou DD/MM/YYYY)
    - Coluna 3: Data Fim (YYYY-MM-DD ou DD/MM/YYYY)
    - Coluna 4: ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o (opcional)
    
    Retorna:
    {
        "success_count": int,
        "error_count": int,
        "skipped_count": int,
        "details": List[dict]
    }
    """
    require_login(request)
    
    import uuid
    import io
    import pandas as pd
    
    trace_id = str(uuid.uuid4())[:8]
    logger.info(f"[{trace_id}] Iniciando importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de atestados - arquivo: {file.filename}")
    
    # ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o 1: Tamanho do arquivo (max 5MB)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    contents = await file.read()
    
    if len(contents) > MAX_FILE_SIZE:
        logger.warning(f"[{trace_id}] Arquivo muito grande: {len(contents)} bytes")
        return JSONResponse({
            "error": "Arquivo muito grande. Tamanho mÃƒÆ’Ã‚Â¡ximo: 5MB",
            "trace_id": trace_id
        }, status_code=400)
    
    # ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o 2: Formato do arquivo
    allowed_extensions = ['.xlsx', '.xls', '.csv']
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        logger.warning(f"[{trace_id}] Formato invÃƒÆ’Ã‚Â¡lido: {file_ext}")
        return JSONResponse({
            "error": f"Formato de arquivo invÃƒÆ’Ã‚Â¡lido. Permitidos: {', '.join(allowed_extensions)}",
            "trace_id": trace_id
        }, status_code=400)
    
    # Processar arquivo
    try:
        df = None
        if file_ext == '.csv':
            # Try multiple encodings and delimiters to handle different CSV formats
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'utf-8-sig']:
                for delimiter in [',', ';', '\t']:
                    try:
                        df = pd.read_csv(io.BytesIO(contents), encoding=encoding, delimiter=delimiter)
                        # Check if we got valid columns (more than 1 column means correct delimiter)
                        if len(df.columns) > 1:
                            logger.info(f"[{trace_id}] CSV lido com encoding: {encoding}, delimiter: '{delimiter}'")
                            break
                    except (UnicodeDecodeError, pd.errors.ParserError):
                        continue
                if df is not None and len(df.columns) > 1:
                    break
            
            if df is None or len(df.columns) <= 1:
                raise ValueError("NÃƒÆ’Ã‚Â£o foi possÃƒÆ’Ã‚Â­vel ler o arquivo CSV. Verifique o formato do arquivo.")
        else:
            df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
        
        logger.info(f"[{trace_id}] Arquivo lido com sucesso - {len(df)} linhas, {len(df.columns)} colunas")
        
    except Exception as e:
        logger.exception(f"[{trace_id}] Erro ao ler arquivo")
        return JSONResponse({
            "error": f"Erro ao processar arquivo: {str(e)}",
            "trace_id": trace_id
        }, status_code=400)
    
    # ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o 3: Verificar colunas obrigatÃƒÆ’Ã‚Â³rias
    if df.empty:
        return JSONResponse({
            "error": "Arquivo vazio",
            "trace_id": trace_id
        }, status_code=400)
    
    # Normalizar nomes de colunas (case-insensitive, sem espaÃƒÆ’Ã‚Â§os extras)
    # TambÃƒÆ’Ã‚Â©m substituir underscores por espaÃƒÆ’Ã‚Â§os para normalizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
    df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ')
    
    # Mapear possÃƒÆ’Ã‚Â­veis nomes de colunas (mais flexÃƒÆ’Ã‚Â­vel)
    col_mapping = {}
    for col in df.columns:
        col_clean = col.replace(' ', '').replace('ÃƒÆ’Ã‚Â­', 'i').replace('ÃƒÆ’Ã‚Âº', 'u')
        
        if 'matr' in col_clean or 'matricula' in col_clean:
            col_mapping['matricula'] = col
        elif 'inicio' in col_clean or 'start' in col_clean or 'datainicio' in col_clean:
            col_mapping['data_inicio'] = col
        elif 'fim' in col_clean or 'end' in col_clean or 'datafim' in col_clean or 'termino' in col_clean:
            col_mapping['data_fim'] = col
        elif 'obs' in col_clean or 'observ' in col_clean or 'nota' in col_clean:
            col_mapping['observacao'] = col
    
    required_cols = ['matricula', 'data_inicio', 'data_fim']
    missing_cols = [c for c in required_cols if c not in col_mapping]
    
    if missing_cols:
        # Mensagem de erro mais clara com as colunas encontradas
        found_cols = list(df.columns)
        return JSONResponse({
            "error": f"Colunas obrigatÃƒÆ’Ã‚Â³rias faltando: {', '.join(missing_cols)}. Esperado: MatrÃƒÆ’Ã‚Â­cula, Data InÃƒÆ’Ã‚Â­cio, Data Fim. Encontrado: {', '.join(found_cols)}",
            "trace_id": trace_id
        }, status_code=400)
    
    # Processar cada linha
    tz = ZoneInfo("America/Sao_Paulo")
    success_count = 0
    error_count = 0
    skipped_count = 0
    details = []
    
    for idx, row in df.iterrows():
        row_num = idx + 2  # +2 porque: ÃƒÆ’Ã‚Â­ndice comeÃƒÆ’Ã‚Â§a em 0 + linha de cabeÃƒÆ’Ã‚Â§alho
        
        try:
            # Extrair dados
            matricula = str(row[col_mapping['matricula']]).strip()
            data_inicio_raw = row[col_mapping['data_inicio']]
            data_fim_raw = row[col_mapping['data_fim']]
            observacao = str(row.get(col_mapping.get('observacao', ''), '')).strip() if 'observacao' in col_mapping else ''
            
            # ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o: MatrÃƒÆ’Ã‚Â­cula nÃƒÆ’Ã‚Â£o vazia
            if not matricula or matricula == 'nan':
                details.append({
                    "linha": row_num,
                    "status": "erro",
                    "matricula": matricula,
                    "mensagem": "MatrÃƒÆ’Ã‚Â­cula vazia"
                })
                error_count += 1
                continue
            
            # Buscar colaborador
            emp = session.exec(
                select(models.Employee).where(models.Employee.registration_id == matricula)
            ).first()
            
            if not emp:
                details.append({
                    "linha": row_num,
                    "status": "ignorado",
                    "matricula": matricula,
                    "mensagem": "MatrÃƒÆ’Ã‚Â­cula nÃƒÆ’Ã‚Â£o encontrada no sistema"
                })
                skipped_count += 1
                logger.warning(f"[{trace_id}] Linha {row_num}: MatrÃƒÆ’Ã‚Â­cula {matricula} nÃƒÆ’Ã‚Â£o encontrada")
                continue
            
            # Parsear datas (suporta YYYY-MM-DD e DD/MM/YYYY)
            def parse_date(date_val):
                """Tenta parsear data em mÃƒÆ’Ã‚Âºltiplos formatos"""
                if pd.isna(date_val):
                    return None
                
                # Se jÃƒÆ’Ã‚Â¡ ÃƒÆ’Ã‚Â© datetime do pandas
                if isinstance(date_val, pd.Timestamp):
                    return date_val.to_pydatetime().replace(tzinfo=tz)
                
                # Se ÃƒÆ’Ã‚Â© string
                date_str = str(date_val).strip()
                formats = ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]
                
                for fmt in formats:
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        return dt.replace(tzinfo=tz)
                    except ValueError:
                        continue
                
                return None
            
            data_inicio = parse_date(data_inicio_raw)
            data_fim = parse_date(data_fim_raw)
            
            if not data_inicio or not data_fim:
                details.append({
                    "linha": row_num,
                    "status": "erro",
                    "matricula": matricula,
                    "nome": emp.name,
                    "mensagem": f"Data invÃƒÆ’Ã‚Â¡lida (InÃƒÆ’Ã‚Â­cio: {data_inicio_raw}, Fim: {data_fim_raw})"
                })
                error_count += 1
                logger.warning(f"[{trace_id}] Linha {row_num}: Datas invÃƒÆ’Ã‚Â¡lidas para {emp.name}")
                continue
            
            # ValidaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o: Data fim >= Data inÃƒÆ’Ã‚Â­cio
            if data_fim < data_inicio:
                details.append({
                    "linha": row_num,
                    "status": "erro",
                    "matricula": matricula,
                    "nome": emp.name,
                    "mensagem": "Data fim anterior ÃƒÆ’Ã‚Â  data inÃƒÆ’Ã‚Â­cio"
                })
                error_count += 1
                continue
            
            # Verificar duplicaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o (se jÃƒÆ’Ã‚Â¡ existe evento de atestado no perÃƒÆ’Ã‚Â­odo)
            existing_events = session.exec(
                select(models.Event)
                .where(models.Event.employee_id == emp.id)
                .where(models.Event.type == "atestado")
                .where(models.Event.timestamp >= data_inicio)
                .where(models.Event.timestamp <= data_fim)
            ).all()
            
            if existing_events:
                details.append({
                    "linha": row_num,
                    "status": "ignorado",
                    "matricula": matricula,
                    "nome": emp.name,
                    "mensagem": f"JÃƒÆ’Ã‚Â¡ existe atestado registrado no perÃƒÆ’Ã‚Â­odo ({len(existing_events)} evento(s))"
                })
                skipped_count += 1
                logger.info(f"[{trace_id}] Linha {row_num}: Atestado duplicado para {emp.name}")
                continue
            
            # Criar eventos para cada dia do perÃƒÆ’Ã‚Â­odo
            current_date = data_inicio
            events_created = 0
            events_to_add = []
            routines_to_add = []
            
            while current_date <= data_fim:
                # Criar evento de atestado
                evt_text = f"Atestado mÃƒÆ’Ã‚Â©dico"
                if observacao and observacao != 'nan':
                    evt_text += f" - {observacao}"
                
                new_event = models.Event(
                    employee_id=emp.id,
                    type="atestado",
                    text=evt_text,
                    timestamp=current_date,
                    category="pessoas",
                    sector=emp.cost_center or "Geral",
                    impact="medium"
                )
                events_to_add.append(new_event)
                events_created += 1
                
                # Criar rotinas para todos os turnos (sem verificar se existe - mais rÃƒÆ’Ã‚Â¡pido)
                date_str = current_date.strftime("%Y-%m-%d")
                for shift in ["ManhÃƒÆ’Ã‚Â£", "Tarde", "Noite"]:
                    routine = models.EmployeeRoutine(
                        employee_id=emp.id,
                        date=date_str,
                        shift=shift,
                        routine="sick",
                        created_at=datetime.now(tz),
                        updated_at=datetime.now(tz)
                    )
                    routines_to_add.append(routine)
                
                current_date += timedelta(days=1)
            
            # Adicionar todos de uma vez (batch insert)
            for event in events_to_add:
                session.add(event)
            for routine in routines_to_add:
                session.add(routine)
            
            details.append({
                "linha": row_num,
                "status": "sucesso",
                "matricula": matricula,
                "nome": emp.name,
                "periodo": f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
                "dias": events_created,
                "mensagem": f"{events_created} dia(s) de atestado registrado(s)"
            })
            success_count += 1
            logger.info(f"[{trace_id}] Linha {row_num}: Atestado criado para {emp.name} - {events_created} dia(s)")
            
        except Exception as e:
            logger.exception(f"[{trace_id}] Erro ao processar linha {row_num}")
            details.append({
                "linha": row_num,
                "status": "erro",
                "matricula": matricula if 'matricula' in locals() else "?",
                "mensagem": f"Erro ao processar: {str(e)}"
            })
            error_count += 1
            # NÃƒÆ’Ã‚Â£o fazer rollback aqui - continuar processando outras linhas
    
    # Commit ÃƒÆ’Ã‚Âºnico no final (muito mais rÃƒÆ’Ã‚Â¡pido!)
    try:
        session.commit()
        logger.info(f"[{trace_id}] Commit realizado com sucesso")
    except Exception as e_commit:
        logger.exception(f"[{trace_id}] Erro ao fazer commit final")
        session.rollback()
        return JSONResponse({
            "error": f"Erro ao salvar dados: {str(e_commit)}",
            "trace_id": trace_id,
            "partial_results": {
                "success_count": success_count,
                "error_count": error_count,
                "skipped_count": skipped_count
            }
        }, status_code=500)
    
    logger.info(f"[{trace_id}] ImportaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o concluÃƒÆ’Ã‚Â­da - Sucesso: {success_count}, Erros: {error_count}, Ignorados: {skipped_count}")
    
    return JSONResponse({
        "success_count": success_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "total_processed": len(df),
        "details": details,
        "trace_id": trace_id
    })

@app.get("/import-medical-certificates", response_class=HTMLResponse)
async def import_medical_certificates_page(request: Request):
    """PÃƒÆ’Ã‚Â¡gina de importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de atestados"""
    user = require_login(request)
    return templates.TemplateResponse("import_medical_certificates.html", {
        "request": request,
        "user": user
    })

@app.get("/api/debug/force-sync")
async def force_sync_debug():
    """ForÃƒÆ’Ã‚Â§a sincronizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o e retorna log detalhado"""
    logs = []
    try:
        with Session(engine) as session:
            sectors = session.exec(select(models.Sector)).all()
            shifts = {}
            for s in sectors:
                if s.shift not in shifts: shifts[s.shift] = []
                shifts[s.shift].append(s)
            
            logs.append(f"Setores encontrados no DB: {len(sectors)}")

            for shift, sector_list in shifts.items():
                 config_db = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == shift)).first()
                 if not config_db: 
                     logs.append(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Config nÃƒÆ’Ã‚Â£o encontrada para turno '{shift}'")
                     continue
                 
                 data = config_db.config_json
                 if isinstance(data, str):
                     import json
                     data = json.loads(data)
                 
                 if not data: 
                    logs.append(f"ÃƒÂ¢Ã‚ÂÃ…â€™ JSON invÃƒÆ’Ã‚Â¡lido/vazio para '{shift}'")
                    continue
                 
                 config_sectors = data.get('sectors', [])
                 logs.append(f"Turno '{shift}': {len(sector_list)} setores no DB vs {len(config_sectors)} no JSON")

                 changed = False
                 
                 for s in sector_list:
                     found = False
                     for cs in config_sectors:
                         # Normalize names for comparison
                         db_name = s.name.strip().lower()
                         json_name = cs.get('label', '').strip().lower()
                         
                         if db_name == json_name:
                             found = True
                             target = cs.get('target')
                             if target != s.max_employees:
                                 logs.append(f"   ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ CORRIGINDO '{s.name}': {target} -> {s.max_employees}")
                                 cs['target'] = s.max_employees
                                 changed = True
                             else:
                                 logs.append(f"   ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ '{s.name}' OK: {target}")
                             break
                     
                     if not found:
                         logs.append(f"   ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â '{s.name}' nÃƒÆ’Ã‚Â£o encontrado no JSON")
                
                 if changed:
                     config_db.config_json = data
                     config_db.updated_at = datetime.now()
                     session.add(config_db)
                     logs.append(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬â„¢Ã‚Â¾ Salvando config para '{shift}'")
            
            session.commit()
            logs.append("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Sync concluÃƒÆ’Ã‚Â­do com sucesso")
    except Exception as e:
        logs.append(f"ÃƒÂ¢Ã‚ÂÃ…â€™ ERRO FATAL: {str(e)}")
        import traceback
        logs.append(traceback.format_exc())
    
    return {"logs": logs}

@app.post("/routine/update", response_class=JSONResponse)
async def update_routine(
    request: Request,
    data: DailyRoutineUpdate,
    session: Session = Depends(get_session)
):
    require_login(request)
    try:
        daily = session.exec(
            select(models.DailyOperation)
            .where(models.DailyOperation.date == data.date)
            .where(models.DailyOperation.shift == data.shift)
        ).first()
        if not daily:
            daily = models.DailyOperation(date=data.date, shift=data.shift)
            session.add(daily)
            
        # Update Log Fields
        if data.attendance_log is not None:
            daily.attendance_log = data.attendance_log
        if data.tonnage is not None:
            daily.tonnage = data.tonnage
        if data.arrival_time is not None:
            daily.arrival_time = data.arrival_time
        if data.exit_time is not None:
            daily.exit_time = data.exit_time
        if data.report is not None:
            daily.report = data.report
        if data.rating is not None:
            daily.rating = data.rating
        if data.status is not None:
            daily.status = data.status
        if data.logs is not None:
            daily.logs = data.logs
            
        # [NEW] Sync Absences to Events
        # We process the attendance_log to find 'absent' or 'sick'
        if data.attendance_log:
             try:
                op_date_dt = datetime.strptime(data.date, "%Y-%m-%d")
                
                # Fetch employees map
                all_ids = [str(k) for k in data.attendance_log.keys()]
                # Optimization: Only fetch relevant employees later if needed, or query all
                # For now, simplistic approach:
                
                for reg_id, entry in data.attendance_log.items():
                    status = entry.get('status')
                    if status in ['absent', 'sick', 'away']:
                        # Check if event already exists for this day/emp
                        # We need the employee ID (int) not just registration_id (str)
                        # So we might need to fetch the employee object
                        emp = session.exec(select(models.Employee).where(models.Employee.registration_id == str(reg_id))).first()
                        if emp:
                            evt_type = "falta"
                            if status == 'sick': evt_type = "atestado"
                            elif status == 'away': evt_type = "afastamento"
                            
                            # Check existence
                            existing = session.exec(select(models.Event).where(
                                models.Event.employee_id == emp.id, 
                                models.Event.type == evt_type
                            ).where(col(models.Event.timestamp) >= op_date_dt).where(col(models.Event.timestamp) < op_date_dt + timedelta(days=1))).first()
                            
                            if not existing:
                                # Create
                                evt_text = f"Registro: {status.upper()} em {op_date_dt.strftime('%d/%m/%Y')}"
                                new_event = models.Event(
                                    timestamp=datetime.now(), # Logged NOW, but text refers to date
                                    text=evt_text,
                                    type=evt_type,
                                    category="pessoas",
                                    sector=emp.cost_center or "Geral",
                                    impact="medium",
                                    employee_id=emp.id
                                )
                                session.add(new_event)
             except Exception as e_sync:
                 print(f"Error syncing events: {e_sync}")
            
        daily.updated_at = datetime.now()
        
        # Save Sector Config
        if data.sector_config:
            config_entry = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == data.shift)).first()
            if not config_entry:
                config_entry = models.SectorConfiguration(shift_name=data.shift, config_json=data.sector_config)
                session.add(config_entry)
            else:
                config_entry.config_json = data.sector_config
                config_entry.updated_at = datetime.now()
                session.add(config_entry)
        
        session.commit()
        session.refresh(daily)
        return JSONResponse({"message": "Routine updated successfully", "id": daily.id})
    except Exception as e:
        print(f"Error updating routine: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# --- Employees API ---

@app.get("/api/employees", response_class=JSONResponse)
async def get_all_employees(request: Request, session: Session = Depends(get_session)):
    """Retorna todos os colaboradores (incluindo demitidos, mas excluindo substituÃƒÆ’Ã‚Â­dos)"""
    user = get_current_user(request)
    
    # Verificar se estÃƒÆ’Ã‚Â¡ logado
    if not user:
        raise HTTPException(status_code=403, detail="NÃƒÆ’Ã‚Â£o autenticado")
    
    # Permitir acesso para qualquer usuÃƒÆ’Ã‚Â¡rio logado (nÃƒÆ’Ã‚Â£o precisa de permissÃƒÆ’Ã‚Â£o especÃƒÆ’Ã‚Â­fica)
    # Isso ÃƒÆ’Ã‚Â© necessÃƒÆ’Ã‚Â¡rio para o Smart Flow funcionar
    # Bypass da verificaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de permissÃƒÆ’Ã‚Âµes de pÃƒÆ’Ã‚Â¡gina para este endpoint especÃƒÆ’Ã‚Â­fico
    
    # Buscar TODOS os colaboradores nÃƒÆ’Ã‚Â£o substituÃƒÆ’Ã‚Â­dos
    employees = session.exec(
        select(models.Employee)
        .where(models.Employee.replaced_by.is_(None))  # Excluir substituÃƒÆ’Ã‚Â­dos
    ).all()
    
    return JSONResponse(
        content={
            "employees": [{
                "id": e.id,
                "registration_id": e.registration_id,
                "name": e.name,
                "role": e.role,
                "shift": e.work_shift,
                "status": e.status
            } for e in employees]
        },
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

# --- Smart Flow Hierarchical API Endpoints ---

@app.get("/api/smart-flow/sectors", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def get_sectors(
    request: Request,
    shift: str = "ManhÃƒÆ’Ã‚Â£",
    session: Session = Depends(get_session)
):
    """Retorna todos os setores e sub-setores de um turno"""
    require_login(request)
    
    sectors = session.exec(
        select(models.Sector)
        .where(models.Sector.shift == shift)
        .order_by(models.Sector.order)
    ).all()
    
    result = []
    for sector in sectors:
        subsectors = session.exec(
            select(models.SubSector)
            .where(models.SubSector.sector_id == sector.id)
            .order_by(models.SubSector.order)
        ).all()
        
        result.append({
            "id": sector.id,
            "name": sector.name,
            "max_employees": sector.max_employees,
            "color": sector.color,
            "icon": sector.icon,
            "order": sector.order,
            "subsectors": [{
                "id": sub.id,
                "name": sub.name,
                "max_employees": sub.max_employees,
                "order": sub.order
            } for sub in subsectors]
        })
    
    return {"sectors": result}

@app.post("/api/smart-flow/sectors", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def create_sector(
    request: Request,
    name: str = Form(...),
    shift: str = Form(...),
    max_employees: int = Form(0),
    color: str = Form("blue"),
    session: Session = Depends(get_session)
):
    """Cria um novo setor"""
    require_login(request)
    
    # Pegar prÃƒÆ’Ã‚Â³xima ordem
    max_order_result = session.exec(
        select(models.Sector.order)
        .where(models.Sector.shift == shift)
        .order_by(models.Sector.order.desc())
    ).first()
    
    max_order = max_order_result if max_order_result is not None else 0
    
    new_sector = models.Sector(
        name=name,
        shift=shift,
        max_employees=max_employees,
        color=color,
        order=max_order + 1
    )
    
    session.add(new_sector)
    session.commit()
    session.refresh(new_sector)
    
    return {"success": True, "sector": {"id": new_sector.id, "name": new_sector.name}}

@app.put("/api/smart-flow/sectors/{sector_id}", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def update_sector(
    request: Request,
    sector_id: int,
    name: str = Form(None),
    max_employees: int = Form(None),
    color: str = Form(None),
    session: Session = Depends(get_session)
):
    """Edita um setor existente"""
    require_login(request)
    
    # DEBUG: Log para rastrear chamadas
    # print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ UPDATE_SECTOR CHAMADO: {sector_id} - {name}")
    
    sector = session.get(models.Sector, sector_id)
    if not sector:
        return JSONResponse({"error": "Setor nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
    
    # Track if max_employees changed (need to sync with SectorConfiguration)
    # FORÃƒÆ’Ã¢â‚¬Â¡ANDO True para garantir sincronizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o durante debug
    meta_changed = True 
    
    if name is not None:
        sector.name = name
    if max_employees is not None:
        sector.max_employees = max_employees
    if color is not None:
        sector.color = color
    
    sector.updated_at = datetime.now()
    session.add(sector)
    
    # IMPORTANTE: Sincronizar com SectorConfiguration
    config_db = session.exec(
        select(models.SectorConfiguration)
        .where(models.SectorConfiguration.shift_name == sector.shift)
    ).first()
    
    if config_db and config_db.config_json:
        # Parse config
        config_data = config_db.config_json if isinstance(config_db.config_json, dict) else json.loads(config_db.config_json)
        
        # Atualizar meta do setor na configuraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
        sectors_list = config_data.get('sectors', [])
        found = False
        
        for s in sectors_list:
            if s.get('label') == sector.name:
                s['target'] = sector.max_employees
                found = True
                break
        
        if found:
            # Salvar configuraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o atualizada
            config_db.config_json = config_data
            config_db.updated_at = datetime.now()
            session.add(config_db)
            session.flush()
            
    try:
        session.commit()
    except Exception as e:
        print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao salvar setor ou configuraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o: {e}")
        session.rollback()
        return JSONResponse({"error": f"Erro ao atualizar setor: {e}"}, status_code=500)
    
    return {"success": True}

@app.delete("/api/smart-flow/sectors/{sector_id}", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def delete_sector(
    request: Request,
    sector_id: int,
    session: Session = Depends(get_session)
):
    """Exclui um setor e remove todas as alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes"""
    require_login(request)
    
    sector = session.get(models.Sector, sector_id)
    if not sector:
        return JSONResponse({"error": "Setor nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
    
    # Cascade delete vai remover sub-setores e alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes automaticamente
    session.delete(sector)
    session.commit()
    
    return {"success": True}

@app.post("/api/smart-flow/subsectors", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def create_subsector(
    request: Request,
    sector_id: int = Form(...),
    name: str = Form(...),
    max_employees: int = Form(0),
    session: Session = Depends(get_session)
):
    """Cria um novo sub-setor"""
    require_login(request)
    
    sector = session.get(models.Sector, sector_id)
    if not sector:
        return JSONResponse({"error": "Setor nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
    
    # Pegar prÃƒÆ’Ã‚Â³xima ordem
    max_order_result = session.exec(
        select(models.SubSector.order)
        .where(models.SubSector.sector_id == sector_id)
        .order_by(models.SubSector.order.desc())
    ).first()
    
    max_order = max_order_result if max_order_result is not None else 0
    
    new_subsector = models.SubSector(
        sector_id=sector_id,
        name=name,
        max_employees=max_employees,
        order=max_order + 1
    )
    
    session.add(new_subsector)
    session.commit()
    session.refresh(new_subsector)
    
    return {"success": True, "subsector": {"id": new_subsector.id, "name": new_subsector.name}}

@app.put("/api/smart-flow/subsectors/{subsector_id}", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def update_subsector(
    request: Request,
    subsector_id: int,
    name: str = Form(None),
    max_employees: int = Form(None),
    session: Session = Depends(get_session)
):
    """Edita um sub-setor existente"""
    require_login(request)
    
    subsector = session.get(models.SubSector, subsector_id)
    if not subsector:
        return JSONResponse({"error": "Sub-setor nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
    
    if name is not None:
        subsector.name = name
    if max_employees is not None:
        subsector.max_employees = max_employees
    
    session.add(subsector)
    session.commit()
    
    return {"success": True}

@app.delete("/api/smart-flow/subsectors/{subsector_id}", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def delete_subsector(
    request: Request,
    subsector_id: int,
    session: Session = Depends(get_session)
):
    """Exclui um sub-setor e remove todas as alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes"""
    require_login(request)
    
    subsector = session.get(models.SubSector, subsector_id)
    if not subsector:
        return JSONResponse({"error": "Sub-setor nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
    
    # Cascade delete vai remover alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes automaticamente
    session.delete(subsector)
    session.commit()
    
    return {"success": True}

@app.get("/api/smart-flow/allocations", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def get_allocations(
    request: Request,
    date: str,
    shift: str,
    session: Session = Depends(get_session)
):
    """Retorna alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes e rotinas do dia/turno"""
    require_login(request)
    
    # Buscar alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes do dia atual
    allocations = session.exec(
        select(models.EmployeeAllocation)
        .where(models.EmployeeAllocation.date == date)
        .where(models.EmployeeAllocation.shift == shift)
    ).all()
    
    # Se nÃƒÆ’Ã‚Â£o houver alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes, buscar dos dias anteriores
    # IMPORTANTE: Para escala 12x36 (noturno), a ÃƒÆ’Ã‚Âºltima alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o pode ter sido hÃƒÆ’Ã‚Â¡ 2-3 dias
    # Buscamos atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s para cobrir escala 12x36 + feriados/fins de semana
    if not allocations:
        from datetime import datetime, timedelta
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
            
            # Buscar atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s (cobre escala 12x36 + possÃƒÆ’Ã‚Â­veis feriados)
            MAX_DAYS_LOOKBACK = 4
            previous_allocations = []
            found_date_str = None
            
            for days_back in range(1, MAX_DAYS_LOOKBACK + 1):
                previous_date = current_date - timedelta(days=days_back)
                previous_date_str = previous_date.strftime("%Y-%m-%d")
                
                print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹ Buscando alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de {previous_date_str} ({days_back} dia(s) atrÃƒÆ’Ã‚Â¡s)...")
                
                previous_allocations = session.exec(
                    select(models.EmployeeAllocation)
                    .where(models.EmployeeAllocation.date == previous_date_str)
                    .where(models.EmployeeAllocation.shift == shift)
                ).all()
                
                if previous_allocations:
                    found_date_str = previous_date_str
                    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Encontradas {len(previous_allocations)} alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de {found_date_str}!")
                    break
                else:
                    print(f"   ÃƒÂ¢Ã‚ÂÃ‚Â­ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o em {previous_date_str}, tentando dia anterior...")
            
            if previous_allocations and found_date_str:
                print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â¥ Copiando {len(previous_allocations)} alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de {found_date_str} para {date}...")
                
                # Copiar alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes encontradas para o dia atual
                for prev_alloc in previous_allocations:
                    new_alloc = models.EmployeeAllocation(
                        date=date,
                        shift=shift,
                        employee_id=prev_alloc.employee_id,
                        subsector_id=prev_alloc.subsector_id
                    )
                    session.add(new_alloc)
                
                session.commit()
                
                # Recarregar alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes criadas
                allocations = session.exec(
                    select(models.EmployeeAllocation)
                    .where(models.EmployeeAllocation.date == date)
                    .where(models.EmployeeAllocation.shift == shift)
                ).all()
                
                print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Escala copiada com sucesso! {len(allocations)} colaboradores alocados (origem: {found_date_str})")
            else:
                print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o encontrada nos ÃƒÆ’Ã‚Âºltimos {MAX_DAYS_LOOKBACK} dias para turno {shift}")
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao copiar escala de dias anteriores: {e}")
    
    # Buscar rotinas do dia atual
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date == date)
        .where(models.EmployeeRoutine.shift == shift)
    ).all()
    
    # Se nÃƒÆ’Ã‚Â£o houver rotinas, copiar de dias anteriores (especialmente FÃƒÆ’Ã‚Â©rias e Afastado)
    # IMPORTANTE: Para escala 12x36 (noturno), buscamos atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s
    if not routines and allocations:
        from datetime import datetime, timedelta
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
            
            # Buscar atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s (cobre escala 12x36 + possÃƒÆ’Ã‚Â­veis feriados)
            MAX_DAYS_LOOKBACK = 4
            previous_routines = []
            found_date_str = None
            
            for days_back in range(1, MAX_DAYS_LOOKBACK + 1):
                previous_date = current_date - timedelta(days=days_back)
                previous_date_str = previous_date.strftime("%Y-%m-%d")
                
                print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹ Buscando rotinas de {previous_date_str} ({days_back} dia(s) atrÃƒÆ’Ã‚Â¡s)...")
                
                previous_routines = session.exec(
                    select(models.EmployeeRoutine)
                    .where(models.EmployeeRoutine.date == previous_date_str)
                    .where(models.EmployeeRoutine.shift == shift)
                ).all()
                
                if previous_routines:
                    found_date_str = previous_date_str
                    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Encontradas {len(previous_routines)} rotinas de {found_date_str}!")
                    break
                else:
                    print(f"   ÃƒÂ¢Ã‚ÂÃ‚Â­ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma rotina em {previous_date_str}, tentando dia anterior...")
            
            if previous_routines and found_date_str:
                # Copiar apenas rotinas persistentes (vacation, away, sick)
                # MAS verificar se o status atual do colaborador ainda corresponde
                persistent_routines = ['vacation', 'away', 'sick']
                copied_count = 0
                
                for prev_routine in previous_routines:
                    if prev_routine.routine in persistent_routines:
                        # Verificar status atual do colaborador no cadastro
                        emp = session.get(models.Employee, prev_routine.employee_id)
                        if emp:
                            emp_status = (emp.status or 'active').lower()
                            routine_type = prev_routine.routine.lower()
                            
                            # SÃƒÆ’Ã‚Â³ copiar se o status atual ainda corresponder ÃƒÆ’Ã‚Â  rotina
                            # vacation -> status deve ser vacation/fÃƒÆ’Ã‚Â©rias
                            # away -> status deve ser away/afastado
                            # sick -> status deve ser sick/atestado OU qualquer status (atestado pode ser temporÃƒÆ’Ã‚Â¡rio)
                            should_copy = False
                            
                            if routine_type == 'vacation' and emp_status in ['vacation', 'fÃƒÆ’Ã‚Â©rias', 'ferias']:
                                should_copy = True
                            elif routine_type == 'away' and emp_status in ['away', 'afastado']:
                                should_copy = True
                            elif routine_type == 'sick':
                                # Atestado ÃƒÆ’Ã‚Â© temporÃƒÆ’Ã‚Â¡rio, copiar apenas se ainda estÃƒÆ’Ã‚Â¡ como sick
                                should_copy = emp_status in ['sick', 'atestado']
                            
                            if should_copy:
                                new_routine = models.EmployeeRoutine(
                                    date=date,
                                    shift=shift,
                                    employee_id=prev_routine.employee_id,
                                    routine=prev_routine.routine
                                )
                                session.add(new_routine)
                                copied_count += 1
                            else:
                                print(f"ÃƒÂ¢Ã‚ÂÃ‚Â­ÃƒÂ¯Ã‚Â¸Ã‚Â NÃƒÆ’Ã‚Â£o copiando rotina '{prev_routine.routine}' para {emp.name} - status atual ÃƒÆ’Ã‚Â© '{emp_status}'")
                
                if copied_count > 0:
                    session.commit()
                    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ {copied_count} rotinas persistentes copiadas de {found_date_str} (FÃƒÆ’Ã‚Â©rias/Afastado/Atestado)")
                    
                    # Recarregar rotinas
                    routines = session.exec(
                        select(models.EmployeeRoutine)
                        .where(models.EmployeeRoutine.date == date)
                        .where(models.EmployeeRoutine.shift == shift)
                    ).all()
            else:
                print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma rotina encontrada nos ÃƒÆ’Ã‚Âºltimos {MAX_DAYS_LOOKBACK} dias para turno {shift}")
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao copiar rotinas: {e}")
    
    # Montar resposta - APENAS subsector_id, nÃƒÆ’Ã‚Â£o objeto completo
    allocations_map = {}
    for alloc in allocations:
        allocations_map[alloc.employee_id] = alloc.subsector_id
    
    routines_map = {}
    for routine in routines:
        routines_map[routine.employee_id] = routine.routine
    
    # Buscar tonÃƒÆ’Ã‚Â©lagem das ROTAS (AutomÃƒÆ’Ã‚Â¡tico)
    # Requisito: "Favor puxar os dados da tonelagem das rotas"
    route_tonnage = session.exec(
        select(func.sum(models.Route.tonnage))
        .where(models.Route.date == date)
        .where(models.Route.shift == shift) # Filter by shift to match operation context
        .where(models.Route.tonnage > 0)
    ).one()
    
    tonnage = route_tonnage if route_tonnage else 0.0

    # Fetch Targets - SEMPRE usar soma dos setores (SOURCE OF TRUTH)
    # HeadcountTarget ÃƒÆ’Ã‚Â© legado e pode estar desatualizado
    all_sectors = session.exec(select(models.Sector)).all()
    target_map = {"ManhÃƒÆ’Ã‚Â£": 0, "Tarde": 0, "Noite": 0}
    for sec in all_sectors:
        sec_shift_norm = "ManhÃƒÆ’Ã‚Â£"
        if "tarde" in sec.shift.lower(): sec_shift_norm = "Tarde"
        elif "noite" in sec.shift.lower(): sec_shift_norm = "Noite"
        target_map[sec_shift_norm] += sec.max_employees

    # Buscar alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes do dia atual
    allocations = session.exec(
        select(models.EmployeeAllocation)
        .where(models.EmployeeAllocation.date == date)
        .where(models.EmployeeAllocation.shift == shift)
    ).all()
    
    # Se nÃƒÆ’Ã‚Â£o houver alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes, buscar dos dias anteriores
    # IMPORTANTE: Para escala 12x36 (noturno), a ÃƒÆ’Ã‚Âºltima alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o pode ter sido hÃƒÆ’Ã‚Â¡ 2-3 dias
    # Buscamos atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s para cobrir escala 12x36 + feriados/fins de semana
    if not allocations:
        from datetime import datetime, timedelta
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
            
            # Buscar atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s (cobre escala 12x36 + possÃƒÆ’Ã‚Â­veis feriados)
            MAX_DAYS_LOOKBACK = 4
            previous_allocations = []
            found_date_str = None
            
            for days_back in range(1, MAX_DAYS_LOOKBACK + 1):
                previous_date = current_date - timedelta(days=days_back)
                previous_date_str = previous_date.strftime("%Y-%m-%d")
                
                print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹ Buscando alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de {previous_date_str} ({days_back} dia(s) atrÃƒÆ’Ã‚Â¡s)...")
                
                previous_allocations = session.exec(
                    select(models.EmployeeAllocation)
                    .where(models.EmployeeAllocation.date == previous_date_str)
                    .where(models.EmployeeAllocation.shift == shift)
                ).all()
                
                if previous_allocations:
                    found_date_str = previous_date_str
                    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Encontradas {len(previous_allocations)} alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de {found_date_str}!")
                    break
                else:
                    print(f"   ÃƒÂ¢Ã‚ÂÃ‚Â­ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o em {previous_date_str}, tentando dia anterior...")
            
            if previous_allocations and found_date_str:
                print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â¥ Copiando {len(previous_allocations)} alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de {found_date_str} para {date}...")
                
                # Copiar alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes encontradas para o dia atual
                for prev_alloc in previous_allocations:
                    new_alloc = models.EmployeeAllocation(
                        date=date,
                        shift=shift,
                        employee_id=prev_alloc.employee_id,
                        subsector_id=prev_alloc.subsector_id
                    )
                    session.add(new_alloc)
                
                session.commit()
                
                # Recarregar alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes criadas
                allocations = session.exec(
                    select(models.EmployeeAllocation)
                    .where(models.EmployeeAllocation.date == date)
                    .where(models.EmployeeAllocation.shift == shift)
                ).all()
                
                print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Escala copiada com sucesso! {len(allocations)} colaboradores alocados (origem: {found_date_str})")
            else:
                print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o encontrada nos ÃƒÆ’Ã‚Âºltimos {MAX_DAYS_LOOKBACK} dias para turno {shift}")
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao copiar escala de dias anteriores: {e}")
    
    # Buscar rotinas do dia atual
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date == date)
        .where(models.EmployeeRoutine.shift == shift)
    ).all()
    
    # Se nÃƒÆ’Ã‚Â£o houver rotinas, copiar de dias anteriores (especialmente FÃƒÆ’Ã‚Â©rias e Afastado)
    # IMPORTANTE: Para escala 12x36 (noturno), buscamos atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s
    if not routines and allocations:
        from datetime import datetime, timedelta
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
            
            # Buscar atÃƒÆ’Ã‚Â© 4 dias para trÃƒÆ’Ã‚Â¡s (cobre escala 12x36 + possÃƒÆ’Ã‚Â­veis feriados)
            MAX_DAYS_LOOKBACK = 4
            previous_routines = []
            found_date_str = None
            
            for days_back in range(1, MAX_DAYS_LOOKBACK + 1):
                previous_date = current_date - timedelta(days=days_back)
                previous_date_str = previous_date.strftime("%Y-%m-%d")
                
                print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¹ Buscando rotinas de {previous_date_str} ({days_back} dia(s) atrÃƒÆ’Ã‚Â¡s)...")
                
                previous_routines = session.exec(
                    select(models.EmployeeRoutine)
                    .where(models.EmployeeRoutine.date == previous_date_str)
                    .where(models.EmployeeRoutine.shift == shift)
                ).all()
                
                if previous_routines:
                    found_date_str = previous_date_str
                    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Encontradas {len(previous_routines)} rotinas de {found_date_str}!")
                    break
                else:
                    print(f"   ÃƒÂ¢Ã‚ÂÃ‚Â­ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma rotina em {previous_date_str}, tentando dia anterior...")
            
            if previous_routines and found_date_str:
                # Copiar apenas rotinas persistentes (vacation, away, sick)
                # MAS verificar se o status atual do colaborador ainda corresponde
                persistent_routines = ['vacation', 'away', 'sick']
                copied_count = 0
                
                for prev_routine in previous_routines:
                    if prev_routine.routine in persistent_routines:
                        # Verificar status atual do colaborador no cadastro
                        emp = session.get(models.Employee, prev_routine.employee_id)
                        if emp:
                            emp_status = (emp.status or 'active').lower()
                            routine_type = prev_routine.routine.lower()
                            
                            # SÃƒÆ’Ã‚Â³ copiar se o status atual ainda corresponder ÃƒÆ’Ã‚Â  rotina
                            # vacation -> status deve ser vacation/fÃƒÆ’Ã‚Â©rias
                            # away -> status deve ser away/afastado
                            # sick -> status deve ser sick/atestado OU qualquer status (atestado pode ser temporÃƒÆ’Ã‚Â¡rio)
                            should_copy = False
                            
                            if routine_type == 'vacation' and emp_status in ['vacation', 'fÃƒÆ’Ã‚Â©rias', 'ferias']:
                                should_copy = True
                            elif routine_type == 'away' and emp_status in ['away', 'afastado']:
                                should_copy = True
                            elif routine_type == 'sick':
                                # Atestado ÃƒÆ’Ã‚Â© temporÃƒÆ’Ã‚Â¡rio, copiar apenas se ainda estÃƒÆ’Ã‚Â¡ como sick
                                should_copy = emp_status in ['sick', 'atestado']
                            
                            if should_copy:
                                new_routine = models.EmployeeRoutine(
                                    date=date,
                                    shift=shift,
                                    employee_id=prev_routine.employee_id,
                                    routine=prev_routine.routine
                                )
                                session.add(new_routine)
                                copied_count += 1
                            else:
                                print(f"ÃƒÂ¢Ã‚ÂÃ‚Â­ÃƒÂ¯Ã‚Â¸Ã‚Â NÃƒÆ’Ã‚Â£o copiando rotina '{prev_routine.routine}' para {emp.name} - status atual ÃƒÆ’Ã‚Â© '{emp_status}'")
                
                if copied_count > 0:
                    session.commit()
                    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ {copied_count} rotinas persistentes copiadas de {found_date_str} (FÃƒÆ’Ã‚Â©rias/Afastado/Atestado)")
                    
                    # Recarregar rotinas
                    routines = session.exec(
                        select(models.EmployeeRoutine)
                        .where(models.EmployeeRoutine.date == date)
                        .where(models.EmployeeRoutine.shift == shift)
                    ).all()
            else:
                print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhuma rotina encontrada nos ÃƒÆ’Ã‚Âºltimos {MAX_DAYS_LOOKBACK} dias para turno {shift}")
        except Exception as e:
            print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao copiar rotinas: {e}")
    
    # Montar resposta - APENAS subsector_id, nÃƒÆ’Ã‚Â£o objeto completo
    allocations_map = {}
    for alloc in allocations:
        allocations_map[alloc.employee_id] = alloc.subsector_id
    
    routines_map = {}
    for routine in routines:
        routines_map[routine.employee_id] = routine.routine
    
    # Buscar tonÃƒÆ’Ã‚Â©lagem das ROTAS (AutomÃƒÆ’Ã‚Â¡tico)
    # Requisito: "Favor puxar os dados da tonelagem das rotas"
    route_tonnage = session.exec(
        select(func.sum(models.Route.tonnage))
        .where(models.Route.date == date)
        .where(models.Route.shift == shift) # Filter by shift to match operation context
        .where(models.Route.tonnage > 0)
    ).one()
    
    tonnage = route_tonnage if route_tonnage else 0.0

    # Fetch Targets - SEMPRE usar soma dos setores (SOURCE OF TRUTH)
    # HeadcountTarget ÃƒÆ’Ã‚Â© legado e pode estar desatualizado
    all_sectors = session.exec(select(models.Sector)).all()
    target_map = {"ManhÃƒÆ’Ã‚Â£": 0, "Tarde": 0, "Noite": 0}
    for sec in all_sectors:
        sec_shift_norm = "ManhÃƒÆ’Ã‚Â£"
        if "tarde" in sec.shift.lower(): sec_shift_norm = "Tarde"
        elif "noite" in sec.shift.lower(): sec_shift_norm = "Noite"
        target_map[sec_shift_norm] += sec.max_employees

    return {
        "allocations": allocations_map,
        "routines": routines_map,
        "tonnage": tonnage,
        "targets": target_map
    }

@app.get("/api/smart-flow/routine", response_class=JSONResponse)
async def get_routine(
    request: Request,
    date: str,
    shift: str,
    session: Session = Depends(get_session)
):
    """Retorna dados da rotina diÃƒÆ’Ã‚Â¡ria (KPIs, Log, Config)"""
    require_login(request)
    
    # 1. Buscar OperaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o DiÃƒÆ’Ã‚Â¡ria
    daily = session.exec(
        select(models.DailyOperation)
        .where(models.DailyOperation.date == date)
        .where(models.DailyOperation.shift == shift)
    ).first()
    
    log = daily.attendance_log if daily and daily.attendance_log else {}
    tonnage = daily.tonnage if daily and daily.tonnage else 0.0
    
    # 2. Calcular KPIs a partir do Log
    kpis = {
        "present": 0,
        "dayoff": 0,
        "sick": 0,
        "missing": 0,
        "vacation": 0,
        "away": 0,
        "target": 0,
        "gap": 0,
        "percent": 0,
        "tonnage": tonnage,
        "productivity": 0
    }
    
    # Helper normalizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o simples
    def normalize_status(val):
        if not val: return ""
        s = str(val).lower().strip()
        # Mapeamentos comuns
        if s in ['presenca', 'trabalhando', 'presente']: return 'present'
        if s in ['folga', 'compensacao', 'dsr']: return 'dayoff'
        if s in ['atestado', 'medico', 'doenca']: return 'sick'
        if s in ['falta', 'ausencia', 'injustificada']: return 'absent'
        if s in ['ferias']: return 'vacation'
        if s in ['afastado', 'licenca', 'inss']: return 'away'
        return s

    # Iterar sobre o log de presenÃƒÆ’Ã‚Â§a (Source of Truth do dia)
    for emp_id, entry in log.items():
        raw_status = entry.get('status')
        status = normalize_status(raw_status)
        
        if status == 'present':
            kpis['present'] += 1
        elif status == 'dayoff':
            kpis['dayoff'] += 1
        elif status == 'sick':
            kpis['sick'] += 1
        elif status in ['absent', 'missing']: # missing n ÃƒÆ’Ã‚Â© padrÃƒÆ’Ã‚Â£o mas vai que
            kpis['missing'] += 1
        elif status == 'vacation':
            kpis['vacation'] += 1
        elif status == 'away':
            kpis['away'] += 1
            
    # 3. Calcular Meta (Soma dos targets dos setores do turno)
    sectors = session.exec(select(models.Sector).where(models.Sector.shift == shift)).all()
    total_target = sum(s.max_employees for s in sectors)
    kpis['target'] = total_target
    
    # 4. KPIs Derivados
    if kpis['present'] < kpis['target']:
        kpis['gap'] = kpis['target'] - kpis['present']
    else:
        kpis['gap'] = 0 # Sem gap negativo visualmente, ou pode ser negativo pra mostrar excesso? Render.js sÃƒÆ’Ã‚Â³ mostra o valor. Deixar 0 se superavit ou negativo? O padrÃƒÆ’Ã‚Â£o gap ÃƒÆ’Ã‚Â© "falta", entÃƒÆ’Ã‚Â£o positivo ÃƒÆ’Ã‚Â© ruim.
        # Se tem 10 vagas e 12 presentes, gap ÃƒÆ’Ã‚Â© -2 (sobra)? Ou 0 (nÃƒÆ’Ã‚Â£o falta)?
        # Geralmente Gap = Meta - Real. Se Meta 10, Real 8, Gap 2. Se Meta 10, Real 12, Gap -2.
        # render.js: setText('total-gap', kpis.gap || 0);
        # Vamos manter matemÃƒÆ’Ã‚Â¡tica simples.
        kpis['gap'] = kpis['target'] - kpis['present']

    if kpis['target'] > 0:
        kpis['percent'] = int((kpis['present'] / kpis['target']) * 100)
    else:
        kpis['percent'] = 100 if kpis['present'] > 0 else 0
        
    if kpis['present'] > 0:
        kpis['productivity'] = int(tonnage / kpis['present'])
        
    # 5. ConfiguraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de Setores (Se salva no daily)
    # Alguns componentes usam sectors_config para saber estado de accordion etc, 
    # mas o principal vem de /api/smart-flow/sectors
    sectors_config = [] 
    if daily and daily.report:
        try:
             # Tentar extrair se existir no report json, senao vazio
             pass
        except: pass

    return {
        "log": log,
        "tonnage": tonnage,
        "sectors_config": sectors_config,
        "kpis": kpis
    }

@app.post("/api/smart-flow/allocations/save", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def save_allocations(
    request: Request,
    session: Session = Depends(get_session)
):
    """Salva alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes e rotinas do dia (Otimizado)"""
    require_login(request)
    
    try:
        data = await request.json()
        date = data.get("date")
        shift = data.get("shift")
        allocations = data.get("allocations", {})  # {employee_id: subsector_id}
        routines = data.get("routines", {})  # {employee_id: routine}
        tonnage = data.get("tonnage") # Optional float
        
        if not date or not shift:
            return JSONResponse({"error": "Data e turno sÃƒÆ’Ã‚Â£o obrigatÃƒÆ’Ã‚Â³rios"}, status_code=400)

        print(f"ÃƒÂ¢Ã…Â¡Ã‚Â¡ [SmartFlow] Salvando alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes para {date} - {shift}")
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
        date = normalize_shift_date(date, shift, now_br)
        
        # --- 1. Pre-Fetch Data (Cache in Memory) ---
        # Fetch ALL employees (needed for validation and sync)
        all_employees = session.exec(select(models.Employee)).all()
        emp_map = {e.id: e for e in all_employees}
        
        # Fetch ALL SubSectors and Sectors
        subsectors = session.exec(select(models.SubSector)).all()
        subsector_map = {s.id: s for s in subsectors}
        
        sectors = session.exec(select(models.Sector)).all()
        sector_map = {s.id: s for s in sectors}
        
        # --- 2. Clear Old Allocations ---
        # Bulk delete is faster
        try:
            # Note: SQLModel might require individual deletion if relationships cascade weirdly, 
            # but for performance, we try bulk. If logic requires cascades, we might need loop 
            # but at least fetch once. 
            # Using execute() with delete statement:
            statement = delete(models.EmployeeAllocation).where(
                models.EmployeeAllocation.date == date,
                models.EmployeeAllocation.shift == shift
            )
            session.exec(statement)
        except Exception as e_del:
            print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Erro no bulk delete, tentando delete manual: {e_del}")
            old_allocs = session.exec(
                select(models.EmployeeAllocation)
                .where(models.EmployeeAllocation.date == date)
                .where(models.EmployeeAllocation.shift == shift)
            ).all()
            for a in old_allocs:
                session.delete(a)
        
        # --- 3. Create New Allocations (Batch) ---
        new_alloc_objs = []
        valid_allocations_for_log = [] # List of (Employee, SubSector) for sync
        
        for emp_id_str, subsector_id_str in allocations.items():
            try:
                emp_id = int(emp_id_str)
                sub_id = int(subsector_id_str)
                
                # In-memory Validations
                if emp_id not in emp_map:
                    continue
                if sub_id not in subsector_map:
                    continue
                    
                new_alloc = models.EmployeeAllocation(
                    date=date, shift=shift,
                    employee_id=emp_id, subsector_id=sub_id
                )
                new_alloc_objs.append(new_alloc)
                valid_allocations_for_log.append((emp_map[emp_id], subsector_map[sub_id]))
                
            except ValueError:
                continue
                
        session.add_all(new_alloc_objs)
        
        # --- 4. Update Routines ---
        # Fetch existing routines for this shift to avoid duplicates
        existing_routines = session.exec(
            select(models.EmployeeRoutine)
            .where(models.EmployeeRoutine.date == date)
            .where(models.EmployeeRoutine.shift == shift)
        ).all()
        routine_dict_db = {r.employee_id: r for r in existing_routines}
        
        for emp_id_str, routine_val in routines.items():
            try:
                emp_id = int(emp_id_str)
                if emp_id not in emp_map: continue
                
                if emp_id in routine_dict_db:
                    # Update existing
                    if routine_dict_db[emp_id].routine != routine_val:
                        routine_dict_db[emp_id].routine = routine_val
                        session.add(routine_dict_db[emp_id])
                else:
                    # Create new
                    new_routine = models.EmployeeRoutine(
                        date=date, shift=shift,
                        employee_id=emp_id, routine=routine_val
                    )
                    session.add(new_routine)
            except ValueError:
                continue

        # --- 5. Sync with DailyOperation.attendance_log ---
        daily_op = session.exec(
            select(models.DailyOperation)
            .where(models.DailyOperation.date == date)
            .where(models.DailyOperation.shift == shift)
        ).first()
        
        if not daily_op:
            daily_op = models.DailyOperation(date=date, shift=shift, attendance_log={})
            session.add(daily_op)
            
        # Capture activities from payload (sent by Store.js inside attendance_log.activities or root)
        # Store.js sends: attendance_log: { activities: {...} }
        payload_log = data.get("attendance_log", {})
        activities_map = payload_log.get("activities", {})
        
        # ... (Existing logic for allocations and routines)

        attendance_log = {}
        
        # Build lookup for routine status from input
        routine_input_lookup = {int(k): v for k, v in routines.items()}
        
        # Process allocations for log
        for emp, sub in valid_allocations_for_log:
            sec = sector_map.get(sub.sector_id)
            if not sec: continue
            
            sector_name_norm = unicodedata.normalize('NFD', sec.name.lower().strip())
            sector_key = sector_name_norm.encode('ascii', 'ignore').decode('utf-8').replace(' ', '_')
            
            status = routine_input_lookup.get(emp.id, 'present')
            
            # Get Activity/Observation for this employee if exists
            emp_activity = activities_map.get(str(emp.id), {})
            
            attendance_log[str(emp.registration_id)] = {
                "status": status,
                "sector": sector_key,
                "sector_name": sec.name, # Store human readable name too
                "subsector_name": sub.name,
                "activity": emp_activity.get("activity"),
                "observation": emp_activity.get("observation")
            }
            
        # Also include employees NOT allocated but with Activity/Routine
        # Merge activities into log for unallocated people
        for emp_id_str, act_data in activities_map.items():
             try:
                 emp_id = int(emp_id_str)
                 emp = emp_map.get(emp_id)
                 if not emp: continue
                 
                 # If already processed via allocation, skip (already enriched above)
                 # Note: attendance_log uses registration_id as key.
                 if str(emp.registration_id) in attendance_log:
                     continue
                     
                 # Add unallocated entry
                 routine = routine_input_lookup.get(emp.id, 'present')
                 attendance_log[str(emp.registration_id)] = {
                     "status": routine,
                     "sector": None,
                     "activity": act_data.get("activity"),
                     "observation": act_data.get("observation")
                 }
             except:
                 continue
            
        if tonnage is not None:
            daily_op.tonnage = float(tonnage)
            
        daily_op.attendance_log = attendance_log
        session.add(daily_op)
        
        print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬â„¢Ã‚Â¾ Commit final ({len(new_alloc_objs)} alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes, {len(attendance_log)} logs)...")
        session.commit()
        print("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Salvo com sucesso!")
        
        return {"success": True, "message": "Dados salvos com sucesso"}
        
    except Exception as e:
        error_msg = f"ÃƒÂ¢Ã‚ÂÃ…â€™ ERRO ao salvar alocaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        
        # Write to file for debugging
        try:
            with open("debug_alloc.log", "a", encoding="utf-8") as f:
                f.write(f"\n{datetime.now()} - {error_msg}\n")
                f.write(traceback.format_exc())
        except:
            pass
            
        session.rollback()
        return JSONResponse({"error": str(e), "success": False}, status_code=500)


@app.post("/api/employees/vacation", response_class=JSONResponse)
async def set_employee_vacation(
    request: Request,
    session: Session = Depends(get_session)
):
    """Define fÃƒÆ’Ã‚Â©rias de um colaborador"""
    require_login(request)
    
    try:
        data = await request.json()
        employee_id = data.get("employee_id")
        vacation_start = data.get("vacation_start")
        vacation_end = data.get("vacation_end")
        
        if not employee_id or not vacation_start or not vacation_end:
            return JSONResponse({"error": "Dados incompletos"}, status_code=400)
        
        # Buscar colaborador
        employee = session.get(models.Employee, int(employee_id))
        if not employee:
            return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
        
        # Validar datas
        start_date = datetime.strptime(vacation_start, "%Y-%m-%d")
        end_date = datetime.strptime(vacation_end, "%Y-%m-%d")
        
        if start_date > end_date:
            return JSONResponse({"error": "Data de inÃƒÆ’Ã‚Â­cio nÃƒÆ’Ã‚Â£o pode ser maior que data de fim"}, status_code=400)
        
        # Atualizar colaborador
        employee.vacation_start = start_date
        employee.vacation_end = end_date
        employee.status = "vacation"
        
        # Criar evento para histÃƒÆ’Ã‚Â³rico
        event = models.Event(
            timestamp=datetime.now(),
            text=f"FÃƒÆ’Ã‚Â©rias Agendadas: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}",
            type="ferias_hist",
            category="vacation",
            employee_id=employee_id
        )
        session.add(event)
        
        session.commit()
        
        print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ FÃƒÆ’Ã‚Â©rias definidas: {employee.name} - {vacation_start} atÃƒÆ’Ã‚Â© {vacation_end}")
        
        return {"success": True, "message": "FÃƒÆ’Ã‚Â©rias definidas com sucesso"}
    except Exception as e:
        print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao definir fÃƒÆ’Ã‚Â©rias: {e}")
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/employees/routine/extended", response_class=JSONResponse)
async def set_employee_routine_extended(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    """Define rotina estendida de um colaborador (mÃƒÆ’Ã‚Âºltiplos dias)"""
    require_login(request)
    
    try:
        data = await request.json()
        employee_id = data.get("employee_id")
        routine = data.get("routine")
        start_date_str = data.get("start_date")
        days = data.get("days", 1)
        update_existing = data.get("update_existing", False)  # Permite atualizar registros existentes
        
        if not employee_id or not routine or not start_date_str:
            return JSONResponse({"error": "Dados incompletos"}, status_code=400)
        
        # Buscar colaborador
        employee = session.get(models.Employee, int(employee_id))
        if not employee:
            return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
        
        # Parse dates
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = start_date + timedelta(days=days - 1)
        
        # Verificar quais dias jÃƒÆ’Ã‚Â¡ existem
        existing_routines = session.exec(
            select(models.EmployeeRoutine)
            .where(models.EmployeeRoutine.employee_id == int(employee_id))
            .where(models.EmployeeRoutine.date >= start_date_str)
            .where(models.EmployeeRoutine.date <= end_date.strftime("%Y-%m-%d"))
        ).all()
        
        # Agrupar rotinas existentes por data
        existing_by_date = {}
        for r in existing_routines:
            date_key = r.date if isinstance(r.date, str) else r.date.strftime("%Y-%m-%d")
            if date_key not in existing_by_date:
                existing_by_date[date_key] = []
            existing_by_date[date_key].append(r)
        
        existing_dates_set = set(existing_by_date.keys())
        
        # Verificar se TODOS os dias jÃƒÆ’Ã‚Â¡ existem e update_existing nÃƒÆ’Ã‚Â£o foi solicitado
        all_dates_in_range = set()
        check_date = start_date
        while check_date <= end_date:
            all_dates_in_range.add(check_date.strftime("%Y-%m-%d"))
            check_date += timedelta(days=1)
        
        # Verificar se hÃƒÆ’Ã‚Â¡ conflitos (alguns ou todos os dias jÃƒÆ’Ã‚Â¡ existem)
        conflicting_dates = sorted(list(existing_dates_set.intersection(all_dates_in_range)))
        
        # Verificar se todos os dias conflitantes jÃƒÆ’Ã‚Â¡ tÃƒÆ’Ã‚Âªm a mesma rotina
        # Se sim, permitir atualizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o automÃƒÆ’Ã‚Â¡tica sem pedir confirmaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
        all_same_routine = True
        if conflicting_dates:
            for date_key in conflicting_dates:
                routines_for_date = existing_by_date.get(date_key, [])
                if routines_for_date:
                    # Verificar se pelo menos uma rotina existente ÃƒÆ’Ã‚Â© diferente
                    existing_routine = routines_for_date[0].routine
                    if existing_routine != routine:
                        all_same_routine = False
                        break
        
        # Se todos os dias jÃƒÆ’Ã‚Â¡ tÃƒÆ’Ã‚Âªm a mesma rotina, permitir atualizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o automÃƒÆ’Ã‚Â¡tica
        if conflicting_dates and all_same_routine and not update_existing:
            # Mesma rotina - atualizar automaticamente sem pedir confirmaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
            update_existing = True
        
        if conflicting_dates and not update_existing:
            # Retornar com cÃƒÆ’Ã‚Â³digo especial para frontend perguntar se quer atualizar
            conflict_dates_formatted = [datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y") for d in conflicting_dates]
            return JSONResponse({
                "error": f"Os seguintes dias jÃƒÆ’Ã‚Â¡ possuem registros: {', '.join(conflict_dates_formatted[:5])}{'...' if len(conflict_dates_formatted) > 5 else ''}. Deseja atualizar?",
                "conflicts": conflict_dates_formatted,
                "can_update": True,
                "success": False
            }, status_code=409)  # 409 Conflict - indica que pode ser resolvido com update
        
        # Labels em portuguÃƒÆ’Ã‚Âªs
        routine_labels = {
            'present': 'Presente',
            'vacation': 'FÃƒÆ’Ã‚Â©rias',
            'sick': 'Atestado',
            'away': 'Afastado',
            'absent': 'Falta',
            'dayoff': 'Folga',
            # Entrada adicional para saÃƒÆ’Ã‚Â­da antecipada
            'early_exit': 'SaÃƒÆ’Ã‚Â­da antecipada'
        }
        
        # Mapear tipo de evento
        event_type_map = {
            'sick': 'atestado',
            'absent': 'falta',
            'away': 'afastamento',
            'vacation': 'ferias_hist',
            'dayoff': 'folga',
            'early_exit': 'saida_antecipada',
            'present': 'presenca'
        }
        event_type = event_type_map.get(routine, 'routine_change')
        
        # Criar ou atualizar rotinas e eventos para cada dia
        created_count = 0
        updated_count = 0
        skipped_count = 0
        current_date = start_date
        br_tz = ZoneInfo("America/Sao_Paulo")
        
        try:
            while current_date <= end_date:
                date_str = current_date.strftime("%Y-%m-%d")
                
                if date_str in existing_dates_set:
                    # Verificar se a rotina existente ÃƒÆ’Ã‚Â© a mesma
                    existing_routines_for_date = existing_by_date.get(date_str, [])
                    existing_routine = existing_routines_for_date[0].routine if existing_routines_for_date else None
                    same_routine = (existing_routine == routine)
                    
                    if update_existing or same_routine:
                        # Se ÃƒÆ’Ã‚Â© a mesma rotina, permitir atualizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o automÃƒÆ’Ã‚Â¡tica
                        # Se update_existing foi solicitado, verificar proteÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes
                        if not same_routine:
                            # Verificar se estÃƒÆ’Ã‚Â¡ tentando sobrescrever atestado/afastamento por falta
                            # Atestado e afastamento tÃƒÆ’Ã‚Âªm prioridade sobre falta
                            protected_routines = {'sick', 'away', 'vacation'}
                            downgrade_routine = routine in {'absent', 'dayoff', 'present'}
                            
                            skip_update = False
                            for existing_r in existing_routines_for_date:
                                if existing_r.routine in protected_routines and downgrade_routine:
                                    # NÃƒÆ’Ã‚Â£o permitir sobrescrever atestado/afastamento por falta/folga/presente
                                    skip_update = True
                                    break
                            
                            if skip_update:
                                # Pular este dia - nÃƒÆ’Ã‚Â£o sobrescrever atestado/afastamento
                                skipped_count += 1
                                current_date += timedelta(days=1)
                                continue
                        
                        # Atualizar registros existentes
                        for existing_r in existing_routines_for_date:
                            existing_r.routine = routine
                            session.add(existing_r)
                        updated_count += 1
                        
                        # Criar novo evento de alteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o para histÃƒÆ’Ã‚Â³rico apenas se a rotina mudou
                        if not same_routine:
                            event_timestamp = datetime.combine(current_date, datetime.min.time()).replace(tzinfo=br_tz) + timedelta(hours=3)
                            event_text = f"{employee.name}: Rotina alterada para {routine_labels.get(routine, routine)} em {current_date.strftime('%d/%m/%Y')}"
                            
                            new_event = models.Event(
                                timestamp=event_timestamp,
                                text=event_text,
                                type=event_type,
                                category=routine,
                                employee_id=int(employee_id)
                            )
                            session.add(new_event)
                    else:
                        # Pular dias que jÃƒÆ’Ã‚Â¡ existem com rotina diferente (comportamento original)
                        skipped_count += 1
                        current_date += timedelta(days=1)
                        continue
                else:
                    # Criar EmployeeRoutine para cada turno
                    for shift_name in ["ManhÃƒÆ’Ã‚Â£", "Tarde", "Noite"]:
                        new_routine = models.EmployeeRoutine(
                            date=date_str,
                            shift=shift_name,
                            employee_id=int(employee_id),
                            routine=routine
                        )
                        session.add(new_routine)
                    
                    # Criar Event para histÃƒÆ’Ã‚Â³rico (um por dia)
                    event_timestamp = datetime.combine(current_date, datetime.min.time()).replace(tzinfo=br_tz) + timedelta(hours=3)
                    event_text = f"{employee.name}: {routine_labels.get(routine, routine)} em {current_date.strftime('%d/%m/%Y')}"
                    
                    new_event = models.Event(
                        timestamp=event_timestamp,
                        text=event_text,
                        type=event_type,
                        category=routine,
                        employee_id=int(employee_id)
                    )
                    session.add(new_event)
                    created_count += 1
                
                current_date += timedelta(days=1)
            
            session.commit()
        except Exception as commit_error:
            session.rollback()
            logger.exception(f"Erro ao processar rotina estendida: {commit_error}")
            raise commit_error
        
        # Mensagem informativa
        action_parts = []
        if created_count > 0:
            action_parts.append(f"{created_count} criado(s)")
        if updated_count > 0:
            action_parts.append(f"{updated_count} atualizado(s)")
        
        action_info = ", ".join(action_parts) if action_parts else "nenhuma alteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"
        print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Rotina estendida: {employee.name} - {routine} de {start_date_str} por {days} dias ({action_info})")
        
        # ================================================================
        # ENVIO DE E-MAIL AUTOMÃƒÆ’Ã‚ÂTICO PARA AUSÃƒÆ’Ã…Â NCIAS (FALTA, FOLGA, ATESTADO)
        # COM TRAVA DE SEGURANÃƒÆ’Ã¢â‚¬Â¡A CONTRA DUPLICADOS
        # ================================================================
        email_sent = False
        email_error = None
        email_already_sent = False
        
        # Mapear rotina para tipo de alerta
        routine_to_alert_type = {
            "absent": "absent",   # Falta -> AdvertÃƒÆ’Ã‚Âªncia
            "dayoff": "dayoff",   # Folga -> NotificaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de Folga
            "sick": "sick",       # Atestado -> NotificaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o MÃƒÆ’Ã‚Â©dica
            "early_exit": "early_exit"  # SaÃƒÆ’Ã‚Â­da antecipada -> Alerta de saÃƒÆ’Ã‚Â­da antecipada
        }
        
        alert_type = routine_to_alert_type.get(routine)
        alert_type_labels = {
            "absent": "advertÃƒÆ’Ã‚Âªncia",
            "dayoff": "folga",
            "sick": "atestado",
            "early_exit": "saÃƒÆ’Ã‚Â­da antecipada"  # Regulamos esse alerta com e-mail tambÃƒÆ’Ã‚Â©m
        }
        
        # Enviar alerta se for um dos tipos configurados (AGORA EM BACKGROUND)
        email_scheduled = False
        if alert_type and (created_count > 0 or updated_count > 0):
            try:
                # TRAVA DE SEGURANÃƒÆ’Ã¢â‚¬Â¡A: Verificar se jÃƒÆ’Ã‚Â¡ foi enviado e-mail para este colaborador/data/tipo
                existing_alert = session.exec(
                    select(models.AbsenceAlertLog)
                    .where(models.AbsenceAlertLog.employee_id == int(employee_id))
                    .where(models.AbsenceAlertLog.absence_date == start_date_str)
                ).first()
                
                if existing_alert:
                    # E-mail jÃƒÆ’Ã‚Â¡ foi enviado anteriormente - NÃƒÆ’Ã†â€™O enviar novamente
                    email_already_sent = True
                    print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ¢â‚¬â„¢ E-mail de {alert_type_labels.get(alert_type, 'alerta')} jÃƒÆ’Ã‚Â¡ enviado para {employee.name} em {start_date_str} (enviado em {existing_alert.sent_at.strftime('%d/%m/%Y %H:%M')})")
                else:
                    # Buscar destinatÃƒÆ’Ã‚Â¡rios ativos para este TIPO de alerta
                    alert_recipients = session.exec(
                        select(models.AbsenceAlertRecipient)
                        .where(models.AbsenceAlertRecipient.is_active == True)
                        .where(models.AbsenceAlertRecipient.alert_type == alert_type)
                    ).all()
                    
                    if alert_recipients:
                        recipient_emails = [r.email for r in alert_recipients]
                        
                        # Identificar quem registrou
                        user_session = request.session.get("user", {})
                        registered_by = user_session.get("username") or user_session.get("email") or "Sistema"
                        
                        # AGENDAR envio de e-mail em BACKGROUND (nÃƒÆ’Ã‚Â£o bloqueia a requisiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o)
                        background_tasks.add_task(
                            send_absence_alert_email_background,
                            employee_id=int(employee_id),
                            employee_name=employee.name,
                            employee_registration_id=employee.registration_id,
                            employee_role=employee.role or "",
                            employee_work_shift=employee.work_shift or "",
                            absence_date=start_date_str,
                            registered_by=registered_by,
                            recipients=recipient_emails,
                            days=days,
                            alert_type=alert_type
                        )
                        email_scheduled = True
                        print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â¤ E-mail de {alert_type_labels.get(alert_type, 'alerta')} agendado em background para {employee.name}")
                    else:
                        print(f"ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¹ÃƒÂ¯Ã‚Â¸Ã‚Â Nenhum destinatÃƒÆ’Ã‚Â¡rio configurado para alertas de {alert_type_labels.get(alert_type, routine)}")
            except Exception as email_exc:
                print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Erro ao processar envio de e-mail de {alert_type_labels.get(alert_type, 'alerta')}: {email_exc}")
                email_error = str(email_exc)
        
        message = f"Rotina processada com sucesso: {action_info}"
        if alert_type and email_scheduled:
            message += f" | E-mail de {alert_type_labels.get(alert_type, 'alerta')} sendo enviado..."
        elif alert_type and email_already_sent:
            message += " | E-mail jÃƒÆ’Ã‚Â¡ enviado anteriormente (nÃƒÆ’Ã‚Â£o duplicado)."
        elif alert_type and email_error:
            message += f" | Aviso: E-mail nÃƒÆ’Ã‚Â£o enviado ({email_error})"
        
        return {
            "success": True,
            "message": message,
            "created_days": created_count,
            "updated_days": updated_count,
            "email_scheduled": email_scheduled if alert_type else None,
            "email_already_sent": email_already_sent if alert_type else None
        }
    except Exception as e:
        print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao criar rotina estendida: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return JSONResponse({"error": str(e), "success": False}, status_code=500)

@app.post("/api/employees/routine", response_class=JSONResponse)
async def set_employee_routine(
    request: Request,
    session: Session = Depends(get_session)
):
    """Define rotina de um colaborador"""
    require_login(request)
    
    try:
        data = await request.json()
        employee_id = data.get("employee_id")
        routine = data.get("routine")
        
        if not employee_id or not routine:
            return JSONResponse({"error": "Dados incompletos"}, status_code=400)
        
        # Buscar colaborador
        employee = session.get(models.Employee, int(employee_id))
        if not employee:
            return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
        
        old_status = employee.status
        
        # Mapear rotina para status
        # status_map = {
        #     'present': 'active',
        #     'vacation': 'vacation',
        #     'sick': 'sick',
        #     'away': 'away',
        #     'absent': 'absent',
        #     'dayoff': 'dayoff'
        # }
        
        # New Logic: Only update long-term statuses
        # Ephemeral statuses (sick, absent, dayoff) should NOT change global status
        # unless we explicitly want them to persists.
        # Decision: 'sick', 'absent', 'dayoff' are DAILY. Global status stays 'active' (or whatever it was).
        # 'vacation', 'away' are LONG TERM.
        
        should_update_status = False
        new_status = old_status # Default keep old
        
        if routine in ['vacation', 'away', 'fired']:
             new_status = routine
             should_update_status = True
        elif routine == 'present':
             new_status = 'active' # Reset to active on present
             should_update_status = True
        
        # Atualizar colaborador APENAS se for mudanÃƒÆ’Ã‚Â§a de status persistente
        if should_update_status:
             employee.status = new_status
        
        # Se voltar para presente, limpar fÃƒÆ’Ã‚Â©rias
        if routine == 'present':
            employee.vacation_start = None
            employee.vacation_end = None
        
        # Labels em portuguÃƒÆ’Ã‚Âªs
        routine_labels = {
            'present': 'Presente',
            'vacation': 'FÃƒÆ’Ã‚Â©rias',
            'sick': 'Atestado',
            'away': 'Afastado',
            'absent': 'Falta',
            'dayoff': 'Folga',
            'early_exit': 'SaÃƒÆ’Ã‚Â­da antecipada'
        }
        
        # Determine Event Type correctly for Report
        # Map routine -> event_type
        event_type_map = {
             'sick': 'atestado',
             'absent': 'falta',
             'away': 'afastamento',
             'vacation': 'ferias',
             'dayoff': 'folga',
             'early_exit': 'saida_antecipada',
             'present': 'presenca'
        }
        
        event_type = event_type_map.get(routine, 'routine_change')
        
        event = models.Event(
            timestamp=datetime.now(),
            text=f"{employee.name}: Rotina setada para {routine_labels.get(routine, routine)}",
            type=event_type,
            category=routine,
            employee_id=employee_id
        )
        session.add(event)

        # --- Sincronizar rotina diÃƒÆ’Ã‚Â¡ria (EmployeeRoutine) ---
        # Fonte ÃƒÆ’Ã‚Âºnica para faltas/atestados/afastamentos usada em relatÃƒÆ’Ã‚Â³rios e performance.
        # Por enquanto aplicamos para a data atual em todos os turnos.
        from zoneinfo import ZoneInfo

        br_tz = ZoneInfo("America/Sao_Paulo")
        today_str = datetime.now(br_tz).strftime("%Y-%m-%d")

        existing_daily = session.exec(
            select(models.EmployeeRoutine)
            .where(models.EmployeeRoutine.employee_id == int(employee_id))
            .where(models.EmployeeRoutine.date == today_str)
        ).all()

        # Indexar por turno para facilitar upsert
        existing_by_shift = {r.shift: r for r in existing_daily if getattr(r, "shift", None)}

        # ProteÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o: nÃƒÆ’Ã‚Â£o permitir sobrescrever atestado/afastamento por falta/folga/presente
        protected_routines = {'sick', 'away', 'vacation'}
        downgrade_routine = routine in {'absent', 'dayoff', 'present'}
        
        for shift_name in ["ManhÃƒÆ’Ã‚Â£", "Tarde", "Noite"]:
            existing = existing_by_shift.get(shift_name)
            if existing:
                # Verificar se estÃƒÆ’Ã‚Â¡ tentando fazer downgrade de rotina protegida
                if existing.routine in protected_routines and downgrade_routine:
                    # NÃƒÆ’Ã‚Â£o sobrescrever atestado/afastamento por falta/folga
                    continue
                    
                if existing.routine != routine:
                    existing.routine = routine
                    session.add(existing)
            else:
                new_routine = models.EmployeeRoutine(
                    date=today_str,
                    shift=shift_name,
                    employee_id=int(employee_id),
                    routine=routine
                )
                session.add(new_routine)
        
        session.commit()
        
        print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Rotina atualizada: {employee.name} - {routine}")
        
        return {"success": True, "message": "Rotina atualizada com sucesso"}
    except Exception as e:
        print(f"ÃƒÂ¢Ã‚ÂÃ…â€™ Erro ao atualizar rotina: {e}")
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)

# --- Organogram Report Route ---

@app.get("/smart-flow/organogram", response_class=HTMLResponse)
async def organogram_report(
    request: Request,
    date: str = None,
    shift: str = None,
    session: Session = Depends(get_session)
):
    """
    RelatÃƒÆ’Ã‚Â³rio de Organograma Operacional
    Mostra setores, sub-setores e colaboradores alocados
    Com indicaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de vagas em aberto
    """
    user = require_login(request)
    try:
        # Default to today and current shift
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        if not shift:
            shift = "ManhÃƒÆ’Ã‚Â£"  # Default shift
        
        # Fetch sectors for this shift
        db_sectors = session.exec(
            select(models.Sector)
            .where(models.Sector.shift == shift)
            .order_by(models.Sector.order)
        ).all()
        
        # Fetch all subsectors
        all_subsectors = session.exec(select(models.SubSector)).all()
        subsector_map = {s.id: s for s in all_subsectors}
        
        # Fetch allocations for this date and shift
        allocations = session.exec(
            select(models.EmployeeAllocation)
            .where(models.EmployeeAllocation.date == date)
            .where(models.EmployeeAllocation.shift == shift)
        ).all()
        
        # Build allocation map: subsector_id -> list of employee_ids
        alloc_by_subsector = {}
        for alloc in allocations:
            if alloc.subsector_id not in alloc_by_subsector:
                alloc_by_subsector[alloc.subsector_id] = []
            alloc_by_subsector[alloc.subsector_id].append(alloc.employee_id)
        
        # Fetch all employees
        all_employees = session.exec(select(models.Employee)).all()
        emp_map = {e.id: e for e in all_employees}
        
        # Build structured data for template
        sectors_data = []
        total_allocated = 0
        total_target = 0
        total_vacancies = 0
        total_subsectors = 0
        vacancies_detail = []
        
        for sector in db_sectors:
            # Get subsectors for this sector
            sector_subsectors = [s for s in all_subsectors if s.sector_id == sector.id]
            sector_subsectors.sort(key=lambda x: x.order)
            
            sector_allocated = 0
            sector_max = sector.max_employees
            subsectors_data = []
            
            for subsector in sector_subsectors:
                total_subsectors += 1
                
                # Get employees allocated to this subsector
                emp_ids = alloc_by_subsector.get(subsector.id, [])
                employees_data = []
                
                for emp_id in emp_ids:
                    emp = emp_map.get(emp_id)
                    if emp:
                        # Get initials from name
                        name_parts = emp.name.split()
                        if len(name_parts) >= 2:
                            initials = name_parts[0][0] + name_parts[-1][0]
                        else:
                            initials = emp.name[:2] if len(emp.name) >= 2 else emp.name
                        
                        employees_data.append({
                            "id": emp.id,
                            "name": emp.name,
                            "initials": initials.upper(),
                            "role": emp.role or "Operador",
                            "status": emp.status
                        })
                        sector_allocated += 1
                
                # Calculate vacancies for this subsector
                subsector_max = subsector.max_employees or 0
                subsector_allocated = len(employees_data)
                subsector_vacancies = max(0, subsector_max - subsector_allocated)
                
                subsector_data = {
                    "id": subsector.id,
                    "name": subsector.name,
                    "max_employees": subsector_max,
                    "employees": employees_data,
                    "allocated_count": subsector_allocated,
                    "vacancies": subsector_vacancies,
                    "occupation_percent": int((subsector_allocated / subsector_max * 100) if subsector_max > 0 else 0)
                }
                subsectors_data.append(subsector_data)
                
                # Track vacancies for detail table
                if subsector_vacancies > 0:
                    vacancies_detail.append({
                        "sector_name": sector.name,
                        "subsector_name": subsector.name,
                        "max_employees": subsector_max,
                        "allocated": subsector_allocated,
                        "vacancies": subsector_vacancies,
                        "occupation_percent": subsector_data["occupation_percent"]
                    })
            
            # Calculate sector totals
            sector_vacancies = max(0, sector_max - sector_allocated)
            total_allocated += sector_allocated
            total_target += sector_max
            total_vacancies += sector_vacancies
            
            sector_data = {
                "id": sector.id,
                "name": sector.name,
                "color": sector.color,
                "max_employees": sector_max,
                "allocated_count": sector_allocated,
                "vacancies": sector_vacancies,
                "occupation_percent": int((sector_allocated / sector_max * 100) if sector_max > 0 else 0),
                "subsectors": subsectors_data
            }
            sectors_data.append(sector_data)
        
        # Build KPIs
        kpis = {
            "total_sectors": len(db_sectors),
            "total_subsectors": total_subsectors,
            "total_allocated": total_allocated,
            "total_target": total_target,
            "total_vacancies": total_vacancies,
            "occupation_percent": int((total_allocated / total_target * 100) if total_target > 0 else 0)
        }
        
        # Sort vacancies detail by vacancies count (descending)
        vacancies_detail.sort(key=lambda x: x["vacancies"], reverse=True)
        
        return templates.TemplateResponse("organogram_report.html", {
            "request": request,
            "date": datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y"),
            "shift": shift,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "sectors": sectors_data,
            "kpis": kpis,
            "vacancies_detail": vacancies_detail
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<h1>Erro ao Gerar Organograma</h1><pre>{traceback.format_exc()}</pre>", status_code=500)

# --- Report Route ---

@app.get("/routine/report", response_class=HTMLResponse)
async def routine_report(
    request: Request,
    date: str,
    shift: str,
    session: Session = Depends(get_session)
):
    user = require_login(request)
    try:
        # 1. Fetch Daily Operation
        daily_op = session.exec(
            select(models.DailyOperation)
            .where(models.DailyOperation.date == date)
            .where(models.DailyOperation.shift == shift)
        ).first()
        
        # 2. Fetch Employees (Active + those in log even if fired/changed)
        # For simplicity, we fetch all non-fired first, then we might need to handle historical
        # The log uses registration_id as key.
        all_employees = session.exec(select(models.Employee)).all()
        emp_map = {str(e.registration_id): e for e in all_employees}
        
        # 3. Fetch Sectors from Sector Table (SOURCE OF TRUTH - Same as Smart Flow)
        # IMPORTANTE: Usar tabela Sector ao invÃƒÆ’Ã‚Â©s de SectorConfiguration para garantir
        # consistÃƒÆ’Ã‚Âªncia entre Smart Flow e RelatÃƒÆ’Ã‚Â³rio
        db_sectors = session.exec(
            select(models.Sector)
            .where(models.Sector.shift == shift)
            .order_by(models.Sector.order)
        ).all()
        
        # Normalizar nome do setor para key (ex: "CÃƒÆ’Ã‚Â¢mara Fria" -> "camara_fria")
        def normalize_sector_key(name):
            import unicodedata
            name_norm = unicodedata.normalize('NFD', name.lower().strip())
            key = name_norm.encode('ascii', 'ignore').decode('utf-8').replace(' ', '_')
            return key
        
        # Converter para estrutura esperada pelo relatÃƒÆ’Ã‚Â³rio
        SECTORS = []
        for sec in db_sectors:
            SECTORS.append({
                "key": normalize_sector_key(sec.name),
                "label": sec.name,
                "target": sec.max_employees
            })
        
        # DEBUG: Log configuration status
        print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â DEBUG - Sectors from Sector table: {len(SECTORS)}")
        for s in SECTORS:
            print(f"   - {s.get('label')}: meta {s.get('target')}")
        
        # 4. Build Snapshot Data
        
        # 4. Build Snapshot Data (FROM SMART FLOW TABLES - SOURCE OF TRUTH)
        # We ignore daily_op.attendance_log because it is legacy/duplicated.
        
        # Fetch Allocations
        allocations = session.exec(
            select(models.EmployeeAllocation)
            .where(models.EmployeeAllocation.date == date)
            .where(models.EmployeeAllocation.shift == shift)
        ).all()
        
        # Fetch Routines
        routines = session.exec(
            select(models.EmployeeRoutine)
            .where(models.EmployeeRoutine.date == date)
            .where(models.EmployeeRoutine.shift == shift)
        ).all()
        
        # Fetch Tonnage (from Routes - Source of Truth)
        route_tonnage_val = session.exec(
            select(func.sum(models.Route.tonnage))
            .where(models.Route.date == date)
            .where(models.Route.shift == shift)
            .where(models.Route.tonnage > 0)
        ).one()
        tonnage = route_tonnage_val if route_tonnage_val else 0.0

        # Build "log" structure dynamically for Report compatibility
        # We need Sector Map to resolve subsector_id -> sector_key
        subsectors = session.exec(select(models.SubSector)).all()
        subsector_map = {s.id: s for s in subsectors}
        sectors = session.exec(select(models.Sector)).all()
        sector_map = {s.id: s for s in sectors}
        
        # Build Routine Map {emp_id: status}
        routine_map = {r.employee_id: r.routine for r in routines}
        
        # Reconstruct "log" (attendance_log style)
        # Key: registration_id (str)
        # Value: {status: ..., sector: key}
        
        log = {}
        processed_emp_ids = set()
        
        # 1. Add allocated employees
        for alloc in allocations:
            emp = session.get(models.Employee, alloc.employee_id)
            if not emp: continue
            
            sub = subsector_map.get(alloc.subsector_id)
            if not sub: continue
            
            sec = sector_map.get(sub.sector_id)
            if not sec: continue
            
            # Resolve Sector Key (normalization)
            sector_name_norm = unicodedata.normalize('NFD', sec.name.lower().strip())
            sector_key = sector_name_norm.encode('ascii', 'ignore').decode('utf-8').replace(' ', '_')
            
            # Resolve Status
            # Priority: Routine DiÃƒÆ’Ã‚Â¡ria > Employee Status Database > 'present'
            # IMPORTANTE: Se nÃƒÆ’Ã‚Â£o houver rotina no dia, verificar status do empregado (vacation, away, etc)
            if emp.id in routine_map:
                status = routine_map[emp.id]
            elif emp.status in ['vacation', 'away', 'sick']:
                # Usar status do banco se for ausÃƒÆ’Ã‚Âªncia conhecida
                status = emp.status
            else:
                # Default para colaboradores ativos sem rotina especÃƒÆ’Ã‚Â­fica
                status = 'present'
            
            log[str(emp.registration_id)] = {
                "status": status,
                "sector": sector_key
            }
            processed_emp_ids.add(emp.id)
            
        # 2. Add non-allocated but with routines (e.g. sick, away, absent not in a sector)
        for r in routines:
            if r.employee_id in processed_emp_ids: continue
            
            emp = session.get(models.Employee, r.employee_id)
            if not emp: continue
            
            # Non-allocated usually doesn't have a sector, or could be 'outros'
            # For report consistency, we might just list them if they have a relevant status
            log[str(emp.registration_id)] = {
                "status": r.routine,
                "sector": None 
            }
        
        # Prepare People List for Report
        people_list = []
        
        # Helper for Shift Normalization (Defined earlier for use in filtering)
        def normalize_str(s):
            if not s: return ""
            return unicodedata.normalize('NFD', str(s)).encode('ascii', 'ignore').decode('utf-8').lower().strip()

        target_shift_norm = normalize_str(shift)

        # Track processed IDs to merge log and DB
        total_present = 0
        processed_ids = set()
        
        # 1. Process via Log (Prioritize Daily Routine/Allocation)
        # This catches everyone who was interacted with today (even if shift changed, or if fired but worked today)
        for reg_id_str, entry in log.items():
            employee = emp_map.get(reg_id_str)
            if not employee:
                continue
            
            daily_status = entry.get('status', 'present')
            sector_key = entry.get('sector')
            
            # Count Present
            if daily_status == 'present':
                total_present += 1
                
            # Check Subst
            is_substituted = False
            if daily_status in ['away', 'vacation']:
                 has_sub_evt = session.exec(select(models.Event).where(
                    models.Event.employee_id == employee.id,
                    models.Event.text.like("%SubstituÃƒÆ’Ã‚Â­do por%")
                 )).first()
                 if has_sub_evt:
                     is_substituted = True

            people_list.append({
                "name": employee.name,
                "status_daily": daily_status,
                "sector_daily": sector_key,
                "is_substituted": is_substituted
            })
            processed_ids.add(employee.id)

        # 2. Process Remaining Employees (Same Shift, No Routine/Allocation Today)
        # Estes sÃƒÆ’Ã‚Â£o pessoas do turno que NÃƒÆ’Ã†â€™O foram alocadas hoje
        # IMPORTANTE: NÃƒÆ’Ã‚Â£o contar como 'present' se nÃƒÆ’Ã‚Â£o estÃƒÆ’Ã‚Â£o alocados (consistÃƒÆ’Ã‚Âªncia com Smart Flow)
        for emp in all_employees:
            if emp.id in processed_ids:
                continue
                
            if emp.status == 'fired': 
                continue # Fired and no routine = ignored
                
            # Check Shift - comparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o EXATA (nÃƒÆ’Ã‚Â£o usar 'in' para evitar matches incorretos)
            emp_shift_norm = normalize_str(emp.work_shift)
            if emp_shift_norm != target_shift_norm:
                continue # Wrong shift
                
            # Determine Status from DB Profile
            # IMPORTANTE: Se nÃƒÆ’Ã‚Â£o estÃƒÆ’Ã‚Â¡ alocado, usar o status do cadastro
            # NÃƒÆ’Ã‚Â£o assumir 'present' para pessoas nÃƒÆ’Ã‚Â£o alocadas (divergia do Smart Flow)
            db_status = emp.status
            report_status = db_status  # Usar status real do banco
            
            if db_status == 'away':
                report_status = 'away'
            elif db_status == 'vacation':
                report_status = 'vacation'
            elif db_status == 'active':
                # Active mas nÃƒÆ’Ã‚Â£o alocado = nÃƒÆ’Ã‚Â£o contar como presente operacionalmente
                # Pode ser: folga, nÃƒÆ’Ã‚Â£o programado, etc.
                # Para consistÃƒÆ’Ã‚Âªncia com Smart Flow, marcar como 'unallocated' (nÃƒÆ’Ã‚Â£o soma em presente)
                report_status = 'unallocated'
                # NÃƒÆ’Ã†â€™O incrementar total_present aqui!
            
            # Substituted Check (Duplicate logic, could functionality extract)
            is_substituted = False
            if report_status in ['away', 'vacation']:
                 has_sub_evt = session.exec(select(models.Event).where(
                    models.Event.employee_id == emp.id,
                    models.Event.text.like("%SubstituÃƒÆ’Ã‚Â­do por%")
                 )).first()
                 if has_sub_evt:
                     is_substituted = True

            people_list.append({
                "name": emp.name,
                "status_daily": report_status,
                "sector_daily": None, # Unallocated
                "is_substituted": is_substituted
            })
        
        # DEBUG: Mostrar setores ÃƒÆ’Ã‚Âºnicos presentes no attendance_log
        unique_sectors = set(p['sector_daily'] for p in people_list if p['sector_daily'])
        print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â DEBUG - Setores no attendance_log: {unique_sectors}")
        print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â DEBUG - Total de colaboradores: {len(people_list)}")
            
        # Substituted Count (Employees 'Away' who have a replacement OR Active employees who are replacements?)
        # User said "reminding that it can only pull this information from the away routine when creating a new employee"
        # Interpreted as: Count of Away employees who have been substituted.
        # Logic: Find 'away' employees. Check if they have an event "SubstituÃƒÆ’Ã‚Â­do por..."
        count_substitutions = 0
        away_employees = [e for e in all_employees if e.status == 'away']
        for emp in away_employees:
            has_sub = session.exec(select(models.Event).where(
                models.Event.employee_id == emp.id,
                models.Event.text.like("%SubstituÃƒÆ’Ã‚Â­do por%")
            )).first()
            if has_sub:
                count_substitutions += 1
                
        # Build Sectors Detailed
        sectors_detailed = []
        total_target = 0
        total_allocated_sum = 0
        
        for sec in SECTORS:
            key = sec.get('key')
            target = int(sec.get('target', 0))
            
            # Find people allocated to this sector
            allocated_people = [p for p in people_list if p['sector_daily'] == key]
            
            # IMPORTANTE: SEMPRE adicionar target ao total, mesmo sem colaboradores
            # Isso garante que a meta total seja a soma de TODAS as metas configuradas
            total_target += target
            
            # IMPORTANTE: Mostrar TODOS os setores, mesmo sem colaboradores
            # Isso mantÃƒÆ’Ã‚Â©m consistÃƒÆ’Ã‚Âªncia com o Smart Flow
            
            # Counts per sector
            present_people = [p for p in allocated_people if p['status_daily'] == 'present']
            absent_people = [p for p in allocated_people if p['status_daily'] in ['absent', 'sick']]
            vacation_away_people = [p for p in allocated_people if p['status_daily'] in ['vacation', 'away']]
            
            # Vagas: Target - Active Allocated? Or just Target - Present?
            # User dashboard usually shows "Vagas" as empty spots. 
            # If target=14 and allocated=13, vacancies=1. 
            # If target=14, allocated=14, present=10 -> gap=4.
            # Usually Vagas = Target - Allocated (Open positions).
            # Gap = Target - Present (Operational gap).
            vacancies = max(0, target - len(allocated_people))
            gap = max(0, target - len(present_people))
            
            sectors_detailed.append({
                "label": sec.get('label'),
                "target": target,
                "allocated_count": len(allocated_people),
                "present_count": len(present_people),
                "vacancies": vacancies, # Vagas
                "absences": len(absent_people), # Faltas/Atestados
                "vacation_away": len(vacation_away_people), # FÃƒÆ’Ã‚Â©rias/Afastados
                "gap": gap
            })
            total_allocated_sum += len(allocated_people)
            
        # Catch Unallocated (Present but not in a sector)
        # We need to know which people were already counted in sectors
        mapped_sector_keys = [s.get('key') for s in SECTORS]
        
        others_allocated = [p for p in people_list if p['sector_daily'] not in mapped_sector_keys]
        others_present = [p for p in others_allocated if p['status_daily'] == 'present']
        others_absent = [p for p in others_allocated if p['status_daily'] in ['absent', 'sick']]
        others_vac_away = [p for p in others_allocated if p['status_daily'] in ['vacation', 'away']]
        
        if others_present or others_allocated:
            sectors_detailed.append({
                "label": "Outros / NÃƒÆ’Ã‚Â£o Definido",
                "target": 0,
                "allocated_count": len(others_allocated),
                "present_count": len(others_present),
                "vacancies": 0,
                "absences": len(others_absent),
                "vacation_away": len(others_vac_away),
                "gap": 0
            })
            total_allocated_sum += len(others_allocated)
        
        # Calcular vagas operacionais (soma das vagas de todos os setores)
        total_operational_vacancies = sum(s.get('vacancies', 0) for s in sectors_detailed)
            
        # Top KPIs - ALINHADO COM SMART FLOW
        # IMPORTANTE: Total target = SOMA DAS METAS CONFIGURADAS (nÃƒÆ’Ã‚Â£o colaboradores do turno)
        # Isso garante consistÃƒÆ’Ã‚Âªncia com o Smart Flow
        
        # total_target jÃƒÆ’Ã‚Â¡ foi calculado no loop acima (soma de todas as metas)
        # NÃƒÆ’Ã‚Â£o usar total_target_real (colaboradores ativos) pois isso causa divergÃƒÆ’Ã‚Âªncia
        
        # Total Headcount (Active Workforce + Absences + Vacation + etc)
        total_headcount = len(people_list)
        
        # Operational Vacancies (Open Positions)
        # Definition: Total Target - Total Headcount
        # If we need 44 people and have 43 (regardless of status), we have 1 open position.
        # If we have 44 people but 3 are absent, we have 3 gaps, but 0 vacancies.
        total_vacancies = max(0, total_target - total_headcount)
        
        # Operational Gap (Missing Hands)
        # Definition: Total Target - Total Present
        total_gap = max(0, total_target - total_present)
        
        # HR Vacancies (Fired count - for reference/dashboard badge if needed)
        hr_vacancies_fired = 0
        for emp in all_employees:
            if emp.status == 'fired':
                 emp_shift_norm = normalize_str(emp.work_shift)
                 if target_shift_norm in emp_shift_norm:
                     hr_vacancies_fired += 1
                     
        # Decide which 'Vagas' to show in Top KPI.
        # User feedback suggests they want the math to close: 37 Present + 2 Absent + ... + X Vagas = 44 Target.
        # So Vagas MUST be (Target - Headcount).
        kpi_vacancies = total_vacancies

        prod_per_person = round(tonnage / total_present, 2) if total_present > 0 else 0
        present_pct = int((total_present / total_target * 100)) if total_target > 0 else 0
        
        # Detailed Counts
        daily_absent = len([p for p in people_list if p['status_daily'] == 'absent'])
        daily_sick = len([p for p in people_list if p['status_daily'] == 'sick'])
        daily_vacation = len([p for p in people_list if p['status_daily'] == 'vacation'])
        daily_away = len([p for p in people_list if p['status_daily'] == 'away'])
        daily_dayoff = len([p for p in people_list if p['status_daily'] == 'dayoff'])
        daily_suspended = len([p for p in people_list if p['status_daily'] == 'suspension'])
        
        count_substitutions = 0
        away_employees = [e for e in all_employees if e.status == 'away']
        for emp in away_employees:
            has_sub = session.exec(select(models.Event).where(
                models.Event.employee_id == emp.id,
                models.Event.text.like("%SubstituÃƒÆ’Ã‚Â­do por%")
            )).first()
            if has_sub:
                count_substitutions += 1
        
        # DEBUG DIAGNOSTIC
        print(f"RelatÃƒÆ’Ã‚Â³rio Debug - Data: {date}, Turno: {shift}")
        print(f"Meta Total: {total_target}")
        print(f"Headcount Total (People List): {total_headcount}")
        print(f"Presentes: {total_present}, Faltas: {daily_absent}, FÃƒÆ’Ã‚Â©rias: {daily_vacation}, Afastados: {daily_away}")
        print(f"Vagas Calculadas (Meta - Headcount): {kpi_vacancies}")
        print(f"Vagas Operacionais (Soma Setores): {total_operational_vacancies}")
        
        # Check filtered out employees
        ignored_count = 0
        for emp in all_employees:
            if emp.id not in processed_ids and emp.status != 'fired':
                emp_shift_norm = normalize_str(emp.work_shift)
                if target_shift_norm not in emp_shift_norm:
                     # print(f"Ignorado (Turno IncompatÃƒÆ’Ã‚Â­vel): {emp.name} ({emp.work_shift}) - Status: {emp.status}")
                     ignored_count += 1
        print(f"Total ignorados por turno incompatÃƒÆ’Ã‚Â­vel: {ignored_count}")

        snapshot = {
            "kpis": {
                "total_target": total_target,
                "total_allocated": total_allocated_sum,
                "total_present": total_present,
                "present_pct": present_pct,
                "total_gap": total_gap,  # Gap Operacional (Meta - Presentes)
                "total_vacancies": kpi_vacancies, # Vagas Abertas (Meta - Headcount)
                "hr_vacancies": hr_vacancies_fired, 
                "operational_gap": total_operational_vacancies, 
                "tonnage": f"{tonnage:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "prod_per_person": f"{prod_per_person:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "count_absent": daily_absent + daily_suspended, 
                "count_sick": daily_sick,
                "count_vacation": daily_vacation,
                "count_away": daily_away,
                "count_dayoff": daily_dayoff,
                "count_vacation_away": daily_vacation + daily_away,
                "count_substitutions": count_substitutions
            },
            "sectors": sectors_detailed,
            "people": people_list
        }
        
        # Extras for Insights
        params_date = datetime.strptime(date, "%Y-%m-%d").date()
        
        # Pre-filter lists for Report (Avoid Jinja complexity)
        absences = [p for p in people_list if p['status_daily'] in ['absent', 'sick']]
        unavail = [p for p in people_list if p['status_daily'] in ['vacation', 'away']]
        
        # Helper for Shift Normalization
        def normalize_str(s):
            if not s: return ""
            return unicodedata.normalize('NFD', str(s)).encode('ascii', 'ignore').decode('utf-8').lower().strip()

        target_shift_norm = normalize_str(shift)

        # Birthdays (Filtered by Shift, exclude fired)
        birthdays = []
        for emp in all_employees:
            if emp.status == 'fired':
                continue
            emp_shift_norm = normalize_str(emp.work_shift)
            if target_shift_norm not in emp_shift_norm:
                continue

            if emp.birthday:
                b_date = emp.birthday.date()
                if b_date.month == params_date.month:
                    is_today = (b_date.day == params_date.day)
                    birthdays.append({
                        "name": emp.name,
                        "day": b_date.day,
                        "month": b_date.month,
                        "is_today": is_today
                    })
        birthdays.sort(key=lambda x: x['day'])
        
        # Contracts (45 and 90 days from admission) - Filtered by Shift, exclude fired
        contracts = []
        for emp in all_employees:
            if emp.status == 'fired':
                continue
            emp_shift_norm = normalize_str(emp.work_shift)
            if target_shift_norm not in emp_shift_norm:
                continue

            if emp.admission_date:
                adm = emp.admission_date.date()
                
                # 45 Days
                d45 = adm + timedelta(days=45)
                days_to_45 = (d45 - params_date).days
                
                # 90 Days
                d90 = adm + timedelta(days=90)
                days_to_90 = (d90 - params_date).days
                
                # Show if within next 30 days of the milestone
                if 0 <= days_to_45 <= 30:
                     contracts.append({
                        "name": emp.name,
                        "date": d45.strftime("%d/%m"),
                        "days": days_to_45,
                        "type": "45 Dias"
                     })
                     
                if 0 <= days_to_90 <= 30:
                     contracts.append({
                        "name": emp.name,
                        "date": d90.strftime("%d/%m"),
                        "days": days_to_90,
                        "type": "90 Dias"
                     })
                     
        contracts.sort(key=lambda x: x['days'])

        return templates.TemplateResponse("report_pdf.html", {
            "request": request,
            "date": datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y"),
            "shift": shift,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "snapshot": snapshot,
            "absences": absences,
            "unavail": unavail,
            "birthdays": birthdays,
            "contracts": contracts
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<h1>Erro ao Gerar RelatÃƒÆ’Ã‚Â³rio</h1><pre>{traceback.format_exc()}</pre>", status_code=500)

from sqlmodel import select
@app.get("/employees", response_class=HTMLResponse)
async def employees_page(request: Request, session: Session = Depends(get_session)):
    import traceback
    from fastapi import HTTPException
    try:
        return await _employees_page_impl(request, session)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in employees_page: {e}")
        traceback.print_exc() # Print to server log
        return HTMLResponse(content=f"<h1>Erro Interno (500)</h1><p>Detalhes no log do servidor.</p><pre>{str(e)}</pre>", status_code=500)
async def _employees_page_impl(request: Request, session: Session):
    # Auto-update statuses based on today's date
    update_vacation_statuses(session, datetime.now())
    # user = require_login(request)
    user = "debug_admin"
        # Fetch Employees (excluindo substituÃƒÆ’Ã‚Â­dos)
    employees = session.exec(
        select(models.Employee)
        .where(models.Employee.replaced_by.is_(None))
    ).all()
        # Calculate Stats
    total_active = sum(1 for e in employees if e.status == "active")
        # Fetch Targets (Create defaults if not exist)
    # Fetch Targets Algorithm
    # 1. Legacy HeadcountTarget (user manually input global target)
    legacy_targets = session.exec(select(models.HeadcountTarget)).all()
    if not legacy_targets:
        defaults = [
            models.HeadcountTarget(shift_name="ManhÃƒÆ’Ã‚Â£", target_value=50),
            models.HeadcountTarget(shift_name="Tarde", target_value=50),
            models.HeadcountTarget(shift_name="Noite", target_value=50)
        ]
        for d in defaults: session.add(d)
        session.commit()
        legacy_targets = session.exec(select(models.HeadcountTarget)).all()
        
    legacy_map = {t.shift_name: t.target_value for t in legacy_targets}

    # 2. Smart Flow Sector Targets (Sum of sector capacities)
    # This is the SOURCE OF TRUTH if sectors exist.
    all_sectors = session.exec(select(models.Sector)).all()
    sector_map_sum = {"ManhÃƒÆ’Ã‚Â£": 0, "Tarde": 0, "Noite": 0}
    has_sectors = False
    
    for sec in all_sectors:
        # Normalize shift name just in case
        sec_shift_norm = "ManhÃƒÆ’Ã‚Â£"
        if "tarde" in sec.shift.lower(): sec_shift_norm = "Tarde"
        elif "noite" in sec.shift.lower(): sec_shift_norm = "Noite"
        
        sector_map_sum[sec_shift_norm] += sec.max_employees
        has_sectors = True
        
    # Decision: User stated /employees is OFFICIAL.
    # So we MUST prioritize the Manual Target (Legacy) over Sector Sum key-by-key.
    # Sector Sum is operational capacity, but Target is HR Budget.
    
    target_map = {}
    for s in ["ManhÃƒÆ’Ã‚Â£", "Tarde", "Noite"]:
        manual_val = legacy_map.get(s, 0)
        sector_val = sector_map_sum[s]
        
        # If manual value is set (exists in DB and > 0, or just exists?), prioritize it.
        # But we treated 0 as 'not set' or 'default'.
        # Let's trust the DB. If user saved 41, use 41.
        if manual_val > 0:
             target_map[s] = manual_val
        elif sector_val > 0:
             target_map[s] = sector_val
        else:
             target_map[s] = 0

    total_target = sum(target_map.values())
    
        # Shift Stats
    shifts = ["ManhÃƒÆ’Ã‚Â£", "Tarde", "Noite"]
    shift_stats = []
        # Init counters for each shift
    shift_data = {
        "ManhÃƒÆ’Ã‚Â£": {"active": 0, "vacation": 0, "away": 0},
        "Tarde": {"active": 0, "vacation": 0, "away": 0},
        "Noite": {"active": 0, "vacation": 0, "away": 0}
    }
    # Helper to determine shift from work_shift
    def get_shift_name(shift_val):
        s = (shift_val or "").strip().lower()
        if "noite" in s: return "Noite"
        if "tarde" in s: return "Tarde"
        # Default to ManhÃƒÆ’Ã‚Â£ only if explicitly ManhÃƒÆ’Ã‚Â£ or fallback
        return "ManhÃƒÆ’Ã‚Â£"
    # LÃƒÆ’Ã¢â‚¬Å“GICA ATUALIZADA:
    # - Afastados NÃƒÆ’Ã†â€™O contam no total de colaboradores (viram vagas temporÃƒÆ’Ã‚Â¡rias)
    # - Quando um afastado retornar, alguÃƒÆ’Ã‚Â©m serÃƒÆ’Ã‚Â¡ demitido para fechar o quadro
    # - Total efetivo = ativos + fÃƒÆ’Ã‚Â©rias (fÃƒÆ’Ã‚Â©rias ÃƒÆ’Ã‚Â© temporÃƒÆ’Ã‚Â¡rio, retorna normalmente)
    # - Vagas = target - total_efetivo (afastados geram vagas)
    
    total_effective_headcount = 0  # Ativos + FÃƒÆ’Ã‚Â©rias (exclui afastados)
    total_away = 0  # Contador separado de afastados
    
    for e in employees:
        if e.status == "fired":
            continue
        # Determine shift
        s_name = get_shift_name(e.work_shift)
        # Increment specific status counter for that shift
        if e.status == "active":
            shift_data[s_name]["active"] += 1
            total_effective_headcount += 1
        elif e.status == "vacation":
            shift_data[s_name]["vacation"] += 1
            total_effective_headcount += 1  # FÃƒÆ’Ã‚Â©rias conta no quadro (retorno normal)
        elif e.status == "away":
            shift_data[s_name]["away"] += 1
            total_away += 1  # Afastados NÃƒÆ’Ã†â€™O contam (viram vaga temporÃƒÆ’Ã‚Â¡ria)
        
    for s in shifts:
        data = shift_data.get(s, {"active":0, "vacation":0, "away":0})
        active_count = data["active"]
        vacation_count = data["vacation"]
        away_count = data["away"]
        
        # Headcount efetivo do turno = ativos + fÃƒÆ’Ã‚Â©rias (exclui afastados)
        # Afastados geram vagas temporÃƒÆ’Ã‚Â¡rias que precisam ser preenchidas por substitutos
        effective_shift_headcount = active_count + vacation_count
        
        target = target_map.get(s, 0)
        
        # Vagas = target - headcount_efetivo
        # Afastados automaticamente viram vagas atÃƒÆ’Ã‚Â© retornarem
        shift_vacancies = max(0, target - effective_shift_headcount)
        
        shift_stats.append({
            "name": s,
            "count": active_count,  # Ativos trabalhando
            "headcount": effective_shift_headcount,  # Efetivo (exclui afastados)
            "vacation": vacation_count,
            "away": away_count,  # Afastados (mostrar separado mas nÃƒÆ’Ã‚Â£o conta no quadro)
            "target": target,
            "vacancies": shift_vacancies
        })
        
    # Status Stats (Global)
    status_stats = {
        "vacation": sum(1 for e in employees if e.status == "vacation"),
        "away": sum(1 for e in employees if e.status == "away"),
        "fired": sum(1 for e in employees if e.status == "fired")
    }
    
    # Vagas totais = target - headcount_efetivo
    # Isso inclui automaticamente os afastados como vagas temporÃƒÆ’Ã‚Â¡rias
    total_vacancies = max(0, total_target - total_effective_headcount)
    
    return templates.TemplateResponse("employees.html", {
        "request": request,
        "user": user,
        "employees": employees,
        "stats": {
            "total_active": total_effective_headcount,  # Efetivo (exclui afastados)
            "total_target": total_target,
            "vacancies": total_vacancies,  # Inclui afastados como vagas
            "total_away": total_away,  # Afastados separados (para referÃƒÆ’Ã‚Âªncia)
            "shifts": shift_stats,
            "statuses": status_stats,
            "targets_map": target_map
        },
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success")
    })

class HeadcountTargetUpdate(BaseModel):
    targets: dict[str, int] # e.g. {"ManhÃƒÆ’Ã‚Â£": 50, "Tarde": 40}

@app.post("/api/employees/targets")
async def update_headcount_targets(data: HeadcountTargetUpdate, session: Session = Depends(get_session)):
    try:
        # Update or Create
        for shift_name, val in data.targets.items():
            db_target = session.exec(select(models.HeadcountTarget).where(models.HeadcountTarget.shift_name == shift_name)).first()
            if db_target:
                db_target.target_value = val
                session.add(db_target)
            else:
                session.add(models.HeadcountTarget(shift_name=shift_name, target_value=val))
        
        session.commit()
        return {"success": True}
    except Exception as e:
        print(f"Error updating targets: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
@app.get("/employees/candidates", response_class=JSONResponse)
async def get_candidates(request: Request, status: str, session: Session = Depends(get_session)):
    require_login(request)
    # Filter by status (fired or away) AND not already replaced
    employees = session.exec(
        select(models.Employee)
        .where(models.Employee.status == status)
        .where(models.Employee.replaced_by == None)  # Exclude already replaced
    ).all()
    return [{
        "id": e.id,
        "name": e.name,
        "registration_id": e.registration_id
    } for e in employees]

@app.post("/employees/add")
async def add_employee(
    request: Request,
    name: str = Form(...),
    registration_id: str = Form(...),
    seller_code: str = Form(None),
    role: str = Form(...),
    work_shift: str = Form(...),
    cost_center: str = Form(...),
    admission_date: str = Form(None),
    birthday: str = Form(None),
    work_days: List[str] = Form(None),
    # Substitution Fields
    is_substitution: bool = Form(False), # Checkbox key presence or explicit true/false if JS sends it
    sub_reason: str = Form(None), # fired, away
    replaced_employee_id: int = Form(None),
    session: Session = Depends(get_session)
):
    require_login(request)
    # Parse dates if provided
    admission_dt = None
    if admission_date:
        try:
            admission_dt = datetime.strptime(admission_date, "%Y-%m-%d")
        except:
            pass
            
    birthday_dt = None
    if birthday:
        try:
            birthday_dt = datetime.strptime(birthday, "%Y-%m-%d")
        except:
            pass
    
    # Process work_days
    work_days_json = '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]'  # Default
    if work_days:
        work_days_json = json.dumps(work_days)
    
    # Auto-assign Schedule based on Shift
    default_schedule = None
    s_lower = (work_shift or "").lower()
    if "manhÃƒÆ’Ã‚Â£" in s_lower or "manha" in s_lower:
        default_schedule = "05:00 - 13:20"
    elif "tarde" in s_lower:
        default_schedule = "12:00 - 20:20"
    elif "noite" in s_lower:
        default_schedule = "18:00 - 06:00"

    new_employee = models.Employee(
        name=name,
        registration_id=registration_id,
        seller_code=seller_code.strip() if seller_code else None,
        role=role,
        work_shift=work_shift,
        cost_center=cost_center,
        admission_date=admission_dt,
        birthday=birthday_dt,
        work_days=work_days_json,
        work_schedule=default_schedule,
        status="active"
    )
    try:
        session.add(new_employee)
        session.flush() # Flush to get ID if needed, though we just need to commit later
        
        # Substitution Logic
        if is_substitution and replaced_employee_id:
            old_emp = session.get(models.Employee, replaced_employee_id)
            if old_emp:
                # Marcar colaborador antigo como substituÃƒÆ’Ã‚Â­do
                old_emp.replaced_by = new_employee.id
                session.add(old_emp)
                
                # 1. History for New Employee
                # "Entrou em substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o a X (Motivo)"
                reason_pt = "Demitido" if sub_reason == 'fired' else "Afastado"
                new_evt = models.Event(
                    text=f"Entrou em substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o a {old_emp.name} ({reason_pt})",
                    type="alteracao_cadastro",
                    category="pessoas",
                    employee_id=new_employee.id,
                    sector="RH"
                )
                session.add(new_evt)
                
                # 2. History for Old Employee
                # "SubstituÃƒÆ’Ã‚Â­do por Y (Data)"
                old_evt = models.Event(
                    text=f"SubstituÃƒÆ’Ã‚Â­do por {new_employee.name}",
                    type="alteracao_cadastro",
                    category="pessoas",
                    employee_id=old_emp.id,
                    sector="RH"
                )
                session.add(old_evt)
                
                # 3. Registrar no HistÃƒÆ’Ã‚Â³rico de SubstituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes
                try:
                    user = require_login(request)
                    registered_by = user.email if hasattr(user, 'email') else str(user)
                except:
                    registered_by = "sistema"
                
                substitution_record = models.SubstitutionHistory(
                    original_employee_id=old_emp.id,
                    original_employee_name=old_emp.name,
                    original_registration_id=old_emp.registration_id,
                    new_employee_id=new_employee.id,
                    new_employee_name=new_employee.name,
                    new_registration_id=new_employee.registration_id,
                    reason=sub_reason or 'fired',
                    shift=old_emp.work_shift,
                    sector=old_emp.cost_center,
                    registered_by=registered_by
                )
                session.add(substitution_record)
        
        session.commit()
        session.commit()
    except Exception as e:
        print(f"Error adding employee: {e}")
        return RedirectResponse(url=f"/employees?error=Erro ao adicionar colaborador: {str(e)}", status_code=status.HTTP_303_SEE_OTHER)
    
    return RedirectResponse(url="/employees?success=Colaborador adicionado com sucesso", status_code=status.HTTP_303_SEE_OTHER)
@app.get("/employees/{employee_id}", response_class=HTMLResponse)
async def employee_detail(
    request: Request,
    employee_id: int,
    date: Optional[str] = None,
    session: Session = Depends(get_session)
):
    user = require_login(request)
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/employees")
    
    # Adjust for Timezone (UTC to BRT approx or Shift logic)
    # If server is UTC, now() might be tomorrow. If server is BRT, -3h is still same day (usually).
    today = datetime.now() - timedelta(hours=3)
    today_date = today.date()
    base_date = safe_parse_iso_date(date) or today_date

    absence_period_label = "MÃƒÆ’Ã‚Âªs"
    absence_start_date, absence_end_date = get_period_range(base_date, "monthly")
    absence_summary = get_absence_summary(
        session,
        employee.id,
        absence_start_date,
        absence_end_date,
        include_day_map=True
    )
    absence_start_str = absence_start_date.strftime("%Y-%m-%d")
    absence_end_str = absence_end_date.strftime("%Y-%m-%d")
    absence_debug = LOG_LEVEL == logging.DEBUG
    absence_debug_info = None
    if absence_debug:
        absence_start_dt = datetime.combine(absence_start_date, datetime.min.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
        absence_end_dt = datetime.combine(absence_end_date, datetime.max.time()).replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
        routine_count_query = (
            select(func.count(models.EmployeeRoutine.id))
            .where(models.EmployeeRoutine.employee_id == employee_id)
            .where(models.EmployeeRoutine.date >= absence_start_str)
            .where(models.EmployeeRoutine.date <= absence_end_str)
        )
        event_count_query = (
            select(func.count(models.Event.id))
            .where(models.Event.employee_id == employee_id)
            .where(models.Event.timestamp >= absence_start_dt)
            .where(models.Event.timestamp <= absence_end_dt)
        )
        try:
            routine_count = session.exec(routine_count_query).one() or 0
        except Exception:
            routine_count = 0
        try:
            event_count = session.exec(event_count_query).one() or 0
        except Exception:
            event_count = 0
        absence_debug_info = {
            "employee_id": employee.id,
            "registration_id": getattr(employee, "registration_id", None),
            "routine_count": routine_count,
            "event_count": event_count
        }

    # --- XP Stats Calculation ---
    # --- XP Stats Calculation ---
    # Tonnage (Production)
    # Daily
    daily_tonnage = session.exec(select(func.sum(models.Route.tonnage)).where(
        models.Route.employee_id == employee.id, 
        models.Route.date == today.strftime("%Y-%m-%d"),
        models.Route.tonnage > 0
    )).one() or 0.0
    
    # Weekly
    start_week = today - timedelta(days=6)
    weekly_tonnage = session.exec(select(func.sum(models.Route.tonnage)).where(
        models.Route.employee_id == employee.id, 
        models.Route.date >= start_week.strftime("%Y-%m-%d"),
        models.Route.tonnage > 0
    )).one() or 0.0
    
    # Monthly
    start_month = today.replace(day=1)
    monthly_tonnage = session.exec(select(func.sum(models.Route.tonnage)).where(
        models.Route.employee_id == employee.id, 
        models.Route.date >= start_month.strftime("%Y-%m-%d"),
        models.Route.tonnage > 0
    )).one() or 0.0

    # XP Points (Gamification)
    # Daily
    daily_xp = session.exec(select(func.sum(models.GameXPTransaction.amount)).where(
        models.GameXPTransaction.employee_id == employee.id, 
        models.GameXPTransaction.created_at >= today.replace(hour=0, minute=0, second=0, microsecond=0),
        models.GameXPTransaction.status == 'confirmed'
    )).one() or 0.0

    # Weekly
    weekly_xp = session.exec(select(func.sum(models.GameXPTransaction.amount)).where(
        models.GameXPTransaction.employee_id == employee.id, 
        models.GameXPTransaction.created_at >= start_week.replace(hour=0, minute=0, second=0, microsecond=0),
        models.GameXPTransaction.status == 'confirmed'
    )).one() or 0.0

    # Monthly
    monthly_xp = session.exec(select(func.sum(models.GameXPTransaction.amount)).where(
        models.GameXPTransaction.employee_id == employee.id, 
        models.GameXPTransaction.created_at >= start_month.replace(hour=0, minute=0, second=0, microsecond=0),
        models.GameXPTransaction.status == 'confirmed'
    )).one() or 0.0

    def fmt_br(val):
        return f"{val:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    def fmt_br_int(val):
        return f"{val:,.0f}".replace(",", ".")
    
    xp_stats = {
        "tonnage": {
            "daily": fmt_br(daily_tonnage),
            "weekly": fmt_br(weekly_tonnage),
            "monthly": fmt_br(monthly_tonnage)
        },
        "points": {
            "daily": fmt_br_int(daily_xp),
            "weekly": fmt_br_int(weekly_xp),
            "monthly": fmt_br_int(monthly_xp),
            "total": fmt_br_int(employee.total_xp or 0.0)
        }
    }

    # Calculate Tenure
    tenure_str = "-"
    if employee.admission_date:
        delta = today.date() - employee.admission_date.date()
        years = delta.days // 365
        months = (delta.days % 365) // 30
        tenure_str = f"{years} anos, {months} meses"

    # Count events
    all_events = session.exec(select(models.Event).where(models.Event.employee_id == employee_id).order_by(models.Event.timestamp.desc())).all()
    
    warnings = len([e for e in all_events if e.type == 'advertencia'])
    
    # Deduplicar eventos para timeline: manter apenas 1 por (data, tipo) para tipos de ausÃƒÆ’Ã‚Âªncia
    # Tipos que devem ser deduplicados por dia
    DEDUPE_TYPES = {"falta", "atestado", "afastamento", "folga", "dayoff", "sick", "absent", "away"}
    seen_day_type = set()
    events = []
    for ev in all_events:
        ev_type = (ev.type or "").lower()
        if ev_type in DEDUPE_TYPES:
            # Extrair data do timestamp
            ev_date = ev.timestamp.date() if ev.timestamp else None
            dedupe_key = (ev_date, ev_type)
            if dedupe_key in seen_day_type:
                continue  # JÃƒÆ’Ã‚Â¡ vimos esse tipo nesse dia
            seen_day_type.add(dedupe_key)
        events.append(ev)
    absence_counts = absence_summary["days"]
    medicals = absence_counts["justified"]
    absences = absence_counts["unjustified"]
    leave_days = absence_counts["leave"]
    offday_days = absence_counts["offday"]
    routine_days_logged = absence_summary["routine_days_logged"]
    logs_day_map = absence_summary.get("logs_day_map", {})
    logs_record_map = absence_summary.get("logs_record_ids", {}) if absence_debug else {}

    absence_history = {
        "falta": [],
        "atestado": [],
        "afastamento": [],
        "folga": []
    }
    for entry in absence_summary.get("day_map", []):
        group = entry.get("group")
        if group not in ["unjustified", "justified", "leave", "offday"]:
            continue
        day_key = entry.get("date")
        logs_count = logs_day_map.get(day_key, {}).get(group, 0)
        record_ids = logs_record_map.get(day_key, {}).get(group, [])
        mapped = {
            "date": entry.get("date"),
            "date_br": fmt_ddmmyyyy(entry.get("date")),
            "group": group,
            "source": entry.get("source"),
            "source_label": format_absence_source_label(entry.get("source")),
            "record_id": entry.get("record_id"),
            "logs_count": logs_count,
            "record_ids": record_ids
        }
        if group == "unjustified":
            absence_history["falta"].append(mapped)
        elif group == "justified":
            absence_history["atestado"].append(mapped)
        elif group == "leave":
            absence_history["afastamento"].append(mapped)
        elif group == "offday":
            absence_history["folga"].append(mapped)
    
    stats = {
        "advertencias": warnings,
        "atestados": medicals,
        "faltas": absences,
        "afastamentos": leave_days,
        "folgas": offday_days,
        "rotinas_periodo": routine_days_logged,
        "ausencias_origem": absence_summary.get("source_label"),
        "ferias": len([e for e in events if e.type == 'ferias'])
    }
    # Parse Work Days for Display
    work_days_list = []
    if employee.work_days:
        try:
            wd_val = employee.work_days
            # Check if it looks like JSON list
            if wd_val.strip().startswith("["):
                 work_days_list = json.loads(wd_val)
            else:
                 # Assume comma separated or single string if not JSON? 
                 # Or just wrap single string.
                 work_days_list = [wd_val]
        except:
            work_days_list = [] # Fallback
            
    days_map = {'Monday': 'Segunda', 'Tuesday': 'TerÃƒÆ’Ã‚Â§a', 'Wednesday': 'Quarta', 'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'SÃƒÆ’Ã‚Â¡bado', 'Sunday': 'Domingo'}
    # Translate immediately for simpler template
    work_days_display = ", ".join([days_map.get(d, d) for d in work_days_list])

    # Fetch Routines for the current absence period
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.employee_id == employee_id)
        .where(models.EmployeeRoutine.date >= absence_start_str)
        .where(models.EmployeeRoutine.date <= absence_end_str)
        .order_by(models.EmployeeRoutine.date.desc())
    ).all()

    # Fetch XP Ledger (Last 50) - V2
    xp_ledger = session.exec(
        select(models.GameXPTransaction)
        .where(models.GameXPTransaction.employee_id == employee_id)
        .order_by(models.GameXPTransaction.created_at.desc())
        .limit(50)
    ).all()
    # Normalize for template generic access if needed, match GameXPTransaction fields
    # Template uses: x.points (V1) or x.amount (V2), x.reason.
    # We must alias or update template. x.points -> x.amount
    # OR: modify the object list to have .points via mapping?
    # Better: Update template to check x.amount OR alias here?
    # I'll update template to use x.amount. (Next step)


    # Fetch Daily Allocation/Activity Data (Range Search: Yesterday, Today, Tomorrow)
    # This handles timezone diffs and future planning
    search_dates = [
        (today - timedelta(days=1)).strftime("%Y-%m-%d"),
        today.strftime("%Y-%m-%d"),
        (today + timedelta(days=1)).strftime("%Y-%m-%d")
    ]
    
    # Fetch operations in range (ignoring shift filter to catch extra hours/changes)
    daily_ops = session.exec(select(models.DailyOperation).where(
        col(models.DailyOperation.date).in_(search_dates)
    ).order_by(desc(models.DailyOperation.date), desc(models.DailyOperation.created_at))).all()

    current_allocation = None
    current_activity = None
    
    # Priority Strategy: Prefer TODAY matching Shift, then TODAY any shift, then TOMORROW/YESTERDAY
    # For simplicity: Just pick the FIRST one (Latest date) that has data for this user.
    # Because we ordered by Date DESC, we will see Tomorrow -> Today -> Yesterday.
    # If planned for tomorrow, we show it. If working today, we show it.
    
    # Pre-fetch Sector Metadata for Fallback (Legacy Logs compatibility)
    sectors_db = session.exec(select(models.Sector)).all()
    subsectors_db = session.exec(select(models.SubSector)).all()
    
    # Map normalized key -> Pretty Name (Re-create normalization logic or fuzzy match?)
    # Since we don't store key in DB easily, we rely on the log['sector'] key.
    # But wait, we can just map simple lookup if needed, OR relies on 'sector_name' being populated in new saves.
    # Ideally, we should just assume new saves work manually re-saving solves it.
    # BUT user is complaining NOW. 
    # Let's try to infer from allocations table IF log is missing info?
    # No, allocations table is the source of truth for "Allocations". Log is for "Snapshot".
    # Let's check EmployeeAllocation table as well!
    
    # Strategy V2: Check EmployeeAllocation TABLE first (Source of Truth for Allocation), 
    # then fallback to Log (Snapshot). Application saves both.
    
    alloc_db = session.exec(select(models.EmployeeAllocation).where(
        models.EmployeeAllocation.employee_id == employee.id,
        models.EmployeeAllocation.date == today.strftime("%Y-%m-%d")
    )).first()
    
    # Override/Augment current_allocation with DB data if found (Most accurate/recent)
    if alloc_db:
        # Resolve names
        sub_obj = session.get(models.SubSector, alloc_db.subsector_id)
        if sub_obj:
            sec_obj = session.get(models.Sector, sub_obj.sector_id)
            if sec_obj:
                current_allocation = {
                    "sector": sec_obj.name,
                    "subsector": sub_obj.name,
                    "date": alloc_db.date,
                    "shift": alloc_db.shift
                }

    # If DB allocation not found (maybe historic/yesterday?), try Log 
    if not current_allocation:
         str_reg_id = str(employee.registration_id)
         for op in daily_ops:
            if op and op.attendance_log:
                log_entry = op.attendance_log.get(str_reg_id)
                if log_entry:
                    sec_name = log_entry.get("sector_name")
                    # Fallback logic for legacy keys
                    if not sec_name and log_entry.get("sector"):
                        # Try to format raw key (e.g. 'expedicao' -> 'Expedicao')
                        sec_name = log_entry.get("sector").replace("_", " ").title()
                        
                    if sec_name:
                        current_allocation = {
                            "sector": sec_name,
                            "subsector": log_entry.get("subsector_name") or "-",
                            "date": op.date,
                            "shift": op.shift
                        }
                    
                    if log_entry.get("activity") or log_entry.get("observation"):
                        current_activity = {
                            "name": log_entry.get("activity"),
                            "observation": log_entry.get("observation"),
                            "date": op.date
                        }
                    if current_allocation or current_activity:
                        break

    # Buscar informaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes de substituiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
    substitution_info = None
    replaced_employee = None
    
    # Verificar se este colaborador SUBSTITUIU alguÃƒÆ’Ã‚Â©m (ÃƒÆ’Ã‚Â© novo e substituiu)
    sub_as_new = session.exec(
        select(models.SubstitutionHistory)
        .where(models.SubstitutionHistory.new_employee_id == employee_id)
    ).first()
    
    # Verificar se este colaborador FOI SUBSTITUÃƒÆ’Ã‚ÂDO (saiu e foi substituÃƒÆ’Ã‚Â­do)
    sub_as_old = session.exec(
        select(models.SubstitutionHistory)
        .where(models.SubstitutionHistory.original_employee_id == employee_id)
    ).first()
    
    if sub_as_new:
        substitution_info = {
            "type": "substituted",
            "original_name": sub_as_new.original_employee_name,
            "original_registration": sub_as_new.original_registration_id,
            "original_id": sub_as_new.original_employee_id,
            "reason": "DemissÃƒÆ’Ã‚Â£o" if sub_as_new.reason == 'fired' else "Afastamento",
            "date": sub_as_new.substitution_date.strftime("%d/%m/%Y")
        }
    
    if sub_as_old:
        replaced_employee = {
            "type": "was_replaced",
            "new_name": sub_as_old.new_employee_name,
            "new_registration": sub_as_old.new_registration_id,
            "new_id": sub_as_old.new_employee_id,
            "reason": "DemissÃƒÆ’Ã‚Â£o" if sub_as_old.reason == 'fired' else "Afastamento",
            "date": sub_as_old.substitution_date.strftime("%d/%m/%Y")
        }

    return templates.TemplateResponse("employee_detail.html", {
        "request": request, 
        "emp": employee, 
        "events": events, 
        "user": user,
        "stats": stats,
        "tenure": tenure_str,
        "work_days_display": work_days_display,
        "routines": routines,
        "xp_stats": xp_stats,
        "xp_ledger": xp_ledger,
        "absence_period_label": absence_period_label,
        "absence_period_range": {
            "start": absence_start_date.strftime("%d/%m/%Y"),
            "end": absence_end_date.strftime("%d/%m/%Y")
        },
        "absence_history": absence_history,
        "absence_day_map": absence_summary.get("day_map", []),
        "absence_debug": absence_debug,
        "absence_debug_info": absence_debug_info,
        "absence_debug_days": absence_summary.get("debug_days", []),
        "absence_debug_unknown_labels": absence_summary.get("debug_unknown_labels", []),
        "current_allocation": current_allocation,
        "current_activity": current_activity,
        "substitution_info": substitution_info,
        "replaced_employee": replaced_employee,
        "today_date": datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    })
@app.post("/employees/{emp_id}/status")
async def update_employee_status(
    emp_id: int,
    request: Request,
    status_action: str = Form(...), # active, vacation, away, fired, delete
    session: Session = Depends(get_session)
):
    require_login(request)
    emp = session.get(models.Employee, emp_id)
    if emp:
        if status_action == "delete":
            # Explicitly fetch and unlink all related records to ensure no FK constraints block deletion
            
            # Unlink Events
            stmt = select(models.Event).where(models.Event.employee_id == emp_id)
            events = session.exec(stmt).all()
            for event in events:
                event.employee_id = None
                session.add(event)
            
            # Delete GameXPTransactions (or unlink if needed)
            from sqlmodel import delete as sql_delete
            session.exec(sql_delete(models.GameXPTransaction).where(models.GameXPTransaction.employee_id == emp_id))
            
            # Delete XPLedger entries
            session.exec(sql_delete(models.XPLedger).where(models.XPLedger.employee_id == emp_id))
            
            # Delete EmployeeAchievements
            session.exec(sql_delete(models.EmployeeAchievement).where(models.EmployeeAchievement.employee_id == emp_id))
            
            # Delete EmployeeRoutines
            session.exec(sql_delete(models.EmployeeRoutine).where(models.EmployeeRoutine.employee_id == emp_id))
            
            # Delete EmployeeAllocations
            session.exec(sql_delete(models.EmployeeAllocation).where(models.EmployeeAllocation.employee_id == emp_id))
            
            # Unlink Routes
            routes = session.exec(select(models.Route).where(models.Route.employee_id == emp_id)).all()
            for route in routes:
                session.delete(route)
            
            # Unlink TranspalletChecklists
            checklists = session.exec(select(models.TranspalletChecklist).where(models.TranspalletChecklist.employee_id == emp_id)).all()
            for cl in checklists:
                session.delete(cl)
            
            # Unlink EquipmentTickets
            tickets = session.exec(select(models.EquipmentTicket).where(models.EquipmentTicket.employee_id == emp_id)).all()
            for ticket in tickets:
                session.delete(ticket)
            
            # Unlink AbsenceAlertLogs
            session.exec(sql_delete(models.AbsenceAlertLog).where(models.AbsenceAlertLog.employee_id == emp_id))
            
            # Unlink PalletCounts
            session.exec(sql_delete(models.PalletCount).where(models.PalletCount.employee_id == emp_id))
            
            # Unlink PalletMaintenanceTickets
            session.exec(sql_delete(models.PalletMaintenanceTicket).where(models.PalletMaintenanceTicket.employee_id == emp_id))
            
            # Unlink LeaderTaskResponses
            session.exec(sql_delete(models.LeaderTaskResponse).where(models.LeaderTaskResponse.employee_id == emp_id))
            
            # Handle replaced_by self-reference
            replacers = session.exec(select(models.Employee).where(models.Employee.replaced_by == emp_id)).all()
            for r in replacers:
                r.replaced_by = None
                session.add(r)
            
            # Handle SubstitutionHistory
            session.exec(sql_delete(models.SubstitutionHistory).where(models.SubstitutionHistory.original_employee_id == emp_id))
            session.exec(sql_delete(models.SubstitutionHistory).where(models.SubstitutionHistory.new_employee_id == emp_id))
            
            # Unlink User if linked
            user_linked = session.exec(select(models.User).where(models.User.employee_id == emp_id)).first()
            if user_linked:
                user_linked.employee_id = None
                session.add(user_linked)
            
            session.delete(emp)
        else:
            # Generate History Event
            event_type = "ocorrencia"
            text_desc = f"Status alterado para {status_action}"
            if status_action == "vacation":
                event_type = "ferias_hist"
                text_desc = "Entrou em FÃƒÆ’Ã‚Â©rias"
            elif status_action == "fired":
                event_type = "demissao"
                text_desc = "Colaborador Demitido"
            elif status_action == "away":
                event_type = "afastamento"
                text_desc = "Colaborador Afastado"
            elif status_action == "active":
                event_type = "retorno"
                text_desc = "Colaborador Reativado (Retorno)"
            elif status_action == "falta":
                event_type = "falta"
                text_desc = f"Registrou Falta em {datetime.now().strftime('%d/%m/%Y')}"
            elif status_action == "atestado":
                event_type = "atestado"
                text_desc = f"Apresentou Atestado em {datetime.now().strftime('%d/%m/%Y')}"
            
            # Translate Routine Change log
            if event_type == "ocorrencia" and "Status alterado" in text_desc:
                 # Map internal status to Portuguese
                 status_map = {
                     "active": "Ativo",
                     "vacation": "FÃƒÆ’Ã‚Â©rias",
                     "away": "Afastado",
                     "fired": "Demitido",
                     "day_off": "Folga"
                 }
                 pt_status = status_map.get(status_action, status_action)
                 text_desc = f"AlteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de Rotina ({datetime.now().strftime('%d/%m/%Y')}): {pt_status}"
                 
            new_event = models.Event(
                text=text_desc,
                type=event_type,
                category="pessoas",
                employee_id=emp.id,
                shift_id=None 
            )
            session.add(new_event)
            emp.status = status_action
            
            # Preencher termination_date automaticamente para demissÃƒÆ’Ã‚Â£o/afastamento
            if status_action in ("fired", "away"):
                if not emp.termination_date:
                    emp.termination_date = datetime.now()
            # Limpar termination_date se reativar
            elif status_action == "active":
                emp.termination_date = None
            
            session.add(emp)
        session.commit()
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/employees/{emp_id}/return")
async def return_employee_from_leave(
    emp_id: int,
    request: Request,
    return_date: str = Form(...),
    session: Session = Depends(get_session)
):
    """
    Retorna um colaborador de fÃƒÆ’Ã‚Â©rias/atestado/afastamento.
    Atualiza o status para 'active', limpa datas de fÃƒÆ’Ã‚Â©rias e atualiza rotinas.
    """
    require_login(request)
    emp = session.get(models.Employee, emp_id)
    
    if not emp:
        raise HTTPException(status_code=404, detail="Colaborador nÃƒÆ’Ã‚Â£o encontrado")
    
    previous_status = emp.status
    br_tz = ZoneInfo("America/Sao_Paulo")
    
    # Parse da data de retorno
    try:
        return_dt = datetime.strptime(return_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Data de retorno invÃƒÆ’Ã‚Â¡lida")
    
    # Map do status anterior para texto descritivo
    status_map = {
        "vacation": "FÃƒÆ’Ã‚Â©rias",
        "away": "Afastamento",
        "sick": "Atestado",
        "fired": "DemissÃƒÆ’Ã‚Â£o",
        "day_off": "Folga"
    }
    previous_status_label = status_map.get(previous_status, previous_status)
    
    # 1. Atualizar status do colaborador para 'active'
    emp.status = "active"
    
    # 2. Limpar datas de fÃƒÆ’Ã‚Â©rias se existirem
    if emp.vacation_start or emp.vacation_end:
        emp.vacation_start = None
        emp.vacation_end = None
    
    session.add(emp)
    
    # 3. Criar evento de retorno
    event_text = f"{emp.name}: Retornou de {previous_status_label} em {return_dt.strftime('%d/%m/%Y')}"
    new_event = models.Event(
        timestamp=datetime.now(br_tz),
        text=event_text,
        type="retorno",
        category="pessoas",
        employee_id=emp.id
    )
    session.add(new_event)
    
    # 4. Atualizar rotinas: de return_date atÃƒÆ’Ã‚Â© hoje + 30 dias, marcar como 'present'
    today = datetime.now(br_tz).date()
    end_update_date = today + timedelta(days=30)
    current_date = return_dt.date()
    
    # Buscar rotinas existentes no perÃƒÆ’Ã‚Â­odo
    existing_routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.employee_id == emp_id)
        .where(models.EmployeeRoutine.date >= return_date)
        .where(models.EmployeeRoutine.date <= end_update_date.strftime("%Y-%m-%d"))
    ).all()
    
    # Agrupar por data
    existing_by_date = {}
    for r in existing_routines:
        if r.date not in existing_by_date:
            existing_by_date[r.date] = []
        existing_by_date[r.date].append(r)
    
    # Atualizar ou criar rotinas como 'present'
    routines_updated = 0
    routines_created = 0
    
    while current_date <= end_update_date:
        date_str = current_date.strftime("%Y-%m-%d")
        
        if date_str in existing_by_date:
            # Atualizar rotinas existentes que nÃƒÆ’Ã‚Â£o sÃƒÆ’Ã‚Â£o 'present'
            for routine in existing_by_date[date_str]:
                if routine.routine in ('vacation', 'away', 'sick', 'absent'):
                    routine.routine = 'present'
                    session.add(routine)
                    routines_updated += 1
        else:
            # Criar novas rotinas como 'present' para cada turno
            for shift_name in ["ManhÃƒÆ’Ã‚Â£", "Tarde", "Noite"]:
                new_routine = models.EmployeeRoutine(
                    date=date_str,
                    shift=shift_name,
                    employee_id=emp_id,
                    routine="present"
                )
                session.add(new_routine)
            routines_created += 1
        
        current_date += timedelta(days=1)
    
    session.commit()
    
    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ {emp.name} retornou de {previous_status_label}. Rotinas: {routines_updated} atualizadas, {routines_created} dias criados")
    
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/events/{event_id}/update_content")
async def update_event_content(
    event_id: int,
    request: Request,
    new_type: str = Form(...),
    new_date: str = Form(...),
    new_text: str = Form(...),
    session: Session = Depends(get_session)
):
    require_login(request)
    event = session.get(models.Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento nÃƒÆ’Ã‚Â£o encontrado")
    
    # Update fields
    event.type = new_type
    event.text = new_text
    
    # Parse Date (expecting YYYY-MM-DDTHH:MM or similar, or just keep existing time if only date provided)
    # The form input will likely be datetime-local or separate date/time. 
    # For now assume the input is ISO string or handle format.
    try:
        # If input is just date, preserve original time?
        # Let's assume input is full datetime-local "YYYY-MM-DDTHH:MM"
        if "T" in new_date:
            event.timestamp = datetime.fromisoformat(new_date)
        else:
            # Just Date
            old_time = event.timestamp.time()
            new_dt = datetime.fromisoformat(new_date)
            event.timestamp = datetime.combine(new_dt.date(), old_time)
            
    except:
        pass # Keep old date if fail
        
    session.add(event)
    session.commit()
    
    return RedirectResponse(url=f"/employees/{event.employee_id}", status_code=status.HTTP_303_SEE_OTHER)
@app.post("/events/{event_id}/delete")
async def delete_event(
    event_id: int,
    request: Request,
    session: Session = Depends(get_session)
):
    require_login(request)
    event = session.get(models.Event, event_id)
    if event:
        emp_id = event.employee_id
        session.delete(event)
        session.commit()
        return RedirectResponse(url=f"/employees/{emp_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)
@app.post("/events/{event_id}/update_vacation")
async def update_vacation_event(
    event_id: int,
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    session: Session = Depends(get_session)
):
    require_login(request)
    event = session.get(models.Event, event_id)
    if not event or event.type != 'ferias_hist':
        raise HTTPException(status_code=404, detail="Evento de fÃƒÆ’Ã‚Â©rias nÃƒÆ’Ã‚Â£o encontrado")
        emp = session.get(models.Employee, event.employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Colaborador nÃƒÆ’Ã‚Â£o encontrado")
    try:
        # Update Employee Dates
        v_start = datetime.strptime(start_date, "%Y-%m-%d")
        v_end = datetime.strptime(end_date, "%Y-%m-%d")
        # Update Event Text (BR Format)
        fmt_start = v_start.strftime("%d/%m/%Y")
        fmt_end = v_end.strftime("%d/%m/%Y")
        event.text = f"FÃƒÆ’Ã‚Â©rias Agendadas: {fmt_start} a {fmt_end}"
        session.add(event)
        
        emp.vacation_start = v_start
        emp.vacation_end = v_end
        
        # Re-eval Status
        today = datetime.now()
        check_start = v_start.replace(hour=0, minute=0, second=0, microsecond=0)
        check_end = v_end.replace(hour=23, minute=59, second=59, microsecond=999)
        
        if check_start <= today <= check_end:
            emp.status = 'vacation'
        else:
            if emp.status == 'vacation':
                emp.status = 'active'
                
        session.add(emp)
        session.commit()
    except ValueError:
        raise HTTPException(status_code=400, detail="Data invÃƒÆ’Ã‚Â¡lida")
        
    return RedirectResponse(url=f"/employees/{emp.id}", status_code=status.HTTP_303_SEE_OTHER)
class MobileAdminStartPayload(BaseModel):
    registration_id: str
    client_id: int
    tonnage: Optional[float] = 0.0

@app.post("/mobile/admin/start-route")
async def mobile_admin_start_route(
    payload: MobileAdminStartPayload,
    request: Request,
    session: Session = Depends(get_session)
):
    try:
        # Check if logged in user is leader
        user_id = request.session.get("user_id")
        if not user_id:
            # Fallback for Web Admin testing on mobile view
            auth_user_id = request.session.get("auth_user_id")
            if auth_user_id:
                # If logged in as User, try to find linked Employee
                user = session.get(models.User, auth_user_id)
                if user and user.employee_id:
                    user_id = user.employee_id
                else:
                    return JSONResponse({"error": "UsuÃƒÆ’Ã‚Â¡rio web sem colaborador vinculado"}, status_code=403)
            else:
                return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
            
        try:
            user_id = int(str(user_id))
        except:
             return JSONResponse({"error": "ID de usuÃƒÆ’Ã‚Â¡rio invÃƒÆ’Ã‚Â¡lido"}, status_code=400)
            
        current_emp = session.get(models.Employee, user_id)
        if not current_emp:
             return JSONResponse({"error": "LÃƒÆ’Ã‚Â­der nÃƒÆ’Ã‚Â£o encontrado"}, status_code=403)
             
        if not getattr(current_emp, "mobile_access_admin_start", False):
             return JSONResponse({"error": "Sem permissÃƒÆ’Ã‚Â£o de lÃƒÆ’Ã‚Â­der"}, status_code=403)

        # Find Target Employee
        target_emp = session.exec(select(models.Employee).where(models.Employee.registration_id == payload.registration_id)).first()
        if not target_emp:
            return JSONResponse({"error": "MatrÃƒÆ’Ã‚Â­cula nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
            
        # Verify Client Existence (Prevent FK Error)
        client = session.get(models.Client, payload.client_id)
        if not client:
             return JSONResponse({"error": "Cliente nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)

        # 1. Create Routine if needed (Safely)
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        routine = session.exec(select(models.EmployeeRoutine).where(
            models.EmployeeRoutine.employee_id == target_emp.id,
            models.EmployeeRoutine.date == today_str
        )).first()
        
        if not routine:
            try:
                routine = models.EmployeeRoutine(
                    employee_id=target_emp.id,
                    date=today_str,
                    shift=target_emp.work_shift or "ManhÃƒÆ’Ã‚Â£",
                    start_time=datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M"),
                    routine="present",
                    status="open"
                )
                session.add(routine)
                session.commit()
                session.refresh(routine)
            except Exception as e:
                # Ignore duplicate key if it was created in parallel
                session.rollback()
                routine = session.exec(select(models.EmployeeRoutine).where(
                    models.EmployeeRoutine.employee_id == target_emp.id,
                    models.EmployeeRoutine.date == today_str
                )).first()


        # 2. Create Route (Multiple routes allowed per employee)
        # 3. Create Route
        new_route = models.Route(
            employee_id=target_emp.id,
            client_id=payload.client_id,
            date=today_str,
            shift=target_emp.work_shift or "ManhÃƒÆ’Ã‚Â£",
            start_time=datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M"),
            status="pending",
            tonnage=payload.tonnage
        )
        session.add(new_route)
        
        # 4. Log
        log = models.Event(
            type="routine_change",
            text=f"Rota iniciada via Mobile (LÃƒÆ’Ã‚Â­der {current_emp.name}) para {target_emp.name}",
            category="processo",
            sector="expedicao",
            impact="low",
            employee_id=target_emp.id,
            timestamp=datetime.now(ZoneInfo("America/Sao_Paulo"))
        )
        session.add(log)
        
        session.commit()
        return JSONResponse({"success": True})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"Erro interno: {str(e)}"}, status_code=500)

@app.post("/employees/{emp_id}/update")
async def update_employee(
    emp_id: int,
    request: Request,
    name: str = Form(...),
    registration_id: str = Form(...),
    seller_code: str = Form(None),
    role: str = Form(...),
    work_shift: str = Form(...),
    cost_center: str = Form(...),
    admission_date: str = Form(None),
    birthday: str = Form(None),
    work_days: List[str] = Form(None),
    work_schedule: str = Form(None),
    mobile_access_separation: bool = Form(False),
    mobile_access_checklist: bool = Form(False),
    mobile_access_admin_start: bool = Form(False),
    vacation_start: str = Form(None),
    vacation_end: str = Form(None),
    session: Session = Depends(get_session)
):
    require_login(request)
    emp = session.get(models.Employee, emp_id)
    if emp:
        # Log Shift Change
        if emp.work_shift != work_shift:
            session.add(models.Event(
                text=f"Troca de Turno: {emp.work_shift} para {work_shift}",
                type="alteracao_cadastro",
                category="pessoas",
                employee_id=emp.id
            ))
                    # Log Role Change
        if emp.role != role:
            session.add(models.Event(
                text=f"AlteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de Cargo: {emp.role} para {role}",
                type="alteracao_cadastro",
                category="pessoas",
                employee_id=emp.id
            ))
        # Log Cost Center Change
        if emp.cost_center != cost_center:
            session.add(models.Event(
                text=f"AlteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de Centro de Custo: {emp.cost_center} -> {cost_center}",
                type="alteracao_cadastro",
                category="pessoas",
                employee_id=emp.id
            ))
            
        emp.name = name
        emp.registration_id = registration_id
        emp.seller_code = seller_code.strip() if seller_code else None
        emp.role = role
        emp.work_shift = work_shift
        emp.cost_center = cost_center
        emp.cost_center = cost_center
        emp.work_schedule = work_schedule
        emp.mobile_access_separation = mobile_access_separation
        emp.mobile_access_checklist = mobile_access_checklist
        emp.mobile_access_admin_start = mobile_access_admin_start
        emp.mobile_access = bool(mobile_access_separation or mobile_access_checklist)

        # Update Work Days
        if work_days:
             emp.work_days = json.dumps(work_days)
        else:
             # Check if it was sent as empty list (cleared) or not sent?
             # If form sends checkboxes, unchecked usually means not sent.
             # We should assume if the list is None/Empty but the request is an Update,
             # we might want to clear it? Or default?
             # Logic: If Form is present in request but empty... FastAPI makes it None usually.
             # Let's save a default "all days" or empty list if explicitly cleared?
             # Ideally if user unchecks all, we receive empty list.
             # BUT: FastAPI Form(None) defaults to None if key missing.
             # If key exists but empty values?
             # For safety: If update comes, we can overwrite. But checkboxes not checked simply don't send keys.
             # This is tricky with pure HTML forms.
             # If the frontend always sends at least one, we are good.
             # If we want to allow clearing all, we need a hidden input or assume None = Clear?
             # Let's assume if updated, we overwrite. If None, maybe don't change?
             # Actually, simpler: if work_days is None, it means NO checkbox checked (or key missing).
             # We should probably clear it if we want to support unchecking all.
             # However, to be safe against accidental clears if form is incomplete:
             # Let's only update if we have data OR if we explicitly handle "clear".
             # For now, let's just update if present. To allow "clearing", user usually leaves one checked.
             # To truly support clearing all, we'd need a hidden input with same name or JS handling.
             # Given the snippet, let's just save valid list if provided.
             pass
        
        # Actually, standard behavior for checkboxes: NOT sent if unchecked.
        # So verifying if we can differentiate "not submitted" vs "unchecked all".
        # We can't easily. But since this is a dedicated update form, we can assume
        # if the user submits the form, they see the checkboxes.
        # If work_days is None, it likely means they unchecked everything.
        # So let's save empty list "[]" if work_days is None? 
        # But wait, we set default Form(None).
        # Let's check how add_employee does it:
        # work_days_json = '["Monday"...]' # Default
        # if work_days: work_days_json = json.dumps(work_days)
        
        # Here: we want to UPDATE.
        # If work_days received (List[str]), we dump it.
        # If None, it means no box checked. Should we clear it? 
        # Yes, usually "Edit" means "Current State".
        # So: emp.work_days = json.dumps(work_days if work_days else [])
        
        if work_days is not None:
             emp.work_days = json.dumps(work_days)
        else:
             # Checkboxes not checked -> None
             emp.work_days = "[]"
        
        if admission_date:
            try:
                emp.admission_date = datetime.strptime(admission_date, "%Y-%m-%d")
            except:
                pass
                
        if birthday:
            try:
                emp.birthday = datetime.strptime(birthday, "%Y-%m-%d")
            except:
                pass
        
        # Processar fÃƒÆ’Ã‚Â©rias programadas
        if vacation_start and vacation_end:
            try:
                v_start = datetime.strptime(vacation_start, "%Y-%m-%d")
                v_end = datetime.strptime(vacation_end, "%Y-%m-%d")
                
                # Validar datas
                if v_start <= v_end:
                    old_v_start = emp.vacation_start
                    old_v_end = emp.vacation_end
                    
                    emp.vacation_start = v_start
                    emp.vacation_end = v_end
                    
                    # Verificar se hoje estÃƒÆ’Ã‚Â¡ dentro do perÃƒÆ’Ã‚Â­odo de fÃƒÆ’Ã‚Â©rias
                    today = datetime.now()
                    if v_start <= today <= v_end:
                        emp.status = 'vacation'
                    elif emp.status == 'vacation' and today > v_end:
                        # FÃƒÆ’Ã‚Â©rias acabaram, voltar para ativo
                        emp.status = 'active'
                    
                    # Log se houve alteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
                    if old_v_start != v_start or old_v_end != v_end:
                        session.add(models.Event(
                            text=f"FÃƒÆ’Ã‚Â©rias programadas: {v_start.strftime('%d/%m/%Y')} a {v_end.strftime('%d/%m/%Y')}",
                            type="ferias",
                            category="pessoas",
                            employee_id=emp.id
                        ))
            except Exception as e:
                print(f"Erro ao processar fÃƒÆ’Ã‚Â©rias: {e}")
        elif vacation_start == "" and vacation_end == "":
            # Se ambos foram limpos, limpar as fÃƒÆ’Ã‚Â©rias
            if emp.vacation_start or emp.vacation_end:
                emp.vacation_start = None
                emp.vacation_end = None
                if emp.status == 'vacation':
                    emp.status = 'active'
                session.add(models.Event(
                    text="FÃƒÆ’Ã‚Â©rias canceladas/removidas",
                    type="ferias",
                    category="pessoas",
                    employee_id=emp.id
                ))
                
        session.add(emp)
        session.commit()
        
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)
@app.post("/settings/targets")
async def update_targets(
    request: Request,
    session: Session = Depends(get_session)
):
    require_login(request)
    form_data = await request.form()
        # Iterate over form keys to find target_{shift}
    for key, value in form_data.items():
        if key.startswith("target_"):
            shift_name = key.replace("target_", "")
            try:
                val = int(value)
                # Check if exists
                stmt = select(models.HeadcountTarget).where(models.HeadcountTarget.shift_name == shift_name)
                target = session.exec(stmt).first()
                if target:
                    target.target_value = val
                    session.add(target)
                else:
                    new_target = models.HeadcountTarget(shift_name=shift_name, target_value=val)
                    session.add(new_target)
            except ValueError:
                pass
        session.commit()
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)
import pandas as pd
from fastapi import UploadFile, File
import io

class BulkImportData(pydantic.BaseModel):
    raw_text: str

@app.post("/api/import/occurrences")
async def import_occurrences(
    data: BulkImportData,
    session: Session = Depends(get_session)
):
    """
    Importa ocorrÃƒÆ’Ã‚Âªncias (Faltas/Atestados) a partir de texto copiado do Excel.
    Formato esperado: Matricula | Nome(Ignorado) | Data | OcorrÃƒÆ’Ã‚Âªncia
    """
    lines = data.raw_text.strip().split('\n')
    stats = {"total": 0, "success": 0, "errors": []}
    
    # Pre-fetch all active employees for validation
    employees = session.exec(select(models.Employee)).all()
    emp_map = {str(e.registration_id): e for e in employees}
    

    # Parse all lines first to gather requirements
    pending_entries = []
    
    # 1. First Pass: Parse and Validate Basic Format
    for line in lines:
        parts = line.split('\t')
        if len(parts) < 4:
            continue
            
        reg_id = parts[0].strip()
        date_str = parts[2].strip()
        occurrence_raw = parts[3].strip()
        
        # Validate Employee
        employee = emp_map.get(reg_id)
        if not employee:
            stats['errors'].append(f"MatrÃƒÆ’Ã‚Â­cula {reg_id}: Colaborador nÃƒÆ’Ã‚Â£o encontrado")
            continue
            
        # Validate Date
        try:
            start_date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            iso_date = start_date_obj.strftime("%Y-%m-%d") # Base date
        except:
             try:
                 start_date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                 iso_date = start_date_obj.strftime("%Y-%m-%d")
             except:
                stats['errors'].append(f"MatrÃƒÆ’Ã‚Â­cula {reg_id}: Data invÃƒÆ’Ã‚Â¡lida ({date_str})")
                continue
                
        # CHECK FOR MULTI-DAY RANGE (If occurrence_raw is actually a Date)
        end_date_obj = None
        is_multi_day = False
        try:
            # Try parsing occurrence_raw as date
            candidate_end = occurrence_raw
            try:
                end_date_obj = datetime.strptime(candidate_end, "%d/%m/%Y")
            except:
                end_date_obj = datetime.strptime(candidate_end, "%Y-%m-%d")
            
            # If successful, it's a multi-day certificate!
            is_multi_day = True
            occurrence_raw = "Atestado (Multi-Dias)" # Force type
            
        except:
            # Not a date, standard processing
            end_date_obj = start_date_obj # Single day
            is_multi_day = False

        
        # Loop for Days (Single or Multi)
        current_loop_date = start_date_obj
        while current_loop_date <= end_date_obj:
            loop_iso = current_loop_date.strftime("%Y-%m-%d")
            
            # Determine Types
            if is_multi_day:
                routine_type, event_type = "sick", "atestado"
                occ_label = f"Atestado ({start_date_obj.strftime('%d/%m')} a {end_date_obj.strftime('%d/%m')})"
            else:
                # Standard Logic
                occ_lower = occurrence_raw.lower()
                routine_type, event_type = None, None
                occ_label = occurrence_raw
                
                if "falta" in occ_lower:
                    routine_type, event_type = "absent", "falta"
                elif "atestado" in occ_lower:
                    routine_type, event_type = "sick", "atestado"
                elif "suspensÃƒÆ’Ã‚Â£o" in occ_lower or "suspensao" in occ_lower:
                    routine_type, event_type = "absent", "suspension"
                elif "advertÃƒÆ’Ã‚Âªncia" in occ_lower or "advertencia" in occ_lower:
                    routine_type, event_type = None, "advertencia"
                else:
                    stats['errors'].append(f"MatrÃƒÆ’Ã‚Â­cula {reg_id}: OcorrÃƒÆ’Ã‚Âªncia desconhecida ({occurrence_raw})")
                    break # Skip this line entirely if error
            
            pending_entries.append({
                "employee": employee,
                "iso_date": loop_iso,
                "date_obj": current_loop_date,
                "routine_type": routine_type,
                "event_type": event_type,
                "raw_occ": occ_label
            })
            
            current_loop_date += timedelta(days=1)
        
    if not pending_entries:
        return stats

    # 2. Bulk Fetch Existing Routines
    # To optimize, we fetch routines for involved employees within the date range
    involved_ids = {e["employee"].id for e in pending_entries}
    dates = [e["date_obj"] for e in pending_entries]
    min_date = min(dates).strftime("%Y-%m-%d")
    max_date = max(dates).strftime("%Y-%m-%d")
    
    existing_routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.employee_id.in_(involved_ids))
        .where(models.EmployeeRoutine.date >= min_date)
        .where(models.EmployeeRoutine.date <= max_date)
    ).all()
    
    # Map (emp_id, date) -> RoutineObject
    routine_map = {(r.employee_id, r.date): r for r in existing_routines}
    
    for entry in pending_entries:
        stats['total'] += 1
        emp = entry["employee"]
        iso_date = entry["iso_date"]
        
        # Routine Upsert
        # Routine Upsert (Only if routine_type matches a change, e.g. Absent/Sick)
        if entry["routine_type"]:
            key = (emp.id, iso_date)
            if key in routine_map:
                routine = routine_map[key]
                routine.routine = entry["routine_type"]
                session.add(routine)
            else:
                routine = models.EmployeeRoutine(
                    date=iso_date,
                    shift=emp.work_shift,
                    employee_id=emp.id,
                    routine=entry["routine_type"]
                )
                session.add(routine)
                routine_map[key] = routine # Update map for potential duplicate lines in same batch
            
        # Event Creation (Blind Insert for history)
        new_event = models.Event(
            timestamp=entry["date_obj"].replace(hour=8, minute=0),
            text=f"ImportaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o em Massa: {entry['raw_occ']}",
            type=entry["event_type"],
            category="import",
            employee_id=emp.id
        )
        session.add(new_event)
        stats['success'] += 1

    session.commit()
    return stats

@app.post("/employees/import")

async def import_employees(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    require_login(request)
    import pandas as pd
    import io
    import unicodedata

    def normalize_text(value: str) -> str:
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return value.strip().lower()

    def pick_column(columns, *candidates):
        normalized = {normalize_text(col): col for col in columns}
        for candidate in candidates:
            key = normalize_text(candidate)
            if key in normalized:
                return normalized[key]
        return None

    content = await file.read()
    try:
        excel = pd.ExcelFile(io.BytesIO(content))
        sheet_names = excel.sheet_names or [0]

        # Prioridade para a aba Souza Pinto quando existir.
        target_sheet = None
        for s in sheet_names:
            if normalize_text(s) == "souza pinto":
                target_sheet = s
                break
        if target_sheet is None:
            target_sheet = sheet_names[0]

        # Detecta cabeÃƒÆ’Ã‚Â§alho nos primeiros registros.
        df_temp = pd.read_excel(io.BytesIO(content), sheet_name=target_sheet, header=None, nrows=10)
        header_row = 0
        expected_headers = {"matricula", "colaborador", "nome funcionario", "nome cargo", "turno", "cargo"}
        for idx, row in df_temp.iterrows():
            row_values = {normalize_text(v) for v in row.values if pd.notna(v)}
            if row_values & expected_headers:
                header_row = idx
                break

        df = pd.read_excel(io.BytesIO(content), sheet_name=target_sheet, header=header_row)
        df.columns = df.columns.astype(str).str.strip()

        col_registration = pick_column(df.columns, "MatrÃƒÆ’Ã‚Â­cula", "Matricula")
        col_name = pick_column(df.columns, "Colaborador", "Nome FuncionÃƒÆ’Ã‚Â¡rio", "Nome Funcionario", "Nome")
        col_role = pick_column(df.columns, "Cargo", "Nome Cargo", "FunÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "Funcao")
        col_cost_center = pick_column(df.columns, "Centro de Custo")
        col_shift = pick_column(df.columns, "Turno")
        col_admission = pick_column(df.columns, "Data AdmissÃƒÆ’Ã‚Â£o", "AdmissÃƒÆ’Ã‚Â£o", "Admissao", "AdminissÃƒÆ’Ã‚Â£o", "Adminissao")
        col_birthday = pick_column(df.columns, "Data Nascimento", "Nascimento", "Data de Nascimento")

        if not col_registration:
            raise ValueError("Coluna de matrÃƒÆ’Ã‚Â­cula nÃƒÆ’Ã‚Â£o encontrada no arquivo.")

        count = 0 
        seen_registration = set()
        for _, row in df.iterrows():
            # Validation
            reg_id = str(row.get(col_registration, "")).strip()
            if not reg_id or reg_id.lower() == "nan" or reg_id.strip() == "":
                continue
            if reg_id in seen_registration:
                continue
            seen_registration.add(reg_id)

            # Check exist
            existing = session.exec(select(models.Employee).where(models.Employee.registration_id == reg_id)).first()
            if not existing:
                # Parse Dates
                admission = None
                if col_admission and pd.notna(row.get(col_admission)):
                    try:
                        admission = pd.to_datetime(row[col_admission], errors="coerce", dayfirst=True)
                        if pd.isna(admission):
                            admission = None
                        else:
                            admission = admission.to_pydatetime()
                    except:
                        pass
                        
                bday = None
                if col_birthday and pd.notna(row.get(col_birthday)):
                    try:
                        bday = pd.to_datetime(row[col_birthday], errors="coerce", dayfirst=True)
                        if pd.isna(bday):
                            bday = None
                        else:
                            bday = bday.to_pydatetime()
                    except:
                        pass
                        
                # Shift
                shift_raw = str(row.get(col_shift, "ManhÃƒÆ’Ã‚Â£")) if col_shift else "ManhÃƒÆ’Ã‚Â£"
                if pd.isna(shift_raw) or shift_raw.strip() == "" or shift_raw.lower() == "nan":
                    shift_raw = "ManhÃƒÆ’Ã‚Â£"
                    
                # Normalize specific cases to match System options (ManhÃƒÆ’Ã‚Â£, Tarde, Noite)
                shift_clean = shift_raw.strip().title() # Converts NOITE -> Noite
                
                if "Manha" in shift_clean or "ManhÃƒÆ’Ã‚Â£" in shift_clean:
                    shift_val = "ManhÃƒÆ’Ã‚Â£"
                elif "Tarde" in shift_clean:
                    shift_val = "Tarde"
                elif "Noite" in shift_clean:
                    shift_val = "Noite"
                else:
                    shift_val = shift_clean # Fallback (e.g. ADM)

                # Auto-assign Schedule
                default_schedule = None
                s_lower = (shift_val or "").lower()
                if "manhÃƒÆ’Ã‚Â£" in s_lower or "manha" in s_lower:
                    default_schedule = "05:00 - 13:20"
                elif "tarde" in s_lower:
                    default_schedule = "12:00 - 20:20"
                elif "noite" in s_lower:
                    default_schedule = "18:00 - 06:00"

                emp = models.Employee(
                    name=str(row.get(col_name, "Sem Nome")).strip() if col_name else "Sem Nome",
                    registration_id=reg_id.strip(),
                    role=str(row.get(col_role, "Operador")).strip() if col_role else "Operador",
                    work_shift=str(shift_val).strip(),
                    cost_center=str(row.get(col_cost_center, target_sheet)).strip() if col_cost_center else str(target_sheet),
                    admission_date=admission,
                    birthday=bday,
                    work_schedule=default_schedule,
                    status="active"
                )
                session.add(emp)
                count += 1
                
        session.commit()
    except Exception as e:
        print(f"Import Error: {e}")
        return RedirectResponse(url=f"/employees?error=Erro na importaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o: {str(e)}", status_code=status.HTTP_303_SEE_OTHER)
        
    return RedirectResponse(url=f"/employees?success={count} colaboradores importados com sucesso.", status_code=status.HTTP_303_SEE_OTHER)
@app.exception_handler(HTTPException)
async def auth_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_307_TEMPORARY_REDIRECT or exc.status_code == status.HTTP_303_SEE_OTHER:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    # For other HTTP exceptions, let them propagate or return JSON?
    # Default behavior: return JSON or HTML error page.
    # We should let FastAPI handle others, but since we are overriding the handler...
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

# --- People Intelligence Helper ---
def get_people_intelligence_metrics(session: Session, shift: str, start_date: Optional[str], end_date: Optional[str], status_filter: Optional[List[str]] = None):
    # 1. Overview Data
    # Se status_filter nÃƒÆ’Ã‚Â£o for fornecido, usa comportamento padrÃƒÆ’Ã‚Â£o (excluindo demitidos)
    if status_filter and len(status_filter) > 0:
        # Filtro personalizado de status
        employees = session.exec(
            select(models.Employee)
            .where(col(models.Employee.status).in_(status_filter))
            .where(models.Employee.replaced_by.is_(None))
        ).all()
    else:
        # Comportamento padrÃƒÆ’Ã‚Â£o: excluir demitidos
        employees = session.exec(
            select(models.Employee)
            .where(models.Employee.status != "fired")
            .where(models.Employee.replaced_by.is_(None))
        ).all()
    
    # Filter by Shift
    if shift != "Todos":
        employees = [e for e in employees if e.work_shift == shift]
    
    total_headcount = len(employees)
    employee_ids = {e.id for e in employees}
    
    # Fetch Events with Filters
    today = datetime.now()
    
    # Date range filter (flexible: can be month, year,  or custom range)
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        except:
            # Fallback to current month
            start_dt = datetime(today.year, today.month, 1)
            if today.month == 12:
                end_dt = datetime(today.year + 1, 1, 1)
            else:
                end_dt = datetime(today.year, today.month + 1, 1)
    else:
        # Default: Current Year to Date
        start_dt = datetime(today.year, 1, 1)
        end_dt = today
    
    
    events = session.exec(
        select(models.Event)
        .where(models.Event.timestamp >= start_dt)
        .where(models.Event.timestamp < end_dt)
        .where(col(models.Event.type).in_(['falta', 'atestado', 'advertencia', 'afastamento']))
    ).all()
    
    # Filter events by employee_ids (shift filter) for context if needed, 
    # BUT for Metrics (KPIs) we will use EmployeeRoutine table to count DAYS lost.
    # This is more accurate for "Taxa de AbsenteÃƒÆ’Ã‚Â­smo" (Man-Days).
    
    # Fetch Routines for the period
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date >= start_dt.strftime("%Y-%m-%d"))
        .where(models.EmployeeRoutine.date <= end_dt.strftime("%Y-%m-%d"))
    ).all()
    
    # Filter routines for selected shift employees
    routines = [r for r in routines if r.employee_id in employee_ids]
    
    # Agrupar por dia ÃƒÆ’Ã‚Âºnico (employee_id + date) para evitar contagem duplicada
    # Cada dia pode ter atÃƒÆ’Ã‚Â© 3 registros (ManhÃƒÆ’Ã‚Â£, Tarde, Noite)
    unique_days = {}  # (emp_id, date) -> routine_type (prioridade: absent > sick > away)
    for r in routines:
        key = (r.employee_id, str(r.date))
        r_type = r.routine
        # Normalizar tipos
        if r_type in ['absent', 'falta']:
            normalized = 'falta'
        elif r_type in ['sick', 'atestado']:
            normalized = 'atestado'
        elif r_type in ['away', 'afastado']:
            normalized = 'afastamento'
        else:
            continue  # Ignorar outros tipos (present, vacation, etc.)
        
        # Se jÃƒÆ’Ã‚Â¡ existe um registro para esse dia, manter o de maior prioridade
        if key not in unique_days:
            unique_days[key] = normalized
        else:
            # Prioridade: falta > atestado > afastamento
            priority = {'falta': 3, 'atestado': 2, 'afastamento': 1}
            if priority.get(normalized, 0) > priority.get(unique_days[key], 0):
                unique_days[key] = normalized
    
    # Contadores gerais (Dias ÃƒÆ’Ã…Â¡NICOS)
    total_absences = sum(1 for v in unique_days.values() if v == 'falta')
    total_sick = sum(1 for v in unique_days.values() if v == 'atestado')
    total_away = sum(1 for v in unique_days.values() if v == 'afastamento')
    
    # 2. Rankings (Top Offenders - by UNIQUE DAYS)
    emp_stats = {}
    
    # Initial population from employees list (to blank fill)
    for emp in employees:
         emp_stats[emp.id] = {'falta': 0, 'atestado': 0, 'advertencia': 0, 'afastamento': 0, 'name': emp.name, 'sector': emp.cost_center or "Geral", 'tenure_months': 0}
         if emp.admission_date:
                delta = datetime.now() - emp.admission_date
                emp_stats[emp.id]['tenure_months'] = int(delta.days / 30)

    # Count unique days per employee
    for (emp_id, day), routine_type in unique_days.items():
        if emp_id not in emp_stats:
            continue
        emp_stats[emp_id][routine_type] += 1
            
    # Include Events only for "Advertencia" (which is an event, not a routine status)
    filtered_events = [e for e in events if e.employee_id in employee_ids]
    for e in filtered_events:
        if e.type == 'advertencia':
             if e.employee_id in emp_stats:
                  emp_stats[e.employee_id]['advertencia'] += 1
    
    # Flatten to ranking list
    ranking_data = []
    for eid, stats in emp_stats.items():
        stats['employee_id'] = eid
        # Only add if they have something relevant? Or keep all for denominator?
        # Only add if > 0 events/days?
        # For Top lists we sort.
        ranking_data.append(stats)
            
    # Sorts - Only show employees with actual data
    top_absent = sorted([r for r in ranking_data if r['falta'] > 0], key=lambda x: x['falta'], reverse=True)
    top_sick = sorted([r for r in ranking_data if r['atestado'] > 0], key=lambda x: x['atestado'], reverse=True)
    top_away = sorted([r for r in ranking_data if r['afastamento'] > 0], key=lambda x: x['afastamento'], reverse=True)
    
    # Define Map for later use
    emp_map = {e.id: e for e in employees}

    # 3. Sector Analysis
    sector_stats = {}
    for item in ranking_data:
        sec = item['sector']
        if sec not in sector_stats:
            sector_stats[sec] = {'falta': 0, 'atestado': 0, 'headcount': 0}
        sector_stats[sec]['falta'] += item['falta']
        sector_stats[sec]['atestado'] += item['atestado']
        
    # Calc Headcount per sector for Rate
    for emp in employees:
        sec = emp.cost_center or "Geral"
        if sec not in sector_stats:
             sector_stats[sec] = {'falta': 0, 'atestado': 0, 'headcount': 0}
        sector_stats[sec]['headcount'] += 1
        
    sector_list = []
    for sec, stats in sector_stats.items():
        if stats['headcount'] > 0:
            stats['name'] = sec
            # Risk Index = Days Lost / Headcount
            stats['risk_index'] = round((stats['falta'] + stats['atestado']) / stats['headcount'], 2)
            sector_list.append(stats)
            
    sector_list.sort(key=lambda x: x['risk_index'], reverse=True)
    
    # 4. Calculate PRESENCE (Accurate Method: Sum of Expected Days)
    days_in_period = (end_dt - start_dt).days
    
    total_expected_work_days_global = 0
    emp_expected_days_map = {}
    
    for emp in employees:
        calc_start = start_dt
        if emp.admission_date:
            try:
                if emp.admission_date.replace(tzinfo=None) > start_dt.replace(tzinfo=None):
                    calc_start = emp.admission_date.replace(tzinfo=None)
            except:
                pass
        
        ex_days = calculate_expected_work_days(
            emp.work_days or '[]',
            calc_start,
            end_dt,
            vacation_start=emp.vacation_start,
            vacation_end=emp.vacation_end
        )
        emp_expected_days_map[emp.id] = ex_days
        total_expected_work_days_global += ex_days
        
    theoretical_attendance = total_expected_work_days_global if total_expected_work_days_global > 0 else 1
    total_events = total_absences + total_sick
    presence_rate = round((1 - (total_events / theoretical_attendance)) * 100, 1) if theoretical_attendance > 0 else 100
    
    # 5. Chronic Offenders (High Operational Risk)
    # Employees with high combined falta + atestado that disrupt operations
    chronic_offenders = []
    for item in ranking_data:
        combined_events = item['falta'] + item['atestado']
        if combined_events >= 3:  # Threshold: 3+ events in period
            item['combined_events'] = combined_events
            item['risk_score'] = round((combined_events / days_in_period) * 100, 1) if days_in_period > 0 else 0
            
            # Use pre-calculated expected days
            emp = emp_map.get(item['employee_id'])
            if emp:
                item['expected_work_days'] = emp_expected_days_map.get(item['employee_id'], 0)
                item['actual_work_days'] = max(0, item['expected_work_days'] - combined_events)
                item['utilization_rate'] = round(
                    (item['actual_work_days'] / item['expected_work_days']) * 100, 1
                ) if item['expected_work_days'] > 0 else 0
            else:
                # Fallback if employee not found
                item['expected_work_days'] = 0
                item['actual_work_days'] = 0
                item['utilization_rate'] = 0
            
            chronic_offenders.append(item)
    
    # Sort by combined events
    chronic_offenders.sort(key=lambda x: x['combined_events'], reverse=True)
    
    return {
        "overview": {
            "headcount": total_headcount,
            "total_absences": total_absences,
            "total_sick": total_sick,
            "total_away": total_away,
            "avg_absence_per_emp": round(total_absences / total_headcount, 2) if total_headcount > 0 else 0,
            "presence_rate": presence_rate,
            "chronic_count": len(chronic_offenders)
        },
        "top_absent": top_absent,
        "top_sick": top_sick,
        "top_away": top_away,
        "sectors": sector_list,
        "chronic_offenders": chronic_offenders,
        "emp_map": emp_map,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d")
    }

# --- People Intelligence Route ---
@app.get("/people-intelligence", response_class=HTMLResponse)
async def people_intelligence_page(
    request: Request, 
    shift: str = "Todos",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session)
):
    user = require_login(request)
    data = get_people_intelligence_metrics(session, shift, start_date, end_date)
    
    return templates.TemplateResponse("people_intelligence.html", {
        "request": request,
        "user": user,
        "current_shift": shift,
        "start_date": data['start_date'],
        "end_date": data['end_date'],
        "overview": data['overview'],
        "top_absent": data['top_absent'][:10],
        "top_sick": data['top_sick'][:10],
        "sectors": data['sectors'],
        "chronic_offenders": data['chronic_offenders'][:10],
        "emp_map": data['emp_map'],
        "all_absent": data['top_absent'],
        "all_sick": data['top_sick'],
        "all_away": data['top_away']
    })

@app.get("/api/people-intelligence/offenders")
async def api_get_offenders(
    request: Request,
    shift: str = "Todos",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session)
):
    require_login(request)
    data = get_people_intelligence_metrics(session, shift, start_date, end_date)
    return JSONResponse(content={"offenders": data['chronic_offenders']})

# --- People Intelligence Report (Print Preview) ---
@app.get("/people-intelligence/report", response_class=HTMLResponse)
async def people_intelligence_report(
    request: Request,
    shift: str = "Todos",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """Print-ready version of people intelligence (no sidebar)"""
    user = require_login(request)
    
    # Parse status filter (comma-separated list)
    status_filter = None
    if status:
        status_filter = [s.strip() for s in status.split(",") if s.strip()]
    
    data = get_people_intelligence_metrics(session, shift, start_date, end_date, status_filter)
    
    # Generate status labels for display
    status_labels = {
        'active': 'Ativos',
        'vacation': 'FÃƒÆ’Ã‚Â©rias',
        'away': 'Afastados', 
        'fired': 'Demitidos'
    }
    selected_status_display = ", ".join([status_labels.get(s, s) for s in (status_filter or ['active', 'vacation', 'away'])])
    
    return templates.TemplateResponse("people_intelligence_report.html", {
        "request": request,
        "current_shift": shift,
        "start_date": data['start_date'],
        "end_date": data['end_date'],
        "overview": data['overview'],
        "top_absent": data['top_absent'][:10],
        "top_sick": data['top_sick'][:10],
        "sectors": data['sectors'],
        "chronic_offenders": data['chronic_offenders'][:10],
        "status_filter": status_filter or [],
        "selected_status_display": selected_status_display
    })



@app.get("/smart-flow/load", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def smart_flow_load(request: Request, shift: str = "ManhÃƒÆ’Ã‚Â£", date: Optional[str] = None, session: Session = Depends(get_session)):
    try:
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
        if not date:
            date = get_effective_shift_date(shift, now_br).strftime("%Y-%m-%d")
        else:
            date = normalize_shift_date(date, shift, now_br)

        # Get Sector Config
        sector_config_db = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == shift)).first()
        sector_config = {}
        if sector_config_db and sector_config_db.config_json:
            sector_config = sector_config_db.config_json
            if isinstance(sector_config, str):
                try:
                    sector_config = json.loads(sector_config)
                except:
                    sector_config = {}
        
        # Default sectors if empty
        if not sector_config or not isinstance(sector_config, dict) or "sectors" not in sector_config:
            sector_config = {
                "sectors": [
                    { "key": "recebimento", "label": "Recebimento", "target": 0, "subsectors": ["Doca 1", "Doca 2", "PaletizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"] },
                    { "key": "camara_fria", "label": "CÃƒÆ’Ã‚Â¢mara Fria", "target": 0, "subsectors": ["Armazenagem", "Abastecimento"] },
                    { "key": "selecao", "label": "SeleÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "target": 0, "subsectors": ["Linha 1", "Linha 2"] },
                    { "key": "expedicao", "label": "ExpediÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "target": 0, "subsectors": ["SeparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o", "Carregamento"] }
                ]
            }

        # Get Operation
        daily_op = session.exec(
            select(models.DailyOperation)
            .where(models.DailyOperation.date == date)
            .where(models.DailyOperation.shift == shift)
        ).first()

        employees_log = {}
        manual_tonnage = 0
        
        if daily_op:
            employees_log = daily_op.attendance_log or {}
            manual_tonnage = daily_op.tonnage or 0

        return {
            "employees_log": employees_log,
            "sector_config": sector_config.get("sectors", []),
            "manual_tonnage": manual_tonnage
        }
    except Exception as e:
        logger.error(f"Error in smart_flow_load: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# --- MÃƒÆ’Ã‚Â³dulo LÃƒÆ’Ã‚Â­der: Checklists em dia, Rotas, Tarefas ---

@app.get("/lider/checklists", response_class=HTMLResponse, dependencies=[Depends(require_leader)])
async def lider_checklists_page(
    request: Request,
    date: Optional[str] = None,
    shift: str = "ManhÃƒÆ’Ã‚Â£",
    session: Session = Depends(get_session),
):
    """PÃƒÆ’Ã‚Â¡gina: quem nÃƒÆ’Ã‚Â£o fez checklist (paleteira) no dia/turno."""
    user = require_login(request)
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    # Quem deveria fazer: mobile_access_checklist e ativo no turno
    employees = session.exec(
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .where(models.Employee.work_shift == shift)
        .where(models.Employee.mobile_access_checklist == True)
    ).all()
    # Quem fez checklist na data/turno
    done_ids = set()
    for row in session.exec(
        select(models.TranspalletChecklist.employee_id)
        .where(models.TranspalletChecklist.date == date)
        .where(models.TranspalletChecklist.shift == shift)
    ).all():
        done_ids.add(row)
    missing = [e for e in employees if e.id not in done_ids]
    return templates.TemplateResponse("lider_checklists.html", {
        "request": request,
        "user": user,
        "current_date": date,
        "current_shift": shift,
        "missing_paleteira": missing,
        "total_expected": len(employees),
        "total_done": len(done_ids),
    })


@app.get("/lider/rotas", response_class=HTMLResponse, dependencies=[Depends(require_leader)])
async def lider_rotas_page(
    request: Request,
    date: Optional[str] = None,
    shift: str = "ManhÃƒÆ’Ã‚Â£",
    session: Session = Depends(get_session),
):
    """PÃƒÆ’Ã‚Â¡gina: quem nÃƒÆ’Ã‚Â£o estÃƒÆ’Ã‚Â¡ no app fazendo rota + velocidade da equipe."""
    user = require_login(request)
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    # Quem deveria estar no app: mobile_access_separation, ativo, turno do dia
    expected = session.exec(
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .where(models.Employee.work_shift == shift)
        .where(models.Employee.mobile_access_separation == True)
    ).all()
    expected_ids = {e.id for e in expected}
    # Quem tem rota no dia/turno
    routes = session.exec(
        select(models.Route)
        .where(models.Route.date == date)
        .where(models.Route.shift == shift)
    ).all()
    with_route_ids = {r.employee_id for r in routes}
    missing_route = [e for e in expected if e.id not in with_route_ids]
    # Velocidade: kg/h por colaborador e total
    emp_tonnage = {}
    for r in routes:
        emp_tonnage[r.employee_id] = emp_tonnage.get(r.employee_id, 0) + (r.tonnage or 0)
    total_tonnage = sum(emp_tonnage.values())
    # Calcular kg/h aproximado (horas no turno: 8h)
    hours_shift = 8.0
    velocity_list = []
    for e in expected:
        kg = emp_tonnage.get(e.id, 0)
        kgh = kg / hours_shift if hours_shift else 0
        velocity_list.append({"employee": e, "tonnage": kg, "kgh": round(kgh, 1)})
    velocity_list.sort(key=lambda x: -x["tonnage"])
    return templates.TemplateResponse("lider_rotas.html", {
        "request": request,
        "user": user,
        "current_date": date,
        "current_shift": shift,
        "missing_route": missing_route,
        "velocity_list": velocity_list,
        "total_tonnage": total_tonnage,
        "total_with_route": len(with_route_ids),
        "total_expected": len(expected),
    })


@app.get("/lider/rotas/relatorio", response_class=HTMLResponse, dependencies=[Depends(require_leader)])
async def lider_rotas_relatorio_page(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    shift: str = "Todos",
    session: Session = Depends(get_session),
):
    """RelatÃƒÆ’Ã‚Â³rio de dias sem rota por colaborador - para impressÃƒÆ’Ã‚Â£o."""
    user = require_login(request)
    br_tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(br_tz)
    today = now.date()
    
    # Defaults para primeiro dia do mÃƒÆ’Ã‚Âªs atÃƒÆ’Ã‚Â© hoje
    if not start_date:
        first_day = date(today.year, today.month, 1)
    else:
        try:
            first_day = datetime.strptime(start_date, "%Y-%m-%d").date()
        except:
            first_day = date(today.year, today.month, 1)
    
    if not end_date:
        last_day = today
    else:
        try:
            last_day = datetime.strptime(end_date, "%Y-%m-%d").date()
        except:
            last_day = today
    
    # Limitar ao dia atual - nÃƒÆ’Ã‚Â£o considerar dias futuros como ausÃƒÆ’Ã‚Âªncia
    if last_day > today:
        last_day = today
    
    # Gerar lista de dias do mÃƒÆ’Ã‚Âªs (somente atÃƒÆ’Ã‚Â© hoje, sem dias futuros)
    all_days = []
    current = first_day
    while current <= last_day:
        all_days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    
    # Buscar colaboradores que deveriam fazer rota
    emp_query = select(models.Employee).where(
        models.Employee.status != "fired",
        models.Employee.mobile_access_separation == True
    )
    if shift != "Todos":
        emp_query = emp_query.where(models.Employee.work_shift == shift)
    emp_query = emp_query.order_by(models.Employee.name)
    
    employees = session.exec(emp_query).all()
    emp_map = {e.id: e for e in employees}
    emp_ids = list(emp_map.keys())
    
    # Buscar todas as rotas do perÃƒÆ’Ã‚Â­odo
    routes = session.exec(
        select(models.Route)
        .where(models.Route.date >= first_day.strftime("%Y-%m-%d"))
        .where(models.Route.date <= last_day.strftime("%Y-%m-%d"))
        .where(models.Route.employee_id.in_(emp_ids) if emp_ids else True)
    ).all()
    
    # Mapear: {employee_id: set(dates_with_routes)}
    routes_by_emp = {}
    for r in routes:
        if r.employee_id not in routes_by_emp:
            routes_by_emp[r.employee_id] = set()
        routes_by_emp[r.employee_id].add(r.date)
    
    # Buscar rotinas para saber dias de folga/fÃƒÆ’Ã‚Â©rias/atestado (para nÃƒÆ’Ã‚Â£o contar como falta de rota)
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date >= first_day.strftime("%Y-%m-%d"))
        .where(models.EmployeeRoutine.date <= last_day.strftime("%Y-%m-%d"))
        .where(models.EmployeeRoutine.employee_id.in_(emp_ids) if emp_ids else True)
    ).all()
    
    # Mapear: {employee_id: {date: routine}}
    routines_by_emp = {}
    for r in routines:
        if r.employee_id not in routines_by_emp:
            routines_by_emp[r.employee_id] = {}
        routines_by_emp[r.employee_id][r.date] = r.routine
    
    # Calcular dias sem rota por colaborador
    report_data = []
    total_missing = 0
    total_no_app = 0  # Total de dias que nÃƒÆ’Ã‚Â£o abriram o app
    
    # Mapa de dias da semana em inglÃƒÆ’Ã‚Âªs para comparaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    for emp_id, emp in emp_map.items():
        emp_routes = routes_by_emp.get(emp_id, set())
        emp_routines = routines_by_emp.get(emp_id, {})
        
        # Obter dias de trabalho do colaborador (padrÃƒÆ’Ã‚Â£o: segunda a sÃƒÆ’Ã‚Â¡bado)
        work_days_list = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        try:
            if emp.work_days:
                import json
                work_days_list = json.loads(emp.work_days)
        except:
            pass
        
        # Dias sem rota (excluindo fÃƒÆ’Ã‚Â©rias, folga, atestado, afastamento)
        missing_days = []
        justified_days = []
        no_app_days = []  # Dias que nÃƒÆ’Ã‚Â£o abriu o app (sem rota E sem rotina)
        
        # Verificar datas de fÃƒÆ’Ã‚Â©rias do colaborador (vacation_start e vacation_end)
        emp_vacation_start = None
        emp_vacation_end = None
        if emp.vacation_start and emp.vacation_end:
            emp_vacation_start = emp.vacation_start.date() if hasattr(emp.vacation_start, 'date') else emp.vacation_start
            emp_vacation_end = emp.vacation_end.date() if hasattr(emp.vacation_end, 'date') else emp.vacation_end
        
        # Verificar se colaborador estÃƒÆ’Ã‚Â¡ afastado
        emp_is_away = emp.status == 'away'
        
        for day_str in all_days:
            day_date = datetime.strptime(day_str, "%Y-%m-%d").date()
            day_weekday = weekday_names[day_date.weekday()]
            
            # Verificar se ÃƒÆ’Ã‚Â© dia de trabalho do colaborador
            if day_weekday not in work_days_list:
                continue  # NÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© dia de trabalho, pular
            
            # Ignorar dias futuros (nÃƒÆ’Ã‚Â£o pode faltar em dia que ainda nÃƒÆ’Ã‚Â£o chegou)
            if day_date > now.date():
                continue
            
            routine = emp_routines.get(day_str, None)  # None = sem rotina registrada
            
            # NOVA VERIFICAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O: Checar se o dia estÃƒÆ’Ã‚Â¡ dentro do perÃƒÆ’Ã‚Â­odo de fÃƒÆ’Ã‚Â©rias do colaborador
            is_vacation_period = False
            if emp_vacation_start and emp_vacation_end:
                if emp_vacation_start <= day_date <= emp_vacation_end:
                    is_vacation_period = True
            
            # LÃƒÆ’Ã‚Â³gica de presenÃƒÆ’Ã‚Â§a:
            # 1. Se tem Route = TRABALHOU
            # 2. Se tem EmployeeRoutine com routine="present" = TRABALHOU (fluxo operacional)
            # 3. Se estÃƒÆ’Ã‚Â¡ no perÃƒÆ’Ã‚Â­odo de fÃƒÆ’Ã‚Â©rias (vacation_start/vacation_end) = JUSTIFICADO
            # 4. Se estÃƒÆ’Ã‚Â¡ afastado (status=away) = JUSTIFICADO
            # 5. Se tem justificativa na rotina (vacation, sick, away, dayoff) = JUSTIFICADO
            # 6. Se tem routine="absent" = FALTA REGISTRADA
            # 7. Se nÃƒÆ’Ã‚Â£o tem rota E nÃƒÆ’Ã‚Â£o tem rotina = NÃƒÆ’Ã†â€™O ABRIU APP
            
            has_route = day_str in emp_routes
            
            if has_route or routine == "present":
                # Colaborador trabalhou (tem rota OU marcou presenÃƒÆ’Ã‚Â§a no fluxo operacional)
                continue  # NÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© ausÃƒÆ’Ã‚Âªncia
            elif is_vacation_period:
                # Colaborador estava de fÃƒÆ’Ã‚Â©rias (baseado em vacation_start/vacation_end)
                justified_days.append({
                    "date": day_str,
                    "reason": "Ferias"
                })
            elif emp_is_away:
                # Colaborador estÃƒÆ’Ã‚Â¡ afastado (status=away)
                justified_days.append({
                    "date": day_str,
                    "reason": "Afastado"
                })
            elif routine in ("vacation", "sick", "away", "dayoff"):
                # Justificado via rotina diÃƒÆ’Ã‚Â¡ria - nÃƒÆ’Ã‚Â£o deveria trabalhar
                justified_days.append({
                    "date": day_str,
                    "reason": {
                        "vacation": "Ferias",
                        "sick": "Atestado",
                        "away": "Afastado",
                        "dayoff": "Folga"
                    }.get(routine, routine)
                })
            elif routine == "absent":
                # Falta registrada explicitamente
                missing_days.append(day_str)
            elif routine is None and not has_route:
                # NÃƒÆ’Ã‚Â£o abriu o app - sem rota e sem rotina registrada
                no_app_days.append(day_str)
        
        # Calcular dias trabalhados: dias com rota OU com presenÃƒÆ’Ã‚Â§a registrada no fluxo operacional
        days_with_presence = {d for d, r in emp_routines.items() if r == "present"}
        total_worked_days = len(emp_routes.union(days_with_presence))
        
        if missing_days or justified_days or no_app_days:
            report_data.append({
                "employee": emp,
                "missing_days": missing_days,
                "justified_days": justified_days,
                "no_app_days": no_app_days,
                "total_missing": len(missing_days),
                "total_justified": len(justified_days),
                "total_no_app": len(no_app_days),
                "total_worked": total_worked_days
            })
            total_missing += len(missing_days)
            total_no_app += len(no_app_days)
    
    # Ordenar por quantidade de ausÃƒÆ’Ã‚Âªncias (faltas + nÃƒÆ’Ã‚Â£o abriu app, maior primeiro)
    report_data.sort(key=lambda x: (x["total_missing"] + x["total_no_app"]), reverse=True)
    
    return templates.TemplateResponse("lider_rotas_relatorio.html", {
        "request": request,
        "user": user,
        "report_data": report_data,
        "start_date": first_day.strftime("%Y-%m-%d"),
        "end_date": last_day.strftime("%Y-%m-%d"),
        "shift": shift,
        "period_label": f"{first_day.strftime('%d/%m/%Y')} a {last_day.strftime('%d/%m/%Y')}",
        "total_days": len(all_days),
        "total_employees": len(employees),
        "total_missing": total_missing,
        "total_no_app": total_no_app,
        "generated_at": now.strftime("%d/%m/%Y %H:%M"),
    })


@app.get("/lider/tarefas", response_class=HTMLResponse, dependencies=[Depends(require_leader)])
async def lider_tarefas_page(request: Request, session: Session = Depends(get_session)):
    """PÃƒÆ’Ã‚Â¡gina: listar e criar tarefas para colaboradores."""
    user = require_login(request)
    tasks = session.exec(
        select(models.LeaderTask)
        .where(models.LeaderTask.status.in_(["sent", "draft"]))
        .order_by(desc(models.LeaderTask.created_at))
    ).all()
    employees = session.exec(
        select(models.Employee).where(models.Employee.status != "fired").order_by(models.Employee.name)
    ).all()
    return templates.TemplateResponse("lider_tarefas.html", {
        "request": request,
        "user": user,
        "tasks": tasks,
        "employees": employees,
    })


@app.post("/api/lider/tarefas", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def api_lider_create_task(
    request: Request,
    session: Session = Depends(get_session),
):
    """Cria uma tarefa e envia para os colaboradores selecionados."""
    user = require_login(request)
    try:
        body = await request.json()
        title = (body.get("title") or "").strip()
        if not title:
            return JSONResponse({"error": "TÃƒÆ’Ã‚Â­tulo ÃƒÆ’Ã‚Â© obrigatÃƒÆ’Ã‚Â³rio"}, status_code=400)
        description = (body.get("description") or "").strip() or None
        priority = (body.get("priority") or "medium").strip().lower()
        if priority not in ("low", "medium", "high"):
            priority = "medium"
        recipient_ids = body.get("recipient_employee_ids") or []
        if isinstance(recipient_ids, list):
            recipient_ids = [int(x) for x in recipient_ids if x]
        else:
            recipient_ids = []
        due_at = None
        if body.get("due_at"):
            try:
                due_at = datetime.fromisoformat(body["due_at"].replace("Z", "+00:00"))
            except Exception:
                pass
        username = (user.get("username") or user.get("name") or "lÃƒÆ’Ã‚Â­der") if isinstance(user, dict) else "lÃƒÆ’Ã‚Â­der"
        task = models.LeaderTask(
            title=title,
            description=description,
            priority=priority,
            status="sent",
            created_by=username,
            recipient_employee_ids=recipient_ids,
            due_at=due_at,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return {"success": True, "task_id": task.id}
    except Exception as e:
        logger.exception("Create task error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/lider/tarefas", response_class=JSONResponse, dependencies=[Depends(require_leader)])
async def api_lider_list_tasks(request: Request, session: Session = Depends(get_session)):
    """Lista tarefas (lÃƒÆ’Ã‚Â­der)."""
    require_login(request)
    tasks = session.exec(
        select(models.LeaderTask)
        .where(models.LeaderTask.status.in_(["sent", "draft"]))
        .order_by(desc(models.LeaderTask.created_at))
    ).all()
    out = []
    for t in tasks:
        out.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "priority": t.priority,
            "status": t.status,
            "created_by": t.created_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "recipient_employee_ids": t.recipient_employee_ids or [],
        })
    return out


@app.get("/api/lider/minhas-tarefas", response_class=JSONResponse)
async def api_minhas_tarefas(request: Request, session: Session = Depends(get_session)):
    """Lista tarefas destinadas ao colaborador logado (User.employee_id)."""
    user = require_login(request)
    user_id = (user.get("id") if isinstance(user, dict) else None)
    if not user_id:
        return []
    db_user = session.get(models.User, user_id)
    emp_id = db_user.employee_id if db_user else None
    if not emp_id:
        return []
    tasks = session.exec(
        select(models.LeaderTask)
        .where(models.LeaderTask.status == "sent")
    ).all()
    my_tasks = [t for t in tasks if emp_id in (t.recipient_employee_ids or [])]
    out = []
    for t in my_tasks:
        out.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "priority": t.priority,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "due_at": t.due_at.isoformat() if t.due_at else None,
        })
    return out


@app.post("/api/lider/tarefas/{task_id}/marcar-visto", response_class=JSONResponse)
async def api_marcar_tarefa_visto(
    request: Request,
    task_id: int,
    session: Session = Depends(get_session),
):
    """Colaborador marca tarefa como vista."""
    user = require_login(request)
    user_id = (user.get("id") if isinstance(user, dict) else None)
    db_user = session.get(models.User, user_id) if user_id else None
    emp_id = db_user.employee_id if db_user else None
    if not emp_id:
        return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o identificado"}, status_code=403)
    task = session.get(models.LeaderTask, task_id)
    if not task or task.status != "sent":
        return JSONResponse({"error": "Tarefa nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    if emp_id not in (task.recipient_employee_ids or []):
        return JSONResponse({"error": "Tarefa nÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© sua"}, status_code=403)
    existing = session.exec(
        select(models.LeaderTaskResponse)
        .where(models.LeaderTaskResponse.task_id == task_id)
        .where(models.LeaderTaskResponse.employee_id == emp_id)
    ).first()
    if existing:
        if not existing.seen_at:
            existing.seen_at = datetime.now()
            session.add(existing)
            session.commit()
        return {"success": True}
    resp = models.LeaderTaskResponse(task_id=task_id, employee_id=emp_id, seen_at=datetime.now())
    session.add(resp)
    session.commit()
    return {"success": True}


@app.post("/api/lider/tarefas/{task_id}/concluir", response_class=JSONResponse)
async def api_concluir_tarefa(
    request: Request,
    task_id: int,
    session: Session = Depends(get_session),
):
    """Colaborador marca tarefa como concluÃƒÆ’Ã‚Â­da."""
    user = require_login(request)
    user_id = (user.get("id") if isinstance(user, dict) else None)
    db_user = session.get(models.User, user_id) if user_id else None
    emp_id = db_user.employee_id if db_user else None
    if not emp_id:
        return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o identificado"}, status_code=403)
    task = session.get(models.LeaderTask, task_id)
    if not task or task.status != "sent":
        return JSONResponse({"error": "Tarefa nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    if emp_id not in (task.recipient_employee_ids or []):
        return JSONResponse({"error": "Tarefa nÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© sua"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    note = (body.get("note") or "").strip() or None
    existing = session.exec(
        select(models.LeaderTaskResponse)
        .where(models.LeaderTaskResponse.task_id == task_id)
        .where(models.LeaderTaskResponse.employee_id == emp_id)
    ).first()
    if existing:
        existing.completed_at = datetime.now()
        existing.note = note
        session.add(existing)
    else:
        resp = models.LeaderTaskResponse(
            task_id=task_id,
            employee_id=emp_id,
            seen_at=datetime.now(),
            completed_at=datetime.now(),
            note=note,
        )
        session.add(resp)
    session.commit()
    return {"success": True}


# --- API de Alertas para LÃƒÆ’Ã‚Â­deres ---

@app.get("/api/lider/alertas", response_class=JSONResponse)
async def api_lider_alertas(request: Request, session: Session = Depends(get_session)):
    """Retorna alertas importantes para o lÃƒÆ’Ã‚Â­der logado."""
    user = require_leader(request)
    user_id = user.get("id") if isinstance(user, dict) else None
    user_role = user.get("role", "").lower() if isinstance(user, dict) else ""
    
    alertas = {
        "ordens_pendentes": [],
        "ordens_atrasadas": [],
        "colaboradores_sem_rota": [],
        "colaboradores_sem_checklist": [],
        "total_alertas": 0,
    }
    
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    
    # 1. Ordens de serviÃƒÆ’Ã‚Â§o pendentes do lÃƒÆ’Ã‚Â­der
    if user_id:
        executions = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.user_id == user_id)
            .where(models.OperationalTaskExecution.scheduled_date == today)
            .where(models.OperationalTaskExecution.status.in_(["pending", "in_progress"]))
        ).all()
        
        for ex in executions:
            task = session.get(models.OperationalTask, ex.task_id)
            if task:
                is_atrasada = False
                if task.scheduled_time:
                    try:
                        scheduled_hour, scheduled_min = map(int, task.scheduled_time.split(":"))
                        scheduled_dt = now.replace(hour=scheduled_hour, minute=scheduled_min, second=0, microsecond=0)
                        if now > scheduled_dt:
                            is_atrasada = True
                    except:
                        pass
                
                item = {
                    "id": ex.id,
                    "task_id": task.id,
                    "title": task.title,
                    "priority": task.priority,
                    "scheduled_time": task.scheduled_time,
                    "status": ex.status,
                }
                
                if is_atrasada:
                    alertas["ordens_atrasadas"].append(item)
                else:
                    alertas["ordens_pendentes"].append(item)
    
    # 2. Colaboradores sem rota hoje (apenas para lÃƒÆ’Ã‚Â­deres/admins)
    if user_role in ("leader", "admin"):
        # Buscar colaboradores que deveriam ter rota hoje mas nÃƒÆ’Ã‚Â£o tÃƒÆ’Ã‚Âªm
        employees_with_route = session.exec(
            select(models.Route.employee_id)
            .where(models.Route.date == today)
        ).all()
        employee_ids_with_route = set(employees_with_route)
        
        # Buscar colaboradores ativos do turno
        db_user = session.get(models.User, user_id) if user_id else None
        
        # Buscar colaboradores presentes hoje
        routines_today = session.exec(
            select(models.EmployeeRoutine)
            .where(models.EmployeeRoutine.date == today)
            .where(models.EmployeeRoutine.routine == "present")
        ).all()
        
        for routine in routines_today:
            if routine.employee_id not in employee_ids_with_route:
                emp = session.get(models.Employee, routine.employee_id)
                if emp and emp.status == "active":
                    # Verificar se deveria ter rota (colaborador de separaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o)
                    if emp.role and "separ" in emp.role.lower():
                        alertas["colaboradores_sem_rota"].append({
                            "id": emp.id,
                            "name": emp.name,
                            "role": emp.role,
                        })
    
    # 3. Colaboradores sem checklist hoje
    if user_role in ("leader", "admin"):
        # Buscar colaboradores que fizeram checklist hoje
        checklists_today = session.exec(
            select(models.TranspalletChecklist.employee_id)
            .where(models.TranspalletChecklist.date == today)
        ).all()
        employee_ids_with_checklist = set(checklists_today)
        
        # Buscar colaboradores presentes que deveriam fazer checklist
        for routine in routines_today:
            if routine.employee_id not in employee_ids_with_checklist:
                emp = session.get(models.Employee, routine.employee_id)
                if emp and emp.status == "active" and emp.mobile_access_checklist:
                    alertas["colaboradores_sem_checklist"].append({
                        "id": emp.id,
                        "name": emp.name,
                        "role": emp.role,
                    })
    
    # Calcular total de alertas
    alertas["total_alertas"] = (
        len(alertas["ordens_pendentes"]) +
        len(alertas["ordens_atrasadas"]) +
        len(alertas["colaboradores_sem_rota"]) +
        len(alertas["colaboradores_sem_checklist"])
    )
    
    return alertas


# --- GM: Ordens de ServiÃƒÆ’Ã‚Â§o Operacionais ---

def require_gm(request: Request):
    """Verifica se o usuÃƒÆ’Ã‚Â¡rio ÃƒÆ’Ã‚Â© GM (admin) para acessar ordens de serviÃƒÆ’Ã‚Â§o."""
    user = require_login(request)
    role = user.get("role", "").lower() if isinstance(user, dict) else ""
    if role not in ("admin", "gm"):
        raise HTTPException(status_code=403, detail="Acesso restrito ao Gerente")
    return user


@app.get("/gm/ordens-servico", response_class=HTMLResponse)
async def gm_ordens_servico_page(request: Request, session: Session = Depends(get_session)):
    """PÃƒÆ’Ã‚Â¡gina principal: criar e gerenciar ordens de serviÃƒÆ’Ã‚Â§o."""
    user = require_gm(request)
    
    # Buscar tarefas ativas
    tasks = session.exec(
        select(models.OperationalTask)
        .where(models.OperationalTask.status.in_(["active", "paused"]))
        .order_by(desc(models.OperationalTask.created_at))
    ).all()
    
    # Buscar lÃƒÆ’Ã‚Â­deres (usuÃƒÆ’Ã‚Â¡rios com role leader)
    leaders = session.exec(
        select(models.User)
        .where(models.User.role == "leader")
        .where(models.User.is_active == True)
    ).all()
    
    # Buscar execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes do dia para mostrar status
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    executions_today = session.exec(
        select(models.OperationalTaskExecution)
        .where(models.OperationalTaskExecution.scheduled_date == today)
    ).all()
    
    # Mapear execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes por task_id e user_id
    exec_map = {}
    for ex in executions_today:
        key = (ex.task_id, ex.user_id)
        exec_map[key] = ex
    
    return templates.TemplateResponse("gm_ordens_servico.html", {
        "request": request,
        "user": user,
        "tasks": tasks,
        "leaders": leaders,
        "executions_today": exec_map,
        "today": today,
    })


@app.post("/api/gm/ordens-servico", response_class=JSONResponse)
async def api_gm_create_ordem(request: Request, session: Session = Depends(get_session)):
    """Criar nova ordem de serviÃƒÆ’Ã‚Â§o."""
    user = require_gm(request)
    try:
        body = await request.json()
        title = (body.get("title") or "").strip()
        if not title:
            return JSONResponse({"error": "TÃƒÆ’Ã‚Â­tulo ÃƒÆ’Ã‚Â© obrigatÃƒÆ’Ã‚Â³rio"}, status_code=400)
        
        description = (body.get("description") or "").strip() or None
        category = (body.get("category") or "geral").strip().lower()
        priority = (body.get("priority") or "medium").strip().lower()
        if priority not in ("low", "medium", "high"):
            priority = "medium"
        
        recurrence_type = (body.get("recurrence_type") or "once").strip().lower()
        if recurrence_type not in ("once", "daily", "weekly", "monthly"):
            recurrence_type = "once"
        
        recurrence_days = body.get("recurrence_days") or []
        if isinstance(recurrence_days, list):
            recurrence_days = [int(x) for x in recurrence_days if str(x).isdigit()]
        else:
            recurrence_days = []
        
        recurrence_day_of_month = None
        if body.get("recurrence_day_of_month"):
            try:
                recurrence_day_of_month = int(body["recurrence_day_of_month"])
                if recurrence_day_of_month < 1 or recurrence_day_of_month > 31:
                    recurrence_day_of_month = None
            except:
                pass
        
        scheduled_time = (body.get("scheduled_time") or "").strip() or None
        estimated_duration = body.get("estimated_duration_minutes")
        if estimated_duration:
            try:
                estimated_duration = int(estimated_duration)
            except:
                estimated_duration = None
        
        recipient_user_ids = body.get("recipient_user_ids") or []
        if isinstance(recipient_user_ids, list):
            recipient_user_ids = [int(x) for x in recipient_user_ids if x]
        else:
            recipient_user_ids = []
        
        requires_photo = bool(body.get("requires_photo"))
        requires_note = bool(body.get("requires_note"))
        
        valid_from = None
        if body.get("valid_from"):
            try:
                valid_from = datetime.fromisoformat(body["valid_from"].replace("Z", "+00:00"))
            except:
                pass
        
        valid_until = None
        if body.get("valid_until"):
            try:
                valid_until = datetime.fromisoformat(body["valid_until"].replace("Z", "+00:00"))
            except:
                pass
        
        username = (user.get("username") or user.get("name") or "GM") if isinstance(user, dict) else "GM"
        
        task = models.OperationalTask(
            title=title,
            description=description,
            category=category,
            priority=priority,
            recurrence_type=recurrence_type,
            recurrence_days=recurrence_days,
            recurrence_day_of_month=recurrence_day_of_month,
            scheduled_time=scheduled_time,
            estimated_duration_minutes=estimated_duration,
            recipient_user_ids=recipient_user_ids,
            requires_photo=requires_photo,
            requires_note=requires_note,
            valid_from=valid_from,
            valid_until=valid_until,
            created_by=username,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        
        # Gerar execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes para hoje se aplicÃƒÆ’Ã‚Â¡vel
        generate_executions_for_task(session, task)
        
        return {"success": True, "task_id": task.id}
    except Exception as e:
        logger.exception("Erro ao criar ordem de serviÃƒÆ’Ã‚Â§o")
        return JSONResponse({"error": str(e)}, status_code=500)


def generate_executions_for_task(session: Session, task: models.OperationalTask, target_date: str = None):
    """Gera execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes para uma tarefa em uma data especÃƒÆ’Ã‚Â­fica."""
    if target_date is None:
        target_date = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    weekday = target_dt.weekday()  # 0=segunda, 6=domingo
    day_of_month = target_dt.day
    
    # Verificar se a tarefa deve ser executada nesta data
    should_execute = False
    
    if task.recurrence_type == "once":
        # Tarefa ÃƒÆ’Ã‚Âºnica - executar se foi criada hoje ou se valid_from ÃƒÆ’Ã‚Â© hoje
        if task.valid_from:
            should_execute = task.valid_from.strftime("%Y-%m-%d") == target_date
        else:
            should_execute = task.created_at.strftime("%Y-%m-%d") == target_date
    elif task.recurrence_type == "daily":
        should_execute = True
    elif task.recurrence_type == "weekly":
        should_execute = weekday in (task.recurrence_days or [])
    elif task.recurrence_type == "monthly":
        should_execute = day_of_month == task.recurrence_day_of_month
    
    if not should_execute:
        return
    
    # Verificar validade
    if task.valid_from and target_dt < task.valid_from.replace(tzinfo=None):
        return
    if task.valid_until and target_dt > task.valid_until.replace(tzinfo=None):
        return
    
    # Criar execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o para cada lÃƒÆ’Ã‚Â­der responsÃƒÆ’Ã‚Â¡vel
    for user_id in (task.recipient_user_ids or []):
        # Verificar se jÃƒÆ’Ã‚Â¡ existe execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o para este lÃƒÆ’Ã‚Â­der nesta data
        existing = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.task_id == task.id)
            .where(models.OperationalTaskExecution.user_id == user_id)
            .where(models.OperationalTaskExecution.scheduled_date == target_date)
        ).first()
        
        if not existing:
            execution = models.OperationalTaskExecution(
                task_id=task.id,
                scheduled_date=target_date,
                user_id=user_id,
                status="pending",
            )
            session.add(execution)
    
    session.commit()


@app.get("/api/gm/ordens-servico", response_class=JSONResponse)
async def api_gm_list_ordens(request: Request, session: Session = Depends(get_session)):
    """Listar ordens de serviÃƒÆ’Ã‚Â§o."""
    require_gm(request)
    tasks = session.exec(
        select(models.OperationalTask)
        .where(models.OperationalTask.status.in_(["active", "paused"]))
        .order_by(desc(models.OperationalTask.created_at))
    ).all()
    
    out = []
    for t in tasks:
        out.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "category": t.category,
            "priority": t.priority,
            "recurrence_type": t.recurrence_type,
            "scheduled_time": t.scheduled_time,
            "status": t.status,
            "recipient_user_ids": t.recipient_user_ids or [],
            "created_by": t.created_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


@app.put("/api/gm/ordens-servico/{task_id}", response_class=JSONResponse)
async def api_gm_update_ordem(task_id: int, request: Request, session: Session = Depends(get_session)):
    """Atualizar ordem de serviÃƒÆ’Ã‚Â§o."""
    require_gm(request)
    task = session.get(models.OperationalTask, task_id)
    if not task:
        return JSONResponse({"error": "Tarefa nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    
    try:
        body = await request.json()
        
        if "title" in body:
            task.title = (body["title"] or "").strip() or task.title
        if "description" in body:
            task.description = (body["description"] or "").strip() or None
        if "category" in body:
            task.category = (body["category"] or "geral").strip().lower()
        if "priority" in body:
            priority = (body["priority"] or "medium").strip().lower()
            task.priority = priority if priority in ("low", "medium", "high") else task.priority
        if "status" in body:
            status = (body["status"] or "active").strip().lower()
            task.status = status if status in ("active", "paused", "archived") else task.status
        if "recipient_user_ids" in body:
            recipient_user_ids = body["recipient_user_ids"] or []
            if isinstance(recipient_user_ids, list):
                task.recipient_user_ids = [int(x) for x in recipient_user_ids if x]
        if "scheduled_time" in body:
            task.scheduled_time = (body["scheduled_time"] or "").strip() or None
        if "requires_photo" in body:
            task.requires_photo = bool(body["requires_photo"])
        if "requires_note" in body:
            task.requires_note = bool(body["requires_note"])
        
        task.updated_at = datetime.now()
        session.add(task)
        session.commit()
        
        return {"success": True}
    except Exception as e:
        logger.exception("Erro ao atualizar ordem de serviÃƒÆ’Ã‚Â§o")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/gm/ordens-servico/{task_id}", response_class=JSONResponse)
async def api_gm_delete_ordem(task_id: int, request: Request, session: Session = Depends(get_session)):
    """Arquivar ordem de serviÃƒÆ’Ã‚Â§o."""
    require_gm(request)
    task = session.get(models.OperationalTask, task_id)
    if not task:
        return JSONResponse({"error": "Tarefa nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    
    task.status = "archived"
    task.updated_at = datetime.now()
    session.add(task)
    session.commit()
    
    return {"success": True}


@app.get("/gm/ordens-servico/historico", response_class=HTMLResponse)
async def gm_ordens_historico_page(request: Request, session: Session = Depends(get_session)):
    """PÃƒÆ’Ã‚Â¡gina de histÃƒÆ’Ã‚Â³rico de execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes."""
    user = require_gm(request)
    
    # Buscar todas as execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes dos ÃƒÆ’Ã‚Âºltimos 30 dias
    start_date = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=30)).strftime("%Y-%m-%d")
    
    executions = session.exec(
        select(models.OperationalTaskExecution)
        .where(models.OperationalTaskExecution.scheduled_date >= start_date)
        .order_by(desc(models.OperationalTaskExecution.scheduled_date))
    ).all()
    
    # Enriquecer com dados da tarefa e lÃƒÆ’Ã‚Â­der
    enriched = []
    for ex in executions:
        task = session.get(models.OperationalTask, ex.task_id)
        leader = session.get(models.User, ex.user_id)
        enriched.append({
            "execution": ex,
            "task": task,
            "leader": leader,
        })
    
    return templates.TemplateResponse("gm_ordens_historico.html", {
        "request": request,
        "user": user,
        "executions": enriched,
    })


@app.get("/api/gm/ordens-servico/historico", response_class=JSONResponse)
async def api_gm_historico(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[int] = None,
    status: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """API para buscar histÃƒÆ’Ã‚Â³rico de execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes com filtros."""
    require_gm(request)
    
    query = select(models.OperationalTaskExecution)
    
    if start_date:
        query = query.where(models.OperationalTaskExecution.scheduled_date >= start_date)
    if end_date:
        query = query.where(models.OperationalTaskExecution.scheduled_date <= end_date)
    if user_id:
        query = query.where(models.OperationalTaskExecution.user_id == user_id)
    if status:
        query = query.where(models.OperationalTaskExecution.status == status)
    
    query = query.order_by(desc(models.OperationalTaskExecution.scheduled_date))
    executions = session.exec(query).all()
    
    out = []
    for ex in executions:
        task = session.get(models.OperationalTask, ex.task_id)
        leader = session.get(models.User, ex.user_id)
        out.append({
            "id": ex.id,
            "task_id": ex.task_id,
            "task_title": task.title if task else "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â",
            "scheduled_date": ex.scheduled_date,
            "user_id": ex.user_id,
            "leader_name": leader.username if leader else "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â",
            "status": ex.status,
            "started_at": ex.started_at.isoformat() if ex.started_at else None,
            "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
            "note": ex.note,
            "postponed_to": ex.postponed_to,
            "postpone_reason": ex.postpone_reason,
            "not_done_reason": ex.not_done_reason,
        })
    return out


@app.get("/gm/ordens-servico/kpis", response_class=HTMLResponse)
async def gm_ordens_kpis_page(request: Request, session: Session = Depends(get_session)):
    """PÃƒÆ’Ã‚Â¡gina de KPIs dos lÃƒÆ’Ã‚Â­deres."""
    user = require_gm(request)
    
    # Buscar lÃƒÆ’Ã‚Â­deres
    leaders = session.exec(
        select(models.User)
        .where(models.User.role == "leader")
        .where(models.User.is_active == True)
    ).all()
    
    # Calcular KPIs para cada lÃƒÆ’Ã‚Â­der (ÃƒÆ’Ã‚Âºltimos 30 dias)
    start_date = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=30)).strftime("%Y-%m-%d")
    
    kpis = []
    for leader in leaders:
        executions = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.user_id == leader.id)
            .where(models.OperationalTaskExecution.scheduled_date >= start_date)
        ).all()
        
        total = len(executions)
        completed = len([e for e in executions if e.status == "completed"])
        in_progress = len([e for e in executions if e.status == "in_progress"])
        pending = len([e for e in executions if e.status == "pending"])
        postponed = len([e for e in executions if e.status == "postponed"])
        not_done = len([e for e in executions if e.status == "not_done"])
        justified = len([e for e in executions if e.status == "justified"])
        
        # Calcular taxa de conclusÃƒÆ’Ã‚Â£o
        completion_rate = (completed / total * 100) if total > 0 else 0
        
        # Calcular taxa de pontualidade (completadas no dia programado)
        on_time = 0
        for ex in executions:
            if ex.status == "completed" and ex.completed_at:
                completed_date = ex.completed_at.strftime("%Y-%m-%d")
                if completed_date == ex.scheduled_date:
                    on_time += 1
        punctuality_rate = (on_time / completed * 100) if completed > 0 else 0
        
        # Taxa de adiamento
        postpone_rate = (postponed / total * 100) if total > 0 else 0
        
        # Taxa de nÃƒÆ’Ã‚Â£o execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
        not_done_rate = (not_done / total * 100) if total > 0 else 0
        
        # Score geral (fÃƒÆ’Ã‚Â³rmula ponderada)
        score = (
            completion_rate * 0.40 +
            punctuality_rate * 0.30 +
            (100 - postpone_rate) * 0.15 +
            (100 - not_done_rate) * 0.15
        )
        
        kpis.append({
            "leader": leader,
            "total": total,
            "completed": completed,
            "pending": pending,
            "in_progress": in_progress,
            "postponed": postponed,
            "not_done": not_done,
            "justified": justified,
            "completion_rate": round(completion_rate, 1),
            "punctuality_rate": round(punctuality_rate, 1),
            "postpone_rate": round(postpone_rate, 1),
            "not_done_rate": round(not_done_rate, 1),
            "score": round(score, 1),
        })
    
    # Ordenar por score descendente
    kpis.sort(key=lambda x: x["score"], reverse=True)
    
    return templates.TemplateResponse("gm_ordens_kpis.html", {
        "request": request,
        "user": user,
        "kpis": kpis,
    })


@app.get("/api/gm/ordens-servico/kpis", response_class=JSONResponse)
async def api_gm_kpis(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """API para buscar KPIs com filtro de perÃƒÆ’Ã‚Â­odo."""
    require_gm(request)
    
    if not start_date:
        start_date = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    leaders = session.exec(
        select(models.User)
        .where(models.User.role == "leader")
        .where(models.User.is_active == True)
    ).all()
    
    kpis = []
    for leader in leaders:
        executions = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.user_id == leader.id)
            .where(models.OperationalTaskExecution.scheduled_date >= start_date)
            .where(models.OperationalTaskExecution.scheduled_date <= end_date)
        ).all()
        
        total = len(executions)
        completed = len([e for e in executions if e.status == "completed"])
        postponed = len([e for e in executions if e.status == "postponed"])
        not_done = len([e for e in executions if e.status == "not_done"])
        
        completion_rate = (completed / total * 100) if total > 0 else 0
        
        on_time = 0
        for ex in executions:
            if ex.status == "completed" and ex.completed_at:
                completed_date = ex.completed_at.strftime("%Y-%m-%d")
                if completed_date == ex.scheduled_date:
                    on_time += 1
        punctuality_rate = (on_time / completed * 100) if completed > 0 else 0
        
        postpone_rate = (postponed / total * 100) if total > 0 else 0
        not_done_rate = (not_done / total * 100) if total > 0 else 0
        
        score = (
            completion_rate * 0.40 +
            punctuality_rate * 0.30 +
            (100 - postpone_rate) * 0.15 +
            (100 - not_done_rate) * 0.15
        )
        
        kpis.append({
            "user_id": leader.id,
            "username": leader.username,
            "total": total,
            "completed": completed,
            "completion_rate": round(completion_rate, 1),
            "punctuality_rate": round(punctuality_rate, 1),
            "postpone_rate": round(postpone_rate, 1),
            "not_done_rate": round(not_done_rate, 1),
            "score": round(score, 1),
        })
    
    kpis.sort(key=lambda x: x["score"], reverse=True)
    return kpis


# --- Rotas para LÃƒÆ’Ã‚ÂDERES executarem as ordens ---

@app.get("/lider/minhas-ordens", response_class=HTMLResponse)
async def lider_minhas_ordens_page(request: Request, session: Session = Depends(get_session)):
    """PÃƒÆ’Ã‚Â¡gina do lÃƒÆ’Ã‚Â­der para ver e executar suas ordens de serviÃƒÆ’Ã‚Â§o."""
    user = require_leader(request)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    if not user_id:
        return HTMLResponse("UsuÃƒÆ’Ã‚Â¡rio nÃƒÆ’Ã‚Â£o identificado", status_code=403)
    
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    # Gerar execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes do dia para todas as tarefas ativas
    active_tasks = session.exec(
        select(models.OperationalTask)
        .where(models.OperationalTask.status == "active")
    ).all()
    
    for task in active_tasks:
        if user_id in (task.recipient_user_ids or []):
            generate_executions_for_task(session, task, today)
    
    # Buscar execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes do lÃƒÆ’Ã‚Â­der para hoje
    executions_today = session.exec(
        select(models.OperationalTaskExecution)
        .where(models.OperationalTaskExecution.user_id == user_id)
        .where(models.OperationalTaskExecution.scheduled_date == today)
        .order_by(models.OperationalTaskExecution.id)
    ).all()
    
    # Enriquecer com dados da tarefa
    tasks_today = []
    for ex in executions_today:
        task = session.get(models.OperationalTask, ex.task_id)
        if task:
            tasks_today.append({
                "execution": ex,
                "task": task,
            })
    
    # Buscar histÃƒÆ’Ã‚Â³rico recente (ÃƒÆ’Ã‚Âºltimos 7 dias)
    week_ago = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=7)).strftime("%Y-%m-%d")
    history = session.exec(
        select(models.OperationalTaskExecution)
        .where(models.OperationalTaskExecution.user_id == user_id)
        .where(models.OperationalTaskExecution.scheduled_date >= week_ago)
        .where(models.OperationalTaskExecution.scheduled_date < today)
        .order_by(desc(models.OperationalTaskExecution.scheduled_date))
    ).all()
    
    history_enriched = []
    for ex in history:
        task = session.get(models.OperationalTask, ex.task_id)
        if task:
            history_enriched.append({
                "execution": ex,
                "task": task,
            })
    
    return templates.TemplateResponse("lider_minhas_ordens.html", {
        "request": request,
        "user": user,
        "tasks_today": tasks_today,
        "history": history_enriched,
        "today": today,
    })


@app.get("/api/lider/minhas-ordens", response_class=JSONResponse)
async def api_lider_minhas_ordens(request: Request, session: Session = Depends(get_session)):
    """API: listar ordens do lÃƒÆ’Ã‚Â­der para hoje."""
    user = require_leader(request)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    if not user_id:
        return []
    
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    executions = session.exec(
        select(models.OperationalTaskExecution)
        .where(models.OperationalTaskExecution.user_id == user_id)
        .where(models.OperationalTaskExecution.scheduled_date == today)
    ).all()
    
    out = []
    for ex in executions:
        task = session.get(models.OperationalTask, ex.task_id)
        if task:
            out.append({
                "execution_id": ex.id,
                "task_id": task.id,
                "title": task.title,
                "description": task.description,
                "category": task.category,
                "priority": task.priority,
                "scheduled_time": task.scheduled_time,
                "requires_photo": task.requires_photo,
                "requires_note": task.requires_note,
                "status": ex.status,
                "started_at": ex.started_at.isoformat() if ex.started_at else None,
                "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
            })
    return out


@app.post("/api/lider/ordens/{execution_id}/iniciar", response_class=JSONResponse)
async def api_lider_iniciar_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """LÃƒÆ’Ã‚Â­der inicia execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o da ordem."""
    user = require_leader(request)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "ExecuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem nÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© sua"}, status_code=403)
    if execution.status not in ("pending",):
        return JSONResponse({"error": f"Status atual ({execution.status}) nÃƒÆ’Ã‚Â£o permite iniciar"}, status_code=400)
    
    execution.status = "in_progress"
    execution.started_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    execution.updated_at = datetime.now()
    session.add(execution)
    session.commit()
    
    return {"success": True, "status": execution.status}


@app.post("/api/lider/ordens/{execution_id}/concluir", response_class=JSONResponse)
async def api_lider_concluir_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """LÃƒÆ’Ã‚Â­der conclui execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o da ordem."""
    user = require_leader(request)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "ExecuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem nÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© sua"}, status_code=403)
    if execution.status not in ("pending", "in_progress"):
        return JSONResponse({"error": f"Status atual ({execution.status}) nÃƒÆ’Ã‚Â£o permite concluir"}, status_code=400)
    
    try:
        body = await request.json()
    except:
        body = {}
    
    task = session.get(models.OperationalTask, execution.task_id)
    
    note = (body.get("note") or "").strip() or None
    photo_urls = body.get("photo_urls") or []
    
    # Validar requisitos
    if task and task.requires_note and not note:
        return JSONResponse({"error": "ObservaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© obrigatÃƒÆ’Ã‚Â³ria para esta tarefa"}, status_code=400)
    if task and task.requires_photo and not photo_urls:
        return JSONResponse({"error": "Foto ÃƒÆ’Ã‚Â© obrigatÃƒÆ’Ã‚Â³ria para esta tarefa"}, status_code=400)
    
    execution.status = "completed"
    execution.completed_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    execution.note = note
    execution.photo_urls = photo_urls if isinstance(photo_urls, list) else []
    execution.updated_at = datetime.now()
    
    if not execution.started_at:
        execution.started_at = execution.completed_at
    
    session.add(execution)
    session.commit()
    
    return {"success": True, "status": execution.status}


@app.post("/api/lider/ordens/{execution_id}/adiar", response_class=JSONResponse)
async def api_lider_adiar_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """LÃƒÆ’Ã‚Â­der adia execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o da ordem."""
    user = require_leader(request)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "ExecuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem nÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© sua"}, status_code=403)
    if execution.status not in ("pending", "in_progress"):
        return JSONResponse({"error": f"Status atual ({execution.status}) nÃƒÆ’Ã‚Â£o permite adiar"}, status_code=400)
    
    try:
        body = await request.json()
    except:
        body = {}
    
    postponed_to = (body.get("postponed_to") or "").strip()
    postpone_reason = (body.get("reason") or "").strip()
    
    if not postponed_to:
        return JSONResponse({"error": "Nova data ÃƒÆ’Ã‚Â© obrigatÃƒÆ’Ã‚Â³ria"}, status_code=400)
    if not postpone_reason:
        return JSONResponse({"error": "Motivo do adiamento ÃƒÆ’Ã‚Â© obrigatÃƒÆ’Ã‚Â³rio"}, status_code=400)
    
    execution.status = "postponed"
    execution.postponed_to = postponed_to
    execution.postpone_reason = postpone_reason
    execution.updated_at = datetime.now()
    session.add(execution)
    session.commit()
    
    return {"success": True, "status": execution.status}


@app.post("/api/lider/ordens/{execution_id}/nao-fazer", response_class=JSONResponse)
async def api_lider_nao_fazer_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """LÃƒÆ’Ã‚Â­der marca ordem como nÃƒÆ’Ã‚Â£o realizada."""
    user = require_leader(request)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "ExecuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem nÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© sua"}, status_code=403)
    if execution.status not in ("pending", "in_progress"):
        return JSONResponse({"error": f"Status atual ({execution.status}) nÃƒÆ’Ã‚Â£o permite esta aÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o"}, status_code=400)
    
    try:
        body = await request.json()
    except:
        body = {}
    
    reason = (body.get("reason") or "").strip()
    
    if not reason:
        return JSONResponse({"error": "Motivo ÃƒÆ’Ã‚Â© obrigatÃƒÆ’Ã‚Â³rio"}, status_code=400)
    
    execution.status = "not_done"
    execution.not_done_reason = reason
    execution.updated_at = datetime.now()
    session.add(execution)
    session.commit()
    
    return {"success": True, "status": execution.status}


# Job para gerar execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes diÃƒÆ’Ã‚Â¡rias (pode ser chamado por cron ou no startup)
@app.post("/api/gm/ordens-servico/gerar-execucoes", response_class=JSONResponse)
async def api_gm_gerar_execucoes(request: Request, session: Session = Depends(get_session)):
    """Gera execuÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes para o dia atual para todas as tarefas ativas."""
    require_gm(request)
    
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    active_tasks = session.exec(
        select(models.OperationalTask)
        .where(models.OperationalTask.status == "active")
    ).all()
    
    generated = 0
    for task in active_tasks:
        before_count = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.task_id == task.id)
            .where(models.OperationalTaskExecution.scheduled_date == today)
        ).all()
        
        generate_executions_for_task(session, task, today)
        
        after_count = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.task_id == task.id)
            .where(models.OperationalTaskExecution.scheduled_date == today)
        ).all()
        
        generated += len(after_count) - len(before_count)
    
    return {"success": True, "generated": generated, "date": today}


# --- Operational History Routes ---

@app.get("/operational/history", response_class=HTMLResponse)
async def operational_history_page(request: Request, session: Session = Depends(get_session)):
    """Render the Operational History Page"""
    try:
        user = require_login(request)
        can_view_checklist_links = (
            isinstance(user, dict)
            and user.get("type") == "user"
            and (user.get("role") or "").lower() in {"admin", "leader"}
        )

        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
        start_date = now_br - timedelta(days=30)
        events = session.exec(
            select(models.Event)
            .where(
                or_(
                    models.Event.reference_type == "checklist",
                    models.Event.type == "checklist"
                ),
                models.Event.timestamp >= start_date
            )
            .order_by(desc(models.Event.timestamp))
        ).all()

        employee_ids = {evt.employee_id for evt in events if evt.employee_id}
        employee_map = {}
        if employee_ids:
            employees = session.exec(
                select(models.Employee).where(models.Employee.id.in_(employee_ids))
            ).all()
            employee_map = {emp.id: emp.name for emp in employees if emp}

        checklist_refs = {
            evt.reference_id
            for evt in events
            if evt.reference_type == "checklist" and evt.reference_id
        }
        existing_checklists = set()
        if checklist_refs:
            existing_checklists = set(
                session.exec(
                    select(models.TranspalletChecklist.id).where(
                        models.TranspalletChecklist.id.in_(checklist_refs)
                    )
                ).all()
            )

        processed_events = []
        for evt in events:
            employee_name = employee_map.get(evt.employee_id) if evt.employee_id else None
            reference_exists = bool(
                evt.reference_type == "checklist"
                and evt.reference_id
                and evt.reference_id in existing_checklists
            )
            processed_events.append({
                "id": evt.id,
                "timestamp": evt.timestamp,
                "text": evt.text,
                "reference_type": evt.reference_type,
                "reference_id": evt.reference_id,
                "sector": evt.sector,
                "employee_name": employee_name,
                "reference_exists": reference_exists
            })
        events = processed_events

        return templates.TemplateResponse(
            "operational_history.html",
            {
                "request": request,
                "events": events,
                "can_view_checklist_links": can_view_checklist_links
            }
        )
    except Exception as e:
        logger.exception("Error rendering operational history")
        return HTMLResponse(content=f"Error: {e}", status_code=500)

from gamification_engine import calculate_daily_xp # Import for recalculation

@app.get("/api/operational/routes")
async def api_operational_routes(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = 'date',
    status: Optional[str] = None,
    session: Session = Depends(get_session)
):
    try:
        query = select(models.Route, models.Employee.name, models.Client.name).join(models.Employee).join(models.Client)
        
        # Filtering
        if start_date:
            query = query.where(models.Route.date >= start_date)
        if end_date:
            query = query.where(models.Route.date <= end_date)
            
        if status:
            query = query.where(models.Route.status == status)
            
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    models.Employee.name.ilike(search_pattern),
                    models.Client.name.ilike(search_pattern),
                    models.Route.date.ilike(search_pattern)
                )
            )

        # Sorting
        # Simple Logic: Only Sort by Date desc by default
        query = query.order_by(desc(models.Route.date), desc(models.Route.id))
        
        results = session.exec(query).all()
        
        # Prepare Response
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))

        data = []
        for r, emp_name, client_name in results:
            s_time = r.start_time
            e_time = r.end_time
            
            # Strategy: If time is in the future relative to NOW, assume it's UTC and subtract 3h.
            # Additional Context: If route is 'pending' or 'completed', it CANNOT be in the future.
            # NEW Context: If Start > End (and End exists), likely Start is UTC and End is Local.
            
            def clean_time_str(time_val):
                if time_val is None: return None
                time_str = ""
                # Handle datetime.time
                if isinstance(time_val, (time, type(datetime.now(ZoneInfo("America/Sao_Paulo")).time()))):
                    time_str = time_val.strftime("%H:%M:%S")
                else:
                    time_str = str(time_val).strip()
                
                try:
                    clean = time_str.split(".")[0]
                    parts = clean.split(":")
                    if len(parts) >= 2:
                        return f"{parts[0]}:{parts[1]}"
                    return clean
                except:
                    return time_str

            s_time = clean_time_str(s_time)
            e_time = clean_time_str(e_time)

            data.append({
                "id": r.id,
                "date": r.date,
                "employee_name": emp_name,
                "employee_id": r.employee_id,
                "client_name": client_name,
                "client_id": r.client_id,
                "start_time": s_time,
                "end_time": e_time,
                "tonnage": r.tonnage,
                "status": r.status
            })
            
            # Calculate Duration
            duration_str = "-"
            if s_time and e_time:
                try:
                    # Parse HH:MM (returned by heuristic)
                    s = datetime.strptime(s_time, "%H:%M")
                    e = datetime.strptime(e_time, "%H:%M")
                    diff = (e - s).total_seconds()
                    if diff < 0: diff += 86400 # Handle overnight if needed
                    
                    dh = int(diff // 3600)
                    dm = int((diff % 3600) // 60)
                    duration_str = f"{dh:02d}:{dm:02d}"
                except:
                    pass
            
            data[-1]["duration"] = duration_str
            
            # Est. XP (Approx 100 XP per 1500kg)
            est_xp = int((r.tonnage / 1500.0) * 100)
            data[-1]["est_xp"] = est_xp
            
        return {"routes": data}
        
    except Exception as e:
        logger.exception("Error fetching routes")
        return JSONResponse({"error": str(e)}, status_code=500)

class RouteUpdateModel(BaseModel):
    tonnage: Optional[float] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: Optional[str] = None

@app.put("/api/operational/routes/{route_id}")
async def api_update_route(
    route_id: int, 
    payload: RouteUpdateModel, 
    session: Session = Depends(get_session)
):
    try:
        route = session.get(models.Route, route_id)
        if not route:
            return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
            
        if payload.tonnage is not None:
            route.tonnage = payload.tonnage
        if payload.start_time is not None:
            route.start_time = payload.start_time
        if payload.end_time is not None:
            route.end_time = payload.end_time
        if payload.status is not None:
            route.status = payload.status
            
        session.add(route)
        session.commit()
        
        # Recalculate Daily XP
        try:
            calculate_daily_xp(session, route.date)
        except Exception as e:
            logger.error(f"Error recalculating XP on update: {e}")
            
        return {"success": True}
    except Exception as e:
        logger.exception(f"Error updating route {route_id}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/operational/routes/{route_id}")
async def api_delete_route(route_id: int, session: Session = Depends(get_session)):
    try:
        route = session.get(models.Route, route_id)
        if not route:
            return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
        
        target_date = route.date # Save date before delete
        session.delete(route)
        session.commit()
        
        # Recalculate Daily XP
        try:
            calculate_daily_xp(session, target_date)
        except Exception as e:
            logger.error(f"Error recalculating XP on delete: {e}")

        return {"success": True}
    except Exception as e:
        logger.exception(f"Error deleting route {route_id}")
        return JSONResponse({"error": str(e)}, status_code=500)

# --- Admin Checklist Routes ---`r`n`r`n@app.get("/admin/equipment/tickets/{ticket_id}"))
async def admin_equipment_ticket_detail(
    request: Request,
    ticket_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    try:
        require_login(request)
        ticket = session.get(models.EquipmentTicket, ticket_id)
        if not ticket:
            return HTMLResponse("Chamado nÃƒÆ’Ã‚Â£o encontrado", status_code=404)
        
        employee = session.get(models.Employee, ticket.employee_id) if ticket.employee_id else None
        events = session.exec(
            select(models.EquipmentTicketEvent)
            .where(models.EquipmentTicketEvent.ticket_id == ticket_id)
            .order_by(models.EquipmentTicketEvent.created_at.desc())
        ).all()
    except Exception as e:
        logger.exception(f"Error loading ticket {ticket_id}")
        return HTMLResponse(f"Erro ao carregar chamado: {str(e)}", status_code=500)
    
    ticket_data = {
        "ticket": ticket,
        "employee": employee,
        "created_at_br": fmt_datetime_br(ticket.created_at),
        "closed_at_br": fmt_datetime_br(ticket.closed_at) if ticket.closed_at else None,
        "image_urls": [f"/static/uploads/tickets/{img}" for img in (ticket.images or [])],
        "events": events
    }

    return templates.TemplateResponse(
        "admin_equipment_ticket_detail.html",
        {
            "request": request,
            "data": ticket_data
        }
    )

@app.post("/admin/equipment/tickets/{ticket_id}/delete", response_class=RedirectResponse)
async def admin_equipment_ticket_delete(
    request: Request,
    ticket_id: int,
    confirm_delete: bool = Form(False),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    ticket = session.get(models.EquipmentTicket, ticket_id)
    if not ticket:
         return RedirectResponse(url="/admin/equipment/tickets?message=Erro&level=error", status_code=303)
         
    if not confirm_delete:
        return RedirectResponse(
            url=f"/admin/equipment/tickets/{ticket_id}?message=Confirme+a+exclus%C3%A3o&level=error", 
            status_code=303
        )
        
    session.add(models.Event(
        timestamp=datetime.now(ZoneInfo("America/Sao_Paulo")),
        text=f"Chamado #{ticket.id} EXCLUÃƒÆ’Ã‚ÂDO por {actor_label}.",
        type="ticket_delete",
        category="audit",
        reference_type="ticket_deleted",
        reference_id=ticket.id
    ))
    
    session.delete(ticket)
    session.commit()
    
    return RedirectResponse(
        url="/admin/equipment/tickets?message=Chamado+exclu%C3%ADdo+com+sucesso", 
        status_code=303
    )

@app.get("/admin/equipment/history", response_class=HTMLResponse)
async def admin_equipment_history(
    request: Request,
    code: str = "",
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    code = (code or "").strip().upper()
    equipment = None
    history = []
    
    if code:
        equipment = session.exec(select(models.TranspalletEquipment).where(models.TranspalletEquipment.code == code)).first()
        
        # Fetch Checklists
        checklists = session.exec(
            select(models.TranspalletChecklist, models.Employee)
            .join(models.Employee, models.Employee.id == models.TranspalletChecklist.employee_id)
            .where(models.TranspalletChecklist.equipment_code == code)
            .order_by(models.TranspalletChecklist.submitted_at.desc())
            .limit(50)
        ).all()
        
        for chk, emp in checklists:
            history.append({
                "type": "checklist",
                "date": chk.submitted_at,
                "date_br": fmt_datetime_br(chk.submitted_at),
                "employee": emp,
                "data": chk,
                "status": "critical" if chk.critical_flag else ("nonconforming" if chk.nonconforming_keys else "ok")
            })
            
        # Fetch Tickets
        tickets = session.exec(
            select(models.EquipmentTicket, models.Employee)
            .join(models.Employee, models.Employee.id == models.EquipmentTicket.employee_id)
            .where(models.EquipmentTicket.equipment_code == code)
            .order_by(models.EquipmentTicket.created_at.desc())
            .limit(50)
        ).all()
        
        for tkt, emp in tickets:
            history.append({
                "type": "ticket",
                "date": tkt.created_at,
                "date_br": fmt_datetime_br(tkt.created_at),
                "employee": emp,
                "data": tkt,
                "status": tkt.status
            })
            
        # Sort combined
        history.sort(key=lambda x: x["date"], reverse=True)

    return templates.TemplateResponse(
        "admin_equipment_history.html",
        {
            "request": request,
            "code": code,
            "equipment": equipment,
            "history": history
        }
    )

@app.post("/admin/routine/checklists/settings/emails/{recipient_id}/test", response_class=RedirectResponse)
async def admin_checklists_test_email(
    request: Request,
    recipient_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    actor_label = user.get("email") if isinstance(user, dict) else str(user or "Sistema")
    recipient = session.get(models.AbsenceAlertRecipient, recipient_id)
    if not recipient:
        return admin_checklists_settings_redirect("E-mail nÃƒÆ’Ã‚Â£o encontrado.", "error")
        
    try:
        report = {
            "subject": "ALERTA DE MANUTENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O - TESTE",
            "body": "Teste de envio de alerta de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o.",
            "equipment_code": "EMP-TESTE-01",
            "operator_name": actor_label,
            "registered_by": actor_label,
            "operator_id": "00000",
            "shift": "ManhÃƒÆ’Ã‚Â£",
            "submitted_at": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y ÃƒÆ’Ã‚Â s %H:%M"),
            "observations": "Este ÃƒÆ’Ã‚Â© um e-mail de teste enviado pela tela de configuraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes.",
            "nonconforming_items": [
                {"label": "Freio de estacionamento", "critical": True},
                {"label": "SinalizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o sonora", "critical": False},
            ],
        }
        sent, error = send_maintenance_email(report, [recipient.email])
        if not sent:
            return admin_checklists_settings_redirect(f"Erro ao testar: {error}", "error")
    except Exception as e:
        return admin_checklists_settings_redirect(f"Erro ao testar: {e}", "error")

    return admin_checklists_settings_redirect(f"E-mail de teste enviado para {recipient.email}", "success")

# ============================================================================
# ABSENCE ALERTS (ADVERTÃƒÆ’Ã…Â NCIA) - ConfiguraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de E-mails
# ============================================================================

def absence_alerts_settings_redirect(message: str, level: str = "success"):
    """Redirect helper for absence alerts settings page"""
    from urllib.parse import quote
    return RedirectResponse(
        url=f"{ALERT_SETTINGS_PATH}?message={quote(message)}&level={level}",
        status_code=status.HTTP_303_SEE_OTHER
    )

def send_absence_alert_email(
    employee: models.Employee,
    absence_date: str,
    registered_by: str,
    recipients: List[str],
    days: int = 1,
    alert_type: str = "absent"
) -> tuple:
    """
    Envia e-mail de alerta de ausÃƒÆ’Ã‚Âªncia (falta, folga, atestado ou saÃƒÆ’Ã‚Â­da antecipada).
    alert_type: 'absent' (falta/advertÃƒÆ’Ã‚Âªncia), 'dayoff' (folga), 'sick' (atestado), 'early_exit' (saÃƒÆ’Ã‚Â­da antecipada)
    Retorna (success: bool, error: str ou None)
    """
    smtp_port = parse_int_env(SMTP_PORT_RAW, 587)
    smtp_tls = parse_bool_env(SMTP_TLS_RAW, True)
    recipient_list = [normalize_email(r) for r in recipients if normalize_email(r)]
    
    if not recipient_list:
        return False, "Nenhum destinatÃƒÆ’Ã‚Â¡rio configurado"
    
    config_error = smtp_config_error(recipient_list)
    if config_error:
        logger.error(config_error)
        return False, config_error
    
    if SMTP_USE_SSL_RAW.strip():
        smtp_use_ssl = parse_bool_env(SMTP_USE_SSL_RAW, False)
    else:
        smtp_use_ssl = smtp_port == 465
    
    # Formatar data
    try:
        date_obj = datetime.strptime(absence_date, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%d/%m/%Y")
    except:
        formatted_date = absence_date
    
    days_text = f"{days} dia(s)" if days > 1 else "1 dia"
    
    # ConfiguraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o por tipo de alerta
    alert_configs = {
        "absent": {
            "emoji": "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨",
            "title": "SOLICITAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE ADVERTÃƒÆ’Ã…Â NCIA",
            "subtitle": "Falta NÃƒÆ’Ã‚Â£o Justificada Registrada",
            "type_label": "FALTA",
            "date_label": "Data da Falta",
            "color": "#dc2626",
            "action": "Solicitamos a abertura de processo de advertÃƒÆ’Ã‚Âªncia conforme procedimento interno."
        },
        "dayoff": {
            "emoji": "ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã¢â‚¬Â¦",
            "title": "NOTIFICAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE FOLGA",
            "subtitle": "Folga Registrada no Sistema",
            "type_label": "FOLGA",
            "date_label": "Data da Folga",
            "color": "#2563eb",
            "action": "Informamos para fins de controle de escala e planejamento operacional."
        },
        "sick": {
            "emoji": "ÃƒÂ°Ã…Â¸Ã‚ÂÃ‚Â¥",
            "title": "NOTIFICAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE ATESTADO MÃƒÆ’Ã¢â‚¬Â°DICO",
            "subtitle": "Atestado MÃƒÆ’Ã‚Â©dico Registrado no Sistema",
            "type_label": "ATESTADO MÃƒÆ’Ã¢â‚¬Â°DICO",
            "date_label": "Data do Atestado",
            "color": "#d97706",
            "action": "Informamos para fins de controle mÃƒÆ’Ã‚Â©dico e registro de afastamento."
        },
        "early_exit": {
            "emoji": "ÃƒÂ¢Ã‚ÂÃ‚Â°",
            "title": "NOTIFICAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O DE SAÃƒÆ’Ã‚ÂDA ANTECIPADA",
            "subtitle": "SaÃƒÆ’Ã‚Â­da antecipada registrada no sistema",
            "type_label": "SAÃƒÆ’Ã‚ÂDA ANTECIPADA",
            "date_label": "Data da SaÃƒÆ’Ã‚Â­da",
            "color": "#fb7185",
            "action": "Solicitamos atualizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o do controle de jornada, conferÃƒÆ’Ã‚Âªncia do ponto e validaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o da saÃƒÆ’Ã‚Â­da antecipada."
        }
    }
    
    config = alert_configs.get(alert_type, alert_configs["absent"])
    
    # Montar assunto
    subject = f"{config['emoji']} {config['title']} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {config['type_label']} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {employee.name}"
    
    # Montar corpo do e-mail
    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: {config['color']}; color: white; padding: 15px 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0; font-size: 18px;">{config['emoji']} {config['title']}</h2>
                <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">{config['subtitle']}</p>
            </div>
            
            <div style="background: #f9fafb; padding: 20px; border: 1px solid #e5e7eb; border-top: none;">
                <p>Prezados,</p>
                
                <p>Informamos que o colaborador abaixo foi registrado com <strong style="color: {config['color']};">{config['type_label']}</strong> no sistema:</p>
                
                <div style="background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 15px; margin: 20px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Colaborador:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{employee.name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>MatrÃƒÆ’Ã‚Â­cula:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{employee.registration_id}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Cargo:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{employee.role or '-'}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Turno:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{employee.work_shift or '-'}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>{config['date_label']}:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6; color: {config['color']}; font-weight: bold;">{formatted_date}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>PerÃƒÆ’Ã‚Â­odo:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{days_text}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Registrado por:</strong></td>
                            <td style="padding: 8px 0;">{registered_by}</td>
                        </tr>
                    </table>
                </div>
                
                <p><strong>{config['action']}</strong></p>
                
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                
                <p style="font-size: 12px; color: #6b7280;">
                    Este ÃƒÆ’Ã‚Â© um e-mail automÃƒÆ’Ã‚Â¡tico gerado pelo sistema de AnÃƒÆ’Ã‚Â¡lise Operacional.<br>
                    Data/Hora do registro: {datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y ÃƒÆ’Ã‚Â s %H:%M")}
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    body_text = f"""
{config['title']} - {config['type_label']}

Prezados,

Informamos que o colaborador abaixo foi registrado com {config['type_label']} no sistema:

- Colaborador: {employee.name}
- MatrÃƒÆ’Ã‚Â­cula: {employee.registration_id}
- Cargo: {employee.role or '-'}
- Turno: {employee.work_shift or '-'}
- {config['date_label']}: {formatted_date}
- PerÃƒÆ’Ã‚Â­odo: {days_text}
- Registrado por: {registered_by}

{config['action']}

---
Este ÃƒÆ’Ã‚Â© um e-mail automÃƒÆ’Ã‚Â¡tico gerado pelo sistema de AnÃƒÆ’Ã‚Â¡lise Operacional.
Data/Hora do registro: {datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y ÃƒÆ’Ã‚Â s %H:%M")}
    """
    
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAINTENANCE_EMAIL_FROM_FIXED
    msg["To"] = ", ".join(recipient_list)
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")
    
    logger.info(
        "Enviando e-mail de alerta (%s) | host=%s port=%s tls=%s ssl=%s from=%s recipients=%s employee=%s",
        alert_type,
        SMTP_HOST,
        smtp_port,
        smtp_tls,
        smtp_use_ssl,
        MAINTENANCE_EMAIL_FROM_FIXED,
        recipient_list,
        employee.name
    )
    
    try:
        if smtp_use_ssl:
            smtp_client = smtplib.SMTP_SSL(SMTP_HOST, smtp_port, timeout=20)
        else:
            smtp_client = smtplib.SMTP(SMTP_HOST, smtp_port, timeout=20)
        with smtp_client as smtp:
            if not smtp_use_ssl and smtp_tls:
                smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        logger.info(f"E-mail de alerta ({alert_type}) enviado com sucesso para {employee.name}.")
        return True, None
    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"Erro ao enviar e-mail de alerta ({alert_type}): {error_msg}")
        return False, error_msg


def send_absence_alert_email_background(
    employee_id: int,
    employee_name: str,
    employee_registration_id: str,
    employee_role: str,
    employee_work_shift: str,
    absence_date: str,
    registered_by: str,
    recipients: List[str],
    days: int,
    alert_type: str
):
    """
    FunÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o executada em background para enviar e-mail de alerta.
    Recebe dados primitivos em vez de objetos SQLModel para evitar problemas de sessÃƒÆ’Ã‚Â£o.
    """
    from database import get_session
    
    # Criar objeto fake de employee apenas com os dados necessÃƒÆ’Ã‚Â¡rios para o e-mail
    class EmployeeData:
        def __init__(self, id, name, registration_id, role, work_shift):
            self.id = id
            self.name = name
            self.registration_id = registration_id
            self.role = role
            self.work_shift = work_shift
    
    employee_data = EmployeeData(
        id=employee_id,
        name=employee_name,
        registration_id=employee_registration_id,
        role=employee_role,
        work_shift=employee_work_shift
    )
    
    alert_type_labels = {
        "absent": "advertÃƒÆ’Ã‚Âªncia",
        "dayoff": "folga",
        "sick": "atestado",
        "early_exit": "saÃƒÆ’Ã‚Â­da antecipada"  # Logado como alerta especÃƒÆ’Ã‚Â­fico
    }
    
    try:
        # Enviar e-mail
        email_sent, email_error = send_absence_alert_email(
            employee=employee_data,
            absence_date=absence_date,
            registered_by=registered_by,
            recipients=recipients,
            days=days,
            alert_type=alert_type
        )
        
        if email_sent:
            # Registrar log no banco de dados usando nova sessÃƒÆ’Ã‚Â£o
            with Session(engine) as session:
                alert_log = models.AbsenceAlertLog(
                    employee_id=employee_id,
                    absence_date=absence_date,
                    sent_by=registered_by,
                    recipients_count=len(recipients)
                )
                session.add(alert_log)
                session.commit()
            print(f"ÃƒÂ°Ã…Â¸Ã¢â‚¬Å“Ã‚Â§ [Background] E-mail de {alert_type_labels.get(alert_type, 'alerta')} enviado para {len(recipients)} destinatÃƒÆ’Ã‚Â¡rio(s) - {employee_name}")
        else:
            print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â [Background] Falha ao enviar e-mail de {alert_type_labels.get(alert_type, 'alerta')}: {email_error}")
    except Exception as exc:
        print(f"ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â [Background] Erro ao processar envio de e-mail: {exc}")
        import traceback
        traceback.print_exc()


@app.get("/admin/alerts/settings", response_class=HTMLResponse)
@app.get("/admin/absence-alerts/settings", response_class=HTMLResponse)
async def admin_absence_alerts_settings(
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """PÃƒÆ’Ã‚Â¡gina de configuraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o de alertas de falta (advertÃƒÆ’Ã‚Âªncias)"""
    message = request.query_params.get("message")
    level = request.query_params.get("level", "success")
    
    recipients = session.exec(
        select(models.AbsenceAlertRecipient)
        .where(models.AbsenceAlertRecipient.is_active == True)
        .order_by(models.AbsenceAlertRecipient.email)
    ).all()
    
    # Filtrar por tipo para o template
    absent_recipients = [r for r in recipients if getattr(r, 'alert_type', 'absent') == 'absent']
    dayoff_recipients = [r for r in recipients if getattr(r, 'alert_type', None) == 'dayoff']
    sick_recipients = [r for r in recipients if getattr(r, 'alert_type', None) == 'sick']
    # Novo grupo de destinatÃƒÆ’Ã‚Â¡rios para saÃƒÆ’Ã‚Â­da antecipada
    early_exit_recipients = [r for r in recipients if getattr(r, 'alert_type', None) == 'early_exit']
    # MigraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o leve: espelha destinatÃƒÆ’Ã‚Â¡rios antigos de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o para a tabela setorial (com campo name/setor)
    legacy_maintenance = session.exec(
        select(models.ChecklistEmailRecipient).order_by(models.ChecklistEmailRecipient.email)
    ).all()
    for legacy in legacy_maintenance:
        legacy_email = normalize_email(getattr(legacy, "email", ""))
        if not legacy_email:
            continue
        existing_maintenance = session.exec(
            select(models.AbsenceAlertRecipient)
            .where(models.AbsenceAlertRecipient.email == legacy_email)
            .where(models.AbsenceAlertRecipient.alert_type == "maintenance")
        ).first()
        if not existing_maintenance:
            session.add(
                models.AbsenceAlertRecipient(
                    email=legacy_email,
                    name=None,
                    alert_type="maintenance",
                    is_active=bool(getattr(legacy, "is_active", True)),
                )
            )
    session.commit()

    maintenance_recipients = session.exec(
        select(models.AbsenceAlertRecipient)
        .where(models.AbsenceAlertRecipient.alert_type == "maintenance")
        .order_by(models.AbsenceAlertRecipient.email)
    ).all()
    
    # Info SMTP para exibiÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o
    smtp_configured = bool(SMTP_HOST and SMTP_USER and SMTP_PASS)
    
    return templates.TemplateResponse(
        "admin_absence_alerts_settings.html",
        {
            "request": request,
            "user": user,
            "recipients": recipients,
            "absent_recipients": absent_recipients,
            "dayoff_recipients": dayoff_recipients,
            "sick_recipients": sick_recipients,
            "early_exit_recipients": early_exit_recipients,
            "maintenance_recipients": maintenance_recipients,
            "message": message,
            "level": level,
            "smtp_host": SMTP_HOST,
            "smtp_port": SMTP_PORT_RAW,
            "smtp_user": SMTP_USER,
            "smtp_configured": smtp_configured
        }
    )

@app.post("/admin/alerts/settings/emails", response_class=RedirectResponse)
@app.post("/admin/absence-alerts/settings/emails", response_class=RedirectResponse)
async def admin_absence_alerts_add_email(
    request: Request,
    email: str = Form(...),
    name: str = Form(""),
    alert_type: str = Form("absent"),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """Adiciona ou reativa um e-mail de destinatÃƒÆ’Ã‚Â¡rio de alertas de ausÃƒÆ’Ã‚Âªncia"""
    email_normalized = normalize_email(email)
    if not email_normalized:
        return absence_alerts_settings_redirect("E-mail invÃƒÆ’Ã‚Â¡lido.", "error")
    
    # Validar alert_type
    valid_types = ["absent", "dayoff", "sick", "early_exit"]
    # 'early_exit' usa os mesmos destinatÃƒÆ’Ã‚Â¡rios das ausÃƒÆ’Ã‚Âªncias crÃƒÆ’Ã‚Â­ticas
    if alert_type not in valid_types:
        alert_type = "absent"
    
    type_labels = {
        "absent": "Falta",
        "dayoff": "Folga",
        "sick": "Atestado",
        "early_exit": "SaÃƒÆ’Ã‚Â­da antecipada"
    }
    type_label = type_labels.get(alert_type, "Falta")
    
    # Verificar se jÃƒÆ’Ã‚Â¡ existe para este tipo
    existing = session.exec(
        select(models.AbsenceAlertRecipient)
        .where(models.AbsenceAlertRecipient.email == email_normalized)
        .where(models.AbsenceAlertRecipient.alert_type == alert_type)
    ).first()
    
    if existing:
        if existing.is_active:
            return absence_alerts_settings_redirect(f"E-mail jÃƒÆ’Ã‚Â¡ cadastrado para {type_label}.", "error")
        else:
            # Reativar
            existing.is_active = True
            existing.name = name.strip() if name else existing.name
            session.add(existing)
            session.commit()
            return absence_alerts_settings_redirect(f"E-mail reativado para {type_label}.", "success")
    
    # Criar novo
    new_recipient = models.AbsenceAlertRecipient(
        email=email_normalized,
        name=name.strip() if name else None,
        alert_type=alert_type,
        is_active=True
    )
    session.add(new_recipient)
    session.commit()
    
    return absence_alerts_settings_redirect(f"E-mail cadastrado para {type_label}.", "success")

@app.post("/admin/alerts/settings/emails/{recipient_id}/delete", response_class=RedirectResponse)
@app.post("/admin/absence-alerts/settings/emails/{recipient_id}/delete", response_class=RedirectResponse)
async def admin_absence_alerts_remove_email(
    request: Request,
    recipient_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """Remove (desativa) um e-mail de destinatÃƒÆ’Ã‚Â¡rio de alertas de falta"""
    recipient = session.get(models.AbsenceAlertRecipient, recipient_id)
    if not recipient:
        return absence_alerts_settings_redirect("E-mail nÃƒÆ’Ã‚Â£o encontrado.", "error")
    
    recipient.is_active = False
    session.add(recipient)
    session.commit()
    
    return absence_alerts_settings_redirect("E-mail removido com sucesso.", "success")

@app.post("/admin/alerts/settings/emails/{recipient_id}/test", response_class=RedirectResponse)
@app.post("/admin/absence-alerts/settings/emails/{recipient_id}/test", response_class=RedirectResponse)
async def admin_absence_alerts_test_email(
    request: Request,
    recipient_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    """Envia e-mail de teste para um destinatÃƒÆ’Ã‚Â¡rio"""
    recipient = session.get(models.AbsenceAlertRecipient, recipient_id)
    if not recipient:
        return absence_alerts_settings_redirect("E-mail nÃƒÆ’Ã‚Â£o encontrado.", "error")
    
    # Criar funcionÃƒÆ’Ã‚Â¡rio fictÃƒÆ’Ã‚Â­cio para teste
    class MockEmployee:
        name = "FUNCIONÃƒÆ’Ã‚ÂRIO TESTE"
        registration_id = "00000"
        role = "Colaborador de Teste"
        work_shift = "ManhÃƒÆ’Ã‚Â£"
    
    mock_employee = MockEmployee()
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    registered_by = user.get("email") if isinstance(user, dict) else str(user or "Sistema")
    
    # Determinar tipo de alerta para o teste
    alert_type = recipient.alert_type or "absent"
    
    success, error = send_absence_alert_email(
        employee=mock_employee,
        absence_date=today,
        registered_by=registered_by,
        recipients=[recipient.email],
        days=1,
        alert_type=alert_type
    )
    
    type_labels = {
        "absent": "Falta",
        "dayoff": "Folga",
        "sick": "Atestado",
        "early_exit": "SaÃƒÆ’Ã‚Â­da antecipada"
    }
    type_label = type_labels.get(alert_type, "Falta")
    
    if success:
        return absence_alerts_settings_redirect(f"E-mail de teste ({type_label}) enviado para {recipient.email}", "success")
    else:
        return absence_alerts_settings_redirect(f"Erro ao enviar: {error}", "error")

@app.post("/admin/absence-alerts/settings/maintenance-emails", response_class=RedirectResponse)
async def admin_absence_maintenance_add_email(
    request: Request,
    email: str = Form(...),
    name: str = Form(""),
    session: Session = Depends(get_session),
    user=Depends(require_leader),
):
    email_norm = normalize_email(email)
    if not email_norm or "@" not in email_norm:
        return maintenance_emails_settings_redirect("E-mail invÃƒÆ’Ã‚Â¡lido.", "error")

    existing = session.exec(
        select(models.AbsenceAlertRecipient)
        .where(models.AbsenceAlertRecipient.email == email_norm)
        .where(models.AbsenceAlertRecipient.alert_type == "maintenance")
    ).first()
    if existing:
        existing.name = (name or "").strip() or existing.name
        if existing.is_active:
            session.add(existing)
            session.commit()
            return maintenance_emails_settings_redirect("E-mail jÃƒÆ’Ã‚Â¡ cadastrado.", "error")
        existing.is_active = True
        session.add(existing)
        session.commit()
    else:
        recipient = models.AbsenceAlertRecipient(
            email=email_norm,
            name=(name or "").strip() or None,
            alert_type="maintenance",
            is_active=True,
        )
        session.add(recipient)
        session.commit()

    legacy = session.exec(
        select(models.ChecklistEmailRecipient)
        .where(models.ChecklistEmailRecipient.email == email_norm)
    ).first()
    if legacy:
        legacy.is_active = True
        session.add(legacy)
    else:
        session.add(models.ChecklistEmailRecipient(email=email_norm, is_active=True))
    session.commit()

    return maintenance_emails_settings_redirect("E-mail cadastrado com sucesso.", "success")
@app.post("/admin/absence-alerts/settings/maintenance-emails/{recipient_id}/delete", response_class=RedirectResponse)
async def admin_absence_maintenance_remove_email(
    request: Request,
    recipient_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader),
):
    recipient = session.get(models.AbsenceAlertRecipient, recipient_id)
    if not recipient:
        return maintenance_emails_settings_redirect("E-mail nÃƒÆ’Ã‚Â£o encontrado.", "error")
    if recipient.alert_type != "maintenance":
        return maintenance_emails_settings_redirect("Tipo de destinatÃƒÆ’Ã‚Â¡rio invÃƒÆ’Ã‚Â¡lido.", "error")

    if recipient.is_active:
        recipient.is_active = False
        session.add(recipient)

    legacy = session.exec(
        select(models.ChecklistEmailRecipient)
        .where(models.ChecklistEmailRecipient.email == recipient.email)
    ).first()
    if legacy and legacy.is_active:
        legacy.is_active = False
        session.add(legacy)
    session.commit()

    return maintenance_emails_settings_redirect("E-mail removido.", "success")
@app.post("/admin/absence-alerts/settings/maintenance-emails/{recipient_id}/test", response_class=RedirectResponse)
async def admin_absence_maintenance_test_email(
    request: Request,
    recipient_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader),
):
    actor_label = user.get("email") if isinstance(user, dict) else str(user or "Sistema")
    recipient = session.get(models.AbsenceAlertRecipient, recipient_id)
    if not recipient:
        return maintenance_emails_settings_redirect("E-mail nÃƒÆ’Ã‚Â£o encontrado.", "error")
    if recipient.alert_type != "maintenance":
        return maintenance_emails_settings_redirect("Tipo de destinatÃƒÆ’Ã‚Â¡rio invÃƒÆ’Ã‚Â¡lido.", "error")

    try:
        report = {
            "subject": "ALERTA DE MANUTENÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O - TESTE",
            "body": "Teste de envio de alerta de manutenÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o.",
            "equipment_code": "EMP-TESTE-01",
            "operator_name": actor_label,
            "registered_by": actor_label,
            "operator_id": "00000",
            "shift": "ManhÃƒÆ’Ã‚Â£",
            "submitted_at": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y ÃƒÆ’Ã‚Â s %H:%M"),
            "observations": "Este ÃƒÆ’Ã‚Â© um e-mail de teste enviado pela tela de configuraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes.",
            "nonconforming_items": [
                {"label": "Freio de estacionamento", "critical": True},
                {"label": "SinalizaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Â£o sonora", "critical": False},
            ],
        }
        sent, error = send_maintenance_email(report, [recipient.email])
        if not sent:
            return maintenance_emails_settings_redirect(f"Erro ao testar: {error}", "error")
    except Exception as exc:
        return maintenance_emails_settings_redirect(f"Erro ao testar: {exc}", "error")

    return maintenance_emails_settings_redirect(f"E-mail de teste enviado para {recipient.email}", "success")

# =============================================================================
# PALLET TRUCK COUNTING SYSTEM
# =============================================================================

class RouteEditPayload(BaseModel):
    employee_id: int
    client_id: int
    tonnage: Optional[float] = 0.0
    reason: str

class RouteDeletePayload(BaseModel):
    reason: str


# ============================================================================
# MOBILE ADMIN - ROUTE MANAGEMENT
# ============================================================================

@app.get("/mobile/admin/routes", response_class=HTMLResponse)
async def mobile_admin_routes_page(
    request: Request,
    session: Session = Depends(get_session)
):
    """PÃƒÆ’Ã‚Â¡gina de gestÃƒÆ’Ã‚Â£o de rotas para lÃƒÆ’Ã‚Â­deres"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/mobile/login", status_code=303)
    
    try:
        user_id = int(str(user_id))
    except:
        return RedirectResponse(url="/mobile/login", status_code=303)
    
    employee = session.get(models.Employee, user_id)
    if not employee or not employee.mobile_access:
        return RedirectResponse(url="/mobile/login?error=access_revoked", status_code=303)
    
    if not getattr(employee, "mobile_access_admin_start", False):
        return RedirectResponse(url="/mobile/dashboard?error=no_permission", status_code=303)
    
    return templates.TemplateResponse(
        "mobile/admin_routes.html",
        {
            "request": request,
            "employee": employee
        }
    )


@app.get("/api/mobile/admin/routes")
async def api_list_admin_routes(
    request: Request,
    session: Session = Depends(get_session)
):
    """API para listar rotas ativas e colaboradores sem rota"""
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
    
    try:
        user_id = int(str(user_id))
    except:
        return JSONResponse({"error": "ID invÃƒÆ’Ã‚Â¡lido"}, status_code=400)
    
    current_emp = session.get(models.Employee, user_id)
    if not current_emp or not getattr(current_emp, "mobile_access_admin_start", False):
        return JSONResponse({"error": "Sem permissÃƒÆ’Ã‚Â£o"}, status_code=403)
    
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    
    # Rotas ativas (pendentes) de hoje
    active_routes = session.exec(
        select(models.Route)
        .where(
            models.Route.date == today,
            models.Route.status == "pending"
        )
        .order_by(models.Route.start_time)
    ).all()
    
    routes_data = []
    for route in active_routes:
        emp = session.get(models.Employee, route.employee_id)
        client = session.get(models.Client, route.client_id)
        
        routes_data.append({
            "id": route.id,
            "employee_id": route.employee_id,
            "employee_name": emp.name if emp else "Desconhecido",
            "employee_registration": emp.registration_id if emp else "N/A",
            "client_id": route.client_id,
            "client_name": client.name if client else "Desconhecido",
            "tonnage": route.tonnage,
            "start_time": route.start_time,
            "shift": route.shift
        })
    
    # Colaboradores ativos sem rota hoje
    all_active_employees = session.exec(
        select(models.Employee)
        .where(
            models.Employee.status == "active",
            models.Employee.mobile_access == True
        )
    ).all()
    
    employees_with_route = {route.employee_id for route in active_routes}
    
    # Filtrar colaboradores que tiveram rota nos ÃƒÆ’Ã‚Âºltimos 4 dias
    four_days_ago = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=4)).strftime("%Y-%m-%d")
    
    recent_route_employees = session.exec(
        select(models.Route.employee_id)
        .where(
            models.Route.date >= four_days_ago,
            models.Route.date <= today
        )
        .distinct()
    ).all()
    
    recent_employee_ids = set(recent_route_employees)
    
    employees_without_route = []
    for emp in all_active_employees:
        # Mostrar apenas se: nÃƒÆ’Ã‚Â£o tem rota hoje E teve rota nos ÃƒÆ’Ã‚Âºltimos 4 dias
        if emp.id not in employees_with_route and emp.id in recent_employee_ids:
            employees_without_route.append({
                "id": emp.id,
                "name": emp.name,
                "registration_id": emp.registration_id,
                "shift": emp.work_shift or "ManhÃƒÆ’Ã‚Â£"
            })
    
    # Buscar todos os clientes para os selects
    all_clients = session.exec(select(models.Client).order_by(models.Client.name)).all()
    clients_data = [{"id": c.id, "name": c.name} for c in all_clients]
    
    # Buscar todos os colaboradores ativos para os selects
    all_employees_data = [
        {
            "id": e.id,
            "name": e.name,
            "registration_id": e.registration_id
        }
        for e in all_active_employees
    ]
    
    return JSONResponse({
        "success": True,
        "active_routes": routes_data,
        "employees_without_route": employees_without_route,
        "all_clients": clients_data,
        "all_employees": all_employees_data
    })


@app.post("/api/mobile/admin/routes/{route_id}/edit")
async def api_edit_admin_route(
    route_id: int,
    payload: RouteEditPayload,
    request: Request,
    session: Session = Depends(get_session)
):
    """API para editar uma rota"""
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
        
        try:
            user_id = int(str(user_id))
        except:
            return JSONResponse({"error": "ID invÃƒÆ’Ã‚Â¡lido"}, status_code=400)
        
        current_emp = session.get(models.Employee, user_id)
        if not current_emp or not getattr(current_emp, "mobile_access_admin_start", False):
            return JSONResponse({"error": "Sem permissÃƒÆ’Ã‚Â£o"}, status_code=403)
        
        # Validar justificativa
        if not payload.reason or len(payload.reason.strip()) < 5:
            return JSONResponse({"error": "Justificativa obrigatÃƒÆ’Ã‚Â³ria (mÃƒÆ’Ã‚Â­nimo 5 caracteres)"}, status_code=400)
        
        # Buscar rota
        route = session.get(models.Route, route_id)
        if not route:
            return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
        
        # Validar colaborador
        target_emp = session.get(models.Employee, payload.employee_id)
        if not target_emp:
            return JSONResponse({"error": "Colaborador nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
        
        # Validar cliente
        client = session.get(models.Client, payload.client_id)
        if not client:
            return JSONResponse({"error": "Cliente nÃƒÆ’Ã‚Â£o encontrado"}, status_code=404)
        
        # Registrar alteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes
        old_emp = session.get(models.Employee, route.employee_id)
        old_client = session.get(models.Client, route.client_id)
        
        changes = []
        if route.employee_id != payload.employee_id:
            changes.append(f"Colaborador: {old_emp.name if old_emp else 'N/A'} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {target_emp.name}")
        if route.client_id != payload.client_id:
            changes.append(f"Cliente: {old_client.name if old_client else 'N/A'} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {client.name}")
        if route.tonnage != payload.tonnage:
            changes.append(f"Tonelagem: {route.tonnage} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {payload.tonnage}")
        
        # Atualizar rota
        route.employee_id = payload.employee_id
        route.client_id = payload.client_id
        route.tonnage = payload.tonnage
        session.add(route)
        
        # Log de auditoria
        log = models.Event(
            type="route_edit",
            text=f"Rota #{route_id} editada por {current_emp.name}. AlteraÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes: {'; '.join(changes)}. Justificativa: {payload.reason}",
            category="processo",
            sector="expedicao",
            impact="medium",
            employee_id=route.employee_id,
            timestamp=datetime.now(ZoneInfo("America/Sao_Paulo"))
        )
        session.add(log)
        
        session.commit()
        return JSONResponse({"success": True, "message": "Rota editada com sucesso"})
        
    except Exception as e:
        logger.exception("Error editing route")
        return JSONResponse({"error": f"Erro interno: {str(e)}"}, status_code=500)


@app.post("/api/mobile/admin/routes/{route_id}/delete")
async def api_delete_admin_route(
    route_id: int,
    payload: RouteDeletePayload,
    request: Request,
    session: Session = Depends(get_session)
):
    """API para excluir uma rota"""
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return JSONResponse({"error": "NÃƒÆ’Ã‚Â£o autorizado"}, status_code=401)
        
        try:
            user_id = int(str(user_id))
        except:
            return JSONResponse({"error": "ID invÃƒÆ’Ã‚Â¡lido"}, status_code=400)
        
        current_emp = session.get(models.Employee, user_id)
        if not current_emp or not getattr(current_emp, "mobile_access_admin_start", False):
            return JSONResponse({"error": "Sem permissÃƒÆ’Ã‚Â£o"}, status_code=403)
        
        # Validar justificativa
        if not payload.reason or len(payload.reason.strip()) < 5:
            return JSONResponse({"error": "Justificativa obrigatÃƒÆ’Ã‚Â³ria (mÃƒÆ’Ã‚Â­nimo 5 caracteres)"}, status_code=400)
        
        # Buscar rota
        route = session.get(models.Route, route_id)
        if not route:
            return JSONResponse({"error": "Rota nÃƒÆ’Ã‚Â£o encontrada"}, status_code=404)
        
        # Guardar informaÃƒÆ’Ã‚Â§ÃƒÆ’Ã‚Âµes para log
        emp = session.get(models.Employee, route.employee_id)
        client = session.get(models.Client, route.client_id)
        
        # Log de auditoria
        log = models.Event(
            type="route_delete",
            text=f"Rota #{route_id} excluÃƒÆ’Ã‚Â­da por {current_emp.name}. Colaborador: {emp.name if emp else 'N/A'}, Cliente: {client.name if client else 'N/A'}. Justificativa: {payload.reason}",
            category="processo",
            sector="expedicao",
            impact="high",
            employee_id=route.employee_id,
            timestamp=datetime.now(ZoneInfo("America/Sao_Paulo"))
        )
        session.add(log)
        
        # Excluir rota
        session.delete(route)
        session.commit()
        
        return JSONResponse({"success": True, "message": "Rota excluÃƒÆ’Ã‚Â­da com sucesso"})
        
    except Exception as e:
        logger.exception("Error deleting route")
        return JSONResponse({"error": f"Erro interno: {str(e)}"}, status_code=500)



