# -*- coding: utf-8 -*-
"""Rotas de BI de Entregas e Devoluções."""

from datetime import datetime, timedelta, date
from typing import Optional
import io
import csv
import statistics
import json
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


def _fmt_br_1(val):
    """Um decimal: 1.234,5"""
    if val is None:
        return "0,0"
    try:
        return f"{float(val):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)


def _fmt_br_2(val):
    """Dois decimais: 1.234,56"""
    if val is None:
        return "0,00"
    try:
        return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)


def _fmt_br_int(val):
    """Inteiro com ponto milhar: 1.234"""
    if val is None:
        return "0"
    try:
        return f"{int(float(val)):,}".replace(",", ".")
    except Exception:
        return str(val)


def _fmt_br_data(s):
    """YYYY-MM-DD -> DD/MM/YYYY"""
    if not s or not str(s).strip():
        return "-"
    try:
        parts = str(s).strip().split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except Exception:
        pass
    return str(s)


def _fmt_br_moeda(val):
    """R$ 1.234,56"""
    if val is None:
        return "R$ 0,00"
    try:
        return "R$ " + _fmt_br_2(val)
    except Exception:
        return "R$ —"


templates.env.filters["fmt_br_1"] = _fmt_br_1
templates.env.filters["fmt_br_2"] = _fmt_br_2
templates.env.filters["fmt_br_int"] = _fmt_br_int
templates.env.filters["fmt_br_data"] = _fmt_br_data
templates.env.filters["fmt_br_moeda"] = _fmt_br_moeda


