import urllib.request
import urllib.error

url = 'http://localhost:8000/routine/report?date=2025-12-28&shift=Manh%C3%A3'

try:
    with urllib.request.urlopen(url) as response:
        print(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    print(e.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
