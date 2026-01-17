import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

def run_fix():
    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found")
        return
        
    # Fix postgres:// -> postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    print(f"Connecting to DB...")
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        # 1. Find Weverton
        print("--- Check Weverton ---")
        result = conn.execute(text("SELECT id, name FROM employee WHERE name ILIKE '%WEVERTON%'"))
        emp = result.fetchone()
        
        if not emp:
            print("Weverton not found in Postgres!")
            return
            
        print(f"Found: {emp[1]} (ID: {emp[0]})")
        emp_id = emp[0]
        
        # 2. Check EmployeeRoutine for Absence
        # Assuming table is 'employeeroutine'
        print("--- Checking employeeroutine ---")
        try:
            query = text("SELECT id, date, routine FROM employeeroutine WHERE employee_id = :eid AND (routine = 'absent' OR routine = 'falta')")
            rows = conn.execute(query, {"eid": emp_id}).fetchall()
            
            if not rows:
                print("No absence found in employeeroutine.")
            else:
                for r in rows:
                    print(f"FOUND: ID={r[0]}, Date={r[1]}, Routine={r[2]}")
                    # Delete
                    del_query = text("DELETE FROM employeeroutine WHERE id = :rid")
                    conn.execute(del_query, {"rid": r[0]})
                    conn.commit()
                    print("Deleted record.")
        except Exception as e:
            print(f"Error checking employeeroutine: {e}")
            
        # 3. Check Event for Absence (Just in case)
        print("--- Checking event ---")
        try:
            # Note: Event in Postgres might lack employee_id if columns drifted, but likely not if app relies on it.
            # But earlier code implied EmployeeRoutine is the source for 'people_intelligence'.
            pass 
        except Exception as e:
            print(e)

if __name__ == "__main__":
    run_fix()
