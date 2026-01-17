

# --- Operational History Routes ---
from datetime import datetime, timedelta, time
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
    """Render the Operational History Page"""
    try:
        require_login(request)
        return templates.TemplateResponse("operational_history.html", {"request": request})
    except Exception as e:
        logger.exception("Error rendering operational history")
        return HTMLResponse(content=f"Error: {e}", status_code=500)

@app.get("/api/operational/routes")
async def api_operational_routes(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = 'date',
    status: Optional[str] = None,
    session: Session = Depends(get_session)
):
    try:
        query = select(models.Route, models.Employee.name, models.Client.name).join(models.Employee).join(models.Client)
        
        # Filtering
        if start_date:
            query = query.where(models.Route.date >= start_date)
        if end_date:
            query = query.where(models.Route.date <= end_date)
            
        if status:
            query = query.where(models.Route.status == status)
            
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    models.Employee.name.ilike(search_pattern),
                    models.Client.name.ilike(search_pattern),
                    models.Route.date.ilike(search_pattern)
                )
            )

        # Sorting
        # Simple Logic: Only Sort by Date desc by default
        query = query.order_by(desc(models.Route.date), desc(models.Route.id))
        
        results = session.exec(query).all()
        
        # Prepare Response
        from zoneinfo import ZoneInfo
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
        
        data = []
        for r, emp_name, client_name in results:
            s_time = r.start_time
            e_time = r.end_time
            
            # Strategy: If time is in the future relative to NOW, assume it's UTC and subtract 3h.
            # Additional Context: If route is 'pending' or 'completed', it CANNOT be in the future.
            # NEW Context: If Start > End (and End exists), likely Start is UTC and End is Local.
            
            def apply_heuristic(time_val, route_status, other_time_val=None, is_start_time=True):
                if time_val is None: return None
                
                # DEBUG Input
                # print(f"DEBUG INPUT: Val={time_val} ({type(time_val)}), Other={other_time_val} ({type(other_time_val)})")
                
                time_str = ""
                if isinstance(time_val, (datetime.time, time)):
                    time_str = time_val.strftime("%H:%M:%S")
                else:
                    time_str = str(time_val).strip()

                try:
                    # Clean input
                    clean_time = time_str.split(".")[0] 
                    parts = clean_time.split(":")
                    if len(parts) == 3: fmt = "%H:%M:%S"
                    elif len(parts) == 2: fmt = "%H:%M"
                    else: return time_str

                    # 2. Construct Aware Datetime
                    dt_obj = datetime.strptime(clean_time, fmt).replace(
                        year=now_br.year, month=now_br.month, day=now_br.day, 
                        tzinfo=ZoneInfo("America/Sao_Paulo")
                    )
                    
                    # 3. Check Consistency with Other Time (Start vs End)
                    force_fix = False
                    if other_time_val:
                        # Parse other time
                        other_str = ""
                        if isinstance(other_time_val, (datetime.time, time)): other_str = other_time_val.strftime("%H:%M:%S")
                        else: other_str = str(other_time_val).strip()
                        o_clean = other_str.split(".")[0]
                        o_parts = o_clean.split(":")
                        o_fmt = "%H:%M:%S" if len(o_parts) == 3 else "%H:%M"
                        dt_other = datetime.strptime(o_clean, o_fmt).replace(year=now_br.year, month=now_br.month, day=now_br.day, tzinfo=ZoneInfo("America/Sao_Paulo"))

                        # Logic: If Start > End (09:00 > 07:53) AND (Start-3h < End) (06:00 < 07:53) -> Fix Start
                        if is_start_time and dt_obj > dt_other:
                            dt_fix = dt_obj - timedelta(hours=3)
                            if dt_fix < dt_other:
                                force_fix = True
                                print(f"DEBUG CONSISTENCY: Fixed Start {clean_time} -> {dt_fix.strftime('%H:%M')} because > End {o_clean}")

                    # 4. Check Window (Future)
                    diff = (dt_obj - now_br).total_seconds()
                    is_future = diff > 0
                    is_started = route_status in ['pending', 'completed']
                    
                    if force_fix or (is_future and (diff < 4 * 3600 or is_started)):
                        new_dt = dt_obj - timedelta(hours=3)
                        res = new_dt.strftime("%H:%M")
                        # print(f"DEBUG FIX: {time_str} -> {res}")
                        return res
                    
                    print(f"DEBUG PASS: {time_str} -> {dt_obj.strftime('%H:%M')} (Diff: {diff})")
                    return dt_obj.strftime("%H:%M")
                    
                except Exception as e:
                    print(f"Timezone Heuristic Error: {e}")
                    return time_str

            s_time = apply_heuristic(s_time, r.status, e_time, is_start_time=True)
            e_time = apply_heuristic(e_time, r.status, None, is_start_time=False)

            data.append({
                "id": r.id,
                "date": r.date,
                "employee_name": emp_name,
                "employee_id": r.employee_id,
                "client_name": client_name,
                "client_id": r.client_id,
                "start_time": s_time,
                "end_time": e_time,
                "tonnage": r.tonnage,
                "status": r.status
            })
            
        return {"routes": data}
        
    except Exception as e:
        logger.exception("Error fetching routes")
        return JSONResponse({"error": str(e)}, status_code=500)

class RouteUpdateModel(BaseModel):
    tonnage: Optional[float] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: Optional[str] = None

@app.put("/api/operational/routes/{route_id}")
async def api_update_route(
    route_id: int, 
    payload: RouteUpdateModel, 
    session: Session = Depends(get_session)
):
    try:
        route = session.get(models.Route, route_id)
        if not route:
            return JSONResponse({"error": "Rota não encontrada"}, status_code=404)
            
        if payload.tonnage is not None:
            route.tonnage = payload.tonnage
        if payload.start_time is not None:
            route.start_time = payload.start_time
        if payload.end_time is not None:
            route.end_time = payload.end_time
        if payload.status is not None:
            route.status = payload.status
            
        session.add(route)
        session.commit()
        return {"success": True}
    except Exception as e:
        logger.exception(f"Error updating route {route_id}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/operational/routes/{route_id}")
async def api_delete_route(route_id: int, session: Session = Depends(get_session)):
    try:
        route = session.get(models.Route, route_id)
        if not route:
            return JSONResponse({"error": "Rota não encontrada"}, status_code=404)
            
        session.delete(route)
        session.commit()
        return {"success": True}
    except Exception as e:
        logger.exception(f"Error deleting route {route_id}")
        return JSONResponse({"error": str(e)}, status_code=500)
