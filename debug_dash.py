import sys
import os
from datetime import datetime
from sqlmodel import select, Session
from database import get_session, engine
import models
import json

def test_query():
    print("Starting Query Test...")
    with Session(engine) as session:
        # Get "Jonathan" or first employee
        emp = session.exec(select(models.Employee)).first()
        if not emp:
            print("No employees found.")
            return

        print(f"Testing for Employee: {emp.name} (ID: {emp.id})")
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Replicate the stmt
        stmt = (
            select(models.Route, models.Client.name)
            .join(models.Client, models.Route.client_id == models.Client.id) 
            .where(
                models.Route.employee_id == emp.id,
                models.Route.date == today_str,
                models.Route.status == "pending"
            )
        )
        
        try:
            results = session.exec(stmt).all()
            print(f"Query returned {len(results)} rows.")
            
            # Test unpacking
            active_routes_list = []
            for r, c_name in results:
                print(f" - Route {r.id}: Client={c_name}")
                active_routes_list.append({
                    "id": r.id,
                    "client_name": c_name,
                    "tonnage": r.tonnage,
                    "start_time": r.start_time
                })
            
            print("JSON Dump Test:")
            print(json.dumps(active_routes_list))
            print("SUCCESS: Logic is sound.")
            
        except Exception as e:
            print(f"FAILURE: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_query()
