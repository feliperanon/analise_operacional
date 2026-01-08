from sqlmodel import Session, select, col
from database import engine
import models
from collections import defaultdict

def fast_fix():
    with Session(engine) as session:
        print("Fetching all routines...")
        all_routines = session.exec(select(models.EmployeeRoutine.id, models.EmployeeRoutine.employee_id, models.EmployeeRoutine.date)).all()
        print(f"Total entries: {len(all_routines)}")
        
        # Group in memory
        grouped = defaultdict(list)
        for r_id, emp_id, date in all_routines:
            grouped[(emp_id, date)].append(r_id)
            
        ids_to_delete = []
        for key, ids in grouped.items():
            if len(ids) > 1:
                # Sort descending (keep largest ID = newest)
                ids.sort(reverse=True)
                ids_to_delete.extend(ids[1:])
                
        count = len(ids_to_delete)
        print(f"Found {count} duplicate IDs to delete.")
        
        if count > 0:
            # Batch delete
            # SQLModel doesn't support bulk delete easily on list of IDs with `session.delete`
            # We use delete statement
            # Delete in chunks of 500 to avoid query size limits
            chunk_size = 500
            for i in range(0, count, chunk_size):
                chunk = ids_to_delete[i:i+chunk_size]
                statement = log_delete = models.EmployeeRoutine.__table__.delete().where(models.EmployeeRoutine.id.in_(chunk))
                session.execute(statement)
                print(f"Deleted chunk {i}-{i+len(chunk)}")
            
            session.commit()
            print("FAST cleanup completed.")
        else:
            print("No duplicates found.")

if __name__ == "__main__":
    fast_fix()
