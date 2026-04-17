# -*- coding: utf-8 -*-
"""Geração de execuções diárias de tarefas operacionais (ordens de serviço)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

import models


def generate_executions_for_task(
    session: Session,
    task: models.OperationalTask,
    target_date: Optional[str] = None,
) -> None:
    """Gera execuções para uma tarefa em uma data específica."""
    if target_date is None:
        target_date = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")

    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    weekday = target_dt.weekday()  # 0=segunda, 6=domingo
    day_of_month = target_dt.day

    should_execute = False

    if task.recurrence_type == "once":
        if task.valid_from:
            should_execute = task.valid_from.strftime("%Y-%m-%d") == target_date
        else:
            should_execute = task.created_at.strftime("%Y-%m-%d") == target_date
    elif task.recurrence_type == "daily":
        should_execute = True
    elif task.recurrence_type == "weekly":
        should_execute = weekday in (task.recurrence_days or [])
    elif task.recurrence_type == "monthly":
        should_execute = day_of_month == task.recurrence_day_of_month

    if not should_execute:
        return

    if task.valid_from and target_dt < task.valid_from.replace(tzinfo=None):
        return
    if task.valid_until and target_dt > task.valid_until.replace(tzinfo=None):
        return

    for user_id in (task.recipient_user_ids or []):
        existing = session.exec(
            select(models.OperationalTaskExecution)
            .where(models.OperationalTaskExecution.task_id == task.id)
            .where(models.OperationalTaskExecution.user_id == user_id)
            .where(models.OperationalTaskExecution.scheduled_date == target_date)
        ).first()

        if not existing:
            execution = models.OperationalTaskExecution(
                task_id=task.id,
                scheduled_date=target_date,
                user_id=user_id,
                status="pending",
            )
            session.add(execution)

    session.commit()
