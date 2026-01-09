from sqlmodel import Session, select, func
from database import engine
from models import EmployeeRoutine, Event
import sys

def inspect_data():
    sys.stdout.reconfigure(encoding='utf-8')
    with Session(engine) as session:
        # Distinct Routines
        routines = session.exec(select(EmployeeRoutine.routine).distinct()).all()
        print(f"📋 Distinct Routines: {routines}")
        
        # Distinct Events
        events = session.exec(select(Event.type).distinct()).all()
        print(f"📋 Distinct Event Types: {events}")

if __name__ == "__main__":
    inspect_data()
