from database import get_session
from gamification_engine import calculate_daily_xp

def run_fix():
    session = next(get_session())
    print("🔧 Executing Manual XP Calculation Backfill...")
    
    dates = ["2026-01-13", "2026-01-14", "2026-01-15"]
    
    for d in dates:
        print(f"👉 Processing {d}...")
        try:
            count = calculate_daily_xp(session, d)
            print(f"   ✅ Created {count} transactions for {d}")
        except Exception as e:
            print(f"   ❌ Error processing {d}: {e}")

if __name__ == "__main__":
    run_fix()
