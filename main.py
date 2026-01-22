# Force Reload for TZDATA
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional, List
import json
import csv
import io
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import traceback
import os
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select, col, delete, text, or_, desc
from sqlalchemy import func
from typing import List
from database import create_db_and_tables, get_session, engine
import models
import logging
import pydantic
from logging.handlers import RotatingFileHandler
import unicodedata
import os
from dotenv import load_dotenv

load_dotenv()
# Performance: Use INFO level in production, DEBUG only when explicitly enabled
LOG_LEVEL = logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO

# Use RotatingFileHandler to prevent infinite log growth
handler = RotatingFileHandler(
    'logs.txt',
    maxBytes=5*1024*1024,  # 5 MB max per file
    backupCount=3  # Keep 3 backup files
)
handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
))

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)
logger.addHandler(handler)

# --- Config ---
SECRET_KEY = "your-secret-key-change-in-production"
ALLOWED_USER = os.getenv("ADMIN_USER", "admin")
ALLOWED_PASS = os.getenv("ADMIN_PASS", "admin")

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
    descontando dias de férias se houver sobreposição.
    
    Args:
        work_days_json: JSON string com dias da semana
        start_date: Data inicial do período
        end_date: Data final do período (exclusiva, geralmente)
        vacation_start: Início das férias
        vacation_end: Fim das férias
    
    Returns:
        Número de dias esperados de trabalho
    """
    # Default fallback: Segunda a Sábado (6 dias)
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
    
    # Converter work_days para números
    work_day_numbers = {day_map[day] for day in work_days if day in day_map}
    
    # Contar dias no período
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
        
        # Só conta se for dia de trabalho E não estiver de férias
        if not is_vacation and current_date.weekday() in work_day_numbers:
            expected_days += 1
        current_date += timedelta(days=1)
    
    return expected_days


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
    """
    check_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    check_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999)
    employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
    for emp in employees:
        if emp.vacation_start and emp.vacation_end:
            # Basic validation of dates
            v_start = emp.vacation_start
            v_end = emp.vacation_end
            
            # Normalize for comparison
            v_s = v_start.replace(hour=0, minute=0, second=0, microsecond=0)
            v_e = v_end.replace(hour=23, minute=59, second=59, microsecond=999)
            
            should_be_vacation = v_s <= check_start <= v_e
            
            if should_be_vacation:
                if emp.status != 'vacation':
                    emp.status = 'vacation'
                    session.add(emp)
            else:
                # If currently marked as vacation but NOT in vacation period anymore (or yet)
                # revert to active.
                if emp.status == 'vacation':
                    emp.status = 'active'
                    session.add(emp)
    session.commit()
