from sqlmodel import Session, delete
from sqlalchemy import update
from database import engine
from models import Employee, Event

def clear_all_employees():
    print("Iniciando limpeza de colaboradores...")
    with Session(engine) as session:
        # 1. Unlink events (set employee_id to NULL to avoid constraint errors)
        try:
            stmt_update = update(Event).values(employee_id=None)
            result_events = session.exec(stmt_update)
            print(f"Eventos desvinculados: {result_events.rowcount}")
        except Exception as e:
            print(f"Aviso ao desvincular eventos (pode não haver tabela ainda): {e}")

        # 2. Delete employees
        try:
            stmt_delete = delete(Employee)
            result_emp = session.exec(stmt_delete)
            print(f"Colaboradores deletados: {result_emp.rowcount}")
        except Exception as e:
            print(f"Erro ao deletar colaboradores: {e}")
            session.rollback()
            return

        session.commit()
        print("Limpeza concluída com sucesso.")

if __name__ == "__main__":
    clear_all_employees()
