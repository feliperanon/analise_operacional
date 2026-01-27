
@app.get("/admin/equipment/tickets/{ticket_id}", response_class=HTMLResponse)
async def admin_equipment_ticket_detail(
    request: Request,
    ticket_id: int,
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    ticket = session.get(models.EquipmentTicket, ticket_id)
    if not ticket:
        return RedirectResponse(
            url="/admin/equipment/tickets?message=Chamado+n%C3%A3o+encontrado&level=error", 
            status_code=303
        )
    
    employee = session.get(models.Employee, ticket.employee_id)
    
    # Fetch Timeline Events
    events = session.exec(
        select(models.Event)
        .where(models.Event.reference_type == "ticket")
        .where(models.Event.reference_id == ticket.id)
        .order_by(models.Event.timestamp.asc())
    ).all()
    
    ticket_data = {
        "ticket": ticket,
        "employee": employee,
        "created_at_br": fmt_datetime_br(ticket.created_at),
        "closed_at_br": fmt_datetime_br(ticket.closed_at) if ticket.closed_at else None,
        "image_urls": [f"/static/uploads/tickets/{img}" for img in (ticket.images or [])],
        "events": events
    }

    return templates.TemplateResponse(
        "admin_equipment_ticket_detail.html",
        {
            "request": request,
            "data": ticket_data
        }
    )

@app.post("/admin/equipment/tickets/{ticket_id}/delete", response_class=RedirectResponse)
async def admin_equipment_ticket_delete(
    request: Request,
    ticket_id: int,
    confirm_delete: bool = Form(False),
    session: Session = Depends(get_session),
    user=Depends(require_leader)
):
    ticket = session.get(models.EquipmentTicket, ticket_id)
    if not ticket:
         return RedirectResponse(url="/admin/equipment/tickets?message=Erro&level=error", status_code=303)
         
    if not confirm_delete:
        return RedirectResponse(
            url=f"/admin/equipment/tickets/{ticket_id}?message=Confirme+a+exclus%C3%A3o&level=error", 
            status_code=303
        )
        
    session.add(models.Event(
        timestamp=datetime.now(ZoneInfo("America/Sao_Paulo")),
        text=f"Chamado #{ticket.id} EXCLUÍDO por {user}.",
        type="ticket_delete",
        category="audit",
        reference_type="ticket_deleted",
        reference_id=ticket.id
    ))
    
    session.delete(ticket)
    session.commit()
    
    return RedirectResponse(
        url="/admin/equipment/tickets?message=Chamado+exclu%C3%ADdo+com+sucesso", 
        status_code=303
    )
