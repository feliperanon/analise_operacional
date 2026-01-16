import urllib.request
import urllib.parse
import json

try:
    # Trigger for today 2026-01-16
    url = "http://127.0.0.1:8000/api/game/calc-daily/2026-01-16"
    req = urllib.request.Request(url, method="POST")
    print(f"Calling {url}...")
    with urllib.request.urlopen(req) as response:
        print(f"Status: {response.status}")
        print(response.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
