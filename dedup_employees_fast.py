import os
os.environ["DEBUG"] = "false"

import json
from sqlmodel import Session, select
from sqlalchemy import text
from database import engine
from models import Employee

def get_completeness_score(emp: Employee) -> int:
    score = 0
    if emp.registration_id: score += 1
    if emp.seller_code: score += 1
    if emp.admission_date: score += 1
    if emp.cost_center: score += 1
    if emp.role and str(emp.role).strip() != "": score += 1
    if emp.birthday: score += 1
    if emp.photo_url: score += 1
    if emp.work_schedule: score += 1
    if emp.status == "active": score += 2
    return score

tables_with_employee_fk = [
    ("event", "employee_id"),
    ("user", "employee_id"),
    ("employee", "replaced_by"),
    ("route", "employee_id"),
    ("deliverysession", "employee_id"),
    ("equipmentticket", "employee_id"),
    ("transpalletchecklist", "employee_id"),
    ("employeeallocation", "employee_id"),
    ("employeeroutine", "employee_id"),
    ("xpledger", "employee_id"),
    ("gamexptransaction", "employee_id"),
    ("employeeachievement", "employee_id"),
    ("palletcount", "employee_id"),
    ("palletmaintenanceticket", "employee_id"),
    ("leadertaskresponse", "employee_id"),
    ("substitutionhistory", "original_employee_id"),
    ("substitutionhistory", "new_employee_id"),
]

def main():
    print("Iniciando varredura rápida de duplicados...")
    with Session(engine) as db:
        employees = db.exec(select(Employee)).all()
        print(f"Total de colaboradores encontrados: {len(employees)}")

        from collections import defaultdict
        groups = defaultdict(list)
        for emp in employees:
            if not emp.name:
                continue
            name_key = " ".join(emp.name.strip().upper().split())
            groups[name_key].append(emp)

        duplicates_found = 0
        deleted_count = 0

        for name, emp_list in groups.items():
            if len(emp_list) > 1:
                duplicates_found += 1
                emp_list.sort(key=lambda x: (get_completeness_score(x), x.id), reverse=True)
                
                kept_emp = emp_list[0]
                duplicates = emp_list[1:]
                dup_ids = [d.id for d in duplicates]
                
                print(f"[{name}] -> Mantendo ID {kept_emp.id} (Removendo {len(dup_ids)} ids duplicados)")

                # Re-assign simple FKs
                for table, column in tables_with_employee_fk:
                    try:
                        sql = text(f"UPDATE {table} SET {column} = :kept_id WHERE {column} IN :dup_ids")
                        db.execute(sql, {"kept_id": kept_emp.id, "dup_ids": tuple(dup_ids)})
                    except Exception:
                        pass
                
                # Finally delete the duplicate records
                for dup_id in dup_ids:
                    try:
                        sql = text("DELETE FROM employee WHERE id = :dup_id")
                        db.execute(sql, {"dup_id": dup_id})
                        deleted_count += 1
                    except Exception as e:
                        print(f"Erro ao deletar duplicado ID {dup_id}: {e}")
        
        db.commit()
        print(f"\\nProcesso concluido! Foram encontrados {duplicates_found} grupos de duplicados e {deleted_count} cadastros indevidos foram removidos.")

if __name__ == "__main__":
    main()
