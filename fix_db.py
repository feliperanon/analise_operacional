from sqlmodel import create_engine, text
import os

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url)

with engine.connect() as connection:
    try:
        # Check if column exists pragma logic or just try add
        # SQLite doesn't support IF NOT EXISTS in ADD COLUMN easily, so we typically wrap in try/except or check first.
        # Simple hack: Select shift from route limit 1. If fails, add it.
        try:
            connection.execute(text("SELECT shift FROM route LIMIT 1"))
            print("Column 'shift' already exists.")
        except Exception:
            print("Column 'shift' missing. Adding it...")
            connection.execute(text("ALTER TABLE route ADD COLUMN shift VARCHAR DEFAULT 'Manhã'"))
            connection.commit()
            print("Column added.")
            
    except Exception as e:
        print(f"Error: {e}")
