
from fastapi.testclient import TestClient
from main import app, require_login, get_session
import models
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlmodel import Session, select

# Mock require_login to return an employee
def mock_require_login(request):
    return {"type": "employee", "id": 1}

app.dependency_overrides[require_login] = mock_require_login

client = TestClient(app)

print("--- VERIFYING CHECKLIST PAGE (CLEANUP) ---")
resp = client.get("/mobile/routine/checklist")
print(f"Checklist Page: {resp.status_code}")
if resp.status_code == 200:
    content = resp.text
    if "/mobile/routine/history" in content and "/mobile/equipment/tickets" in content:
        print("[OK] Quick Access Links found")
    else:
        print("[FAIL] Quick Access Links NOT found")
    
    if "Histórico (7 dias)" in content:
        print("[FAIL] History block still present")
    else:
        print("[OK] History block removed")

print("\n--- VERIFYING HISTORY PAGE ---")
resp_hist = client.get("/mobile/routine/history")
print(f"History Page: {resp_hist.status_code}")
if resp_hist.status_code == 200:
    print("[OK] Page loaded")
    if "Histórico Recente" in resp_hist.text:
        print("[OK] Header found")

print("\n--- VERIFYING TICKETS PAGE ---")
resp_tkt = client.get("/mobile/equipment/tickets")
print(f"Tickets Page: {resp_tkt.status_code}")
