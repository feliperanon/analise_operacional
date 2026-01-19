
from sqlmodel import Session, select, delete
from database import engine
import models
from datetime import datetime
from zoneinfo import ZoneInfo

def test_e2e_xp():
    with Session(engine) as session:
        emp_id = 3218
        date_str = "2026-01-18"
        
        # 1. Cleanup existing routes and transactions for this test
        try:
            # Delete routes
            routes_to_del = session.exec(select(models.Route).where(models.Route.employee_id == emp_id, models.Route.date == date_str)).all()
            for r in routes_to_del: session.delete(r)
            
            # Delete transactions
            txs_to_del = session.exec(select(models.GameXPTransaction).where(models.GameXPTransaction.employee_id == emp_id, models.GameXPTransaction.reason.contains(f"daily_{date_str}"))).all()
            for tx in txs_to_del: session.delete(tx)
            
            session.commit()
            print("Cleanup done.")
        except Exception as e:
            print(f"Cleanup error: {e}")
            session.rollback()

        # 2. Create pending route
        route = models.Route(
            employee_id=emp_id,
            client_id=1,
            date=date_str,
            tonnage=1000.0,
            start_time="10:00",
            status="pending"
        )
        session.add(route)
        session.commit()
        session.refresh(route)
        route_id = route.id
        print(f"Created pending route: {route_id}")

        # 3. Simulate finish
        r = session.get(models.Route, route_id)
        r.end_time = "11:00"
        r.status = "completed"
        session.add(r)
        
        print("Trigerring XP calc...")
        from gamification_engine import calculate_daily_xp
        calculate_daily_xp(session, date_str)
        session.commit()

        # 4. Verify
        txs = session.exec(select(models.GameXPTransaction).where(
            models.GameXPTransaction.employee_id == emp_id,
            models.GameXPTransaction.reason.contains(f"daily_{date_str}")
        )).all()
        
        print(f"Found {len(txs)} transactions.")
        for tx in txs:
            print(f"  - ID: {tx.id}, Status: {tx.status}, Amount: {tx.amount}")
            if tx.status == "provisional":
                print("✅ SUCCESS: Provisional transaction created!")

if __name__ == "__main__":
    test_e2e_xp()
