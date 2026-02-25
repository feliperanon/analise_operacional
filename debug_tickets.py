
import sys
from fastapi.testclient import TestClient
from main import app, require_leader, get_session

# Mock user
def mock_require_leader():
    return "admin_user"

app.dependency_overrides[require_leader] = mock_require_leader

client = TestClient(app)

print("--- DEBUGGING TICKETS 500 ---")
try:
    resp_tkt = client.get("/admin/equipment/tickets")
    print(f"Tickets Status: {resp_tkt.status_code}")
    if resp_tkt.status_code == 500:
         print(resp_tkt.text)
except Exception as e:
    import traceback
    traceback.print_exc()
