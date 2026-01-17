import sys
import os

sys.path.append(os.getcwd())

from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime, timedelta

def fix_today_utc(dry_run=True):
    with Session(engine) as session:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"Checking routes for today: {today}")
        
        # Select all routes for today
        stmt = select(models.Route).where(models.Route.date == today)
        routes = session.exec(stmt).all()
        
        count = 0
        fixed = 0
        
        print(f"Found {len(routes)} routes.")
        
        for r in routes:
            s_time = r.start_time
            e_time = r.end_time
            
            needs_fix = False
            
            # Logic: If Start Time is between 08:30 and 10:30 (Likely UTC for 05:30-07:30)
            # And Status is NOT 'open' (meaning it was created/completed)
            # Note: 08:51 fits here.
            
            try:
                if not s_time: continue
                
                # Parse
                parts = s_time.split(":")
                h = int(parts[0])
                
                # UTC Window for Morning Shift (05:00 - 08:00 Local -> 08:00 - 11:00 UTC)
                if 8 <= h <= 11:
                    # Candidate for fix
                    # Show details
                    emp = session.get(models.Employee, r.employee_id)
                    emp_name = emp.name if emp else "Unknown"
                    
                    print(f"[CANDIDATE] ID: {r.id} | Emp: {emp_name} | Start: {s_time} | End: {e_time}")
                    
                    if not dry_run:
                        # Fix Start
                        dt_s = datetime.strptime(s_time, "%H:%M")
                        new_s = (dt_s - timedelta(hours=3)).strftime("%H:%M")
                        r.start_time = new_s
                        
                        # Fix End if exists
                        if e_time:
                            dt_e = datetime.strptime(e_time, "%H:%M")
                            new_e = (dt_e - timedelta(hours=3)).strftime("%H:%M")
                            r.end_time = new_e
                            
                        session.add(r)
                        fixed += 1
                        print(f"   -> FIXED: Start {new_s} | End: {r.end_time}")
                        
            except Exception as e:
                print(f"Error processing route {r.id}: {e}")
                
        if not dry_run:
            session.commit()
            print(f"Commited {fixed} fixes.")
        else:
            print("Dry Run Completed. No changes made.")

if __name__ == "__main__":
    import sys
    dry = "commit" not in sys.argv
    fix_today_utc(dry_run=dry)
