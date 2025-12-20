from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime

def test_query():
    print("Testing DB Connection and Schema...")
    with Session(engine) as session:
        try:
            # 1. Test Select Route with shift
            print("1. Querying Routes with shift...")
            date = datetime.now().strftime("%Y-%m-%d")
            shift = "Manhã"
            routes = session.exec(
                select(models.Route)
                .where(models.Route.date == date)
                .where(models.Route.shift == shift)
            ).all()
            print(f"Routes query success. Found {len(routes)} routes.")
            for r in routes:
                print(r)
                
        except Exception as e:
            print(f"CRITICAL ERROR IN QUERY: {e}")

if __name__ == "__main__":
    test_query()
