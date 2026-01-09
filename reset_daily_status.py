from sqlmodel import Session, select, delete
from database import engine
from models import Employee, EmployeeRoutine, Event
from datetime import datetime
import sys

def reset_status():
    sys.stdout.reconfigure(encoding='utf-8')
    today = datetime.now().strftime("%Y-%m-%d")
    
    with Session(engine) as session:
        print(f"🧹 Iniciando reset de Faltas e Atestados para {today}...")
        
        # 1. Reset Status -> Active (except Fired)
        employees = session.exec(select(Employee).where(Employee.status != "fired")).all()
        count_status = 0
        for emp in employees:
            if emp.status != "active":
                emp.status = "active"
                session.add(emp)
                count_status += 1
        
        # 2. Delete Daily Routines (Absences/Sick/Etc) for TODAY
        # Note: We delete ALL routines for today to start fresh, 
        # assuming the user wants to re-launch everything.
        statement_routine = select(EmployeeRoutine).where(EmployeeRoutine.date == today)
        routines = session.exec(statement_routine).all()
        count_routine = 0
        for r in routines:
            session.delete(r)
            count_routine += 1
            
        # 3. Delete Events (Falta/Atestado) created TODAY?
        # Ideally, we filter by date... events have timestamp.
        # We'll just look for events today.
        start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        statement_event = select(Event).where(Event.timestamp >= start_of_day).where(
            (Event.type == "falta") | (Event.type == "atestado")
        )
        events = session.exec(statement_event).all()
        count_event = 0
        for e in events:
            session.delete(e)
            count_event += 1
            
        session.commit()
        
        print(f"\n✅ Reset Concluído:")
        print(f"- {count_status} colaboradores voltaram para status 'Active'.")
        print(f"- {count_routine} rotinas do dia {today} foram apagadas.")
        print(f"- {count_event} eventos de falta/atestado de hoje foram apagados.")

if __name__ == "__main__":
    reset_status()
