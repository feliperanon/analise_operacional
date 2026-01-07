
from sqlmodel import Session, select
from database import engine
from models import DailyOperation
from datetime import datetime

def check_db():
    print("Checking DB connection...")
    try:
        with Session(engine) as session:
            # Try to fetch one op
            stmt = select(DailyOperation).limit(1)
            result = session.exec(stmt).first()
            print("Query Successful.")
            if result:
                print(f"Found op: {result.date} - {result.shift}")
            else:
                print("No operations found, but query worked.")
    except Exception as e:
        print(f"DB Error: {e}")

if __name__ == "__main__":
    check_db()
