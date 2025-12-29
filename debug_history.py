from sqlmodel import Session, select
from database import engine
import models
import json
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

def inspect_data():
    with Session(engine) as session:
        # Find Mariana
        mariana = session.exec(select(models.Employee).where(models.Employee.name.like("%MARIANA STEFANE%"))).first()
        if not mariana:
            print("Mariana not found")
        else:
            print(f"Mariana ID: {mariana.id}, Reg: {mariana.registration_id}")
            # Check events
            events = session.exec(select(models.Event).where(models.Event.employee_id == mariana.id)).all()
            print("Events for Mariana:")
            for e in events:
                print(f" - [{e.timestamp}] {e.text} (Type: {e.type})")

        # Find Vanderli
        vanderli = session.exec(select(models.Employee).where(models.Employee.name.like("%VANDERLI%"))).first()
        if not vanderli:
            print("Vanderli not found")
        else:
            print(f"Vanderli ID: {vanderli.id}")
            events = session.exec(select(models.Event).where(models.Event.employee_id == vanderli.id)).all()
            print("Events for Vanderli:")
            for e in events:
                print(f" - [{e.timestamp}] {e.text} (Type: {e.type})")

if __name__ == "__main__":
    inspect_data()
