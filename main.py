from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from typing import Optional, List
import json
from datetime import datetime, timedelta
import traceback
import os
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select, col
from typing import List
from database import create_db_and_tables, get_session
import models
import logging
import unicodedata
logging.basicConfig(filename='logs.txt', level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# --- Config ---
SECRET_KEY = "your-secret-key-change-in-production"
ALLOWED_USER = "feliperanon"
ALLOWED_PASS = "571232ce"

# --- Helper Functions ---
def calculate_expected_work_days(work_days_json: str, start_date: datetime, end_date: datetime) -> int:
    """
    Calcula quantos dias o colaborador deveria trabalhar baseado na escala.
    
    Args:
        work_days_json: JSON string com dias da semana, ex: '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]'
        start_date: Data inicial do período
        end_date: Data final do período
    
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
    
    while current_date < end_date:
        if current_date.weekday() in work_day_numbers:
            expected_days += 1
        current_date += timedelta(days=1)
    
    return expected_days


# API Models
from pydantic import BaseModel
from typing import Optional, List
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
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield
app = FastAPI(lifespan=lifespan)
# Add Session Middleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
# --- Auth Dependencies ---
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)
def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        return None
    return user
def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, detail="Not authenticated")
    return user
# --- Routes ---
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
# --- Route Management ---
# --- Separação de Mercadorias Management ---
@app.get("/separacao", response_class=HTMLResponse)
async def separacao_page(request: Request, date: Optional[str] = None, shift: str = "Manhã", session: Session = Depends(get_session)):
    user = require_login(request)
    
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
        
    # 1. Fetch DailyOperation
    daily_op = session.exec(
        select(models.DailyOperation)
        .where(models.DailyOperation.date == date)
        .where(models.DailyOperation.shift == shift)
    ).first()
    
    # 2. Filter Employees (Sector == Expedicao)
    all_employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
    emp_map_reg = {e.registration_id: e for e in all_employees}
    
    eligible_employees = []
    if daily_op and daily_op.attendance_log:
        for reg_id, data in daily_op.attendance_log.items():
            if data.get('sector') == 'expedicao': 
                emp = emp_map_reg.get(reg_id)
                if emp:
                    eligible_employees.append(emp)
                    
    eligible_employees.sort(key=lambda x: x.name)

    # 3. Fetch Clients
    clients = session.exec(select(models.Client)).all()
    cli_map = {c.id: c.name for c in clients}

    # 4. Fetch Routes
    db_routes = session.exec(
        select(models.Route)
        .where(models.Route.date == date)
        .where(models.Route.shift == shift)
        .order_by(models.Route.start_time)
    ).all()

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
            if diff <= 0: return 0.0
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
        routes_view.append({
            "id": r.id,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "tonnage": r.tonnage if r.tonnage is not None else 0.0,
            "tonnage_fmt": fmt_num(r.tonnage),
            "productivity": prod,
            "productivity_fmt": fmt_num(prod),
            "duration_fmt": calc_duration_str(r.start_time, r.end_time),
            "employee_name": emp_map_id.get(r.employee_id, models.Employee(name="Desconhecido")).name,
            "client_name": cli_map.get(r.client_id, "Desconhecido"),
            "employee_id": r.employee_id,
            "client_id": r.client_id
        })

    return templates.TemplateResponse("routes.html", {
        "request": request, 
        "user": user,
        "employees": eligible_employees, 
        "clients": clients,
        "routes": routes_view,
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
    client_id: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(None),
    tonnage: float = Form(0.0),
    session: Session = Depends(get_session)
):
    require_login(request)
    try:
        new_route = models.Route(
            date=date,
            shift=shift,
            employee_id=employee_id,
            client_id=client_id,
            start_time=start_time,
            end_time=end_time,
            tonnage=tonnage,
            status="pending"
        )
        session.add(new_route)
        session.commit()
    except Exception as e:
        print(f"Error adding separacao: {e}")
    return RedirectResponse(url=f"/separacao?date={date}&shift={shift}", status_code=status.HTTP_303_SEE_OTHER)
@app.post("/separacao/delete/{route_id}", response_class=RedirectResponse)
async def delete_separacao(
    request: Request,
    route_id: int,
    session: Session = Depends(get_session)
):
    require_login(request)
    route = session.get(models.Route, route_id)
    if route:
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
    employee_id: int = Form(None), # Made optional as finish modal doesn't send it? Wait, finish modal sends hidden inputs. Edit modal sends all.
    client_id: int = Form(None),
    start_time: str = Form(None),
    end_time: str = Form(None),
    tonnage: Optional[float] = Form(None),
    session: Session = Depends(get_session)
):
    require_login(request)
    route = session.get(models.Route, route_id)
    if route:
        if employee_id is not None: route.employee_id = employee_id
        if client_id is not None: route.client_id = client_id
        if start_time is not None: route.start_time = start_time
        if end_time is not None: route.end_time = end_time
        if tonnage is not None: route.tonnage = tonnage
        session.add(route)
        session.commit()
        return RedirectResponse(url=f"/separacao?date={route.date}&shift={route.shift}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/separacao", status_code=status.HTTP_303_SEE_OTHER)
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, shift: Optional[str] = None, session: Session = Depends(get_session)):
    try:
        user = get_current_user(request)
        if not user:
            return RedirectResponse(url="/login")
        # --- People Management Logic ---
        today = datetime.now().date()
        # Base Query
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
                                evt_text = f"Registro: {status.upper()} em {data.date}"
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
async def get_employees(
    request: Request,
    session: Session = Depends(get_session)
):
    """Retorna lista de todos os colaboradores ativos"""
    require_login(request)
    
    employees = session.exec(
        select(models.Employee)
        .where(models.Employee.status != 'fired')
    ).all()
    
    return {
        "employees": [{
            "id": e.registration_id,
            "name": e.name,
            "role": e.role,
            "shift": e.work_shift,
            "cost_center": e.cost_center,
            "status": e.status
        } for e in employees]
    }

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
    
    sector = session.get(models.Sector, sector_id)
    if not sector:
        return JSONResponse({"error": "Setor não encontrado"}, status_code=404)
    
    if name is not None:
        sector.name = name
    if max_employees is not None:
        sector.max_employees = max_employees
    if color is not None:
        sector.color = color
    
    sector.updated_at = datetime.now()
    session.add(sector)
    session.commit()
    
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
    
    # Buscar alocações
    allocations = session.exec(
        select(models.EmployeeAllocation)
        .where(models.EmployeeAllocation.date == date)
        .where(models.EmployeeAllocation.shift == shift)
    ).all()
    
    # Buscar rotinas
    routines = session.exec(
        select(models.EmployeeRoutine)
        .where(models.EmployeeRoutine.date == date)
        .where(models.EmployeeRoutine.shift == shift)
    ).all()
    
    # Montar resposta
    allocations_map = {}
    for alloc in allocations:
        allocations_map[alloc.employee_id] = {
            "subsector_id": alloc.subsector_id,
            "allocation_id": alloc.id
        }
    
    routines_map = {}
    for routine in routines:
        routines_map[routine.employee_id] = routine.routine
    
    return {
        "allocations": allocations_map,
        "routines": routines_map
    }

@app.post("/api/smart-flow/allocations/save", response_class=JSONResponse)
async def save_allocations(
    request: Request,
    session: Session = Depends(get_session)
):
    """Salva alocações e rotinas do dia"""
    require_login(request)
    
    try:
        data = await request.json()
        date = data.get("date")
        shift = data.get("shift")
        allocations = data.get("allocations", {})  # {employee_id: subsector_id}
        routines = data.get("routines", {})  # {employee_id: routine}
        
        # 1. Limpar alocações antigas do dia/turno
        old_allocations = session.exec(
            select(models.EmployeeAllocation)
            .where(models.EmployeeAllocation.date == date)
            .where(models.EmployeeAllocation.shift == shift)
        ).all()
        
        for alloc in old_allocations:
            session.delete(alloc)
        
        # 2. Criar novas alocações
        for emp_id, subsector_id in allocations.items():
            new_alloc = models.EmployeeAllocation(
                date=date,
                shift=shift,
                employee_id=int(emp_id),
                subsector_id=subsector_id
            )
            session.add(new_alloc)
        
        # 3. Atualizar rotinas
        for emp_id, routine in routines.items():
            existing = session.exec(
                select(models.EmployeeRoutine)
                .where(models.EmployeeRoutine.date == date)
                .where(models.EmployeeRoutine.shift == shift)
                .where(models.EmployeeRoutine.employee_id == int(emp_id))
            ).first()
            
            if existing:
                existing.routine = routine
                existing.updated_at = datetime.now()
                session.add(existing)
            else:
                new_routine = models.EmployeeRoutine(
                    date=date,
                    shift=shift,
                    employee_id=int(emp_id),
                    routine=routine
                )
                session.add(new_routine)
        
        session.commit()
        
        return {"success": True, "message": "Alocações e rotinas salvas com sucesso"}
    except Exception as e:
        logger.exception("Error saving allocations")
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
                    
        # Defaults if missing
        if not sector_config or "sectors" not in sector_config:
            sector_config = {
                "sectors": [
                    { "key": "recebimento", "label": "Recebimento", "target": 0 },
                    { "key": "camara_fria", "label": "Câmara Fria", "target": 0 },
                    { "key": "selecao", "label": "Seleção", "target": 0 },
                    { "key": "expedicao", "label": "Expedição", "target": 0 }
                ]
            }
            
        SECTORS = sector_config.get("sectors", [])
        
        # 4. Build Snapshot Data
        
        # Initial State
        log = daily_op.attendance_log if daily_op and daily_op.attendance_log else {}
        tonnage = daily_op.tonnage if daily_op and daily_op.tonnage else 0.0
        
        # Prepare People List for Report
        people_list = []
        
        # We iterate over ALL active employees to show absences/vacations correctly
        # AND we check the log for specific daily statuses
        
        # Helper to get daily entry
        def get_daily_status(reg_id):
            return log.get(str(reg_id), {})
            
        total_present = 0
        
        for emp in all_employees:
            if emp.status == 'fired': continue # Skip fired for now unless in log?
            
            # Filter by Shift:
            # Include if they belong to this shift OR if they are in the log (borrowed)
            # Normalize strings for comparison just in case
            emp_shift = (emp.work_shift or "").strip().lower()
            req_shift = shift.strip().lower()
            
            is_same_shift = (emp_shift == req_shift)
            entry = get_daily_status(emp.registration_id)
            is_in_log = (str(emp.registration_id) in log)
            
            if not is_same_shift and not is_in_log:
                continue
            
            # Determine effective status for today
            daily_status = entry.get('status')
            
            if not daily_status:
                # Fallback to permanent
                if emp.status == 'active': daily_status = 'present'
                else: daily_status = emp.status # vacation, sick, away
            
            sector_key = entry.get('sector')
            
            # Count Present
            if daily_status == 'present':
                total_present += 1
                
            # Check if Substituted (Only relevant if Away/Vacation?)
            # User said: "destacar que ele ja foi subistiuido, somente com a rotina de afastado"
            # So we check if there's a "Substituído por" event for this employee
            is_substituted = False
            if daily_status in ['away', 'vacation']:
                 has_sub_evt = session.exec(select(models.Event).where(
                    models.Event.employee_id == emp.id,
                    models.Event.text.like("%Substituído por%")
                 )).first()
                 if has_sub_evt:
                     is_substituted = True

            people_list.append({
                "name": emp.name,
                "status_daily": daily_status,
                "sector_daily": sector_key,
                "is_substituted": is_substituted
            })
            
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
            total_target += target
            
            # Find people allocated to this sector
            allocated_people = [p for p in people_list if p['sector_daily'] == key]
            
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
            
        # Top KPIs
        total_gap = sum(s['gap'] for s in sectors_detailed)
        total_vacancies = sum(s['vacancies'] for s in sectors_detailed)
        
        prod_per_person = round(tonnage / total_present, 2) if total_present > 0 else 0
        present_pct = int((total_present / total_target * 100)) if total_target > 0 else 0
        
        # Detailed Counts
        daily_absent = len([p for p in people_list if p['status_daily'] == 'absent'])
        daily_sick = len([p for p in people_list if p['status_daily'] == 'sick'])
        daily_vacation = len([p for p in people_list if p['status_daily'] == 'vacation'])
        daily_away = len([p for p in people_list if p['status_daily'] == 'away'])
        
        snapshot = {
            "kpis": {
                "total_target": total_target,
                "total_allocated": total_allocated_sum,
                "total_present": total_present,
                "present_pct": present_pct,
                "total_gap": total_gap,
                "total_vacancies": total_vacancies,
                "tonnage": f"{tonnage:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "prod_per_person": f"{prod_per_person:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "count_absent": daily_absent + daily_sick, # Combine for card
                "count_vacation_away": daily_vacation + daily_away, # Combine for card
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
    except Exception:
        return HTMLResponse(content=f"<h1>Debug 500</h1><pre>{traceback.format_exc()}</pre>", status_code=500)
async def _employees_page_impl(request: Request, session: Session):
    # Auto-update statuses based on today's date
    update_vacation_statuses(session, datetime.now())
    # user = require_login(request)
    user = "debug_admin"
        # Fetch Employees
    employees = session.exec(select(models.Employee)).all()
        # Calculate Stats
    total_active = sum(1 for e in employees if e.status == "active")
        # Fetch Targets (Create defaults if not exist)
    targets = session.exec(select(models.HeadcountTarget)).all()
    if not targets:
        # Defaults
        defaults = [
            models.HeadcountTarget(shift_name="Manhã", target_value=50),
            models.HeadcountTarget(shift_name="Tarde", target_value=50),
            models.HeadcountTarget(shift_name="Noite", target_value=50)
        ]
        for d in defaults:
            session.add(d)
        session.commit()
        targets = session.exec(select(models.HeadcountTarget)).all()
    
    target_map = {t.shift_name: t.target_value for t in targets}
    total_target = sum(t.target_value for t in targets)
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
        # If there are other statuses (unlikely per current logic), they are counted in total but not specifically in shift 'active'
    for s in shifts:
        data = shift_data.get(s, {"active":0, "vacation":0, "away":0})
        active_count = data["active"]
        target = target_map.get(s, 0)
        shift_stats.append({
            "name": s,
            "count": active_count,
            "vacation": data["vacation"],
            "away": data["away"],
            "target": target,
            "vacancies": target - active_count
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
            "statuses": status_stats
        }
    })
@app.get("/employees/candidates", response_class=JSONResponse)
async def get_candidates(request: Request, status: str, session: Session = Depends(get_session)):
    require_login(request)
    # Filter by status (fired or away)
    employees = session.exec(select(models.Employee).where(models.Employee.status == status)).all()
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
    
    new_employee = models.Employee(
        name=name,
        registration_id=registration_id,
        role=role,
        work_shift=work_shift,
        cost_center=cost_center,
        admission_date=admission_dt,
        birthday=birthday_dt,
        work_days=work_days_json,
        status="active"
    )
    try:
        session.add(new_employee)
        session.flush() # Flush to get ID if needed, though we just need to commit later
        
        # Substitution Logic
        if is_substitution and replaced_employee_id:
            old_emp = session.get(models.Employee, replaced_employee_id)
            if old_emp:
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
    except Exception as e:
        print(f"Error adding employee: {e}")
    
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)
@app.get("/employees/{employee_id}", response_class=HTMLResponse)
async def read_employee(request: Request, employee_id: int, session: Session = Depends(get_session)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    employee = session.get(models.Employee, employee_id)
    if not employee:
        # Handle 404
        return RedirectResponse(url="/employees")
        
    # Stats
    today_date = datetime.now()
    
    # Calculate Tenure
    tenure_str = "-"
    if employee.admission_date:
        delta = today_date.date() - employee.admission_date.date()
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
        "faltas": absences
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

    return templates.TemplateResponse("employee_detail.html", {
        "request": request, 
        "emp": employee, 
        "events": events, 
        "user": user,
        "stats": stats,
        "tenure": tenure_str,
        "work_days_display": work_days_display
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
                
            new_event = models.Event(
                text=text_desc,
                type=event_type,
                category="pessoas",
                employee_id=emp.id,
                shift_id=None # Optionally link to current shift if known
            )
            session.add(new_event)
            emp.status = status_action
            session.add(emp)
        session.commit()
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)
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
                    
                emp = models.Employee(
                    name=str(row.get("name", "Sem Nome")).strip(),
                    registration_id=reg_id.strip(),
                    role=str(row.get("role", "Operador")).strip(),
                    work_shift=str(shift_val).strip(),
                    cost_center=str(row.get("cost_center", "Geral")).strip(),
                    admission_date=admission,
                    birthday=bday,
                    status="active"
                )
                session.add(emp)
                count += 1
                
        session.commit()
    except Exception as e:
        print(f"Import Error: {e}")
        
    return RedirectResponse(url="/employees", status_code=status.HTTP_303_SEE_OTHER)
@app.exception_handler(HTTPException)
async def auth_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_307_TEMPORARY_REDIRECT:
        return RedirectResponse(url="/login")
    raise exc

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
    
    # 1. Overview Data
    employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
    
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
        .where(col(models.Event.type).in_(['falta', 'atestado', 'advertencia']))
    ).all()
    
    # Filter events by employee_ids (shift filter)
    events = [e for e in events if e.employee_id in employee_ids]
    
    total_absences = sum(1 for e in events if e.type == 'falta')
    total_sick = sum(1 for e in events if e.type == 'atestado')
    
    # 2. Rankings (Top Offenders)
    emp_stats = {}
    for e in events:
        if e.employee_id not in emp_stats:
            emp_stats[e.employee_id] = {'falta': 0, 'atestado': 0, 'advertencia': 0, 'name': 'Unknown', 'sector': 'Unknown', 'tenure_months': 0}
        emp_stats[e.employee_id][e.type] += 1
        
    # Enlighten with Employee Data
    emp_map = {e.id: e for e in employees}
    
    ranking_data = []
    for eid, stats in emp_stats.items():
        if eid in emp_map:
            emp = emp_map[eid]
            stats['employee_id'] = eid  # For linking
            stats['name'] = emp.name
            stats['sector'] = emp.cost_center or "Geral"
            if emp.admission_date:
                delta = datetime.now() - emp.admission_date
                stats['tenure_months'] = int(delta.days / 30)
            ranking_data.append(stats)
            
    # Sorts - Only show employees with actual events
    top_absent = sorted([r for r in ranking_data if r['falta'] > 0], key=lambda x: x['falta'], reverse=True)[:10]
    top_sick = sorted([r for r in ranking_data if r['atestado'] > 0], key=lambda x: x['atestado'], reverse=True)[:10]
    
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
            stats['risk_index'] = round((stats['falta'] + stats['atestado']) / stats['headcount'], 2)
            sector_list.append(stats)
            
    sector_list.sort(key=lambda x: x['risk_index'], reverse=True)
    
    # 4. Calculate Presence Index
    # Total working days in period
    days_in_period = (end_dt - start_dt).days
    # Theoretical attendance = headcount * working days
    theoretical_attendance = total_headcount * days_in_period if total_headcount > 0 else 1
    # Actual absences (faltas + atestados)
    total_events = total_absences + total_sick
    # Presence rate = (1 - (absences / theoretical)) * 100
    presence_rate = round((1 - (total_events / theoretical_attendance)) * 100, 1) if theoretical_attendance > 0 else 100
    
    # 5. Chronic Offenders (High Operational Risk)
    # Employees with high combined falta + atestado that disrupt operations
    chronic_offenders = []
    for item in ranking_data:
        combined_events = item['falta'] + item['atestado']
        if combined_events >= 3:  # Threshold: 3+ events in period
            item['combined_events'] = combined_events
            item['risk_score'] = round((combined_events / days_in_period) * 100, 1) if days_in_period > 0 else 0
            
            # NEW: Calculate expected work days based on employee's work schedule
            emp = emp_map.get(item['employee_id'])
            if emp:
                item['expected_work_days'] = calculate_expected_work_days(
                    emp.work_days or '[]',
                    start_dt,
                    end_dt
                )
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
    chronic_offenders = chronic_offenders[:10]  # Top 10

    return templates.TemplateResponse("people_intelligence.html", {
        "request": request,
        "user": user,
        "current_shift": shift,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
        "overview": {
            "headcount": total_headcount,
            "total_absences": total_absences,
            "total_sick": total_sick,
            "avg_absence_per_emp": round(total_absences / total_headcount, 2) if total_headcount > 0 else 0,
            "presence_rate": presence_rate,
            "chronic_count": len(chronic_offenders)
        },
        "top_absent": top_absent,
        "top_sick": top_sick,
        "sectors": sector_list,
        "chronic_offenders": chronic_offenders,
        "emp_map": emp_map  # For linking to employee pages
    })

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
    
    # Reuse the same logic as main page
    employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
    
    if shift != "Todos":
        employees = [e for e in employees if e.work_shift == shift]
    
    total_headcount = len(employees)
    employee_ids = {e.id for e in employees}
    
    today = datetime.now()
    
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        except:
            start_dt = datetime(today.year, today.month, 1)
            if today.month == 12:
                end_dt = datetime(today.year + 1, 1, 1)
            else:
                end_dt = datetime(today.year, today.month + 1, 1)
    else:
        start_dt = datetime(today.year, 1, 1)
        end_dt = today
    
    events = session.exec(
        select(models.Event)
        .where(models.Event.timestamp >= start_dt)
        .where(models.Event.timestamp < end_dt)
        .where(col(models.Event.type).in_(['falta', 'atestado', 'advertencia']))
    ).all()
    
    events = [e for e in events if e.employee_id in employee_ids]
    
    total_absences = sum(1 for e in events if e.type == 'falta')
    total_sick = sum(1 for e in events if e.type == 'atestado')
    
    emp_stats = {}
    for e in events:
        if e.employee_id not in emp_stats:
            emp_stats[e.employee_id] = {'falta': 0, 'atestado': 0, 'advertencia': 0}
        emp_stats[e.employee_id][e.type] += 1
    
    emp_map = {e.id: e for e in employees}
    
    ranking_data = []
    for eid, stats in emp_stats.items():
        if eid in emp_map:
            emp = emp_map[eid]
            stats['employee_id'] = eid
            stats['name'] = emp.name
            stats['sector'] = emp.cost_center or "Geral"
            if emp.admission_date:
                delta = datetime.now() - emp.admission_date
                stats['tenure_months'] = int(delta.days / 30)
            ranking_data.append(stats)
    
    top_absent = sorted([r for r in ranking_data if r['falta'] > 0], key=lambda x: x['falta'], reverse=True)[:10]
    top_sick = sorted([r for r in ranking_data if r['atestado'] > 0], key=lambda x: x['atestado'], reverse=True)[:10]
    
    sector_stats = {}
    for item in ranking_data:
        sec = item['sector']
        if sec not in sector_stats:
            sector_stats[sec] = {'falta': 0, 'atestado': 0, 'headcount': 0}
        sector_stats[sec]['falta'] += item['falta']
        sector_stats[sec]['atestado'] += item['atestado']
    
    for emp in employees:
        sec = emp.cost_center or "Geral"
        if sec not in sector_stats:
            sector_stats[sec] = {'falta': 0, 'atestado': 0, 'headcount': 0}
        sector_stats[sec]['headcount'] += 1
    
    sector_list = []
    for sec, stats in sector_stats.items():
        if stats['headcount'] > 0:
            stats['name'] = sec
            stats['risk_index'] = round((stats['falta'] + stats['atestado']) / stats['headcount'], 2)
            sector_list.append(stats)
    
    sector_list.sort(key=lambda x: x['risk_index'], reverse=True)
    
    days_in_period = (end_dt - start_dt).days
    theoretical_attendance = total_headcount * days_in_period if total_headcount > 0 else 1
    total_events = total_absences + total_sick
    presence_rate = round((1 - (total_events / theoretical_attendance)) * 100, 1) if theoretical_attendance > 0 else 100
    
    chronic_offenders = []
    for item in ranking_data:
        combined_events = item['falta'] + item['atestado']
        if combined_events >= 3:
            item['combined_events'] = combined_events
            item['risk_score'] = round((combined_events / days_in_period) * 100, 1) if days_in_period > 0 else 0
            
            # Calculate expected work days based on employee's work schedule
            emp = emp_map.get(item['employee_id'])
            if emp:
                item['expected_work_days'] = calculate_expected_work_days(
                    emp.work_days or '[]',
                    start_dt,
                    end_dt
                )
                item['actual_work_days'] = max(0, item['expected_work_days'] - combined_events)
                item['utilization_rate'] = round(
                    (item['actual_work_days'] / item['expected_work_days']) * 100, 1
                ) if item['expected_work_days'] > 0 else 0
            else:
                item['expected_work_days'] = 0
                item['actual_work_days'] = 0
                item['utilization_rate'] = 0
            
            chronic_offenders.append(item)
    
    chronic_offenders.sort(key=lambda x: x['combined_events'], reverse=True)
    chronic_offenders = chronic_offenders[:10]
    
    return templates.TemplateResponse("people_intelligence_report.html", {
        "request": request,
        "current_shift": shift,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
        "overview": {
            "headcount": total_headcount,
            "total_absences": total_absences,
            "total_sick": total_sick,
            "avg_absence_per_emp": round(total_absences / total_headcount, 2) if total_headcount > 0 else 0,
            "presence_rate": presence_rate,
            "chronic_count": len(chronic_offenders)
        },
        "top_absent": top_absent,
        "top_sick": top_sick,
        "sectors": sector_list,
        "chronic_offenders": chronic_offenders
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
