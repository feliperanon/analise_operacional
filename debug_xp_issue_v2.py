
from sqlmodel import Session, select
from database import engine
import models
import json

def diagnose_xp(employee_id, target_date):
    with Session(engine) as session:
        print(f"--- Diagnosing XP for Employee {employee_id} ---")
        
        # 1. Check ALL routes for this employee to see date format
        all_routes = session.exec(
            select(models.Route).where(models.Route.employee_id == employee_id)
        ).all()
        
        print(f"Total routes for employee: {len(all_routes)}")
        dates_found = set(r.date for r in all_routes)
        print(f"Dates found in DB: {dates_found}")

        # 2. Check specifically for the target date
        routes = session.exec(
            select(models.Route).where(
                models.Route.employee_id == employee_id,
                models.Route.date == target_date
            )
        ).all()
        
        print(f"\nRoutes for {target_date}: {len(routes)}")
        for r in routes:
            print(f"  - ID: {r.id}, Date: '{r.date}', Status: {r.status}, Kg: {r.tonnage}")

        # 3. Check ALL XP transactions for this employee
        txs = session.exec(
            select(models.GameXPTransaction).where(models.GameXPTransaction.employee_id == employee_id)
        ).all()
        
        print(f"\nTotal XP Transactions for employee: {len(txs)}")
        for tx in txs:
            print(f"  - ID: {tx.id}, Status: {tx.status}, Date: {tx.created_at}, Reason: {tx.reason[:50]}...")

if __name__ == "__main__":
    import sys
    emp_id = 442
    date = "2026-01-18"
    diagnose_xp(emp_id, date)
