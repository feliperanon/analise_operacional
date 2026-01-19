
from sqlmodel import Session, select
from database import engine
import models
import json

def diagnose_xp(employee_id, date_str):
    with Session(engine) as session:
        print(f"--- Diagnosing XP for Employee {employee_id} on {date_str} ---")
        
        # 1. Check Routes
        routes = session.exec(
            select(models.Route).where(
                models.Route.employee_id == employee_id,
                models.Route.date == date_str
            )
        ).all()
        
        print(f"Found {len(routes)} routes:")
        for r in routes:
            print(f"  - Route ID: {r.id}, Status: {r.status}, Tonnage: {r.tonnage}, Time: {r.start_time}-{r.end_time}")
            
        # 2. Check XP Transactions
        # The reason contains "Produtividade {date_str}"
        reference = f"daily_{date_str}"
        txs = session.exec(
            select(models.GameXPTransaction).where(
                models.GameXPTransaction.employee_id == employee_id,
                models.GameXPTransaction.reason.contains(reference)
            )
        ).all()
        
        print(f"\nFound {len(txs)} GameXPTransactions:")
        for tx in txs:
            print(f"  - TX ID: {tx.id}, Status: {tx.status}, Amount: {tx.amount}, Reason: {tx.reason}")

if __name__ == "__main__":
    import sys
    emp_id = 442
    date = "2026-01-18"
    diagnose_xp(emp_id, date)
