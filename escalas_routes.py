# Módulo Escala Operacional - Quadro mobile-first para gestão de motoristas, caminhões e ajudantes
"""Integra com /separacao: alterações refletem nas rotas de entrega em tempo real."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select

import models
from database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/escala", tags=["escala"])

ESCALA_STATUSES = ("nao_escalado", "escalado", "em_ajuste", "pendencia")  # UI usa só os dois primeiros
SHIFTS = ("Manhã", "Tarde", "Noite")


def _norm_plate(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip().upper().replace("-", "").replace(" ", "").replace(".", "")
    return s


def _safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def _get_user_label(request: Request) -> str:
    try:
        uid = request.session.get("user_id") or request.session.get("auth_user_id")
        email = request.session.get("email") or request.session.get("auth_user_email") or request.session.get("username")
        if email:
            return str(email)
        if uid:
            return f"user:{uid}"
    except Exception:
        pass
    return "sistema"


def _require_login(request: Request, is_api: bool = False):
    uid = request.session.get("user_id") or request.session.get("auth_user_id")
    if not uid:
        if is_api:
            return JSONResponse({"error": "Não autorizado. Faça login."}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)
    return None


def _check_escala_access(request: Request, session: Session, is_api: bool = False):
    """Verifica se o usuário tem permissão para acessar o módulo Escala.
    User (admin/leader): precisa de 'processos' em allowed_pages ou ser admin.
    Employee: precisa de mobile_access_escala=True."""
    auth_user_id = request.session.get("auth_user_id")
    user_id = request.session.get("user_id")
    allowed_pages = request.session.get("allowed_pages")
    try:
        allowed = json.loads(allowed_pages) if isinstance(allowed_pages, str) else (allowed_pages or [])
    except Exception:
        allowed = []

    # User (admin/leader) logado via /login
    if auth_user_id:
        if "admin" in str(request.session.get("auth_user_role", "")).lower():
            return None
        if "processos" in allowed:
            return None
        msg = "Sem permissão para o módulo Escala. Solicite acesso ao administrador."
        if is_api:
            return JSONResponse({"error": msg}, status_code=403)
        return RedirectResponse(url="/login?error=no_escala_access", status_code=303)

    # Employee logado via mobile
    if user_id:
        try:
            emp_id = int(user_id)
        except (TypeError, ValueError):
            emp_id = None
        if emp_id:
            emp = session.get(models.Employee, emp_id)
            if emp and getattr(emp, "mobile_access_escala", False):
                return None
        msg = "Módulo Escala não habilitado para seu cadastro. Solicite ao gestor."
        if is_api:
            return JSONResponse({"error": msg}, status_code=403)
        return RedirectResponse(url="/mobile/entregas?error=no_escala_access", status_code=303)

    return None


def _log_escala_alteracao(
    session: Session,
    date: str,
    shift: str,
    employee_id: int,
    campo: str,
    valor_anterior: Optional[str],
    valor_novo: Optional[str],
    altered_by: str,
):
    log = models.EscalaAlteracaoLog(
        date=date,
        shift=shift,
        employee_id=employee_id,
        campo=campo,
        valor_anterior=valor_anterior or "",
        valor_novo=valor_novo or "",
        altered_by=altered_by,
    )
    session.add(log)


def _build_escala_groups(
    session: Session,
    date: str,
    shift: str,
    date_to: Optional[str] = None,
) -> tuple[Dict[str, Any], List[Dict], List[models.Employee], List[models.Employee], List[models.Vehicle]]:
    """Agrupa rotas delivery por (date, employee_id, plate) e retorna escalas, motoristas, ajudantes, caminhões."""
    date_to = date_to or date
    emp_map = {e.id: e for e in session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()}
    vehicles = list(
        session.exec(
            select(models.Vehicle)
            .where(models.Vehicle.vehicle_type == "caminhao")
            .where(models.Vehicle.is_active == True)
        ).all()
    )

    routes = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= date)
        .where(models.Route.date <= date_to)
        .where(models.Route.shift == shift)
        .order_by(models.Route.date, models.Route.employee_id)
    ).all()

    # Agrupar por (date, employee_id, plate)
    groups: Dict[tuple, Dict] = {}
    for r in routes:
        plate_norm = _norm_plate(r.delivery_vehicle_plate) or "-"
        key = (r.date, r.employee_id or 0, plate_norm)
        if key not in groups:
            emp = emp_map.get(r.employee_id)
            helper_ids = []
            try:
                parsed = json.loads(r.delivery_helpers_json) if r.delivery_helpers_json else []
                for h in parsed if isinstance(parsed, list) else []:
                    if isinstance(h, int) and h != r.employee_id:
                        helper_ids.append(h)
                    elif isinstance(h, str) and h.strip().isdigit() and int(h) != r.employee_id:
                        helper_ids.append(int(h))
            except Exception:
                pass

            plate_raw = _safe_str(r.delivery_vehicle_plate).strip()
            has_plate = bool(plate_raw) and plate_raw != "-"
            default_status = "nao_escalado" if not has_plate else "escalado"
            groups[key] = {
                "date": r.date,
                "employee_id": r.employee_id,
                "vehicle_plate": r.delivery_vehicle_plate or "-",
                "helper_ids": helper_ids,
                "total_weight": 0.0,
                "total_value": 0.0,
                "total_qty": 0,
                "route_ids": [],
                "escala_status": _safe_str(r.escala_status).strip() or default_status,
            }
        g = groups[key]
        g["total_weight"] += _safe_float(r.tonnage)
        g["total_value"] += _safe_float(r.valor_financeiro)
        g["total_qty"] += 1
        g["route_ids"].append(r.id)

    escalas = []
    for key, g in groups.items():
        emp = emp_map.get(g["employee_id"])
        helper_names = [emp_map.get(hid).name for hid in g["helper_ids"] if emp_map.get(hid)]
        escalas.append({
            "id": f"{g['date']}_{g['employee_id']}_{_norm_plate(g['vehicle_plate'])}",
            "date": g["date"],
            "employee_id": g["employee_id"],
            "driver_name": emp.name if emp else "—",
            "vehicle_plate": g["vehicle_plate"],
            "helper_ids": g["helper_ids"],
            "helper_names": helper_names,
            "total_weight": round(g["total_weight"], 2),
            "total_value": round(g["total_value"], 2),
            "total_qty": g["total_qty"],
            "route_ids": g["route_ids"],
            "escala_status": g["escala_status"],
            "conflicts": [],
        })

    # Motoristas = mobile_access_separation (App Separação) | Ajudantes = mobile_access_helper
    motoristas = [e for e in emp_map.values() if e.status == "active" and getattr(e, "mobile_access_separation", False)]
    ajudantes = [e for e in emp_map.values() if e.status == "active" and getattr(e, "mobile_access_helper", False)]

    motoristas.sort(key=lambda x: _safe_str(x.name).lower())
    ajudantes.sort(key=lambda x: _safe_str(x.name).lower())

    # Alocados
    alocados_driver = {e["employee_id"] for e in escalas}
    alocados_helper = set()
    for e in escalas:
        alocados_helper.update(e["helper_ids"])
    alocados_plate = {_norm_plate(e["vehicle_plate"]) for e in escalas if _norm_plate(e["vehicle_plate"])}

    alocados_driver = {e["employee_id"] for e in escalas}
    alocados_helper = set()
    for e in escalas:
        alocados_helper.update(e["helper_ids"])
    completas = sum(1 for e in escalas if e["escala_status"] == "escalado" and e["vehicle_plate"] and e["vehicle_plate"] != "-")
    pendentes = sum(1 for e in escalas if e["escala_status"] in ("nao_escalado", "pendencia"))
    motoristas_sem_escala = len([m for m in motoristas if m.id not in alocados_driver])
    ajudantes_sem_escala = len([a for a in ajudantes if a.id not in alocados_helper])

    summary = {
        "total": len(escalas),
        "completas": completas,
        "pendentes": pendentes,
        "em_ajuste": sum(1 for e in escalas if e["escala_status"] == "em_ajuste"),
        "peso_total": round(sum(e["total_weight"] for e in escalas), 2),
        "valor_total": round(sum(e["total_value"] for e in escalas), 2),
        "motoristas": len(motoristas),
        "ajudantes": len(ajudantes),
        "escalados": completas,
        "sem_escala": motoristas_sem_escala + ajudantes_sem_escala,
    }

    return summary, escalas, motoristas, ajudantes, vehicles


@router.get("", response_class=HTMLResponse)
async def escala_page(
    request: Request,
    date: Optional[str] = None,
    shift: str = "Manhã",
    session: Session = Depends(get_session),
):
    redir = _require_login(request, is_api=False)
    if redir:
        return redir
    perm = _check_escala_access(request, session, is_api=False)
    if perm:
        return perm

    today = datetime.now().strftime("%Y-%m-%d")
    date = date or today

    summary, escalas, motoristas, ajudantes, vehicles = _build_escala_groups(session, date, shift)

    return _templates.TemplateResponse(
        "escala.html",
        {
            "request": request,
            "selected_date": date,
            "selected_shift": shift,
            "shifts": SHIFTS,
            "summary": summary,
            "escalas": escalas,
            "motoristas": motoristas,
            "ajudantes": ajudantes,
            "vehicles": vehicles,
            "today": today,
        },
    )


@router.get("/api/data", response_class=JSONResponse)
async def escala_api_data(
    request: Request,
    date: Optional[str] = None,
    shift: str = "Manhã",
    session: Session = Depends(get_session),
):
    redir = _require_login(request, is_api=True)
    if redir:
        return redir
    perm = _check_escala_access(request, session, is_api=True)
    if perm:
        return perm

    today = datetime.now().strftime("%Y-%m-%d")
    date = date or today

    summary, escalas, motoristas, ajudantes, vehicles = _build_escala_groups(session, date, shift)

    alocados_driver = {e["employee_id"] for e in escalas}
    alocados_helper = set()
    for e in escalas:
        alocados_helper.update(e["helper_ids"])
    alocados_plate = {_norm_plate(e["vehicle_plate"]) for e in escalas if _norm_plate(e["vehicle_plate"])}

    return JSONResponse({
        "summary": summary,
        "escalas": escalas,
        "motoristas_disponiveis": [{"id": m.id, "name": _safe_str(m.name)} for m in motoristas if m.id not in alocados_driver],
        "motoristas_todos": [{"id": m.id, "name": _safe_str(m.name)} for m in motoristas],
        "motoristas_alocados": list(alocados_driver),
        "ajudantes_disponiveis": [{"id": a.id, "name": _safe_str(a.name)} for a in ajudantes if a.id not in alocados_helper],
        "ajudantes_todos": [{"id": a.id, "name": _safe_str(a.name)} for a in ajudantes],
        "ajudantes_alocados": list(alocados_helper),
        "caminhoes_disponiveis": [{"id": v.id, "placa": _safe_str(v.placa)} for v in vehicles if _norm_plate(v.placa) not in alocados_plate],
        "caminhoes_alocados": list(alocados_plate),
        "vehicles": [{"id": v.id, "placa": _safe_str(v.placa)} for v in vehicles],
    })


@router.post("/api/atualizar", response_class=JSONResponse)
async def escala_api_atualizar(
    request: Request,
    session: Session = Depends(get_session),
):
    redir = _require_login(request, is_api=True)
    if redir:
        return redir
    perm = _check_escala_access(request, session, is_api=True)
    if perm:
        return perm

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido."}, status_code=400)

    date = body.get("date")
    shift = body.get("shift", "Manhã")
    escala_id = body.get("escala_id")  # date_employeeId_plateNorm
    novo_motorista_id = body.get("novo_motorista_id")
    novo_caminhao_placa = body.get("novo_caminhao_placa")
    novos_ajudantes_ids = body.get("novos_ajudantes_ids")  # list
    novo_status = body.get("novo_status")

    if not date or not escala_id:
        return JSONResponse({"ok": False, "error": "date e escala_id obrigatórios."}, status_code=400)

    parts = escala_id.split("_")
    if len(parts) < 3:
        return JSONResponse({"ok": False, "error": "escala_id inválido."}, status_code=400)

    route_date, emp_id_str, plate_norm = parts[0], parts[1], parts[2]
    try:
        old_employee_id = int(emp_id_str)
    except ValueError:
        return JSONResponse({"ok": False, "error": "escala_id inválido."}, status_code=400)

    routes = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == route_date)
        .where(models.Route.employee_id == old_employee_id)
    ).all()

    if not routes:
        return JSONResponse({"ok": False, "error": "Escala não encontrada."}, status_code=404)

    if plate_norm and plate_norm != "-":
        routes = [r for r in routes if _norm_plate(r.delivery_vehicle_plate) == plate_norm]
    if not routes:
        return JSONResponse({"ok": False, "error": "Escala não encontrada."}, status_code=404)

    user_label = _get_user_label(request)

    if novo_motorista_id is not None:
        emp = session.get(models.Employee, novo_motorista_id)
        if not emp:
            return JSONResponse({"ok": False, "error": "Motorista não encontrado."}, status_code=404)
        old_name = (session.get(models.Employee, old_employee_id) or type('E', (), {'name': '?'})()).name
        for r in routes:
            _log_escala_alteracao(session, route_date, shift, r.employee_id, "motorista", old_name, emp.name, user_label)
            r.employee_id = novo_motorista_id
            session.add(r)

    if novo_caminhao_placa is not None and str(novo_caminhao_placa).strip():
        placa_clean = str(novo_caminhao_placa).strip().upper()
        old_plate = routes[0].delivery_vehicle_plate or "-"
        for r in routes:
            _log_escala_alteracao(session, route_date, shift, r.employee_id, "caminhao", old_plate, placa_clean, user_label)
            r.delivery_vehicle_plate = placa_clean
            session.add(r)

    if novos_ajudantes_ids is not None:
        norm = []
        seen = set()
        for h in (novos_ajudantes_ids if isinstance(novos_ajudantes_ids, list) else []):
            try:
                hid = int(h)
                if hid != (routes[0].employee_id if routes else 0) and hid not in seen:
                    seen.add(hid)
                    norm.append(hid)
            except (TypeError, ValueError):
                pass
        helpers_json = json.dumps(norm) if norm else None
        old_helpers = routes[0].delivery_helpers_json or "[]"
        for r in routes:
            _log_escala_alteracao(session, route_date, shift, r.employee_id, "ajudante", old_helpers, helpers_json or "[]", user_label)
            r.delivery_helpers_json = helpers_json
            session.add(r)

    if novo_status and novo_status in ESCALA_STATUSES:
        for r in routes:
            old_st = r.escala_status or "escalado"
            _log_escala_alteracao(session, route_date, shift, r.employee_id, "status", old_st, novo_status, user_label)
            r.escala_status = novo_status
            session.add(r)

    session.commit()
    return JSONResponse({"ok": True, "message": "Alteração salva. Atualize a página /separacao para ver as mudanças."})


_templates = None

mobile_escala_router = APIRouter(tags=["mobile-escala"])


@mobile_escala_router.get("/mobile/escala", response_class=HTMLResponse)
async def mobile_escala_page(
    request: Request,
    date: Optional[str] = None,
    shift: str = "Manhã",
    session: Session = Depends(get_session),
):
    """Escala Operacional acessível em /mobile/escala para colaboradores."""
    redir = _require_login(request, is_api=False)
    if redir:
        return redir
    perm = _check_escala_access(request, session, is_api=False)
    if perm:
        return perm

    today = datetime.now().strftime("%Y-%m-%d")
    date = date or today

    summary, escalas, motoristas, ajudantes, vehicles = _build_escala_groups(session, date, shift)

    employee = None
    user_id = request.session.get("user_id")
    if user_id:
        try:
            emp_id = int(user_id)
            employee = session.get(models.Employee, emp_id)
        except (TypeError, ValueError):
            pass

    return _templates.TemplateResponse(
        "escala_mobile.html",
        {
            "request": request,
            "selected_date": date,
            "selected_shift": shift,
            "shifts": SHIFTS,
            "summary": summary,
            "escalas": escalas,
            "motoristas": motoristas,
            "ajudantes": ajudantes,
            "vehicles": vehicles,
            "today": today,
            "employee": employee,
        },
    )


def init_escalas_router(templates):
    """Retorna o router. Configura templates para as rotas."""
    global _templates
    _templates = templates
    return router
