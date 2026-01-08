from sqlmodel import Session, select, col
from database import engine
import models
from datetime import datetime
import sys

# Mocking the Calculate Function locally for simplicity
def calculate_expected_work_days(*args, **kwargs):
    return 20

def debug_metrics():
    with open("debug_report.txt", "w", encoding="utf-8") as f:
        with Session(engine) as session:
            shift = "Manhã"
            start_date = "2026-01-01"
            end_date = "2026-01-08"
            
            f.write(f"--- DEBUG REPORT LOGIC ---\nShift: {shift}\nDates: {start_date} to {end_date}\n\n")
            
            # 1. Overview Data
            employees = session.exec(
                select(models.Employee)
                .where(models.Employee.status != "fired")
                .where(models.Employee.replaced_by.is_(None))
            ).all()
            
            # Filter by Shift
            employees_filtered = [e for e in employees if e.work_shift == shift]
            f.write(f"Total Employees: {len(employees)}\n")
            f.write(f"Filtered by Shift '{shift}': {len(employees_filtered)}\n")
            
            # Check Arthur in List
            arthur = next((e for e in employees_filtered if e.id == 417), None)
            if arthur:
                f.write(f"✅ Arthur FOUND in filtered list. Shift: '{arthur.work_shift}'\n")
            else:
                f.write(f"❌ Arthur NOT FOUND in filtered list!\n")
                arthur_raw = session.get(models.Employee, 417)
                if arthur_raw:
                     f.write(f"   Arthur Raw Shift: '{arthur_raw.work_shift}' (Expected: '{shift}')\n")

            total_headcount = len(employees_filtered)
            employee_ids = {e.id for e in employees_filtered}
            
            # Date Range
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            
            f.write(f"Query Range: {start_dt} to {end_dt}\n")
            
            events = session.exec(
                select(models.Event)
                .where(models.Event.timestamp >= start_dt)
                .where(models.Event.timestamp < end_dt)
                .where(col(models.Event.type).in_(['falta', 'atestado', 'advertencia', 'afastamento']))
            ).all()
            
            f.write(f"Raw Events Found (Global): {len(events)}\n")
            
            # Debug specific event for Arthur
            arthur_events_raw = [e for e in events if e.employee_id == 417]
            f.write(f"Arthur Events in Raw Query: {len(arthur_events_raw)}\n")
            for e in arthur_events_raw:
                 f.write(f"   [{e.timestamp}] Type: '{e.type}' ID: {e.id}\n")

            # Filter events by employee_ids
            events_final = [e for e in events if e.employee_id in employee_ids]
            f.write(f"Events after Employee Filter: {len(events_final)}\n")
            
            arthur_events_final = [e for e in events_final if e.employee_id == 417]
            f.write(f"Arthur Events Final: {len(arthur_events_final)}\n")

            total_sick = sum(1 for e in events_final if e.type == 'atestado')
            f.write(f"Total Sick Count: {total_sick}\n")

if __name__ == "__main__":
    debug_metrics()
