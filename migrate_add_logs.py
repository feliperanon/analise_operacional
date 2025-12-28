import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

# Get database URL from environment
database_url = os.environ.get("DATABASE_URL")

if not database_url:
    print("ERROR: DATABASE_URL not found in environment variables")
    print("Using local SQLite - migration not needed for PostgreSQL")
    exit(0)

# Fix for Render/Heroku using postgres:// instead of postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

print(f"Connecting to PostgreSQL database...")

try:
    # Connect to PostgreSQL
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    
    # Add logs column if it doesn't exist
    print("Adding 'logs' column to 'dailyoperation' table...")
    cursor.execute("""
        ALTER TABLE dailyoperation 
        ADD COLUMN IF NOT EXISTS logs JSON;
    """)
    
    conn.commit()
    print("✓ Migration completed successfully!")
    print("✓ Column 'logs' added to 'dailyoperation' table")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"✗ Migration failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
