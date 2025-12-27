from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timedelta
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select
from database import create_db_and_tables, get_session
import models

# --- Config ---
SECRET_KEY = "your-secret-key-change-in-production"
ALLOWED_USER = "feliperanon"
ALLOWED_PASS = "571232ce"



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

    # 1. Fetch DailyOperation for Allocation Data
    daily_op = session.exec(
        select(models.DailyOperation)
        .where(models.DailyOperation.date == date)
        .where(models.DailyOperation.shift == shift)
    ).first()
    
    # 2. Filter Employees (Sector == Expedicao)
    all_employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
    emp_map_reg = {e.registration_id: e for e in all_employees}
    emp_map_id = {e.id: e for e in all_employees}
    
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

    # 4. Fetch Routes (Separação)
    db_routes = session.exec(
        select(models.Route)
        .where(models.Route.date == date)
        .where(models.Route.shift == shift)
        .order_by(models.Route.start_time)
    ).all()
    
    # 5. Enrich & Calculate Productivity
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

    for r in db_routes:
        prod = calc_productivity(r.start_time, r.end_time, r.tonnage)
        
        def fmt_num(n):
            val = n if n is not None else 0.0
            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
        def calc_duration_str(start, end):
            if not start or not end: return None
            try:
                s = datetime.strptime(start, "%H:%M")
                e = datetime.strptime(end, "%H:%M")
                diff = (e - s).total_seconds()
                if diff < 0: return None # Ignore negative/overflow for now
                
                hours = int(diff // 3600)
                mins = int((diff % 3600) // 60)
                return f"{hours:02d}h {mins:02d}m"
            except:
                return None

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
async def read_root(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    # --- Dashboard Data Logic ---
    today = datetime.now()
    next_30 = today + timedelta(days=30)
    
    employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
    
    vacations_soon = []
    birthdays_month = []
    probation_risks = []
    work_anniversaries = []
    
    current_month = today.month
    
    for emp in employees:
        # 1. Upcoming Vacations (Next 30 days)
        if emp.vacation_start:
             # Check if starts in [today, next_30]
             if today <= emp.vacation_start <= next_30:
                 vacations_soon.append({
                     "id": emp.id,
                     "name": emp.name,
                     "shift": emp.work_shift,
                     "start": emp.vacation_start.strftime("%d/%m"),
                     "end": emp.vacation_end.strftime("%d/%m") if emp.vacation_end else "?"
                 })
    
        # 2. Birthdays (Current Month)
        if emp.birthday:
            if emp.birthday.month == current_month:
                birthdays_month.append({
                    "id": emp.id,
                    "name": emp.name,
                    "shift": emp.work_shift,
                    "day": emp.birthday.day,
                    "date_str": emp.birthday.strftime("%d/%m")
                })
        
        # 3. Probation Expiration (45 or 90 days)
        if emp.admission_date:
            d45 = emp.admission_date + timedelta(days=45)
            d90 = emp.admission_date + timedelta(days=90)
            
            # Check if d45 is in next 30 days
            if today <= d45 <= next_30:
                probation_risks.append({
                    "id": emp.id,
                    "name": emp.name,
                    "shift": emp.work_shift,
                    "type": "45 dias",
                    "date": d45.strftime("%d/%m")
                })
            
            # Check if d90 is in next 30 days
            if today <= d90 <= next_30:
                probation_risks.append({
                    "id": emp.id,
                    "name": emp.name,
                    "shift": emp.work_shift,
                    "type": "90 dias",
                    "date": d90.strftime("%d/%m")
                })
                
            # 4. Work Anniversary (Current Month)
            # Only if not admitted this year (must have at least 1 year)
            if emp.admission_date.month == current_month and emp.admission_date.year < today.year:
                years = today.year - emp.admission_date.year
                work_anniversaries.append({
                    "id": emp.id,
                    "name": emp.name,
                    "shift": emp.work_shift,
                    "years": years,
                    "date_str": emp.admission_date.strftime("%d/%m"),
                    "day": emp.admission_date.day
                })

    # Sort lists
    vacations_soon.sort(key=lambda x: datetime.strptime(x['start'], "%d/%m").replace(year=today.year))
    birthdays_month.sort(key=lambda x: x['day'])
    probation_risks.sort(key=lambda x: datetime.strptime(x['date'], "%d/%m").replace(year=today.year))
    work_anniversaries.sort(key=lambda x: x['day'])

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "message": "Operação Inteligente - Sistema Iniciado",
        "user": user,
        "vacations_soon": vacations_soon,
        "birthdays_month": birthdays_month,
        "probation_risks": probation_risks,
        "work_anniversaries": work_anniversaries
    })



# --- Smart Flow Routes ---

@app.get("/smart-flow", response_class=HTMLResponse)
async def smart_flow_page(request: Request, shift: str = "Manhã", date: Optional[str] = None, session: Session = Depends(get_session)):
    user = require_login(request)
    
    # Get Employees for "Available Pool" (Active, Sick, Vacation, Away - Everyone except Fired)
    
    # Auto-Update Vacation Status Check
    
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
    
    if sector_config_db and sector_config_db.config_json:
        sector_config = sector_config_db.config_json
    else:
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
    sectors_total_demand = sum(s.get("target", 0) for s in sector_config.get("sectors", []))

    # Calculate Real Tonnage from Routes
    routes_in_shift = session.exec(
        select(models.Route)
        .where(models.Route.date == date)
        .where(models.Route.shift == shift)
    ).all()
    total_tonnage_real = sum(r.tonnage for r in routes_in_shift if r.tonnage)

    # Format Tonnage
    def fmt_num(n):
        val = n if n is not None else 0.0
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

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
        "total_tonnage_fmt": fmt_num(total_tonnage_real)
    })

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
        
        # Create History Event
        hist_event = models.Event(
            employee_id=emp.id,
            type="ferias_hist",
            text=f"Férias Agendadas: {data.start_date} a {data.end_date}",
            category="pessoas",
            sector=emp.cost_center or "Geral",
            timestamp=datetime.now()
        )
        session.add(hist_event)
        
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
            continue
            
    session.commit()
    return JSONResponse({
        "message": f"{updated_count} colaboradores atualizados.",
        "errors": errors
    })



