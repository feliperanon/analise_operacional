from sqlmodel import Session, create_engine, text
from models import EmployeeRoutine, XPLedger

# Database Connection
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url)

def migrate():
    with Session(engine) as session:
        print("Starting Ledger Migration...")
        
        # 1. Add columns to EmployeeRoutine (Reopen Audit)
        try:
            session.exec(text("ALTER TABLE employeeroutine ADD COLUMN reopened_at DATETIME"))
            print("- Added 'reopened_at' column")
        except Exception as e:
            print(f"- 'reopened_at' exists or error: {e}")

        try:
            session.exec(text("ALTER TABLE employeeroutine ADD COLUMN reopened_by VARCHAR"))
            print("- Added 'reopened_by' column")
        except Exception as e:
            print(f"- 'reopened_by' exists or error: {e}")

        try:
            session.exec(text("ALTER TABLE employeeroutine ADD COLUMN reopened_reason VARCHAR"))
            print("- Added 'reopened_reason' column")
        except Exception as e:
            print(f"- 'reopened_reason' exists or error: {e}")

        # 2. Create XPLedger Table
        try:
            session.exec(text("""
                CREATE TABLE IF NOT EXISTS xpledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    datetime DATETIME NOT NULL,
                    type VARCHAR NOT NULL,
                    points FLOAT NOT NULL,
                    reference_id VARCHAR,
                    note VARCHAR,
                    FOREIGN KEY(employee_id) REFERENCES employee(id)
                )
            """))
            print("- Created 'xpledger' table")
            
            # Index on employee_id
            session.exec(text("CREATE INDEX IF NOT EXISTS ix_xpledger_employee_id ON xpledger (employee_id)"))
            # Index on type
            session.exec(text("CREATE INDEX IF NOT EXISTS ix_xpledger_type ON xpledger (type)"))
            print("- Created indices for XPLedger")
            
        except Exception as e:
            print(f"Error creating XPLedger: {e}")

        session.commit()
        print("Migration Completed!")

if __name__ == "__main__":
    migrate()
