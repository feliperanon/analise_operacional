"""
Diagnóstico: Listar todas as rotas de hoje com seus horários atuais.
"""
import sys
import os
sys.path.append(os.getcwd())

from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime

def list_all_routes():
    with Session(engine) as session:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"Rotas de hoje ({today}):\n")
        
        stmt = select(models.Route).where(models.Route.date == today)
        routes = session.exec(stmt).all()
        
        print(f"{'ID':<6} {'Colaborador':<35} {'Início':<8} {'Fim':<8} {'Status':<12}")
        print("-" * 80)
        
        for r in routes:
            emp = session.get(models.Employee, r.employee_id)
            emp_name = (emp.name if emp else f"ID:{r.employee_id}")[:35]
            start = r.start_time or "-"
            end = r.end_time or "-"
            status = r.status or "-"
            print(f"{r.id:<6} {emp_name:<35} {start:<8} {end:<8} {status:<12}")
        
        print(f"\nTotal: {len(routes)} rotas")

if __name__ == "__main__":
    list_all_routes()
