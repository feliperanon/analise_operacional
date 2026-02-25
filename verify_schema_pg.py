from database import engine
from sqlalchemy import text

def verify_columns():
    with engine.connect() as conn:
        print(f"Checking columns in DB: {engine.url}")
        
        # Query information_schema for equipmentticket columns
        sql = text("SELECT column_name FROM information_schema.columns WHERE table_name = 'equipmentticket'")
        result = conn.execute(sql)
        columns = [row[0] for row in result]
        
        print(f"Found {len(columns)} columns: {columns}")
        
        required = ["maintenance_email_sent_at", "maintenance_email_error", "closed_at", "closed_by"]
        missing = [c for c in required if c not in columns]
        
        if missing:
            print(f"MISSING columns: {missing}")
        else:
            print("ALL required columns are PRESENTS.")

if __name__ == "__main__":
    verify_columns()
