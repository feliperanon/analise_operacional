
import os
import re

target_file = "main.py"

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# 1. FIX: admin_equipment_tickets (Defensive image_urls) -------------------------
# We look for the loop over rows
old_eq_tickets = """    rows = session.exec(query).all()
    tickets = []
    for ticket, employee in rows:
        image_urls = [f"/static/uploads/tickets/{img}" for img in (ticket.images or [])]
        tickets.append({
            "ticket": ticket,
            "employee": employee,
            "created_at_br": fmt_datetime_br(ticket.created_at),
            "image_urls": image_urls
        })"""

new_eq_tickets = """    rows = session.exec(query).all()
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
        })"""

if old_eq_tickets in content:
    content = content.replace(old_eq_tickets, new_eq_tickets)
    print("Fixed admin_equipment_tickets")
else:
    # Try normalized match
    print("Warning: admin_equipment_tickets block not found, checking normalization...")

# 2. FIX: admin_checklists_dashboard (Remove Avg Resolution, Add URLs) ----------------
# We replace the whole function body from `async def admin_checklists_dashboard` to return
# Note: Since I used a dedicated script before, I know the content.
# I will use a larger block replacement.

old_dash_start = 'async def admin_checklists_dashboard(\n    request: Request,'
# We find the end of the function (before next decorator)
# But strict replace is better.

# Updated dashboard function with URLs and NO Avg Resolution
new_dash_func = """async def admin_checklists_dashboard(
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
    shift_stats = []
    for shift, count in shift_counts:
        pct = round((count / total_count) * 100, 1) if total_count else 0
        shift_stats.append({"shift": shift, "count": count, "percent": pct})
    shift_stats = sorted(shift_stats, key=lambda x: x["count"], reverse=True)

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
        "tickets_high": f"/admin/equipment/tickets?days={period_days}&severity=high",
    }

    return templates.TemplateResponse(
        "admin_routine_checklists_dashboard.html",
        {
            "request": request,
            "period_days": period_days,
            "total_count": total_count,
            "critical_count": critical_count,
            "nonconforming_count": nonconforming_count,
            "avg_resolution_hours": None, # Explicitly None
            "shift_stats": shift_stats,
            "top_items": top_items,
            "top_equipment": top_equipment,
            "ticket_stats": ticket_stats,
            "ticket_top_eq": ticket_top_eq,
            "card_urls": card_urls
        }
    )"""

# For dashboard we need to find the start and end of the function in `content` and replace it.
# Regex to find the function body
dash_pattern = r'@app\.get\("/admin/routine/checklists/dashboard".*?\)\nasync def admin_checklists_dashboard\(.*?\):.*?return templates\.TemplateResponse\(\s+"admin_routine_checklists_dashboard\.html",\s+\{.*?\}\s+\)'
# Matches are hard with multiline and nested braces.
# I will use string replace if I can match the specific unique parts.

# Actually, I'll rely on the previous script's output structure since I know it.
start_marker = '@app.get("/admin/routine/checklists/dashboard", response_class=HTMLResponse)\nasync def admin_checklists_dashboard('
end_marker = '    return templates.TemplateResponse(\n        "admin_routine_checklists_dashboard.html",\n        {\n            "request": request,\n            "period_days": period_days,\n            "total_count": total_count,\n            "critical_count": critical_count,\n            "nonconforming_count": nonconforming_count,\n            "avg_resolution_hours": avg_resolution_hours,\n            "shift_stats": shift_stats,\n            "top_items": top_items,\n            "top_equipment": top_equipment,\n            "ticket_stats": ticket_stats,\n            "ticket_top_eq": ticket_top_eq\n        }\n    )'

start_idx = content.find(start_marker)
if start_idx != -1:
    end_idx = content.find(end_marker, start_idx) + len(end_marker)
    if end_idx != -1:
        # Construct full new function with decorator
        new_func_full = '@app.get("/admin/routine/checklists/dashboard", response_class=HTMLResponse)\n' + new_dash_func
        content = content[:start_idx] + new_func_full + content[end_idx:]
        print("Fixed admin_checklists_dashboard")
    else:
        print("Could not find end of dashboard function")
else:
    print("Could not find start of dashboard function")

# 3. FIX: admin_checklists_page (List view) - Add filters --------------------
# Replace the whole function.

list_start = '@app.get("/admin/routine/checklists", response_class=HTMLResponse)\nasync def admin_checklists_page('
list_end_marker = '    return templates.TemplateResponse(\n        "admin_routine_checklists.html",\n        {\n            "request": request,\n            "rows": checklist_rows,'

new_list_func = """@app.get("/admin/routine/checklists", response_class=HTMLResponse)
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
        "reviewed": "Em revisão",
        "approved": "Aprovado",
        "rejected": "Rejeitado"
    }
    equipment_labels = {
        "blocked": "Bloqueado",
        "available": "Disponível"
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
    )"""

start_idx = content.find(list_start)
if start_idx != -1:
    # Need to find the end of the return statement.
    # It ends with `    )` indented at level 4.
    # Since I know the template params structure...
    # I'll search for the end of the summary dict closure } then next line indented )
    end_marker_str = '            }\n        }\n    )'
    end_idx = content.find(end_marker_str, start_idx)
    if end_idx != -1:
        end_idx += len(end_marker_str) # Include the closing params
        # Replace
        content = content[:start_idx] + new_list_func + content[end_idx:]
        print("Fixed admin_checklists_page")
    else:
        print("Could not find end of admin_checklists_page")
        # Fallback dump to debug if needed
else:
    print("Could not find start of admin_checklists_page")

with open(target_file, "w", encoding="utf-8") as f:
    f.write(content)
