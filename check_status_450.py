from sqlmodel import Session, select
from database import engine
from models import Employee
import sys

def check_450():
    sys.stdout.reconfigure(encoding='utf-8')
    with Session(engine) as session:
        emp = session.exec(select(Employee).where(Employee.registration_id == "450")).first() # Assuming 450 is ID or RegID? User said /employees/450, usually that's ID. Let's check both or ID.
        # User url: /employees/450. In FastAPI routes, usually /employees/{id}.
        # So it's ID 450.
        emp = session.exec(select(Employee).where(Employee.id == 450)).first()
        if emp:
            print(f"Employee 450 ({emp.name}): Status={emp.status}")
        else:
            print("Employee 450 not found.")

if __name__ == "__main__":
    check_450()
