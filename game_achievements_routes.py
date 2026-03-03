# -*- coding: utf-8 -*-
"""Rotas de gestao de conquistas (modularizado de main.py)."""

from datetime import datetime
from typing import Optional, Any, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
import models


def init_game_achievements_router(
    *,
    templates,
    require_leader: Callable[[Request], Any],
    require_login: Callable[[Request], Any],
    logger,
) -> APIRouter:
    router = APIRouter()

    class AchievementSchema(BaseModel):
        id: Optional[int] = None
        name: str
        description: Optional[str] = ""
        icon: Optional[str] = "🏆"
        xp_reward: int = 100
        category: str = "general"
        trigger_type: str = "manual"
        trigger_value: Optional[str] = None

    class GrantAchievementSchema(BaseModel):
        achievement_id: int
        employee_id: int
        reason: Optional[str] = None

    @router.get("/admin/game/achievements", response_class=HTMLResponse)
    def admin_achievements_page(request: Request, user=Depends(require_leader)):
        return templates.TemplateResponse("admin_achievements.html", {"request": request, "user": user})

    @router.get("/api/game/achievements", dependencies=[Depends(require_leader)])
    def api_list_achievements(session: Session = Depends(get_session), user=Depends(require_login)):
        try:
            achievements = session.exec(select(models.GameAchievement).order_by(models.GameAchievement.xp_reward)).all()
            return {"success": True, "data": achievements}
        except Exception as e:
            logger.error(f"Error listing achievements: {e}")
            return {"success": False, "error": str(e)}

    @router.post("/api/game/achievements", dependencies=[Depends(require_leader)])
    def api_save_achievement(
        data: AchievementSchema,
        session: Session = Depends(get_session),
        user=Depends(require_login),
    ):
        try:
            if data.id:
                ach = session.get(models.GameAchievement, data.id)
                if not ach:
                    return {"success": False, "error": "Conquista nao encontrada"}
                ach.name = data.name
                ach.description = data.description
                ach.icon = data.icon
                ach.xp_reward = data.xp_reward
                ach.category = data.category
                ach.trigger_type = data.trigger_type
                ach.trigger_value = data.trigger_value
                session.add(ach)
            else:
                ach = models.GameAchievement(
                    name=data.name,
                    description=data.description,
                    icon=data.icon,
                    xp_reward=data.xp_reward,
                    category=data.category,
                    trigger_type=data.trigger_type,
                    trigger_value=data.trigger_value,
                    slug=data.name.lower().replace(" ", "_"),
                )
                session.add(ach)

            session.commit()
            session.refresh(ach)
            return {"success": True, "data": ach}
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving achievement: {e}")
            return {"success": False, "error": str(e)}

    @router.delete("/api/game/achievements/{ach_id}", dependencies=[Depends(require_leader)])
    def api_delete_achievement(ach_id: int, session: Session = Depends(get_session), user=Depends(require_login)):
        try:
            ach = session.get(models.GameAchievement, ach_id)
            if not ach:
                return {"success": False, "error": "Nao encontrado"}
            session.delete(ach)
            session.commit()
            return {"success": True}
        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e)}

    @router.post("/api/game/achievements/grant", dependencies=[Depends(require_leader)])
    def api_grant_achievement(
        data: GrantAchievementSchema,
        session: Session = Depends(get_session),
        user=Depends(require_login),
    ):
        try:
            ach = session.get(models.GameAchievement, data.achievement_id)
            emp = session.get(models.Employee, data.employee_id)
            if not ach or not emp:
                return {"success": False, "error": "Conquista ou Colaborador nao encontrado."}

            user_ach = models.EmployeeAchievement(
                employee_id=emp.id,
                achievement_id=ach.id,
                status="approved",
                approved_by=str(user),
                approved_at=datetime.now(ZoneInfo("America/Sao_Paulo")),
            )
            session.add(user_ach)

            if ach.xp_reward > 0:
                tx = models.GameXPTransaction(
                    employee_id=emp.id,
                    amount=ach.xp_reward,
                    source_type="achievement_grant",
                    status="confirmed",
                    reason=f"Conquista: {ach.name} | {data.reason or ''}",
                    manager_id=str(user),
                    confirmed_at=datetime.now(ZoneInfo("America/Sao_Paulo")),
                )
                session.add(tx)
                emp.total_xp += ach.xp_reward
                session.add(emp)

            session.commit()
            return {
                "success": True,
                "message": f"Conquista '{ach.name}' concedida para {emp.name}.",
                "xp_added": ach.xp_reward,
            }
        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e)}

    return router