def sync_sectors_on_startup():
    """Sincroniza automaticamente Sector -> SectorConfiguration ao iniciar"""
    try:
        print("🔄 Sincronizando setores com configuração...")
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
                            print(f"   🔧 Auto-Corrigindo {s.name} ({shift}): {cs.get('target')} -> {s.max_employees}")
                            cs['target'] = s.max_employees
                            changed = True
                
                if changed:
                    config_db.config_json = data
                    config_db.updated_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
                    session.add(config_db)
            
            session.commit()
        print("✅ Sincronização de startup concluída.")
    except Exception as e:
        print(f"❌ Erro no sync de startup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    try:
        from database import engine
        print(f"🌍 DATABASE URL DETECTADA: {engine.url}")
        sync_sectors_on_startup()
    except Exception as e:
        print(f"❌ Erro ao iniciar sync: {e}")
    yield

app = FastAPI(title="Análise Operacional", version="2.0.0", lifespan=lifespan)

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
    if request.url.path.startswith("/api/") or request.url.path.startswith("/smart-flow") or request.url.path.startswith("/routine/report"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
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

templates.env.filters["fmt_br"] = fmt_br
templates.env.filters["fmt_br_int"] = fmt_br_int

# --- Auth Helper Functions ---
def get_current_user(request: Request):
    user = request.session.get("user")
    if user: return user
    
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
    # User is Admin (str) -> Can access everything (or maybe restrict from mobile specific logic if needed, but usually fine)
    if isinstance(user, str):
        return user

    # User is Employee (dict) -> RESTRICTED TO /mobile ONLY
    if isinstance(user, dict) and user.get("type") == "employee":
        if not path.startswith("/mobile") and not path.startswith("/static") and not path.startswith("/api"):
            # Trying to access Desktop/Admin page -> Redirect to Mobile Dashboard
            # e.g. /smart-flow, /employees, /
            print(f"🔒 Access Denied: Mobile User {user.get('id')} tried to access {path}")
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/mobile/dashboard"})

    return user

def require_gm(request: Request, session: Session = Depends(get_session)):
    """
    Dependency to ensure the user is logged in AND is a Game Master (Admin).
    """
    try:
        user = get_current_user(request)
        if not user:
             raise HTTPException(status_code=403, detail="Not authenticated")
        
        if isinstance(user, str):
            # "Admin" or similar string -> ALLOW
            return None 

        if isinstance(user, dict):
            # Employee
            user_id = user.get("id")
            emp = session.get(models.Employee, user_id)
            if not emp:
                 raise HTTPException(status_code=403, detail="Employee not found")
            
            # Strict check: Regular employees cannot trigger audits.
            # Only allow if role implies GM rights (or we just restrict this to Admin string users for now?)
            # Let's check if role is "Admin" or similar.
            if emp.role not in ["Admin", "Manager", "Master"]:
                raise HTTPException(status_code=403, detail="Acesso negado: Requer privilégios de Admin/GM.")

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
    icon: Optional[str] = "🏆"
    xp_reward: int = 100
    category: str = "general"
    trigger_type: str = "manual"
    trigger_value: Optional[str] = None

@app.get("/admin/game/achievements", response_class=HTMLResponse)
def admin_achievements_page(request: Request, user=Depends(require_login)):
    """Page to manage achievements"""
    return templates.TemplateResponse("admin_achievements.html", {"request": request, "user": user})

@app.get("/api/game/achievements")
def api_list_achievements(session: Session = Depends(get_session), user=Depends(require_login)):
    try:
        achievements = session.exec(select(models.GameAchievement).order_by(models.GameAchievement.xp_reward)).all()
        return {"success": True, "data": achievements}
    except Exception as e:
        logger.error(f"Error listing achievements: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/game/achievements")
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
                return {"success": False, "error": "Achievement not found"}
            
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

@app.delete("/api/game/achievements/{ach_id}")
def api_delete_achievement(ach_id: int, session: Session = Depends(get_session), user=Depends(require_login)):
    try:
        ach = session.get(models.GameAchievement, ach_id)
        if not ach:
            return {"success": False, "error": "Not found"}
        
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

@app.post("/api/game/achievements/grant")
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
            return {"success": False, "error": "Conquista ou Colaborador não encontrado."}
        
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




@app.post("/api/admin/reset-data")
async def api_reset_data(
    request: Request, 
    reset_routes: bool = Form(False),
    reset_xp: bool = Form(False),
    reset_all: bool = Form(False),
    session: Session = Depends(get_session)
):
    try:
        user = require_login(request)
        # Extra security: Ensure only admin
        if user != ALLOWED_USER:
             return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=403)

        import shutil
        import time
        
        # 1. Create Backup
        if reset_routes or reset_xp or reset_all:
             timestamp = time.strftime("%Y%m%d_%H%M%S")
             try:
                 shutil.copy("database.db", f"database.db.reset_backup_{timestamp}")
                 print(f"✅ Backup created: database.db.reset_backup_{timestamp}")
             except Exception as e:
                 print(f"⚠️ Backup failed: {e}")
        
        count_deleted = 0
        
        # 2. Reset Logic
        if reset_all:
            # Nuclear Option: Clear everything operational
            tables = [
                models.Route, models.DailyOperation, models.Event, 
                models.EmployeeRoutine, models.EmployeeAllocation, 
                models.XPLedger, models.GameXPTransaction, 
                models.EmployeeAchievement
            ]
            for table in tables:
                session.exec(delete(table))
            
            # Reset Employee XP
            session.exec(text("UPDATE employee SET total_xp = 0"))
            
            # Reset Shift Data? Usually yes for factory reset
            session.exec(delete(models.Shift))
            
            print("☢️ FACTORY RESET COMPLETED")
            
        else:
            # Granular
            if reset_routes:
                # Clear client history / routes
                session.exec(delete(models.Route))
                session.exec(delete(models.DailyOperation)) # Ops log usually tied to routes
                print("🧹 Routes & DailyOps cleared")
                
            if reset_xp:
                # Clear Gamification
                session.exec(delete(models.XPLedger))
                session.exec(delete(models.GameXPTransaction))
                session.exec(delete(models.EmployeeAchievement))
                # Reset field
                employees = session.exec(select(models.Employee)).all()
                for e in employees:
                    e.total_xp = 0
                    session.add(e)
                print("🎮 XP History cleared")

        session.commit()
        return {"success": True, "message": "Dados resetados com sucesso."}

    except Exception as e:
        logger.error(f"Reset Failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

# --- Auth Dependencies ---
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# Moved get_current_user and require_login to top of file to fix NameError dependencies

def get_dashboard_data(session: Session, shift_filter: str):
    """
    Fetches data for the Command Center Dashboard (Nexus).
    """
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Sao_Paulo")
    today = datetime.now(tz)
    today_str = today.strftime("%Y-%m-%d")
    
    # --- 1. Operations Pulse (KPIs) ---
    
    # Query today's routes
    query = select(models.Route).where(models.Route.date == today_str)
    if shift_filter != "Todos":
        query = query.where(models.Route.shift == shift_filter)
    
    todays_routes = session.exec(query).all()
    
    total_tonnage = sum(r.tonnage for r in todays_routes if r.tonnage)
    total_routes_count = len(todays_routes)
    
    # Calculate Kg/h (Instant or Average)
    # Simple approach: Total Tonnage / Hours elapsed today (or shift duration)
    # Refined: Active Tonnage / Active Time
    # Let's use a simple heuristic for now: Avg of completed routes performance
    kgh_values = []
    
    # Refactor: Group Active Routes by Employee
    active_employees = {} # eid -> {name, photo, routes: []}
    
    for r in todays_routes:
        # Check if active (started but not ended)
        if r.start_time and not r.end_time:
             # Calculate active duration
             try:
                 # Use robust aware datetime
                 now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
                 
                 # Parse start_time (assuming naive HH:MM is UTC-3 or UTC)
                 # If stored as UTC naive (08:50 for 05:50), and we act as Sao Paulo:
                 fmt = "%H:%M:%S" if len(r.start_time.split(":")) == 3 else "%H:%M"
                 start_dt = datetime.strptime(r.start_time, fmt).replace(
                     year=now_br.year, month=now_br.month, day=now_br.day,
                     tzinfo=ZoneInfo("America/Sao_Paulo")
                 )
                 
                 # Heuristic Check
                 # If start_dt is 0-4 hours AHEAD of now, it's likely a UTC->Local mismatch (e.g. 09:00 vs 06:00)
                 diff_sec = (start_dt - now_br).total_seconds()
                 
                 display_time = r.start_time # Default to raw
                 
                 if diff_sec > 0 and diff_sec < 4 * 3600:
                     # Correct it: Subtract 3 hours
                     start_dt = start_dt - timedelta(hours=3)
                     display_time = start_dt.strftime("%H:%M")
                 elif diff_sec > 12 * 3600:
                     # Started yesterday? (e.g. 23:00 vs 01:00)
                     start_dt = start_dt - timedelta(days=1)
                     # display_time remains same HH:MM usually, but context matters.
                 
                 duration_mins = int((now_br - start_dt).total_seconds() / 60)
                 if duration_mins < 0: duration_mins = 0
                 
                 # ... fetch client/emp ...
                 client_name = "Cliente"
                 if r.client_id:
                     client = session.get(models.Client, r.client_id)
                     client_name = client.name if client else "Desconhecido"
                 
                 emp = session.get(models.Employee, r.employee_id)
                 emp_name = emp.name if emp else "..."
                 emp_photo = emp.photo_url if emp else None
                 
                 eid = r.employee_id
                 if eid not in active_employees:
                     active_employees[eid] = {
                         "employee_name": emp_name.split()[0], # First name
                         "employee_full_name": emp_name,
                         "photo_url": emp_photo,
                         "routes": []
                     }
                 
                 active_employees[eid]['routes'].append({
                     "client": client_name,
                     "duration_mins": duration_mins,
                     "start_time": display_time, # <--- FIXED
                     "tonnage": r.tonnage or 0.0,
                     "tonnage_fmt": f"{r.tonnage:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".") if r.tonnage else "0,000"
                 })
                 
             except Exception as e:
                 print(f"Error parsing active route: {e}")
        
        # Calculate Kg/h for completed
        elif r.start_time and r.end_time and r.tonnage:
             try:
                 s = datetime.strptime(r.start_time, "%H:%M")
                 e = datetime.strptime(r.end_time, "%H:%M")
                 seconds = (e - s).total_seconds()
                 if seconds > 0:
                     kgh = (r.tonnage / seconds) * 3600
                     kgh_values.append(kgh)
             except: pass

    avg_kgh = sum(kgh_values) / len(kgh_values) if kgh_values else 0
    
    # --- 2. Headcount ---
    # Count active employees in 'EmployeeRoutine' for today
    base_hc_query = select(models.EmployeeRoutine).where(
        models.EmployeeRoutine.date == today_str,
        models.EmployeeRoutine.routine == 'present'
    )
    if shift_filter != "Todos":
        base_hc_query = base_hc_query.where(models.EmployeeRoutine.shift == shift_filter)
    
    present_count = len(session.exec(base_hc_query).all())
    
    # Get Target (Meta)
    target_val = 45 # Default
    if shift_filter != "Todos":
        t = session.exec(select(models.HeadcountTarget).where(models.HeadcountTarget.shift_name == shift_filter)).first()
        if t: target_val = t.target_value
    else:
        # Sum all targets
        targets = session.exec(select(models.HeadcountTarget)).all()
        if targets: target_val = sum(t.target_value for t in targets)

    # HR Condensed (Placeholder)
    
    # Flatten for template
    active_routes = list(active_employees.values())

    return {
        "kpi": {
            "tonnage": total_tonnage,
            "routes_count": total_routes_count,
            "avg_kgh": round(avg_kgh, 1),
            "headcount": present_count,
            "target_headcount": target_val
        },
        "live_separation": active_routes,
        "active_separators_count": len(active_routes)
    }


# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, shift: str = "Todos", session: Session = Depends(get_session)):
    user = require_login(request)
    # Redirect mobile users
    if isinstance(user, dict) and user.get("type") == "employee":
        return RedirectResponse(url="/mobile/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    # 1. Fetch Dashboard Data (KPIs + Live Separation)
    data = get_dashboard_data(session, shift)
    
    # 2. Add HR Data (Compact) for Carousel
    # Fetching simplified lists for the template
    today = datetime.now(ZoneInfo("America/Sao_Paulo"))
    employees = session.exec(select(models.Employee).where(models.Employee.status != 'fired')).all()
    
    # Birthdays (Month)
    birthdays = []
    for emp in employees:
        if emp.birthday and emp.birthday.month == today.month:
            birthdays.append(emp)
    
    # Vacation (Active)
    on_vacation = [e for e in employees if e.status == 'vacation']
    
    # Attach to data object
    data["hr"] = {
        "birthdays": [{"name": e.name.split()[0], "day": e.birthday.day, "photo": e.photo_url} for e in birthdays],
        "vacation": [{"name": e.name.split()[0], "photo": e.photo_url} for e in on_vacation]
    }

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "dashboard": data,
        "current_shift": shift
    })

@app.get("/mobile", response_class=RedirectResponse)
async def mobile_root():
    return RedirectResponse(url="/mobile/login")
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ALLOWED_USER and password == ALLOWED_PASS:
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Credenciais inválidas"})
@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")
# --- Mobile Portal Routes ---

@app.get("/mobile/login", response_class=HTMLResponse)
async def mobile_login(request: Request):
    error = request.query_params.get("error")
    error_msg = None
    if error == "access_revoked":
        error_msg = "Seu acesso foi revogado pelo administrador."
    return templates.TemplateResponse("mobile/login.html", {"request": request, "error": error_msg})

@app.post("/mobile/auth")
async def mobile_auth(
    request: Request,
    registration_id: str = Form(...),
    session: Session = Depends(get_session)
):
    registration_id = registration_id.strip()
    statement = select(models.Employee).where(models.Employee.registration_id == registration_id)
    employee = session.exec(statement).first()
    
    if not employee:
        return templates.TemplateResponse(
            "mobile/login.html", 
            {"request": request, "error": "Matrícula não encontrada."}
        )
    
    if employee.status == "fired":
        return templates.TemplateResponse(
            "mobile/login.html", 
            {"request": request, "error": "Acesso não autorizado."}
        )

    # Check Mobile Access Permission
    if not employee.mobile_access:
        return templates.TemplateResponse(
            "mobile/login.html", 
            {"request": request, "error": "Seu usuário não possui permissão de acesso ao app mobile."}
        )

    # Clear any existing session (e.g. Admin login) to prevent conflicts
    request.session.clear()
    
    request.session["user_id"] = employee.id
    request.session["user_role"] = "employee"
    return RedirectResponse(url="/mobile/dashboard", status_code=303)

@app.get("/mobile/logout")
async def mobile_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/mobile/login", status_code=303)

@app.get("/mobile/dashboard", response_class=HTMLResponse)
async def mobile_dashboard(request: Request, current_user: dict = Depends(get_current_user), session: Session = Depends(get_session)):
    try:
        # Validate User Type (Must be dict from mobile login)
        if not isinstance(current_user, dict):
             # Logged in as Admin/User but trying to access Mobile Dashboard
             # Redirect to mobile login to identify as Employee
             return RedirectResponse(url="/mobile/login", status_code=303)

        # Find Employee linked to User
        # The existing get_current_user returns a dict with 'id' for employee
        user_id = current_user.get("id")
        if not user_id:
            return RedirectResponse(url="/mobile/login", status_code=303)

        employee = session.get(models.Employee, user_id)
        if not employee:
            request.session.clear()
            return RedirectResponse(url="/mobile/login", status_code=303)

        # Enforce Mobile Access (Revocation Check)
        if not employee.mobile_access:
            request.session.clear()
            return RedirectResponse(url="/mobile/login?error=access_revoked", status_code=303)

        today = datetime.now(ZoneInfo("America/Sao_Paulo"))
        yesterday = today - timedelta(days=1)
        if yesterday.weekday() == 6: # If Sunday, check Saturday
             yesterday = today - timedelta(days=2)
             
        thirty_days_ago = today - timedelta(days=30)
        
        # Fetch raw routes for the last 30 days (needed for productivity challenge and charts)
        raw_routes = session.exec(
            select(models.Route)
            .where(
                models.Route.employee_id == employee.id,
                models.Route.date >= thirty_days_ago.strftime("%Y-%m-%d"),
                models.Route.status == "completed"
            )
        ).all()
        
        # --- Yesterday's Performance (gamification) ---
        stmt = select(func.sum(models.Route.tonnage)).where(
            models.Route.employee_id == employee.id,
            models.Route.date == yesterday.strftime("%Y-%m-%d")
        )
        yesterday_kg = session.exec(stmt).one() or 0.0

        # --- Productivity Challenge (NEW) ---
        # Fetch yesterday's stats
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        y_routes = [r for r in raw_routes if r.date == yesterday_str]
        y_kg = sum([r.tonnage for r in y_routes if r.tonnage]) or 0.0
        
        y_seconds = 0
        for r in y_routes:
            if r.start_time and r.end_time:
                try:
                    s = datetime.strptime(r.start_time, "%H:%M")
                    e = datetime.strptime(r.end_time, "%H:%M")
                    y_seconds += (e - s).total_seconds()
                except: pass
        
        y_hours = y_seconds / 3600.0 if y_seconds > 0 else 0
        y_kgh = y_kg / y_hours if y_hours > 0 else 0
        
        # Challenge Logic
        ai_message = "Pronto para superar seus limites hoje? Vamos lá!"
        if y_kg > 0 and y_kgh > 0:
            target_kgh = y_kgh * 1.1 # 10% more efficiency
            # "Yesterday you did 1000kg in 1h (1000kg/h). If you do it in 54min (1100kg/h) or more, you gain +100XP"
            # We'll simplify the message for the user's specific request
            target_time_min = int((y_kg / target_kgh) * 60) if target_kgh > 0 else 0
            
            y_time_str = f"{int(y_hours)}h {int((y_hours*60)%60)}min" if y_hours >= 1 else f"{int(y_hours*60)}min"
            
            ai_message = f"Ontem você fez {y_kg:,.0f}kg em {y_time_str}. Se hoje fizer o mesmo peso (ou mais) em menos tempo, ganha +100 XP!"

        # --- Clients for Modal ---
        clients = session.exec(select(models.Client)).all()

        # --- Chart Data (Advanced) ---
        chart_labels = []
        chart_daily_kg = []
        chart_daily_kgh = []
        chart_cumulative_kg = []
        chart_bg_colors = []
        
        running_total = 0
        
        # Pre-fetch data to analyze rankings
        daily_stats = []
        
        # Aggregate in Python
        daily_map = {}
        for r in raw_routes:
            if not r.start_time or not r.end_time: continue
            
            try:
                # Calculate Duration
                s = datetime.strptime(r.start_time, "%H:%M")
                e = datetime.strptime(r.end_time, "%H:%M")
                diff_seconds = (e - s).total_seconds()
                
                # Update Map
                current_kg, current_seconds = daily_map.get(r.date, (0, 0))
                daily_map[r.date] = (current_kg + r.tonnage, current_seconds + diff_seconds)
            except Exception as e:
                print(f"Error aggregating route {r.id}: {e}")
                continue
        
        # Generate last 7 days for chart
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            label = d.strftime("%d/%m")
            
            kg, seconds = daily_map.get(d_str, (0, 0))
            
            # Kgh
            hours = seconds / 3600.0 if seconds > 0 else 0
            kgh = kg / hours if hours > 0 else 0
            
            # Cumulative
            running_total += kg
            
            chart_labels.append(label)
            chart_daily_kg.append(float(f"{kg:.1f}"))
            chart_daily_kgh.append(float(f"{kgh:.1f}"))
            chart_cumulative_kg.append(float(f"{running_total:.1f}"))
            
            # Color logic (Green > 1000kg/h)
            if kgh >= 1000:
                chart_bg_colors.append("#10b981") # Emerald 500
            elif kgh >= 700:
                 chart_bg_colors.append("#f59e0b") # Amber 500
            else:
                 chart_bg_colors.append("#ef4444") # Red 500

        # --- Active Routes (Pending) ---
        today_str = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
        
        # 1. Active Routes
        active_routes_stmt = (
            select(models.Route, models.Client.name)
            .join(models.Client, models.Route.client_id == models.Client.id)
            .where(
                models.Route.employee_id == employee.id,
                models.Route.date == today_str,
                models.Route.status == "pending"
            )
        )
        active_routes_result = session.exec(active_routes_stmt).all()
        
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))

        active_routes_list = []
        for r, c_name in active_routes_result:
            s_time = r.start_time
            # Heuristic Timezone Fix
            if s_time:
                try:
                    # Support HH:MM and HH:MM:SS
                    fmt = "%H:%M:%S" if len(s_time.split(":")) == 3 else "%H:%M"
                    s_dt = datetime.strptime(s_time, fmt).replace(
                        year=now_br.year, month=now_br.month, day=now_br.day, 
                        tzinfo=ZoneInfo("America/Sao_Paulo")
                    )
                    
                    diff = (s_dt - now_br).total_seconds()
                    if diff > 0 and diff < 4 * 3600:
                        s_time = (s_dt - timedelta(hours=3)).strftime("%H:%M")
                except Exception as e:
                    pass

            active_routes_list.append({
                "id": r.id,
                "client_name": c_name,
                "tonnage": r.tonnage,
                "start_time": s_time
            })

        # 2. Completed Routes (History Today)
        completed_routes_stmt = (
            select(models.Route, models.Client.name)
            .join(models.Client, models.Route.client_id == models.Client.id) 
            .where(
                models.Route.employee_id == employee.id,
                models.Route.date == today_str,
                models.Route.status == "completed"
            )
            .order_by(models.Route.end_time.desc())
        )
        completed_routes_result = session.exec(completed_routes_stmt).all()
        
        completed_routes_list = []
        for r, c_name in completed_routes_result:
            # Calculate duration/productivity for display
            duration_str = "00:00"
            perf_str = "0,00 Kg/h"
            
            s_time_fixed = r.start_time
            e_time_fixed = r.end_time
            
            # Fix Start Time
            if s_time_fixed:
                try:
                    fmt = "%H:%M:%S" if len(s_time_fixed.split(":")) == 3 else "%H:%M"
                    s_dt = datetime.strptime(s_time_fixed, fmt).replace(
                        year=now_br.year, month=now_br.month, day=now_br.day, 
                        tzinfo=ZoneInfo("America/Sao_Paulo")
                    )
                    if (s_dt - now_br).total_seconds() > 0 and (s_dt - now_br).total_seconds() < 4 * 3600:
                         s_time_fixed = (s_dt - timedelta(hours=3)).strftime("%H:%M")
                except: pass

            # Fix End Time
            if e_time_fixed:
                try:
                    fmt = "%H:%M:%S" if len(e_time_fixed.split(":")) == 3 else "%H:%M"
                    e_dt = datetime.strptime(e_time_fixed, fmt).replace(
                        year=now_br.year, month=now_br.month, day=now_br.day, 
                        tzinfo=ZoneInfo("America/Sao_Paulo")
                    )
                    if (e_dt - now_br).total_seconds() > 0 and (e_dt - now_br).total_seconds() < 4 * 3600:
                         e_time_fixed = (e_dt - timedelta(hours=3)).strftime("%H:%M")
                except: pass

            if r.start_time and r.end_time: # Calc duration using ORIGINAL logic but fixed might be better visually?
                # Actually for calculation we should use the corrected times OR just raw delta if they are consistent
                # Let's keep existing calc logic but use FIXED for display
                try:
                    s = datetime.strptime(r.start_time, "%H:%M")
                    e = datetime.strptime(r.end_time, "%H:%M")
                    diff_sec = (e - s).total_seconds()
                    
                    # Duration
                    h_dur = int(diff_sec // 3600)
                    m_dur = int((diff_sec % 3600) // 60)
                    duration_str = f"{h_dur:02d}h {m_dur:02d}m"
                    
                    # Metric: Kg/h
                    t = r.tonnage if r.tonnage else 0
                    hours_decimal = diff_sec / 3600.0
                    if hours_decimal <= 0: hours_decimal = 0.016 # 1 min
                    
                    kgh = t / hours_decimal
                    perf_str = f"{kgh:,.2f} Kg/h".replace(",", "X").replace(".", ",").replace("X", ".")
                except Exception as ex:
                    print(f"Error calc history: {ex}")
                    pass

            completed_routes_list.append({
                "id": r.id,
                "client_name": c_name,
                "tonnage": r.tonnage,
                "start_time": s_time_fixed,
                "end_time": e_time_fixed,
                "duration": duration_str,
                "performance": perf_str
            })

        # --- Gamification Logic (XP = Total Tonnage) ---
# --- Gamification V2 Engine ---
        from gamification_engine import get_employee_progress
        
        # Calculate Progress (Respecting Time Caps & DB Levels)
        progress_data = get_employee_progress(session, employee.id)
        
        if progress_data:
            current_level = progress_data["level"]
            next_level = progress_data["next_level"]
            progress_percent = progress_data["progress"]
        else:
            # Fallback if critical failure
            current_level = {"name": "N/A", "level": 0, "badge_image": "badge_1.png"}
            next_level = None
            progress_percent = 0

        # Process XP History
        # Fetch Revoked Achievement Names for Filtering
        revoked_names = session.exec(
            select(models.GameAchievement.name)
            .join(models.EmployeeAchievement, models.GameAchievement.id == models.EmployeeAchievement.achievement_id)
            .where(
                models.EmployeeAchievement.employee_id == employee.id,
                models.EmployeeAchievement.status == "revoked"
            )
        ).all()

        raw_history = session.exec(select(GameXPTransaction)
            .where(GameXPTransaction.employee_id == employee.id)
            .where(GameXPTransaction.status == "confirmed")
            .order_by(desc(GameXPTransaction.created_at))
            .limit(50) # Fetch more to allow for filtering
        ).all()

        xp_history_list = []
        for tx in raw_history:
            # FILTER 1: Hide Revocation Transactions
            if tx.source_type == "achievement_revoke":
                continue
            
            # FILTER 2: Hide Grant Transactions for Revoked Achievements
            if tx.source_type == "achievement_grant":
                is_revoked_grant = False
                for r_name in revoked_names:
                    # Reason format: "Conquista Desbloqueada: Imune a Tudo ..."
                    # Check if revoked name is present in the reason
                    if r_name in tx.reason:
                        is_revoked_grant = True
                        break
                if is_revoked_grant:
                    continue

            # Limit to 20 items for display AFTER filtering
            if len(xp_history_list) >= 20:
                break

            title = tx.reason
            details = ""
            category = "other"  # produção, evento, bônus, manual, other
            icon = "star"
            
            # Format "Produtividade" entries
            if "Produtividade" in tx.reason and "|" in tx.reason:
                try:
                    parts = tx.reason.split("|")
                    # parts[0] = "Produtividade 2026-01-08 (ref...)"
                    date_part = parts[0].split(" ")[1] # 2026-01-08
                    pt_date = date_part.split("-")
                    formatted_date = f"{pt_date[2]}/{pt_date[1]}" # 08/01
                    
                    kg_val = parts[1].strip()
                    uo_val = parts[2].strip()
                    
                    title = f"Produção {formatted_date}"
                    details = f"{kg_val} • {uo_val}"
                    category = "producao"
                    icon = "truck"
                    
                    # Extrair breakdown [Base: X | Eficiência: +Y | Evento: +Z] = Total XP
                    for p in parts:
                        if p.strip().startswith("[") and "]" in p:
                            # Parse breakdown: [Base: 123 | Eficiência: +12 | Evento (1.5x): +61]
                            breakdown = p.strip()[1:p.strip().index("]")]  # Remove [ e ]
                            details = breakdown.replace(" | ", "\n")  # Cada item em nova linha
                            break
                    
                    # Verificar if tem evento ou bônus horário nas partes extras
                    for p in parts:
                        if "Event:" in p:
                            title += f" 🎉"
                        if "Early" in p:
                            title += f" ⏰"
                except:
                    pass # Fallback to raw reason
            elif "Ajuste manual" in tx.reason:
                category = "manual"
                icon = "edit"
                title = "Ajuste Manual"
                details = tx.reason.replace("Ajuste manual:", "").strip() if ":" in tx.reason else ""
            elif tx.amount < 0:
                category = "penalty"
                icon = "alert-circle"
            
            xp_history_list.append({
                "amount": tx.amount,
                "reason": title,
                "details": details,  # New field
                "type": tx.source_type,
                "category": category,
                "icon": icon
            })

        # Serialize Clients using JSON (Prevent JS Syntax Errors)
        clients_list = [{"id": c.id, "name": c.name} for c in clients]
        
        # --- Calculate Streak (consecutive work days) ---
        streak_days = 0
        try:
            # Get last 30 days of work
            work_dates = set()
            for r in raw_routes:
                if r.date:
                    work_dates.add(r.date)
            
            # Count consecutive days backwards from today
            check_date = now.date()
            while True:
                # Skip weekends
                if check_date.weekday() >= 5:  # Saturday or Sunday
                    check_date -= timedelta(days=1)
                    continue
                
                date_str = check_date.strftime("%Y-%m-%d")
                if date_str in work_dates or check_date == now.date():
                    if date_str in work_dates:
                        streak_days += 1
                    check_date -= timedelta(days=1)
                else:
                    break
                
                if streak_days > 30:  # Safety limit
                    break
        except Exception as e:
            print(f"Error calculating streak: {e}")
            streak_days = 0

        # --- Special Events (NEW) ---
        upcoming_events = []
        try:
            config_events = session.get(models.GameConfiguration, "xp_special_events")
            if config_events:
                all_events = json.loads(config_events.value)
                # Filter active and future (next 7 days)
                for ev in all_events:
                    if not ev.get('date'): continue
                    ev_date = datetime.strptime(ev['date'], "%Y-%m-%d").date()
                    if ev_date >= today.date() and ev_date <= (today + timedelta(days=7)).date():
                        upcoming_events.append(ev)
        except Exception as e:
            print(f"Error fetching special events: {e}")
        
        # --- Time Bonuses (Bônus por Horário) ---
        time_bonuses = []
        try:
            config_time = session.get(models.GameConfiguration, "xp_time_rules")
            if config_time:
                all_bonuses = json.loads(config_time.value)
                # Filter only active bonuses
                for bonus in all_bonuses:
                    if bonus.get('active', True):  # Default to active if not specified
                        time_bonuses.append(bonus)
        except Exception as e:
            print(f"Error fetching time bonuses: {e}")

        # --- Calculate Daily Goal & Progress (Legacy replaced by Productivity in AI Message) ---
        # We'll keep daily_goal for the UI if needed, but the focus is events
        daily_goal = 500.0
        daily_current_kg = 0.0
        try:
            # Sum of today's completed tonnage
            daily_current_kg = sum([r.tonnage for r in raw_routes if r.date == today_str and r.tonnage]) or 0.0
            
            # Use yesterday's KG as goal for the visual bar if available
            if y_kg > 0:
                daily_goal = y_kg
            else:
                daily_goal = 500.0
        except Exception as e:
            print(f"Error calculating daily goal: {e}")
        
        # Achievements Count
        ach_count_total = session.exec(select(func.count(models.GameAchievement.id))).one()
        ach_count_unlocked = session.exec(select(func.count(models.EmployeeAchievement.id))
                                            .where(models.EmployeeAchievement.employee_id == employee.id, models.EmployeeAchievement.status == "approved")).one()

        context = {
            "request": request,
            "employee": employee,
            "clients_json": json.dumps(clients_list), # SAFE JSON
            "active_routes": json.dumps(active_routes_list), # JSON for Alpine
            "completed_routes": json.dumps(completed_routes_list), # JSON for Alpine History
            "current_date": datetime.now().strftime("%d/%m/%Y"),
            "ai_message": ai_message,
            # Gamification Data
            "gamification": {
                "level": current_level,
                "next_level": next_level,
                "total_xp": int(employee.total_xp), # Use confirmed XP from DB
                "progress_percent": progress_percent,
                "time_in_company": progress_data["months_tenure"] if progress_data else 0,
                "achievements_total": ach_count_total,
                "achievements_unlocked": ach_count_unlocked
            },
            # New: Streak & Daily Goal
            "streak_days": streak_days,
            "daily_goal": daily_goal,
            "daily_current_kg": daily_current_kg,
            # XP Extract Data
            "daily_xp_gain": int(session.exec(select(func.sum(GameXPTransaction.amount))
                .where(GameXPTransaction.employee_id == employee.id)
                .where(func.date(GameXPTransaction.created_at) == datetime.now().date())
                .where(GameXPTransaction.status == "confirmed")
            ).one() or 0),
            
            "xp_history": xp_history_list,
            "chart_labels": json.dumps(chart_labels),
            "chart_daily_kg": json.dumps(chart_daily_kg),
            "chart_daily_kgh": json.dumps(chart_daily_kgh),
            "chart_cumulative_kg": json.dumps(chart_cumulative_kg),
            "chart_bg_colors": json.dumps(chart_bg_colors),
            "upcoming_events": upcoming_events,
            "time_bonuses": time_bonuses
        }
        return templates.TemplateResponse("mobile/dashboard.html", context)

    except Exception as e:
        import traceback
        error_msg = f"Error in mobile_dashboard: {str(e)}\n{traceback.format_exc()}"
        print(error_msg) # Log to console
        return JSONResponse(status_code=500, content={"error": "Internal Server Error", "details": str(e), "trace": traceback.format_exc()})

# --- Conquistas Route ---
@app.get("/mobile/achievements", response_class=HTMLResponse)
async def mobile_achievements(request: Request, current_user: dict = Depends(get_current_user), session: Session = Depends(get_session)):
    try:
        user_id = current_user.get("id")
        if not user_id: return RedirectResponse(url="/mobile/login", status_code=303)
        employee = session.get(models.Employee, user_id)
        if not employee: return RedirectResponse(url="/mobile/login", status_code=303)

        # Gamification Data
        from gamification_engine import get_employee_progress
        progress_data = get_employee_progress(session, employee.id)
        
        # Achievements Data
        all_achievements = session.exec(select(models.GameAchievement).order_by(models.GameAchievement.xp_reward)).all()
        my_achievements = session.exec(select(models.EmployeeAchievement)
            .where(models.EmployeeAchievement.employee_id == employee.id)
            .where(models.EmployeeAchievement.status == "approved")
        ).all()
        
        my_unlocked_ids = {a.achievement_id: a.earned_at for a in my_achievements}
        
        achievements_list = []
        unlocked_count = 0
        total_bonus_xp = 0
        
        for ach in all_achievements:
            is_unlocked = ach.id in my_unlocked_ids
            if is_unlocked:
                unlocked_count += 1
                total_bonus_xp += ach.xp_reward
                
            achievements_list.append({
                "name": ach.name,
                "description": ach.description,
                "xp_reward": ach.xp_reward,
                "icon": ach.icon,
                "unlocked": is_unlocked,
                "earned_at": my_unlocked_ids.get(ach.id)
            })
            
        # Full XP History (Limit 100)
        xp_history_full = session.exec(select(models.GameXPTransaction)
            .where(models.GameXPTransaction.employee_id == employee.id)
            .where(models.GameXPTransaction.status == "confirmed")
            .order_by(desc(models.GameXPTransaction.created_at))
            .limit(100)
        ).all()

        return templates.TemplateResponse("mobile/achievements.html", {
            "request": request,
            "employee": employee,
            "gamification": {
                "level": progress_data["level"],
                "next_level": progress_data["next_level"],
                "total_xp": int(employee.total_xp),
                "progress_percent": progress_data["progress"]
            },
            "achievements": achievements_list,
            "unlocked_count": unlocked_count,
            "total_achievements": len(all_achievements),
            "total_bonus_xp": total_bonus_xp,
            "xp_history_full": xp_history_full
        })
    except Exception as e:
        print(traceback.format_exc())
        return RedirectResponse(url="/mobile/dashboard", status_code=303)

# --- Gamification V2 API & Admin ---
from gamification_engine import calculate_daily_xp, confirm_pending_xp
from models import GameLevel, GameXPTransaction, GameAchievement
from sqlmodel import desc

@app.post("/api/game/calc-daily/{date_str}")
async def api_calc_xp(date_str: str, session: Session = Depends(get_session)):
    """Trigger Daily XP Calculation Manually"""
    count = calculate_daily_xp(session, date_str)
    return {"success": True, "created_transactions": count}

@app.post("/api/game/confirm-xp")
async def api_confirm_xp(session: Session = Depends(get_session)):
    """Trigger Confirmation of Pending XP"""
    count = confirm_pending_xp(session)
    return {"success": True, "confirmed_transactions": count}

@app.post("/api/game/recalculate-all/{date_str}")
async def api_recalculate_all(date_str: str, session: Session = Depends(get_session)):
    """Force recalculation of XP for ALL employees on a specific date"""
    try:
        from gamification_engine import calculate_daily_xp
        count = calculate_daily_xp(session, date_str)
        return {"success": True, "processed": count}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/api/game/achievements/check-all")
def check_all_achievements(
    session: Session = Depends(get_session),
    current_user: models.Employee = Depends(require_gm)
):
    try:
        from gamification_engine import check_and_award_achievements
        employees = session.exec(select(models.Employee).where(models.Employee.status == "active")).all()
        count = 0
        for emp in employees:
            check_and_award_achievements(session, emp.id)
            count += 1
        return {"success": True, "message": f"Verificação concluída para {count} colaboradores."}
    except Exception as e:
        print(f"Error checking achievements: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/game/achievements/audit-all")
def audit_all_achievements(
    session: Session = Depends(get_session),
    current_user: models.Employee = Depends(require_gm)
):
    try:
        from gamification_engine import audit_and_revoke_achievements
        employees = session.exec(select(models.Employee).where(models.Employee.status == "active")).all()
        total_revoked = 0
        for emp in employees:
            revoked = audit_and_revoke_achievements(session, emp.id)
            total_revoked += revoked
        return {"success": True, "message": f"Auditoria concluída. {total_revoked} conquistas revogadas."}
    except Exception as e:
        print(f"Error auditing achievements: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/game/audit")
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




@app.get("/api/game/audit/routes")
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
    """Detalhamento por rota (rotina) com XP estimado por rota, para auditoria/explicação."""
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

@app.get("/api/game/export/xp")
async def api_game_export_xp(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None,
    employee_id: Optional[int] = None,
    session: Session = Depends(get_session)
):
    """Exporta histórico de XP para CSV (Streaming)."""
    require_login(request)
    
    # Reutiliza lógica de filtro (query base)
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

@app.get("/api/game/audit/summary")
async def api_game_audit_summary(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = "confirmed",
    session: Session = Depends(get_session)
):
    """Retorna sumário agregado de XP por colaborador no período."""
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


@app.post("/api/game/manual-xp")
async def api_manual_xp(payload: ManualXPRequest, request: Request, session: Session = Depends(get_session)):
    """Cria uma transação manual de XP (bonificação/penalidade)."""
    require_login(request)

    emp = session.get(models.Employee, payload.employee_id)
    if not emp:
        return JSONResponse({"success": False, "error": "Colaborador não encontrado."}, status_code=404)

    # Validação básica
    if not payload.reason or not payload.reason.strip():
        return JSONResponse({"success": False, "error": "Informe um motivo (reason)."}, status_code=400)

    try:
        amount = int(payload.amount)
    except Exception:
        return JSONResponse({"success": False, "error": "amount inválido."}, status_code=400)

    if amount == 0:
        return JSONResponse({"success": False, "error": "amount não pode ser 0."}, status_code=400)

    status_val = (payload.status or "confirmed").strip().lower()
    if status_val not in ("confirmed", "provisional"):
        return JSONResponse({"success": False, "error": "status inválido (use confirmed ou provisional)."}, status_code=400)

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
async def admin_game_dashboard(request: Request, session: Session = Depends(get_session)):
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
async def admin_game_audit(request: Request, session: Session = Depends(get_session)):
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
    session: Session = Depends(get_session)
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

@app.get("/api/game/audit/employee/{employee_id}")
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
        return {"error": "Employee not found"}

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

@app.post("/api/game/levels")
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

@app.post("/api/game/achievements")
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

@app.post("/api/game/transaction/{tx_id}/{action}")
async def api_manage_tx(tx_id: int, action: str, session: Session = Depends(get_session)):
    """Approve/Reject Provisional Transaction"""
    tx = session.get(GameXPTransaction, tx_id)
    if not tx: return {"error": "Transaction not found"}
    
    
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
        require_login(request) # Admin Only
        
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

@app.post("/api/game/settings")
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
             return JSONResponse({"error": "Unauthorized"}, status_code=401)
             
        route = session.get(models.Route, route_id)
        if not route:
             return JSONResponse({"error": "Rota não encontrada"}, status_code=404)
             
        if route.employee_id != user_id:
             return JSONResponse({"error": "Não autorizado"}, status_code=403)
             
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
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
        
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
            shift="Manhã", # Placeholder
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
         # return JSONResponse({"error": "Rotina já encerrada hoje."}, status_code=400) # Removed limitation
         
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
@app.get("/mobile/login", response_class=HTMLResponse)
async def mobile_login_page(request: Request):
    return templates.TemplateResponse("mobile/login.html", {"request": request})

@app.post("/mobile/auth", response_class=RedirectResponse)
async def mobile_auth(request: Request, registration_id: str = Form(...), session: Session = Depends(get_session)):
    # Simple Auth: Check if ID exists and is active
    statement = select(models.Employee).where(models.Employee.registration_id == registration_id)
    employee = session.exec(statement).first()
    
    if not employee or employee.status == "fired":
         return RedirectResponse(url="/mobile/login?error=Matrícula inválida ou inativa", status_code=status.HTTP_303_SEE_OTHER)
         
    # Set Session
    request.session["user_id"] = employee.id
    request.session["user_role"] = "employee"
    
    return RedirectResponse(url="/mobile/dashboard", status_code=303)

@app.get("/mobile/logout")
async def mobile_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/mobile/login", status_code=303)

@app.post("/mobile/routine/start", response_class=RedirectResponse)
async def mobile_routine_start(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
        
    user_id = user.get("id")
    
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
        current_shift = "Manhã" 
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
    # User: "Quando eu clicar encerrar o dia no botão deve se finalizar e encerrar tambem na pagina /separacao"
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
                description=f"Quebrou recorde diário: {today_prod}kg",
                severity="info"
            )
             session.add(event)
             
        session.commit()
        
        # Logout after stopping routine? Or just stay on dashboard locked?
        # User requested: "encerrar operação e travar"
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
        routine.reopened_by = str(user)
        routine.reopened_reason = reason
        routine.reopened_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
        
        session.add(routine)
        
        # Log Event
        session.add(models.Event(
            date=datetime.now().strftime("%Y-%m-%d"),
            employee_id=routine.employee_id,
            event_type="info",
            description=f"Rotina reaberta por {user}: {reason}",
            severity="warning"
        ))
        session.commit()
    
    # Redirect back to Employee Detail
    return RedirectResponse(url=f"/employees/{routine.employee_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/mobile/api/ai/today")
async def mobile_ai_today(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
         return JSONResponse({"error": "Unauthorized"}, status_code=401)
         
    user_id = user.get("id")
    today = datetime.now().date()
    
    # 1. Calculate Average Productivity (Last 10 Days)
    # Placeholder logic
    avg_prod = 1500.0 # kg/h
    target = round(avg_prod * 1.05, 0)
    
    return {
        "avg_prod": avg_prod,
        "target_prod": target,
        "message": f"Ontem você fez X. Hoje sua meta é {target}kg/h."
    }


# --- Client Routes ---
@app.post("/clients/add", response_class=RedirectResponse)
async def add_client(
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session)
):
    require_login(request)
    try:
        # Check if exists
        existing = session.exec(select(models.Client).where(models.Client.name == name)).first()
        if not existing:
            new_client = models.Client(name=name)
            session.add(new_client)
            session.commit()
    except Exception as e:
        print(f"Error adding client: {e}")
        # Redirect back to Clients page
    return RedirectResponse(url="/clients", status_code=status.HTTP_303_SEE_OTHER)
@app.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    clients = session.exec(select(models.Client)).all()
    return templates.TemplateResponse("clients.html", {"request": request, "user": user, "clients": clients})
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
    
    # Period Stats
    today = datetime.now().date()
    stats_today = 0.0
    stats_week = 0.0
    stats_month = 0.0
    stats_year = 0.0
    
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
    
    return templates.TemplateResponse("client_details.html", {
        "request": request,
        "user": user,
        "client": client,
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
            "year_fmt": fmt(stats_year)
        },
        "history": history
    })

@app.post("/clients/{client_id}/update", response_class=RedirectResponse)
async def update_client(request: Request, client_id: int, name: str = Form(...), session: Session = Depends(get_session)):
    require_login(request)
    client = session.get(models.Client, client_id)
    if client:
        client.name = name
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

# --- Route Management ---
# --- Separação de Mercadorias Management ---
@app.get("/separacao", response_class=HTMLResponse)
async def separacao_page(request: Request, date: Optional[str] = None, shift: str = "Manhã", session: Session = Depends(get_session)):
    user = require_login(request)
    
    # Check for Mobile User
    current_emp_id = None
    is_mobile_user = False
    
    if isinstance(user, dict) and user.get("type") == "employee":
        current_emp_id = user.get("id")
        is_mobile_user = True
    
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
        
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

    # 4. Fetch Routes
    query = select(models.Route).where(models.Route.date == date).where(models.Route.shift == shift)
    
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
        "selected_date_fmt": datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y")
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
        daily_stats = {start_date + timedelta(days=i): {'tonnage': 0.0, 'duration_seconds': 0.0} for i in range(31)}
        total_sys_tonnage = 0.0

        emp_stats = {} 
        client_dur_stats = {} 
        emp_day_intervals = {} 
        
        all_emps = {e.id: e.name for e in session.exec(select(models.Employee)).all()}
        
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
                        if r.start_time and r.end_time: 
                            s = datetime.strptime(r.start_time, "%H:%M")
                            e = datetime.strptime(r.end_time, "%H:%M")
                            diff = (e - s).total_seconds()
                            if diff > 0:
                                daily_stats[r_date_obj]['tonnage'] += t
                                daily_stats[r_date_obj]['duration_seconds'] += diff
            except:
                pass
            
            # Individual Stats (Selected Date)
            if r.date == date:
                if shift and shift != "Todos" and r.shift != shift:
                     continue
                     
                if r.employee_id and r.start_time and r.end_time:
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

        return {
            "abc_data": abc_data,
            "prod_chart_labels": prod_chart_labels,
            "prod_chart_data": prod_chart_data,
            "total_tonnage": total_sys_tonnage,
            "kpi": {
                "global_kgh": f"{avg_sys_kgh:,.1f}".replace(".", ","),
                "avg_idle": f"{avg_sys_idle:,.1f}h".replace(".", ","),
                "total_vol": f"{total_sys_tonnage:,.0f}".replace(",", ".")
            },
            "productivity": productivity,
            "sla_ranking": sla_ranking,
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

@app.get("/rankings", response_class=HTMLResponse)
async def rankings_page(request: Request, shift: Optional[str] = None, date: Optional[str] = None, period: str = "daily", sort_by: str = "tonnage", order: str = "desc", session: Session = Depends(get_session)):
    import traceback
    try:
        user = require_login(request)
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        target_date = datetime.strptime(date, "%Y-%m-%d")
        start_date_str = date
        end_date_str = date
        
        if period == "weekly":
            start_date_obj = target_date - timedelta(days=6)
            start_date_str = start_date_obj.strftime("%Y-%m-%d")
        elif period == "monthly":
            start_date_obj = target_date - timedelta(days=29)
            start_date_str = start_date_obj.strftime("%Y-%m-%d")
            
        # --- Leaderboards (Selected Period) ---
        query = select(models.Route).where(models.Route.tonnage > 0)
        
        # Date Filter
        query = query.where(models.Route.date >= start_date_str)
        query = query.where(models.Route.date <= end_date_str)
        
        if shift and shift != 'Geral':
            query = query.where(models.Route.shift == shift)
            
        routes_period = session.exec(query).all()
        
        emp_stats = {} # id -> {original_obj, tonnage, duration_secs, count, max_tonnage, max_kgh}
        
        emp_map = {e.id: e for e in session.exec(select(models.Employee)).all()}
        
        for r in routes_period:
            eid = r.employee_id
            if eid not in emp_stats:
                emp_stats[eid] = {'emp': emp_map.get(eid), 'tonnage': 0, 'secs': 0, 'count': 0, 'max_tonnage': 0, 'max_kgh': 0}
                
            stats = emp_stats[eid]
            t = r.tonnage or 0.0
            stats['tonnage'] += t
            stats['count'] += 1
            if t > stats['max_tonnage']:
                stats['max_tonnage'] = t
                
            # Duration
            try:
                if r.start_time and r.end_time:
                    s = datetime.strptime(r.start_time, "%H:%M")
                    e = datetime.strptime(r.end_time, "%H:%M")
                    diff = (e-s).total_seconds()
                    if diff > 0:
                        stats['secs'] += diff
                        # Max Kgh only counts single route peak
                        current_kgh = (t / (diff/3600))
                        if current_kgh > stats['max_kgh']:
                            stats['max_kgh'] = current_kgh
            except:
                pass
                
        # Listify
        ranking_list = []
        for eid, s in emp_stats.items():
            if not s['emp']: continue
            
            hours = 0
            avg_kgh = 0
            if s['secs'] > 0:
                hours = s['secs'] / 3600
                avg_kgh = s['tonnage'] / hours
                
            ranking_list.append({
                "id": eid,
                "name": s['emp'].name,
                "photo": s['emp'].photo_url,
                "tonnage": s['tonnage'],
                "kgh": avg_kgh,
                "count": s['count'],
                "time_hours": hours,
                "time_fmt": "{:02d}:{:02d}".format(int(hours), int((hours*60)%60)),
                "max_tonnage": s['max_tonnage'],
                "max_kgh": s['max_kgh']
            })
            
        # Sorters (Dynamic)
        reverse_order = True if order == 'desc' else False
        
        if sort_by == 'kgh':
            ranking_list.sort(key=lambda x: x['kgh'], reverse=reverse_order)
        elif sort_by == 'time':
            ranking_list.sort(key=lambda x: x['time_hours'], reverse=reverse_order)
        elif sort_by == 'count':
            ranking_list.sort(key=lambda x: x['count'], reverse=reverse_order)
        else: # tonnage
            ranking_list.sort(key=lambda x: x['tonnage'], reverse=reverse_order)

        # --- Badges Logic ---
        badges = []
        if ranking_list:
            by_kgh = sorted(ranking_list, key=lambda x: x['max_kgh'], reverse=True)
            by_vol = sorted(ranking_list, key=lambda x: x['max_tonnage'], reverse=True)
            by_cnt = sorted(ranking_list, key=lambda x: x['count'], reverse=True)
            
            flash = by_kgh[0] if by_kgh and by_kgh[0]['max_kgh'] > 0 else None
            hulk  = by_vol[0] if by_vol and by_vol[0]['max_tonnage'] > 0 else None
            mara  = by_cnt[0] if by_cnt and by_cnt[0]['count'] >= 5 else None 
            
            if flash:
                badges.append({
                    "image": "/static/badges/flash.png", "title": "The Flash", 
                    "class": "shadow-yellow-500/50 border-yellow-500/50", "desc": "Maior velocidade (única)",
                    "winner": flash['name'].split()[0], "value": f"{int(flash['max_kgh'])} kg/h"
                })
            if hulk:
                badges.append({
                    "image": "/static/badges/hulk.png", "title": "Hulk Esmaga", 
                    "class": "shadow-green-500/50 border-green-500/50", "desc": "Maior carga (única)",
                    "winner": hulk['name'].split()[0], "value": f"{int(hulk['max_tonnage'])} kg"
                })
            if mara:
                badges.append({
                    "image": "/static/badges/marathon.png", "title": "Maratonista", 
                    "class": "shadow-blue-500/50 border-blue-500/50", "desc": "Mais separações",
                    "winner": mara['name'].split()[0], "value": f"{mara['count']} viagens"
                })

        # --- Global Levels (All Employees) ---
        query_levels = select(models.Employee).where(models.Employee.status == 'active')
        if shift and shift not in ['Geral', 'Todos', None]:
            query_levels = query_levels.where(models.Employee.work_shift == shift)
            
        all_emps = session.exec(query_levels.order_by(models.Employee.total_xp.desc()).limit(12)).all()
        
        level_list = []
        for e in all_emps:
            xp = e.total_xp or 0.0
            lvl_name = "Júnior"
            progress = 0
            
            if xp < 5000:
                lvl_name = "Bronze"
                progress = (xp / 5000) * 100
            elif xp < 15000:
                lvl_name = "Prata"
                progress = ((xp - 5000) / 10000) * 100
            elif xp < 50000:
                lvl_name = "Ouro"
                progress = ((xp - 15000) / 35000) * 100
            else:
                lvl_name = "Diamante"
                progress = 100

            level_list.append({
                "name": e.name,
                "level": lvl_name,
                "xp": int(xp),
                "progress": progress
            })

        return templates.TemplateResponse("rankings.html", {
            "request": request,
            "period": period,
            "current_period": period,
            "selected_date": date,
            "current_shift": shift or 'Todos',
            "current_sort": sort_by,
            "current_order": order,
            "badges": badges,
            "ranking_list": ranking_list,
            "levels": level_list
        })

    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(f"<h1>Erro 500</h1><pre>{traceback.format_exc()}</pre>", status_code=500)

@app.get("/api/rankings/employee/{employee_id}/details")
async def get_ranking_details(
    request: Request,
    employee_id: int,
    date: str,
    period: str = "daily",
    shift: Optional[str] = None,
    session: Session = Depends(get_session)
):
    try:
        user = require_login(request)
        target_date = datetime.strptime(date, "%Y-%m-%d")
        start_date_str = date
        end_date_str = date
        
        if period == "weekly":
            start_date_obj = target_date - timedelta(days=6)
            start_date_str = start_date_obj.strftime("%Y-%m-%d")
        elif period == "monthly":
            start_date_obj = target_date - timedelta(days=29)
            start_date_str = start_date_obj.strftime("%Y-%m-%d")
            
        # Stats Query
        query = select(models.Route, models.Client).join(models.Client, models.Route.client_id == models.Client.id)
        query = query.where(models.Route.employee_id == employee_id)
        query = query.where(models.Route.tonnage > 0)
        query = query.where(models.Route.date >= start_date_str)
        query = query.where(models.Route.date <= end_date_str)
        
        if shift and shift not in ['Geral', 'Todos', None, 'null']:
            query = query.where(models.Route.shift == shift)
            
        results = session.exec(query).all() # List of (Route, Client)
        
        routes_data = []
        total_tonnage = 0
        total_secs = 0
        max_kgh = 0
        
        for r, c in results:
            tonnage = r.tonnage or 0
            duration_fmt = "-"
            kgh = 0
            
            # Duration logic
            try:
                if r.start_time and r.end_time:
                    s = datetime.strptime(r.start_time, "%H:%M")
                    e = datetime.strptime(r.end_time, "%H:%M")
                    diff = (e-s).total_seconds()
                    if diff > 0:
                        total_secs += diff
                        duration_fmt = f"{int(diff//3600):02d}:{int((diff%3600)//60):02d}"
                        kgh = tonnage / (diff/3600)
                        if kgh > max_kgh: max_kgh = kgh
            except: pass
            
            total_tonnage += tonnage
            
            routes_data.append({
                "client": c.name,
                "tonnage": int(tonnage),
                "start": r.start_time,
                "end": r.end_time or "-",
                "duration": duration_fmt,
                "kgh": int(kgh),
                "date": datetime.strptime(r.date, "%Y-%m-%d").strftime("%d/%m")
            })
            
        # Summary
        avg_kgh = 0
        hours = total_secs / 3600
        if hours > 0:
            avg_kgh = total_tonnage / hours
            
        employee = session.exec(select(models.Employee).where(models.Employee.id == employee_id)).first()
            
        return {
            "employee": {
                "name": employee.name if employee else "Desconhecido",
                "photo": employee.photo_url if employee else None
            },
            "summary": {
                "total_tonnage": int(total_tonnage),
                "avg_kgh": int(avg_kgh),
                "total_hours": f"{int(hours):02d}:{int((hours*60)%60):02d}",
                "count": len(routes_data)
            },
            "routes": sorted(routes_data, key=lambda x: x['start'] or "", reverse=True)
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"Erro: {str(e)}", status_code=500)
        query = select(models.Employee).where(models.Employee.status == 'active')
        
        # Apply Shift Filter (if specific shift selected)
        # Note: 'Todos' or None means no filter
        if shift and shift not in ['Todos', 'all']:
            query = query.where(models.Employee.work_shift == shift)
            
        employees = session.exec(query).all()
        
        # Also fetch people ON VACATION, filtering by shift if needed
        vac_query = select(models.Employee).where(models.Employee.status == 'vacation')
        if shift and shift not in ['Todos', 'all']:
            vac_query = vac_query.where(models.Employee.work_shift == shift)
            
        vacation_active_employees = session.exec(vac_query).all()
                # Helper to get shift badge color/label
        def get_shift_meta(s):
            s = (s or '').lower()
            if s == 'manhã': return {'label': 'M', 'color': 'blue'}
            if s == 'tarde': return {'label': 'T', 'color': 'orange'}
            if s == 'noite': return {'label': 'N', 'color': 'purple'}
            return {'label': '-', 'color': 'slate'}
        # 1. Birthdays (Current Month)
        birthdays = []
        for emp in employees:
            if emp.birthday:
                b_date = emp.birthday.date()
                if b_date.month == today.month:
                    is_today = (b_date.day == today.day)
                    birthdays.append({
                        "id": emp.id,
                        "name": emp.name,
                        "day": b_date.day,
                        "is_today": is_today,
                        "date": b_date,
                        "shift": get_shift_meta(emp.work_shift)
                    })
        birthdays.sort(key=lambda x: x['day'])
        # 2. Company Anniversaries (Current Month)
        anniversaries = []
        for emp in employees:
            if emp.admission_date:
                a_date = emp.admission_date.date()
                if a_date.month == today.month and a_date.year != today.year:
                    years = today.year - a_date.year
                    is_today = (a_date.day == today.day)
                    anniversaries.append({
                        "id": emp.id,
                        "name": emp.name,
                        "years": years,
                        "day": a_date.day,
                        "is_today": is_today,
                        "shift": get_shift_meta(emp.work_shift)
                    })
        anniversaries.sort(key=lambda x: x['day'])
        # 3. Vacations (Active + Upcoming 20 days)
        # We need to scan ACTIVE employees for UPCOMING vacations, 
        # and VACATION employees for CURRENT status.
        vacation_list = []
                # A) Currently on Vacation
        for emp in vacation_active_employees:
            end_str = "-"
            if emp.vacation_end:
                end_str = emp.vacation_end.strftime('%d/%m')
            vacation_list.append({
                "id": emp.id,
                "name": emp.name,
                "status": "Em Férias",
                "date_info": f"Volta: {end_str}",
                "is_active": True, # Blue/Orange status
                "shift": get_shift_meta(emp.work_shift)
            })
        # B) Upcoming (Next 20 days) - Scan Active Employees
        limit_date = today + timedelta(days=20)
        for emp in employees:
            if emp.vacation_start:
                v_start = emp.vacation_start.date()
                # If starts between tomorrow and limit_date
                if today < v_start <= limit_date:
                    vacation_list.append({
                        "id": emp.id,
                        "name": emp.name,
                        "status": "Vai sair",
                        "date_info": f"Sai: {v_start.strftime('%d/%m')}",
                        "is_active": False, # Future
                        "shift": get_shift_meta(emp.work_shift),
                        "sort_date": v_start
                    })
                # Sort: Current first, then upcoming by date
        # We can use a sort key tuple: (0 for current/1 for future, date)
        # Active vacations don't have a sort_date easily, give them today
        # Fix: Using v_start directly in lambda can be tricky if not captured, but x['sort_date'] works.
        vacation_list.sort(key=lambda x: (1 if x['status'] == 'Vai sair' else 0, x.get('sort_date', today)))
        # 4. Contract Expiry (45 and 90 days)
        contracts = []
        for emp in employees:
            if emp.admission_date:
                adm = emp.admission_date.date()
                
                # 45 Days
                d45 = adm + timedelta(days=45)
                days_to_45 = (d45 - today).days
                
                # 90 Days
                d90 = adm + timedelta(days=90)
                days_to_90 = (d90 - today).days
                
                if 0 <= days_to_45 <= 30:
                    contracts.append({
                        "id": emp.id,
                        "name": emp.name,
                        "type": "45 Dias",
                        "date": d45,
                        "days_left": days_to_45,
                        "is_today": (days_to_45 == 0),
                        "shift": get_shift_meta(emp.work_shift)
                    })
                    
                if 0 <= days_to_90 <= 30:
                    contracts.append({
                        "id": emp.id,
                        "name": emp.name,
                        "type": "90 Dias",
                        "date": d90,
                        "days_left": days_to_90,
                        "is_today": (days_to_90 == 0),
                        "shift": get_shift_meta(emp.work_shift)
                    })
        contracts.sort(key=lambda x: x['days_left'])
        months_pt = {
            1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
            7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
        }
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": "Operação Inteligente - Sistema Iniciado",
            "user": user,
            "current_shift": shift or 'Todos',
            "people_data": {
                "birthdays": birthdays,
                "anniversaries": anniversaries,
                "vacation": vacation_list,
                "contracts": contracts,
                "month_name": months_pt.get(today.month, today.strftime('%B'))
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<h1>Error Interno (500)</h1><pre>{traceback.format_exc()}</pre>", status_code=500)
# --- Smart Flow Routes ---
@app.get("/smart-flow", response_class=HTMLResponse)
async def smart_flow_page(request: Request, shift: str = "Manhã", date: Optional[str] = None, session: Session = Depends(get_session)):
    try:
        user = require_login(request)
        # Get Employees for "Available Pool" (Active, Sick, Vacation, Away - Everyone except Fired)
        # Auto-Update Vacation Status Check
        if date:
            try:
                update_vacation_statuses(session, datetime.strptime(date, "%Y-%m-%d"))
            except Exception as e:
                print(f"Error checking vacation dates: {e}")
                
        employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
        emp_map = {e.registration_id: e for e in employees}
        
        # Get Daily Op
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
            
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
                    { "key": "recebimento", "label": "Recebimento", "target": 0, "subsectors": ["Doca 1", "Doca 2", "Paletização"] },
                    { "key": "camara_fria", "label": "Câmara Fria", "target": 0, "subsectors": ["Armazenagem", "Abastecimento"] },
                    { "key": "selecao", "label": "Seleção", "target": 0, "subsectors": ["Linha 1", "Linha 2"] },
                    { "key": "expedicao", "label": "Expedição", "target": 0, "subsectors": ["Separação", "Carregamento"] }
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
            
        # Get employees who are substituted (for Dashboard "Substituição" KPI)
        # Logic: Events where text contains "Substituído por"
        sub_events = session.exec(select(models.Event).where(col(models.Event.text).contains("Substituído por"))).all()
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
                "is_substituted": e.registration_id in substituted_ids
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
        
        evt_text = f"Férias Agendadas: {fmt_start} a {fmt_end}"
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
            errors.append(f"Matrícula {item.registration_id} não encontrada.")
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
                text=f"Férias Agendadas: {item.start_date} a {item.end_date}",
                category="pessoas",
                sector=emp.cost_center or "Geral",
                timestamp=datetime.now()
            )
            session.add(hist_event)
            
            session.add(emp)
            updated_count += 1
            
        except ValueError:
            errors.append(f"Data inválida para matrícula {item.registration_id}")
        except Exception as e:
            errors.append(f"Erro ao processar matrícula {item.registration_id}: {str(e)}")

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
    Importa atestados médicos em lote a partir de planilha Excel/CSV
    
    Formato esperado:
    - Coluna 1: Matrícula
    - Coluna 2: Data Início (YYYY-MM-DD ou DD/MM/YYYY)
    - Coluna 3: Data Fim (YYYY-MM-DD ou DD/MM/YYYY)
    - Coluna 4: Observação (opcional)
    
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
    logger.info(f"[{trace_id}] Iniciando importação de atestados - arquivo: {file.filename}")
    
    # Validação 1: Tamanho do arquivo (max 5MB)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    contents = await file.read()
    
    if len(contents) > MAX_FILE_SIZE:
        logger.warning(f"[{trace_id}] Arquivo muito grande: {len(contents)} bytes")
        return JSONResponse({
            "error": "Arquivo muito grande. Tamanho máximo: 5MB",
            "trace_id": trace_id
        }, status_code=400)
    
    # Validação 2: Formato do arquivo
    allowed_extensions = ['.xlsx', '.xls', '.csv']
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        logger.warning(f"[{trace_id}] Formato inválido: {file_ext}")
        return JSONResponse({
            "error": f"Formato de arquivo inválido. Permitidos: {', '.join(allowed_extensions)}",
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
                raise ValueError("Não foi possível ler o arquivo CSV. Verifique o formato do arquivo.")
        else:
            df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
        
        logger.info(f"[{trace_id}] Arquivo lido com sucesso - {len(df)} linhas, {len(df.columns)} colunas")
        
    except Exception as e:
        logger.exception(f"[{trace_id}] Erro ao ler arquivo")
        return JSONResponse({
            "error": f"Erro ao processar arquivo: {str(e)}",
            "trace_id": trace_id
        }, status_code=400)
    
    # Validação 3: Verificar colunas obrigatórias
    if df.empty:
        return JSONResponse({
            "error": "Arquivo vazio",
            "trace_id": trace_id
        }, status_code=400)
    
    # Normalizar nomes de colunas (case-insensitive, sem espaços extras)
    # Também substituir underscores por espaços para normalização
    df.columns = df.columns.str.strip().str.lower().str.replace('_', ' ')
    
    # Mapear possíveis nomes de colunas (mais flexível)
    col_mapping = {}
    for col in df.columns:
        col_clean = col.replace(' ', '').replace('í', 'i').replace('ú', 'u')
        
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
            "error": f"Colunas obrigatórias faltando: {', '.join(missing_cols)}. Esperado: Matrícula, Data Início, Data Fim. Encontrado: {', '.join(found_cols)}",
            "trace_id": trace_id
        }, status_code=400)
    
    # Processar cada linha
    tz = ZoneInfo("America/Sao_Paulo")
    success_count = 0
    error_count = 0
    skipped_count = 0
    details = []
    
    for idx, row in df.iterrows():
        row_num = idx + 2  # +2 porque: índice começa em 0 + linha de cabeçalho
        
        try:
            # Extrair dados
            matricula = str(row[col_mapping['matricula']]).strip()
            data_inicio_raw = row[col_mapping['data_inicio']]
            data_fim_raw = row[col_mapping['data_fim']]
            observacao = str(row.get(col_mapping.get('observacao', ''), '')).strip() if 'observacao' in col_mapping else ''
            
            # Validação: Matrícula não vazia
            if not matricula or matricula == 'nan':
                details.append({
                    "linha": row_num,
                    "status": "erro",
                    "matricula": matricula,
                    "mensagem": "Matrícula vazia"
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
                    "mensagem": "Matrícula não encontrada no sistema"
                })
                skipped_count += 1
                logger.warning(f"[{trace_id}] Linha {row_num}: Matrícula {matricula} não encontrada")
                continue
            
            # Parsear datas (suporta YYYY-MM-DD e DD/MM/YYYY)
            def parse_date(date_val):
                """Tenta parsear data em múltiplos formatos"""
                if pd.isna(date_val):
                    return None
                
                # Se já é datetime do pandas
                if isinstance(date_val, pd.Timestamp):
                    return date_val.to_pydatetime().replace(tzinfo=tz)
                
                # Se é string
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
                    "mensagem": f"Data inválida (Início: {data_inicio_raw}, Fim: {data_fim_raw})"
                })
                error_count += 1
                logger.warning(f"[{trace_id}] Linha {row_num}: Datas inválidas para {emp.name}")
                continue
            
            # Validação: Data fim >= Data início
            if data_fim < data_inicio:
                details.append({
                    "linha": row_num,
                    "status": "erro",
                    "matricula": matricula,
                    "nome": emp.name,
                    "mensagem": "Data fim anterior à data início"
                })
                error_count += 1
                continue
            
            # Verificar duplicação (se já existe evento de atestado no período)
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
                    "mensagem": f"Já existe atestado registrado no período ({len(existing_events)} evento(s))"
                })
                skipped_count += 1
                logger.info(f"[{trace_id}] Linha {row_num}: Atestado duplicado para {emp.name}")
                continue
            
            # Criar eventos para cada dia do período
            current_date = data_inicio
            events_created = 0
            events_to_add = []
            routines_to_add = []
            
            while current_date <= data_fim:
                # Criar evento de atestado
                evt_text = f"Atestado médico"
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
                
                # Criar rotinas para todos os turnos (sem verificar se existe - mais rápido)
                date_str = current_date.strftime("%Y-%m-%d")
                for shift in ["Manhã", "Tarde", "Noite"]:
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
            # Não fazer rollback aqui - continuar processando outras linhas
    
    # Commit único no final (muito mais rápido!)
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
    
    logger.info(f"[{trace_id}] Importação concluída - Sucesso: {success_count}, Erros: {error_count}, Ignorados: {skipped_count}")
    
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
    """Página de importação de atestados"""
    user = require_login(request)
    return templates.TemplateResponse("import_medical_certificates.html", {
        "request": request,
        "user": user
    })

