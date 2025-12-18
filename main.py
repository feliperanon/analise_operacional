from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
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

# --- Flow Logic ---
def get_sector_from_cc(cost_center):
    cc = (cost_center or "").upper()
    if any(x in cc for x in ["RECEBIMENTO", "DESC", "CONF"]): return "Recebimento"
    if any(x in cc for x in ["CAMARA", "FRIO", "RESFRIADO"]): return "Câmara Fria"
    if any(x in cc for x in ["SELECAO", "CLASSIFICACAO"]): return "Seleção"
    if any(x in cc for x in ["BLOCADO", "QUEBRA"]): return "Blocado"
    if any(x in cc for x in ["EMBANDEJAMENTO", "EMB"]): return "Embandejamento"
    if any(x in cc for x in ["ESTOQUE", "CONTROLE", "INV"]): return "Estoque"
    if any(x in cc for x in ["EXPEDICAO", "EXP", "CARGA"]): return "Expedição"
    return "Outros" # Fallback or maybe pool

@app.get("/flow", response_class=HTMLResponse)
async def flow_dashboard(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    employees = session.exec(select(models.Employee).where(models.Employee.status == "active")).all()
    
    # Init Sector Data
    sectors = {
        "Recebimento": {"count": 0, "people": [], "status": "ok", "target": 10},
        "Câmara Fria": {"count": 0, "people": [], "status": "warning", "target": 5},
        "Seleção": {"count": 0, "people": [], "status": "ok", "target": 15},
        "Blocado": {"count": 0, "people": [], "status": "critical", "target": 8},
        "Embandejamento": {"count": 0, "people": [], "status": "ok", "target": 12},
        "Estoque": {"count": 0, "people": [], "status": "ok", "target": 4},
        "Expedição": {"count": 0, "people": [], "status": "ok", "target": 20},
    }
    
    # Populate Sectors
    for emp in employees:
        sec = get_sector_from_cc(emp.cost_center)
        if sec in sectors:
            sectors[sec]["count"] += 1
            sectors[sec]["people"].append(emp)
    
    # Simple Status Logic (Mock for now)
    for name, data in sectors.items():
        if data["count"] < data["target"] * 0.8:
            data["status"] = "critical"
        elif data["count"] < data["target"]:
            data["status"] = "warning"
        else:
            data["status"] = "ok"

    return templates.TemplateResponse("flow.html", {
        "request": request,
        "user": user,
        "sectors": sectors
    })

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

    # Helper to determine shift from cost center
    def get_shift_from_cc(cost_center):
        cc = (cost_center or "").upper()
        if "NOITE" in cc: return "Noite"
        if "TARDE" in cc: return "Tarde"
        return "Manhã" # Default

    total_real_active = 0

    for e in employees:
        if e.status == "fired":
            continue
            
        # Count towards total if not fired
        total_real_active += 1
        
        # Determine shift
        s_name = get_shift_from_cc(e.cost_center)
        
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
        # Use header=1 because the first row (0) is a title "QUADRO DE EXPEDIÇÃO NL"
        df = pd.read_excel(io.BytesIO(content), header=1)
        
        # Map Portuguese headers
        column_map = {
            "Matrícula": "registration_id",
            "Colaborador": "name", 
            "Nome": "name",
            "Data Admissão": "admission_date",
            "Admissão": "admission_date",
            "Data Nascimento": "birthday",
            "Nascimento": "birthday",
            "Centro de Custo": "cost_center",
            "Cargo": "role",
            "Função": "role",
            "Turno": "work_shift"
        }
        df = df.rename(columns=column_map)
        
        count = 0 
        for _, row in df.iterrows():
            # Validation
            reg_id = str(row.get("registration_id", ""))
            if not reg_id or reg_id.lower() == "nan":
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
                shift_val = row.get("work_shift", "Manhã")
                if pd.isna(shift_val): shift_val = "Manhã"

                emp = models.Employee(
                    name=str(row.get("name", "Sem Nome")),
                    registration_id=reg_id,
                    role=str(row.get("role", "Operador")),
                    work_shift=str(shift_val),
                    cost_center=str(row.get("cost_center", "Geral")),
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
