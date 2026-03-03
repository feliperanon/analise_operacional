# -*- coding: utf-8 -*-
"""Rotas de BI de Entregas (modularizado de main.py)."""

from datetime import datetime, timedelta, date
from typing import Optional
import io
import csv
import statistics
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlmodel import Session, select
from sqlalchemy import func

import models
from database import get_session

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def _build_bi_delivery_dataset(
    session: Session,
    date_from: Optional[str],
    date_to: Optional[str],
    shift: str,
    driver_id: Optional[int],
    plate: str,
    status: str,
    detail_driver_id: Optional[int] = None,
    detail_status: str = "Todos",
) -> dict:
    tz = ZoneInfo("America/Sao_Paulo")
    today = datetime.now(tz).date()

    def _parse_date(raw: Optional[str]) -> Optional[date]:
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            return None

    parsed_from = _parse_date(date_from) or (today - timedelta(days=6))
    parsed_to = _parse_date(date_to) or today
    if parsed_from > parsed_to:
        parsed_from, parsed_to = parsed_to, parsed_from

    status_norm = (status or "Todos").strip().lower()
    plate_norm = (plate or "Todos").strip().upper()
    detail_status_norm = (detail_status or "Todos").strip().lower()

    query = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= parsed_from.strftime("%Y-%m-%d"))
        .where(models.Route.date <= parsed_to.strftime("%Y-%m-%d"))
    )
    if shift and shift != "Todos":
        query = query.where(models.Route.shift == shift)
    if driver_id:
        query = query.where(models.Route.employee_id == driver_id)
    if plate_norm and plate_norm != "TODOS":
        query = query.where(models.Route.delivery_vehicle_plate == plate_norm)
    if status_norm and status_norm != "todos":
        query = query.where(func.lower(models.Route.delivery_status) == status_norm)

    routes = session.exec(query.order_by(models.Route.date, models.Route.created_at)).all()

    # Devoluções lançadas manualmente (módulo Devoluções - Excel/manual)
    include_manual = (status_norm == "todos" or status_norm == "devolucao") and plate_norm == "TODOS"
    manual_devolucoes = []
    if include_manual:
        q_manual = (
            select(models.Devolucao)
            .where(models.Devolucao.data_romaneio >= parsed_from.strftime("%Y-%m-%d"))
            .where(models.Devolucao.data_romaneio <= parsed_to.strftime("%Y-%m-%d"))
        )
        if driver_id:
            q_manual = q_manual.where(models.Devolucao.motorista_id == driver_id)
        manual_devolucoes = session.exec(q_manual.order_by(models.Devolucao.data_romaneio, models.Devolucao.created_at)).all()

    employee_ids = sorted({r.employee_id for r in routes if r.employee_id})
    client_ids = sorted({r.client_id for r in routes if r.client_id})
    employee_ids = sorted(set(employee_ids) | {d.motorista_id for d in manual_devolucoes if d.motorista_id})
    client_ids = sorted(set(client_ids) | {d.client_id for d in manual_devolucoes if d.client_id})
    plate_set = sorted({(r.delivery_vehicle_plate or "").strip().upper() for r in routes if (r.delivery_vehicle_plate or "").strip()})

    employee_map = {}
    if employee_ids:
        emps = session.exec(select(models.Employee).where(models.Employee.id.in_(employee_ids))).all()
        employee_map = {e.id: e for e in emps}

    client_map = {}
    if client_ids:
        clients = session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all()
        client_map = {c.id: c for c in clients}

    vehicle_map = {}
    if plate_set:
        vehicles = session.exec(select(models.Vehicle).where(models.Vehicle.placa.in_(plate_set))).all()
        vehicle_map = {v.placa.upper(): v for v in vehicles}

    def _parse_hhmm(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            hh, mm = str(value).strip().split(":")
            return int(hh) * 60 + int(mm)
        except Exception:
            return None

    def _duration_minutes(start_value: Optional[str], end_value: Optional[str]) -> Optional[int]:
        start_m = _parse_hhmm(start_value)
        end_m = _parse_hhmm(end_value)
        if start_m is None or end_m is None:
            return None
        if end_m < start_m:
            end_m += 24 * 60
        return max(0, end_m - start_m)

    per_driver = {}
    per_day = {}
    route_rows = []
    exception_rows = []
    route_durations = []
    anomaly_flags = []

    planned_stops = len(routes)
    planned_kg = 0.0
    planned_value = 0.0
    realized_stops = 0
    realized_kg = 0.0
    realized_value = 0.0
    started_stops = 0
    returned_stops = 0
    returned_kg = 0.0
    returned_value = 0.0
    reopen_routes = 0

    for r in routes:
        status_raw = (r.delivery_status or "pendente").strip().lower()
        employee = employee_map.get(r.employee_id)
        client = client_map.get(r.client_id)

        driver_name = employee.name if employee else f"Motorista #{r.employee_id}"
        truck_plate = (r.delivery_vehicle_plate or "-").upper()
        vehicle = vehicle_map.get(truck_plate)
        vehicle_label = f"{truck_plate} - {vehicle.modelo}" if vehicle else truck_plate
        planned_w = float(r.tonnage or 0.0)
        planned_v = float(r.valor_financeiro or 0.0)
        return_w = float(r.devolucao_volume if r.devolucao_volume is not None else (planned_w if status_raw == "devolucao" else 0.0))
        return_v = float(r.valor_devolucao if r.valor_devolucao is not None else (planned_v if status_raw == "devolucao" else 0.0))
        delivered_w = max(0.0, planned_w - return_w) if status_raw == "devolucao" else (planned_w if status_raw == "entregue" else 0.0)
        delivered_v = max(0.0, planned_v - return_v) if status_raw == "devolucao" else (planned_v if status_raw == "entregue" else 0.0)

        planned_kg += planned_w
        planned_value += planned_v

        is_started = status_raw in ("iniciada", "devolucao", "entregue")
        is_realized = status_raw in ("devolucao", "entregue")
        if is_started:
            started_stops += 1
        if is_realized:
            realized_stops += 1
            realized_kg += delivered_w
            realized_value += delivered_v
        if status_raw == "devolucao":
            returned_stops += 1
            returned_kg += return_w
            returned_value += return_v
        if (r.delivery_reopen_count or 0) > 0:
            reopen_routes += 1

        duration_m = _duration_minutes(r.delivery_started_at or r.start_time, r.delivery_finished_at or r.end_time)
        if duration_m is not None and is_realized:
            route_durations.append(duration_m)

        route_rows.append({
            "route_id": r.id,
            "date": r.date,
            "shift": r.shift,
            "driver_id": r.employee_id,
            "driver_name": driver_name,
            "client_id": r.client_id,
            "client_name": client.name if client else f"Cliente #{r.client_id}",
            "status": status_raw,
            "planned_kg": round(planned_w, 2),
            "planned_value": round(planned_v, 2),
            "delivered_kg": round(delivered_w, 2),
            "delivered_value": round(delivered_v, 2),
            "returned_kg": round(return_w if status_raw == "devolucao" else 0.0, 2),
            "returned_value": round(return_v if status_raw == "devolucao" else 0.0, 2),
            "reopen_count": r.delivery_reopen_count or 0,
            "duration_m": duration_m,
            "plate": truck_plate,
            "vehicle_label": vehicle_label,
            "address": r.delivery_address or "",
            "neighborhood": r.delivery_neighborhood or "",
            "city": r.delivery_city or "",
            "order_number": r.delivery_order_number or "-",
        })

        driver_bucket = per_driver.setdefault(
            driver_name,
            {
                "driver_name": driver_name,
                "driver_id": r.employee_id,
                "planned_stops": 0,
                "realized_stops": 0,
                "pending_stops": 0,
                "started_stops": 0,
                "returned_stops": 0,
                "planned_kg": 0.0,
                "realized_kg": 0.0,
                "returned_kg": 0.0,
                "planned_value": 0.0,
                "realized_value": 0.0,
                "returned_value": 0.0,
                "reopen_count": 0,
                "durations": [],
                "main_plate": truck_plate,
            },
        )
        driver_bucket["planned_stops"] += 1
        driver_bucket["planned_kg"] += planned_w
        driver_bucket["planned_value"] += planned_v
        driver_bucket["reopen_count"] += (r.delivery_reopen_count or 0)
        if is_started:
            driver_bucket["started_stops"] += 1
        if is_realized:
            driver_bucket["realized_stops"] += 1
            driver_bucket["realized_kg"] += delivered_w
            driver_bucket["realized_value"] += delivered_v
        else:
            driver_bucket["pending_stops"] += 1
        if status_raw == "devolucao":
            driver_bucket["returned_stops"] += 1
            driver_bucket["returned_kg"] += return_w
            driver_bucket["returned_value"] += return_v
        if duration_m is not None:
            driver_bucket["durations"].append(duration_m)

        day_bucket = per_day.setdefault(
            r.date,
            {
                "date": r.date,
                "planned_stops": 0,
                "started_stops": 0,
                "realized_stops": 0,
                "returned_stops": 0,
                "planned_kg": 0.0,
                "returned_kg": 0.0,
                "planned_value": 0.0,
                "returned_value": 0.0,
            },
        )
        day_bucket["planned_stops"] += 1
        day_bucket["planned_kg"] += planned_w
        day_bucket["planned_value"] += planned_v
        if is_started:
            day_bucket["started_stops"] += 1
        if is_realized:
            day_bucket["realized_stops"] += 1
        if status_raw == "devolucao":
            day_bucket["returned_stops"] += 1
            day_bucket["returned_kg"] += return_w
            day_bucket["returned_value"] += return_v

        score = 0
        if status_raw in ("pendente", "reaberta"):
            score += 25
        if status_raw == "iniciada":
            score += 20
        if status_raw == "devolucao":
            score += 55
        score += min(20, (r.delivery_reopen_count or 0) * 6)
        if duration_m is not None and duration_m > 120:
            score += 10
        if planned_w >= 500:
            score += 8

        if score >= 30:
            exception_rows.append(
                {
                    "route_id": r.id,
                    "date": r.date,
                    "shift": r.shift,
                    "driver_name": driver_name,
                    "driver_id": r.employee_id,
                    "client_name": client.name if client else f"Cliente #{r.client_id}",
                    "status": status_raw,
                    "planned_kg": round(planned_w, 2),
                    "planned_value": round(planned_v, 2),
                    "returned_kg": round(return_w if status_raw == "devolucao" else 0.0, 2),
                    "returned_value": round(return_v if status_raw == "devolucao" else 0.0, 2),
                    "reopen_count": r.delivery_reopen_count or 0,
                    "duration_m": duration_m,
                    "score": score,
                    "vehicle_label": vehicle_label,
                }
            )

    # Incluir devoluções manuais (Excel/manual)
    for d in manual_devolucoes:
        employee = employee_map.get(d.motorista_id)
        client = client_map.get(d.client_id)
        driver_name = employee.name if employee else f"Motorista #{d.motorista_id}"
        client_name = client.name if client else f"Cliente #{d.client_id}"
        return_v = float(d.valor or 0.0)
        return_w = 0.0  # manual não tem kg
        returned_stops += 1
        returned_value += return_v
        returned_kg += return_w
        route_rows.append({
            "route_id": -d.id,
            "date": d.data_romaneio,
            "shift": "-",
            "driver_id": d.motorista_id,
            "driver_name": driver_name,
            "client_id": d.client_id,
            "client_name": client_name,
            "status": "devolucao",
            "planned_kg": 0.0,
            "planned_value": 0.0,
            "delivered_kg": 0.0,
            "delivered_value": 0.0,
            "returned_kg": return_w,
            "returned_value": round(return_v, 2),
            "reopen_count": 0,
            "duration_m": None,
            "plate": "-",
            "vehicle_label": "-",
            "address": "",
            "neighborhood": "",
            "city": "",
            "order_number": f"Man. {d.id}",
            "source": "MANUAL",
        })
        driver_bucket = per_driver.setdefault(
            driver_name,
            {
                "driver_name": driver_name,
                "driver_id": d.motorista_id,
                "planned_stops": 0,
                "realized_stops": 0,
                "pending_stops": 0,
                "started_stops": 0,
                "returned_stops": 0,
                "planned_kg": 0.0,
                "realized_kg": 0.0,
                "returned_kg": 0.0,
                "planned_value": 0.0,
                "realized_value": 0.0,
                "returned_value": 0.0,
                "reopen_count": 0,
                "durations": [],
                "main_plate": "-",
            },
        )
        driver_bucket["returned_stops"] += 1
        driver_bucket["returned_value"] += return_v
        driver_bucket["returned_kg"] += return_w
        day_bucket = per_day.setdefault(
            d.data_romaneio,
            {
                "date": d.data_romaneio,
                "planned_stops": 0,
                "started_stops": 0,
                "realized_stops": 0,
                "returned_stops": 0,
                "planned_kg": 0.0,
                "returned_kg": 0.0,
                "planned_value": 0.0,
                "returned_value": 0.0,
            },
        )
        day_bucket["returned_stops"] += 1
        day_bucket["returned_value"] += return_v
        day_bucket["returned_kg"] += return_w
        exception_rows.append({
            "route_id": -d.id,
            "date": d.data_romaneio,
            "shift": "-",
            "driver_name": driver_name,
            "driver_id": d.motorista_id,
            "client_name": client_name,
            "status": "devolucao",
            "planned_kg": 0.0,
            "planned_value": 0.0,
            "returned_kg": return_w,
            "returned_value": round(return_v, 2),
            "reopen_count": 0,
            "duration_m": None,
            "score": 55,
            "vehicle_label": "Manual",
            "source": "MANUAL",
        })

    global_return_rate = (returned_stops / max(planned_stops, 1) * 100.0) if (planned_stops or manual_devolucoes) else 0.0
    avg_duration = statistics.mean(route_durations) if route_durations else 0.0

    tactical_rows = []
    for _, bucket in per_driver.items():
        avg_driver_duration = statistics.mean(bucket["durations"]) if bucket["durations"] else 0.0
        efficiency = (bucket["realized_stops"] / bucket["planned_stops"] * 100.0) if bucket["planned_stops"] else 0.0
        return_rate = (bucket["returned_stops"] / bucket["planned_stops"] * 100.0) if bucket["planned_stops"] else 0.0
        started_rate = (bucket["started_stops"] / bucket["planned_stops"] * 100.0) if bucket["planned_stops"] else 0.0
        tactical_rows.append({
            **bucket,
            "efficiency": round(efficiency, 2),
            "return_rate": round(return_rate, 2),
            "started_rate": round(started_rate, 2),
            "avg_duration": round(avg_driver_duration, 1),
        })
        if bucket["planned_stops"] >= 5 and return_rate >= (global_return_rate + 10.0):
            anomaly_flags.append(
                f"{bucket['driver_name']} com devolucao {return_rate:.1f}% (media geral {global_return_rate:.1f}%)."
            )
        if avg_driver_duration > 0 and avg_duration > 0 and avg_driver_duration >= (avg_duration * 1.8):
            anomaly_flags.append(
                f"{bucket['driver_name']} com tempo medio {avg_driver_duration:.0f} min (media geral {avg_duration:.0f} min)."
            )
    tactical_rows.sort(key=lambda x: (x["efficiency"], -x["return_rate"], x["planned_stops"]), reverse=True)

    daily_rows = []
    for day in sorted(per_day.keys()):
        row = per_day[day]
        denom = max(row["planned_stops"], 1)
        row["started_rate"] = round((row["started_stops"] / denom * 100.0), 2)
        row["return_rate"] = round((row["returned_stops"] / denom * 100.0), 2)
        daily_rows.append(row)

    last_n = daily_rows[-7:] if len(daily_rows) >= 7 else daily_rows
    if last_n:
        forecast_stops = round(statistics.mean([x["planned_stops"] for x in last_n]), 1)
        forecast_return_rate = round(statistics.mean([x["return_rate"] for x in last_n]), 2)
    else:
        forecast_stops = 0.0
        forecast_return_rate = 0.0

    exception_rows.sort(key=lambda x: (x["score"], x["planned_kg"]), reverse=True)
    top_exceptions = exception_rows[:25]

    recommendations = []
    if global_return_rate >= 10:
        recommendations.append("Priorizar auditoria de devolucao nas rotas com maior peso e revisar motivo/cliente recorrente.")
    if tactical_rows:
        worst_return = max(tactical_rows, key=lambda x: x["return_rate"])
        if worst_return["return_rate"] >= 15 and worst_return["planned_stops"] >= 5:
            recommendations.append(
                f"Rebalancear carga de {worst_return['driver_name']} e aplicar apoio adicional para reduzir devolucao."
            )
    if started_stops < planned_stops:
        recommendations.append("Atuar na fila de pendentes com priorizacao por alto peso para reduzir risco de atraso.")
    if avg_duration >= 120:
        recommendations.append("Tempo medio elevado: revisar sequencia de paradas e pontos de congestionamento.")
    if not recommendations:
        recommendations.append("Operacao estavel no periodo; manter monitoramento diario dos alertas de devolucao.")

    filters_payload = {
        "date_from": parsed_from.strftime("%Y-%m-%d"),
        "date_to": parsed_to.strftime("%Y-%m-%d"),
        "shift": shift,
        "driver_id": driver_id,
        "plate": plate,
        "status": status,
        "detail_driver_id": detail_driver_id,
        "detail_status": detail_status,
    }

    drivers_filter = sorted(
        [{"id": d["driver_id"], "name": d["driver_name"]} for d in tactical_rows],
        key=lambda x: x["name"],
    )
    plates_filter = sorted({x["main_plate"] for x in tactical_rows if x["main_plate"] and x["main_plate"] != "-"})

    detail_rows = route_rows
    detail_tokens = []
    if detail_driver_id:
        detail_rows = [r for r in detail_rows if r["driver_id"] == detail_driver_id]
        driver_label = next((r["driver_name"] for r in detail_rows), f"Motorista #{detail_driver_id}")
        detail_tokens.append(f"Motorista: {driver_label}")
    if detail_status_norm != "todos":
        detail_rows = [r for r in detail_rows if r["status"] == detail_status_norm]
        detail_tokens.append(f"Status: {detail_status_norm.title()}")
    detail_rows = sorted(detail_rows, key=lambda x: (x["date"], x["shift"], x["driver_name"], x["route_id"]))
    detail_title = " | ".join(detail_tokens) if detail_tokens else "Todos os detalhes do periodo"

    filters_query = urlencode(
        {
            "date_from": filters_payload["date_from"],
            "date_to": filters_payload["date_to"],
            "shift": filters_payload["shift"],
            "driver_id": filters_payload["driver_id"] or "",
            "plate": filters_payload["plate"],
            "status": filters_payload["status"],
        }
    )

    kpis = {
        "planned_stops": planned_stops,
        "realized_stops": realized_stops,
        "started_stops": started_stops,
        "pending_stops": max(0, planned_stops - started_stops),
        "planned_kg": round(planned_kg, 2),
        "realized_kg": round(realized_kg, 2),
        "returned_kg": round(returned_kg, 2),
        "planned_value": round(planned_value, 2),
        "realized_value": round(realized_value, 2),
        "returned_value": round(returned_value, 2),
        "return_rate_qtd": round((returned_stops / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "return_rate_kg": round((returned_kg / planned_kg * 100.0), 2) if planned_kg else 0.0,
        "return_rate_value": round((returned_value / planned_value * 100.0), 2) if planned_value else 0.0,
        "sla_start": round((started_stops / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "sla_finish": round((realized_stops / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "reopen_index": round((reopen_routes / planned_stops * 100.0), 2) if planned_stops else 0.0,
        "avg_duration_m": round(avg_duration, 1) if avg_duration else 0.0,
        "forecast_next_stops": forecast_stops,
        "forecast_next_return_rate": forecast_return_rate,
    }

    return {
        "filters": filters_payload,
        "kpis": kpis,
        "daily_rows": daily_rows,
        "tactical_rows": tactical_rows,
        "exception_rows": top_exceptions,
        "anomaly_flags": anomaly_flags[:10],
        "recommendations": recommendations[:6],
        "drivers_filter": drivers_filter,
        "plates_filter": plates_filter,
        "statuses_filter": ["Todos", "Pendente", "Iniciada", "Entregue", "Devolucao", "Reaberta", "Cancelada"],
        "detail_rows": detail_rows[:300],
        "detail_title": detail_title,
        "detail_total": len(detail_rows),
        "filters_query": filters_query,
        "all_route_rows": route_rows,
    }


@router.get("/bi/delivery", response_class=HTMLResponse)
async def bi_delivery_page(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    shift: str = "Todos",
    driver_id: Optional[str] = None,
    plate: str = "Todos",
    status: str = "Todos",
    detail_driver_id: Optional[str] = None,
    detail_status: str = "Todos",
    session: Session = Depends(get_session),
):
    parsed_driver_id: Optional[int] = None
    if driver_id is not None:
        raw_driver_filter = str(driver_id).strip()
        if raw_driver_filter.isdigit():
            parsed_driver_id = int(raw_driver_filter)

    parsed_detail_driver_id: Optional[int] = None
    if detail_driver_id is not None:
        raw_driver = str(detail_driver_id).strip()
        if raw_driver.isdigit():
            parsed_detail_driver_id = int(raw_driver)

    dataset = _build_bi_delivery_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift=shift,
        driver_id=parsed_driver_id,
        plate=plate,
        status=status,
        detail_driver_id=parsed_detail_driver_id,
        detail_status=detail_status,
    )
    return templates.TemplateResponse("bi_delivery.html", {"request": request, **dataset})


@router.get("/bi/delivery/export")
async def bi_delivery_export(
    format: str = "csv",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    shift: str = "Todos",
    driver_id: Optional[str] = None,
    plate: str = "Todos",
    status: str = "Todos",
    session: Session = Depends(get_session),
):
    parsed_driver_id: Optional[int] = None
    if driver_id is not None:
        raw_driver_filter = str(driver_id).strip()
        if raw_driver_filter.isdigit():
            parsed_driver_id = int(raw_driver_filter)

    dataset = _build_bi_delivery_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift=shift,
        driver_id=parsed_driver_id,
        plate=plate,
        status=status,
    )
    rows = dataset["all_route_rows"]
    timestamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M")
    fmt = (format or "csv").strip().lower()

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["rota_id", "data", "turno", "motorista", "cliente", "status", "kg_planejado", "kg_entregue", "kg_devolvido", "valor_planejado", "valor_entregue", "valor_devolvido", "reaberturas", "duracao_min", "placa", "pedido"])
        for r in rows:
            writer.writerow([r["route_id"], r["date"], r["shift"], r["driver_name"], r["client_name"], r["status"], f"{r['planned_kg']:.2f}", f"{r['delivered_kg']:.2f}", f"{r['returned_kg']:.2f}", f"{r['planned_value']:.2f}", f"{r['delivered_value']:.2f}", f"{r['returned_value']:.2f}", r["reopen_count"], r["duration_m"] or "", r["plate"], r["order_number"]])
        buffer = io.BytesIO(output.getvalue().encode("utf-8-sig"))
        filename = f"bi_entregas_{timestamp}.csv"
        return StreamingResponse(buffer, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})

    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "BI Entregas"
        ws.append(["Rota ID", "Data", "Turno", "Motorista", "Cliente", "Status", "Kg Planejado", "Kg Entregue", "Kg Devolvido", "Valor Planejado", "Valor Entregue", "Valor Devolvido", "Reaberturas", "Duracao (min)", "Placa", "Pedido"])
        for r in rows:
            ws.append([r["route_id"], r["date"], r["shift"], r["driver_name"], r["client_name"], r["status"], r["planned_kg"], r["delivered_kg"], r["returned_kg"], r["planned_value"], r["delivered_value"], r["returned_value"], r["reopen_count"], r["duration_m"] or 0, r["plate"], r["order_number"]])
        excel_buffer = io.BytesIO()
        wb.save(excel_buffer)
        excel_buffer.seek(0)
        filename = f"bi_entregas_{timestamp}.xlsx"
        return StreamingResponse(excel_buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})

    if fmt == "pdf":
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)
        width, height = A4
        y = height - 40
        c.setFont("Helvetica-Bold", 12)
        c.drawString(30, y, "BI Entregas - Relatorio Executivo")
        y -= 16
        c.setFont("Helvetica", 9)
        c.drawString(30, y, f"Periodo: {dataset['filters']['date_from']} ate {dataset['filters']['date_to']}")
        y -= 14
        c.drawString(30, y, f"Planejadas: {dataset['kpis']['planned_stops']} | Realizadas: {dataset['kpis']['realized_stops']} | Devolucao: {dataset['kpis']['return_rate_qtd']:.1f}%")
        y -= 20
        c.setFont("Helvetica-Bold", 9)
        c.drawString(30, y, "Data")
        c.drawString(95, y, "Motorista")
        c.drawString(265, y, "Cliente")
        c.drawString(450, y, "Status")
        c.drawString(500, y, "Kg")
        c.drawString(545, y, "R$")
        y -= 12
        c.setFont("Helvetica", 8)
        for r in rows[:180]:
            if y <= 30:
                c.showPage()
                y = height - 30
                c.setFont("Helvetica", 8)
            c.drawString(30, y, str(r["date"]))
            c.drawString(95, y, str(r["driver_name"])[:28])
            c.drawString(265, y, str(r["client_name"])[:32])
            c.drawString(450, y, str(r["status"])[:10])
            c.drawRightString(535, y, f"{r['planned_kg']:.1f}")
            c.drawRightString(590, y, f"{r['planned_value']:.0f}")
            y -= 10
        c.save()
        pdf_buffer.seek(0)
        filename = f"bi_entregas_{timestamp}.pdf"
        return StreamingResponse(pdf_buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})

    return JSONResponse({"error": "Formato invalido. Use csv, xlsx ou pdf."}, status_code=400)
