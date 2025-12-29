from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime

def fix_history():
    with Session(engine) as session:
        # 1. Find Employees
        mariana = session.exec(select(models.Employee).where(models.Employee.name.like("%MARIANA STEFANE%"))).first()
        vanderli = session.exec(select(models.Employee).where(models.Employee.name.like("%VANDERLI%"))).first()
        
        if not mariana:
            print("ERROR: Mariana not found")
            return
        if not vanderli:
            print("ERROR: Vanderli not found")
            return
            
        print(f"Found Mariana: {mariana.name} (ID: {mariana.id})")
        print(f"Found Vanderli: {vanderli.name} (ID: {vanderli.id})")
        
        # 2. Check for existing events to prevent duplicates
        # Check Mariana's events
        existing_mariana = session.exec(select(models.Event).where(
            models.Event.employee_id == mariana.id,
            models.Event.text.like("%substituição%")
        )).first()
        
        # Check Vanderli's events
        existing_vanderli = session.exec(select(models.Event).where(
            models.Event.employee_id == vanderli.id,
            models.Event.text.like("%Substituído por%")
        )).first()
        
        if existing_mariana:
             print("Event already exists for Mariana. Skipping.")
        else:
             print("Creating event for Mariana...")
             evt_m = models.Event(
                text=f"Entrou em substituição a {vanderli.name} (Demitido)",
                type="alteracao_cadastro",
                category="pessoas",
                employee_id=mariana.id,
                sector="RH",
                timestamp=datetime.now() # Or ideally match admission/creation? User didn't specify, now is fine.
             )
             session.add(evt_m)

        if existing_vanderli:
             print("Event already exists for Vanderli. Skipping.")
        else:
             print("Creating event for Vanderli...")
             evt_v = models.Event(
                text=f"Substituído por {mariana.name}",
                type="alteracao_cadastro",
                category="pessoas",
                employee_id=vanderli.id,
                sector="RH",
                timestamp=datetime.now()
             )
             session.add(evt_v)
             
        session.commit()
        print("Fix applied successfully.")

if __name__ == "__main__":
    fix_history()
