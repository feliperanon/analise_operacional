from sqlmodel import Session, select
from database import engine
import models
from collections import Counter

def check_dupes():
    with Session(engine) as session:
        # Check specifically for employee 415 (Antonio)
        emp_id = 415
        with open("debug_cleanup_result.txt", "w") as f:
            stmt = select(models.EmployeeRoutine).where(models.EmployeeRoutine.employee_id == emp_id)
            routines = session.exec(stmt).all()
            
            f.write(f"Checking routines for Employee ID: {emp_id}\n")
            f.write(f"Total entries found: {len(routines)}\n")

            # Check for duplicates by date
            dates = [r.date for r in routines]
            counts = Counter(dates)
            dupes = {d: c for d, c in counts.items() if c > 1}

            f.write(f"Dates with duplicates: {len(dupes)}\n")
            if dupes:
                f.write("Examples of duplicates:\n")
                for d, c in list(dupes.items())[:5]:
                    f.write(f"Date: {d} -> {c} entries\n")
                    
            # Count types
            types = [r.routine for r in routines]
            type_counts = Counter(types)
            f.write(f"Routine Type Counts: {type_counts}\n")


if __name__ == "__main__":
    check_dupes()
