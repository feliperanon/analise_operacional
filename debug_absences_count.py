from sqlmodel import Session, select, func
from database import engine
from models import EmployeeRoutine, Event
import sys

def debug_counts():
    sys.stdout.reconfigure(encoding='utf-8')
    with Session(engine) as session:
        # Count Routines
        r_count = session.exec(select(func.count(EmployeeRoutine.id)).where(
            (EmployeeRoutine.routine == "absent") | 
            (EmployeeRoutine.routine == "sick") | 
            (EmployeeRoutine.routine == "vacation") |
            (EmployeeRoutine.routine == "away")
        )).one()
        
        # Count Events
        e_count = session.exec(select(func.count(Event.id)).where(
            (Event.type == "falta") | 
            (Event.type == "atestado") | 
            (Event.type == "advertencia") |
            (Event.type == "suspensao")
        )).one()
        
        print(f"📊 DEBUG COUNTS:")
        print(f"EmployeeRoutine (absent/sick/vacation/away): {r_count}")
        print(f"Event (falta/atestado/advertencia/suspensao): {e_count}")

if __name__ == "__main__":
    debug_counts()
