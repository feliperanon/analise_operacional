
import os
import re

target_file = "main.py"

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update mobile_checklist_page to include equipment_list
# We look for:
#     today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
#     
#     # 1. Checklists do Dia (Mantido)
# .And insert equipment fetch before return.

# Find the end of data gathering and before return
mobile_chk_search = '    return templates.TemplateResponse(\n        "mobile/routine_checklist.html",'
mobile_chk_replacement = """    
    # 5. Equipment List for standardized input
    equipment_list = session.exec(select(models.TranspalletEquipment).order_by(models.TranspalletEquipment.code)).all()

    return templates.TemplateResponse(
        "mobile/routine_checklist.html",
        {
            "equipment_list": equipment_list,"""

if mobile_chk_search in content:
    content = content.replace(mobile_chk_search, mobile_chk_replacement)
    print("Updated mobile_checklist_page with equipment_list")
else:
    print("WARNING: Could not update mobile_checklist_page (search string not found)")


# 2. Add Mobile Tickets Routes
# We can add these after `mobile_ticket_new` (searched for `@app.get("/mobile/equipment/tickets/new"`)
mobile_ticket_new_marker = '@app.get("/mobile/equipment/tickets/new", response_class=HTMLResponse)'

new_routes_code = """
@app.get("/mobile/equipment/tickets", response_class=HTMLResponse)
async def mobile_tickets_list(request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
    employee = session.get(models.Employee, user.get("id"))
    try:
        require_mobile_module(employee, "checklist")
    except HTTPException:
        return RedirectResponse(url="/mobile/dashboard", status_code=303)

    tickets = session.exec(
        select(models.EquipmentTicket)
        .where(models.EquipmentTicket.employee_id == employee.id)
        .order_by(desc(models.EquipmentTicket.created_at))
        .limit(50)
    ).all()

    return templates.TemplateResponse("mobile/tickets_list.html", {
        "request": request, 
        "tickets": tickets,
        "employee": employee
    })

@app.get("/mobile/equipment/tickets/{ticket_id}", response_class=HTMLResponse)
async def mobile_tickets_detail(ticket_id: int, request: Request, session: Session = Depends(get_session)):
    user = require_login(request)
    if not isinstance(user, dict) or user.get("type") != "employee":
        return RedirectResponse(url="/mobile/login", status_code=303)
    
    ticket = session.get(models.EquipmentTicket, ticket_id)
    if not ticket or ticket.employee_id != user.get("id"):
        return RedirectResponse(url="/mobile/equipment/tickets", status_code=303)
        
    image_list = ticket.images or []
    image_list = [f"/static/uploads/tickets/{img}" for img in image_list]

    return templates.TemplateResponse("mobile/tickets_detail.html", {
        "request": request, 
        "ticket": ticket,
        "images": image_list
    })

"""

if mobile_ticket_new_marker in content:
    # Insert *before* the new ticket route to keep them grouped or after? 
    # Let's insert before to keep mobile routes together logic.
    content = content.replace(mobile_ticket_new_marker, new_routes_code + "\n" + mobile_ticket_new_marker)
    print("Added Mobile Tickets Routes")
else:
    print("WARNING: Could not find mobile_ticket_new_marker")

# 3. Update api_create_ticket with Duplicate Check
# Search for:
#     if not description:
#         return JSONResponse({"error": "Descrição obrigatória."}, status_code=400)
# Insert check there.

duplicate_check_marker = '    if not description:\n        return JSONResponse({"error": "Descrição obrigatória."}, status_code=400)'

duplicate_logic = """
    # Check for duplicates (Same equipment, same day, status open)
    today_start = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(hour=0, minute=0, second=0, microsecond=0)
    existing = session.exec(
        select(models.EquipmentTicket)
        .where(models.EquipmentTicket.equipment_code == equipment_code)
        .where(models.EquipmentTicket.status == "open")
        .where(models.EquipmentTicket.created_at >= today_start)
    ).first()
    
    if existing:
        return JSONResponse({
            "error": f"Já existe um chamado ABERTO hoje para o equipamento {equipment_code}. Consulte o chamado #{existing.id} antes de abrir outro.",
            "existing_ticket_id": existing.id,
            "success": False
        }, status_code=409)
"""

if duplicate_check_marker in content:
    content = content.replace(duplicate_check_marker, duplicate_check_marker + "\n" + duplicate_logic)
    print("Added Duplicate Check logic")
else:
    print("WARNING: Could not find duplicate_check_marker")

# 4. Remove Average Resolution from Dashboard backend
# Previous turn removed it from template, but logic might still be there.
# Search for: "ticket_stats['avg_resolution'] ="
# and comment it out or ensure it's removed.
# Actually I replaced the whole function in previous turn (v1468) setting "avg_resolution": 0 explicitly.
# So I just need to verify it is indeed gone or set to None/0.
# The user asked to "Remove definitively".
# I'll check if I can remove the entire calculation block related to resolution if present.

with open(target_file, "w", encoding="utf-8") as f:
    f.write(content)
