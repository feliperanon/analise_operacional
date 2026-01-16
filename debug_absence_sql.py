import sqlite3

def run_debug():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    print("--- Tables ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print(cursor.fetchall())

    print("--- Searching for Weverton ---")
    cursor.execute("SELECT id, name FROM employee WHERE name LIKE '%WEVERTON%'")
    emps = cursor.fetchall()
    
    if not emps:
        print("No employee found.")
        return

    for emp_id, name in emps:
        print(f"Found: {name} (ID: {emp_id})")
        
        # Check DayStatus
        print(f" Checking DayStatus for ID {emp_id}...")
        cursor.execute("SELECT date, shift, status FROM daystatus WHERE employee_id = ? AND status = 'absent'", (emp_id,))
        rows = cursor.fetchall()
        for r in rows:
            print(f"  [DayStatus] Date: {r[0]}, Shift: {r[1]}, Status: {r[2]}")
            
        # Check Events
        print(f" Checking Events for ID {emp_id}...")
        cursor.execute("SELECT date, event_type, text FROM event WHERE employee_id = ? AND (event_type LIKE '%Falta%' OR text LIKE '%Falta%')", (emp_id,))
        rows = cursor.fetchall()
        for r in rows:
            print(f"  [Event] Date: {r[0]}, Type: {r[1]}, Text: {r[2]}")

    conn.close()

if __name__ == "__main__":
    run_debug()
