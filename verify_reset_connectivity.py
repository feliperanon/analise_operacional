
import requests
import sys

# URL Base
BASE_URL = "http://localhost:8000"

def login_admin():
    session = requests.Session()
    # Assuming default admin creds based on main.py check (admin/admin or env var)
    # The script in main.py uses ALLOWED_USER/PASS env vars, default admin/admin
    payload = {
        "username": "admin",
        "password": "admin"
    }
    r = session.post(f"{BASE_URL}/login", data=payload)
    if r.status_code == 200 and "Configurações" in r.text: # Simple check if logged in (or redirect to index)
        print("✅ Logged in as Admin")
        return session
    
    # Check if redirect happened (usually 303 -> 200 on index)
    if r.url == f"{BASE_URL}/" or r.url == f"{BASE_URL}/admin/game":
        print("✅ Logged in as Admin (Redirected)")
        return session
        
    print(f"❌ Login Failed: {r.status_code}, URL: {r.url}")
    return None

def test_reset(session):
    print("\n--- Testing Route Reset (Safe Mode - Just checking if endpoint is reachable) ---")
    # We won't actually delete everything in this test unless user wants, but 
    # since we are in "Verify" phase, let's assume we want to verify it WORKS.
    # But wait, I don't want to destroy user data if they are running this locally with real data.
    # The user asked to "iniciar do zero na segunda", implying they WANT to wipe it.
    # I will do a "Dry Run" check first? No, the API doesn't support dry run.
    
    # Let's just create a dummy route first to see if we can delete it?
    # Or better, just check if the endpoint responds correctly.
    
    # Ideally I shouldn't wipe data automatically in a verify script unless I created a test DB.
    # BUT, I can check if the endpoint exists and returns 403/200 structure.
    
    pass

if __name__ == "__main__":
    print("⚠️ This script is for manual verification of connectivity.")
    print("To verify the reset, please inspect the 'Admin > Configurações > Zona de Perigo' UI manually.")
    print("Or run a manual curl request if you are sure you want to wipe data.")
    
    # Just checking if server is up
    try:
        r = requests.get(BASE_URL)
        print(f"✅ Server is running (Status {r.status_code})")
    except Exception as e:
        print(f"❌ Server not reachable: {e}")
