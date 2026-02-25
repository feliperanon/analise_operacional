
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"

print(f"DEBUG: Script Location: {BASE_DIR}")
print(f"DEBUG: Env Path: {env_path}")
print(f"DEBUG: Env Path Exists? {env_path.exists()}")

# Try loading without override first
load_dotenv(dotenv_path=env_path)
print(f"DEBUG: [No Override] SMTP_HOST='{os.getenv('SMTP_HOST')}'")

# Try loading WITH override
load_dotenv(dotenv_path=env_path, override=True)
print(f"DEBUG: [With Override] SMTP_HOST='{os.getenv('SMTP_HOST')}'")

# Read file manually to confirm content
try:
    with open(env_path, 'r', encoding='utf-8') as f:
        print("DEBUG: Raw .env content snippet:")
        print(f.read()[:200])
except Exception as e:
    print(f"ERROR reading .env: {e}")
