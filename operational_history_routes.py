
# --- Operational History Routes ---

@app.get("/operational/history", response_class=HTMLResponse)
async def operational_history_page(request: Request):
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
        
        data = []
        for r, emp_name, client_name in results:
            data.append({
                "id": r.id,
                "date": r.date,
                "employee_name": emp_name,
                "employee_id": r.employee_id,
                "client_name": client_name,
                "client_id": r.client_id,
                "start_time": r.start_time,
                "end_time": r.end_time,
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
