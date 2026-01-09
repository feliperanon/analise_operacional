from sqlmodel import Session, select
from database import engine
from models import Employee
import sys

def generate_audit_list():
    with Session(engine) as session:
        employees = session.exec(select(Employee).where(Employee.status == "active").order_by(Employee.work_shift, Employee.name)).all()
        
        with open("active_employees_list.md", "w", encoding="utf-8") as f:
            f.write("\n# 📋 Auditoria de Colaboradores Ativos\n\n")
            f.write("Use esta lista para identificar quem NÃO deveria estar ativo.\n\n")
            
            current_shift = None
            count = 0
            
            for emp in employees:
                shift = emp.work_shift or "Sem Turno"
                if shift != current_shift:
                    if current_shift:
                        f.write(f"\n**Total {current_shift}: {count}**\n\n")
                    f.write(f"## 🕒 Turno: {shift}\n")
                    f.write("| ID | Matrícula | Nome | Cargo | Data Admissão |\n")
                    f.write("|---|---|---|---|---|\n")
                    current_shift = shift
                    count = 0
                
                adm = emp.admission_date.strftime('%d/%m/%Y') if emp.admission_date else "-"
                f.write(f"| {emp.id} | {emp.registration_id} | {emp.name} | {emp.role} | {adm} |\n")
                count += 1
                
            if current_shift:
                f.write(f"\n**Total {current_shift}: {count}**\n\n")

if __name__ == "__main__":
    generate_audit_list()
