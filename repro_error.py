
import urllib.request
import urllib.parse
import http.cookiejar

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Login
login_data = urllib.parse.urlencode({"username": "feliperanon", "password": "571232ce"}).encode()
print("Logging in...")
try:
    resp = opener.open("http://127.0.0.1:8000/login", data=login_data)
    print(f"Login status: {resp.getcode()}")
except Exception as e:
    print(f"Login failed: {e}")

# Access Flow
print("Accessing Flow...")
try:
    resp = opener.open("http://127.0.0.1:8000/flow")
    print(f"Flow status: {resp.getcode()}")
    print(resp.read().decode()[:500])
except urllib.error.HTTPError as e:
    print(f"Flow failed: {e.code}")
    print(e.read().decode()[:500])
except Exception as e:
    print(f"Flow error: {e}")
