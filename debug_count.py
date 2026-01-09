from sqlmodel import Session, select, func
from database import engine
from models import Employee

def check_counts():
    with Session(engine) as session:
        # 1. Count by Shift and Status
        print("--- Counts by Shift/Status ---")
        shifts = session.exec(select(Employee.work_shift).distinct()).all()
        for shift in shifts:
            if not shift: continue
            count_active = session.exec(select(func.count()).where(Employee.work_shift == shift, Employee.status == 'active')).one()
            count_fired = session.exec(select(func.count()).where(Employee.work_shift == shift, Employee.status == 'fired')).one()
            count_total = session.exec(select(func.count()).where(Employee.work_shift == shift)).one()
            print(f"Shift '{shift}': Active={count_active}, Fired={count_fired}, Total={count_total}")

        # 2. Check for Duplicates (Name)
        print("\n--- Duplicate Names (Active) ---")
        employees = session.exec(select(Employee).where(Employee.status == 'active')).all()
        seen = {}
        dupes = []
        for e in employees:
            if e.name in seen:
                dupes.append(e.name)
            seen[e.name] = True
        
        if dupes:
            print(f"Found {len(dupes)} duplicates: {dupes[:10]}...")
        else:
            print("No duplicate active names found.")

        # 3. Check for Duplicates (Registration ID)
        print("\n--- Duplicate Reg IDs (Active) ---")
        seen_reg = {}
        dupes_reg = []
        for e in employees:
            if e.registration_id and e.registration_id in seen_reg:
                dupes_reg.append(e.registration_id)
            seen_reg[e.registration_id] = True
            
        if dupes_reg:
             print(f"Found {len(dupes_reg)} duplicate IDs: {dupes_reg[:10]}...")
        else:
             print("No duplicate registration IDs found.")

if __name__ == "__main__":
    import sys
    # Redirect stdout to a file
    with open("debug_count_result.txt", "w", encoding="utf-8") as f:
        sys.stdout = f
        check_counts()
        print("Done.")
