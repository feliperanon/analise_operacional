from sqlmodel import Session, select, col
from models import Employee, DayStatus, Event
from database import engine

def debug_weverton():
    with Session(engine) as session:
        # 1. Find Employee
        emp = session.exec(select(Employee).where(col(Employee.name).contains("WEVERTON ALEXSSANDER"))).first()
        if not emp:
            print("Employee not found!")
            return

        print(f"Employee Found: {emp.name} (ID: {emp.id})")

        # 2. Check DayStatus (Absences)
        absences = session.exec(select(DayStatus).where(DayStatus.employee_id == emp.id).where(DayStatus.status == 'absent')).all()
        print(f"\n--- DayStatus Absences ({len(absences)}) ---")
        for a in absences:
            print(f"Date: {a.date}, Shift: {a.shift}, Status: {a.status}")

        # 3. Check Events (Occurrences)
        events = session.exec(select(Event).where(Event.employee_id == emp.id).where(col(Event.event_type).contains("Falta"))).all()
        print(f"\n--- Events 'Falta' ({len(events)}) ---")
        for e in events:
            print(f"Date: {e.date}, Type: {e.event_type}, Text: {e.text}")

if __name__ == "__main__":
    debug_weverton()
