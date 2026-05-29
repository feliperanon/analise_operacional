import json
import re
from sqlmodel import Session, select
from database import engine
from models import (
    Employee, Event, User, Route, DeliverySession, EquipmentTicket,
    TranspalletChecklist, EmployeeAllocation, EmployeeRoutine, XPLedger,
    GameXPTransaction, EmployeeAchievement, PalletCount,
    PalletMaintenanceTicket, LeaderTaskResponse, LeaderTask, SubstitutionHistory
)


def normalize_numeric_id(value):
    """Remove o sufixo decimal (ex.: '201.0' -> '201') de IDs numéricos."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    # Remove .0 / .00 finais apenas quando o valor é numérico inteiro.
    s = re.sub(r"\.0+$", "", s)
    return s


def normalize_employee_ids(db):
    """Normaliza registration_id e seller_code de todos os colaboradores."""
    employees = db.exec(select(Employee)).all()
    changed = 0
    for emp in employees:
        new_reg = normalize_numeric_id(emp.registration_id)
        new_seller = normalize_numeric_id(emp.seller_code)
        if new_reg != emp.registration_id or new_seller != emp.seller_code:
            emp.registration_id = new_reg
            emp.seller_code = new_seller
            db.add(emp)
            changed += 1
    if changed:
        db.commit()
    print(f"Normalizacao concluida: {changed} cadastros ajustados (.0 removido).")

def get_completeness_score(emp: Employee) -> int:
    score = 0
    if emp.registration_id: score += 1
    if emp.seller_code: score += 1
    if emp.admission_date: score += 1
    if emp.cost_center: score += 1
    if emp.role and emp.role.strip() != "": score += 1
    if emp.birthday: score += 1
    if emp.photo_url: score += 1
    if emp.work_schedule: score += 1
    if emp.status == "active": score += 2  # Priorize active employees
    return score

def main():
    print("Iniciando varredura de duplicados...")
    with Session(engine) as db:
        # A normalizacao de IDs (remover sufixo .0) e feita DEPOIS da
        # deduplicacao. Se normalizassemos antes, "632886.0" colidiria com
        # "632886" ja existente, violando o indice unico de registration_id.

        employees = db.exec(select(Employee)).all()
        print(f"Total de colaboradores encontrados: {len(employees)}")

        # Agrupar por nome (maiúsculas e sem espaços extras)
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
                # Ordenar por score e depois por ID (para garantir determinismo)
                emp_list.sort(key=lambda x: (get_completeness_score(x), x.id), reverse=True)
                
                kept_emp = emp_list[0]
                duplicates = emp_list[1:]

                print(f"\n[{name}] - Manter ID {kept_emp.id} (Score {get_completeness_score(kept_emp)})")
                
                for dup in duplicates:
                    print(f"  Removendo duplicado ID {dup.id} (Score {get_completeness_score(dup)})")
                    
                    # --- Re-assigning FOREIGN KEYS ---
                    # Event
                    events = db.exec(select(Event).where(Event.employee_id == dup.id)).all()
                    for ev in events: ev.employee_id = kept_emp.id

                    # User
                    users = db.exec(select(User).where(User.employee_id == dup.id)).all()
                    for u in users: u.employee_id = kept_emp.id

                    # Employee.replaced_by
                    replaced = db.exec(select(Employee).where(Employee.replaced_by == dup.id)).all()
                    for r in replaced: r.replaced_by = kept_emp.id

                    # Route
                    routes = db.exec(select(Route).where(Route.employee_id == dup.id)).all()
                    for r in routes: r.employee_id = kept_emp.id

                    # DeliverySession
                    ds = db.exec(select(DeliverySession).where(DeliverySession.employee_id == dup.id)).all()
                    for d in ds: d.employee_id = kept_emp.id

                    # EquipmentTicket
                    tickets = db.exec(select(EquipmentTicket).where(EquipmentTicket.employee_id == dup.id)).all()
                    for t in tickets: t.employee_id = kept_emp.id

                    # TranspalletChecklist
                    checks = db.exec(select(TranspalletChecklist).where(TranspalletChecklist.employee_id == dup.id)).all()
                    for c in checks: c.employee_id = kept_emp.id

                    # EmployeeAllocation
                    allocs = db.exec(select(EmployeeAllocation).where(EmployeeAllocation.employee_id == dup.id)).all()
                    for a in allocs: a.employee_id = kept_emp.id

                    # EmployeeRoutine
                    routines = db.exec(select(EmployeeRoutine).where(EmployeeRoutine.employee_id == dup.id)).all()
                    for r in routines: r.employee_id = kept_emp.id

                    # XPLedger
                    xps = db.exec(select(XPLedger).where(XPLedger.employee_id == dup.id)).all()
                    for x in xps: x.employee_id = kept_emp.id

                    # GameXPTransaction
                    gxps = db.exec(select(GameXPTransaction).where(GameXPTransaction.employee_id == dup.id)).all()
                    for g in gxps: g.employee_id = kept_emp.id

                    # EmployeeAchievement
                    achvs = db.exec(select(EmployeeAchievement).where(EmployeeAchievement.employee_id == dup.id)).all()
                    for ac in achvs: ac.employee_id = kept_emp.id

                    # PalletCount
                    pcs = db.exec(select(PalletCount).where(PalletCount.employee_id == dup.id)).all()
                    for p in pcs: p.employee_id = kept_emp.id

                    # PalletMaintenanceTicket
                    pmts = db.exec(select(PalletMaintenanceTicket).where(PalletMaintenanceTicket.employee_id == dup.id)).all()
                    for pm in pmts: pm.employee_id = kept_emp.id

                    # LeaderTaskResponse
                    ltresp = db.exec(select(LeaderTaskResponse).where(LeaderTaskResponse.employee_id == dup.id)).all()
                    for ltr in ltresp: ltr.employee_id = kept_emp.id

                    # SubstitutionHistory
                    subs_orig = db.exec(select(SubstitutionHistory).where(SubstitutionHistory.original_employee_id == dup.id)).all()
                    for s in subs_orig: s.original_employee_id = kept_emp.id
                    subs_new = db.exec(select(SubstitutionHistory).where(SubstitutionHistory.new_employee_id == dup.id)).all()
                    for s in subs_new: s.new_employee_id = kept_emp.id

                    # LeaderTask.recipient_employee_ids mapping
                    tasks = db.exec(select(LeaderTask)).all()
                    for t in tasks:
                        if t.recipient_employee_ids and dup.id in t.recipient_employee_ids:
                            new_list = [kept_emp.id if x == dup.id else x for x in t.recipient_employee_ids]
                            t.recipient_employee_ids = list(set(new_list)) # deduplicate
                            db.add(t)

                    # Now delete the duplicate
                    db.delete(dup)
                    deleted_count += 1
        
        if deleted_count > 0:
            db.commit()
            print(f"\nProcesso concluido! Foram encontrados {duplicates_found} grupos de duplicados e {deleted_count} cadastros indevidos foram removidos.")
        else:
            print("\nNenhum colaborador duplicado encontrado ou necessario remover.")

        # Agora que os duplicados foram removidos, e seguro normalizar os IDs
        # restantes (remover sufixo .0) sem risco de violar o indice unico.
        print("\nNormalizando IDs dos colaboradores restantes...")
        normalize_employee_ids(db)

if __name__ == "__main__":
    main()
