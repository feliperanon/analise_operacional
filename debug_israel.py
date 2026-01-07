from sqlmodel import Session, select
from database import engine
from models import Employee, Route
from datetime import datetime

with Session(engine) as session:
    # Find Israel
    emp = session.exec(select(Employee).where(Employee.name.like('%ISRAEL RODRIGUES%'))).first()
    
    with open("israel_routes.txt", "w", encoding="utf-8") as f:
        if emp:
            f.write(f"Name: {emp.name}\n")
            f.write(f"Schedule: {emp.work_schedule}\n")
            
            today = datetime.now().strftime('%Y-%m-%d')
            routes = session.exec(select(Route).where(Route.employee_id == emp.id).where(Route.date == today)).all()
            
            f.write("\nRoutes:\n")
            total_dur = 0
            intervals = []
            
            for r in routes:
                f.write(f"- {r.start_time} to {r.end_time} | {r.tonnage}kg\n")
                if r.start_time and r.end_time:
                    try:
                        s = datetime.strptime(r.start_time, "%H:%M")
                        e = datetime.strptime(r.end_time, "%H:%M")
                        dur = (e - s).total_seconds() / 3600
                        total_dur += dur
                        intervals.append((s, e))
                    except:
                        pass
            
            f.write(f"\nSummed Duration: {total_dur:.2f}h\n")
            
            # Merge Intervals Check
            intervals.sort()
            merged = []
            for start, end in intervals:
                if not merged or start > merged[-1][1]:
                    merged.append([start, end])
                else:
                    merged[-1][1] = max(merged[-1][1], end)
            
            real_dur = sum((e - s).total_seconds() for s, e in merged) / 3600
            f.write(f"Real (Merged) Duration: {real_dur:.2f}h\n")
            
        else:
            f.write("Employee not found\n")
