from sqlmodel import Session, select, func
from models import XPLedger, Employee, GameXPTransaction
from database import engine

def check_ledger():
    with Session(engine) as session:
        # Check V1
        count_v1 = session.exec(select(func.count(XPLedger.id))).one()
        print(f"Total entries in XPLedger (V1): {count_v1}")
        
        # Check V2
        count_v2 = session.exec(select(func.count(GameXPTransaction.id))).one()
        print(f"Total entries in GameXPTransaction (V2): {count_v2}")
        
        if count_v2 > 0:
            last_5 = session.exec(select(GameXPTransaction).order_by(GameXPTransaction.created_at.desc()).limit(5)).all()
            for x in last_5:
                print(f"V2 ID: {x.id}, Emp: {x.employee_id}, Amount: {x.amount}, Date: {x.created_at}")

        # Check total_xp for first active employee
        emp = session.exec(select(Employee).where(Employee.status == 'active').limit(1)).first()
        if emp:
            print(f"Employee {emp.name} (ID {emp.id}) Total XP: {emp.total_xp}")

if __name__ == "__main__":
    check_ledger()
