from sqlmodel import Session, select
from database import engine
import models
import sys

def debug():
    with open("debug_output.txt", "w", encoding="utf-8") as f:
        with Session(engine) as session:
            # ID 417 - Arthur
            emp_id = 417
            emp = session.get(models.Employee, emp_id)
            if not emp:
                f.write("Arthur not found!\n")
                return

            f.write(f"Employee: {emp.name} (ID: {emp.id}) Status: {emp.status} Shift: '{emp.work_shift}'\n")
            
            f.write("\n--- EVENTS (Last 10) ---\n")
            events = session.exec(select(models.Event).where(models.Event.employee_id == emp_id).order_by(models.Event.timestamp.desc()).limit(10)).all()
            for e in events:
                f.write(f"[{e.timestamp}] Type: {e.type} | Category: {e.category} | Text: {e.text}\n")
                
            f.write("\n--- ROUTINES (Jan 2026) ---\n")
            routines = session.exec(select(models.EmployeeRoutine).where(models.EmployeeRoutine.employee_id == emp_id).where(models.EmployeeRoutine.date >= "2026-01-01")).all()
            for r in routines:
                f.write(f"[{r.date} - {r.shift}] Routine: {r.routine}\n")

if __name__ == "__main__":
    debug()
