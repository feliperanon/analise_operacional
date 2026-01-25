
import os

target_file = "main.py"

with open(target_file, "r", encoding="utf-8") as f:
    content = f.read()

# Fix admin_equipment_tickets stats calculation
# Old logic:
#    now_7d = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=7)
#    recent_count = len([t for t in tickets if t["ticket"].created_at >= now_7d])

# We need to replace the logic block.
# Finding context...

old_kpi_block = """    # KPI Stats
    total_count = len(tickets)
    open_count = len([t for t in tickets if t["ticket"].status == "open"])
    high_count = len([t for t in tickets if t["ticket"].severity == "high" and t["ticket"].status == "open"])
    
    now_7d = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=7)
    recent_count = len([t for t in tickets if t["ticket"].created_at >= now_7d])"""

new_kpi_block = """    # KPI Stats
    total_count = len(tickets)
    open_count = len([t for t in tickets if t["ticket"].status == "open"])
    high_count = len([t for t in tickets if t["ticket"].severity == "high" and t["ticket"].status == "open"])
    
    now_7d = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=7)
    # Fix TZ: Make comparison robust (ignoring TZ for count or ensuring both aligned)
    # Simplify: convert both to naive or aware.
    now_7d_naive = now_7d.replace(tzinfo=None)
    
    recent_count = 0
    for t in tickets:
        dt = t["ticket"].created_at
        if dt:
            # If naive, compare with naive. If aware, compare with aware?
            # Safest is to strip TZ for this "recent" check as 7 days is rough.
            dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
            if dt_naive >= now_7d_naive:
                recent_count += 1"""

if old_kpi_block in content:
    content = content.replace(old_kpi_block, new_kpi_block)
    print("Fixed admin_equipment_tickets TZ issue")
else:
    # Try normalized match (remove indent) if needed, or find subset
    # Let's try to match specifically the line `recent_count = ...`
    print("Could not match exact KPI block. Trying simpler replacement...")
    
    line_to_replace = '    recent_count = len([t for t in tickets if t["ticket"].created_at >= now_7d])'
    
    replacement_lines = """    # TZ SAFE FIX
    recent_count = 0
    now_7d_naive = now_7d.replace(tzinfo=None)
    for t in tickets:
        dt = t["ticket"].created_at
        if dt and (dt.replace(tzinfo=None) if dt.tzinfo else dt) >= now_7d_naive:
            recent_count += 1"""
    
    if line_to_replace in content:
        content = content.replace(line_to_replace, replacement_lines)
        print("Fixed admin_equipment_tickets TZ issue (Line Method)")
    else:
        print("Could not find recent_count line.")

with open(target_file, "w", encoding="utf-8") as f:
    f.write(content)
