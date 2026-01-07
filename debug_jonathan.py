from sqlmodel import Session, select
from database import engine
from models import Employee, Route
from datetime import datetime

with Session(engine) as session:
    emp = session.exec(select(Employee).where(Employee.name.like('%JONATHAN WASHINGTON%'))).first()
    if emp:
        print(f"Name: {emp.name}")
        print(f"Schedule: {emp.work_schedule}")
        
        today = datetime.now().strftime('%Y-%m-%d')
        routes = session.exec(select(Route).where(Route.employee_id == emp.id).where(Route.date == today)).all()
        
        print("\nRoutes:")
        total_dur = 0
        for r in routes:
            print(f"- {r.start_time} to {r.end_time} | {r.tonnage}kg")
            if r.start_time and r.end_time:
                s = datetime.strptime(r.start_time, "%H:%M")
                e = datetime.strptime(r.end_time, "%H:%M")
                dur = (e - s).total_seconds() / 3600
                total_dur += dur
        
        print(f"\nTotal Active Hours: {total_dur:.2f}")
    else:
        print("Employee not found")
