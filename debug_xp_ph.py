from sqlmodel import Session, select
from database import engine
from models import Employee, GameXPTransaction, Route

def check_xp_status(emp_id):
    with Session(engine) as session:
        # Check Employee
        emp = session.get(Employee, emp_id)
        if not emp:
            print(f"Employee {emp_id} not found")
            return

        print(f"Checking XP for: {emp.name} (ID: {emp.id})")
        
        # Check Today's Routes
        routes = session.exec(select(Route).where(Route.employee_id == emp_id, Route.status == "completed")).all()
        print(f"Routes Completed: {len(routes)}")
        for r in routes:
            print(f" - Route {r.id}: {r.tonnage}kg, Start: {r.start_time}, End: {r.end_time}")

        # Check XP Transactions
        txs = session.exec(select(GameXPTransaction).where(GameXPTransaction.employee_id == emp_id)).all()
        print(f"\nXP Transactions ({len(txs)}):")
        for tx in txs:
            print(f" - ID {tx.id} | Amount: {tx.amount} | Status: {tx.status} | Reason: {tx.reason} | Created: {tx.created_at}")

        if not txs:
            print("No XP transactions found.")

if __name__ == "__main__":
    check_xp_status(504) # PH ID provided by user
