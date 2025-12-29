
import logging
from sqlmodel import Session, select, col
from database import engine
from models import DailyOperation, Employee, Event
from datetime import datetime
import json

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def backfill_events():
    with Session(engine) as session:
        # Fetch all processed daily operations
        ops = session.exec(select(DailyOperation)).all()
        logger.info(f"Found {len(ops)} daily operations to scan.")

        # Cache Employees
        employees = session.exec(select(Employee)).all()
        emp_map = {str(e.registration_id): e for e in employees}
        logger.info(f"Cached {len(employees)} employees.")

        new_events_count = 0
        
        for op in ops:
            if not op.attendance_log:
                continue
                
            op_date_dt = datetime.strptime(op.date, "%Y-%m-%d")
            
            # For each entry in attendance log
            for reg_id, entry in op.attendance_log.items():
                status = entry.get('status')
                
                # We care about: absent (falta), sick (atestado), away (afastado)
                if status not in ['absent', 'sick']:
                    continue
                    
                emp = emp_map.get(str(reg_id))
                if not emp:
                    continue

                # Determine Event Type
                event_type = "falta" if status == 'absent' else "atestado"
                
                # Check for duplicate: Event for this employee, this date (approx), this type
                # We assume the event timestamp matches the op date 
                # (Or strictly, an event of this type created around this time? 
                # Better: Check if an event exists for this employee with timestamp on this DATE)
                
                # Complex filter in SQLModel/SQLAlchemy for Date part of DataTime is tricky without specific funcs
                # We'll fetch events for this employee and filter in python for safety and simplicity (volume isn't huge yet)
                
                existing_events = session.exec(
                    select(Event)
                    .where(Event.employee_id == emp.id)
                    .where(Event.type == event_type)
                ).all()
                
                # Check if any matches the date
                already_exists = any(e.timestamp.date() == op_date_dt.date() for e in existing_events)
                
                if not already_exists:
                    # Create Event
                    evt_text = f"Registro automático: {status.upper()} em {op.date}"
                    if status == 'sick':
                        evt_text = f"Atestado registrado em {op.date}"
                    elif status == 'absent':
                        evt_text = f"Falta registrada em {op.date}"
                        
                    new_event = Event(
                        timestamp=op_date_dt.replace(hour=8, minute=0), # Set to morning of that day
                        text=evt_text,
                        type=event_type,
                        category="pessoas",
                        sector=emp.cost_center or "Geral",
                        impact="medium", # Faltas/Atestados generally medium
                        employee_id=emp.id,
                        # We don't link shift_id easily unless we fetch shift object, skippable for now
                    )
                    session.add(new_event)
                    new_events_count += 1

        session.commit()
        logger.info(f"Backfill Complete. Created {new_events_count} new events.")

if __name__ == "__main__":
    backfill_events()
