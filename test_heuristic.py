
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Simulate the Logic in operational_history_routes.py
now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))

def apply_heuristic(time_str):
    if not time_str: return time_str
    try:
        # Clean input
        clean_time = time_str.split(".")[0] 
        
        # 1. Format
        parts = clean_time.split(":")
        if len(parts) == 3: fmt = "%H:%M:%S"
        elif len(parts) == 2: fmt = "%H:%M"
        else: return "FORMAT_ERR"

        # 2. Construct Aware Datetime
        dt_obj = datetime.strptime(clean_time, fmt).replace(
            year=now_br.year, month=now_br.month, day=now_br.day, 
            tzinfo=ZoneInfo("America/Sao_Paulo")
        )
        
        # 3. Diff
        diff = (dt_obj - now_br).total_seconds()
        
        # print(f"Testing {time_str}:")
        # print(f"  Now BR: {now_br}")
        # print(f"  Target: {dt_obj}")
        # print(f"  Diff Sec: {diff}")
        
        # 4. Check Window
        if diff > 0 and diff < 4 * 3600:
            new_dt = dt_obj - timedelta(hours=3)
            return new_dt.strftime("%H:%M")
        
        return dt_obj.strftime("%H:%M")
        
    except Exception as e:
        return f"ERROR: {e}"

# Test Cases
print(f"--- TEST HEURISTIC ---")
print(f"Result 09:00 (UTC stored?): {apply_heuristic('09:00')}")
print(f"Result 09:00:00 (UTC with sec?): {apply_heuristic('09:00:00')}")
print(f"Result 09:00:05.123 (Micros?): {apply_heuristic('09:00:05.123')}")
print(f"Result 06:00 (Already Local?): {apply_heuristic('06:00')}")