@app.get("/api/debug/force-sync")
async def force_sync_debug():
    """Força sincronização e retorna log detalhado"""
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
                     logs.append(f"❌ Config não encontrada para turno '{shift}'")
                     continue
                 
                 data = config_db.config_json
                 if isinstance(data, str):
                     import json
                     data = json.loads(data)
                 
                 if not data: 
                    logs.append(f"❌ JSON inválido/vazio para '{shift}'")
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
                                 logs.append(f"   🔧 CORRIGINDO '{s.name}': {target} -> {s.max_employees}")
                                 cs['target'] = s.max_employees
                                 changed = True
                             else:
                                 logs.append(f"   ✅ '{s.name}' OK: {target}")
                             break
                     
                     if not found:
                         logs.append(f"   ⚠️ '{s.name}' não encontrado no JSON")
                
                 if changed:
                     config_db.config_json = data
                     config_db.updated_at = datetime.now()
                     session.add(config_db)
                     logs.append(f"💾 Salvando config para '{shift}'")
            
            session.commit()
            logs.append("✅ Sync concluído com sucesso")
    except Exception as e:
        logs.append(f"❌ ERRO FATAL: {str(e)}")
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
    """Retorna todos os colaboradores (incluindo demitidos, mas excluindo substituídos)"""
    require_login(request)
    
    # Buscar TODOS os colaboradores não substituídos
    employees = session.exec(
        select(models.Employee)
        .where(models.Employee.replaced_by.is_(None))  # Excluir substituídos
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

@app.get("/api/smart-flow/sectors", response_class=JSONResponse)
async def get_sectors(
    request: Request,
    shift: str = "Manhã",
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

@app.post("/api/smart-flow/sectors", response_class=JSONResponse)
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
    
    # Pegar próxima ordem
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

@app.put("/api/smart-flow/sectors/{sector_id}", response_class=JSONResponse)
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
    # print(f"🔧 UPDATE_SECTOR CHAMADO: {sector_id} - {name}")
    
    sector = session.get(models.Sector, sector_id)
    if not sector:
        return JSONResponse({"error": "Setor não encontrado"}, status_code=404)
    
    # Track if max_employees changed (need to sync with SectorConfiguration)
    # FORÇANDO True para garantir sincronização durante debug
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
        
        # Atualizar meta do setor na configuração
        sectors_list = config_data.get('sectors', [])
        found = False
        
        for s in sectors_list:
            if s.get('label') == sector.name:
                s['target'] = sector.max_employees
                found = True
                break
        
        if found:
            # Salvar configuração atualizada
            config_db.config_json = config_data
            config_db.updated_at = datetime.now()
            session.add(config_db)
            session.flush()
            
    try:
        session.commit()
    except Exception as e:
        print(f"❌ Erro ao salvar setor ou configuração: {e}")
        session.rollback()
        return JSONResponse({"error": f"Erro ao atualizar setor: {e}"}, status_code=500)
    
    return {"success": True}

@app.delete("/api/smart-flow/sectors/{sector_id}", response_class=JSONResponse)
async def delete_sector(
    request: Request,
    sector_id: int,
    session: Session = Depends(get_session)
):
    """Exclui um setor e remove todas as alocações"""
    require_login(request)
    
    sector = session.get(models.Sector, sector_id)
    if not sector:
        return JSONResponse({"error": "Setor não encontrado"}, status_code=404)
    
    # Cascade delete vai remover sub-setores e alocações automaticamente
    session.delete(sector)
    session.commit()
    
    return {"success": True}

@app.post("/api/smart-flow/subsectors", response_class=JSONResponse)
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
        return JSONResponse({"error": "Setor não encontrado"}, status_code=404)
    
    # Pegar próxima ordem
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

@app.put("/api/smart-flow/subsectors/{subsector_id}", response_class=JSONResponse)
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
        return JSONResponse({"error": "Sub-setor não encontrado"}, status_code=404)
    
    if name is not None:
        subsector.name = name
    if max_employees is not None:
        subsector.max_employees = max_employees
    
    session.add(subsector)
    session.commit()
    
    return {"success": True}

@app.delete("/api/smart-flow/subsectors/{subsector_id}", response_class=JSONResponse)
async def delete_subsector(
    request: Request,
    subsector_id: int,
    session: Session = Depends(get_session)
):
    """Exclui um sub-setor e remove todas as alocações"""
    require_login(request)
    
    subsector = session.get(models.SubSector, subsector_id)
    if not subsector:
        return JSONResponse({"error": "Sub-setor não encontrado"}, status_code=404)
    
    # Cascade delete vai remover alocações automaticamente
    session.delete(subsector)
    session.commit()
    
    return {"success": True}

@app.get("/api/smart-flow/allocations", response_class=JSONResponse)
async def get_allocations(
    request: Request,
    date: str,
    shift: str,
    session: Session = Depends(get_session)
):
    """Retorna alocações e rotinas do dia/turno"""
    require_login(request)
    
    # Buscar alocações do dia atual
    allocations = session.exec(
        select(models.EmployeeAllocation)
        .where(models.EmployeeAllocation.date == date)
        .where(models.EmployeeAllocation.shift == shift)
    ).all()
    
    # Se não houver alocações, buscar do dia anterior
    if not allocations:
        from datetime import datetime, timedelta
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
            previous_date = current_date - timedelta(days=1)
            previous_date_str = previous_date.strftime("%Y-%m-%d")
            
            print(f"📋 Nenhuma alocação encontrada para {date}. Buscando escala de {previous_date_str}...")
            
            # Buscar alocações do dia anterior
            previous_allocations = session.exec(
                select(models.EmployeeAllocation)
                .where(models.EmployeeAllocation.date == previous_date_str)
                .where(models.EmployeeAllocation.shift == shift)
            ).all()
            
            if previous_allocations:
                print(f"✅ Encontradas {len(previous_allocations)} alocações do dia anterior. Copiando...")
                
                # Copiar alocações do dia anterior para o dia atual
                for prev_alloc in previous_allocations:
                    new_alloc = models.EmployeeAllocation(
                        date=date,
                        shift=shift,
                        employee_id=prev_alloc.employee_id,
                        subsector_id=prev_alloc.subsector_id
                    )
                    session.add(new_alloc)
                
                session.commit()
                
                # Recarregar alocações criadas
                allocations = session.exec(
                    select(models.EmployeeAllocation)
                    .where(models.EmployeeAllocation.date == date)
                    .where(models.EmployeeAllocation.shift == shift)
                ).all()
                
                print(f"✅ Escala copiada com sucesso! {len(allocations)} colaboradores alocados.")
        except Exception as e:
            print(f"❌ Erro ao copiar escala do dia anterior: {e}")
    
    # Buscar rotinas do dia atual
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date == date)
        .where(models.EmployeeRoutine.shift == shift)
    ).all()
    
    # Se não houver rotinas, copiar do dia anterior (especialmente Férias e Afastado)
    if not routines and allocations:
        from datetime import datetime, timedelta
        try:
            current_date = datetime.strptime(date, "%Y-%m-%d")
            previous_date = current_date - timedelta(days=1)
            previous_date_str = previous_date.strftime("%Y-%m-%d")
            
            print(f"📋 Buscando rotinas de {previous_date_str}...")
            
            # Buscar rotinas do dia anterior
            previous_routines = session.exec(
                select(models.EmployeeRoutine)
                .where(models.EmployeeRoutine.date == previous_date_str)
                .where(models.EmployeeRoutine.shift == shift)
            ).all()
            
            if previous_routines:
                # Copiar apenas rotinas persistentes (vacation, away, sick)
                persistent_routines = ['vacation', 'away', 'sick']
                copied_count = 0
                
                for prev_routine in previous_routines:
                    if prev_routine.routine in persistent_routines:
                        new_routine = models.EmployeeRoutine(
                            date=date,
                            shift=shift,
                            employee_id=prev_routine.employee_id,
                            routine=prev_routine.routine
                        )
                        session.add(new_routine)
                        copied_count += 1
                
                if copied_count > 0:
                    session.commit()
                    print(f"✅ {copied_count} rotinas persistentes copiadas (Férias/Afastado/Atestado)")
                    
                    # Recarregar rotinas
                    routines = session.exec(
                        select(models.EmployeeRoutine)
                        .where(models.EmployeeRoutine.date == date)
                        .where(models.EmployeeRoutine.shift == shift)
                    ).all()
        except Exception as e:
            print(f"❌ Erro ao copiar rotinas: {e}")
    
    # Montar resposta - APENAS subsector_id, não objeto completo
    allocations_map = {}
    for alloc in allocations:
        allocations_map[alloc.employee_id] = alloc.subsector_id
    
    routines_map = {}
    for routine in routines:
        routines_map[routine.employee_id] = routine.routine
    
    # Buscar tonélagem das ROTAS (Automático)
    # Requisito: "Favor puxar os dados da tonelagem das rotas"
    route_tonnage = session.exec(
        select(func.sum(models.Route.tonnage))
        .where(models.Route.date == date)
        .where(models.Route.shift == shift) # Filter by shift to match operation context
        .where(models.Route.tonnage > 0)
    ).one()
    
    tonnage = route_tonnage if route_tonnage else 0.0
    
    # Se quiser manter o manual como fallback ou override, teria que ter lógica extra.
    # Mas o pedido implica que as rotas são a fonte.
    # daily_op = session.exec(...)
    # tonnage = daily_op.tonnage if daily_op and daily_op.tonnage else 0

    return {
        "allocations": allocations_map,
        "routines": routines_map,
        "tonnage": tonnage
    }

