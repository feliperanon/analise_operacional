from sqlmodel import Session, select, delete, col
from database import engine
from models import Employee, EmployeeRoutine, Event
import sys

def wipe_all_absences_aggressive():
    sys.stdout.reconfigure(encoding='utf-8')
    
    with Session(engine) as session:
        print(f"🧨 Iniciando REMOÇÃO AGRESSIVA de histórico de faltas/atestados...\n")
        
        # 1. Reset Status -> Active
        employees = session.exec(select(Employee).where(Employee.status != "fired")).all()
        for emp in employees:
            if emp.status != "active":
                emp.status = "active"
                session.add(emp)
        
        # 2. Delete Routines (Broader Keywords)
        # We target anything that looks like an absence
        bad_routines = [
            'absent', 'sick', 'vacation', 'away', 'suspension',
            'falta', 'atestado', 'ferias', 'afastado', 'suspensao',
            'advertencia', 'licenca', 'retorno', 'medico', 'atestado_medico'
        ]
        
        statement_routine = select(EmployeeRoutine).where(
            col(EmployeeRoutine.routine).in_(bad_routines)
        )
        # Add ILIKE logic if SQLModel supported it easily, but distinct list helps.
        # Let's just fetch all non-present and filter in python if needed, or use IN.
        # Efficient way: delete based on list.
        
        routines = session.exec(statement_routine).all()
        count_routine = len(routines)
        for r in routines:
            session.delete(r)

        # 3. Delete Events (Broader Keywords)
        bad_events = [
            'falta', 'atestado', 'atestado_medico', 'suspensao', 'advertencia',
            'afastamento', 'licenca', 'suspension', 'warning', 'absent', 'sick'
        ]
        
        statement_event = select(Event).where(
            col(Event.type).in_(bad_events)
        )
        events = session.exec(statement_event).all()
        count_event = len(events)
        for e in events:
            session.delete(e)
            
        session.commit()
        
        print(f"\n✅ Limpeza Agressiva Concluída:")
        print(f"- Todos os ativos resetados para 'Active'.")
        print(f"- {count_routine} rotinas apagadas.")
        print(f"- {count_event} eventos apagados.")

if __name__ == "__main__":
    wipe_all_absences_aggressive()
