
import os
import re

target_file = "main.py"

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# 1. ADD /mobile/routine/history ROUTE
# Can be added after `mobile_checklist_page`.

mobile_history_route = """
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
    
    checklists = session.exec(
        select(models.TranspalletChecklist)
        .where(models.TranspalletChecklist.employee_id == employee_id)
        .where(models.TranspalletChecklist.date >= history_start)
        # .where(models.TranspalletChecklist.date < today) # Maybe show today's too if already done? 
        # Usually history implies past, but let's show all latest.
        .order_by(models.TranspalletChecklist.submitted_at.desc())
    ).all()
    
    history_view = []
    for c in checklists:
        is_fail = c.critical_flag or c.nonconforming_keys
        history_view.append({
            "equipment_code": c.equipment_code,
            "submitted_at_date": c.submitted_at.strftime("%d/%m") if c.submitted_at else "-",
            "submitted_at_time": c.submitted_at.strftime("%H:%M") if c.submitted_at else "-",
            "status_dot": "bg-red-500" if is_fail else "bg-emerald-500",
            "status_badge_class": "text-red-400 bg-red-500/10" if c.critical_flag else ("text-amber-400 bg-amber-500/10" if c.nonconforming_keys else "text-emerald-400 bg-emerald-500/10"),
            "status_label": "Falha" if c.critical_flag else ("Atenção" if c.nonconforming_keys else "OK"),
            "original": c
        })
        
    return templates.TemplateResponse("mobile/routine_history.html", {
        "request": request,
        "employee": employee,
        "history_checklists": history_view
    })
"""

# Insert before `mobile_checklist_page` (search for definition)
search_str = 'async def mobile_checklist_page(request: Request, session: Session = Depends(get_session)):'
decorator_str = '@app.get("/mobile/routine/checklist", response_class=HTMLResponse)'

if decorator_str in content:
    content = content.replace(decorator_str, mobile_history_route + "\n" + decorator_str)
    print("Added mobile_checklist_history route")
else:
    print("Could not find mobile_checklist_page decorator")

# 2. MODIFY mobile_checklist_page TO REMOVE HISTORY/TICKETS FETCH
# We need to strip the logic blocks 2 and 3.

# Remove Block 2
block2_start = '    # 2. Histórico (Últimos 7 dias, excluindo hoje)'
block2_end = '    # 3. Chamados Abertos (Últimos 30 dias para não poluir)' # Assuming this follows

# Logic to remove lines between start and end is tricky with simple replace if variable names change.
# But looking at previous view, we can identify them.

# We will replace the whole function body again to be clean.
# Actually, replacing large blocks is risky if indentation differs.
# Let's verify the content structure.
# The previous view showed lines 4036 to ~4220.

new_mobile_page_func = """@app.get("/mobile/routine/checklist", response_class=HTMLResponse)
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
            "status_label": "Falha" if c.critical_flag else ("Atenção" if c.nonconforming_keys else "OK"),
            "original": c
        })

    # 4. Alertas de Dias Pendentes (Missing Days)
    # Regra: Work Days - Absences - Done Days
    missing_days = []
    
    # Janela de análise: Últimos 14 dias até ontem
    analysis_end = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)).date()
    analysis_start = analysis_end - timedelta(days=13) # 14 dias total
    
    # Buscar Checklists feitos no período
    done_dates = set(session.exec(
        select(models.TranspalletChecklist.date)
        .where(models.TranspalletChecklist.employee_id == employee_id)
        .where(models.TranspalletChecklist.date >= analysis_start.strftime("%Y-%m-%d"))
        .where(models.TranspalletChecklist.date <= analysis_end.strftime("%Y-%m-%d"))
    ).all())
    
    # Buscar Ausências (EmployeeRoutine != present)
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
            # E não tiver ausência registrada...
            if d_str not in absence_map:
                # E não tiver checklist feito...
                if d_str not in done_dates:
                    # ENTÃO é pendente
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
        "Tuesday": "Terça-feira",
        "Wednesday": "Quarta-feira",
        "Thursday": "Quinta-feira",
        "Friday": "Sexta-feira",
        "Saturday": "Sábado",
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
    
    # 5. Equipment List for standardized input
    equipment_list = session.exec(select(models.TranspalletEquipment).order_by(models.TranspalletEquipment.code)).all()

    return templates.TemplateResponse(
        "mobile/routine_checklist.html",
        {
            "equipment_list": equipment_list,
            "request": request,
            "employee": employee,
            "items": CHECKLIST_ITEMS,
            "today": today,
            "checklists": checklists_view,
            "missing_days": missing_days_view
        }
    )
"""

# Current func has start @ 4036 and end around 4220.
# We will identify by start marker and end marker.

start_marker = '@app.get("/mobile/routine/checklist", response_class=HTMLResponse)\nasync def mobile_checklist_page(request: Request, session: Session = Depends(get_session)):'
end_marker_str = '            "missing_days": missing_days_view\n        }\n    )'
# The current file likely has duplicate `request, employee...` lines due to my previous manual fix in replacement.
# But since I am replacing the whole function it should be fine.

# I will assume `start_marker` is unique and `end_marker_str` is unique enough (or I can find next function).

next_func_marker = '@app.get("/mobile/equipment/tickets", response_class=HTMLResponse)'

start_idx = content.find(start_marker)
if start_idx != -1:
    end_idx = content.find(next_func_marker, start_idx)
    if end_idx != -1:
        # Cut earlier to account for newlines
        # The new function includes the decorator.
        content = content[:start_idx] + new_mobile_page_func + "\n\n" + content[end_idx:]
        print("Replaced mobile_checklist_page")
    else:
        print("Could not find next function marker")
else:
    print("Could not find mobile_checklist_page start")

with open(target_file, "w", encoding="utf-8") as f:
    f.write(content)
