from sqlmodel import Session, select, func
from database import engine
from models import Employee

def check_shifts():
    with Session(engine) as session:
        # Get distinct shifts
        statement = select(Employee.work_shift).distinct()
        shifts = session.exec(statement).all()
        print(f"Distinct Shifts in DB: {shifts}")
        
        # Count per shift
        for s in shifts:
            count = session.exec(select(func.count(Employee.id)).where(Employee.work_shift == s)).one()
            print(f"Shift '{s}': {count} employees")

if __name__ == "__main__":
    check_shifts()
