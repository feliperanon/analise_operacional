from sqlmodel import select, Session
from database import engine
import models
from datetime import datetime

def test_query():
    print("Testing employee query...")
    try:
        with Session(engine) as session:
            # Replicating the query from smart_flow_page
            employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
            print(f"Successfully fetched {len(employees)} employees.")
            if employees:
                e = employees[0]
                print(f"Sample Employee: {e.name}, Vacation Start: {e.vacation_start}")
    except Exception as e:
        print(f"Query FAILED: {e}")

if __name__ == "__main__":
    test_query()