def _ma(vals: list[float], w: int) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for i in range(len(vals)):
        chunk = vals[max(0, i - w + 1): i + 1]
        out.append(round(sum(chunk) / len(chunk), 2) if chunk else None)
    return out


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

    def _d(raw: Optional[str]) -> Optional[date]:
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            return None

    date_i = _d(date_from) or today.replace(day=1)
    date_f = _d(date_to) or today
    if date_i > date_f:
        date_i, date_f = date_f, date_i

    st = (status or "Todos").strip().lower()
    pl = (plate or "Todos").strip().upper()
    detail_status_norm = (detail_status or "Todos").strip().lower()

    q = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= date_i.strftime("%Y-%m-%d"))
        .where(models.Route.date <= date_f.strftime("%Y-%m-%d"))
    )
    if shift and shift != "Todos":
        q = q.where(models.Route.shift == shift)
    if driver_id:
        q = q.where(models.Route.employee_id == driver_id)
    if pl and pl != "TODOS":
        q = q.where(models.Route.delivery_vehicle_plate == pl)
    if st and st != "todos":
        q = q.where(func.lower(models.Route.delivery_status) == st)
    routes = session.exec(q.order_by(models.Route.date, models.Route.created_at)).all()

    manual = []
    if (st in ("todos", "devolucao")) and pl == "TODOS":
        qm = (
            select(models.Devolucao)
            .where(models.Devolucao.data_romaneio >= date_i.strftime("%Y-%m-%d"))
            .where(models.Devolucao.data_romaneio <= date_f.strftime("%Y-%m-%d"))
        )
        if driver_id:
            qm = qm.where(models.Devolucao.motorista_id == driver_id)
        manual = session.exec(qm.order_by(models.Devolucao.data_romaneio, models.Devolucao.created_at)).all()

    emp_ids = sorted({r.employee_id for r in routes if r.employee_id} | {d.motorista_id for d in manual if d.motorista_id})
    cli_ids = sorted({r.client_id for r in routes if r.client_id} | {d.client_id for d in manual if d.client_id})
    emp_map = {e.id: e for e in (session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all() if emp_ids else [])}
    cli_map = {c.id: c for c in (session.exec(select(models.Client).where(models.Client.id.in_(cli_ids))).all() if cli_ids else [])}
    mot_map = {m.id: m for m in (session.exec(select(models.DevolucaoMotivo)).all())}
    rsp_map = {r.id: r for r in (session.exec(select(models.DevolucaoResponsabilidade)).all())}

    def _hm(v: Optional[str]) -> Optional[int]:
        if not v:
            return None
        try:
            h, m = str(v).split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return None

    def _dur(a: Optional[str], b: Optional[str]) -> Optional[int]:
        sa, sb = _hm(a), _hm(b)
        if sa is None or sb is None:
            return None
        if sb < sa:
            sb += 24 * 60
        return max(0, sb - sa)

    planned_stops = len(routes)
    planned_kg = planned_value = 0.0
    realized_stops = started_stops = 0
    realized_kg = realized_value = 0.0
    returned_stops = 0
    returned_kg = returned_value = 0.0
    reopen_routes = 0
    dur_list: list[int] = []

    per_day: dict[str, dict] = {}
    per_driver: dict[str, dict] = {}
    motivo_agg: dict[str, dict] = {}
    resp_agg: dict[str, dict] = {}
    cluster_agg: dict[str, dict] = {}
    ret_count_day: dict[str, int] = {}
    ret_value_day: dict[str, float] = {}
    client_returns: dict[str, int] = {}
    reopen_heat: dict[str, dict[str, int]] = {}
    route_rows: list[dict] = []
    ex_rows: list[dict] = []

    def _acc_devol(date_key: str, driver_name: str, client_name: str, motivo: str, resp: str, cluster: str, val: float):
        nonlocal returned_stops, returned_value
        returned_stops += 1
        returned_value += val
        ret_count_day[date_key] = ret_count_day.get(date_key, 0) + 1
        ret_value_day[date_key] = round(ret_value_day.get(date_key, 0.0) + val, 2)
        motivo_agg.setdefault(motivo, {"motivo": motivo, "qtd": 0, "valor": 0.0})
        motivo_agg[motivo]["qtd"] += 1
        motivo_agg[motivo]["valor"] += val
        resp_agg.setdefault(resp, {"responsabilidade": resp, "qtd": 0, "valor": 0.0})
        resp_agg[resp]["qtd"] += 1
        resp_agg[resp]["valor"] += val
        cluster_agg.setdefault(cluster, {"cluster": cluster, "qtd": 0, "valor": 0.0})
        cluster_agg[cluster]["qtd"] += 1
        cluster_agg[cluster]["valor"] += val
        client_returns[client_name] = client_returns.get(client_name, 0) + 1

    for r in routes:
        status_raw = (r.delivery_status or "pendente").strip().lower()
        emp = emp_map.get(r.employee_id)
        cli = cli_map.get(r.client_id)
        driver = emp.name if emp else f"Motorista #{r.employee_id}"
        client = cli.name if cli else f"Cliente #{r.client_id}"
        planned_w = float(r.tonnage or 0.0)
        planned_v = float(r.valor_financeiro or 0.0)
        ret_w = float(r.devolucao_volume if r.devolucao_volume is not None else (planned_w if status_raw == "devolucao" else 0.0))
        ret_v = float(r.valor_devolucao if r.valor_devolucao is not None else (planned_v if status_raw == "devolucao" else 0.0))
        del_w = max(0.0, planned_w - ret_w) if status_raw == "devolucao" else (planned_w if status_raw == "entregue" else 0.0)
        del_v = max(0.0, planned_v - ret_v) if status_raw == "devolucao" else (planned_v if status_raw == "entregue" else 0.0)
        dur = _dur(r.delivery_started_at or r.start_time, r.delivery_finished_at or r.end_time)

        planned_kg += planned_w
        planned_value += planned_v
        if status_raw in ("iniciada", "devolucao", "entregue"):
            started_stops += 1
        if status_raw in ("devolucao", "entregue"):
            realized_stops += 1
            realized_kg += del_w
            realized_value += del_v
            if dur is not None:
                dur_list.append(dur)
        if status_raw == "devolucao":
            returned_kg += ret_w
            _acc_devol(r.date, driver, client, (r.delivery_return_reason or "Nao informado"), (r.delivery_return_category or "Nao informado"), "Sem Cluster", ret_v)
        if (r.delivery_reopen_count or 0) > 0:
            reopen_routes += 1
            reopen_heat.setdefault(r.date, {})
            reopen_heat[r.date][driver] = reopen_heat[r.date].get(driver, 0) + int(r.delivery_reopen_count or 0)

        per_day.setdefault(r.date, {"date": r.date, "planned_stops": 0, "started_stops": 0, "realized_stops": 0, "returned_stops": 0, "planned_kg": 0.0, "returned_kg": 0.0, "planned_value": 0.0, "returned_value": 0.0})
        d = per_day[r.date]
        d["planned_stops"] += 1
        d["planned_kg"] += planned_w
        d["planned_value"] += planned_v
        if status_raw in ("iniciada", "devolucao", "entregue"):
            d["started_stops"] += 1
        if status_raw in ("devolucao", "entregue"):
            d["realized_stops"] += 1
        if status_raw == "devolucao":
            d["returned_stops"] += 1
            d["returned_kg"] += ret_w
            d["returned_value"] += ret_v

        per_driver.setdefault(driver, {"driver_name": driver, "driver_id": r.employee_id, "planned_stops": 0, "realized_stops": 0, "started_stops": 0, "returned_stops": 0, "planned_kg": 0.0, "realized_kg": 0.0, "returned_kg": 0.0, "planned_value": 0.0, "realized_value": 0.0, "returned_value": 0.0, "reopen_count": 0, "durations": [], "main_plate": (r.delivery_vehicle_plate or "-").upper()})
        b = per_driver[driver]
        b["planned_stops"] += 1
        b["planned_kg"] += planned_w
        b["planned_value"] += planned_v
        b["reopen_count"] += (r.delivery_reopen_count or 0)
        if status_raw in ("iniciada", "devolucao", "entregue"):
            b["started_stops"] += 1
        if status_raw in ("devolucao", "entregue"):
            b["realized_stops"] += 1
            b["realized_kg"] += del_w
            b["realized_value"] += del_v
        if status_raw == "devolucao":
            b["returned_stops"] += 1
            b["returned_kg"] += ret_w
            b["returned_value"] += ret_v
        if dur is not None:
            b["durations"].append(dur)

        row = {"route_id": r.id, "date": r.date, "shift": r.shift, "driver_id": r.employee_id, "driver_name": driver, "client_id": r.client_id, "client_name": client, "status": status_raw, "planned_kg": round(planned_w, 2), "planned_value": round(planned_v, 2), "delivered_kg": round(del_w, 2), "delivered_value": round(del_v, 2), "returned_kg": round(ret_w if status_raw == "devolucao" else 0.0, 2), "returned_value": round(ret_v if status_raw == "devolucao" else 0.0, 2), "reopen_count": r.delivery_reopen_count or 0, "duration_m": dur, "plate": (r.delivery_vehicle_plate or "-").upper(), "order_number": r.delivery_order_number or "-", "motivo": r.delivery_return_reason or "-", "responsabilidade": r.delivery_return_category or "-", "cluster": "Sem Cluster", "acima_300": ("SIM" if ret_v >= 300 and status_raw == "devolucao" else "NAO"), "source": "ROTA"}
        route_rows.append(row)
        score = (55 if status_raw == "devolucao" else 20 if status_raw == "iniciada" else 25 if status_raw in ("pendente", "reaberta") else 0) + min(20, (r.delivery_reopen_count or 0) * 6) + (10 if (dur or 0) > 120 else 0) + (8 if planned_w >= 500 else 0)
        if score >= 30:
            ex_rows.append({"score": score, "date": r.date, "shift": r.shift, "driver_name": driver, "driver_id": r.employee_id, "client_name": client, "status": status_raw, "planned_kg": round(planned_w, 2), "planned_value": round(planned_v, 2), "returned_kg": round(ret_w if status_raw == "devolucao" else 0.0, 2), "returned_value": round(ret_v if status_raw == "devolucao" else 0.0, 2), "reopen_count": r.delivery_reopen_count or 0, "duration_m": dur, "source": "ROTA"})

    for d in manual:
        driver = (emp_map.get(d.motorista_id).name if emp_map.get(d.motorista_id) else f"Motorista #{d.motorista_id}")
        client = (cli_map.get(d.client_id).name if cli_map.get(d.client_id) else f"Cliente #{d.client_id}")
        motivo = (mot_map.get(d.motivo_id).nome if mot_map.get(d.motivo_id) else "Nao informado")
        resp = (rsp_map.get(d.responsabilidade_id).nome if rsp_map.get(d.responsabilidade_id) else "Nao informado")
        cluster = d.cluster or "Sem Cluster"
        ret_v = float(d.valor or 0.0)
        above = "SIM" if (d.acima_300 or "").upper() == "SIM" or ret_v >= 300 else "NAO"
        _acc_devol(d.data_romaneio, driver, client, motivo, resp, cluster, ret_v)
        route_rows.append({"route_id": -d.id, "date": d.data_romaneio, "shift": "-", "driver_id": d.motorista_id, "driver_name": driver, "client_id": d.client_id, "client_name": client, "status": "devolucao", "planned_kg": 0.0, "planned_value": 0.0, "delivered_kg": 0.0, "delivered_value": 0.0, "returned_kg": 0.0, "returned_value": round(ret_v, 2), "reopen_count": 0, "duration_m": None, "plate": "-", "order_number": f"Man. {d.id}", "motivo": motivo, "responsabilidade": resp, "cluster": cluster, "acima_300": above, "source": "MANUAL"})
        ex_rows.append({"score": 55, "date": d.data_romaneio, "shift": "-", "driver_name": driver, "driver_id": d.motorista_id, "client_name": client, "status": "devolucao", "planned_kg": 0.0, "planned_value": 0.0, "returned_kg": 0.0, "returned_value": round(ret_v, 2), "reopen_count": 0, "duration_m": None, "source": "MANUAL"})
        per_driver.setdefault(driver, {"driver_name": driver, "driver_id": d.motorista_id, "planned_stops": 0, "realized_stops": 0, "started_stops": 0, "returned_stops": 0, "planned_kg": 0.0, "realized_kg": 0.0, "returned_kg": 0.0, "planned_value": 0.0, "realized_value": 0.0, "returned_value": 0.0, "reopen_count": 0, "durations": [], "main_plate": "-"})
        per_driver[driver]["returned_stops"] += 1
        per_driver[driver]["returned_value"] += ret_v

    avg_duration = statistics.mean(dur_list) if dur_list else 0.0
    global_return_rate = (returned_stops / max(1, planned_stops) * 100.0) if (planned_stops or manual) else 0.0
    tactical = []
    for row in per_driver.values():
        p = max(1, row["planned_stops"])
        v = max(0.01, row["planned_value"]) # Avoid division by zero
        delivered_stops = max(0, row["realized_stops"] - row["returned_stops"])
        tactical.append({
            **row,
            "delivered_stops": delivered_stops,
            "efficiency": round(delivered_stops / p * 100.0, 2) if row["planned_stops"] else 0.0,
            "return_rate": round(row["returned_stops"] / p * 100.0, 2) if row["planned_stops"] else (100.0 if row["returned_stops"] > 0 else 0.0),
            "started_rate": round(row["started_stops"] / p * 100.0, 2) if row["planned_stops"] else 0.0,
            "avg_duration": round(statistics.mean(row["durations"]), 1) if row["durations"] else 0.0,
            "returned_value_pct": round((row["returned_value"] / v) * 100.0, 2) if row["planned_value"] else 0.0
        })
    tactical.sort(key=lambda x: (x["efficiency"], -x["return_rate"], x["planned_stops"]), reverse=True)

    daily_rows = []
    for day in sorted(per_day):
        row = per_day[day]
        denom = max(1, row["planned_stops"])
        row["started_rate"] = round(row["started_stops"] / denom * 100.0, 2)
        row["return_rate"] = round(row["returned_stops"] / denom * 100.0, 2)
        daily_rows.append(row)
    rec7 = daily_rows[-7:] if len(daily_rows) >= 7 else daily_rows
    forecast_stops = round(statistics.mean([x["planned_stops"] for x in rec7]), 1) if rec7 else 0.0
    forecast_return_qtd = round(statistics.mean([x["return_rate"] for x in rec7]), 2) if rec7 else 0.0
    forecast_return_value = round(
        statistics.mean([
            ((x.get("returned_value", 0.0) or 0.0) / max(0.01, (x.get("planned_value", 0.0) or 0.0))) * 100.0
            if (x.get("planned_value", 0.0) or 0.0) > 0 else 0.0
            for x in rec7
        ]),
        2
    ) if rec7 else 0.0
    risk_label, risk_severity = ("Critico", "danger") if forecast_return_value >= 4 else ("Atencao", "warning") if forecast_return_value >= 2 else ("Controlado", "success")
    anomaly_flags: list[str] = []
    global_return_rate_value = (returned_value / max(0.01, planned_value) * 100.0) if planned_value else 0.0

    if global_return_rate_value >= 2:
        anomaly_flags.append(f"Ponto de atencao financeiro: devolucao em valor em {_fmt_br_1(global_return_rate_value)}% (meta <= 2,0%).")
    if client_returns:
        rec_client = [n for n, c in sorted(client_returns.items(), key=lambda x: x[1], reverse=True) if c >= 2][:3]
        if rec_client:
            anomaly_flags.append(f"Clientes com devolucao recorrente: {', '.join(rec_client)}.")
    if cluster_agg:
        cl = max(cluster_agg.values(), key=lambda x: x["valor"])
        anomaly_flags.append(f"Cluster critico por valor: {cl['cluster']} (R$ {_fmt_br_2(cl['valor'])}).")
    if ret_value_day:
        dpk, vpk = max(ret_value_day.items(), key=lambda x: x[1])
        anomaly_flags.append(f"Pico de devolucao em {_fmt_br_data(dpk)}: R$ {_fmt_br_2(vpk)}.")
    high_value_drivers = sorted(
        [x for x in tactical if (x.get("returned_value_pct") or 0) >= 2 and (x.get("planned_stops") or 0) >= 5],
        key=lambda x: (x.get("returned_value_pct") or 0),
        reverse=True
    )[:3]
    if high_value_drivers:
        anomaly_flags.append(
            "Motoristas acima da meta financeira: " +
            ", ".join([f"{x['driver_name']} ({_fmt_br_1(x.get('returned_value_pct') or 0)}%)" for x in high_value_drivers]) +
            "."
        )
    dias_acima_meta = [
        d for d, v in per_day.items()
        if (v.get("planned_value", 0.0) or 0.0) > 0 and ((v.get("returned_value", 0.0) or 0.0) / max(0.01, (v.get("planned_value", 0.0) or 0.0)) * 100.0) >= 2
    ]
    if len(dias_acima_meta) >= 3:
        anomaly_flags.append(f"Serie de risco: {len(dias_acima_meta)} dia(s) com devolucao em valor acima de 2,0%.")

    recommendations = []
    if global_return_rate_value >= 2:
        recommendations.append("Priorizar plano de contencao financeira: devolver no maximo 2,0% do valor real.")
    if tactical:
        wr = max(tactical, key=lambda x: x["returned_value_pct"])
        if wr["returned_value_pct"] >= 2 and wr["planned_stops"] >= 5:
            recommendations.append(f"Rebalancear carteira de {wr['driver_name']} (devolucao em valor: {_fmt_br_1(wr['returned_value_pct'])}%).")
    if started_stops < planned_stops:
        recommendations.append("Atuar na fila de pendentes com prioridade por maior impacto.")
    if avg_duration >= 120:
        recommendations.append("Tempo medio elevado: revisar sequencia e janela de entrega.")
    if motivo_agg:
        top_motivo_val = max(motivo_agg.values(), key=lambda x: x["valor"])
        recommendations.append(f"Estudo 80/20: atacar primeiro o motivo '{top_motivo_val['motivo']}' (R$ {_fmt_br_2(top_motivo_val['valor'])}).")
    if client_returns:
        top_cliente, top_qtd = max(client_returns.items(), key=lambda x: x[1])
        if top_qtd >= 2:
            recommendations.append(f"Estudo de causa raiz com cliente {top_cliente}: {top_qtd} devolucoes no periodo.")
    if not recommendations:
        recommendations.append("Operacao estavel no periodo; manter monitoramento diario.")

    total_mot = sum(v["qtd"] for v in motivo_agg.values()) or 1
    motivos_rows = sorted([{"motivo": v["motivo"], "qtd": int(v["qtd"]), "valor": round(v["valor"], 2), "pct": round(v["qtd"] / total_mot * 100.0, 2)} for v in motivo_agg.values()], key=lambda x: (x["qtd"], x["valor"]), reverse=True)

    # Motivo x Motorista x Qtd x Valor x % valor real (para gráfico detalhado)
    motivo_motorista: dict[str, dict[str, dict]] = {}
    for r in route_rows:
        if r.get("status") != "devolucao" or (r.get("returned_value") or 0) <= 0:
            continue
        motivo = r.get("motivo") or "Nao informado"
        driver = r.get("driver_name") or "-"
        val = float(r.get("returned_value") or 0.0)
        motivo_motorista.setdefault(motivo, {})
        motivo_motorista[motivo].setdefault(driver, {"qtd": 0, "valor": 0.0})
        motivo_motorista[motivo][driver]["qtd"] += 1
        motivo_motorista[motivo][driver]["valor"] = round(motivo_motorista[motivo][driver]["valor"] + val, 2)
    motivo_names = sorted(motivo_motorista.keys(), key=lambda m: -sum(d["valor"] for d in motivo_motorista[m].values()))[:15]
    driver_names_mot = sorted({d for m_data in motivo_motorista.values() for d in m_data.keys()})
    motivos_detailed = []
    for motivo in motivo_names:
        row = {"motivo": motivo, "qtd": 0, "valor": 0.0, "pct": 0.0, "por_motorista": {}}
        for driver, data in motivo_motorista[motivo].items():
            row["qtd"] += data["qtd"]
            row["valor"] += data["valor"]
            valor_real_drv = (per_driver.get(driver, {}).get("realized_value") or 0.0) + (per_driver.get(driver, {}).get("returned_value") or 0.0)
            pct_val = round(data["valor"] / valor_real_drv * 100.0, 2) if valor_real_drv > 0 else (100.0 if data["valor"] > 0 else 0.0)
            row["por_motorista"][driver] = {"qtd": data["qtd"], "valor": data["valor"], "pct_valor_real": pct_val}
        row["valor"] = round(row["valor"], 2)
        row["pct"] = round(row["qtd"] / total_mot * 100.0, 2) if total_mot else 0.0
        motivos_detailed.append(row)
    resp_rows = sorted([{"responsabilidade": v["responsabilidade"], "qtd": int(v["qtd"]), "valor": round(v["valor"], 2)} for v in resp_agg.values()], key=lambda x: x["qtd"], reverse=True)
    cluster_rows = sorted([{"cluster": v["cluster"], "qtd": int(v["qtd"]), "valor": round(v["valor"], 2)} for v in cluster_agg.values()], key=lambda x: x["valor"], reverse=True)

    # Motorista x Responsabilidade x Valor: valor devolvido por motorista e responsabilidade, % devolução baseada em valor real
    driver_resp_value: dict[str, dict[str, float]] = {}
    for r in route_rows:
        if r.get("status") != "devolucao" or (r.get("returned_value") or 0) <= 0:
            continue
        drv = r.get("driver_name") or "-"
        resp = r.get("responsabilidade") or "Nao informado"
        val = float(r.get("returned_value") or 0.0)
        driver_resp_value.setdefault(drv, {})
        driver_resp_value[drv][resp] = round(driver_resp_value[drv].get(resp, 0.0) + val, 2)
    resp_names = sorted({r for drv_data in driver_resp_value.values() for r in drv_data.keys()})
    driver_resp_rows = []
    for drv, data in per_driver.items():
        resp_vals = {r: driver_resp_value.get(drv, {}).get(r, 0.0) for r in resp_names}
        total_ret = sum(resp_vals.values())
        valor_real = (data.get("realized_value") or 0.0) + (data.get("returned_value") or 0.0)
        pct_devolucao_valor = round(total_ret / valor_real * 100.0, 2) if valor_real > 0 else (100.0 if total_ret > 0 else 0.0)
        driver_resp_rows.append({
            "driver": drv,
            "responsabilidades": resp_vals,
            "valor_devolvido": round(total_ret, 2),
            "valor_real": round(valor_real, 2),
            "pct_devolucao_valor": pct_devolucao_valor,
        })
    driver_resp_rows = [r for r in driver_resp_rows if r["valor_devolvido"] > 0]
    driver_resp_rows = sorted(driver_resp_rows, key=lambda x: -x["valor_devolvido"])[:20]

    # Correlacao Motorista x Cliente x Devolucoes (bubble/scatter)
    pair_agg: dict[tuple[str, str], dict] = {}
    for r in route_rows:
        if r.get("status") != "devolucao":
            continue
        drv = r.get("driver_name") or "-"
        cli = r.get("client_name") or "Sem cliente"
        val = float(r.get("returned_value") or 0.0)
        key = (drv, cli)
        pair_agg.setdefault(key, {"driver": drv, "client": cli, "qtd": 0, "valor": 0.0})
        pair_agg[key]["qtd"] += 1
        pair_agg[key]["valor"] = round(pair_agg[key]["valor"] + val, 2)

    pair_rows = sorted(pair_agg.values(), key=lambda x: (x["valor"], x["qtd"]), reverse=True)[:120]
    corr_drivers = sorted({x["driver"] for x in pair_rows})
    corr_clients = sorted({x["client"] for x in pair_rows})
    corr_driver_idx = {d: i for i, d in enumerate(corr_drivers)}
    corr_client_idx = {c: i for i, c in enumerate(corr_clients)}
    corr_points = []
    for p in pair_rows:
        d_data = per_driver.get(p["driver"], {})
        valor_real_drv = (d_data.get("realized_value") or 0.0) + (d_data.get("returned_value") or 0.0)
        pct_val = round((p["valor"] / valor_real_drv) * 100.0, 2) if valor_real_drv > 0 else (100.0 if p["valor"] > 0 else 0.0)
        corr_points.append({
            "x": corr_driver_idx.get(p["driver"], 0),
            "y": corr_client_idx.get(p["client"], 0),
            "r": max(4, min(20, 4 + (p["valor"] ** 0.5) * 0.12)),
            "driver": p["driver"],
            "client": p["client"],
            "qtd": p["qtd"],
            "valor": round(p["valor"], 2),
            "pct_valor_real": pct_val,
        })
    def _prev_month_key(date_key: str) -> Optional[str]:
        try:
            dref = datetime.strptime(str(date_key), "%Y-%m-%d").date()
            y = dref.year
            m = dref.month - 1
            if m == 0:
                m = 12
                y -= 1
            # Ajusta para o ultimo dia valido do mes anterior (ex.: 31 -> 30/28/29)
            max_day = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
            d = min(dref.day, max_day)
            return date(y, m, d).strftime("%Y-%m-%d")
        except Exception:
            return None

    trend_dates = sorted(set(list(per_day.keys()) + list(ret_count_day.keys())))
    trend_qtd = [ret_count_day.get(k, 0) for k in trend_dates]
    trend_val = [round(ret_value_day.get(k, 0.0), 2) for k in trend_dates]
    trend_meta_2pct = [round((per_day.get(k, {}).get("planned_value", 0.0) or 0.0) * 0.02, 2) for k in trend_dates]
    trend_last_month_val: list[Optional[float]] = []
    for k in trend_dates:
        pm = _prev_month_key(k)
        trend_last_month_val.append(round(ret_value_day.get(pm, 0.0), 2) if pm else None)
    heat_rows = [{"date": dt, "driver": drv, "value": v} for dt, d in reopen_heat.items() for drv, v in d.items()]

    filters_payload = {"date_from": date_i.strftime("%Y-%m-%d"), "date_to": date_f.strftime("%Y-%m-%d"), "shift": shift, "driver_id": driver_id, "plate": plate, "status": status, "detail_driver_id": detail_driver_id, "detail_status": detail_status}
    filters_query = urlencode({"date_from": filters_payload["date_from"], "date_to": filters_payload["date_to"], "shift": filters_payload["shift"], "driver_id": filters_payload["driver_id"] or "", "plate": filters_payload["plate"], "status": filters_payload["status"]})
    detail_rows = sorted(route_rows, key=lambda x: (x["date"], x["shift"], x["driver_name"], x["route_id"]))
    if detail_driver_id:
        detail_rows = [r for r in detail_rows if r["driver_id"] == detail_driver_id]
    if detail_status_norm != "todos":
        detail_rows = [r for r in detail_rows if r["status"] == detail_status_norm]

    delivered_stops = max(0, realized_stops - returned_stops)

    # Devolução mês anterior (query dedicada)
    def _prev_month_range(d: date) -> tuple[date, date]:
        y, m = d.year, d.month - 1
        if m == 0:
            m, y = 12, y - 1
        first = date(y, m, 1)
        last = date(y, m, [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
        return first, last
    prev_first, prev_last = _prev_month_range(date_i)
    prev_str_first = prev_first.strftime("%Y-%m-%d")
    prev_str_last = prev_last.strftime("%Y-%m-%d")
    q_prev = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= prev_str_first)
        .where(models.Route.date <= prev_str_last)
    )
    if shift and shift != "Todos":
        q_prev = q_prev.where(models.Route.shift == shift)
    if driver_id:
        q_prev = q_prev.where(models.Route.employee_id == driver_id)
    if pl and pl != "TODOS":
        q_prev = q_prev.where(models.Route.delivery_vehicle_plate == pl)
    prev_routes = session.exec(q_prev).all()
    prev_month_planned_val = 0.0
    prev_month_qtd = 0
    prev_month_valor = 0.0
    for r in prev_routes:
        status_raw = (r.delivery_status or "pendente").strip().lower()
        planned_v = float(r.valor_financeiro or 0.0)
        prev_month_planned_val += planned_v
        if status_raw == "devolucao":
            prev_month_qtd += 1
            prev_month_valor += float(r.valor_devolucao if r.valor_devolucao is not None else planned_v)
    if st in ("todos", "devolucao") and pl == "TODOS":
        qm_prev = (
            select(models.Devolucao)
            .where(models.Devolucao.data_romaneio >= prev_str_first)
            .where(models.Devolucao.data_romaneio <= prev_str_last)
        )
        if driver_id:
            qm_prev = qm_prev.where(models.Devolucao.motorista_id == driver_id)
        for d in session.exec(qm_prev).all():
            prev_month_qtd += 1
            prev_month_valor += float(d.valor or 0.0)
    prev_month_pct = round(prev_month_valor / max(0.01, prev_month_planned_val) * 100.0, 2) if prev_month_planned_val else 0.0

    kpis = {
        "planned_stops": planned_stops,
        "realized_stops": realized_stops,
        "delivered_stops": delivered_stops,
        "started_stops": started_stops,
        "pending_stops": max(0, planned_stops - started_stops),
        "planned_kg": round(planned_kg, 2),
        "realized_kg": round(realized_kg, 2),
        "returned_kg": round(returned_kg, 2),
        "planned_value": round(planned_value, 2),
        "realized_value": round(realized_value, 2),
        "returned_value": round(returned_value, 2),
        "return_rate_qtd": round(returned_stops / max(1, planned_stops) * 100.0, 2) if planned_stops else 0.0,
        "return_rate_kg": round(returned_kg / max(1, planned_kg) * 100.0, 2) if planned_kg else 0.0,
        "return_rate_value": round(returned_value / max(1, planned_value) * 100.0, 2) if planned_value else 0.0,
        "sla_start": round(started_stops / max(1, planned_stops) * 100.0, 2) if planned_stops else 0.0,
        "sla_finish": round(delivered_stops / max(1, planned_stops) * 100.0, 2) if planned_stops else 0.0,
        "reopen_index": round(reopen_routes / max(1, planned_stops) * 100.0, 2) if planned_stops else 0.0,
        "avg_duration_m": round(avg_duration, 1),
        "forecast_next_stops": forecast_stops,
        "forecast_next_return_rate": forecast_return_value,
        "forecast_next_return_rate_qtd": forecast_return_qtd,
        "forecast_next_return_rate_value": forecast_return_value,
        "total_devolucoes": returned_stops,
        "valor_total_devolvido": round(returned_value, 2),
        "devolucoes_acima_300_count": len([r for r in route_rows if r.get("acima_300") == "SIM"]),
        "devolucoes_acima_300_pct": round((len([r for r in route_rows if r.get("acima_300") == "SIM"]) / max(1, returned_stops)) * 100.0, 2) if returned_stops else 0.0,
        "risk_label": risk_label,
        "risk_severity": risk_severity,
        "meta_devolucao_pct": 2.0,
        "devolucao_mes_anterior_qtd": prev_month_qtd,
        "devolucao_mes_anterior_valor": round(prev_month_valor, 2),
        "devolucao_mes_anterior_pct": prev_month_pct,
    }

    chart_payload = {
        "trend": {
            "dates": trend_dates,
            "qtd": trend_qtd,
            "valor": trend_val,
            "ma7": _ma(trend_val, 7),
            "ma30": _ma(trend_val, 30),
            "meta_2pct": trend_meta_2pct,
            "last_month_valor": trend_last_month_val,
        },
        "motivos": motivos_rows,
        "motivos_detailed": motivos_detailed,
        "motivos_drivers": driver_names_mot,
        "responsabilidade": resp_rows,
        "cluster": cluster_rows,
        "drivers": [{"driver": r["driver_name"], "eficiencia": r["efficiency"], "devolucao_pct": r["return_rate"], "devolucao_valor_pct": r["returned_value_pct"], "valor_devolvido": r["returned_value"]} for r in tactical][:20],
        "reopen_heatmap": heat_rows,
        "driver_resp_valor": {
            "drivers": [r["driver"] for r in driver_resp_rows],
            "responsabilidades": resp_names,
            "datasets": [{"resp": r, "data": [driver_resp_value.get(drv, {}).get(r, 0.0) for drv in [x["driver"] for x in driver_resp_rows]]} for r in resp_names] if resp_names else [],
            "pct_devolucao_valor": [r["pct_devolucao_valor"] for r in driver_resp_rows],
        },
        "driver_client_corr": {
            "drivers": corr_drivers,
            "clients": corr_clients,
            "points": corr_points,
        },
    }

    return {
        "filters": filters_payload,
        "kpis": kpis,
        "daily_rows": daily_rows,
        "tactical_rows": tactical,
        "exception_rows": sorted(ex_rows, key=lambda x: x["score"], reverse=True)[:25],
        "anomaly_flags": anomaly_flags[:10],
        "recommendations": recommendations[:6],
        "drivers_filter": sorted([{"id": d["driver_id"], "name": d["driver_name"]} for d in tactical], key=lambda x: x["name"]),
        "plates_filter": sorted({x["main_plate"] for x in tactical if x["main_plate"] and x["main_plate"] != "-"}),
        "statuses_filter": ["Todos", "Pendente", "Iniciada", "Entregue", "Devolucao", "Reaberta", "Cancelada"],
        "detail_rows": detail_rows[:300],
        "detail_title": "Drill-through operacional",
        "detail_total": len(detail_rows),
        "filters_query": filters_query,
        "all_route_rows": route_rows,
        "motivos_rows": motivos_rows[:12],
        "responsabilidade_rows": resp_rows,
        "cluster_rows": cluster_rows,
        "chart_payload_json": json.dumps(chart_payload, ensure_ascii=False),
        "detail_rows_json": json.dumps(detail_rows, ensure_ascii=False),
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
    parsed_driver_id: Optional[int] = int(driver_id) if (driver_id or "").strip().isdigit() else None
    parsed_detail_driver_id: Optional[int] = int(detail_driver_id) if (detail_driver_id or "").strip().isdigit() else None
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
    parsed_driver_id: Optional[int] = int(driver_id) if (driver_id or "").strip().isdigit() else None
    dataset = _build_bi_delivery_dataset(session, date_from, date_to, shift, parsed_driver_id, plate, status)
    rows = dataset["all_route_rows"]
    stamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M")
    fmt = (format or "csv").strip().lower()

    def _row_data_br(r):
        data_br = _fmt_br_data(r["date"])
        kg_p = _fmt_br_2(r.get("planned_kg", 0))
        kg_d = _fmt_br_2(r.get("delivered_kg", 0))
        kg_ret = _fmt_br_2(r.get("returned_kg", 0))
        v_p = _fmt_br_2(r.get("planned_value", 0))
        v_d = _fmt_br_2(r.get("delivered_value", 0))
        v_ret = _fmt_br_2(r.get("returned_value", 0))
        return [r["route_id"], data_br, r["shift"], r["driver_name"], r["client_name"], r["status"], kg_p, kg_d, kg_ret, v_p, v_d, v_ret, r["reopen_count"], r["duration_m"] or "", r["plate"], r["order_number"], r.get("motivo", ""), r.get("responsabilidade", ""), r.get("cluster", ""), r.get("acima_300", ""), r.get("source", "")]

    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow(["rota_id", "data", "turno", "motorista", "cliente", "status", "kg_planejado", "kg_entregue", "kg_devolvido", "valor_planejado", "valor_entregue", "valor_devolvido", "reaberturas", "duracao_min", "placa", "pedido", "motivo", "responsabilidade", "cluster", "acima_300", "origem"])
        for r in rows:
            w.writerow(_row_data_br(r))
        buf = io.BytesIO(out.getvalue().encode("utf-8-sig"))
        return StreamingResponse(buf, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=bi_entregas_{stamp}.csv"})

    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "BI Entregas"
        ws.append(["Rota ID", "Data", "Turno", "Motorista", "Cliente", "Status", "Kg Planejado", "Kg Entregue", "Kg Devolvido", "Valor Planejado", "Valor Entregue", "Valor Devolvido", "Reaberturas", "Duracao (min)", "Placa", "Pedido", "Motivo", "Responsabilidade", "Cluster", "Acima 300", "Origem"])
        for r in rows:
            ws.append(_row_data_br(r))
        xbuf = io.BytesIO()
        wb.save(xbuf)
        xbuf.seek(0)
        return StreamingResponse(xbuf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=bi_entregas_{stamp}.xlsx"})

    if fmt == "pdf":
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        pbuf = io.BytesIO()
        c = canvas.Canvas(pbuf, pagesize=A4)
        _, h = A4
        y = h - 40
        c.setFont("Helvetica-Bold", 12)
        c.drawString(30, y, "BI Entregas - Relatorio Executivo")
        y -= 16
        c.setFont("Helvetica", 9)
        period_from = _fmt_br_data(dataset["filters"]["date_from"])
        period_to = _fmt_br_data(dataset["filters"]["date_to"])
        c.drawString(30, y, f"Periodo: {period_from} ate {period_to}")
        y -= 14
        c.drawString(30, y, f"Planejadas: {dataset['kpis']['planned_stops']} | Realizadas: {dataset['kpis']['realized_stops']} | Devolucao: {_fmt_br_1(dataset['kpis']['return_rate_qtd'])}%")
        y -= 20
        c.setFont("Helvetica", 8)
        for r in rows[:180]:
            if y <= 30:
                c.showPage()
                y = h - 30
                c.setFont("Helvetica", 8)
            c.drawString(30, y, _fmt_br_data(r["date"]))
            c.drawString(95, y, str(r["driver_name"])[:28])
            c.drawString(265, y, str(r["client_name"])[:32])
            c.drawString(450, y, str(r["status"])[:10])
            c.drawRightString(590, y, _fmt_br_2(r.get("planned_value", 0)))
            y -= 10
        c.save()
        pbuf.seek(0)
        return StreamingResponse(pbuf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=bi_entregas_{stamp}.pdf"})

    return JSONResponse({"error": "Formato invalido. Use csv, xlsx ou pdf."}, status_code=400)
