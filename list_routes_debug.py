
from main import app
import inspect

print("Listing all routes:")
for route in app.routes:
    if hasattr(route, "path"):
        print(f"Path: {route.path} | Name: {route.name} | Func: {route.endpoint.__name__}")
