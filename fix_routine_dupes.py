from sqlmodel import Session, select, func
from database import engine
import models
from collections import defaultdict

def fix_dupes():
    with Session(engine) as session:
        print("Scanning for duplicates...")
        
        # specific to emp 415 first to test, or global?
        # Let's do global cleanup as this likely affects others.
        
        all_routines = session.exec(select(models.EmployeeRoutine)).all()
        print(f"Total routines: {len(all_routines)}")
        
        # Group by (employee_id, date)
        grouped = defaultdict(list)
        for r in all_routines:
            grouped[(r.employee_id, r.date)].append(r)
            
        dupes_found = 0
        deleted_count = 0
        
        for key, entries in grouped.items():
            if len(entries) > 1:
                dupes_found += 1
                # Sort by ID descending (keep latest created/updated?)
                # Assuming higher ID = newer
                entries.sort(key=lambda x: x.id, reverse=True)
                
                # Keep the first one (newest), delete the rest
                to_keep = entries[0]
                to_delete = entries[1:]
                
                for d in to_delete:
                    session.delete(d)
                    deleted_count += 1
                    
        print(f"Found {dupes_found} date/employee pairs with duplicates.")
        print(f"Deleting {deleted_count} redundant entries...")
        
        session.commit()
        print("Cleanup done.")

if __name__ == "__main__":
    fix_dupes()
