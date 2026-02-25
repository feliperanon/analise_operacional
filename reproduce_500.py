
import sys
import os
from fastapi.testclient import TestClient
from main import app, require_leader, get_session
from models import Employee

# Mock user
def mock_require_leader():
    return "admin_user"

app.dependency_overrides[require_leader] = mock_require_leader

client = TestClient(app)

print("--- TESTING /admin/equipment/tickets ---")
try:
    response = client.get("/admin/equipment/tickets")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 500:
        print("Traceback content:")
        print(response.text)
    else:
        print("Success or other error.")
except Exception as e:
    print(f"Exception triggering request: {e}")

print("\n--- TESTING /admin/routine/checklists/dashboard ---")
try:
    response = client.get("/admin/routine/checklists/dashboard")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 500:
        print("Traceback content:")
        # In debug mode FastAPI might return traceback, but TestClient raises the exception directly usually?
        # fastAPI test client raises exceptions by default provided allow_server_errors is not False?
        # Actually starlette TestClient raises exceptions.
        pass
    else:
        print("Success or other error.")
except Exception as e:
    print(f"Exception caught during dashboard request: {e}")
    import traceback
    traceback.print_exc()
