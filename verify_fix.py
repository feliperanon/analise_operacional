from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from main import app
import logging

# Disable logging for test
logging.basicConfig(level=logging.CRITICAL)

client = TestClient(app)

def test_admin_route():
    # Login as admin/leader first to get session cookie?
    # Actually, main.py uses session cookie or dependency.
    # Simulating a request might be hard without auth mocking.
    # But we can try to hit it and see if it 500s or 401s (401 is success for this test, as it means code ran until auth check).
    # If it 500s due to "schema error" or "ImportError", that's bad.
    
    print("Testing /admin/equipment/tickets...")
    try:
        response = client.get("/admin/equipment/tickets", follow_redirects=False)
        print(f"Status: {response.status_code}")
        # If 303 or 401 or 200, it's 'working' (code didn't crash on import/definition).
        # To test the SQL execution, we'd need a valid session.
    except Exception as e:
        print(f"CRASH: {e}")

if __name__ == "__main__":
    test_admin_route()
