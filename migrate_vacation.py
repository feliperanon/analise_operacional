import sqlite3

def migrate():
    try:
        print("Connecting to database.db...")
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Add vacation_start
        try:
            print("Attempting to add vacation_start...")
            cursor.execute("ALTER TABLE employee ADD COLUMN vacation_start DATETIME")
            print("Successfully added vacation_start column")
        except sqlite3.OperationalError as e:
            print(f"Skipped vacation_start (likely exists): {e}")
            
        # Add vacation_end
        try:
            print("Attempting to add vacation_end...")
            cursor.execute("ALTER TABLE employee ADD COLUMN vacation_end DATETIME")
            print("Successfully added vacation_end column")
        except sqlite3.OperationalError as e:
            print(f"Skipped vacation_end (likely exists): {e}")

        conn.commit()
        conn.close()
        print("Migration completed.")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
