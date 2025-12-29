from sqlmodel import Session, select
from database import get_session, create_db_and_tables, engine
import models
import logging

# Desativa logs excessivos do sqlalchemy
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

def fix_employee():
    with Session(engine) as session:
        # Busca exata pelo ID ou matricula que descobrimos
        # ID: 544, Matrícula: 1263
        emp = session.get(models.Employee, 544)
        
        if not emp:
            print("Funcionário ID 544 não encontrado.")
            return

        print(f"Status atual: {emp.status}")
        if emp.status == 'fired':
            emp.status = 'active'
            session.add(emp)
            session.commit()
            print(f"Sucesso: Status de '{emp.name}' atualizado para 'active'.")
        else:
            print(f"Funcionário já está com status: {emp.status}")

if __name__ == "__main__":
    fix_employee()
