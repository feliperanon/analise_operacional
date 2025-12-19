from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session
from database import create_db_and_tables, get_session
import models

# --- Config ---
SECRET_KEY = "your-secret-key-change-in-production"
ALLOWED_USER = "feliperanon"
ALLOWED_PASS = "571232ce"



# API Models
from pydantic import BaseModel
from typing import Optional

class DailyRoutineUpdate(BaseModel):
    date: str
    shift: str
    attendance_log: Optional[dict] = {}
    tonnage: Optional[int] = None
    arrival_time: Optional[str] = None
    exit_time: Optional[str] = None
    report: Optional[str] = None
    rating: Optional[int] = 0
    rating: Optional[int] = 0
    status: Optional[str] = None
    sector_config: Optional[dict] = None

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

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "message": "Operação Inteligente - Sistema Iniciado",
        "user": user
    })



# --- Smart Flow Routes ---

@app.get("/smart-flow", response_class=HTMLResponse)
async def smart_flow_page(request: Request, shift: str = "Manhã", session: Session = Depends(get_session)):
    user = require_login(request)
    
    # Get Daily Op
    today_str = datetime.now().strftime("%Y-%m-%d")
    daily_op = session.exec(
        select(models.DailyOperation)
        .where(models.DailyOperation.date == today_str)
        .where(models.DailyOperation.shift == shift)
    ).first()
    
    if not daily_op:
        daily_op = models.DailyOperation(date=today_str, shift=shift) # Transient
        
    # Get Employees for "Available Pool"
    employees = session.exec(select(models.Employee).where(models.Employee.status == "active")).all()
    
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

    return templates.TemplateResponse("smart_flow.html", {
        "request": request,
        "user": user,
        "daily_op": daily_op,
        "employees_list": employees,
        "current_shift": shift,
        "total_target": sectors_total_demand, 
        "shift_target_hr": shift_target_hr, # Passed for KPI
        "sector_config": sector_config 
    })

    return templates.TemplateResponse("smart_flow.html", {
        "request": request,
        "user": user,
        "daily_op": daily_op,
        "employees_list": employees,
        "current_shift": shift,
        "total_target": total_target,
        "sector_targets": sector_targets 
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
                
                if target_status:
                    employee = session.exec(select(models.Employee).where(models.Employee.registration_id == emp_id)).first()
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
                            event_type = "advertencia" # Using 'away' button as Advertencia placeholder for now based on user context, or just 'afastado'
                            event_text = f"Afastamento registrado em {data.date}"
                            
                        # If 'absent' is not a persistent status on Employee model usually (it resets daily), 
                        # we might need to handle it differently, BUT if we are updating the employee status to 'absent' (which doesn't exist in the model enum usually? let's check),
                        # Wait, the Employee model status enum is: active, vacation, away, fired. 
                        # 'absent' and 'sick' might be daily statuses not persistent? 
                        # Let's check model.
                        
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
    user = require_login(request)
    
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

@app.get("/employees/{emp_id}", response_class=HTMLResponse)
async def get_employee_details(request: Request, emp_id: int, session: Session = Depends(get_session)):
    try:
        require_login(request)
        emp = session.get(models.Employee, emp_id)
        if not emp:
            raise HTTPException(status_code=404, detail="Colaborador não encontrado")
        
        # Fetch events sorted by date desc
        stmt = select(models.Event).where(models.Event.employee_id == emp_id).order_by(models.Event.timestamp.desc())
        events = session.exec(stmt).all()
        
        # Calculate stats
        stats = {
            "faltas": sum(1 for e in events if e.type == "falta"),
            "atestados": sum(1 for e in events if e.type == "atestado"),
            "advertencias": sum(1 for e in events if e.type == "advertencia"),
            "ferias": sum(1 for e in events if e.type == "ferias_hist"), 
        }
        
        return templates.TemplateResponse("employee_detail.html", {
            "request": request,
            "emp": emp,
            "events": events,
            "stats": stats
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<h1>Erro no Servidor</h1><pre>{traceback.format_exc()}</pre>", status_code=500)

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
