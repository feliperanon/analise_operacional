import sys
from datetime import datetime
import json
from sqlmodel import select, Session
from database import engine
import models

with Session(engine) as session:
    # 1. Get Employee (Safe)
    employee = session.exec(select(models.Employee)).first()
    if not employee:
        print("No employee found.")
        sys.exit(0)
    
    print(f"Testing for employee: {employee.name} (ID: {employee.id})")
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 2. Completed Routes Logic (Copy-Paste from main.py)
    completed_routes_stmt = (
        select(models.Route, models.Client.name)
        .join(models.Client, models.Route.client_id == models.Client.id) 
        .where(
            models.Route.employee_id == employee.id,
            models.Route.date == today_str,
            models.Route.status == "completed"
        )
        .order_by(models.Route.end_time.desc())
    )
    completed_routes_result = session.exec(completed_routes_stmt).all()
    
    completed_routes_list = []
    print(f"Found {len(completed_routes_result)} completed routes.")
    
    for r, c_name in completed_routes_result:
        duration_str = "00:00"
        perf_str = "0,00 Kg/h"
        
        print(f"Processing Route {r.id}: Start={r.start_time}, End={r.end_time}, Tons={r.tonnage}")
        
        if r.start_time and r.end_time:
            try:
                s = datetime.strptime(r.start_time, "%H:%M")
                e = datetime.strptime(r.end_time, "%H:%M")
                diff_sec = (e - s).total_seconds()
                
                # Duration
                h_dur = int(diff_sec // 3600)
                m_dur = int((diff_sec % 3600) // 60)
                duration_str = f"{h_dur:02d}h {m_dur:02d}m"
                
                # Metric: Kg/h
                t = r.tonnage if r.tonnage else 0
                hours_decimal = diff_sec / 3600.0
                if hours_decimal <= 0: hours_decimal = 0.016 # 1 min
                
                kgh = t / hours_decimal
                perf_str = f"{kgh:,.2f} Kg/h".replace(",", "X").replace(".", ",").replace("X", ".")
                print(f"  -> Calc: {kgh} Kg/h -> Str: {perf_str}")
                
            except Exception as ex:
                print(f"Error calc history: {ex}")
                pass

        completed_routes_list.append({
            "id": r.id,
            "client_name": c_name,
            "tonnage": r.tonnage,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "duration": duration_str,
            "performance": perf_str
        })
    
    print("Serialization Test:")
    out = json.dumps(completed_routes_list)
    print(out[:100] + "...")
    print("Success!")
