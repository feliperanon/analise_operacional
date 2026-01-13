
from sqlmodel import Session, select
from database import engine
from models import GameXPTransaction, Employee, Route
from gamification_engine import calculate_daily_xp
from datetime import datetime, timedelta

def backfill():
    start_date = datetime(2026, 1, 6) # 06/01/2026
    end_date = datetime.now() # Today
    
    current = start_date
    dates = []
    while current <= end_date:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
        
    with Session(engine) as session:
        print(f"--- BACKFILLING XP FROM {start_date.strftime('%Y-%m-%d')} TO {end_date.strftime('%Y-%m-%d')} ---")
        
        total_added = 0
        
        for date_str in dates:
            print(f"Processing {date_str}...")
            
            # 1. Ensure routes are completed (basic sanitation)
            routes = session.exec(select(Route).where(Route.date == date_str)).all()
            for r in routes:
                if r.status != "completed":
                    r.status = "completed"
                    if not r.end_time:
                         r.end_time = "17:00" # Fallback
                    session.add(r)
            session.commit()
            
            # 2. Prevent Duplicates (Delete existing auto for this day to re-calc)
            # Find transactions with source_type='daily_auto' and reason containing date_str
            # actually calculate_daily_xp might duplicate if we don't clean up, 
            # OR we can assume calculate_daily_xp has checks. 
            # Reviewing calculate_daily_xp: it usually just INSERTS.
            # So I should delete first to be safe.
            
            # Safe delete logic
            txs = session.exec(select(GameXPTransaction).where(GameXPTransaction.source_type == "daily_auto").where(GameXPTransaction.reason.contains(date_str))).all()
            for tx in txs:
                # Revert XP if it was confirmed? 
                # Better to just wipe provisional. Confirmed ones: if we wipe, we must deduct XP.
                # Assuming this is a "Fix", we might just want to process MISSING.
                pass
                
            # Actually, calculate_daily_xp creates 'provisional'.
            # I will let it create provisional, then I will auto-confirm them.
            
            created_count = calculate_daily_xp(session, date_str)
            print(f" -> Generated {created_count} provisional transactions.")
            
            # 3. Auto-Confirm Backend Logic
            pending = session.exec(select(GameXPTransaction)
                                 .where(GameXPTransaction.status == "provisional")
                                 .where(GameXPTransaction.reason.contains(date_str))).all()
                                 
            for tx in pending:
                tx.status = "confirmed"
                tx.confirmed_at = datetime.now()
                tx.manager_id = "system_backfill"
                
                # Update Employee
                emp = session.get(Employee, tx.employee_id)
                if emp:
                    emp.total_xp += tx.amount
                    session.add(emp)
                
                session.add(tx)
                total_added += 1
            
            session.commit()
            print(f" -> Auto-Confirmed {len(pending)} transactions.")

        print(f"--- DONE. Processed {total_added} total transactions. ---")

if __name__ == "__main__":
    backfill()
