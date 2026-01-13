
from sqlmodel import Session, select, func, delete
from database import engine
from models import Route, GameXPTransaction, Employee
from gamification_engine import calculate_daily_xp
from datetime import datetime, timedelta

def fix():
    with Session(engine) as session:
        print("--- FIXING GAMIFICATION DATA ---")
        
        # 1. Fix Pending Routes (Yesterday & Today)
        routes = session.exec(select(Route).where(Route.status == "pending")).all()
        print(f"Found {len(routes)} PENDING routes. Fixing status...")
        for r in routes:
            r.status = "completed"
            if not r.end_time:
                # If no end time, assume 1 hour after start or now
                r.end_time = datetime.now().strftime("%H:%M") 
            session.add(r)
        session.commit()
        print("Routes updated.")
        
        # 2. Clear Provisional Transactions for cleanup (Optional, but safe for debug)
        # We only clear if we want to force recalc
        # statement = delete(GameXPTransaction).where(GameXPTransaction.status == "provisional")
        # session.exec(statement)
        # session.commit()
        # print("Cleared provisional transactions.")

        # 3. Recalc for Last 3 Days
        dates_to_check = [
            (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
            (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
            datetime.now().strftime("%Y-%m-%d")
        ]
        
        for d in dates_to_check:
            print(f"Calculating for {d}...")
            count = calculate_daily_xp(session, d)
            print(f" -> Created {count} transactions.")
            
        # 4. Verify Final State
        pending = session.exec(select(GameXPTransaction).where(GameXPTransaction.status == "provisional")).all()
        print(f"\nTOTAL PENDING in DB: {len(pending)}")
        for p in pending:
            print(f" - [ID {p.id}] Emp {p.employee_id}: {p.amount} XP ({p.reason})")

if __name__ == "__main__":
    fix()
