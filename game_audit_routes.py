# -*- coding: utf-8 -*-
"""Rotas de auditoria de game/xp (modularizado de main.py)."""

from datetime import datetime, timedelta
from typing import Optional, Any, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session, select, col, desc

from database import get_session
import models
from route_duration import route_duration_minutes


def parse_reason(reason: str):
    """Parse de reason em campos estruturados."""
    ref = None
    kg = None
    uo = None
    evento = None
    regra_horario = None

    if not reason:
        return {"ref": ref, "kg": kg, "uo": uo, "evento": evento, "regra_horario": regra_horario}

    if "ref:" in reason:
        try:
            ref = reason.split("ref:")[1].split(")")[0].strip()
        except Exception:
            ref = None

    parts = [p.strip() for p in reason.split("|")]
    for p in parts:
        if p.endswith("kg") and kg is None:
            try:
                num = "".join(ch for ch in p if (ch.isdigit() or ch in ".,"))
                kg = float(num.replace(".", "").replace(",", ".")) if num else None
            except Exception:
                pass
        if " UO" in p and uo is None:
            try:
                num = p.split("UO")[0].strip()
                uo = float(num.replace(",", "."))
            except Exception:
                pass
        if p.startswith("Event:"):
            evento = p.replace("Event:", "").strip()
        if p.startswith("Early"):
            regra_horario = p

    return {"ref": ref, "kg": kg, "uo": uo, "evento": evento, "regra_horario": regra_horario}


