from sqlmodel import Session, select, func
from database import engine
from models import Employee, GameXPTransaction

def recalc_all_xp():
    with Session(engine) as session:
        employees = session.exec(select(Employee)).all()
        print(f"Checking {len(employees)} employees...")
        
        updated_count = 0
        for emp in employees:
            # Sum confirmed/provisional transactions
            # Usually only 'confirmed' count for Total, but if we want to show 'Running Total' we might include provisional?
            # Standard: Total XP = Confirmed. Provisional is "Potential".
            # BUT, the dashboard usually shows "Live" data.
            # Let's check gamification_engine. 
            # It updates total_xp ONLY on confirm_pending_xp.
            # So if transactions are provisional (daily_auto created 18:59), they might NOT be in total_xp yet.
            # That explains "Total wrong" if user expects instant update.
            # However, for display purposes, we might want to show Sum(All) or ensure they are confirmed faster.
            # Or the user just wants the cached value to be correct.
            
            # Let's sum ALL valid transactions to see the "Real" theoretical total
            total_ledger = session.exec(
                select(func.sum(GameXPTransaction.amount))
                .where(GameXPTransaction.employee_id == emp.id)
                .where(GameXPTransaction.status != "rejected") # Include provisional + confirmed
            ).one() or 0.0
            
            if int(total_ledger) != int(emp.total_xp):
                print(f"Mismatch for {emp.name}: Ledger {total_ledger} != Current {emp.total_xp}. Updating...")
                emp.total_xp = int(total_ledger)
                session.add(emp)
                updated_count += 1
                
        session.commit()
        print(f"Recalculation Complete. Updated {updated_count} employees.")

if __name__ == "__main__":
    recalc_all_xp()
