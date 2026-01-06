import os
from sqlmodel import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get Database URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fallback to local sqlite if no env var (though in this environment it likely exists)
    DATABASE_URL = "sqlite:///./database.db"
    
print(f"Connecting to: {DATABASE_URL}")

engine = create_engine(DATABASE_URL)

def apply_migration():
    print("Applying XP Migration...")
    try:
        with open("migration_add_xp.sql", "r", encoding="utf-8") as f:
            sql_content = f.read()
            
        statements = [s.strip() for s in sql_content.split(';') if s.strip()]
        
        with engine.connect() as connection:
            for statement in statements:
                print(f"Executing: {statement}...")
                try:
                    connection.execute(text(statement))
                    connection.commit()
                    print("✅ Success")
                except Exception as e:
                    print(f"⚠️ Error (column might already exist): {e}")
                    
    except Exception as e:
        print(f"❌ Critical Error: {e}")

if __name__ == "__main__":
    apply_migration()
