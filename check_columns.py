from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'gameachievement'"))
    rows = result.fetchall()
    print(f"Found {len(rows)} columns:")
    for row in rows:
        print(f"  - {row[0]}")
