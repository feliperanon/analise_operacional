from sqlmodel import Session, select, func
from database import engine
from models import Employee, GameXPTransaction

def check_totals():
    with Session(engine) as session:
        employees = session.exec(select(Employee)).all()
        print(f"Checking {len(employees)} employees...")
        print(f"{'Name':<30} | {'Stored Total':<12} | {'Ledger Sum':<12} | {'Diff':<6}")
        print("-" * 70)
        
        for emp in employees:
            # Sum all non-rejected transactions
            ledger_sum = session.exec(
                select(func.sum(GameXPTransaction.amount))
                .where(GameXPTransaction.employee_id == emp.id)
                .where(GameXPTransaction.status != "rejected")
            ).one() or 0
            
            stored = emp.total_xp or 0
            diff = stored - ledger_sum
            
            if diff != 0:
                print(f"{emp.name:<30} | {stored:<12} | {ledger_sum:<12} | {diff:<6} <-- MISMATCH")
            else:
                # Optional: Print everyone to see values
                # print(f"{emp.name:<30} | {stored:<12} | {ledger_sum:<12} | OK")
                pass

if __name__ == "__main__":
    check_totals()
