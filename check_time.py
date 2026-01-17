from datetime import datetime
from zoneinfo import ZoneInfo
import os

try:
    print(f"System Time (Naive): {datetime.now()}")
    print(f"System Time (UTC): {datetime.utcnow()}")
    
    br_tz = ZoneInfo("America/Sao_Paulo")
    print(f"BR Time (ZoneInfo): {datetime.now(br_tz)}")
    
    # Check TZ env var
    print(f"TZ Env Var: {os.environ.get('TZ')}")
    
except Exception as e:
    print(f"Error: {e}")
