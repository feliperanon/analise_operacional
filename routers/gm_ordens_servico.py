# -*- coding: utf-8 -*-
"""Rotas GM: ordens de serviço, KPIs e APIs de execução para líderes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, desc, select

import models
from database import get_session
from deps.ordens_auth import require_gerente, require_leader_ordens
from services.operational_task_executions import generate_executions_for_task

logger = logging.getLogger(__name__)
router = APIRouter(tags=["gm-ordens-servico"])
templates = Jinja2Templates(directory="templates")


@router.post("/api/gm/ordens-servico", response_class=JSONResponse)
async def api_gm_create_ordem(request: Request, session: Session = Depends(get_session)):
    """Criar nova ordem de serviço."""
    user = require_gerente(request)
    try:
        body = await request.json()
        title = (body.get("title") or "").strip()
        if not title:
            return JSONResponse({"error": "Título é obrigatório"}, status_code=400)

        description = (body.get("description") or "").strip() or None
        category = (body.get("category") or "geral").strip().lower()
        priority = (body.get("priority") or "medium").strip().lower()
        if priority not in ("low", "medium", "high"):
            priority = "medium"

        recurrence_type = (body.get("recurrence_type") or "once").strip().lower()
        if recurrence_type not in ("once", "daily", "weekly", "monthly"):
            recurrence_type = "once"

        recurrence_days = body.get("recurrence_days") or []
        if isinstance(recurrence_days, list):
            recurrence_days = [int(x) for x in recurrence_days if str(x).isdigit()]
        else:
            recurrence_days = []

        recurrence_day_of_month = None
        if body.get("recurrence_day_of_month"):
            try:
                recurrence_day_of_month = int(body["recurrence_day_of_month"])
                if recurrence_day_of_month < 1 or recurrence_day_of_month > 31:
                    recurrence_day_of_month = None
            except Exception:
                pass

        scheduled_time = (body.get("scheduled_time") or "").strip() or None
        estimated_duration = body.get("estimated_duration_minutes")
        if estimated_duration:
            try:
                estimated_duration = int(estimated_duration)
            except Exception:
                estimated_duration = None

        recipient_user_ids = body.get("recipient_user_ids") or []
        if isinstance(recipient_user_ids, list):
            recipient_user_ids = [int(x) for x in recipient_user_ids if x]
        else:
            recipient_user_ids = []

        requires_photo = bool(body.get("requires_photo"))
        requires_note = bool(body.get("requires_note"))

        valid_from = None
        if body.get("valid_from"):
            try:
                valid_from = datetime.fromisoformat(body["valid_from"].replace("Z", "+00:00"))
            except Exception:
                pass

        valid_until = None
        if body.get("valid_until"):
            try:
                valid_until = datetime.fromisoformat(body["valid_until"].replace("Z", "+00:00"))
            except Exception:
                pass

        username = (user.get("username") or user.get("name") or "GM") if isinstance(user, dict) else "GM"

        task = models.OperationalTask(
            title=title,
            description=description,
            category=category,
            priority=priority,
            recurrence_type=recurrence_type,
            recurrence_days=recurrence_days,
            recurrence_day_of_month=recurrence_day_of_month,
            scheduled_time=scheduled_time,
            estimated_duration_minutes=estimated_duration,
            recipient_user_ids=recipient_user_ids,
            requires_photo=requires_photo,
            requires_note=requires_note,
            valid_from=valid_from,
            valid_until=valid_until,
            created_by=username,
        )
        session.add(task)
        session.commit()
        session.refresh(task)

        generate_executions_for_task(session, task)

        return {"success": True, "task_id": task.id}
    except Exception as e:
        logger.exception("Erro ao criar ordem de serviço")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/gm/ordens-servico", response_class=JSONResponse)
async def api_gm_list_ordens(request: Request, session: Session = Depends(get_session)):
    """Listar ordens de serviço."""
    require_gerente(request)
    tasks = session.exec(
        select(models.OperationalTask)
        .where(models.OperationalTask.status.in_(["active", "paused"]))
        .order_by(desc(models.OperationalTask.created_at))
    ).all()

    out = []
    for t in tasks:
        out.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "category": t.category,
            "priority": t.priority,
            "recurrence_type": t.recurrence_type,
            "scheduled_time": t.scheduled_time,
            "status": t.status,
            "recipient_user_ids": t.recipient_user_ids or [],
            "created_by": t.created_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


@router.put("/api/gm/ordens-servico/{task_id}", response_class=JSONResponse)
async def api_gm_update_ordem(task_id: int, request: Request, session: Session = Depends(get_session)):
    """Atualizar ordem de serviço."""
    require_gerente(request)
    task = session.get(models.OperationalTask, task_id)
    if not task:
        return JSONResponse({"error": "Tarefa não encontrada"}, status_code=404)

    try:
        body = await request.json()

        if "title" in body:
            task.title = (body["title"] or "").strip() or task.title
        if "description" in body:
            task.description = (body["description"] or "").strip() or None
        if "category" in body:
            task.category = (body["category"] or "geral").strip().lower()
        if "priority" in body:
            priority = (body["priority"] or "medium").strip().lower()
            task.priority = priority if priority in ("low", "medium", "high") else task.priority
        if "status" in body:
            st = (body["status"] or "active").strip().lower()
            task.status = st if st in ("active", "paused", "archived") else task.status
        if "recipient_user_ids" in body:
            recipient_user_ids = body["recipient_user_ids"] or []
            if isinstance(recipient_user_ids, list):
                task.recipient_user_ids = [int(x) for x in recipient_user_ids if x]
        if "scheduled_time" in body:
            task.scheduled_time = (body["scheduled_time"] or "").strip() or None
        if "requires_photo" in body:
            task.requires_photo = bool(body["requires_photo"])
        if "requires_note" in body:
            task.requires_note = bool(body["requires_note"])

        task.updated_at = datetime.now()
        session.add(task)
        session.commit()

        return {"success": True}
    except Exception as e:
        logger.exception("Erro ao atualizar ordem de serviço")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/api/gm/ordens-servico/{task_id}", response_class=JSONResponse)
async def api_gm_delete_ordem(task_id: int, request: Request, session: Session = Depends(get_session)):
    """Arquivar ordem de serviço."""
    require_gerente(request)
    task = session.get(models.OperationalTask, task_id)
    if not task:
        return JSONResponse({"error": "Tarefa não encontrada"}, status_code=404)

    task.status = "archived"
    task.updated_at = datetime.now()
    session.add(task)
    session.commit()

    return {"success": True}


@router.get("/gm/ordens-servico/kpis", response_class=HTMLResponse)
async def gm_ordens_kpis_page(request: Request, session: Session = Depends(get_session)):
    """Página de KPIs dos líderes."""
    user = require_gerente(request)

    leaders = session.exec(
        select(models.User)
        .where(models.User.role == "leader")
        .where(models.User.is_active == True)
    ).all()

    start_date = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=30)).strftime("%Y-%m-%d")

    kpis = []
    for leader in leaders:
        executions = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.user_id == leader.id)
            .where(models.OperationalTaskExecution.scheduled_date >= start_date)
        ).all()

        total = len(executions)
        completed = len([e for e in executions if e.status == "completed"])
        in_progress = len([e for e in executions if e.status == "in_progress"])
        pending = len([e for e in executions if e.status == "pending"])
        postponed = len([e for e in executions if e.status == "postponed"])
        not_done = len([e for e in executions if e.status == "not_done"])
        justified = len([e for e in executions if e.status == "justified"])

        completion_rate = (completed / total * 100) if total > 0 else 0

        on_time = 0
        for ex in executions:
            if ex.status == "completed" and ex.completed_at:
                completed_date = ex.completed_at.strftime("%Y-%m-%d")
                if completed_date == ex.scheduled_date:
                    on_time += 1
        punctuality_rate = (on_time / completed * 100) if completed > 0 else 0

        postpone_rate = (postponed / total * 100) if total > 0 else 0
        not_done_rate = (not_done / total * 100) if total > 0 else 0

        score = (
            completion_rate * 0.40
            + punctuality_rate * 0.30
            + (100 - postpone_rate) * 0.15
            + (100 - not_done_rate) * 0.15
        )

        kpis.append({
            "leader": leader,
            "total": total,
            "completed": completed,
            "pending": pending,
            "in_progress": in_progress,
            "postponed": postponed,
            "not_done": not_done,
            "justified": justified,
            "completion_rate": round(completion_rate, 1),
            "punctuality_rate": round(punctuality_rate, 1),
            "postpone_rate": round(postpone_rate, 1),
            "not_done_rate": round(not_done_rate, 1),
            "score": round(score, 1),
        })

    kpis.sort(key=lambda x: x["score"], reverse=True)

    return templates.TemplateResponse("gm_ordens_kpis.html", {
        "request": request,
        "user": user,
        "kpis": kpis,
    })


@router.get("/api/gm/ordens-servico/kpis", response_class=JSONResponse)
async def api_gm_kpis(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """API para buscar KPIs com filtro de período."""
    require_gerente(request)

    if not start_date:
        start_date = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")

    leaders = session.exec(
        select(models.User)
        .where(models.User.role == "leader")
        .where(models.User.is_active == True)
    ).all()

    kpis = []
    for leader in leaders:
        executions = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.user_id == leader.id)
            .where(models.OperationalTaskExecution.scheduled_date >= start_date)
            .where(models.OperationalTaskExecution.scheduled_date <= end_date)
        ).all()

        total = len(executions)
        completed = len([e for e in executions if e.status == "completed"])
        postponed = len([e for e in executions if e.status == "postponed"])
        not_done = len([e for e in executions if e.status == "not_done"])

        completion_rate = (completed / total * 100) if total > 0 else 0

        on_time = 0
        for ex in executions:
            if ex.status == "completed" and ex.completed_at:
                completed_date = ex.completed_at.strftime("%Y-%m-%d")
                if completed_date == ex.scheduled_date:
                    on_time += 1
        punctuality_rate = (on_time / completed * 100) if completed > 0 else 0

        postpone_rate = (postponed / total * 100) if total > 0 else 0
        not_done_rate = (not_done / total * 100) if total > 0 else 0

        score = (
            completion_rate * 0.40
            + punctuality_rate * 0.30
            + (100 - postpone_rate) * 0.15
            + (100 - not_done_rate) * 0.15
        )

        kpis.append({
            "user_id": leader.id,
            "username": leader.username,
            "total": total,
            "completed": completed,
            "completion_rate": round(completion_rate, 1),
            "punctuality_rate": round(punctuality_rate, 1),
            "postpone_rate": round(postpone_rate, 1),
            "not_done_rate": round(not_done_rate, 1),
            "score": round(score, 1),
        })

    kpis.sort(key=lambda x: x["score"], reverse=True)
    return kpis


@router.get("/lider/minhas-ordens", response_class=RedirectResponse)
async def lider_minhas_ordens_removed():
    """Página descontinuada: redireciona para o fluxo inteligente."""
    return RedirectResponse(url="/smart-flow", status_code=301)


@router.post("/api/lider/ordens/{execution_id}/iniciar", response_class=JSONResponse)
async def api_lider_iniciar_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """Líder inicia execução da ordem."""
    user = require_leader_ordens(request)
    user_id = user.get("id") if isinstance(user, dict) else None

    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "Execução não encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem não é sua"}, status_code=403)
    if execution.status not in ("pending",):
        return JSONResponse({"error": f"Status atual ({execution.status}) não permite iniciar"}, status_code=400)

    execution.status = "in_progress"
    execution.started_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    execution.updated_at = datetime.now()
    session.add(execution)
    session.commit()

    return {"success": True, "status": execution.status}


@router.post("/api/lider/ordens/{execution_id}/concluir", response_class=JSONResponse)
async def api_lider_concluir_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """Líder conclui execução da ordem."""
    user = require_leader_ordens(request)
    user_id = user.get("id") if isinstance(user, dict) else None

    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "Execução não encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem não é sua"}, status_code=403)
    if execution.status not in ("pending", "in_progress"):
        return JSONResponse({"error": f"Status atual ({execution.status}) não permite concluir"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        body = {}

    task = session.get(models.OperationalTask, execution.task_id)

    note = (body.get("note") or "").strip() or None
    photo_urls = body.get("photo_urls") or []

    if task and task.requires_note and not note:
        return JSONResponse({"error": "Observação é obrigatória para esta tarefa"}, status_code=400)
    if task and task.requires_photo and not photo_urls:
        return JSONResponse({"error": "Foto é obrigatória para esta tarefa"}, status_code=400)

    execution.status = "completed"
    execution.completed_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    execution.note = note
    execution.photo_urls = photo_urls if isinstance(photo_urls, list) else []
    execution.updated_at = datetime.now()

    if not execution.started_at:
        execution.started_at = execution.completed_at

    session.add(execution)
    session.commit()

    return {"success": True, "status": execution.status}


@router.post("/api/lider/ordens/{execution_id}/adiar", response_class=JSONResponse)
async def api_lider_adiar_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """Líder adia execução da ordem."""
    user = require_leader_ordens(request)
    user_id = user.get("id") if isinstance(user, dict) else None

    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "Execução não encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem não é sua"}, status_code=403)
    if execution.status not in ("pending", "in_progress"):
        return JSONResponse({"error": f"Status atual ({execution.status}) não permite adiar"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        body = {}

    postponed_to = (body.get("postponed_to") or "").strip()
    postpone_reason = (body.get("reason") or "").strip()

    if not postponed_to:
        return JSONResponse({"error": "Nova data é obrigatória"}, status_code=400)
    if not postpone_reason:
        return JSONResponse({"error": "Motivo do adiamento é obrigatório"}, status_code=400)

    execution.status = "postponed"
    execution.postponed_to = postponed_to
    execution.postpone_reason = postpone_reason
    execution.updated_at = datetime.now()
    session.add(execution)
    session.commit()

    return {"success": True, "status": execution.status}


@router.post("/api/lider/ordens/{execution_id}/nao-fazer", response_class=JSONResponse)
async def api_lider_nao_fazer_ordem(execution_id: int, request: Request, session: Session = Depends(get_session)):
    """Líder marca ordem como não realizada."""
    user = require_leader_ordens(request)
    user_id = user.get("id") if isinstance(user, dict) else None

    execution = session.get(models.OperationalTaskExecution, execution_id)
    if not execution:
        return JSONResponse({"error": "Execução não encontrada"}, status_code=404)
    if execution.user_id != user_id:
        return JSONResponse({"error": "Esta ordem não é sua"}, status_code=403)
    if execution.status not in ("pending", "in_progress"):
        return JSONResponse({"error": f"Status atual ({execution.status}) não permite esta ação"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        body = {}

    reason = (body.get("reason") or "").strip()

    if not reason:
        return JSONResponse({"error": "Motivo é obrigatório"}, status_code=400)

    execution.status = "not_done"
    execution.not_done_reason = reason
    execution.updated_at = datetime.now()
    session.add(execution)
    session.commit()

    return {"success": True, "status": execution.status}


@router.post("/api/gm/ordens-servico/gerar-execucoes", response_class=JSONResponse)
async def api_gm_gerar_execucoes(request: Request, session: Session = Depends(get_session)):
    """Gera execuções para o dia atual para todas as tarefas ativas."""
    require_gerente(request)

    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")

    active_tasks = session.exec(
        select(models.OperationalTask).where(models.OperationalTask.status == "active")
    ).all()

    generated = 0
    for task in active_tasks:
        before_count = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.task_id == task.id)
            .where(models.OperationalTaskExecution.scheduled_date == today)
        ).all()

        generate_executions_for_task(session, task, today)

        after_count = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.task_id == task.id)
            .where(models.OperationalTaskExecution.scheduled_date == today)
        ).all()

        generated += len(after_count) - len(before_count)

    return {"success": True, "generated": generated, "date": today}
