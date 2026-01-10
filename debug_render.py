from fastapi.templating import Jinja2Templates
from fastapi import Request
import json

templates = Jinja2Templates(directory="c:/Projeto/analise_operacional/templates")

def test_render():
    context = {
        "request": {"url": "http://test/mobile/dashboard"},
        "employee": {"name": "Test User", "registration_id": "123", "total_xp": 1500},
        "clients": [{"id": 1, "name": "Client A"}],
        "active_routes": json.dumps([{"id": 10, "client_name": "Client A", "start_time": "10:00", "tonnage": 500}]),
        "completed_routes": json.dumps([]),
        "chart_labels": json.dumps(["A", "B"]),
        "chart_daily_kg": json.dumps([100, 200]),
        "chart_daily_kgh": json.dumps([10, 20]),
        "chart_bg_colors": json.dumps(["red", "blue"]),
        "gamification": {
            "current_level": {"name": "Novato", "badge": "b1.png"},
            "next_level": {"name": "Aprendiz", "min_xp": 2000},
            "progress_percent": 75,
            "total_xp": 1500
        }
    }
    
    try:
        # Simulate render
        output = templates.get_template("mobile/dashboard.html").render(context)
        print("Render Success!")
        print("--- Snippet ---")
        print(output[:500])
        print("--- Script Block ---")
        # Find script block
        start = output.find("dashboardController")
        if start != -1:
            print(output[start:start+500])
        else:
            print("WARNING: dashboardController not found in output")
            
    except Exception as e:
        print(f"Render FAILED: {e}")

if __name__ == "__main__":
    test_render()
