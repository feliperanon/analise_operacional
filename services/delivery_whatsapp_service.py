# -*- coding: utf-8 -*-
"""Dominio do fluxo manual de notificacao de saida via WhatsApp."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session, desc, select

import models
from services.whatsapp_provider import BaseWhatsAppProvider, get_whatsapp_provider

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
logger = logging.getLogger(__name__)

WHATSAPP_ROUTE_STATUS_NAO_DISPONIVEL = "nao_disponivel"
WHATSAPP_ROUTE_STATUS_PENDENTE = "pendente_envio"
WHATSAPP_ROUTE_STATUS_PROCESSANDO = "em_processamento"
WHATSAPP_ROUTE_STATUS_ENVIADO = "enviado"
WHATSAPP_ROUTE_STATUS_ENVIADO_PARCIAL = "enviado_parcial"
WHATSAPP_ROUTE_STATUS_FALHA = "falha"
WHATSAPP_ROUTE_STATUS_CANCELADO = "cancelado"

WHATSAPP_ITEM_STATUS_ELEGIVEL = "elegivel"
WHATSAPP_ITEM_STATUS_SEM_CONTATO = "sem_contato"
WHATSAPP_ITEM_STATUS_TELEFONE_INVALIDO = "telefone_invalido"
WHATSAPP_ITEM_STATUS_BLOQUEADO = "bloqueado"
WHATSAPP_ITEM_STATUS_JA_ENVIADO = "ja_enviado"
WHATSAPP_ITEM_STATUS_ENVIADO = "enviado"
WHATSAPP_ITEM_STATUS_FALHA = "falha"

WHATSAPP_ROUTE_STATUS_LABELS = {
    WHATSAPP_ROUTE_STATUS_NAO_DISPONIVEL: "Nao disponivel",
    WHATSAPP_ROUTE_STATUS_PENDENTE: "Pendente",
    WHATSAPP_ROUTE_STATUS_PROCESSANDO: "Em processamento",
    WHATSAPP_ROUTE_STATUS_ENVIADO: "Enviado",
    WHATSAPP_ROUTE_STATUS_ENVIADO_PARCIAL: "Enviado parcial",
    WHATSAPP_ROUTE_STATUS_FALHA: "Falha",
    WHATSAPP_ROUTE_STATUS_CANCELADO: "Cancelado",
}

WHATSAPP_ITEM_STATUS_LABELS = {
    WHATSAPP_ITEM_STATUS_ELEGIVEL: "Elegivel",
    WHATSAPP_ITEM_STATUS_SEM_CONTATO: "Sem contato",
    WHATSAPP_ITEM_STATUS_TELEFONE_INVALIDO: "Telefone invalido",
    WHATSAPP_ITEM_STATUS_BLOQUEADO: "Bloqueado",
    WHATSAPP_ITEM_STATUS_JA_ENVIADO: "Ja enviado",
    WHATSAPP_ITEM_STATUS_ENVIADO: "Enviado",
    WHATSAPP_ITEM_STATUS_FALHA: "Falha",
}

WHATSAPP_DEFAULT_MESSAGE = (
    "Ola, seu pedido saiu para entrega e esta em rota. "
    "Em caso de necessidade, entre em contato com nossa equipe."
)

_BLOCKED_CLIENT_OPERATIONAL_STATUSES = {"INATIVO", "FECHOU", "BLOQUEADO"}


def now_br() -> datetime:
    return datetime.now(SAO_PAULO_TZ)


def _safe_json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _post_n8n_delivery_whatsapp_webhook(
    *,
    snapshot: Dict[str, Any],
    route_date: str,
    shift: str,
    employee_id: int,
    vehicle_plate: str,
    operator_label: str,
    retry_failed: bool,
    allow_repeat: bool,
    skip_session_ready: bool,
    sent_count: int,
    failed_count: int,
    per_client_results: List[Dict[str, Any]],
) -> None:
    webhook_url = str(os.getenv("N8N_DELIVERY_WHATSAPP_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        return

    token = str(os.getenv("N8N_DELIVERY_WHATSAPP_WEBHOOK_AUTH_TOKEN") or "").strip()
    timeout_raw = str(os.getenv("N8N_DELIVERY_WHATSAPP_WEBHOOK_TIMEOUT_SECONDS") or "10").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except Exception:
        timeout_seconds = 10.0
    timeout_seconds = max(2.0, min(timeout_seconds, 60.0))

    payload = {
        "event": "delivery.whatsapp.batch_finished",
        "occurred_at": now_br().isoformat(),
        "route": {
            "route_group_key": snapshot.get("route_group_key"),
            "route_date": route_date,
            "shift": shift,
            "employee_id": employee_id,
            "driver_name": snapshot.get("driver_name") or "",
            "vehicle_plate": vehicle_plate,
        },
        "operator": {"label": operator_label or ""},
        "delivery_whatsapp": {
            "retry_failed": bool(retry_failed),
            "allow_repeat": bool(allow_repeat),
            "skip_session_ready": bool(skip_session_ready),
            "status": snapshot.get("status"),
            "status_label": snapshot.get("status_label"),
            "message": snapshot.get("preview_message"),
            "summary": snapshot.get("summary") or {},
            "sent_count": int(sent_count or 0),
            "failed_count": int(failed_count or 0),
            "results": per_client_results,
        },
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(webhook_url, json=payload, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("delivery whatsapp n8n webhook error: %s", exc)


def _norm_text(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return (
        unicodedata.normalize("NFKD", raw)
        .encode("ascii", "ignore")
        .decode()
        .upper()
    )


def normalize_plate(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def format_datetime_br(value: Optional[datetime]) -> str:
    if not value:
        return ""
    try:
        dt = _coerce_sp_datetime(value)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)


def _coerce_sp_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.tzinfo:
            return value.astimezone(SAO_PAULO_TZ)
        return value.replace(tzinfo=SAO_PAULO_TZ)
    except Exception:
        return value


def delivery_route_group_key(route_date: str, shift: str, employee_id: int, vehicle_plate: str) -> str:
    return "|".join(
        [
            str(route_date or "").strip(),
            str(shift or "").strip(),
            str(int(employee_id or 0)),
            normalize_plate(vehicle_plate) or "-",
        ]
    )


def get_route_group_identity(routes: Iterable[models.Route]) -> Dict[str, Any]:
    rows = list(routes)
    if not rows:
        raise ValueError("Grupo de rota vazio.")
    first = rows[0]
    vehicle_plate = first.delivery_vehicle_plate or ""
    shift = first.shift or "Manhã"
    return {
        "route_date": first.date,
        "shift": shift,
        "employee_id": int(first.employee_id or 0),
        "vehicle_plate": vehicle_plate,
        "route_group_key": delivery_route_group_key(first.date, shift, int(first.employee_id or 0), vehicle_plate),
    }


def list_delivery_group_routes(
    session: Session,
    *,
    route_date: str,
    shift: str,
    employee_id: int,
    vehicle_plate: str,
) -> List[models.Route]:
    rows = list(
        session.exec(
            select(models.Route)
            .where(models.Route.type == "delivery")
            .where(models.Route.date == route_date)
            .where(models.Route.employee_id == employee_id)
            .order_by(models.Route.created_at, models.Route.id)
        ).all()
    )
    plate_norm = normalize_plate(vehicle_plate)
    shift_norm = _norm_text(shift)
    return [
        row
        for row in rows
        if normalize_plate(getattr(row, "delivery_vehicle_plate", None)) == plate_norm
        and _norm_text(getattr(row, "shift", None) or shift) == shift_norm
    ]


def _resolve_client_phone(client: Optional[models.Client]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not client:
        return None, None, None

    candidates = [
        getattr(client, "fone_e164", None),
        getattr(client, "fone", None),
        getattr(client, "fone_alternativo", None),
    ]
    raw_phone = next((str(candidate).strip() for candidate in candidates if str(candidate or "").strip()), None)
    if not raw_phone:
        return None, None, None

    digits = re.sub(r"\D", "", raw_phone)
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) > 11:
        digits = digits[-11:]

    if len(digits) not in (10, 11):
        return raw_phone, None, raw_phone

    normalized = f"+55{digits}"
    if len(digits) == 11:
        display = f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    else:
        display = f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return raw_phone, normalized, display


def _is_client_blocked(client: Optional[models.Client]) -> bool:
    if not client:
        return True
    if bool(getattr(client, "lgpd_nao_contatar", False)) or bool(getattr(client, "lgpd_restricao_dados", False)):
        return True
    operational_status = _norm_text(getattr(client, "status_operacional", None))
    return operational_status in _BLOCKED_CLIENT_OPERATIONAL_STATUSES


def _group_session_started(session: Session, routes: List[models.Route]) -> bool:
    if not routes:
        return False
    identity = get_route_group_identity(routes)
    if any(getattr(route, "delivery_whatsapp_ready_at", None) for route in routes):
        return True
    if any(str(getattr(route, "delivery_status", "") or "").strip().lower() in {"iniciada", "entregue", "devolucao", "reaberta"} for route in routes):
        return True

    ds_rows = list(
        session.exec(
            select(models.DeliverySession)
            .where(models.DeliverySession.date == identity["route_date"])
            .where(models.DeliverySession.employee_id == identity["employee_id"])
            .order_by(desc(models.DeliverySession.id))
        ).all()
    )
    plate_norm = normalize_plate(identity["vehicle_plate"])
    return any(normalize_plate(getattr(ds, "vehicle_plate", None)) == plate_norm for ds in ds_rows)


def _started_session_for_group(session: Session, routes: List[models.Route]) -> Optional[models.DeliverySession]:
    if not routes:
        return None
    identity = get_route_group_identity(routes)
    plate_norm = normalize_plate(identity["vehicle_plate"])
    ds_rows = list(
        session.exec(
            select(models.DeliverySession)
            .where(models.DeliverySession.date == identity["route_date"])
            .where(models.DeliverySession.employee_id == identity["employee_id"])
            .order_by(desc(models.DeliverySession.started_at), desc(models.DeliverySession.id))
        ).all()
    )
    for ds in ds_rows:
        if normalize_plate(getattr(ds, "vehicle_plate", None)) == plate_norm:
            return ds
    return None


def _latest_success_item(items: List[models.DeliveryWhatsAppItem]) -> Optional[models.DeliveryWhatsAppItem]:
    for item in items:
        if item.status == WHATSAPP_ITEM_STATUS_ENVIADO:
            return item
    return None


def _serialize_history_batches(batches: List[models.DeliveryWhatsAppBatch]) -> List[Dict[str, Any]]:
    return [
        {
            "id": batch.id,
            "status": batch.status,
            "status_label": WHATSAPP_ROUTE_STATUS_LABELS.get(batch.status, batch.status.title()),
            "operator_label": batch.operator_label or "",
            "provider_name": batch.provider_name or "",
            "eligible_count": int(batch.eligible_count or 0),
            "sent_count": int(batch.sent_count or 0),
            "failed_count": int(batch.failed_count or 0),
            "ignored_count": int(batch.ignored_count or 0),
            "is_retry": bool(batch.is_retry),
            "created_at": format_datetime_br(batch.created_at),
            "finished_at": format_datetime_br(batch.finished_at),
            "failure_reason": batch.failure_reason or "",
        }
        for batch in batches
    ]


def _compute_route_status(
    *,
    ready: bool,
    sendable_count: int,
    sent_count: int,
    failed_count: int,
    latest_batch_status: Optional[str],
) -> str:
    if latest_batch_status == WHATSAPP_ROUTE_STATUS_PROCESSANDO:
        return WHATSAPP_ROUTE_STATUS_PROCESSANDO
    if latest_batch_status == WHATSAPP_ROUTE_STATUS_CANCELADO:
        return WHATSAPP_ROUTE_STATUS_CANCELADO
    if not ready:
        return WHATSAPP_ROUTE_STATUS_NAO_DISPONIVEL
    if sent_count > 0:
        if failed_count > 0 or sendable_count > 0:
            return WHATSAPP_ROUTE_STATUS_ENVIADO_PARCIAL
        return WHATSAPP_ROUTE_STATUS_ENVIADO
    if failed_count > 0 and sendable_count == 0:
        return WHATSAPP_ROUTE_STATUS_FALHA
    return WHATSAPP_ROUTE_STATUS_PENDENTE


def build_delivery_whatsapp_snapshot(
    session: Session,
    routes: List[models.Route],
    *,
    retry_failed: bool = False,
) -> Dict[str, Any]:
    if not routes:
        raise ValueError("Nenhuma rota de entrega encontrada para o grupo.")

    identity = get_route_group_identity(routes)
    route_group_key = identity["route_group_key"]
    client_ids = list({int(route.client_id or 0) for route in routes if route.client_id})
    clients = list(session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all()) if client_ids else []
    client_map = {int(client.id): client for client in clients if client.id}

    items = list(
        session.exec(
            select(models.DeliveryWhatsAppItem)
            .where(models.DeliveryWhatsAppItem.route_group_key == route_group_key)
            .order_by(desc(models.DeliveryWhatsAppItem.created_at), desc(models.DeliveryWhatsAppItem.id))
        ).all()
    )
    history_by_client: Dict[int, List[models.DeliveryWhatsAppItem]] = defaultdict(list)
    for item in items:
        history_by_client[int(item.client_id or 0)].append(item)

    batches = list(
        session.exec(
            select(models.DeliveryWhatsAppBatch)
            .where(models.DeliveryWhatsAppBatch.route_group_key == route_group_key)
            .order_by(desc(models.DeliveryWhatsAppBatch.created_at), desc(models.DeliveryWhatsAppBatch.id))
        ).all()
    )
    latest_batch = batches[0] if batches else None

    route_by_client: Dict[int, models.Route] = {}
    for route in sorted(routes, key=lambda row: (row.created_at, row.id or 0)):
        client_id = int(route.client_id or 0)
        if client_id and client_id not in route_by_client:
            route_by_client[client_id] = route

    session_row = _started_session_for_group(session, routes)
    ready = _group_session_started(session, routes)
    ready_candidates = [
        _coerce_sp_datetime(getattr(route, "delivery_whatsapp_ready_at", None))
        for route in routes
        if getattr(route, "delivery_whatsapp_ready_at", None)
    ]
    if session_row and getattr(session_row, "started_at", None):
        ready_candidates.append(_coerce_sp_datetime(session_row.started_at))
    ready_at = min(ready_candidates) if ready_candidates else None

    driver = session.get(models.Employee, identity["employee_id"]) if identity["employee_id"] else None
    clients_payload: List[Dict[str, Any]] = []
    summary = {
        "total_clients": len(route_by_client),
        "eligible": 0,
        "sendable": 0,
        "sent": 0,
        "failed": 0,
        "no_contact": 0,
        "invalid_phone": 0,
        "blocked": 0,
        "already_sent": 0,
        "ignored": 0,
        "pending_retry": 0,
    }

    for client_id, route in route_by_client.items():
        client = client_map.get(client_id)
        item_history = history_by_client.get(client_id, [])
        latest_item = item_history[0] if item_history else None
        sent_item = _latest_success_item(item_history)
        raw_phone, phone_normalized, phone_display = _resolve_client_phone(client)
        blocked = _is_client_blocked(client)

        current_status = WHATSAPP_ITEM_STATUS_ELEGIVEL
        sendable = ready and not retry_failed
        can_retry = False
        failure_reason = ""
        last_sent_at = sent_item.sent_at if sent_item else None
        last_provider_message_id = sent_item.provider_message_id if sent_item else None

        if blocked:
            current_status = WHATSAPP_ITEM_STATUS_BLOQUEADO
            sendable = False
            summary["blocked"] += 1
        elif not raw_phone:
            current_status = WHATSAPP_ITEM_STATUS_SEM_CONTATO
            sendable = False
            summary["no_contact"] += 1
        elif not phone_normalized:
            current_status = WHATSAPP_ITEM_STATUS_TELEFONE_INVALIDO
            sendable = False
            summary["invalid_phone"] += 1
        elif sent_item is not None:
            current_status = WHATSAPP_ITEM_STATUS_JA_ENVIADO
            sendable = False
            summary["sent"] += 1
            summary["already_sent"] += 1
        elif latest_item and latest_item.status == WHATSAPP_ITEM_STATUS_FALHA:
            current_status = WHATSAPP_ITEM_STATUS_FALHA
            failure_reason = latest_item.failure_reason or ""
            sendable = ready and retry_failed
            can_retry = ready
            summary["failed"] += 1
            summary["pending_retry"] += 1
        elif not ready:
            current_status = WHATSAPP_ITEM_STATUS_ELEGIVEL
            sendable = False
        else:
            current_status = WHATSAPP_ITEM_STATUS_ELEGIVEL
            sendable = not retry_failed

        if current_status in {
            WHATSAPP_ITEM_STATUS_BLOQUEADO,
            WHATSAPP_ITEM_STATUS_SEM_CONTATO,
            WHATSAPP_ITEM_STATUS_TELEFONE_INVALIDO,
            WHATSAPP_ITEM_STATUS_JA_ENVIADO,
        }:
            summary["ignored"] += 1

        if current_status == WHATSAPP_ITEM_STATUS_ELEGIVEL:
            summary["eligible"] += 1
        if sendable:
            summary["sendable"] += 1

        clients_payload.append(
            {
                "client_id": client_id,
                "route_id": route.id,
                "client_name": getattr(client, "razao_social", None) or getattr(client, "name", None) or "Cliente",
                "order_number": route.delivery_order_number or "",
                "route_code": route.delivery_route_code or "",
                "phone_raw": raw_phone or "",
                "phone_display": phone_display or raw_phone or "",
                "phone_normalized": phone_normalized or "",
                "status": current_status,
                "status_label": WHATSAPP_ITEM_STATUS_LABELS.get(current_status, current_status.title()),
                "sendable": bool(sendable),
                "can_retry": bool(can_retry),
                "attempt_count": len(item_history),
                "failure_reason": failure_reason,
                "last_sent_at": format_datetime_br(last_sent_at),
                "last_provider_message_id": last_provider_message_id or "",
                "blocked_reason": "LGPD / restricao operacional" if blocked else "",
                "has_delivery_started": bool(route.delivery_started_at or str(route.delivery_status or "").lower() in {"iniciada", "entregue", "devolucao"}),
            }
        )

    clients_payload.sort(key=lambda row: (0 if row["sendable"] else 1, row["status_label"], row["client_name"]))

    route_status = _compute_route_status(
        ready=ready,
        sendable_count=summary["sendable"] if not retry_failed else 0,
        sent_count=summary["sent"],
        failed_count=summary["failed"],
        latest_batch_status=latest_batch.status if latest_batch else None,
    )

    last_sent_batch = next((batch for batch in batches if int(batch.sent_count or 0) > 0), None)
    last_sent_at = _coerce_sp_datetime(last_sent_batch.finished_at) if last_sent_batch and last_sent_batch.finished_at else None
    if not last_sent_at:
        sent_dates = [_coerce_sp_datetime(item.sent_at) for item in items if item.sent_at]
        last_sent_at = max(sent_dates) if sent_dates else None

    return {
        "route_group_key": route_group_key,
        "route_date": identity["route_date"],
        "shift": identity["shift"],
        "employee_id": identity["employee_id"],
        "driver_name": getattr(driver, "name", None) or f"Motorista #{identity['employee_id']}",
        "vehicle_plate": identity["vehicle_plate"],
        "session_started": bool(session_row),
        "session_status": getattr(session_row, "status", "") if session_row else "",
        "session_started_at": format_datetime_br(getattr(session_row, "started_at", None)) if session_row else "",
        "operator_label": "",
        "preview_message": WHATSAPP_DEFAULT_MESSAGE,
        "ready": ready,
        "ready_at": ready_at,
        "ready_at_fmt": format_datetime_br(ready_at),
        "last_sent_at": last_sent_at,
        "last_sent_at_fmt": format_datetime_br(last_sent_at),
        "last_sent_by": last_sent_batch.operator_label if last_sent_batch else "",
        "status": route_status,
        "status_label": WHATSAPP_ROUTE_STATUS_LABELS.get(route_status, route_status.title()),
        "can_send": bool(ready and summary["sendable"] > 0 and route_status != WHATSAPP_ROUTE_STATUS_PROCESSANDO),
        "can_retry_failed": bool(ready and summary["pending_retry"] > 0 and route_status != WHATSAPP_ROUTE_STATUS_PROCESSANDO),
        "summary": summary,
        "clients": clients_payload,
        "history": _serialize_history_batches(batches[:12]),
    }


def _apply_route_cache(
    routes: List[models.Route],
    snapshot: Dict[str, Any],
    *,
    ready_at: Optional[datetime] = None,
    last_sent_at: Optional[datetime] = None,
    last_sent_by: Optional[str] = None,
) -> None:
    summary_payload = {
        "status": snapshot.get("status"),
        "summary": snapshot.get("summary") or {},
        "route_group_key": snapshot.get("route_group_key"),
        "updated_at": now_br().isoformat(),
    }
    for route in routes:
        if ready_at and not getattr(route, "delivery_whatsapp_ready_at", None):
            route.delivery_whatsapp_ready_at = ready_at
        route.delivery_whatsapp_status = snapshot.get("status")
        route.delivery_whatsapp_last_sent_at = last_sent_at or snapshot.get("last_sent_at")
        route.delivery_whatsapp_last_sent_by = last_sent_by or snapshot.get("last_sent_by") or None
        route.delivery_whatsapp_summary_json = _safe_json_dumps(summary_payload)


def mark_delivery_group_whatsapp_ready(
    session: Session,
    *,
    route_date: str,
    shift: str,
    employee_id: int,
    vehicle_plate: str,
) -> Optional[Dict[str, Any]]:
    routes = list_delivery_group_routes(
        session,
        route_date=route_date,
        shift=shift,
        employee_id=employee_id,
        vehicle_plate=vehicle_plate,
    )
    if not routes:
        return None
    if not _group_session_started(session, routes):
        snapshot = build_delivery_whatsapp_snapshot(session, routes)
        _apply_route_cache(routes, snapshot)
        for route in routes:
            session.add(route)
        session.commit()
        return snapshot

    ready_at = min([
        _coerce_sp_datetime(route.delivery_whatsapp_ready_at)
        for route in routes
        if route.delivery_whatsapp_ready_at
    ] or [now_br()])
    for route in routes:
        if not route.delivery_whatsapp_ready_at:
            route.delivery_whatsapp_ready_at = ready_at
            session.add(route)

    snapshot = build_delivery_whatsapp_snapshot(session, routes)
    snapshot["ready_at"] = ready_at
    snapshot["ready_at_fmt"] = format_datetime_br(ready_at)
    if snapshot.get("status") == WHATSAPP_ROUTE_STATUS_NAO_DISPONIVEL:
        snapshot["status"] = WHATSAPP_ROUTE_STATUS_PENDENTE
        snapshot["status_label"] = WHATSAPP_ROUTE_STATUS_LABELS[WHATSAPP_ROUTE_STATUS_PENDENTE]
        snapshot["ready"] = True
    _apply_route_cache(routes, snapshot, ready_at=ready_at)
    for route in routes:
        session.add(route)
    session.commit()
    return snapshot


def prepare_delivery_whatsapp_snapshot(
    session: Session,
    *,
    route_date: str,
    shift: str,
    employee_id: int,
    vehicle_plate: str,
    auto_mark_ready: bool = True,
) -> Dict[str, Any]:
    routes = list_delivery_group_routes(
        session,
        route_date=route_date,
        shift=shift,
        employee_id=employee_id,
        vehicle_plate=vehicle_plate,
    )
    if not routes:
        raise ValueError("Rota nao encontrada.")
    if auto_mark_ready and _group_session_started(session, routes) and not any(route.delivery_whatsapp_ready_at for route in routes):
        mark_delivery_group_whatsapp_ready(
            session,
            route_date=route_date,
            shift=shift,
            employee_id=employee_id,
            vehicle_plate=vehicle_plate,
        )
        routes = list_delivery_group_routes(
            session,
            route_date=route_date,
            shift=shift,
            employee_id=employee_id,
            vehicle_plate=vehicle_plate,
        )
    return build_delivery_whatsapp_snapshot(session, routes)


def _resolve_sendable_clients_for_batch(
    snapshot: Dict[str, Any],
    *,
    only_client_ids: Optional[List[int]],
    allow_repeat: bool,
    skip_session_ready: bool,
    retry_failed: bool,
) -> List[Dict[str, Any]]:
    """Define quais linhas do snapshot entram no lote (subconjunto, reenvio, rota sem sessão)."""
    ready = bool(snapshot.get("ready"))
    clients = list(snapshot.get("clients") or [])
    id_set: Optional[set] = None
    if only_client_ids:
        id_set = {int(x) for x in only_client_ids if int(x) > 0}
        found_ids = {int(c["client_id"]) for c in clients}
        missing = id_set - found_ids
        if missing:
            raise ValueError("Um ou mais clientes selecionados nao pertencem a esta rota.")

    if retry_failed:
        out: List[Dict[str, Any]] = []
        for c in clients:
            cid = int(c["client_id"])
            if id_set is not None and cid not in id_set:
                continue
            if c.get("status") != WHATSAPP_ITEM_STATUS_FALHA:
                continue
            if not c.get("can_retry"):
                continue
            if not c.get("phone_normalized"):
                continue
            out.append(c)
        if not out:
            raise ValueError("Nao existem falhas pendentes para reenvio.")
        return out

    if skip_session_ready and not ready:
        if not id_set:
            raise ValueError("Selecione ao menos um cliente para enviar sem rota iniciada.")
        out = []
        for c in clients:
            cid = int(c["client_id"])
            if cid not in id_set:
                continue
            if c.get("status") == WHATSAPP_ITEM_STATUS_BLOQUEADO:
                continue
            if c.get("status") == WHATSAPP_ITEM_STATUS_SEM_CONTATO or not c.get("phone_normalized"):
                continue
            if c.get("status") == WHATSAPP_ITEM_STATUS_TELEFONE_INVALIDO:
                continue
            if c.get("status") == WHATSAPP_ITEM_STATUS_JA_ENVIADO and not allow_repeat:
                continue
            out.append(c)
        if not out:
            raise ValueError("Nenhum cliente selecionado elegivel para envio (sem rota iniciada).")
        return out

    if not ready:
        return []

    out = []
    for c in clients:
        cid = int(c["client_id"])
        if id_set is not None and cid not in id_set:
            continue
        if c.get("sendable"):
            out.append(c)
            continue
        if allow_repeat and c.get("status") == WHATSAPP_ITEM_STATUS_JA_ENVIADO:
            if not c.get("phone_normalized"):
                continue
            out.append(c)

    if not out:
        if id_set:
            raise ValueError("Nenhum cliente selecionado elegivel para envio com as opcoes atuais.")
        raise ValueError("Nao existem clientes elegiveis para envio.")

    return out


def send_delivery_whatsapp_notifications(
    session: Session,
    *,
    route_date: str,
    shift: str,
    employee_id: int,
    vehicle_plate: str,
    operator_label: str,
    operator_user_id: Optional[int] = None,
    retry_failed: bool = False,
    only_client_ids: Optional[List[int]] = None,
    allow_repeat: bool = False,
    skip_session_ready: bool = False,
    provider: Optional[BaseWhatsAppProvider] = None,
) -> Dict[str, Any]:
    routes = list_delivery_group_routes(
        session,
        route_date=route_date,
        shift=shift,
        employee_id=employee_id,
        vehicle_plate=vehicle_plate,
    )
    if not routes:
        raise ValueError("Rota nao encontrada.")

    if _group_session_started(session, routes) and not any(route.delivery_whatsapp_ready_at for route in routes):
        mark_delivery_group_whatsapp_ready(
            session,
            route_date=route_date,
            shift=shift,
            employee_id=employee_id,
            vehicle_plate=vehicle_plate,
        )
        routes = list_delivery_group_routes(
            session,
            route_date=route_date,
            shift=shift,
            employee_id=employee_id,
            vehicle_plate=vehicle_plate,
        )

    snapshot = build_delivery_whatsapp_snapshot(session, routes, retry_failed=retry_failed)
    ready = bool(snapshot.get("ready"))
    if not ready and not skip_session_ready:
        raise ValueError("A rota ainda nao ficou apta para notificacao.")

    sendable_clients = _resolve_sendable_clients_for_batch(
        snapshot,
        only_client_ids=only_client_ids,
        allow_repeat=allow_repeat,
        skip_session_ready=skip_session_ready,
        retry_failed=retry_failed,
    )

    latest_batch = session.exec(
        select(models.DeliveryWhatsAppBatch)
        .where(models.DeliveryWhatsAppBatch.route_group_key == snapshot["route_group_key"])
        .order_by(desc(models.DeliveryWhatsAppBatch.created_at), desc(models.DeliveryWhatsAppBatch.id))
    ).first()
    if latest_batch and latest_batch.status == WHATSAPP_ROUTE_STATUS_PROCESSANDO:
        raise ValueError("Ja existe um lote em processamento para esta rota.")

    started_at = now_br()
    provider_impl = provider or get_whatsapp_provider()
    batch = models.DeliveryWhatsAppBatch(
        route_group_key=snapshot["route_group_key"],
        route_date=route_date,
        shift=shift,
        employee_id=employee_id,
        vehicle_plate=vehicle_plate,
        status=WHATSAPP_ROUTE_STATUS_PROCESSANDO,
        provider_name=provider_impl.provider_name,
        operator_user_id=operator_user_id,
        operator_label=operator_label,
        total_clients=int(snapshot["summary"].get("total_clients") or 0),
        eligible_count=len(sendable_clients),
        sent_count=0,
        failed_count=0,
        ignored_count=int(snapshot["summary"].get("ignored") or 0),
        no_contact_count=int(snapshot["summary"].get("no_contact") or 0),
        invalid_count=int(snapshot["summary"].get("invalid_phone") or 0),
        blocked_count=int(snapshot["summary"].get("blocked") or 0),
        already_sent_count=int(snapshot["summary"].get("already_sent") or 0),
        is_retry=retry_failed,
        preview_message=WHATSAPP_DEFAULT_MESSAGE,
        request_payload_json=_safe_json_dumps(
            {
                "retry_failed": retry_failed,
                "allow_repeat": allow_repeat,
                "skip_session_ready": skip_session_ready,
                "only_client_ids": only_client_ids,
                "sendable_client_ids": [int(client["client_id"]) for client in sendable_clients],
            }
        ),
        started_at=started_at,
    )
    session.add(batch)

    processing_snapshot = dict(snapshot)
    processing_snapshot["status"] = WHATSAPP_ROUTE_STATUS_PROCESSANDO
    processing_snapshot["status_label"] = WHATSAPP_ROUTE_STATUS_LABELS[WHATSAPP_ROUTE_STATUS_PROCESSANDO]
    processing_snapshot["can_send"] = False
    processing_snapshot["can_retry_failed"] = False
    _apply_route_cache(routes, processing_snapshot, ready_at=snapshot.get("ready_at"), last_sent_by=operator_label)
    for route in routes:
        session.add(route)
    session.commit()
    session.refresh(batch)

    sent_count = 0
    failed_count = 0
    per_client_results: List[Dict[str, Any]] = []

    try:
        for client_payload in sendable_clients:
            metadata = {
                "route_group_key": snapshot["route_group_key"],
                "route_date": route_date,
                "shift": shift,
                "employee_id": employee_id,
                "vehicle_plate": vehicle_plate,
                "client_id": client_payload["client_id"],
                "route_id": client_payload["route_id"],
                "retry_failed": retry_failed,
            }
            result = provider_impl.send_message(
                phone_number=str(client_payload.get("phone_normalized") or ""),
                message=WHATSAPP_DEFAULT_MESSAGE,
                metadata=metadata,
            )
            item_status = WHATSAPP_ITEM_STATUS_ENVIADO if result.success else WHATSAPP_ITEM_STATUS_FALHA
            sent_at = now_br() if result.success else None

            item = models.DeliveryWhatsAppItem(
                batch_id=batch.id,
                route_group_key=snapshot["route_group_key"],
                route_id=client_payload.get("route_id"),
                route_date=route_date,
                shift=shift,
                employee_id=employee_id,
                vehicle_plate=vehicle_plate,
                client_id=int(client_payload["client_id"]),
                client_name=str(client_payload.get("client_name") or ""),
                phone_raw=str(client_payload.get("phone_raw") or ""),
                phone_normalized=str(client_payload.get("phone_normalized") or ""),
                status=item_status,
                attempt_number=int(client_payload.get("attempt_count") or 0) + 1,
                provider_name=result.provider_name,
                provider_message_id=result.provider_message_id,
                operator_user_id=operator_user_id,
                operator_label=operator_label,
                request_payload_json=_safe_json_dumps(result.request_payload),
                response_json=_safe_json_dumps(result.response_payload),
                failure_reason=result.error_message,
                sent_at=sent_at,
            )
            session.add(item)

            if result.success:
                sent_count += 1
            else:
                failed_count += 1

            per_client_results.append(
                {
                    "client_id": client_payload["client_id"],
                    "client_name": client_payload.get("client_name") or "",
                    "status": item_status,
                    "provider_message_id": result.provider_message_id,
                    "error": result.error_message,
                }
            )

        finished_at = now_br()
        if sent_count > 0 and failed_count == 0:
            batch.status = WHATSAPP_ROUTE_STATUS_ENVIADO
        elif sent_count > 0 and failed_count > 0:
            batch.status = WHATSAPP_ROUTE_STATUS_ENVIADO_PARCIAL
        elif failed_count > 0:
            batch.status = WHATSAPP_ROUTE_STATUS_FALHA
        else:
            batch.status = WHATSAPP_ROUTE_STATUS_CANCELADO
        batch.sent_count = sent_count
        batch.failed_count = failed_count
        batch.finished_at = finished_at
        batch.response_json = _safe_json_dumps(
            {
                "provider": provider_impl.provider_name,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "results": per_client_results,
            }
        )
        if failed_count > 0 and sent_count == 0:
            batch.failure_reason = "Nenhuma mensagem foi aceita pelo provider."
        session.add(batch)
        session.flush()

        final_snapshot = build_delivery_whatsapp_snapshot(session, routes)
        _apply_route_cache(
            routes,
            final_snapshot,
            ready_at=final_snapshot.get("ready_at"),
            last_sent_at=finished_at if sent_count > 0 else None,
            last_sent_by=operator_label if sent_count > 0 else final_snapshot.get("last_sent_by"),
        )
        for route in routes:
            session.add(route)
        session.commit()

        _post_n8n_delivery_whatsapp_webhook(
            snapshot=final_snapshot,
            route_date=route_date,
            shift=shift,
            employee_id=employee_id,
            vehicle_plate=vehicle_plate,
            operator_label=operator_label,
            retry_failed=retry_failed,
            allow_repeat=allow_repeat,
            skip_session_ready=skip_session_ready,
            sent_count=sent_count,
            failed_count=failed_count,
            per_client_results=per_client_results,
        )

        return {
            "batch_id": batch.id,
            "batch_status": batch.status,
            "summary": final_snapshot["summary"],
            "snapshot": final_snapshot,
        }
    except Exception as exc:
        session.rollback()
        persisted_batch = session.get(models.DeliveryWhatsAppBatch, batch.id)
        if persisted_batch:
            persisted_batch.status = WHATSAPP_ROUTE_STATUS_FALHA
            persisted_batch.failed_count = max(int(persisted_batch.failed_count or 0), failed_count)
            persisted_batch.finished_at = now_br()
            persisted_batch.failure_reason = str(exc)
            session.add(persisted_batch)

        refreshed_routes = list_delivery_group_routes(
            session,
            route_date=route_date,
            shift=shift,
            employee_id=employee_id,
            vehicle_plate=vehicle_plate,
        )
        if refreshed_routes:
            failed_snapshot = build_delivery_whatsapp_snapshot(session, refreshed_routes)
            if persisted_batch:
                failed_snapshot["status"] = WHATSAPP_ROUTE_STATUS_FALHA
                failed_snapshot["status_label"] = WHATSAPP_ROUTE_STATUS_LABELS[WHATSAPP_ROUTE_STATUS_FALHA]
            _apply_route_cache(refreshed_routes, failed_snapshot, ready_at=failed_snapshot.get("ready_at"))
            for route in refreshed_routes:
                session.add(route)
        session.commit()
        raise


def remark_delivery_whatsapp_clients(
    session: Session,
    *,
    route_date: str,
    shift: str,
    employee_id: int,
    vehicle_plate: str,
    client_ids: List[int],
) -> Dict[str, Any]:
    """Remove o histórico de envio (itens) para permitir um novo envio manual.

    Observação: esta operação é intencionalmente simples e afeta apenas o grupo de rota.
    """
    routes = list_delivery_group_routes(
        session,
        route_date=route_date,
        shift=shift,
        employee_id=employee_id,
        vehicle_plate=vehicle_plate,
    )
    if not routes:
        raise ValueError("Rota nao encontrada.")

    identity = get_route_group_identity(routes)
    ids = [int(cid) for cid in (client_ids or []) if int(cid) > 0]
    if not ids:
        raise ValueError("Nenhum cliente selecionado para remarcar.")

    items = list(
        session.exec(
            select(models.DeliveryWhatsAppItem)
            .where(models.DeliveryWhatsAppItem.route_group_key == identity["route_group_key"])
            .where(models.DeliveryWhatsAppItem.client_id.in_(ids))
        ).all()
    )
    if not items:
        snapshot = build_delivery_whatsapp_snapshot(session, routes)
        _apply_route_cache(routes, snapshot, ready_at=snapshot.get("ready_at"))
        for route in routes:
            session.add(route)
        session.commit()
        return snapshot

    for item in items:
        session.delete(item)
    session.commit()

    snapshot = build_delivery_whatsapp_snapshot(session, routes)
    _apply_route_cache(routes, snapshot, ready_at=snapshot.get("ready_at"))
    for route in routes:
        session.add(route)
    session.commit()
    return snapshot


def build_delivery_whatsapp_page_overview(
    session: Session,
    *,
    route_date: str,
    shift: str,
    employee_id: int,
    vehicle_plate: str,
    auto_mark_ready: bool = False,
) -> Dict[str, Any]:
    snapshot = prepare_delivery_whatsapp_snapshot(
        session,
        route_date=route_date,
        shift=shift,
        employee_id=employee_id,
        vehicle_plate=vehicle_plate,
        auto_mark_ready=auto_mark_ready,
    )
    return {
        "route_group_key": snapshot["route_group_key"],
        "status": snapshot["status"],
        "status_label": snapshot["status_label"],
        "summary": snapshot["summary"],
        "ready_at_fmt": snapshot["ready_at_fmt"],
        "ready_at_iso": snapshot["ready_at"].isoformat() if snapshot.get("ready_at") else "",
        "last_sent_at_fmt": snapshot["last_sent_at_fmt"],
        "last_sent_at_iso": snapshot["last_sent_at"].isoformat() if snapshot.get("last_sent_at") else "",
        "last_sent_by": snapshot["last_sent_by"],
        "can_send": snapshot["can_send"],
        "can_retry_failed": snapshot["can_retry_failed"],
    }


def list_delivery_whatsapp_history(
    session: Session,
    *,
    route_date: Optional[str] = None,
    shift: Optional[str] = None,
    employee_id: Optional[int] = None,
    vehicle_plate: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    query = select(models.DeliveryWhatsAppBatch).order_by(
        desc(models.DeliveryWhatsAppBatch.created_at),
        desc(models.DeliveryWhatsAppBatch.id),
    )
    if route_date:
        query = query.where(models.DeliveryWhatsAppBatch.route_date == route_date)
    if shift:
        query = query.where(models.DeliveryWhatsAppBatch.shift == shift)
    if employee_id:
        query = query.where(models.DeliveryWhatsAppBatch.employee_id == employee_id)
    if status:
        query = query.where(models.DeliveryWhatsAppBatch.status == status)
    if date_from:
        query = query.where(models.DeliveryWhatsAppBatch.route_date >= date_from)
    if date_to:
        query = query.where(models.DeliveryWhatsAppBatch.route_date <= date_to)

    batches = list(session.exec(query.limit(max(1, min(limit, 300)))).all())
    plate_norm = normalize_plate(vehicle_plate)
    if plate_norm:
        batches = [batch for batch in batches if normalize_plate(batch.vehicle_plate) == plate_norm]

    batch_ids = [int(batch.id) for batch in batches if batch.id]
    items: List[models.DeliveryWhatsAppItem] = []
    if batch_ids:
        items = list(
            session.exec(
                select(models.DeliveryWhatsAppItem)
                .where(models.DeliveryWhatsAppItem.batch_id.in_(batch_ids))
                .order_by(desc(models.DeliveryWhatsAppItem.created_at), desc(models.DeliveryWhatsAppItem.id))
            ).all()
        )

    item_rows = [
        {
            "id": item.id,
            "batch_id": item.batch_id,
            "route_date": item.route_date,
            "shift": item.shift,
            "employee_id": item.employee_id,
            "vehicle_plate": item.vehicle_plate,
            "client_id": item.client_id,
            "client_name": item.client_name or "",
            "phone_display": item.phone_normalized or item.phone_raw or "",
            "status": item.status,
            "status_label": WHATSAPP_ITEM_STATUS_LABELS.get(item.status, item.status.title()),
            "attempt_number": int(item.attempt_number or 0),
            "operator_label": item.operator_label or "",
            "provider_message_id": item.provider_message_id or "",
            "failure_reason": item.failure_reason or "",
            "sent_at": format_datetime_br(item.sent_at),
            "created_at": format_datetime_br(item.created_at),
        }
        for item in items
    ]

    return {
        "batches": _serialize_history_batches(batches),
        "items": item_rows,
    }