@app.post("/api/smart-flow/allocations/save", response_class=JSONResponse)
async def save_allocations(
    request: Request,
    session: Session = Depends(get_session)
):
    """Salva alocações e rotinas do dia (Otimizado)"""
    require_login(request)
    
    try:
        data = await request.json()
        date = data.get("date")
        shift = data.get("shift")
        allocations = data.get("allocations", {})  # {employee_id: subsector_id}
        routines = data.get("routines", {})  # {employee_id: routine}
        tonnage = data.get("tonnage") # Optional float
        
        if not date or not shift:
            return JSONResponse({"error": "Data e turno são obrigatórios"}, status_code=400)
            
        print(f"⚡ [SmartFlow] Salvando alocações para {date} - {shift}")
        
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
            print(f"⚠️ Erro no bulk delete, tentando delete manual: {e_del}")
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
        
        print(f"💾 Commit final ({len(new_alloc_objs)} alocações, {len(attendance_log)} logs)...")
        session.commit()
        print("✅ Salvo com sucesso!")
        
        return {"success": True, "message": "Dados salvos com sucesso"}
        
    except Exception as e:
        print(f"❌ ERRO ao salvar alocações: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return JSONResponse({"error": str(e), "success": False}, status_code=500)


@app.post("/api/employees/vacation", response_class=JSONResponse)
async def set_employee_vacation(
    request: Request,
    session: Session = Depends(get_session)
):
    """Define férias de um colaborador"""
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
            return JSONResponse({"error": "Colaborador não encontrado"}, status_code=404)
        
        # Validar datas
        start_date = datetime.strptime(vacation_start, "%Y-%m-%d")
        end_date = datetime.strptime(vacation_end, "%Y-%m-%d")
        
        if start_date > end_date:
            return JSONResponse({"error": "Data de início não pode ser maior que data de fim"}, status_code=400)
        
        # Atualizar colaborador
        employee.vacation_start = start_date
        employee.vacation_end = end_date
        employee.status = "vacation"
        
        # Criar evento para histórico
        event = models.Event(
            timestamp=datetime.now(),
            text=f"Férias Agendadas: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}",
            type="ferias_hist",
            category="vacation",
            employee_id=employee_id
        )
        session.add(event)
        
        session.commit()
        
        print(f"✅ Férias definidas: {employee.name} - {vacation_start} até {vacation_end}")
        
        return {"success": True, "message": "Férias definidas com sucesso"}
    except Exception as e:
        print(f"❌ Erro ao definir férias: {e}")
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)


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
            return JSONResponse({"error": "Colaborador não encontrado"}, status_code=404)
        
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
        
        # Atualizar colaborador APENAS se for mudança de status persistente
        if should_update_status:
             employee.status = new_status
        
        # Se voltar para presente, limpar férias
        if routine == 'present':
            employee.vacation_start = None
            employee.vacation_end = None
        
        # Labels em português
        routine_labels = {
            'present': 'Presente',
            'vacation': 'Férias',
            'sick': 'Atestado',
            'away': 'Afastado',
            'absent': 'Falta',
            'dayoff': 'Folga'
        }
        
        # Determine Event Type correctly for Report
        # Map routine -> event_type
        event_type_map = {
             'sick': 'atestado',
             'absent': 'falta',
             'away': 'afastamento',
             'vacation': 'ferias',
             'dayoff': 'folga',
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
        
        session.commit()
        
        print(f"✅ Rotina atualizada: {employee.name} - {routine}")
        
        return {"success": True, "message": "Rotina atualizada com sucesso"}
    except Exception as e:
        print(f"❌ Erro ao atualizar rotina: {e}")
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)

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
        
        # 3. Fetch Sector Config (Targets)
        sector_config_db = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == shift)).first()
        sector_config = {}
        if sector_config_db and sector_config_db.config_json:
            sector_config = sector_config_db.config_json
            if isinstance(sector_config, str):
                try:
                    sector_config = json.loads(sector_config)
                except:
                    sector_config = {}
                    
        # DEBUG: Log configuration status
        print(f"🔍 DEBUG - Sector Config DB found: {sector_config_db is not None}")
        if sector_config_db:
            print(f"🔍 DEBUG - Config JSON type: {type(sector_config_db.config_json)}")
            print(f"🔍 DEBUG - Sectors in config: {len(sector_config.get('sectors', []))}")
            if sector_config.get('sectors'):
                for s in sector_config['sectors']:
                    print(f"   - {s.get('label')}: meta {s.get('target')}")
        else:
            print(f"⚠️ WARNING - No SectorConfiguration found for shift '{shift}'")
                    
        # IMPORTANTE: Não usar defaults hardcoded
        # O relatório deve sempre usar a configuração real do Smart Flow
        # Se não houver configuração, mostrar lista vazia (não inventar setores)
        if not sector_config or "sectors" not in sector_config:
            print(f"⚠️ WARNING - Using empty sectors list (no config found)")
            sector_config = {"sectors": []}
            
        SECTORS = sector_config.get("sectors", [])
        
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
            # Priority: Routine > Employee Status > 'present'
            status = routine_map.get(emp.id, 'present')
            
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
                    models.Event.text.like("%Substituído por%")
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

        # 2. Process Remaining Employees (Same Shift, No Routine Today)
        # This catches "Away", "Vacation" people who didn't get a routine entry today
        for emp in all_employees:
            if emp.id in processed_ids:
                continue
                
            if emp.status == 'fired': 
                continue # Fired and no routine = ignored
                
            # Check Shift
            emp_shift_norm = normalize_str(emp.work_shift)
            if target_shift_norm not in emp_shift_norm:
                continue # Wrong shift
                
            # Determine Status from DB Profile
            db_status = emp.status
            report_status = 'present' # Default assumption if active
            
            if db_status == 'away':
                report_status = 'away'
            elif db_status == 'vacation':
                report_status = 'vacation'
            elif db_status == 'active':
                # Active but no routine... Assume present (unallocated) or just list them?
                # If we assume present, we might increase "Presentes" count.
                # If they are truly absent, they should have been marked 'absent'.
                # Assumption: Active = Present
                report_status = 'present'
                total_present += 1
            
            # Substituted Check (Duplicate logic, could functionality extract)
            is_substituted = False
            if report_status in ['away', 'vacation']:
                 has_sub_evt = session.exec(select(models.Event).where(
                    models.Event.employee_id == emp.id,
                    models.Event.text.like("%Substituído por%")
                 )).first()
                 if has_sub_evt:
                     is_substituted = True

            people_list.append({
                "name": emp.name,
                "status_daily": report_status,
                "sector_daily": None, # Unallocated
                "is_substituted": is_substituted
            })
        
        # DEBUG: Mostrar setores únicos presentes no attendance_log
        unique_sectors = set(p['sector_daily'] for p in people_list if p['sector_daily'])
        print(f"🔍 DEBUG - Setores no attendance_log: {unique_sectors}")
        print(f"🔍 DEBUG - Total de colaboradores: {len(people_list)}")
            
        # Substituted Count (Employees 'Away' who have a replacement OR Active employees who are replacements?)
        # User said "reminding that it can only pull this information from the away routine when creating a new employee"
        # Interpreted as: Count of Away employees who have been substituted.
        # Logic: Find 'away' employees. Check if they have an event "Substituído por..."
        count_substitutions = 0
        away_employees = [e for e in all_employees if e.status == 'away']
        for emp in away_employees:
            has_sub = session.exec(select(models.Event).where(
                models.Event.employee_id == emp.id,
                models.Event.text.like("%Substituído por%")
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
            # Isso mantém consistência com o Smart Flow
            
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
                "vacation_away": len(vacation_away_people), # Férias/Afastados
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
                "label": "Outros / Não Definido",
                "target": 0,
                "allocated_count": len(others_allocated),
                "present_count": len(others_present),
                "vacancies": 0,
                "absences": len(others_absent),
                "vacation_away": len(others_vac_away),
                "gap": 0
            })
            total_allocated_sum += len(others_allocated)
            
        # Top KPIs - ALINHADO COM SMART FLOW
        # IMPORTANTE: Total target = SOMA DAS METAS CONFIGURADAS (não colaboradores do turno)
        # Isso garante consistência com o Smart Flow
        
        # total_target já foi calculado no loop acima (soma de todas as metas)
        # Não usar total_target_real (colaboradores ativos) pois isso causa divergência
        
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
                models.Event.text.like("%Substituído por%")
            )).first()
            if has_sub:
                count_substitutions += 1
        
        # DEBUG DIAGNOSTIC
        print(f"Relatório Debug - Data: {date}, Turno: {shift}")
        print(f"Meta Total: {total_target}")
        print(f"Headcount Total (People List): {total_headcount}")
        print(f"Presentes: {total_present}, Faltas: {daily_absent}, Férias: {daily_vacation}, Afastados: {daily_away}")
        print(f"Vagas Calculadas (Meta - Headcount): {kpi_vacancies}")
        print(f"Vagas Operacionais (Soma Setores): {total_operational_vacancies}")
        
        # Check filtered out employees
        ignored_count = 0
        for emp in all_employees:
            if emp.id not in processed_ids and emp.status != 'fired':
                emp_shift_norm = normalize_str(emp.work_shift)
                if target_shift_norm not in emp_shift_norm:
                     # print(f"Ignorado (Turno Incompatível): {emp.name} ({emp.work_shift}) - Status: {emp.status}")
                     ignored_count += 1
        print(f"Total ignorados por turno incompatível: {ignored_count}")

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
        return HTMLResponse(content=f"<h1>Erro ao Gerar Relatório</h1><pre>{traceback.format_exc()}</pre>", status_code=500)

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
        # Fetch Employees (excluindo substituídos)
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
            models.HeadcountTarget(shift_name="Manhã", target_value=50),
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
    sector_map_sum = {"Manhã": 0, "Tarde": 0, "Noite": 0}
    has_sectors = False
    
    for sec in all_sectors:
        # Normalize shift name just in case
        sec_shift_norm = "Manhã"
        if "tarde" in sec.shift.lower(): sec_shift_norm = "Tarde"
        elif "noite" in sec.shift.lower(): sec_shift_norm = "Noite"
        
        sector_map_sum[sec_shift_norm] += sec.max_employees
        has_sectors = True
        
    # Decision: User stated /employees is OFFICIAL.
    # So we MUST prioritize the Manual Target (Legacy) over Sector Sum key-by-key.
    # Sector Sum is operational capacity, but Target is HR Budget.
    
    target_map = {}
    for s in ["Manhã", "Tarde", "Noite"]:
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
    shifts = ["Manhã", "Tarde", "Noite"]
    shift_stats = []
        # Init counters for each shift
    shift_data = {
        "Manhã": {"active": 0, "vacation": 0, "away": 0},
        "Tarde": {"active": 0, "vacation": 0, "away": 0},
        "Noite": {"active": 0, "vacation": 0, "away": 0}
    }
    # Helper to determine shift from work_shift
    def get_shift_name(shift_val):
        s = (shift_val or "").strip().lower()
        if "noite" in s: return "Noite"
        if "tarde" in s: return "Tarde"
        # Default to Manhã only if explicitly Manhã or fallback
        return "Manhã"
    total_real_active = 0
    for e in employees:
        if e.status == "fired":
            continue
        # Count towards total if not fired
        total_real_active += 1
        # Determine shift
        s_name = get_shift_name(e.work_shift)
        # Increment specific status counter for that shift
        if e.status == "active":
            shift_data[s_name]["active"] += 1
        elif e.status == "vacation":
            shift_data[s_name]["vacation"] += 1
        elif e.status == "away":
            shift_data[s_name]["away"] += 1
        
    for s in shifts:
        data = shift_data.get(s, {"active":0, "vacation":0, "away":0})
        active_count = data["active"] # Active presence
        # Total head count for vacancies calculation includes active + vacation + away? 
        # Usually vacancies = Target - Headcount (Active people).
        # Here active_count is purely status='active' (present).
        # We need total headcount of the shift (excluding fired).
        total_shift_headcount = data["active"] + data["vacation"] + data["away"]
        
        target = target_map.get(s, 0)
        shift_stats.append({
            "name": s,
            "count": active_count, # Display "Active" users
            "headcount": total_shift_headcount, # Logic for vacancies
            "vacation": data["vacation"],
            "away": data["away"],
            "target": target,
            "vacancies": max(0, target - total_shift_headcount)
        })
        
    # Status Stats (Global)
    status_stats = {
        "vacation": sum(1 for e in employees if e.status == "vacation"),
        "away": sum(1 for e in employees if e.status == "away"),
        "fired": sum(1 for e in employees if e.status == "fired")
    }
    return templates.TemplateResponse("employees.html", {
        "request": request,
        "user": user,
        "employees": employees,
        "stats": {
            "total_active": total_real_active,
            "total_target": total_target,
            "vacancies": total_target - total_real_active,
            "shifts": shift_stats,
            "statuses": status_stats,
            "targets_map": target_map # Pass map for editing logic
        },
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success")
    })

