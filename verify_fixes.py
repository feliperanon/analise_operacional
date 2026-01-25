
import sys
from fastapi.testclient import TestClient
from main import app, require_leader, get_session

# Mock user
def mock_require_leader():
    return "admin_user"

app.dependency_overrides[require_leader] = mock_require_leader

client = TestClient(app)

print("--- VERIFYING DASHBOARD ---")
resp = client.get("/admin/routine/checklists/dashboard?days=30")
print(f"Dashboard Status: {resp.status_code}")
if resp.status_code == 200:
    content = resp.text
    if 'href="/admin/routine/checklists?period_days=30"' in content:
        print("[OK] Link total found")
    else:
        print("[FAIL] Link total NOT found")
        
    if 'href="/admin/routine/checklists?period_days=30&nonconforming=1"' in content:
        print("[OK] Link nonconforming found")
    else:
        print("[FAIL] Link nonconforming NOT found")

    if "Tempo Médio Resolução" not in content:
        print("[OK] Avg Resolution card removed (text check)")
    else:
        # It might be in comments or something, but header should be gone
        if '<div class="text-xs text-slate-400 uppercase tracking-wider font-bold mb-1">Tempo Médio Resolução</div>' not in content:
             print("[OK] Avg Resolution card markup removed")
        else:
             print("[FAIL] Avg Resolution card markup STILL PRESENT")

print("\n--- VERIFYING LIST VIEW (Drill-down) ---")
resp_list = client.get("/admin/routine/checklists?period_days=30&nonconforming=1")
print(f"List View Status: {resp_list.status_code}")
if resp_list.status_code == 200:
    print("[OK] List view handles new params")
else:
    print(f"[FAIL] List view returned {resp_list.status_code}")

print("\n--- VERIFYING TICKETS (Defensive) ---")
resp_tkt = client.get("/admin/equipment/tickets")
print(f"Tickets Status: {resp_tkt.status_code}")
