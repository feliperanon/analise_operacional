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
    for s in shifts:
        count = sum(1 for e in employees if e.status == "active" and e.work_shift == s)
        target = target_map.get(s, 0)
        shift_stats.append({
            "name": s,
            "count": count,
            "target": target,
            "vacancies": target - count
        })

    return templates.TemplateResponse("employees.html", {
        "request": request,
        "user": user,
        "employees": employees,
        "stats": {
            "total_active": total_active,
            "total_target": total_target,
            "vacancies": total_target - total_active,
            "shifts": shift_stats
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
