from sqlmodel import Session, select
from database import get_session, create_db_and_tables, engine
import models

import logging
# Desativa logs excessivos do sqlalchemy
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

def check_employee():
    with Session(engine) as session:
        # Tenta buscar por nome parcial
        statement = select(models.Employee).where(models.Employee.name.like("%VANDERLI%"))
        results = session.exec(statement).all()
        
        with open("check_result.txt", "w", encoding="utf-8") as f:
            if not results:
                f.write("Nenhum funcionário encontrado com 'VANDERLI' no nome.\n")
            else:
                f.write(f"Encontrados {len(results)} funcionário(s):\n")
                for emp in results:
                    f.write(f"ID: {emp.id}\n")
                    f.write(f"Nome: {emp.name}\n")
                    f.write(f"Matrícula: {emp.registration_id}\n")
                    f.write(f"Status: {emp.status}\n")
                    f.write(f"Turno: {emp.work_shift}\n")
                    f.write(f"Cost Center: {emp.cost_center}\n")
                    f.write(f"Role: {emp.role}\n")
                    f.write("-" * 20 + "\n")

if __name__ == "__main__":
    check_employee()
