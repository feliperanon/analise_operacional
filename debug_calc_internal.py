
from sqlmodel import Session, select
from database import engine
import models
from gamification_engine import calculate_daily_xp
import traceback

def debug_calc(date_str):
    with Session(engine) as session:
        try:
            print(f"--- Debugging calculate_daily_xp for {date_str} ---")
            count = calculate_daily_xp(session, date_str)
            print(f"Success! Created/Updated {count} transactions.")
            session.commit()
        except Exception as e:
            print("FAILED with exception:")
            print(traceback.format_exc())

if __name__ == "__main__":
    debug_calc("2026-01-18")
