from sqlmodel import Session, select
from database import engine
import models

def fix_events():
    with Session(engine) as session:
        # Fetch generic routine_change events
        events = session.exec(select(models.Event).where(models.Event.type == "routine_change")).all()
        
        updated_count = 0
        
        type_map = {
             'sick': 'atestado',
             'absent': 'falta',
             'away': 'afastamento',
             'vacation': 'ferias',
             'dayoff': 'folga',
             'present': 'presenca'
        }
        
        print(f"Encontrados {len(events)} eventos do tipo 'routine_change'. Analisando...")
        
        for event in events:
            # Check category
            if event.category in type_map:
                new_type = type_map[event.category]
                if event.type != new_type:
                    print(f"🔄 Corrigindo Evento {event.id} ({event.category}): {event.type} -> {new_type}")
                    event.type = new_type
                    session.add(event)
                    updated_count += 1
            else:
                # Try infer from text?
                txt = (event.text or "").lower()
                if "falta" in txt:
                    event.type = "falta"
                    session.add(event)
                    updated_count += 1
                elif "atestado" in txt:
                    event.type = "atestado"
                    session.add(event)
                    updated_count += 1
                
        session.commit()
        print(f"✅ Total corrigidos: {updated_count}")
        
if __name__ == "__main__":
    fix_events()