@app.post("/routine/update", response_class=JSONResponse)
async def update_routine(
    request: Request,
    data: DailyRoutineUpdate,
    session: Session = Depends(get_session)
):
    require_login(request)
    try:
        # Find or Create
        daily = session.exec(
            select(models.DailyOperation)
            .where(models.DailyOperation.date == data.date)
            .where(models.DailyOperation.shift == data.shift)
        ).first()
        
        old_log = {}
        if not daily:
            daily = models.DailyOperation(date=data.date, shift=data.shift)
        else:
            old_log = daily.attendance_log or {}
            
        # Update fields
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
            
        daily.updated_at = datetime.now()
        
        # --- Timeline Logic ---
        if data.attendance_log:
            new_log = data.attendance_log
            
            # SYNC: Update Employee Status based on attendance log
            for emp_id, entry in new_log.items():
                status = entry.get("status")
                target_status = None
                
                # Retrieve Employee
                employee = session.exec(select(models.Employee).where(models.Employee.registration_id == emp_id)).first()
                if not employee: continue

                # Event generation for DAILY statuses (Persistent or Not)
                # 'absent' (Falta) is usually a daily thing, might not change GLOBAL employee status?
                # 'sick' (Atestado) might be short term.
                
                # Check if this precise daily entry is NEW or CHANGED from old logs to avoid duplicates on every save?
                # Ideally we check against the DB or simple logic: if status is provided and different?
                # For simplicity, we trust the 'status' field.
                
                # Event Logic for STATS
                if status == 'absent':
                     # Check if we already logged a 'falta' for this employee TODAY to avoid duplicates
                     today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                     existing_falta = session.exec(
                         select(models.Event)
                         .where(models.Event.employee_id == employee.id)
                         .where(models.Event.type == 'falta')
                         .where(models.Event.timestamp >= today_start)
                     ).first()
                     
                     if not existing_falta:
                         evt = models.Event(
                            employee_id=employee.id,
                            type="falta",
                            text=f"Falta registrada em {data.date}",
                            timestamp=datetime.now(),
                            category="pessoas",
                            sector="RH"
                         )
                         session.add(evt)
                     
                target_status = None
                if status == 'vacation': target_status = 'vacation' 
                elif status == 'sick': target_status = 'sick'       
                elif status == 'away': target_status = 'away'
                elif status == 'present': target_status = 'active' # Logic for return

                if target_status:
                    employee = session.exec(select(models.Employee).where(models.Employee.registration_id == emp_id)).first()
                    # Only update if changed
                    if employee and employee.status != target_status:
                        # Log Event for Status Change
                        event_type = None
                        event_text = None
                        
                        if target_status == 'sick':
                            event_type = "atestado"
                            event_text = f"Atestado registrado em {data.date}"
                        elif target_status == 'vacation':
                            event_type = "ferias_hist"
                            event_text = f"Início de férias em {data.date}"
                        elif target_status == 'away':
                            event_type = "advertencia" 
                            event_text = f"Afastamento registrado em {data.date}"
                        elif target_status == 'active':
                            if employee.status == 'vacation':
                                event_type = "retorno_ferias"
                                event_text = f"Retorno de Férias em {data.date}"
                            elif employee.status == 'sick':
                                event_type = "retorno_atestado"
                                event_text = f"Retorno de Atestado em {data.date}"
                            else:
                                event_type = "retorno"
                                event_text = f"Retorno à atividade em {data.date}"
                        
                        employee.status = target_status
                        session.add(employee)
                        
                        if event_type:
                            evt = models.Event(
                                employee_id=employee.id,
                                type=event_type,
                                text=event_text,
                                timestamp=datetime.now(),
                                category="pessoas",
                                sector="RH"
                            )
                            session.add(evt)
            
            # Detect Changes
            all_ids = set(old_log.keys()) | set(new_log.keys())
            
            for reg_id in all_ids:
                old_entry = old_log.get(reg_id)
                new_entry = new_log.get(reg_id)
                
                # Fetch Employee PK
                emp_obj = session.exec(select(models.Employee).where(models.Employee.registration_id == reg_id)).first()
                if not emp_obj:
                    continue # Should not happen if data is consistent
                
                real_emp_id = emp_obj.id

                # Case 1: New Allocation (Was not in log, now is)
                if not old_entry and new_entry:
                    sector = new_entry.get('sector')
                    sub = new_entry.get('subsector', 'Geral')
                    event = models.Event(
                        employee_id=real_emp_id,
                        type="allocacao",
                        text=f"Alocado em {sector} ({sub}) - {data.shift}",
                        timestamp=datetime.now(),
                        category="processo",
                        sector=sector
                    )
                    session.add(event)
                    
                # Case 2: Changed Allocation (Moved Sector/Subsector)
                elif old_entry and new_entry:
                    old_sec = old_entry.get('sector')
                    old_sub = old_entry.get('subsector', 'Geral')
                    new_sec = new_entry.get('sector')
                    new_sub = new_entry.get('subsector', 'Geral')
                    
                    if old_sec != new_sec or old_sub != new_sub:
                        event = models.Event(
                            employee_id=real_emp_id,
                            type="movimentacao",
                            text=f"Movido de {old_sec} ({old_sub}) para {new_sec} ({new_sub})",
                            timestamp=datetime.now(),
                            category="processo",
                            sector=new_sec
                        )
                        session.add(event)
                        
                # Case 3: Removed
                elif old_entry and not new_entry:
                    event = models.Event(
                        employee_id=real_emp_id,
                        type="remocao",
                        text=f"Removido do fluxo operacional ({data.shift})",
                        timestamp=datetime.now(),
                        category="processo",
                        sector="Geral"
                    )
                    session.add(event)

        if data.sector_config:
            # Save Sector Config
            config_entry = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == data.shift)).first()
            if not config_entry:
                config_entry = models.SectorConfiguration(shift_name=data.shift, config_json=data.sector_config)
            else:
                config_entry.config_json = data.sector_config
                config_entry.updated_at = datetime.now()
            session.add(config_entry)
            
        session.add(daily)
        session.commit()
        
        return {"status": "success", "id": daily.id}
    except Exception as e:
        print(f"Update error: {e}")
        return JSONResponse(content={"status": "error", "msg": str(e)}, status_code=500)

# --- Employee Routes ---
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
        "employees": employees,
        "stats": {
            "total_active": total_real_active,
            "total_target": total_target,
            "vacancies": total_target - total_real_active,
            "shifts": shift_stats,
            "statuses": status_stats
        }
    })

    return templates.TemplateResponse("employees.html", {
        "request": request,
        "user": user,
        "employees": employees,
        "stats": {
            "total_active": total_active,
            "total_target": total_target,
            "vacancies": total_target - total_active,
            "shifts": shift_stats,
            "statuses": status_stats
        }
    })

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

    new_employee = models.Employee(
        name=name,
        registration_id=registration_id,
        role=role,
        work_shift=work_shift,
        cost_center=cost_center,
        admission_date=admission_dt,
        birthday=birthday_dt,
        status="active"
    )
    try:
        session.add(new_employee)
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
        delta = today_date.date() - employee.admission_date
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

    return templates.TemplateResponse("employee_detail.html", {
        "request": request, 
        "emp": employee, 
        "events": events, 
        "user": user,
        "stats": stats,
        "tenure": tenure_str
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