class HeadcountTargetUpdate(BaseModel):
    targets: dict[str, int] # e.g. {"Manhã": 50, "Tarde": 40}

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
    if "manhã" in s_lower or "manha" in s_lower:
        default_schedule = "05:00 - 13:20"
    elif "tarde" in s_lower:
        default_schedule = "12:00 - 20:20"
    elif "noite" in s_lower:
        default_schedule = "19:00 - 07:00"

    new_employee = models.Employee(
        name=name,
        registration_id=registration_id,
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
                # Marcar colaborador antigo como substituído
                old_emp.replaced_by = new_employee.id
                session.add(old_emp)
                
                # 1. History for New Employee
                # "Entrou em substituição a X (Motivo)"
                reason_pt = "Demitido" if sub_reason == 'fired' else "Afastado"
                new_evt = models.Event(
                    text=f"Entrou em substituição a {old_emp.name} ({reason_pt})",
                    type="alteracao_cadastro",
                    category="pessoas",
                    employee_id=new_employee.id,
                    sector="RH"
                )
                session.add(new_evt)
                
                # 2. History for Old Employee
                # "Substituído por Y (Data)"
                old_evt = models.Event(
                    text=f"Substituído por {new_employee.name}",
                    type="alteracao_cadastro",
                    category="pessoas",
                    employee_id=old_emp.id,
                    sector="RH"
                )
                session.add(old_evt)
        
        session.commit()
        session.commit()
    except Exception as e:
        print(f"Error adding employee: {e}")
        return RedirectResponse(url=f"/employees?error=Erro ao adicionar colaborador: {str(e)}", status_code=status.HTTP_303_SEE_OTHER)
    
    return RedirectResponse(url="/employees?success=Colaborador adicionado com sucesso", status_code=status.HTTP_303_SEE_OTHER)
@app.get("/employees/{employee_id}", response_class=HTMLResponse)
async def employee_detail(request: Request, employee_id: int, session: Session = Depends(get_session)):
    user = require_login(request)
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return RedirectResponse(url="/employees")
    
    # Adjust for Timezone (UTC to BRT approx or Shift logic)
    # If server is UTC, now() might be tomorrow. If server is BRT, -3h is still same day (usually).
    today = datetime.now() - timedelta(hours=3)
    today_date = today

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
    events = session.exec(select(models.Event).where(models.Event.employee_id == employee_id).order_by(models.Event.timestamp.desc())).all()
    
    warnings = len([e for e in events if e.type == 'advertencia'])
    medicals = len([e for e in events if e.type == 'atestado'])
    absences = len([e for e in events if e.type == 'falta'])
    
    stats = {
        "advertencias": warnings,
        "atestados": medicals,
        "faltas": absences,
        "ferias": len([e for e in events if e.type == 'ferias']) # Assuming type exists differently or calculated
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
            
    days_map = {'Monday': 'Segunda', 'Tuesday': 'Terça', 'Wednesday': 'Quarta', 'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'Sábado', 'Sunday': 'Domingo'}
    # Translate immediately for simpler template
    work_days_display = ", ".join([days_map.get(d, d) for d in work_days_list])

    # Fetch Recent Routines (Last 15)
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.employee_id == employee_id)
        .order_by(models.EmployeeRoutine.date.desc())
        .limit(15)
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
        "current_allocation": current_allocation,
        "current_activity": current_activity
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
            # Explicitly fetch and unlink events to ensure no FK constraints block deletion
            stmt = select(models.Event).where(models.Event.employee_id == emp_id)
            events = session.exec(stmt).all()
            for event in events:
                event.employee_id = None
                session.add(event)
            session.delete(emp)
        else:
            # Generate History Event
            event_type = "ocorrencia"
            text_desc = f"Status alterado para {status_action}"
            if status_action == "vacation":
                event_type = "ferias_hist"
                text_desc = "Entrou em Férias"
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
                     "vacation": "Férias",
                     "away": "Afastado",
                     "fired": "Demitido",
                     "day_off": "Folga"
                 }
                 pt_status = status_map.get(status_action, status_action)
                 text_desc = f"Alteração de Rotina ({datetime.now().strftime('%d/%m/%Y')}): {pt_status}"
                 
            new_event = models.Event(
                text=text_desc,
                type=event_type,
                category="pessoas",
                employee_id=emp.id,
                shift_id=None 
            )
            session.add(new_event)
            emp.status = status_action
            session.add(emp)
        session.commit()
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
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    
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
        raise HTTPException(status_code=404, detail="Evento de férias não encontrado")
        emp = session.get(models.Employee, event.employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")
    try:
        # Update Employee Dates
        v_start = datetime.strptime(start_date, "%Y-%m-%d")
        v_end = datetime.strptime(end_date, "%Y-%m-%d")
        # Update Event Text (BR Format)
        fmt_start = v_start.strftime("%d/%m/%Y")
        fmt_end = v_end.strftime("%d/%m/%Y")
        event.text = f"Férias Agendadas: {fmt_start} a {fmt_end}"
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
        raise HTTPException(status_code=400, detail="Data inválida")
        
    return RedirectResponse(url=f"/employees/{emp.id}", status_code=status.HTTP_303_SEE_OTHER)
@app.post("/employees/{emp_id}/update")
async def update_employee(
    emp_id: int,
    request: Request,
    name: str = Form(...),
    registration_id: str = Form(...),
    role: str = Form(...),
    work_shift: str = Form(...),
    cost_center: str = Form(...),
    admission_date: str = Form(None),
    birthday: str = Form(None),
    work_days: List[str] = Form(None),
    work_schedule: str = Form(None),
    mobile_access: bool = Form(False),
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
                text=f"Alteração de Cargo: {emp.role} para {role}",
                type="alteracao_cadastro",
                category="pessoas",
                employee_id=emp.id
            ))
        # Log Cost Center Change
        if emp.cost_center != cost_center:
            session.add(models.Event(
                text=f"Alteração de Centro de Custo: {emp.cost_center} -> {cost_center}",
                type="alteracao_cadastro",
                category="pessoas",
                employee_id=emp.id
            ))
            
        emp.name = name
        emp.registration_id = registration_id
        emp.role = role
        emp.work_shift = work_shift
        emp.cost_center = cost_center
        emp.cost_center = cost_center
        emp.work_schedule = work_schedule
        emp.mobile_access = mobile_access

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
    Importa ocorrências (Faltas/Atestados) a partir de texto copiado do Excel.
    Formato esperado: Matricula | Nome(Ignorado) | Data | Ocorrência
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
            stats['errors'].append(f"Matrícula {reg_id}: Colaborador não encontrado")
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
                stats['errors'].append(f"Matrícula {reg_id}: Data inválida ({date_str})")
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
                elif "suspensão" in occ_lower or "suspensao" in occ_lower:
                    routine_type, event_type = "absent", "suspension"
                elif "advertência" in occ_lower or "advertencia" in occ_lower:
                    routine_type, event_type = None, "advertencia"
                else:
                    stats['errors'].append(f"Matrícula {reg_id}: Ocorrência desconhecida ({occurrence_raw})")
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
            text=f"Importação em Massa: {entry['raw_occ']}",
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
    content = await file.read()
    try:
        # Check if first row is title or header
        # Try reading a few lines to inspect
        df_temp = pd.read_excel(io.BytesIO(content), header=None, nrows=5)
        
        header_row = 0
        # Look for "Matrícula" or "Colaborador" in the first few rows
        for idx, row in df_temp.iterrows():
            row_vals = [str(x).strip() for x in row.values if pd.notna(x)]
            if any(h in row_vals for h in ["Matrícula", "Matricula", "Colaborador", "Turno"]):
                header_row = idx
                break
                
        # Reload with correct header
        df = pd.read_excel(io.BytesIO(content), header=header_row)
        
        # Clean column names (strip whitespace and title case for better matching)
        # We will create a map of normalized_col -> original_col to rename correctly below
        # Actually simplest is just to add more keys to the map.
        df.columns = df.columns.astype(str).str.strip()
        
        # Map Portuguese headers (Robust mapping)
        column_map = {
            "Matrícula": "registration_id", "Matricula": "registration_id", "MATRICULA": "registration_id", "MATRÍCULA": "registration_id",
            "Colaborador": "name", "Nome": "name", "COLABORADOR": "name", "NOME": "name",
            "Data Admissão": "admission_date", "Admissão": "admission_date", "DATA ADMISSÃO": "admission_date", "ADMISSÃO": "admission_date",
            "Data Nascimento": "birthday", "Nascimento": "birthday", "DATA NASCIMENTO": "birthday", "NASCIMENTO": "birthday",
            "Centro de Custo": "cost_center", "CENTRO DE CUSTO": "cost_center",
            "Cargo": "role", "Função": "role", "CARGO": "role", "FUNÇÃO": "role", "FUNCAO": "role",
            "Turno": "work_shift", "TURNO": "work_shift"
        }
        df = df.rename(columns=column_map)
        count = 0 
        for _, row in df.iterrows():
            # Validation
            reg_id = str(row.get("registration_id", ""))
            if not reg_id or reg_id.lower() == "nan" or reg_id.strip() == "":
                continue
                
            # Check exist
            existing = session.exec(select(models.Employee).where(models.Employee.registration_id == reg_id)).first()
            if not existing:
                # Parse Dates
                admission = None
                if "admission_date" in row and pd.notna(row["admission_date"]):
                    try:
                        admission = pd.to_datetime(row["admission_date"]).to_pydatetime()
                    except:
                        pass
                        
                bday = None
                if "birthday" in row and pd.notna(row["birthday"]):
                    try:
                        bday = pd.to_datetime(row["birthday"]).to_pydatetime()
                    except:
                        pass
                        
                # Shift
                shift_raw = str(row.get("work_shift", "Manhã"))
                if pd.isna(shift_raw) or shift_raw.strip() == "" or shift_raw.lower() == "nan":
                    shift_raw = "Manhã"
                    
                # Normalize specific cases to match System options (Manhã, Tarde, Noite)
                shift_clean = shift_raw.strip().title() # Converts NOITE -> Noite
                
                if "Manha" in shift_clean or "Manhã" in shift_clean:
                    shift_val = "Manhã"
                elif "Tarde" in shift_clean:
                    shift_val = "Tarde"
                elif "Noite" in shift_clean:
                    shift_val = "Noite"
                else:
                    shift_val = shift_clean # Fallback (e.g. ADM)

                # Auto-assign Schedule
                default_schedule = None
                s_lower = (shift_val or "").lower()
                if "manhã" in s_lower or "manha" in s_lower:
                    default_schedule = "05:00 - 13:20"
                elif "tarde" in s_lower:
                    default_schedule = "12:00 - 20:20"
                elif "noite" in s_lower:
                    default_schedule = "19:00 - 07:00"

                emp = models.Employee(
                    name=str(row.get("name", "Sem Nome")).strip(),
                    registration_id=reg_id.strip(),
                    role=str(row.get("role", "Operador")).strip(),
                    work_shift=str(shift_val).strip(),
                    cost_center=str(row.get("cost_center", "Geral")).strip(),
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
        return RedirectResponse(url=f"/employees?error=Erro na importação: {str(e)}", status_code=status.HTTP_303_SEE_OTHER)
        
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
def get_people_intelligence_metrics(session: Session, shift: str, start_date: Optional[str], end_date: Optional[str]):
    # 1. Overview Data (excluindo substituídos e demitidos)
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
    # This is more accurate for "Taxa de Absenteísmo" (Man-Days).
    
    # Fetch Routines for the period
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date >= start_dt.strftime("%Y-%m-%d"))
        .where(models.EmployeeRoutine.date <= end_dt.strftime("%Y-%m-%d"))
    ).all()
    
    # Filter routines for selected shift employees
    routines = [r for r in routines if r.employee_id in employee_ids]
    
    # Contadores gerais (Dias)
    total_absences = sum(1 for r in routines if r.routine in ['absent', 'falta'])
    total_sick = sum(1 for r in routines if r.routine in ['sick', 'atestado'])
    total_away = sum(1 for r in routines if r.routine in ['away', 'afastado'])
    
    # 2. Rankings (Top Offenders - by DAYS)
    emp_stats = {}
    
    # Initial population from employees list (to blank fill)
    for emp in employees:
         emp_stats[emp.id] = {'falta': 0, 'atestado': 0, 'advertencia': 0, 'afastamento': 0, 'name': emp.name, 'sector': emp.cost_center or "Geral", 'tenure_months': 0}
         if emp.admission_date:
                delta = datetime.now() - emp.admission_date
                emp_stats[emp.id]['tenure_months'] = int(delta.days / 30)

    # Count Routines (Days)
    for r in routines:
        if r.employee_id not in emp_stats: continue # Should be covered by filter above
        
        # Normalize routine types
        r_type = r.routine
        if r_type in ['absent', 'falta']:
            emp_stats[r.employee_id]['falta'] += 1
        elif r_type in ['sick', 'atestado']:
            emp_stats[r.employee_id]['atestado'] += 1
        elif r_type in ['away', 'afastado']:
            emp_stats[r.employee_id]['afastamento'] += 1
            
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
    session: Session = Depends(get_session)
):
    """Print-ready version of people intelligence (no sidebar)"""
    user = require_login(request)
    data = get_people_intelligence_metrics(session, shift, start_date, end_date)
    
    return templates.TemplateResponse("people_intelligence_report.html", {
        "request": request,
        "current_shift": shift,
        "start_date": data['start_date'],
        "end_date": data['end_date'],
        "overview": data['overview'],
        "top_absent": data['top_absent'][:10],
        "top_sick": data['top_sick'][:10],
        "sectors": data['sectors'],
        "chronic_offenders": data['chronic_offenders'][:10]
    })



@app.get("/smart-flow/load", response_class=JSONResponse)
async def smart_flow_load(request: Request, shift: str = "Manhã", date: Optional[str] = None, session: Session = Depends(get_session)):
    try:
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

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
                    { "key": "recebimento", "label": "Recebimento", "target": 0, "subsectors": ["Doca 1", "Doca 2", "Paletização"] },
                    { "key": "camara_fria", "label": "Câmara Fria", "target": 0, "subsectors": ["Armazenagem", "Abastecimento"] },
                    { "key": "selecao", "label": "Seleção", "target": 0, "subsectors": ["Linha 1", "Linha 2"] },
                    { "key": "expedicao", "label": "Expedição", "target": 0, "subsectors": ["Separação", "Carregamento"] }
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

# --- Operational History Routes ---

@app.get("/operational/history", response_class=HTMLResponse)
async def operational_history_page(request: Request):
    """Render the Operational History Page"""
    try:
        require_login(request)
        return templates.TemplateResponse("operational_history.html", {"request": request})
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
            return JSONResponse({"error": "Rota não encontrada"}, status_code=404)
            
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
            return JSONResponse({"error": "Rota não encontrada"}, status_code=404)
        
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
