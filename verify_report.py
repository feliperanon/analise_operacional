
import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

def test_save_and_report():
    print("1. Saving Routine with Mock Logs...")
    
    date = datetime.now().strftime("%Y-%m-%d")
    shift = "Manhã"
    
    # Mock Log Payload
    payload = {
        "status": "open",
        "rating": 5,
        "logs": [
            {
                "context": {"date": date, "shift": shift, "type": "snapshot"},
                "kpis": {"total_target": 100, "total_present": 95, "total_gap": 5},
                "sectors": [
                    {"label": "Test Sector", "target": 10, "present_count": 8, "gap": 2}
                ],
                "people": []
            },
            {
                "type": "event",
                "timestamp": datetime.now().isoformat(),
                "payload": {"action": "test_event"}
            }
        ]
    }
    
    import time
    
    # Save
    print("   Attempting to save (retrying if connection refused)...")
    for i in range(5):
        try:
            res = requests.post(f"{BASE_URL}/routine/update", json=payload, params={"date": date, "shift": shift})
            break
        except requests.exceptions.ConnectionError:
            print(f"   ... Connection refused, retrying in 2s ({i+1}/5)")
            time.sleep(2)
    else:
        print("   ❌ Save Failed: Could not connect to backend.")
        return

    if res.status_code == 200:
            print("   ✅ Save Successful")
        else:
            print(f"   ❌ Save Failed: {res.status_code} - {res.text}")
            return

        # Report
        print("\n2. Fetching Report...")
        res_report = requests.get(f"{BASE_URL}/routine/report", params={"date": date, "shift": shift})
        
        if res_report.status_code == 200:
            print("   ✅ Report Generated Successfully")
            if "Relatório Operacional" in res_report.text:
                 print("   ✅ Content Verified (Title found)")
            if "Test Sector" in res_report.text:
                 print("   ✅ Content Verified (Snapshot data found)")
            
            # Write to file for manual inspection if needed
            with open("report_test.html", "w", encoding="utf-8") as f:
                f.write(res_report.text)
            print("   📄 Saved report_test.html")
            
        else:
            print(f"   ❌ Report Failed: {res_report.status_code} - {res_report.text}")

    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    test_save_and_report()
