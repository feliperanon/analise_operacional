from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.getcwd())

def fix_revert_endtime(dry_run=True):
    with Session(engine) as session:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"Checking routes for today: {today}")
        
        # Select all routes for today
        stmt = select(models.Route).where(models.Route.date == today)
        routes = session.exec(stmt).all()
        
        count = 0
        fixed = 0
        
        for r in routes:
            if not r.end_time or not r.start_time: continue
            
            try:
                # Check for "Impossible" End Times (Morning Shift context)
                # If End Time is < 06:00 (e.g. 04:53) AND Start Time is > End Time (06:00 > 04:53)
                
                s_dt = datetime.strptime(r.start_time, "%H:%M")
                e_dt = datetime.strptime(r.end_time, "%H:%M")
                
                # Logic: If End Time < 06:00 (04:53) likely it was 07:53 Local.
                # So we add 3h back.
                
                if e_dt.hour < 6:
                     print(f"[CANDIDATE REVERT] ID: {r.id} | Start: {r.start_time} | End: {r.end_time}")
                     
                     if not dry_run:
                         new_e_dt = e_dt + timedelta(hours=3)
                         r.end_time = new_e_dt.strftime("%H:%M")
                         session.add(r)
                         fixed += 1
                         print(f"   -> REVERTED End Time: {r.end_time}")
            except Exception as e:
                print(f"Error: {e}")
                
        if not dry_run:
            session.commit()
            print(f"Committed {fixed} reverts.")
        else:
            print("Dry run finished.")

if __name__ == "__main__":
    dry = "commit" not in sys.argv
    fix_revert_endtime(dry_run=dry)
