
from sqlmodel import Session, select, create_engine
import os
import models

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

if __name__ == "__main__":
    with Session(engine) as session:
        try:
            print("Querying employees with filter...")
            
            # Create dummy
            dummy = models.Employee(
                name="Teste Flow", registration_id="99999", role="Tester", 
                flow_step="Descarga", flow_override_sector="Recebimento"
            )
            session.add(dummy)
            session.commit()
            print("Inserted dummy.")

            query = select(models.Employee).where(models.Employee.work_shift == "Manhã")
            emps = session.exec(query).all()
            print(f"Found {len(emps)} employees.")
            for e in emps:
                 print(f"{e.name}: {e.flow_step} ({e.flow_override_sector})")
        except Exception as e:
            import traceback
            traceback.print_exc()