def init_game_audit_router(
    *,
    require_login: Callable[[Request], Any],
    require_leader: Callable[[Request], Any],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/game/audit", dependencies=[Depends(require_leader)])
    async def api_game_audit(
        request: Request,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        employee_id: Optional[int] = None,
        limit: int = 200,
        session: Session = Depends(get_session),
    ):
        require_login(request)

        q = (
            select(models.GameXPTransaction, models.Employee)
            .join(models.Employee)
            .order_by(models.GameXPTransaction.created_at.desc())
            .limit(min(max(limit, 1), 500))
        )

        if status:
            q = q.where(models.GameXPTransaction.status == status)
        if employee_id:
            q = q.where(models.GameXPTransaction.employee_id == employee_id)

        if start_date:
            try:
                sdt = datetime.strptime(start_date, "%Y-%m-%d")
                q = q.where(models.GameXPTransaction.created_at >= sdt)
            except Exception:
                pass
        if end_date:
            try:
                edt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                q = q.where(models.GameXPTransaction.created_at < edt)
            except Exception:
                pass

        rows = session.exec(q).all()
        tz_br = ZoneInfo("America/Sao_Paulo")

        data = []
        for tx, emp in rows:
            parsed = parse_reason(tx.reason)
            created_at_br = None
            if tx.created_at:
                if tx.created_at.tzinfo is None:
                    created_at_br = tx.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz_br)
                else:
                    created_at_br = tx.created_at.astimezone(tz_br)

            data.append(
                {
                    "id": tx.id,
                    "employee_id": tx.employee_id,
                    "employee_name": emp.name,
                    "created_at": created_at_br.strftime("%Y-%m-%d %H:%M") if created_at_br else None,
                    "amount": int(tx.amount) if tx.amount is not None else 0,
                    "status": tx.status,
                    "source_type": tx.source_type,
                    "reason": tx.reason,
                    "ref": parsed["ref"],
                    "kg": parsed["kg"],
                    "uo": parsed["uo"],
                    "evento": parsed["evento"],
                    "regra_horario": parsed["regra_horario"],
                }
            )

        return {"success": True, "items": data}

    @router.get("/api/game/audit/routes", dependencies=[Depends(require_leader)])
    async def api_game_audit_routes(
        request: Request,
        date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        employee_id: Optional[int] = None,
        status: Optional[str] = "completed",
        limit: int = 500,
        session: Session = Depends(get_session),
    ):
        require_login(request)

        q = (
            select(models.Route, models.Employee.name, models.Client.name)
            .join(models.Employee)
            .join(models.Client)
            .order_by(desc(models.Route.date), desc(models.Route.id))
            .limit(min(max(limit, 1), 2000))
        )

        if status:
            q = q.where(models.Route.status == status)
        if employee_id:
            q = q.where(models.Route.employee_id == employee_id)
        if date:
            q = q.where(models.Route.date == date)
        else:
            if start_date:
                q = q.where(models.Route.date >= start_date)
            if end_date:
                q = q.where(models.Route.date <= end_date)

        rows = session.exec(q).all()
        kg_per_uo = 1500.0
        xp_per_uo = 100

        items = []
        for r, emp_name, client_name in rows:
            kg = float(r.tonnage or 0.0)
            uo = (kg / kg_per_uo) if kg > 0 else 0.0
            xp_est = int(uo * xp_per_uo)

            dur_min = route_duration_minutes(r)
            dur_hhmm = None
            kgh = None
            if dur_min is not None and dur_min > 0:
                hh = dur_min // 60
                mm = dur_min % 60
                dur_hhmm = f"{hh:02d}:{mm:02d}"
                hours = dur_min / 60.0
                kgh = kg / hours

            items.append(
                {
                    "route_id": r.id,
                    "date": r.date,
                    "employee_id": r.employee_id,
                    "employee_name": emp_name,
                    "client_id": r.client_id,
                    "client_name": client_name,
                    "start_time": r.start_time,
                    "end_time": r.end_time,
                    "duration": dur_hhmm,
                    "duration_minutes": dur_min,
                    "kg": kg,
                    "uo": round(uo, 2),
                    "kgh": round(kgh, 1) if kgh is not None else None,
                    "xp_estimado": xp_est,
                    "status": r.status,
                }
            )

        return {"success": True, "items": items}

    @router.get("/api/game/export/xp", dependencies=[Depends(require_leader)])
    async def api_game_export_xp(
        request: Request,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        employee_id: Optional[int] = None,
        session: Session = Depends(get_session),
    ):
        require_login(request)

        q = select(models.GameXPTransaction, models.Employee).join(models.Employee).order_by(desc(models.GameXPTransaction.created_at))
        if status:
            q = q.where(models.GameXPTransaction.status == status)
        if employee_id:
            q = q.where(models.GameXPTransaction.employee_id == employee_id)
        if start_date:
            try:
                sdt = datetime.strptime(start_date, "%Y-%m-%d")
                q = q.where(models.GameXPTransaction.created_at >= sdt)
            except Exception:
                pass
        if end_date:
            try:
                edt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                q = q.where(models.GameXPTransaction.created_at < edt)
            except Exception:
                pass

        async def iter_csv():
            yield "ID,Data,Horario,Colaborador,Matricula,Quantidade XP,Status,Tipo,Motivo,Detalhes\n"
            records = session.exec(q).all()
            for tx, emp in records:
                dt_str = tx.created_at.strftime("%d/%m/%Y")
                hr_str = tx.created_at.strftime("%H:%M:%S")
                reason_clean = tx.reason.replace("\n", " ").replace(",", ";")
                row = [
                    str(tx.id),
                    dt_str,
                    hr_str,
                    emp.name,
                    str(emp.registration_id),
                    str(int(tx.amount)),
                    tx.status,
                    tx.source_type,
                    reason_clean,
                    "",
                ]
                yield ",".join(row) + "\n"

        filename = f"xp_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        return StreamingResponse(iter_csv(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})

    @router.get("/api/game/audit/summary", dependencies=[Depends(require_leader)])
    async def api_game_audit_summary(
        request: Request,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = "confirmed",
        session: Session = Depends(get_session),
    ):
        require_login(request)

        q = select(models.GameXPTransaction).where(models.GameXPTransaction.status == status)
        if start_date:
            try:
                sdt = datetime.strptime(start_date, "%Y-%m-%d")
                q = q.where(models.GameXPTransaction.created_at >= sdt)
            except Exception:
                pass
        if end_date:
            try:
                edt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                q = q.where(models.GameXPTransaction.created_at < edt)
            except Exception:
                pass

        transactions = session.exec(q).all()
        summary = {}
        for tx in transactions:
            eid = tx.employee_id
            if eid not in summary:
                summary[eid] = {"amount": 0, "count": 0}
            summary[eid]["amount"] += tx.amount
            summary[eid]["count"] += 1

        result = []
        if summary:
            emps = session.exec(select(models.Employee).where(col(models.Employee.id).in_(summary.keys()))).all()
            emp_map = {e.id: e for e in emps}
            for eid, stats in summary.items():
                emp = emp_map.get(eid)
                if emp:
                    result.append(
                        {
                            "employee_id": eid,
                            "employee_name": emp.name,
                            "photo_url": emp.photo_url,
                            "total_xp": int(stats["amount"]),
                            "tx_count": stats["count"],
                        }
                    )

        result.sort(key=lambda x: x["total_xp"], reverse=True)
        return {"success": True, "summary": result}

    return router

