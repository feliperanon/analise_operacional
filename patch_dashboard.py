
import os

target_file = "main.py"

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# Define the start of the function to locate it
func_start = 'async def admin_checklists_dashboard('
if func_start not in content:
    print("Function not found!")
    exit(1)

# Define the old return block we want to replace
old_block = '''    avg_resolution_hours = None
    if resolution_seconds:
        avg_resolution_hours = round(sum(resolution_seconds) / len(resolution_seconds) / 3600, 2)

    return templates.TemplateResponse(
        "admin_routine_checklists_dashboard.html",
        {
            "request": request,
            "period_days": period_days,
            "total_count": total_count,
            "critical_count": critical_count,
            "nonconforming_count": nonconforming_count,
            "avg_resolution_hours": avg_resolution_hours,
            "shift_stats": shift_stats,
            "top_items": top_items,
            "top_equipment": top_equipment
        }
    )'''

# Define the new block with ticket stats
new_block = '''    avg_resolution_hours = None
    if resolution_seconds:
        avg_resolution_hours = round(sum(resolution_seconds) / len(resolution_seconds) / 3600, 2)

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
        "avg_resolution": 0
    }
    
    # Ticket resolution (created -> closed)
    t_res_secs = []
    for t in tickets:
        if t.status == "closed" and t.closed_at:
             delta = (t.closed_at - t.created_at).total_seconds()
             if delta > 0: t_res_secs.append(delta)
    if t_res_secs:
        ticket_stats["avg_resolution"] = round(sum(t_res_secs) / len(t_res_secs) / 3600, 1)

    # Ticket top equipment
    t_eq_counter = Counter([t.equipment_code for t in tickets])
    ticket_top_eq = [{"code": k, "count": v} for k,v in t_eq_counter.most_common(10)]

    return templates.TemplateResponse(
        "admin_routine_checklists_dashboard.html",
        {
            "request": request,
            "period_days": period_days,
            "total_count": total_count,
            "critical_count": critical_count,
            "nonconforming_count": nonconforming_count,
            "avg_resolution_hours": avg_resolution_hours,
            "shift_stats": shift_stats,
            "top_items": top_items,
            "top_equipment": top_equipment,
            "ticket_stats": ticket_stats,
            "ticket_top_eq": ticket_top_eq
        }
    )'''

# Normalize line endings to avoid issues
content_norm = content.replace("\r\n", "\n")
old_block_norm = old_block.replace("\r\n", "\n")
new_block_norm = new_block.replace("\r\n", "\n")

if old_block_norm in content_norm:
    new_content = content_norm.replace(old_block_norm, new_block_norm)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Successfully patched main.py")
else:
    print("Could not find exact block match. Dumping partial content for debug:")
    start_idx = content_norm.find(func_start)
    print(content_norm[start_idx:start_idx+2000])
