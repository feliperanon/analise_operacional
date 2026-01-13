
from sqlmodel import Session, select, func
from database import engine
from models import Route, Employee, GameXPTransaction
from gamification_engine import calculate_daily_xp
from datetime import datetime, timedelta

def debug():
    with Session(engine) as session:
        # 1. Date to Check
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        print(f"--- Debugging for Yesterday ({yesterday_str}) & Today ({today_str}) ---")
        
        # 2. Check Routes
        routes_y = session.exec(select(Route).where(Route.date == yesterday_str)).all()
        print(f"Routes found for {yesterday_str}: {len(routes_y)}")
        for r in routes_y:
            print(f" - Route {r.id}: Emp={r.employee_id}, Status={r.status}, Tonnage={r.tonnage}, Date={r.date}")
            
        routes_t = session.exec(select(Route).where(Route.date == today_str)).all()
        print(f"Routes found for {today_str}: {len(routes_t)}")
        for r in routes_t:
             print(f" - Route {r.id}: Emp={r.employee_id}, Status={r.status}, Tonnage={r.tonnage}, Date={r.date}")

        # 3. Force Trigger Calculation for BOTH
        print("\n--- Triggering Calc ---")
        c1 = calculate_daily_xp(session, yesterday_str)
        c2 = calculate_daily_xp(session, today_str)
        print(f"Calc Yesterday created: {c1} txs")
        print(f"Calc Today created: {c2} txs")
        
        # 4. Check Transactions
        pending = session.exec(select(GameXPTransaction).where(GameXPTransaction.status == "provisional")).all()
        print(f"\n--- Pending Transactions ({len(pending)}) ---")
        for p in pending:
            print(f"ID={p.id}, Emp={p.employee_id}, Amount={p.amount}, Reason={p.reason}")

if __name__ == "__main__":
    debug()
