# -*- coding: utf-8 -*-
"""Rotas de BI de Entregas e Devoluções."""

from datetime import datetime, timedelta, date
import math
from typing import Any, Dict, List, Optional
import io
import time
import csv
import statistics
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlmodel import Session, select
from sqlalchemy import func, or_, and_

import models
from database import get_session
from route_duration import route_duration_minutes, route_duration_minutes_mobile_only
from devolucao_kpi_canonical import counts_devolucao_rotas_concluidas, pct_devolucao_sobre_rotas_concluidas
from utils.business_calendar import competence_date_str

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Motivos/responsabilidades: tabelas pequenas; cache em memória evita 2× leitura por página BI.
_BI_MOT_RSP_CACHE: dict = {"ts": 0.0, "mot": None, "rsp": None}
_BI_MOT_RSP_TTL_SEC = 300.0


def _json_for_inline_script(obj: Any) -> str:
    """JSON para <script type=\"application/json\">: impede que '</' em texto feche a tag e invalide o parse."""
    try:
        raw = json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        raw = json.dumps(obj, ensure_ascii=False, default=str)
    return raw.replace("</", "\\u003c/")


def _competence_period_window(date_i: date, date_f: date, pad_days: int = 10) -> tuple[str, str, str, str]:
    start = date_i.strftime("%Y-%m-%d")
    end = date_f.strftime("%Y-%m-%d")
    window_start = (date_i - timedelta(days=pad_days)).strftime("%Y-%m-%d")
    window_end = (date_f + timedelta(days=pad_days)).strftime("%Y-%m-%d")
    return start, end, window_start, window_end


def _competence_date_or_self(raw_date: Optional[str]) -> str:
    return competence_date_str(raw_date) or str(raw_date or "")[:10]


def _in_competence_period(raw_date: Optional[str], start: str, end: str) -> bool:
    comp = _competence_date_or_self(raw_date)
    return bool(comp) and start <= comp <= end


def _get_cached_mot_rsp_maps(session: Session):
    now = time.monotonic()
    if _BI_MOT_RSP_CACHE["mot"] is not None and (now - _BI_MOT_RSP_CACHE["ts"]) < _BI_MOT_RSP_TTL_SEC:
        return _BI_MOT_RSP_CACHE["mot"], _BI_MOT_RSP_CACHE["rsp"]
    mot_map = {m.id: m for m in session.exec(select(models.DevolucaoMotivo)).all()}
    rsp_map = {r.id: r for r in session.exec(select(models.DevolucaoResponsabilidade)).all()}
    _BI_MOT_RSP_CACHE["mot"] = mot_map
    _BI_MOT_RSP_CACHE["rsp"] = rsp_map
    _BI_MOT_RSP_CACHE["ts"] = now
    return mot_map, rsp_map


def _fmt_br_1(val):
    """Um decimal: 1.234,5"""
    if val is None:
        return "0,0"
    try:
        n = float(val)
        if not math.isfinite(n):
            return "0,0"
        return f"{n:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)


def _fmt_br_2(val):
    """Dois decimais: 1.234,56"""
    if val is None:
        return "0,00"
    try:
        n = float(val)
        if not math.isfinite(n):
            return "0,00"
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)


def _fmt_br_int(val):
    """Inteiro com ponto milhar: 1.234"""
    if val is None:
        return "0"
    try:
        n = float(val)
        if not math.isfinite(n):
            return "0"
        return f"{int(n):,}".replace(",", ".")
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


def _fmt_br_kg(val):
    """Peso em quilogramas (padrão BR: vírgula decimal)."""
    if val is None:
        return "—"
    try:
        return _fmt_br_2(val) + " kg"
    except Exception:
        return "—"


def _fmt_br_duracao(val):
    """Duração em minutos: <60 → 'X min'; ≥60 → 'X h Y min' (padrão BR)."""
    if val is None:
        return "—"
    try:
        m = int(round(float(val)))
        if m < 0:
            m = 0
        if m < 60:
            return f"{m} min"
        h, mn = m // 60, m % 60
        if mn == 0:
            return f"{h} h"
        return f"{h} h {mn} min"
    except Exception:
        return "—"


templates.env.filters["fmt_br_kg"] = _fmt_br_kg

templates.env.filters["fmt_br_1"] = _fmt_br_1
templates.env.filters["fmt_br_2"] = _fmt_br_2
templates.env.filters["fmt_br_int"] = _fmt_br_int
templates.env.filters["fmt_br_data"] = _fmt_br_data
templates.env.filters["fmt_br_moeda"] = _fmt_br_moeda
templates.env.filters["fmt_br_duracao"] = _fmt_br_duracao


def _norm_text(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _safe_pct(numerator: float, denominator: float) -> float:
    den = float(denominator or 0.0)
    num = float(numerator or 0.0)
    if not math.isfinite(den) or not math.isfinite(num) or den <= 0:
        return 0.0
    return (num / den) * 100.0


# Custo operacional estimado (R$/hora) — parâmetro explicável no tooltip
_BI_EXEC_HOURLY_COST = 75.0

_DURATION_BUCKET_LABELS = ("≤20 min", "21–40 min", "41–60 min", "61–90 min", ">90 min")


def _duration_bucket_idx(minutes: Optional[float]) -> Optional[int]:
    if minutes is None:
        return None
    try:
        m = float(minutes)
    except (TypeError, ValueError):
        return None
    if m <= 20:
        return 0
    if m <= 40:
        return 1
    if m <= 60:
        return 2
    if m <= 90:
        return 3
    return 4


def _classify_macro_cause(motivo: Optional[str], responsabilidade: Optional[str]) -> str:
    """Macrocausa para BI executivo (devolução / responsabilização)."""
    m = _norm_text(motivo or "")
    r = _norm_text(responsabilidade or "")
    t = f"{m} {r}"
    if any(
        k in t
        for k in (
            "sem dinheiro",
            "cheque",
            "credito",
            "crédito",
            "limite",
            "financeiro",
            "pagamento",
            "inadimpl",
        )
    ):
        return "Financeiro / pagamento"
    if any(k in t for k in ("fechado", "ausente", "nao estava", "não estava", "nao recebeu", "não recebeu", "desistiu")):
        return "Cliente / mercado"
    if any(
        k in t
        for k in (
            "localiz",
            "endereco",
            "endereço",
            "nao localizado",
            "não localizado",
            "cadastro",
            "janela",
            "horario entrega",
            "horário",
            "acesso dificil",
            "difícil acesso",
            "planejamento",
        )
    ):
        return "Cadastro / planejamento"
    if any(
        k in t
        for k in (
            "carregamento",
            "separacao",
            "separação",
            "expedicao",
            "expedição",
            "embalagem",
            "carga errada",
            "quantidade errada",
        )
    ):
        return "Logística"
    if "logist" in t:
        return "Logística"
    if any(k in t for k in ("preco", "preço", "prazo", "pedido", "produto", "comercial", "nao fez pedido", "não fez pedido", "venda")):
        return "Comercial"
    return "Comercial"


def _heatmap_delay_cause(row: dict) -> str:
    """Causa operacional para heatmap cidade × causa (visitas com atrito)."""
    st = _norm_text(row.get("status"))
    motivo = _norm_text(row.get("motivo") or "")
    if st == "devolucao":
        if any(k in motivo for k in ("fechado", "ausente", "fechado")):
            return "Cliente ausente / ponto fechado"
        if any(k in motivo for k in ("preco", "preço", "pedido", "produto", "comercial", "prazo")):
            return "Erro comercial (refletido na rota)"
        return "Devolução"
    if int(row.get("reopen_count") or 0) > 0:
        return "Reabertura"
    visit = str(row.get("visit_time") or "").strip()
    window = str(row.get("client_window") or "").strip()
    ws, we = _parse_client_window_range(window)
    if visit and ws is not None and we is not None:
        wmatch = _time_is_within_window(visit, ws, we)
        if wmatch is False:
            return "Horário / janela"
    dur = row.get("duration_m")
    if dur is not None and float(dur) > 55:
        if any(k in motivo for k in ("localiz", "nao localizado", "não localizado", "endereco", "endereço")):
            return "Local não localizado"
        if "acesso" in motivo:
            return "Difícil acesso"
    mc = _classify_macro_cause(row.get("motivo"), row.get("responsabilidade"))
    if mc == "Cadastro / planejamento":
        return "Erro cadastro / planejamento"
    if float(dur or 0) > 60:
        return "Demora operacional"
    return "Outros"


def _client_row_key(client_id, client_name: str) -> str:
    if client_id is not None:
        return f"id:{int(client_id)}"
    return f"name:{str(client_name or '').strip().lower()}"


def _exec_accumulate_rows(
    rows: list[dict],
    synth_group_id: Optional[int] = None,
    group_member_ids: Optional[set] = None,
    financial_rows: Optional[list[dict]] = None,
) -> dict:
    """Métricas executivas a partir de linhas ROTA/MANUAL filtradas."""
    unprod_by_key: dict[str, float] = {}
    macro_value_global: dict[str, float] = {}
    macro_time_global: dict[str, float] = {}
    macro_clients: dict[str, set] = {}
    macro_drivers: dict[str, set] = {}
    delivered_total = 0.0
    returned_total = 0.0
    planned_for_rate = 0.0
    manual_returned_sum = 0.0
    visits_rota = 0
    duration_total = 0.0
    unproductive_total = 0.0
    productive_total = 0.0
    bucket_visits = [0, 0, 0, 0, 0]
    bucket_value = [0.0, 0, 0, 0, 0]
    bucket_duration = [0.0, 0, 0, 0, 0]
    bucket_returns = [0, 0, 0, 0, 0]
    bucket_unprod = [0.0, 0, 0, 0, 0]
    city_bucket: dict[str, list] = {}
    city_cause: dict[str, dict[str, float]] = {}
    driver_unprod: dict[str, float] = {}
    cause_unprod_time: dict[str, float] = {}

    def row_key(row):
        cid = row.get("client_id")
        if synth_group_id and group_member_ids and cid is not None and int(cid) in group_member_ids:
            return _client_row_key(-int(synth_group_id), f"Grupo:{synth_group_id}")
        return _client_row_key(cid, str(row.get("client_name") or ""))

    for row in rows:
        src = str(row.get("source") or "ROTA").strip().upper()
        st = _norm_text(row.get("status"))
        cid = row.get("client_id")
        key = row_key(row)
        dur = row.get("duration_m")
        dval = float(dur or 0) if dur is not None else 0.0
        driver_name = str(row.get("driver_name") or "-").strip() or "-"
        city = str(row.get("client_city") or "Sem cidade").strip() or "Sem cidade"
        deliv_val = float(row.get("delivered_value") or 0.0)
        ret_val = float(row.get("returned_value") or 0.0)
        planned_v = float(row.get("planned_value") or 0.0)
        reopen = int(row.get("reopen_count") or 0)

        if src == "ROTA":
            visits_rota += 1
            planned_for_rate += planned_v
            delivered_total += deliv_val if st == "entregue" else (deliv_val if st == "devolucao" else 0.0)
            if financial_rows is None and st == "devolucao":
                returned_total += ret_val if ret_val > 0 else planned_v
            if dur is not None:
                duration_total += dval
                is_unproductive = st == "devolucao" or reopen > 0 or st in ("reaberta", "cancelada")
                if is_unproductive:
                    unproductive_total += dval
                    unprod_by_key[key] = unprod_by_key.get(key, 0.0) + dval
                    driver_unprod[driver_name] = driver_unprod.get(driver_name, 0.0) + dval
                else:
                    productive_total += dval
                bi = _duration_bucket_idx(dur)
                if bi is not None:
                    bucket_visits[bi] += 1
                    bucket_value[bi] += deliv_val if st == "entregue" else (deliv_val if st == "devolucao" else planned_v * 0.01)
                    bucket_duration[bi] += dval
                    if st == "devolucao":
                        bucket_returns[bi] += 1
                        bucket_unprod[bi] += dval
                    elif is_unproductive:
                        bucket_unprod[bi] += dval
                    city_bucket.setdefault(city, [0, 0, 0, 0, 0])
                    city_bucket[city][bi] += 1
                if st == "devolucao" or reopen > 0 or (dur and float(dur) > 60) or (
                    st != "entregue" and st != "pendente"
                ):
                    cause = _heatmap_delay_cause(row)
                    city_cause.setdefault(city, {})
                    city_cause[city][cause] = city_cause[city].get(cause, 0.0) + 1.0
                    if dur and (st == "devolucao" or reopen > 0):
                        cause_unprod_time[cause] = cause_unprod_time.get(cause, 0.0) + dval
        elif financial_rows is None and src == "MANUAL" and st == "devolucao" and ret_val > 0:
            returned_total += ret_val
            manual_returned_sum += ret_val
        if financial_rows is None and st == "devolucao" and ret_val > 0:
            macro = _classify_macro_cause(row.get("motivo"), row.get("responsabilidade"))
            macro_value_global[macro] = macro_value_global.get(macro, 0.0) + ret_val
            if dur:
                macro_time_global[macro] = macro_time_global.get(macro, 0.0) + dval
            macro_clients.setdefault(macro, set())
            if cid is not None:
                macro_clients[macro].add(int(cid))
            macro_drivers.setdefault(macro, set())
            macro_drivers[macro].add(driver_name)

    if financial_rows is not None:
        for row in financial_rows:
            ret_val = float(row.get("value") or row.get("returned_value") or 0.0)
            if ret_val <= 0:
                continue
            cid = row.get("client_id")
            driver_name = str(row.get("driver_name") or "-").strip() or "-"
            returned_total += ret_val
            if row.get("standalone"):
                manual_returned_sum += ret_val
            macro = _classify_macro_cause(row.get("motivo"), row.get("responsabilidade"))
            macro_value_global[macro] = macro_value_global.get(macro, 0.0) + ret_val
            macro_clients.setdefault(macro, set())
            if cid is not None:
                macro_clients[macro].add(int(cid))
            macro_drivers.setdefault(macro, set())
            macro_drivers[macro].add(driver_name)

    fin_base = planned_for_rate + manual_returned_sum
    if fin_base <= 0:
        fin_base = max(delivered_total + returned_total, 0.01)
    return {
        "unprod_by_key": unprod_by_key,
        "macro_value_global": macro_value_global,
        "macro_time_global": macro_time_global,
        "macro_clients": macro_clients,
        "macro_drivers": macro_drivers,
        "delivered_total": round(delivered_total, 2),
        "returned_total": round(returned_total, 2),
        "financial_base": round(max(fin_base, 0.01), 2),
        "visits_rota": visits_rota,
        "duration_total": round(duration_total, 1),
        "unproductive_total": round(unproductive_total, 1),
        "productive_total": round(productive_total, 1),
        "bucket_visits": bucket_visits,
        "bucket_value": [round(x, 2) for x in bucket_value],
        "bucket_duration": [round(x, 1) for x in bucket_duration],
        "bucket_returns": bucket_returns,
        "bucket_unprod": [round(x, 1) for x in bucket_unprod],
        "city_bucket": city_bucket,
        "city_cause": city_cause,
        "driver_unprod": driver_unprod,
        "cause_unprod_time": cause_unprod_time,
    }


def _week_bucket(date_str: Optional[str]) -> str:
    try:
        ref = datetime.strptime(str(date_str or ""), "%Y-%m-%d").date()
        iso = ref.isocalendar()
        return f"{iso.year}-S{iso.week:02d}"
    except Exception:
        return "Sem semana"


def _parse_hhmm_minutes(value: Optional[str]) -> Optional[int]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        hh, mm = raw[:5].split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return None


def _parse_client_window_range(window: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    raw = str(window or "").strip()
    if not raw or raw.lower().startswith("sem janela"):
        return (None, None)
    parts = raw.split(" - ", 1) if " - " in raw else raw.split("-", 1)
    if len(parts) != 2:
        return (None, None)
    return (_parse_hhmm_minutes(parts[0]), _parse_hhmm_minutes(parts[1]))


def _time_is_within_window(value: Optional[str], start_m: Optional[int], end_m: Optional[int]) -> Optional[bool]:
    visit_m = _parse_hhmm_minutes(value)
    if visit_m is None or start_m is None or end_m is None:
        return None
    if end_m >= start_m:
        return start_m <= visit_m <= end_m
    return visit_m >= start_m or visit_m <= end_m


def _aggregate_bi_client_rows(rows: list[dict], financial_rows: Optional[list[dict]] = None) -> dict[str, dict]:
    client_agg: dict[str, dict] = {}

    for row in rows:
        row_client_id = row.get("client_id")
        row_client_name = str(row.get("client_name") or "").strip() or "Sem Cliente"
        key = f"id:{row_client_id}" if row_client_id is not None else f"name:{row_client_name.lower()}"
        source = str(row.get("source") or "ROTA").strip().upper()
        status_row = _norm_text(row.get("status"))
        duration_m = row.get("duration_m")
        duration_value = float(duration_m or 0.0) if duration_m is not None else 0.0
        planned_value = float(row.get("planned_value") or 0.0)
        delivered_value = float(row.get("delivered_value") or 0.0)
        returned_value = float(row.get("returned_value") or 0.0)
        returned_kg = float(row.get("returned_kg") or 0.0)
        reopen_count = int(row.get("reopen_count") or 0)
        driver_name = str(row.get("driver_name") or "-").strip() or "-"
        motivo = str(row.get("motivo") or "Não informado").strip() or "Não informado"
        responsabilidade = str(row.get("responsabilidade") or "Não informado").strip() or "Não informado"
        week_key = _week_bucket(row.get("date"))
        window_label = str(row.get("client_window") or "").strip() or "Sem janela"
        visit_time = str(row.get("visit_time") or "").strip()

        bucket = client_agg.setdefault(
            key,
            {
                "client_id": row_client_id,
                "client_key": key,
                "client_name": row_client_name,
                "city": str(row.get("client_city") or "").strip() or "Sem cidade",
                "bairro": str(row.get("client_bairro") or "").strip() or "Sem bairro",
                "segmento": str(row.get("client_segmento") or "").strip() or "Sem segmento",
                "prioridade": str(row.get("client_prioridade") or "").strip().upper() or "Sem prioridade",
                "status_operacional": str(row.get("client_status_operacional") or "").strip() or "Sem status",
                "status_cadastro": str(row.get("client_status_cadastro") or "").strip() or "Sem cadastro",
                "address": str(row.get("client_address") or "").strip() or "Endereço não informado",
                "window": window_label,
                "visits": 0,
                "delivered_visits": 0,
                "open_visits": 0,
                "returned_occurrences": 0,
                "planned_value": 0.0,
                "delivered_value": 0.0,
                "returned_value": 0.0,
                "returned_kg": 0.0,
                "manual_returned_value": 0.0,
                "total_duration_m": 0.0,
                "duration_count": 0,
                "reopen_count": 0,
                "window_checks": 0,
                "window_hits": 0,
                "window_misses": 0,
                "weeks": {},
                "drivers": {},
                "motivos": {},
                "responsabilidades": {},
                "latest_date": str(row.get("date") or ""),
            },
        )

        if str(row.get("date") or "") > bucket["latest_date"]:
            bucket["latest_date"] = str(row.get("date") or "")

        if source == "ROTA":
            bucket["visits"] += 1
            bucket["planned_value"] += planned_value
            bucket["delivered_value"] += delivered_value
            bucket["weeks"][week_key] = bucket["weeks"].get(week_key, 0) + 1

        driver_bucket = bucket["drivers"].setdefault(
            driver_name,
            {"visits": 0, "duration_m": 0.0, "returned_value": 0.0, "returns": 0},
        )
        if source == "ROTA":
            driver_bucket["visits"] += 1
        if duration_m is not None:
            bucket["total_duration_m"] += duration_value
            bucket["duration_count"] += 1
            driver_bucket["duration_m"] += duration_value
        if reopen_count:
            bucket["reopen_count"] += reopen_count

        if source == "ROTA" and visit_time:
            window_start_m, window_end_m = _parse_client_window_range(bucket["window"])
            window_match = _time_is_within_window(visit_time, window_start_m, window_end_m)
            if window_match is not None:
                bucket["window_checks"] += 1
                if window_match:
                    bucket["window_hits"] += 1
                else:
                    bucket["window_misses"] += 1

        if status_row == "entregue":
            bucket["delivered_visits"] += 1
        elif status_row in {"pendente", "iniciada", "reaberta", "cancelada"}:
            bucket["open_visits"] += 1

        if financial_rows is None and status_row == "devolucao":
            bucket["returned_occurrences"] += 1
            bucket["returned_value"] += returned_value
            bucket["returned_kg"] += returned_kg
            driver_bucket["returned_value"] += returned_value
            driver_bucket["returns"] += 1
            motivo_bucket = bucket["motivos"].setdefault(motivo, {"count": 0, "value": 0.0})
            motivo_bucket["count"] += 1
            motivo_bucket["value"] += returned_value
            resp_bucket = bucket["responsabilidades"].setdefault(responsabilidade, {"count": 0, "value": 0.0})
            resp_bucket["count"] += 1
            resp_bucket["value"] += returned_value

    if financial_rows is not None:
        for row in financial_rows:
            row_client_id = row.get("client_id")
            row_client_name = str(row.get("client_name") or "").strip() or "Sem Cliente"
            key = f"id:{row_client_id}" if row_client_id is not None else f"name:{row_client_name.lower()}"
            driver_name = str(row.get("driver_name") or "-").strip() or "-"
            motivo = str(row.get("motivo") or "Não informado").strip() or "Não informado"
            responsabilidade = str(row.get("responsabilidade") or "Não informado").strip() or "Não informado"
            returned_value = float(row.get("value") or row.get("returned_value") or 0.0)
            bucket = client_agg.setdefault(
                key,
                {
                    "client_id": row_client_id,
                    "client_key": key,
                    "client_name": row_client_name,
                    "city": str(row.get("client_city") or "").strip() or "Sem cidade",
                    "bairro": str(row.get("client_bairro") or "").strip() or "Sem bairro",
                    "segmento": str(row.get("client_segmento") or "").strip() or "Sem segmento",
                    "prioridade": str(row.get("client_prioridade") or "").strip().upper() or "Sem prioridade",
                    "status_operacional": str(row.get("client_status_operacional") or "").strip() or "Sem status",
                    "status_cadastro": str(row.get("client_status_cadastro") or "").strip() or "Sem cadastro",
                    "address": str(row.get("client_address") or "").strip() or "Endereço não informado",
                    "window": str(row.get("client_window") or "").strip() or "Sem janela",
                    "visits": 0,
                    "delivered_visits": 0,
                    "open_visits": 0,
                    "returned_occurrences": 0,
                    "planned_value": 0.0,
                    "delivered_value": 0.0,
                    "returned_value": 0.0,
                    "returned_kg": 0.0,
                    "manual_returned_value": 0.0,
                    "total_duration_m": 0.0,
                    "duration_count": 0,
                    "reopen_count": 0,
                    "window_checks": 0,
                    "window_hits": 0,
                    "window_misses": 0,
                    "weeks": {},
                    "drivers": {},
                    "motivos": {},
                    "responsabilidades": {},
                    "latest_date": str(row.get("date") or ""),
                },
            )
            if str(row.get("date") or "") > bucket["latest_date"]:
                bucket["latest_date"] = str(row.get("date") or "")
            if row.get("standalone"):
                bucket["manual_returned_value"] += returned_value
            bucket["returned_occurrences"] += 1
            bucket["returned_value"] += returned_value
            driver_bucket = bucket["drivers"].setdefault(
                driver_name,
                {"visits": 0, "duration_m": 0.0, "returned_value": 0.0, "returns": 0},
            )
            driver_bucket["returned_value"] += returned_value
            driver_bucket["returns"] += 1
            motivo_bucket = bucket["motivos"].setdefault(motivo, {"count": 0, "value": 0.0})
            motivo_bucket["count"] += 1
            motivo_bucket["value"] += returned_value
            resp_bucket = bucket["responsabilidades"].setdefault(responsabilidade, {"count": 0, "value": 0.0})
            resp_bucket["count"] += 1
            resp_bucket["value"] += returned_value

    return client_agg


def _ma(vals: list[float], w: int) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for i in range(len(vals)):
        chunk = vals[max(0, i - w + 1): i + 1]
        out.append(round(sum(chunk) / len(chunk), 2) if chunk else None)
    return out


def _get_fleet_plates(session: Session) -> set[str]:
    """Retorna placas ativas da frota (Vehicle). Em caso de erro, retorna set vazio."""
    try:
        rows = session.exec(
            select(models.Vehicle.placa).where(models.Vehicle.is_active == True)
        ).all()
        return {str(p).strip().upper() for p in (rows or []) if p and str(p).strip()}
    except Exception:
        return set()


def _load_financial_devolucao_rows(
    session: Session,
    date_i: date,
    date_f: date,
    shift: str,
    driver_id: Optional[int],
    plate: str,
    status: str,
) -> tuple[list[dict], set[int]]:
    """Base financeira do BI.

    Regra de fechamento:
    - até a última data coberta pelo Excel no recorte, Excel é a fonte oficial;
    - depois disso, usa a base consolidada do sistema sem duplicatas.

    Retorna também os route_id já cobertos por linhas Devolucao em ``selected`` (evita duplicar valor com a rota).
    """
    st = (status or "Todos").strip().lower()
    if st not in ("todos", "devolucao"):
        return [], set()

    pl = (plate or "Todos").strip().upper()
    lookback_start = date_i - timedelta(days=7)
    q = (
        select(models.Devolucao)
        .where(models.Devolucao.data_romaneio >= lookback_start.strftime("%Y-%m-%d"))
        .where(models.Devolucao.data_romaneio <= date_f.strftime("%Y-%m-%d"))
    )
    if driver_id:
        q = q.where(models.Devolucao.motorista_id == driver_id)
    devolucoes = session.exec(q.order_by(models.Devolucao.data_romaneio, models.Devolucao.created_at)).all()
    if not devolucoes:
        return [], set()

    route_ids = sorted({int(d.route_id) for d in devolucoes if d.route_id is not None})
    route_map = {
        r.id: r
        for r in (
            session.exec(select(models.Route).where(models.Route.id.in_(route_ids))).all()
            if route_ids else []
        )
    }

    filtered: list[models.Devolucao] = []
    for d in devolucoes:
        comp_date = competence_date_str(str(d.data_entrega or d.data_romaneio or ""))
        if comp_date:
            if not (date_i.strftime("%Y-%m-%d") <= comp_date <= date_f.strftime("%Y-%m-%d")):
                continue
        route = route_map.get(d.route_id) if d.route_id is not None else None
        if shift and shift != "Todos" and route is not None and (route.shift or "").strip() != shift:
            continue
        if pl and pl != "TODOS":
            route_plate = ((route.delivery_vehicle_plate or "").strip().upper() if route else "")
            if not route_plate or route_plate != pl:
                continue
        filtered.append(d)
    if not filtered:
        return [], set()

    def _effective_date(dev: models.Devolucao) -> str:
        return competence_date_str(str(dev.data_entrega or dev.data_romaneio or "").strip()) or str(dev.data_romaneio or "").strip()

    excel_cutoff = max(
        (_effective_date(d) for d in filtered if str(d.source or "").strip().upper() == "EXCEL" and _effective_date(d)),
        default=None,
    )
    if excel_cutoff:
        selected = []
        for d in filtered:
            eff_date = _effective_date(d)
            source = str(d.source or "").strip().upper()
            if eff_date and eff_date <= excel_cutoff:
                if source == "EXCEL":
                    selected.append(d)
            elif d.duplicate_of_id is None:
                selected.append(d)
    else:
        selected = [d for d in filtered if d.duplicate_of_id is None]
    if not selected:
        return [], set()

    emp_ids = sorted({int(d.motorista_id) for d in selected if d.motorista_id})
    cli_ids = sorted({int(d.client_id) for d in selected if d.client_id})
    mot_ids = sorted({int(d.motivo_id) for d in selected if d.motivo_id})
    rsp_ids = sorted({int(d.responsabilidade_id) for d in selected if d.responsabilidade_id})

    emp_map = {
        e.id: e
        for e in (
            session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all()
            if emp_ids else []
        )
    }
    cli_map = {
        c.id: c
        for c in (
            session.exec(select(models.Client).where(models.Client.id.in_(cli_ids))).all()
            if cli_ids else []
        )
    }
    mot_map = {
        m.id: m
        for m in (
            session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.id.in_(mot_ids))).all()
            if mot_ids else []
        )
    }
    rsp_map = {
        r.id: r
        for r in (
            session.exec(select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.id.in_(rsp_ids))).all()
            if rsp_ids else []
        )
    }

    rows: list[dict] = []
    for d in selected:
        route = route_map.get(d.route_id) if d.route_id is not None else None
        cli = cli_map.get(d.client_id)
        emp = emp_map.get(d.motorista_id)
        val = round(float(d.valor or 0.0), 2)
        client_window = ""
        if cli and getattr(cli, "janela_horario_inicio", None) and getattr(cli, "janela_horario_fim", None):
            client_window = f"{cli.janela_horario_inicio} - {cli.janela_horario_fim}"
        rows.append(
            {
                "devolucao_id": d.id,
                "route_id": d.route_id,
                "date": d.data_romaneio,
                "delivery_date": d.data_entrega,
                "driver_id": d.motorista_id,
                "driver_name": (emp.name if emp else f"Motorista #{d.motorista_id}"),
                "client_id": d.client_id,
                "client_name": (cli.name if cli else f"Cliente #{d.client_id}"),
                "client_city": (getattr(cli, "municipio", None) or "").strip() if cli else "",
                "client_bairro": (getattr(cli, "bairro", None) or "").strip() if cli else "",
                "client_segmento": (getattr(cli, "segmento", None) or "").strip() if cli else "",
                "client_prioridade": (getattr(cli, "prioridade_logistica", None) or "").strip() if cli else "",
                "client_status_operacional": (getattr(cli, "status_operacional", None) or "").strip() if cli else "",
                "client_status_cadastro": (getattr(cli, "status_cliente", None) or "").strip() if cli else "",
                "client_address": (cli.get_full_address() or cli.endereco or "").strip() if cli else "",
                "client_window": client_window,
                "shift": (route.shift or "-") if route else "-",
                "plate": ((route.delivery_vehicle_plate or "-").strip().upper() if route else "-"),
                "value": val,
                "returned_value": val,
                "motivo": (mot_map.get(d.motivo_id).nome if mot_map.get(d.motivo_id) else "Nao informado"),
                "responsabilidade": (rsp_map.get(d.responsabilidade_id).nome if rsp_map.get(d.responsabilidade_id) else "Nao informado"),
                "cluster": d.cluster or "Sem Cluster",
                "source": (d.source or "MANUAL").strip().upper(),
                "standalone": d.route_id is None,
                "acima_300": "SIM" if (str(d.acima_300 or "").upper() == "SIM" or val >= 300) else "NAO",
            }
        )
    covered_route_ids = {int(d.route_id) for d in selected if d.route_id is not None}
    return rows, covered_route_ids


def _financial_gap_rows_from_routes(
    routes: list,
    covered_route_ids: set[int],
    emp_map: dict,
    cli_map: dict,
) -> list[dict]:
    """Rotas com devolução operacional sem registro Devolucao na consolidação financeira (completa valor e gráficos)."""
    gap: list[dict] = []
    for r in routes:
        status_raw = (r.delivery_status or "pendente").strip().lower()
        if status_raw == "devolucao" and (r.delivery_return_reason or "").strip().upper() == "ENCERRAMENTO TARDIO AUTOMATICO":
            status_raw = "entregue"
        if status_raw != "devolucao":
            continue
        rid = int(r.id) if r.id is not None else None
        if rid is not None and rid in covered_route_ids:
            continue
        emp = emp_map.get(r.employee_id)
        cli = cli_map.get(r.client_id)
        driver_name = emp.name if emp else f"Motorista #{r.employee_id}"
        client_name = cli.name if cli else f"Cliente #{r.client_id}"
        planned_v = float(r.valor_financeiro or 0.0)
        ret_v = float(r.valor_devolucao if r.valor_devolucao is not None else (planned_v if status_raw == "devolucao" else 0.0))
        val = round(ret_v, 2)
        motivo = (r.delivery_return_reason or "Nao informado").strip() or "Nao informado"
        resp = (r.delivery_return_category or "Nao informado").strip() or "Nao informado"
        client_window = ""
        if cli and getattr(cli, "janela_horario_inicio", None) and getattr(cli, "janela_horario_fim", None):
            client_window = f"{cli.janela_horario_inicio} - {cli.janela_horario_fim}"
        gap.append(
            {
                "devolucao_id": None,
                "route_id": r.id,
                "date": r.date,
                "delivery_date": r.date,
                "driver_id": r.employee_id,
                "driver_name": driver_name,
                "client_id": r.client_id,
                "client_name": client_name,
                "client_city": (getattr(cli, "municipio", None) or "").strip() if cli else "",
                "client_bairro": (getattr(cli, "bairro", None) or "").strip() if cli else "",
                "client_segmento": (getattr(cli, "segmento", None) or "").strip() if cli else "",
                "client_prioridade": (getattr(cli, "prioridade_logistica", None) or "").strip() if cli else "",
                "client_status_operacional": (getattr(cli, "status_operacional", None) or "").strip() if cli else "",
                "client_status_cadastro": (getattr(cli, "status_cliente", None) or "").strip() if cli else "",
                "client_address": (cli.get_full_address() or cli.endereco or "").strip() if cli else "",
                "client_window": client_window,
                "shift": (r.shift or "-").strip() if r.shift else "-",
                "plate": ((r.delivery_vehicle_plate or "-").strip().upper() if r.delivery_vehicle_plate else "-"),
                "value": val,
                "returned_value": val,
                "motivo": motivo,
                "responsabilidade": resp,
                "cluster": "Sem Cluster",
                "source": "ROTA",
                "standalone": False,
                "acima_300": "SIM" if val >= 300 else "NAO",
            }
        )
    return gap


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
    period_start, period_end, window_start, window_end = _competence_period_window(date_i, date_f)

    st = (status or "Todos").strip().lower()
    pl = (plate or "Todos").strip().upper()
    detail_status_norm = (detail_status or "Todos").strip().lower()

    q = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= window_start)
        .where(models.Route.date <= window_end)
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
    routes = [r for r in routes if _in_competence_period(getattr(r, "date", None), period_start, period_end)]

    # % devolução operacional oficial (rotas concluídas): ignora filtro de status — mesmo critério Central / informativo
    q_rotas_kpi = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= window_start)
        .where(models.Route.date <= window_end)
    )
    if shift and shift != "Todos":
        q_rotas_kpi = q_rotas_kpi.where(models.Route.shift == shift)
    if driver_id:
        q_rotas_kpi = q_rotas_kpi.where(models.Route.employee_id == driver_id)
    if pl and pl != "TODOS":
        q_rotas_kpi = q_rotas_kpi.where(models.Route.delivery_vehicle_plate == pl)
    routes_for_kpi_rotas = session.exec(q_rotas_kpi.order_by(models.Route.date, models.Route.created_at)).all()
    routes_for_kpi_rotas = [
        r for r in routes_for_kpi_rotas
        if _in_competence_period(getattr(r, "date", None), period_start, period_end)
    ]
    rotas_devolucao_count, rotas_concluidas_count = counts_devolucao_rotas_concluidas(routes_for_kpi_rotas)
    return_rate_rotas = pct_devolucao_sobre_rotas_concluidas(routes_for_kpi_rotas)

    manual = []
    if (st in ("todos", "devolucao")) and pl == "TODOS":
        qm = (
            select(models.Devolucao)
            .where(models.Devolucao.data_romaneio >= window_start)
            .where(models.Devolucao.data_romaneio <= window_end)
            .where(models.Devolucao.route_id.is_(None))
        )
        if driver_id:
            qm = qm.where(models.Devolucao.motorista_id == driver_id)
        manual = session.exec(qm.order_by(models.Devolucao.data_romaneio, models.Devolucao.created_at)).all()
        manual = [
            d for d in manual
            if _in_competence_period(
                getattr(d, "data_entrega", None) or getattr(d, "data_romaneio", None),
                period_start,
                period_end,
            )
        ]

    emp_ids = sorted({r.employee_id for r in routes if r.employee_id} | {d.motorista_id for d in manual if d.motorista_id})
    cli_ids = sorted({r.client_id for r in routes if r.client_id} | {d.client_id for d in manual if d.client_id})
    emp_map = {e.id: e for e in (session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all() if emp_ids else [])}
    cli_map = {c.id: c for c in (session.exec(select(models.Client).where(models.Client.id.in_(cli_ids))).all() if cli_ids else [])}
    mot_map, rsp_map = _get_cached_mot_rsp_maps(session)

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

    def _fallback_route_time(value: Optional[str]) -> Optional[str]:
        raw = str(value or "").strip()
        if not raw or raw in {"00:00", "0:00"}:
            return None
        return raw

    def _pct(numerator: float, denominator: float) -> float:
        """Percentual seguro sem divisor artificial."""
        den = float(denominator or 0.0)
        if den <= 0:
            return 0.0
        return (float(numerator or 0.0) / den) * 100.0

    planned_stops = len(routes)
    planned_kg = planned_value = 0.0
    realized_stops = started_stops = 0
    realized_kg = realized_value = 0.0
    returned_stops = 0
    returned_kg = returned_value = 0.0
    returned_value_manual = 0.0
    reopen_routes = 0
    dur_list: list[int] = []

    per_day: dict[str, dict] = {}
    per_driver: dict[str, dict] = {}
    motivo_agg: dict[str, dict] = {}
    resp_agg: dict[str, dict] = {}
    cluster_agg: dict[str, dict] = {}
    ret_count_day: dict[str, int] = {}
    ret_value_day: dict[str, float] = {}
    client_returns: dict[str, dict] = {}
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
        cr = client_returns.setdefault(client_name, {"qtd": 0, "valor": 0.0})
        cr["qtd"] += 1
        cr["valor"] += val

    for r in routes:
        comp_date = _competence_date_or_self(getattr(r, "date", None)) or str(getattr(r, "date", "") or "")
        status_raw = (r.delivery_status or "pendente").strip().lower()
        # Legacy: encerramento automático foi marcado como devolução por engano → tratar como entregue
        if status_raw == "devolucao" and (r.delivery_return_reason or "").strip().upper() == "ENCERRAMENTO TARDIO AUTOMATICO":
            status_raw = "entregue"
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
        # Só contabiliza tempo com registro mobile (GPS início + fim); web não mede duração.
        dur = route_duration_minutes_mobile_only(r)
        start_ref = (r.delivery_started_at or "").strip() or _fallback_route_time(r.start_time)
        end_ref = (r.delivery_finished_at or "").strip() or _fallback_route_time(r.end_time)

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
            _acc_devol(comp_date, driver, client, (r.delivery_return_reason or "Nao informado"), (r.delivery_return_category or "Nao informado"), "Sem Cluster", ret_v)
        if (r.delivery_reopen_count or 0) > 0:
            reopen_routes += 1
            reopen_heat.setdefault(comp_date, {})
            reopen_heat[comp_date][driver] = reopen_heat[comp_date].get(driver, 0) + int(r.delivery_reopen_count or 0)

        per_day.setdefault(comp_date, {"date": comp_date, "planned_stops": 0, "started_stops": 0, "realized_stops": 0, "returned_stops": 0, "planned_kg": 0.0, "realized_kg": 0.0, "returned_kg": 0.0, "planned_value": 0.0, "returned_value": 0.0})
        d = per_day[comp_date]
        d["planned_stops"] += 1
        d["planned_kg"] += planned_w
        d["planned_value"] += planned_v
        if status_raw in ("iniciada", "devolucao", "entregue"):
            d["started_stops"] += 1
        if status_raw in ("devolucao", "entregue"):
            d["realized_stops"] += 1
            d["realized_kg"] = round(float(d.get("realized_kg") or 0.0) + del_w, 4)
        if status_raw == "devolucao":
            d["returned_stops"] += 1
            d["returned_kg"] += ret_w
            d["returned_value"] += ret_v

        per_driver.setdefault(driver, {"driver_name": driver, "driver_id": r.employee_id, "planned_stops": 0, "realized_stops": 0, "started_stops": 0, "returned_stops": 0, "planned_kg": 0.0, "realized_kg": 0.0, "returned_kg": 0.0, "planned_value": 0.0, "realized_value": 0.0, "returned_value": 0.0, "manual_returned_value": 0.0, "reopen_count": 0, "durations": [], "main_plate": (r.delivery_vehicle_plate or "-").upper()})
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

        client_city = (getattr(cli, "municipio", None) or r.delivery_city or "").strip() if cli or r.delivery_city else ""
        client_bairro = (getattr(cli, "bairro", None) or r.delivery_neighborhood or "").strip() if cli or r.delivery_neighborhood else ""
        client_segmento = (getattr(cli, "segmento", None) or "").strip() if cli else ""
        client_prioridade = (getattr(cli, "prioridade_logistica", None) or "").strip() if cli else ""
        client_status_operacional = (getattr(cli, "status_operacional", None) or "").strip() if cli else ""
        client_status_cadastro = (getattr(cli, "status_cliente", None) or "").strip() if cli else ""
        client_address = ""
        if cli:
            client_address = (cli.get_full_address() or cli.endereco or "").strip()
        if not client_address:
            client_address = (r.delivery_address or "").strip()
        client_window = ""
        if cli and getattr(cli, "janela_horario_inicio", None) and getattr(cli, "janela_horario_fim", None):
            client_window = f"{cli.janela_horario_inicio} - {cli.janela_horario_fim}"
        row = {"route_id": r.id, "date": comp_date, "shift": r.shift, "driver_id": r.employee_id, "driver_name": driver, "client_id": r.client_id, "client_name": client, "client_city": client_city, "client_bairro": client_bairro, "client_segmento": client_segmento, "client_prioridade": client_prioridade, "client_status_operacional": client_status_operacional, "client_status_cadastro": client_status_cadastro, "client_address": client_address, "client_window": client_window, "visit_time": (start_ref or ""), "status": status_raw, "planned_kg": round(planned_w, 2), "planned_value": round(planned_v, 2), "delivered_kg": round(del_w, 2), "delivered_value": round(del_v, 2), "returned_kg": round(ret_w if status_raw == "devolucao" else 0.0, 2), "returned_value": round(ret_v if status_raw == "devolucao" else 0.0, 2), "reopen_count": r.delivery_reopen_count or 0, "duration_m": dur, "plate": (r.delivery_vehicle_plate or "-").upper(), "order_number": r.delivery_order_number or "-", "motivo": r.delivery_return_reason or "-", "responsabilidade": r.delivery_return_category or "-", "cluster": "Sem Cluster", "acima_300": ("SIM" if ret_v >= 300 and status_raw == "devolucao" else "NAO"), "source": "ROTA", "possible_duplicate": False}
        route_rows.append(row)
        score = (55 if status_raw == "devolucao" else 20 if status_raw == "iniciada" else 25 if status_raw in ("pendente", "reaberta") else 0) + min(20, (r.delivery_reopen_count or 0) * 6) + (10 if (dur or 0) > 120 else 0) + (8 if planned_w >= 500 else 0)
        if score >= 30:
            ex_rows.append({"score": score, "date": comp_date, "shift": r.shift, "driver_name": driver, "driver_id": r.employee_id, "client_name": client, "status": status_raw, "planned_kg": round(planned_w, 2), "planned_value": round(planned_v, 2), "returned_kg": round(ret_w if status_raw == "devolucao" else 0.0, 2), "returned_value": round(ret_v if status_raw == "devolucao" else 0.0, 2), "reopen_count": r.delivery_reopen_count or 0, "duration_m": dur, "source": "ROTA"})

    rota_devol_keys_for_dup: set[tuple] = {
        (r["date"], r["client_id"], r["driver_id"], round(float(r.get("returned_value") or 0), 2))
        for r in route_rows
        if (r.get("status") or "").lower() == "devolucao"
    }
    for d in manual:
        # Ignora Devolucao vinculada a rota: já está representada na linha ROTA (não é manual)
        if d.route_id is not None:
            continue
        driver = (emp_map.get(d.motorista_id).name if emp_map.get(d.motorista_id) else f"Motorista #{d.motorista_id}")
        client = (cli_map.get(d.client_id).name if cli_map.get(d.client_id) else f"Cliente #{d.client_id}")
        motivo = (mot_map.get(d.motivo_id).nome if mot_map.get(d.motivo_id) else "Nao informado")
        resp = (rsp_map.get(d.responsabilidade_id).nome if rsp_map.get(d.responsabilidade_id) else "Nao informado")
        cluster = d.cluster or "Sem Cluster"
        ret_v = float(d.valor or 0.0)
        above = "SIM" if (d.acima_300 or "").upper() == "SIM" or ret_v >= 300 else "NAO"
        dup_key = (d.data_romaneio, d.client_id, d.motorista_id, round(ret_v, 2))
        is_possible_dup = dup_key in rota_devol_keys_for_dup
        if not is_possible_dup:
            _acc_devol(d.data_romaneio, driver, client, motivo, resp, cluster, ret_v)
            returned_value_manual += ret_v
            per_driver.setdefault(driver, {"driver_name": driver, "driver_id": d.motorista_id, "planned_stops": 0, "realized_stops": 0, "started_stops": 0, "returned_stops": 0, "planned_kg": 0.0, "realized_kg": 0.0, "returned_kg": 0.0, "planned_value": 0.0, "realized_value": 0.0, "returned_value": 0.0, "manual_returned_value": 0.0, "reopen_count": 0, "durations": [], "main_plate": "-"})
            per_driver[driver]["returned_stops"] += 1
            per_driver[driver]["returned_value"] += ret_v
            per_driver[driver]["manual_returned_value"] += ret_v
        route_rows.append({"route_id": -d.id, "date": d.data_romaneio, "shift": "-", "driver_id": d.motorista_id, "driver_name": driver, "client_id": d.client_id, "client_name": client, "client_city": (getattr(cli_map.get(d.client_id), "municipio", None) or "").strip() if cli_map.get(d.client_id) else "", "client_bairro": (getattr(cli_map.get(d.client_id), "bairro", None) or "").strip() if cli_map.get(d.client_id) else "", "client_segmento": (getattr(cli_map.get(d.client_id), "segmento", None) or "").strip() if cli_map.get(d.client_id) else "", "client_prioridade": (getattr(cli_map.get(d.client_id), "prioridade_logistica", None) or "").strip() if cli_map.get(d.client_id) else "", "client_status_operacional": (getattr(cli_map.get(d.client_id), "status_operacional", None) or "").strip() if cli_map.get(d.client_id) else "", "client_status_cadastro": (getattr(cli_map.get(d.client_id), "status_cliente", None) or "").strip() if cli_map.get(d.client_id) else "", "client_address": (cli_map.get(d.client_id).get_full_address() or cli_map.get(d.client_id).endereco or "").strip() if cli_map.get(d.client_id) else "", "client_window": (f"{cli_map.get(d.client_id).janela_horario_inicio} - {cli_map.get(d.client_id).janela_horario_fim}" if cli_map.get(d.client_id) and getattr(cli_map.get(d.client_id), "janela_horario_inicio", None) and getattr(cli_map.get(d.client_id), "janela_horario_fim", None) else ""), "visit_time": "", "status": "devolucao", "planned_kg": 0.0, "planned_value": 0.0, "delivered_kg": 0.0, "delivered_value": 0.0, "returned_kg": 0.0, "returned_value": round(ret_v, 2), "reopen_count": 0, "duration_m": None, "plate": "-", "order_number": f"Man. {d.id}", "motivo": motivo, "responsabilidade": resp, "cluster": cluster, "acima_300": above, "source": "MANUAL", "possible_duplicate": is_possible_dup})
        if not is_possible_dup:
            ex_rows.append({"score": 55, "date": d.data_romaneio, "shift": "-", "driver_name": driver, "driver_id": d.motorista_id, "client_name": client, "status": "devolucao", "planned_kg": 0.0, "planned_value": 0.0, "returned_kg": 0.0, "returned_value": round(ret_v, 2), "reopen_count": 0, "duration_m": None, "source": "MANUAL"})

    financial_rows, covered_financial_route_ids = _load_financial_devolucao_rows(
        session=session,
        date_i=date_i,
        date_f=date_f,
        shift=shift,
        driver_id=driver_id,
        plate=plate,
        status=status,
    )
    gap_financial_rows: list[dict] = []
    if financial_rows:
        returned_value = 0.0
        returned_value_manual = 0.0
        ret_count_day = {}
        ret_value_day = {}
        client_returns = {}
        motivo_agg = {}
        resp_agg = {}
        cluster_agg = {}
        driver_return_value: dict[str, float] = {}
        driver_standalone_value: dict[str, float] = {}

        def _accumulate_financial_row(row: dict) -> None:
            nonlocal returned_value, returned_value_manual
            date_key = str(row.get("date") or "")
            driver_name = str(row.get("driver_name") or "-").strip() or "-"
            client_name = str(row.get("client_name") or "Sem cliente").strip() or "Sem cliente"
            motivo = str(row.get("motivo") or "Nao informado").strip() or "Nao informado"
            resp = str(row.get("responsabilidade") or "Nao informado").strip() or "Nao informado"
            cluster = str(row.get("cluster") or "Sem Cluster").strip() or "Sem Cluster"
            val = round(float(row.get("value") or row.get("returned_value") or 0.0), 2)
            returned_value += val
            if row.get("standalone"):
                returned_value_manual += val
                driver_standalone_value[driver_name] = round(driver_standalone_value.get(driver_name, 0.0) + val, 2)
            driver_return_value[driver_name] = round(driver_return_value.get(driver_name, 0.0) + val, 2)
            ret_count_day[date_key] = ret_count_day.get(date_key, 0) + 1
            ret_value_day[date_key] = round(ret_value_day.get(date_key, 0.0) + val, 2)
            motivo_agg.setdefault(motivo, {"motivo": motivo, "qtd": 0, "valor": 0.0})
            motivo_agg[motivo]["qtd"] += 1
            motivo_agg[motivo]["valor"] = round(motivo_agg[motivo]["valor"] + val, 2)
            resp_agg.setdefault(resp, {"responsabilidade": resp, "qtd": 0, "valor": 0.0})
            resp_agg[resp]["qtd"] += 1
            resp_agg[resp]["valor"] = round(resp_agg[resp]["valor"] + val, 2)
            cluster_agg.setdefault(cluster, {"cluster": cluster, "qtd": 0, "valor": 0.0})
            cluster_agg[cluster]["qtd"] += 1
            cluster_agg[cluster]["valor"] = round(cluster_agg[cluster]["valor"] + val, 2)
            cr = client_returns.setdefault(client_name, {"qtd": 0, "valor": 0.0})
            cr["qtd"] += 1
            cr["valor"] = round(cr["valor"] + val, 2)

        for row in financial_rows:
            _accumulate_financial_row(row)

        gap_financial_rows = _financial_gap_rows_from_routes(
            routes, covered_financial_route_ids, emp_map, cli_map
        )
        for row in gap_financial_rows:
            _accumulate_financial_row(row)

        for driver_name, driver_data in per_driver.items():
            driver_data["returned_value"] = round(driver_return_value.get(driver_name, 0.0), 2)
            driver_data["manual_returned_value"] = round(driver_standalone_value.get(driver_name, 0.0), 2)
        for daily in per_day.values():
            daily["returned_value"] = 0.0
        for date_key, val in ret_value_day.items():
            per_day.setdefault(
                date_key,
                {
                    "date": date_key,
                    "planned_stops": 0,
                    "started_stops": 0,
                    "realized_stops": 0,
                    "returned_stops": 0,
                    "planned_kg": 0.0,
                    "realized_kg": 0.0,
                    "returned_kg": 0.0,
                    "planned_value": 0.0,
                    "returned_value": 0.0,
                },
            )
            per_day[date_key]["returned_value"] = round(val, 2)

    financial_rows_all = (financial_rows + gap_financial_rows) if financial_rows else []

    avg_duration = statistics.mean(dur_list) if dur_list else 0.0
    global_return_rate = (returned_stops / max(1, planned_stops) * 100.0) if (planned_stops or manual) else 0.0
    tactical = []
    for row in per_driver.values():
        p = max(1, row["planned_stops"])
        value_base = (row["planned_value"] or 0.0) + (row.get("manual_returned_value") or 0.0)
        if value_base <= 0:
            value_base = (row["realized_value"] or 0.0) + (row["returned_value"] or 0.0)
        delivered_stops = max(0, row["realized_stops"] - row["returned_stops"])
        tactical.append({
            **row,
            "delivered_stops": delivered_stops,
            "efficiency": round(delivered_stops / p * 100.0, 2) if row["planned_stops"] else 0.0,
            "return_rate": round(row["returned_stops"] / p * 100.0, 2) if row["planned_stops"] else (100.0 if row["returned_stops"] > 0 else 0.0),
            "started_rate": round(row["started_stops"] / p * 100.0, 2) if row["planned_stops"] else 0.0,
            "avg_duration": round(statistics.mean(row["durations"]), 1) if row["durations"] else 0.0,
            "returned_value_pct": round(_pct(row["returned_value"], value_base), 2)
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
    financial_base_value = planned_value + returned_value_manual
    if financial_base_value <= 0:
        financial_base_value = realized_value + returned_value
    global_return_rate_value = _pct(returned_value, financial_base_value)

    if global_return_rate_value >= 2:
        anomaly_flags.append(f"Ponto de atencao financeiro: devolucao em valor em {_fmt_br_1(global_return_rate_value)}% (meta <= 2,0%).")
    if client_returns:
        rec_client = [(n, c) for n, c in sorted(client_returns.items(), key=lambda x: x[1]["qtd"], reverse=True) if c["qtd"] >= 2][:3]
        if rec_client:
            parts = []
            for nome, d in rec_client:
                pct_val = _pct(d["valor"], financial_base_value)
                parts.append(f"{nome} ({d['qtd']} devolucoes, {_fmt_br_1(pct_val)}% do valor)")
            anomaly_flags.append(f"Clientes com devolucao recorrente: {'; '.join(parts)}.")
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
        if (v.get("planned_value", 0.0) or 0.0) > 0 and _pct((v.get("returned_value", 0.0) or 0.0), (v.get("planned_value", 0.0) or 0.0)) >= 2
    ]
    if len(dias_acima_meta) >= 3:
        anomaly_flags.append(f"Serie de risco: {len(dias_acima_meta)} dia(s) com devolucao em valor acima de 2,0%.")

    # Detectar possíveis duplicatas ROTA + MANUAL (mesma data, cliente, motorista e valor)
    rota_devol_keys: set[tuple] = set()
    for r in route_rows:
        if (r.get("source") or "").upper() == "ROTA" and (r.get("status") or "").lower() == "devolucao":
            k = (r.get("date"), r.get("client_id"), r.get("driver_id"), round(float(r.get("returned_value") or 0), 2))
            rota_devol_keys.add(k)
    dup_count = 0
    for r in route_rows:
        if (r.get("source") or "").upper() != "MANUAL":
            continue
        k = (r.get("date"), r.get("client_id"), r.get("driver_id"), round(float(r.get("returned_value") or 0), 2))
        if k in rota_devol_keys:
            dup_count += 1
    if dup_count > 0:
        anomaly_flags.append(f"Possivel duplicata ROTA+MANUAL: {dup_count} devolucao(oes) com mesma data, cliente, motorista e valor. Revisar cadastro.")

    recommendations: list[str] = []
    if dup_count > 0:
        recommendations.append("Revisar devolucoes manuais que coincidem com rotas ja marcadas como devolucao (evitar contagem dupla no BI).")
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
    # Exclui "Não informado" / "Nao informado" dos gráficos (devem vir de dados mal preenchidos)
    _nao_inf = ("nao informado", "não informado")
    motivo_agg_ok = {k: v for k, v in motivo_agg.items() if (k or "").strip().lower() not in _nao_inf}
    resp_agg_ok = {k: v for k, v in resp_agg.items() if (k or "").strip().lower() not in _nao_inf}
    if motivo_agg_ok:
        top_motivo_val = max(motivo_agg_ok.values(), key=lambda x: x["valor"])
        recommendations.append(f"Estudo 80/20: atacar primeiro o motivo '{top_motivo_val['motivo']}' (R$ {_fmt_br_2(top_motivo_val['valor'])}).")
    if client_returns:
        top_cliente, top_d = max(client_returns.items(), key=lambda x: x[1]["qtd"])
        top_qtd = top_d["qtd"]
        if top_qtd >= 2:
            recommendations.append(f"Estudo de causa raiz com cliente {top_cliente}: {top_qtd} devolucoes no periodo.")
    if not recommendations:
        recommendations.append("Operacao estavel no periodo; manter monitoramento diario.")

    total_mot = sum(v["qtd"] for v in motivo_agg_ok.values()) or 1
    motivos_rows = sorted([{"motivo": v["motivo"], "qtd": int(v["qtd"]), "valor": round(v["valor"], 2), "pct": round(v["qtd"] / total_mot * 100.0, 2)} for v in motivo_agg_ok.values()], key=lambda x: (x["qtd"], x["valor"]), reverse=True)

    # Motivo x Motorista x Qtd x Valor x % valor real (para gráfico detalhado)
    financial_detail_rows = financial_rows_all if financial_rows_all else [
        {
            "date": r.get("date"),
            "driver_name": r.get("driver_name"),
            "client_name": r.get("client_name"),
            "returned_value": r.get("returned_value"),
            "motivo": r.get("motivo"),
            "responsabilidade": r.get("responsabilidade"),
        }
        for r in route_rows
        if r.get("status") == "devolucao" and (r.get("returned_value") or 0) > 0
    ]
    motivo_motorista: dict[str, dict[str, dict]] = {}
    for r in financial_detail_rows:
        motivo = (r.get("motivo") or "").strip() or "Nao informado"
        if motivo.upper() == "ENCERRAMENTO TARDIO AUTOMATICO" or motivo.lower() in _nao_inf:
            continue
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
    resp_rows = sorted([{"responsabilidade": v["responsabilidade"], "qtd": int(v["qtd"]), "valor": round(v["valor"], 2)} for v in resp_agg_ok.values()], key=lambda x: x["qtd"], reverse=True)
    cluster_rows = sorted([{"cluster": v["cluster"], "qtd": int(v["qtd"]), "valor": round(v["valor"], 2)} for v in cluster_agg.values()], key=lambda x: x["valor"], reverse=True)

    # Motorista x Responsabilidade x Valor: valor devolvido por motorista e responsabilidade, % devolução baseada em valor real
    driver_resp_value: dict[str, dict[str, float]] = {}
    for r in financial_detail_rows:
        motivo_raw = (r.get("motivo") or "").strip().upper()
        if motivo_raw == "ENCERRAMENTO TARDIO AUTOMATICO":
            continue
        drv = r.get("driver_name") or "-"
        resp = (r.get("responsabilidade") or "").strip() or "Nao informado"
        if resp.lower() in _nao_inf:
            continue
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
    for r in financial_detail_rows:
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
    for _ in trend_dates:
        trend_last_month_val.append(None)
    heat_rows = [{"date": dt, "driver": drv, "value": v} for dt, d in reopen_heat.items() for drv, v in d.items()]

    filters_payload = {"date_from": date_i.strftime("%Y-%m-%d"), "date_to": date_f.strftime("%Y-%m-%d"), "shift": shift, "driver_id": driver_id, "plate": plate, "status": status, "detail_driver_id": detail_driver_id, "detail_status": detail_status}
    filters_query = urlencode({"date_from": filters_payload["date_from"], "date_to": filters_payload["date_to"], "shift": filters_payload["shift"], "driver_id": filters_payload["driver_id"] or "", "plate": filters_payload["plate"], "status": filters_payload["status"]})
    # Exclui MANUAL duplicado: mesma devolução já registrada em ROTA (evita linha duplicada no drill-through)
    detail_rows = [
        r for r in route_rows
        if not (str(r.get("source") or "").upper() == "MANUAL" and r.get("possible_duplicate"))
    ]
    detail_rows = sorted(detail_rows, key=lambda x: (x["date"], x["shift"], x["driver_name"], x["route_id"]))
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
    prev_month_planned_val = round(sum(float(r.valor_financeiro or 0.0) for r in prev_routes), 2)
    prev_financial_rows, prev_covered_route_ids = _load_financial_devolucao_rows(
        session=session,
        date_i=prev_first,
        date_f=prev_last,
        shift=shift,
        driver_id=driver_id,
        plate=plate,
        status=status,
    )
    prev_emp_ids = sorted({r.employee_id for r in prev_routes if r.employee_id})
    prev_cli_ids = sorted({r.client_id for r in prev_routes if r.client_id})
    prev_emp_map = {
        e.id: e
        for e in (
            session.exec(select(models.Employee).where(models.Employee.id.in_(prev_emp_ids))).all()
            if prev_emp_ids
            else []
        )
    }
    prev_cli_map = {
        c.id: c
        for c in (
            session.exec(select(models.Client).where(models.Client.id.in_(prev_cli_ids))).all()
            if prev_cli_ids
            else []
        )
    }
    prev_gap_rows = _financial_gap_rows_from_routes(
        prev_routes, prev_covered_route_ids, prev_emp_map, prev_cli_map
    )
    prev_financial_rows_all = prev_financial_rows + prev_gap_rows
    prev_month_qtd = len(prev_financial_rows_all)
    prev_month_valor = round(
        sum(float(r.get("value") or r.get("returned_value") or 0.0) for r in prev_financial_rows_all), 2
    )
    prev_month_manual_valor = round(
        sum(float(r.get("value") or r.get("returned_value") or 0.0) for r in prev_financial_rows_all if r.get("standalone")),
        2,
    )
    prev_month_base = prev_month_planned_val + prev_month_manual_valor
    if prev_month_base <= 0:
        prev_month_base = prev_month_valor
    prev_month_pct = round(_pct(prev_month_valor, prev_month_base), 2)
    prev_ret_value_day: dict[str, float] = {}
    for row in prev_financial_rows_all:
        prev_key = str(row.get("date") or "")
        prev_ret_value_day[prev_key] = round(
            prev_ret_value_day.get(prev_key, 0.0) + float(row.get("value") or row.get("returned_value") or 0.0),
            2,
        )
    trend_last_month_val = []
    for k in trend_dates:
        pm = _prev_month_key(k)
        trend_last_month_val.append(round(prev_ret_value_day.get(pm, 0.0), 2) if pm else None)

    devolucoes_acima_300_count = len(
        [
            r for r in (financial_rows_all or [])
            if str(r.get("acima_300") or "").upper() == "SIM"
        ]
    ) if financial_rows_all else len([r for r in route_rows if r.get("acima_300") == "SIM"])

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
        "return_rate_rotas": return_rate_rotas,
        "rotas_devolucao_count": rotas_devolucao_count,
        "rotas_concluidas_count": rotas_concluidas_count,
        "return_rate_kg": round(returned_kg / max(1, planned_kg) * 100.0, 2) if planned_kg else 0.0,
        "return_rate_value": round(global_return_rate_value, 2),
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
        "devolucoes_acima_300_count": devolucoes_acima_300_count,
        "devolucoes_acima_300_pct": round((devolucoes_acima_300_count / max(1, len(financial_rows_all) or returned_stops)) * 100.0, 2) if (financial_rows_all or returned_stops) else 0.0,
        "risk_label": risk_label,
        "risk_severity": risk_severity,
        "meta_devolucao_pct": 2.0,
        "devolucao_mes_anterior_qtd": prev_month_qtd,
        "devolucao_mes_anterior_valor": round(prev_month_valor, 2),
        "devolucao_mes_anterior_pct": prev_month_pct,
    }

    delivery_daily_chart = [
        {
            "date": str(r.get("date") or ""),
            "planned_stops": int(r.get("planned_stops") or 0),
            "delivered_stops": max(0, int(r.get("realized_stops") or 0) - int(r.get("returned_stops") or 0)),
            "started_stops": int(r.get("started_stops") or 0),
            "planned_kg": round(float(r.get("planned_kg") or 0.0), 2),
            "realized_kg": round(float(r.get("realized_kg") or 0.0), 2),
        }
        for r in daily_rows
    ]

    chart_payload = {
        "delivery_daily": delivery_daily_chart,
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
        "fleet_plates": sorted(
            _get_fleet_plates(session)
        ),
        "statuses_filter": ["Todos", "Pendente", "Iniciada", "Entregue", "Devolucao", "Reaberta", "Cancelada"],
        "detail_rows": detail_rows[:300],
        "detail_title": "Drill-through operacional",
        "detail_total": len(detail_rows),
        "filters_query": filters_query,
        "all_route_rows": route_rows,
        "all_financial_rows": financial_rows_all,
        "motivos_rows": motivos_rows[:12],
        "responsabilidade_rows": resp_rows,
        "cluster_rows": cluster_rows,
        "chart_payload_json": json.dumps(chart_payload, ensure_ascii=False),
        "detail_rows_json": json.dumps(detail_rows, ensure_ascii=False),
    }


def _build_bi_clientes_dataset(
    session: Session,
    date_from: Optional[str],
    date_to: Optional[str],
    shift: str,
    driver_id: Optional[int],
    plate: str,
    status: str,
    client_id: Optional[int] = None,
    city: str = "Todos",
    priority: str = "Todos",
    client_status: str = "Todos",
    segmentos: Optional[list[str]] = None,
    returns_filter: str = "Todos",
    detail_client_id: Optional[int] = None,
    client_filter_scope: str = "solo",
) -> dict:
    tz = ZoneInfo("America/Sao_Paulo")
    today = datetime.now(tz).date()

    def _parse_d(raw: Optional[str]) -> Optional[date]:
        if not raw:
            return None
        try:
            return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
        except Exception:
            return None

    date_i = _parse_d(date_from) or today.replace(day=1)
    date_f = _parse_d(date_to) or today
    if date_i > date_f:
        date_i, date_f = date_f, date_i
    cur_s, cur_e = date_i.strftime("%Y-%m-%d"), date_f.strftime("%Y-%m-%d")
    current_days = max(1, (date_f - date_i).days + 1)
    previous_date_to = date_i - timedelta(days=1)
    previous_date_from = previous_date_to - timedelta(days=current_days - 1)
    prev_s = previous_date_from.strftime("%Y-%m-%d")
    prev_e = previous_date_to.strftime("%Y-%m-%d")

    # Uma única leitura de rotas + manuais (período atual + anterior contíguo) — evita 2ª ida ao Postgres.
    merged_dataset = _build_bi_delivery_dataset(
        session=session,
        date_from=prev_s,
        date_to=cur_e,
        shift=shift,
        driver_id=driver_id,
        plate=plate,
        status=status,
    )
    all_merged = list(merged_dataset.get("all_route_rows", []))
    all_financial = list(merged_dataset.get("all_financial_rows", []))
    base_rows = [r for r in all_merged if cur_s <= r["date"] <= cur_e]
    previous_rows_pool = [r for r in all_merged if prev_s <= r["date"] <= prev_e]
    base_financial_rows = [r for r in all_financial if cur_s <= r["date"] <= cur_e]
    previous_financial_rows_pool = [r for r in all_financial if prev_s <= r["date"] <= prev_e]

    _drivers_map: dict[int, str] = {}
    _plates_set: set = set()
    for r in base_rows:
        did = r.get("driver_id")
        if did is not None:
            _drivers_map[int(did)] = str(r.get("driver_name") or f"Motorista #{did}")
        pl = r.get("plate")
        if pl and str(pl).strip() not in ("", "-"):
            _plates_set.add(str(pl).strip().upper())
    delivery_dataset = {
        "filters": {**merged_dataset.get("filters", {}), "date_from": cur_s, "date_to": cur_e},
        "drivers_filter": sorted([{"id": i, "name": n} for i, n in _drivers_map.items()], key=lambda x: x["name"]),
        "plates_filter": sorted(_plates_set),
        "statuses_filter": merged_dataset.get("statuses_filter", []),
    }

    scope = (client_filter_scope or "solo").strip().lower()
    if scope not in ("solo", "group"):
        scope = "solo"
    client_ids_filter = None
    aggregate_group = None
    group_filter_note = None
    if client_id:
        if scope == "group":
            cobj = session.get(models.Client, int(client_id))
            gid = getattr(cobj, "client_group_id", None) if cobj else None
            if gid:
                mids = session.exec(select(models.Client.id).where(models.Client.client_group_id == gid)).all()
                client_ids_filter = {int(x) for x in mids if x is not None}
                if len(client_ids_filter) > 1:
                    cg = session.get(models.ClientGroup, gid)
                    aggregate_group = (int(gid), (cg.name if cg else f"Grupo #{gid}"))
            if not client_ids_filter:
                client_ids_filter = {int(client_id)}
            elif len(client_ids_filter) == 1:
                group_filter_note = "Apenas uma loja neste grupo; mesmo que filtrar só ela."
        else:
            client_ids_filter = {int(client_id)}

    selected_segmentos = [str(s or "").strip() for s in (segmentos or []) if str(s or "").strip()]
    segmento_norm_set = {_norm_text(s) for s in selected_segmentos if _norm_text(s) and _norm_text(s) != _norm_text("Todos")}
    city_norm = "" if (city or "Todos").strip() == "Todos" else _norm_text(city)
    priority_norm = "" if (priority or "Todos").strip() == "Todos" else str(priority or "").strip().upper()
    client_status_norm = "" if (client_status or "Todos").strip() == "Todos" else _norm_text(client_status)

    clients_filter_map: dict[int, str] = {}
    cities_filter = set()
    priorities_filter = set()
    client_statuses_filter = set()
    segmentos_filter = set()
    for row in base_rows:
        row_client_id = row.get("client_id")
        if row_client_id is not None:
            clients_filter_map[int(row_client_id)] = str(row.get("client_name") or f"Cliente #{row_client_id}")
        row_city = str(row.get("client_city") or "").strip()
        row_priority = str(row.get("client_prioridade") or "").strip().upper()
        row_client_status = str(row.get("client_status_operacional") or "").strip()
        row_segmento = str(row.get("client_segmento") or "").strip()
        if row_city:
            cities_filter.add(row_city)
        if row_priority:
            priorities_filter.add(row_priority)
        if row_client_status:
            client_statuses_filter.add(row_client_status)
        if row_segmento:
            segmentos_filter.add(row_segmento)

    def _apply_client_filters(rows: list[dict]) -> list[dict]:
        filtered = []
        for row in rows:
            row_client_id = row.get("client_id")
            row_city = _norm_text(row.get("client_city"))
            row_priority = str(row.get("client_prioridade") or "").strip().upper()
            row_client_status = _norm_text(row.get("client_status_operacional"))
            row_segmento = _norm_text(row.get("client_segmento"))
            if client_ids_filter is not None:
                if row_client_id is None or int(row_client_id) not in client_ids_filter:
                    continue
            if city_norm and row_city != city_norm:
                continue
            if priority_norm and row_priority != priority_norm:
                continue
            if client_status_norm and row_client_status != client_status_norm:
                continue
            if segmento_norm_set and row_segmento not in segmento_norm_set:
                continue
            filtered.append(row)
        return filtered

    filtered_rows = _apply_client_filters(base_rows)
    filtered_financial_rows = _apply_client_filters(base_financial_rows)

    detail_client_id = detail_client_id or client_id

    def _rows_for_group_aggregate(rows: list[dict]) -> list[dict]:
        if not aggregate_group or not client_ids_filter or len(client_ids_filter) <= 1:
            return rows
        gid, gname = aggregate_group
        synth_id = -int(gid)
        out = []
        for row in rows:
            cid = row.get("client_id")
            if cid is None or int(cid) not in client_ids_filter:
                continue
            r = dict(row)
            r["client_id"] = synth_id
            r["client_name"] = f"Grupo: {gname}"
            r["client_city"] = "—"
            r["client_bairro"] = "—"
            r["client_segmento"] = "—"
            r["client_prioridade"] = "—"
            r["client_status_operacional"] = "—"
            r["client_status_cadastro"] = "—"
            r["client_address"] = f"{len(client_ids_filter)} lojas"
            r["client_window"] = "—"
            out.append(r)
        return out

    rows_for_agg = _rows_for_group_aggregate(filtered_rows)

    def _risk_label(score: int) -> tuple[str, str]:
        if score >= 70:
            return ("Crítico", "danger")
        if score >= 40:
            return ("Atenção", "warning")
        return ("Controlado", "success")

    client_agg = _aggregate_bi_client_rows(rows_for_agg, _rows_for_group_aggregate(filtered_financial_rows))

    filters_base = delivery_dataset.get("filters", {})
    current_date_from = datetime.strptime(str(filters_base.get("date_from") or date_from), "%Y-%m-%d").date()
    current_date_to = datetime.strptime(str(filters_base.get("date_to") or date_to), "%Y-%m-%d").date()
    current_days = max(1, (current_date_to - current_date_from).days + 1)
    previous_date_to = current_date_from - timedelta(days=1)
    previous_date_from = previous_date_to - timedelta(days=current_days - 1)
    previous_label = f"{_fmt_br_data(previous_date_from.strftime('%Y-%m-%d'))} a {_fmt_br_data(previous_date_to.strftime('%Y-%m-%d'))}"
    current_label = f"{_fmt_br_data(current_date_from.strftime('%Y-%m-%d'))} a {_fmt_br_data(current_date_to.strftime('%Y-%m-%d'))}"

    previous_rows = _apply_client_filters(previous_rows_pool)
    previous_financial_rows = _apply_client_filters(previous_financial_rows_pool)
    previous_client_agg = _aggregate_bi_client_rows(
        _rows_for_group_aggregate(previous_rows),
        _rows_for_group_aggregate(previous_financial_rows),
    )

    _exec_gid = None
    _exec_mem = None
    if aggregate_group and client_ids_filter and len(client_ids_filter) > 1:
        _exec_gid = int(aggregate_group[0])
        _exec_mem = set(int(x) for x in client_ids_filter)
    exec_cur = _exec_accumulate_rows(filtered_rows, _exec_gid, _exec_mem, filtered_financial_rows)
    exec_prev = _exec_accumulate_rows(
        _apply_client_filters(previous_rows_pool),
        _exec_gid,
        _exec_mem,
        previous_financial_rows,
    )

    ranking_rows = []
    for item in client_agg.values():
        previous_item = previous_client_agg.get(item["client_key"], {})
        weekly_peak = max(item["weeks"].values()) if item["weeks"] else 0
        weekly_avg = round(statistics.mean(item["weeks"].values()), 2) if item["weeks"] else 0.0
        avg_duration_m = round(item["total_duration_m"] / item["duration_count"], 1) if item["duration_count"] else 0.0
        financial_base = item["planned_value"] + item["manual_returned_value"]
        if financial_base <= 0:
            financial_base = item["delivered_value"] + item["returned_value"]
        qty_den = item["visits"] if item["visits"] > 0 else item["returned_occurrences"]
        return_rate_qtd = round(_safe_pct(item["returned_occurrences"], qty_den), 2)
        return_rate_value = round(_safe_pct(item["returned_value"], financial_base if financial_base > 0 else item["returned_value"]), 2)

        prev_financial_base = float(previous_item.get("planned_value", 0.0) or 0.0) + float(previous_item.get("manual_returned_value", 0.0) or 0.0)
        if prev_financial_base <= 0:
            prev_financial_base = float(previous_item.get("delivered_value", 0.0) or 0.0) + float(previous_item.get("returned_value", 0.0) or 0.0)
        prev_visits = int(previous_item.get("visits", 0) or 0)
        prev_returns = int(previous_item.get("returned_occurrences", 0) or 0)
        prev_returned_value = round(float(previous_item.get("returned_value", 0.0) or 0.0), 2)
        has_previous_data = bool(prev_visits or prev_returns or prev_financial_base > 0 or prev_returned_value > 0)
        prev_qty_den = prev_visits if prev_visits > 0 else prev_returns
        prev_return_rate_qtd = round(_safe_pct(prev_returns, prev_qty_den), 2) if has_previous_data else 0.0
        prev_return_rate_value = round(_safe_pct(prev_returned_value, prev_financial_base if prev_financial_base > 0 else prev_returned_value), 2) if has_previous_data else 0.0
        delta_return_rate_value = round(return_rate_value - prev_return_rate_value, 2)
        delta_return_rate_qtd = round(return_rate_qtd - prev_return_rate_qtd, 2)
        delta_returned_value = round(float(item["returned_value"] or 0.0) - prev_returned_value, 2)

        top_driver_name = "-"
        top_driver_visits = 0
        top_driver_return_name = "-"
        top_driver_return_value = 0.0
        top_driver_return_share = 0.0
        if item["drivers"]:
            top_driver_name, top_driver_data = max(
                item["drivers"].items(),
                key=lambda kv: (kv[1].get("visits", 0), kv[1].get("returned_value", 0.0), kv[1].get("duration_m", 0.0)),
            )
            top_driver_visits = int(top_driver_data.get("visits", 0) or 0)
            if float(item["returned_value"] or 0.0) > 0:
                top_driver_return_name, top_driver_return_data = max(
                    item["drivers"].items(),
                    key=lambda kv: (kv[1].get("returned_value", 0.0), kv[1].get("returns", 0), kv[1].get("visits", 0)),
                )
                top_driver_return_value = round(float(top_driver_return_data.get("returned_value", 0.0) or 0.0), 2)
                top_driver_return_share = round(_safe_pct(top_driver_return_value, item["returned_value"]), 2)
            else:
                top_driver_return_name = top_driver_name
        top_motivo_name = "-"
        top_motivo_count = 0
        if item["motivos"]:
            top_motivo_name, top_motivo_data = max(
                item["motivos"].items(),
                key=lambda kv: (kv[1].get("value", 0.0), kv[1].get("count", 0)),
            )
            top_motivo_count = int(top_motivo_data.get("count", 0) or 0)
        top_resp_name = "-"
        top_resp_return_value = 0.0
        top_resp_return_share = 0.0
        if item["responsabilidades"]:
            top_resp_name, top_resp_data = max(
                item["responsabilidades"].items(),
                key=lambda kv: (kv[1].get("value", 0.0), kv[1].get("count", 0)),
            )
            if float(item["returned_value"] or 0.0) > 0:
                top_resp_return_value = round(float(top_resp_data.get("value", 0.0) or 0.0), 2)
                top_resp_return_share = round(_safe_pct(top_resp_return_value, item["returned_value"]), 2)

        window_checks = int(item.get("window_checks", 0) or 0)
        window_hits = int(item.get("window_hits", 0) or 0)
        window_misses = int(item.get("window_misses", 0) or 0)
        window_adherence_pct = round(_safe_pct(window_hits, window_checks), 2) if window_checks > 0 else None

        risk_score = min(
            100,
            int(
                round(
                    (return_rate_value * 10.5)
                    + (return_rate_qtd * 1.6)
                    + min(18.0, avg_duration_m / 6.0)
                    + min(16.0, item["reopen_count"] * 4.0)
                    + (10.0 if item["returned_occurrences"] >= 2 else 0.0)
                    + (8.0 if weekly_peak >= 3 else 0.0)
                )
            ),
        )
        risk_label, risk_tone = _risk_label(risk_score)

        ck = item["client_key"]
        unproductive_m = round(float(exec_cur["unprod_by_key"].get(ck, 0.0) or 0.0), 1)
        macro_vals: dict[str, float] = {}
        for mot, data in (item.get("motivos") or {}).items():
            mac = _classify_macro_cause(mot, "")
            macro_vals[mac] = macro_vals.get(mac, 0.0) + float(data.get("value") or 0)
        dom_macro = "—"
        dom_macro_share = 0.0
        if macro_vals:
            dom_macro, mv = max(macro_vals.items(), key=lambda x: x[1])
            tv = sum(macro_vals.values())
            dom_macro_share = round(_safe_pct(mv, tv), 1) if tv > 0 else 0.0
        elif float(item.get("returned_value") or 0) > 0:
            dom_macro = _classify_macro_cause(top_motivo_name, top_resp_name)
            dom_macro_share = 100.0
        dv_client = float(item.get("delivered_value") or 0)
        tdur = float(item.get("total_duration_m") or 0)
        min_per_1000 = round(tdur / max(dv_client / 1000.0, 0.01), 1) if dv_client > 0 else 0.0
        est_op_cost = round((tdur / 60.0) * _BI_EXEC_HOURLY_COST, 2)
        est_balance = round(dv_client - est_op_cost - float(item.get("returned_value") or 0), 2)
        logistic_weight = round(tdur / max(dv_client, 1.0), 4) if dv_client > 0 else 0.0
        return_per_hour = round(float(item.get("returned_value") or 0) / max(tdur / 60.0, 0.01), 2)
        ur = unproductive_m / max(tdur, 0.01)
        wear_score = min(
            100,
            int(
                round(
                    return_rate_value * 10.0
                    + min(28.0, ur * 42.0)
                    + min(20.0, avg_duration_m / 5.5)
                    + min(14.0, float(item.get("reopen_count") or 0) * 3.5)
                    + return_rate_qtd * 2.2
                    + (10.0 if item["returned_occurrences"] >= 2 else 0.0)
                )
            ),
        )
        if wear_score >= 75:
            wear_tier, wear_tone = ("Destrutivo", "danger")
        elif wear_score >= 52:
            wear_tier, wear_tone = ("Crítico", "danger")
        elif wear_score >= 30:
            wear_tier, wear_tone = ("Atenção", "warning")
        else:
            wear_tier, wear_tone = ("Saudável", "success")
        if dom_macro == "Comercial":
            suggested_action = "Alinhar pedido, preço e prazo com comercial antes da próxima expedição."
        elif dom_macro == "Logística":
            suggested_action = "Foco em conferência de carga, separação e execução de rota."
        elif dom_macro == "Cadastro / planejamento":
            suggested_action = "Auditoria de endereço, janela e acesso no cadastro."
        elif dom_macro == "Cliente / mercado":
            suggested_action = "Renegociar janela e confirmação de recebimento (D-1)."
        elif dom_macro == "Financeiro / pagamento":
            suggested_action = "Validar forma de pagamento e limite com financeiro/comercial."
        else:
            suggested_action = "Revisão conjunta comercial + operação no ponto."

        ranking_rows.append(
            {
                "client_id": item["client_id"],
                "client_name": item["client_name"],
                "city": item["city"],
                "bairro": item["bairro"],
                "segmento": item["segmento"],
                "prioridade": item["prioridade"],
                "status_operacional": item["status_operacional"],
                "status_cadastro": item["status_cadastro"],
                "address": item["address"],
                "window": item["window"],
                "visits": item["visits"],
                "delivered_visits": item["delivered_visits"],
                "open_visits": item["open_visits"],
                "returned_occurrences": item["returned_occurrences"],
                "weekly_peak_visits": weekly_peak,
                "weekly_avg_visits": weekly_avg,
                "planned_value": round(item["planned_value"], 2),
                "delivered_value": round(dv_client, 2),
                "returned_value": round(item["returned_value"], 2),
                "returned_kg": round(item["returned_kg"], 2),
                "return_rate_qtd": return_rate_qtd,
                "return_rate_value": return_rate_value,
                "total_duration_m": round(item["total_duration_m"], 1),
                "avg_duration_m": avg_duration_m,
                "reopen_count": item["reopen_count"],
                "top_driver_name": top_driver_name,
                "top_driver_visits": top_driver_visits,
                "top_driver_return_name": top_driver_return_name,
                "top_motivo_name": top_motivo_name,
                "top_motivo_count": top_motivo_count,
                "top_responsabilidade_name": top_resp_name,
                "latest_date": item["latest_date"],
                "risk_score": risk_score,
                "risk_label": risk_label,
                "risk_tone": risk_tone,
                "has_previous_data": has_previous_data,
                "previous_return_rate_qtd": prev_return_rate_qtd,
                "previous_return_rate_value": prev_return_rate_value,
                "previous_returned_value": prev_returned_value,
                "delta_return_rate_qtd": delta_return_rate_qtd,
                "delta_return_rate_value": delta_return_rate_value,
                "delta_returned_value": delta_returned_value,
                "window_checks": window_checks,
                "window_hits": window_hits,
                "window_misses": window_misses,
                "window_adherence_pct": window_adherence_pct,
                "top_driver_return_value": top_driver_return_value,
                "top_driver_return_share": top_driver_return_share,
                "top_responsabilidade_return_value": top_resp_return_value,
                "top_responsabilidade_return_share": top_resp_return_share,
                "unproductive_m": unproductive_m,
                "dominant_macro": dom_macro,
                "dominant_macro_share": dom_macro_share,
                "min_per_1000_brl": min_per_1000,
                "est_operational_cost": est_op_cost,
                "est_balance": est_balance,
                "logistic_weight": logistic_weight,
                "return_per_hour": return_per_hour,
                "wear_score": wear_score,
                "wear_tier": wear_tier,
                "wear_tone": wear_tone,
                "suggested_action": suggested_action,
            }
        )

    ranking_rows.sort(
        key=lambda row: (
            row.get("wear_score", 0),
            row.get("risk_score", 0),
            row.get("returned_value", 0.0),
            row.get("total_duration_m", 0.0),
        ),
        reverse=True,
    )

    rf = str(returns_filter or "Todos").strip().lower()
    if rf == "com_devolucao":
        ranking_rows = [row for row in ranking_rows if float(row.get("returned_value") or 0) > 0 or int(row.get("returned_occurrences") or 0) > 0]
    elif rf == "acima_meta":
        ranking_rows = [row for row in ranking_rows if float(row.get("return_rate_value") or 0) >= 2.0]

    total_visits = sum(int(row.get("visits", 0) or 0) for row in ranking_rows)
    critical_clients = [row for row in ranking_rows if (row.get("risk_score", 0) >= 70 or row.get("return_rate_value", 0.0) >= 2.0)]
    clients_with_returns = [row for row in ranking_rows if (row.get("returned_occurrences", 0) or 0) > 0]
    top_time_row = max(ranking_rows, key=lambda row: row.get("total_duration_m", 0.0), default=None)
    top_freq_row = max(ranking_rows, key=lambda row: (row.get("weekly_peak_visits", 0), row.get("visits", 0)), default=None)
    top_return_row = max(ranking_rows, key=lambda row: row.get("returned_value", 0.0), default=None)
    top_pct_row = max(ranking_rows, key=lambda row: row.get("return_rate_value", 0.0), default=None)
    top_recurrence_row = max(ranking_rows, key=lambda row: row.get("returned_occurrences", 0), default=None)
    top_risk_row = ranking_rows[0] if ranking_rows else None
    worsening_candidates = [row for row in ranking_rows if row.get("has_previous_data")]
    top_worsening_row = max(
        worsening_candidates,
        key=lambda row: (row.get("delta_return_rate_value", 0.0), row.get("delta_returned_value", 0.0)),
        default=None,
    )
    window_rows = [row for row in ranking_rows if (row.get("window_checks", 0) or 0) > 0]
    top_window_risk_row = min(
        window_rows,
        key=lambda row: (row.get("window_adherence_pct", 100.0), -int(row.get("window_misses", 0) or 0)),
        default=None,
    )
    driver_concentration_rows = [row for row in ranking_rows if (row.get("top_driver_return_share", 0.0) or 0.0) > 0]
    top_driver_concentration_row = max(
        driver_concentration_rows,
        key=lambda row: (row.get("top_driver_return_share", 0.0), row.get("returned_value", 0.0)),
        default=None,
    )
    resp_concentration_rows = [row for row in ranking_rows if (row.get("top_responsabilidade_return_share", 0.0) or 0.0) > 0]
    top_resp_concentration_row = max(
        resp_concentration_rows,
        key=lambda row: (row.get("top_responsabilidade_return_share", 0.0), row.get("returned_value", 0.0)),
        default=None,
    )

    city_agg: dict[str, dict] = {}
    for row in ranking_rows:
        city_label = str(row.get("city") or "Sem cidade").strip() or "Sem cidade"
        city_bucket = city_agg.setdefault(city_label, {"city": city_label, "clients": 0, "visits": 0, "returned_value": 0.0})
        city_bucket["clients"] += 1
        city_bucket["visits"] += int(row.get("visits", 0) or 0)
        city_bucket["returned_value"] += float(row.get("returned_value", 0.0) or 0.0)
    city_rows = sorted(city_agg.values(), key=lambda row: (row["visits"], row["returned_value"]), reverse=True)
    top_city_row = city_rows[0] if city_rows else None
    top_city_share = round(_safe_pct(top_city_row["visits"], total_visits), 1) if top_city_row else 0.0

    ec, ep = exec_cur, exec_prev
    fin_b = max(float(ec["financial_base"] or 0), 0.01)
    fin_b_prev = max(float(ep["financial_base"] or 0), 0.01)
    pct_dev = round(_safe_pct(ec["returned_total"], fin_b), 2)
    pct_dev_prev = round(_safe_pct(ep["returned_total"], fin_b_prev), 2)

    def _delta_pct_exec(a, b):
        try:
            a_f = float(a or 0)
            b_f = float(b or 0)
            if not math.isfinite(a_f) or not math.isfinite(b_f) or b_f <= 0:
                return None
            return round((a_f - b_f) / b_f * 100.0, 1)
        except Exception:
            return None

    clients_over_60 = sum(1 for r in ranking_rows if float(r.get("avg_duration_m") or 0) > 60)
    clients_over_90 = sum(1 for r in ranking_rows if float(r.get("avg_duration_m") or 0) > 90)
    waste_pct = round(_safe_pct(ec["unproductive_total"], ec["duration_total"]), 2) if ec["duration_total"] > 0 else 0.0
    waste_prev = round(_safe_pct(ep["unproductive_total"], ep["duration_total"]), 2) if ep["duration_total"] > 0 else 0.0

    executive_kpis = {
        "delivered_value": ec["delivered_total"],
        "returned_value": ec["returned_total"],
        "return_pct_value": pct_dev,
        "total_duration_min": ec["duration_total"],
        "unproductive_min": ec["unproductive_total"],
        "productive_min": ec["productive_total"],
        "waste_pct": waste_pct,
        "monitored_clients": len(ranking_rows),
        "deliveries_count": ec["visits_rota"],
        "clients_with_returns": len(clients_with_returns),
        "clients_avg_over_60": clients_over_60,
        "clients_avg_over_90": clients_over_90,
        "delta_delivered_pct": _delta_pct_exec(ec["delivered_total"], ep["delivered_total"]),
        "delta_return_pp": round(pct_dev - pct_dev_prev, 2),
        "delta_duration_pct": _delta_pct_exec(ec["duration_total"], ep["duration_total"]),
        "delta_unproductive_pct": _delta_pct_exec(ec["unproductive_total"], ep["unproductive_total"]),
        "delta_waste_pp": round(waste_pct - waste_prev, 2),
        "period_current": current_label,
        "period_previous": previous_label,
    }

    executive_headlines = []
    macro_v = ec["macro_value_global"]
    tmacro = sum(macro_v.values()) or 1.0
    if tmacro > 200 and _safe_pct(macro_v.get("Logística", 0), tmacro) < 40:
        executive_headlines.append(
            "Parte relevante das perdas em valor não se concentra na macrocausa Logística — aprofundar comercial, cadastro e cliente."
        )
    dur_sorted = sorted((float(r.get("total_duration_m") or 0) for r in ranking_rows), reverse=True)
    top5_share = (sum(dur_sorted[:5]) / max(float(ec["duration_total"] or 1), 1.0)) if ranking_rows else 0.0
    if top5_share >= 0.30 and len(ranking_rows) >= 5:
        executive_headlines.append(
            "Grande parte do tempo operacional concentra-se em poucos clientes — priorizar planos de ação direcionados."
        )
    vr = max(1, ec["visits_rota"])
    slow_share = _safe_pct(ec["bucket_visits"][3] + ec["bucket_visits"][4], vr)
    if slow_share >= 12 and ec["visits_rota"] > 15:
        executive_headlines.append(
            "Visitas longas (61+ min) pesam no mix — revisar roteirização, janelas e cadastro de acesso."
        )
    destr_n = sum(1 for r in ranking_rows if r.get("wear_tier") == "Destrutivo")
    if destr_n >= 1:
        executive_headlines.append(
            f"{destr_n} cliente(s) em perfil Destrutivo (alto desgaste) exigem intervenção gerencial prioritária."
        )
    if not executive_headlines:
        executive_headlines.append("Recorte sem alertas executivos extremos; manter monitoramento semanal.")

    false_villains = []
    for r in ranking_rows:
        if float(r.get("returned_value") or 0) <= 0:
            continue
        dm = r.get("dominant_macro") or ""
        if dm in ("—", "Logística"):
            continue
        if float(r.get("return_rate_value") or 0) >= 0.8 or int(r.get("wear_score") or 0) >= 42:
            false_villains.append(
                {
                    "client_id": r.get("client_id"),
                    "client_name": r.get("client_name"),
                    "city": r.get("city"),
                    "returned_value": r.get("returned_value"),
                    "unproductive_m": r.get("unproductive_m"),
                    "dominant_macro": dm,
                    "driver": r.get("top_driver_return_name") or r.get("top_driver_name"),
                    "suggested_action": r.get("suggested_action"),
                }
            )
    false_villains = false_villains[:15]

    cb_map = exec_cur["city_bucket"]
    city_visit_tot = {c: sum(cb_map[c]) for c in cb_map}
    heatmap_cities = sorted(city_visit_tot.keys(), key=lambda x: city_visit_tot[x], reverse=True)[:14]
    if not heatmap_cities and city_rows:
        heatmap_cities = [r["city"] for r in city_rows[:14]]
    heatmap_bucket_matrix = [[int(cb_map.get(c, [0] * 5)[i]) for i in range(5)] for c in heatmap_cities]
    all_causes = set()
    for cco in exec_cur["city_cause"].values():
        all_causes.update(cco.keys())
    cause_order = sorted(all_causes)[:12] if all_causes else ["Devolução", "Outros"]
    heatmap_cause_matrix = [[int(exec_cur["city_cause"].get(c, {}).get(cause, 0)) for cause in cause_order] for c in heatmap_cities]

    city_roll: dict[str, dict] = {}
    for r in ranking_rows:
        ct = str(r.get("city") or "Sem cidade").strip() or "Sem cidade"
        b = city_roll.setdefault(ct, {"td": 0.0, "v": 0, "unp": 0.0, "del": 0.0, "ret": 0.0, "cli": 0, "m60": 0})
        b["td"] += float(r.get("total_duration_m") or 0)
        b["v"] += int(r.get("visits") or 0)
        b["unp"] += float(r.get("unproductive_m") or 0)
        b["del"] += float(r.get("delivered_value") or 0)
        b["ret"] += float(r.get("returned_value") or 0)
        b["cli"] += 1
        if float(r.get("avg_duration_m") or 0) > 60:
            b["m60"] += 1
    macro_by_city: dict[str, dict[str, int]] = {}
    for r in ranking_rows:
        ct = str(r.get("city") or "Sem cidade")
        dm = r.get("dominant_macro") or ""
        if dm and dm != "—":
            macro_by_city.setdefault(ct, {})
            macro_by_city[ct][dm] = macro_by_city[ct].get(dm, 0) + 1

    def _city_max(getter):
        if not city_roll:
            return "—", 0.0
        best = max(city_roll.items(), key=lambda kv: getter(kv[1]))
        return best[0], getter(best[1])

    ct_time, _ = _city_max(lambda x: x["td"] / max(x["v"], 1))
    ct_unp, _ = _city_max(lambda x: x["unp"])
    ct_m60, v_m60 = _city_max(lambda x: x["m60"] / max(x["cli"], 1) * 100.0)
    ct_dev, _ = _city_max(lambda x: _safe_pct(x["ret"], x["del"] + x["ret"]) if (x["del"] + x["ret"]) > 0 else 0)
    ct_com = "—"
    if macro_by_city:
        ct_com = max(macro_by_city.items(), key=lambda kv: kv[1].get("Comercial", 0))[0]

    heatmap_city_kpis = [
        {"label": "Maior tempo médio (min/visita)", "city": ct_time, "hint": "Cidade com maior tempo total / visitas"},
        {"label": "Maior tempo improdutivo acumulado", "city": ct_unp},
        {"label": "Maior % clientes com média >60 min", "city": ct_m60, "value": round(v_m60, 1)},
        {"label": "Maior % devolução s/ valor (agreg.)", "city": ct_dev},
        {"label": "Mais clientes macro Comercial", "city": ct_com},
    ]

    anomaly_flags = []
    if top_risk_row and top_risk_row["risk_score"] >= 70:
        anomaly_flags.append(
            f"Cliente mais crítico: {top_risk_row['client_name']} com score {top_risk_row['risk_score']} e devolução financeira em {_fmt_br_1(top_risk_row['return_rate_value'])}%."
        )
    if top_return_row and top_return_row["returned_value"] > 0:
        anomaly_flags.append(
            f"Maior impacto financeiro: {top_return_row['client_name']} acumulou { _fmt_br_moeda(top_return_row['returned_value']) } em devoluções."
        )
    if top_time_row and top_time_row["total_duration_m"] >= 180:
        anomaly_flags.append(
            f"Tempo operacional concentrado em {top_time_row['client_name']}: { _fmt_br_duracao(top_time_row['total_duration_m']) } no período."
        )
    if top_recurrence_row and top_recurrence_row["returned_occurrences"] >= 2:
        anomaly_flags.append(
            f"Recorrência de devolução: {top_recurrence_row['client_name']} teve {top_recurrence_row['returned_occurrences']} ocorrência(s) no período."
        )
    if top_city_row and top_city_share >= 40:
        anomaly_flags.append(
            f"Concentração geográfica: {top_city_row['city']} representa {_fmt_br_1(top_city_share)}% das visitas filtradas."
        )
    if top_worsening_row and top_worsening_row.get("delta_return_rate_value", 0.0) >= 1.0:
        anomaly_flags.append(
            f"Piora vs período anterior: {top_worsening_row['client_name']} subiu {_fmt_br_1(top_worsening_row['delta_return_rate_value'])} p.p. em devolução por valor."
        )
    if top_window_risk_row and (top_window_risk_row.get("window_adherence_pct") or 0.0) < 85:
        anomaly_flags.append(
            f"Janela crítica: {top_window_risk_row['client_name']} aderiu a {_fmt_br_1(top_window_risk_row['window_adherence_pct'])}% da janela ({top_window_risk_row['window_misses']} fora da janela)."
        )
    if top_driver_concentration_row and top_driver_concentration_row.get("top_driver_return_share", 0.0) >= 75:
        anomaly_flags.append(
            f"Concentração em motorista: {top_driver_concentration_row['client_name']} depende de {top_driver_concentration_row['top_driver_return_name']} em {_fmt_br_1(top_driver_concentration_row['top_driver_return_share'])}% do valor devolvido."
        )
    if top_resp_concentration_row and top_resp_concentration_row.get("top_responsabilidade_return_share", 0.0) >= 75:
        anomaly_flags.append(
            f"Concentração em responsabilidade: {top_resp_concentration_row['client_name']} concentra {_fmt_br_1(top_resp_concentration_row['top_responsabilidade_return_share'])}% do valor em {top_resp_concentration_row['top_responsabilidade_name']}."
        )
    if not anomaly_flags:
        anomaly_flags.append("Sem concentração crítica de cliente no recorte selecionado.")

    recommendations = []
    if top_pct_row and top_pct_row["return_rate_value"] >= 2:
        recommendations.append(
            f"Abrir plano de ação com {top_pct_row['client_name']} e {top_pct_row['top_driver_name']} para reduzir a devolução em valor abaixo de 2,0%."
        )
    if top_time_row and top_time_row["avg_duration_m"] >= 90:
        recommendations.append(
            f"Revisar janela, acesso e sequência de atendimento de {top_time_row['client_name']} para reduzir o tempo médio de {_fmt_br_duracao(top_time_row['avg_duration_m'])}."
        )
    if top_freq_row and top_freq_row["weekly_peak_visits"] >= 3:
        recommendations.append(
            f"Mapear rotina semanal de {top_freq_row['client_name']}: pico de {top_freq_row['weekly_peak_visits']} visita(s) por semana."
        )
    if top_recurrence_row and top_recurrence_row["top_motivo_name"] != "-":
        recommendations.append(
            f"Atacar o motivo recorrente '{top_recurrence_row['top_motivo_name']}' em {top_recurrence_row['client_name']}."
        )
    if top_city_row and top_city_share >= 40:
        recommendations.append(
            f"Separar carteira por cidade em {top_city_row['city']} para reduzir concentração de rota e gargalo operacional."
        )
    if top_worsening_row and top_worsening_row.get("delta_return_rate_value", 0.0) >= 1.0:
        recommendations.append(
            f"Revisar o cliente {top_worsening_row['client_name']} contra o período anterior: foco em causa raiz, embalagem e conferência com {top_worsening_row['top_driver_name']}."
        )
    if top_window_risk_row and (top_window_risk_row.get("window_adherence_pct") or 0.0) < 90:
        recommendations.append(
            f"Negociar janela e sequência de atendimento de {top_window_risk_row['client_name']} para reduzir {top_window_risk_row['window_misses']} visita(s) fora da janela."
        )
    if top_driver_concentration_row and top_driver_concentration_row.get("top_driver_return_share", 0.0) >= 70:
        recommendations.append(
            f"Quebrar concentração de execução em {top_driver_concentration_row['client_name']}: hoje {top_driver_concentration_row['top_driver_return_name']} representa {_fmt_br_1(top_driver_concentration_row['top_driver_return_share'])}% do valor devolvido."
        )
    if top_resp_concentration_row and top_resp_concentration_row.get("top_responsabilidade_return_share", 0.0) >= 70:
        recommendations.append(
            f"Atacar a responsabilidade dominante em {top_resp_concentration_row['client_name']}: {top_resp_concentration_row['top_responsabilidade_name']} concentra {_fmt_br_1(top_resp_concentration_row['top_responsabilidade_return_share'])}%."
        )
    if not recommendations:
        recommendations.append("Operação de clientes sem alarme relevante no período; manter acompanhamento semanal.")

    managerial_actions = []
    for rec in recommendations[:10]:
        cat = "conjunta"
        rl = (rec or "").lower()
        if any(x in rl for x in ("comercial", "pedido", "preço", "preco", "prazo", "venda")):
            cat = "comercial"
        elif any(x in rl for x in ("carga", "expedição", "expedicao", "motorista", "rota", "separação", "separacao", "conferência")):
            cat = "logistica"
        elif any(x in rl for x in ("janela", "cadastro", "acesso", "cidade", "carteira")):
            cat = "cadastro"
        elif "financeiro" in rl or "pagamento" in rl:
            cat = "financeira"
        managerial_actions.append({"category": cat, "text": rec})

    detail_title = "Selecione um cliente no ranking para abrir o drill-through."
    detail_client = None
    detail_rows = []
    if detail_client_id:
        if int(detail_client_id) < 0:
            gid = -int(detail_client_id)
            grp = session.get(models.ClientGroup, gid)
            mem = session.exec(select(models.Client.id).where(models.Client.client_group_id == gid)).all()
            mem_set = {int(x) for x in mem if x is not None}
            detail_rows = [
                row for row in sorted(filtered_rows, key=lambda current: (current.get("date") or "", current.get("route_id") or 0), reverse=True)
                if row.get("client_id") in mem_set
            ]
            gnm = grp.name if grp else f"Grupo #{gid}"
            detail_client = {
                "client_id": detail_client_id,
                "client_name": f"Grupo: {gnm}",
                "city": "—",
                "bairro": "—",
                "segmento": "—",
                "prioridade": "—",
                "status_operacional": "—",
                "status_cadastro": "—",
                "address": "—",
                "window": "—",
            }
            detail_title = f"Drill-through · {detail_client['client_name']} ({len(mem_set)} lojas)"
        else:
            detail_client = next((row for row in ranking_rows if row.get("client_id") == detail_client_id), None)
            detail_rows = [
                row for row in sorted(filtered_rows, key=lambda current: (current.get("date") or "", current.get("route_id") or 0), reverse=True)
                if row.get("client_id") == detail_client_id
            ]
            if detail_client:
                detail_title = f"Drill-through do cliente {detail_client['client_name']}"

    macro_items = sorted(macro_v.items(), key=lambda x: -x[1]) if macro_v else [("Sem dados", 0.0)]
    vr_exec = max(1, ec["visits_rota"])
    scatter_pts = []
    sc_cand = [r for r in ranking_rows if int(r.get("visits") or 0) >= 1][:42]
    if len(sc_cand) >= 2:
        xs = [float(r.get("avg_duration_m") or 0) for r in sc_cand]
        ys = [float(r.get("delivered_value") or 0) for r in sc_cand]
        try:
            mx = float(statistics.median(xs))
            my = float(statistics.median(ys)) if ys else 0.0
        except statistics.StatisticsError:
            mx, my = 45.0, 5000.0
        for r in sc_cand:
            x, y = float(r.get("avg_duration_m") or 0), float(r.get("delivered_value") or 0)
            if y >= my and x <= mx:
                quad = "Eficiente"
            elif y >= my:
                quad = "Estratégico (pesado)"
            elif x >= mx:
                quad = "Destrutivo"
            else:
                quad = "Baixo impacto"
            scatter_pts.append(
                {
                    "x": round(x, 1),
                    "y": round(y, 2),
                    "r": int(min(22, max(5, int(r.get("visits") or 1) * 2))),
                    "name": (r.get("client_name") or "")[:28],
                    "cid": r.get("client_id"),
                    "retpct": round(float(r.get("return_rate_value") or 0), 2),
                    "quad": quad,
                }
            )
    serve_rank = sorted(
        [r for r in ranking_rows if float(r.get("delivered_value") or 0) > 100],
        key=lambda r: float(r.get("min_per_1000_brl") or 0),
        reverse=True,
    )[:12]
    du_sorted = sorted(exec_cur["driver_unprod"].items(), key=lambda x: -x[1])[:10]
    cu_sorted = sorted(exec_cur["cause_unprod_time"].items(), key=lambda x: -x[1])[:8]

    chart_payload = {
        "time_rank": {
            "labels": [row["client_name"] for row in sorted(ranking_rows, key=lambda row: row.get("total_duration_m", 0.0), reverse=True)[:12]],
            "minutes": [round(row["total_duration_m"], 1) for row in sorted(ranking_rows, key=lambda row: row.get("total_duration_m", 0.0), reverse=True)[:12]],
            "avg_minutes": [round(row["avg_duration_m"], 1) for row in sorted(ranking_rows, key=lambda row: row.get("total_duration_m", 0.0), reverse=True)[:12]],
        },
        "frequency_rank": {
            "labels": [row["client_name"] for row in sorted(ranking_rows, key=lambda row: (row.get("weekly_peak_visits", 0), row.get("visits", 0)), reverse=True)[:12]],
            "visits": [int(row["visits"]) for row in sorted(ranking_rows, key=lambda row: (row.get("weekly_peak_visits", 0), row.get("visits", 0)), reverse=True)[:12]],
            "weekly_peak": [int(row["weekly_peak_visits"]) for row in sorted(ranking_rows, key=lambda row: (row.get("weekly_peak_visits", 0), row.get("visits", 0)), reverse=True)[:12]],
        },
        "returns_rank": {
            "labels": [row["client_name"] for row in sorted(ranking_rows, key=lambda row: row.get("returned_value", 0.0), reverse=True)[:12]],
            "returned_value": [round(row["returned_value"], 2) for row in sorted(ranking_rows, key=lambda row: row.get("returned_value", 0.0), reverse=True)[:12]],
            "return_rate_value": [round(row["return_rate_value"], 2) for row in sorted(ranking_rows, key=lambda row: row.get("returned_value", 0.0), reverse=True)[:12]],
        },
        "city_concentration": {
            "labels": [row["city"] for row in city_rows[:10]],
            "visits": [int(row["visits"]) for row in city_rows[:10]],
            "clients": [int(row["clients"]) for row in city_rows[:10]],
            "returned_value": [round(row["returned_value"], 2) for row in city_rows[:10]],
        },
        "comparison_meta": {
            "current_label": current_label,
            "previous_label": previous_label,
        },
        "period_compare": {
            "labels": [row["client_name"] for row in sorted(worsening_candidates, key=lambda row: (row.get("delta_return_rate_value", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "current_pct": [round(row["return_rate_value"], 2) for row in sorted(worsening_candidates, key=lambda row: (row.get("delta_return_rate_value", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "previous_pct": [round(row["previous_return_rate_value"], 2) for row in sorted(worsening_candidates, key=lambda row: (row.get("delta_return_rate_value", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "delta_pct": [round(row["delta_return_rate_value"], 2) for row in sorted(worsening_candidates, key=lambda row: (row.get("delta_return_rate_value", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "current_value": [round(row["returned_value"], 2) for row in sorted(worsening_candidates, key=lambda row: (row.get("delta_return_rate_value", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "previous_value": [round(row["previous_returned_value"], 2) for row in sorted(worsening_candidates, key=lambda row: (row.get("delta_return_rate_value", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
        },
        "driver_concentration": {
            "labels": [row["client_name"] for row in sorted(driver_concentration_rows, key=lambda row: (row.get("top_driver_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "share": [round(row["top_driver_return_share"], 2) for row in sorted(driver_concentration_rows, key=lambda row: (row.get("top_driver_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "driver": [row["top_driver_return_name"] for row in sorted(driver_concentration_rows, key=lambda row: (row.get("top_driver_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "returned_value": [round(row["returned_value"], 2) for row in sorted(driver_concentration_rows, key=lambda row: (row.get("top_driver_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
        },
        "responsibility_concentration": {
            "labels": [row["client_name"] for row in sorted(resp_concentration_rows, key=lambda row: (row.get("top_responsabilidade_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "share": [round(row["top_responsabilidade_return_share"], 2) for row in sorted(resp_concentration_rows, key=lambda row: (row.get("top_responsabilidade_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "responsabilidade": [row["top_responsabilidade_name"] for row in sorted(resp_concentration_rows, key=lambda row: (row.get("top_responsabilidade_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
            "returned_value": [round(row["returned_value"], 2) for row in sorted(resp_concentration_rows, key=lambda row: (row.get("top_responsabilidade_return_share", 0.0), row.get("returned_value", 0.0)), reverse=True)[:12]],
        },
        "window_adherence": {
            "labels": [row["client_name"] for row in sorted(window_rows, key=lambda row: (row.get("window_adherence_pct", 100.0), -(row.get("window_misses", 0) or 0)), reverse=False)[:12]],
            "adherence_pct": [round(row["window_adherence_pct"], 2) for row in sorted(window_rows, key=lambda row: (row.get("window_adherence_pct", 100.0), -(row.get("window_misses", 0) or 0)), reverse=False)[:12]],
            "hits": [int(row["window_hits"]) for row in sorted(window_rows, key=lambda row: (row.get("window_adherence_pct", 100.0), -(row.get("window_misses", 0) or 0)), reverse=False)[:12]],
            "misses": [int(row["window_misses"]) for row in sorted(window_rows, key=lambda row: (row.get("window_adherence_pct", 100.0), -(row.get("window_misses", 0) or 0)), reverse=False)[:12]],
            "checks": [int(row["window_checks"]) for row in sorted(window_rows, key=lambda row: (row.get("window_adherence_pct", 100.0), -(row.get("window_misses", 0) or 0)), reverse=False)[:12]],
        },
        "duration_buckets": {
            "labels": list(_DURATION_BUCKET_LABELS),
            "visits": list(ec["bucket_visits"]),
            "visit_pct": [round(_safe_pct(ec["bucket_visits"][i], vr_exec), 1) for i in range(5)],
            "delivered_value": list(ec["bucket_value"]),
            "duration_min": list(ec["bucket_duration"]),
            "returns": list(ec["bucket_returns"]),
            "unprod_min": list(ec["bucket_unprod"]),
        },
        "macro_loss": {
            "labels": [a[0] for a in macro_items],
            "values": [round(a[1], 2) for a in macro_items],
            "pct": [round(_safe_pct(a[1], tmacro), 1) for a in macro_items],
            "minutes": [round(exec_cur["macro_time_global"].get(a[0], 0.0), 1) for a in macro_items],
        },
        "productive_split": {
            "productive_min": ec["productive_total"],
            "unproductive_min": ec["unproductive_total"],
        },
        "scatter_clients": scatter_pts,
        "exec_compare_bars": {
            "labels": ["Valor entregue (R$)", "Valor devolvido (R$)", "Tempo total (h)", "Tempo improd. (h)"],
            "current": [
                round(ec["delivered_total"], 2),
                round(ec["returned_total"], 2),
                round(ec["duration_total"] / 60.0, 2),
                round(ec["unproductive_total"] / 60.0, 2),
            ],
            "previous": [
                round(ep["delivered_total"], 2),
                round(ep["returned_total"], 2),
                round(ep["duration_total"] / 60.0, 2),
                round(ep["unproductive_total"] / 60.0, 2),
            ],
        },
        "serve_cost_rank": {
            "labels": [r.get("client_name", "")[:22] for r in serve_rank],
            "min_per_1000": [float(r.get("min_per_1000_brl") or 0) for r in serve_rank],
            "est_balance": [float(r.get("est_balance") or 0) for r in serve_rank],
        },
        "driver_unproductive": {"labels": [a[0][:18] for a in du_sorted], "minutes": [round(a[1], 1) for a in du_sorted]},
        "cause_unproductive": {"labels": [a[0][:20] for a in cu_sorted], "minutes": [round(a[1], 1) for a in cu_sorted]},
        "heatmap_duration": {
            "cities": heatmap_cities,
            "buckets": list(_DURATION_BUCKET_LABELS),
            "matrix": heatmap_bucket_matrix,
        },
        "heatmap_cause": {
            "cities": heatmap_cities,
            "causes": cause_order,
            "matrix": heatmap_cause_matrix,
        },
        "wear_rank": {
            "labels": [r.get("client_name", "")[:20] for r in ranking_rows[:15]],
            "scores": [int(r.get("wear_score") or 0) for r in ranking_rows[:15]],
            "tiers": [r.get("wear_tier") or "" for r in ranking_rows[:15]],
        },
    }

    filters = {
        **delivery_dataset.get("filters", {}),
        "client_id": client_id,
        "city": city,
        "priority": priority,
        "client_status": client_status,
        "segmentos": selected_segmentos,
        "returns_filter": returns_filter,
        "detail_client_id": detail_client_id,
        "client_scope": scope if client_id else "solo",
        "group_filter_note": group_filter_note,
    }
    _fq = {
        "date_from": filters.get("date_from") or "",
        "date_to": filters.get("date_to") or "",
        "shift": filters.get("shift") or "Todos",
        "driver_id": filters.get("driver_id") or "",
        "plate": filters.get("plate") or "Todos",
        "status": filters.get("status") or "Todos",
        "client_id": filters.get("client_id") or "",
        "city": filters.get("city") or "Todos",
        "priority": filters.get("priority") or "Todos",
        "client_status": filters.get("client_status") or "Todos",
        "returns_filter": filters.get("returns_filter") or "Todos",
        "client_scope": filters.get("client_scope") or "solo",
    }
    _fq["segmentos"] = filters.get("segmentos") or []
    if filters.get("detail_client_id"):
        _fq["detail_client_id"] = str(filters["detail_client_id"])
    filters_query = urlencode(_fq, doseq=True)

    kpis = {
        "monitored_clients": len(ranking_rows),
        "clients_with_returns": len(clients_with_returns),
        "critical_clients": len(critical_clients),
        "total_visits": total_visits,
        "top_time_client": top_time_row["client_name"] if top_time_row else "—",
        "top_time_minutes": round(top_time_row["total_duration_m"], 1) if top_time_row else 0.0,
        "top_freq_client": top_freq_row["client_name"] if top_freq_row else "—",
        "top_freq_peak": int(top_freq_row["weekly_peak_visits"]) if top_freq_row else 0,
        "top_return_client": top_return_row["client_name"] if top_return_row else "—",
        "top_return_value": round(top_return_row["returned_value"], 2) if top_return_row else 0.0,
        "top_pct_client": top_pct_row["client_name"] if top_pct_row else "—",
        "top_pct_value": round(top_pct_row["return_rate_value"], 2) if top_pct_row else 0.0,
        "top_recurrence_client": top_recurrence_row["client_name"] if top_recurrence_row else "—",
        "top_recurrence_count": int(top_recurrence_row["returned_occurrences"]) if top_recurrence_row else 0,
        "top_city": top_city_row["city"] if top_city_row else "—",
        "top_city_share": top_city_share,
        "comparison_current_label": current_label,
        "comparison_previous_label": previous_label,
        "worsening_client": top_worsening_row["client_name"] if top_worsening_row else "—",
        "worsening_delta_pct": round(top_worsening_row["delta_return_rate_value"], 2) if top_worsening_row else 0.0,
        "window_client": top_window_risk_row["client_name"] if top_window_risk_row else "—",
        "window_adherence_pct": round(top_window_risk_row["window_adherence_pct"], 2) if top_window_risk_row and top_window_risk_row.get("window_adherence_pct") is not None else None,
        "driver_concentration_client": top_driver_concentration_row["client_name"] if top_driver_concentration_row else "—",
        "driver_concentration_pct": round(top_driver_concentration_row["top_driver_return_share"], 2) if top_driver_concentration_row else 0.0,
        "driver_concentration_driver": top_driver_concentration_row["top_driver_return_name"] if top_driver_concentration_row else "—",
        "responsibility_concentration_client": top_resp_concentration_row["client_name"] if top_resp_concentration_row else "—",
        "responsibility_concentration_pct": round(top_resp_concentration_row["top_responsabilidade_return_share"], 2) if top_resp_concentration_row else 0.0,
        "responsibility_concentration_name": top_resp_concentration_row["top_responsabilidade_name"] if top_resp_concentration_row else "—",
    }

    return {
        "filters": filters,
        "filters_query": filters_query,
        "kpis": kpis,
        "ranking_rows": ranking_rows[:60],
        "ranking_total": len(ranking_rows),
        "detail_client": detail_client,
        "detail_rows": detail_rows[:200],
        "detail_total": len(detail_rows),
        "detail_title": detail_title,
        "anomaly_flags": anomaly_flags[:6],
        "recommendations": recommendations[:6],
        "drivers_filter": delivery_dataset.get("drivers_filter", []),
        "plates_filter": delivery_dataset.get("plates_filter", []),
        "statuses_filter": delivery_dataset.get("statuses_filter", []),
        "clients_filter": [{"id": client_key, "name": clients_filter_map[client_key]} for client_key in sorted(clients_filter_map, key=lambda current: clients_filter_map[current])],
        "cities_filter": sorted(cities_filter),
        "priorities_filter": sorted(priorities_filter),
        "client_statuses_filter": sorted(client_statuses_filter),
        "segmentos_filter": sorted(segmentos_filter),
        "chart_payload_json": json.dumps(chart_payload, ensure_ascii=False),
        "all_client_rows": ranking_rows,
        "executive_kpis": executive_kpis,
        "executive_headlines": executive_headlines,
        "false_villains": false_villains,
        "managerial_actions": managerial_actions,
        "heatmap_city_kpis": heatmap_city_kpis,
    }


def _build_relatorio_avaliacao_motorista(
    session: Session,
    date_str: str,
    driver_ids: Optional[List[int]] = None,
) -> dict:
    """Monta dados do relatório de avaliação diária do motorista."""
    tz = ZoneInfo("America/Sao_Paulo")
    today = datetime.now(tz).date().strftime("%Y-%m-%d")

    def _parse_hhmm(v: Optional[str]) -> Optional[int]:
        if not v:
            return None
        try:
            h, m = str(v).strip().split(":")[:2]
            return int(h) * 60 + int(m)
        except (ValueError, IndexError):
            return None

    def _dur_m(start_v: Optional[str], end_v: Optional[str]) -> Optional[int]:
        s, e = _parse_hhmm(start_v), _parse_hhmm(end_v)
        if s is None or e is None:
            return None
        if e < s:
            e += 24 * 60
        return max(0, e - s)

    def _fmt_hora(v: Optional[str]) -> str:
        return (v or "--:--").strip() or "--:--"

    def _fmt_min(m: Optional[int]) -> str:
        return _fmt_br_duracao(m)

    def _valid_operation_times(values: list[Optional[str]]) -> list[int]:
        parsed = [_parse_hhmm(v) for v in values if v]
        valid = [v for v in parsed if v is not None and v > 0]
        return valid

    def _tipo_priority(tipo: Optional[str]) -> int:
        raw = (tipo or "").strip().lower()
        if "devol" in raw:
            return 0
        if "entrega" in raw:
            return 1
        return 2

    q = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == date_str)
    )
    if driver_ids:
        q = q.where(models.Route.employee_id.in_(driver_ids))
    routes = session.exec(q.order_by(models.Route.start_time, models.Route.id)).all()

    emp_ids = list({r.employee_id for r in routes if r.employee_id})
    cli_ids = list({r.client_id for r in routes if r.client_id})
    emp_map = {
        e.id: e
        for e in (
            session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all()
            if emp_ids
            else []
        )
    }
    cli_map = {
        c.id: c
        for c in (
            session.exec(select(models.Client).where(models.Client.id.in_(cli_ids))).all()
            if cli_ids
            else []
        )
    }
    vehicles = {v.placa.upper(): v for v in session.exec(select(models.Vehicle)).all()}

    by_driver: dict[int, dict] = {}
    for r in routes:
        drv_id = r.employee_id
        if drv_id not in by_driver:
            ds = session.exec(
                select(models.DeliverySession)
                .where(models.DeliverySession.employee_id == drv_id)
                .where(models.DeliverySession.date == date_str)
                .order_by(models.DeliverySession.id.desc())
            ).first()
            helpers = []
            if ds and ds.helpers_json:
                try:
                    hl = json.loads(ds.helpers_json) if isinstance(ds.helpers_json, str) else (ds.helpers_json or [])
                    seen = set()
                    for h in (hl if isinstance(hl, list) else []):
                        if h is None:
                            continue
                        if isinstance(h, (int, str)) and str(h).strip().isdigit():
                            he = emp_map.get(int(h))
                            if he and he.name:
                                key = he.name.strip().lower()
                                if key not in seen:
                                    seen.add(key)
                                    helpers.append(he.name)
                        elif isinstance(h, str) and (h or "").strip():
                            # Mobile envia nomes diretamente em helpers_json
                            name = (h or "").strip()
                            key = name.lower()
                            if key not in seen:
                                seen.add(key)
                                helpers.append(name)
                except Exception:
                    pass
            placa = (r.delivery_vehicle_plate or (ds.vehicle_plate if ds else "") or "").strip().upper()
            veic = vehicles.get(placa)
            modelo = f"{veic.marca} {veic.modelo}" if veic else (placa or "-")

            emp = emp_map.get(drv_id)
            by_driver[drv_id] = {
                "driver_id": drv_id,
                "motorista": emp.name if emp else f"Motorista #{drv_id}",
                "ajudantes": helpers,
                "km_inicial": ds.km_departure if ds else None,
                "km_final": ds.km_return if ds else None,
                "km_total": (float(ds.km_return or 0) - float(ds.km_departure or 0)) if ds and ds.km_return and ds.km_departure else None,
                "placa": placa or "-",
                "modelo": modelo,
                "turnos": set(),
                "hora_inicio": None,
                "hora_fim": None,
                "tempo_operando_min": None,
                "paradas": [],
                "saiu_kg": 0.0,
                "saiu_valor": 0.0,
                "entregue_kg": 0.0,
                "entregue_valor": 0.0,
                "devolucao_kg": 0.0,
                "devolucao_valor": 0.0,
            }

        d = by_driver[drv_id]
        d["turnos"].add((r.shift or "").strip() or "-")
        st = (r.delivery_status or "pendente").strip().lower()
        planned_kg = float(r.tonnage or 0.0)
        planned_val = float(r.valor_financeiro or 0.0)
        ret_kg = float(r.devolucao_volume if r.devolucao_volume is not None else (planned_kg if st == "devolucao" else 0.0))
        ret_val = float(r.valor_devolucao if r.valor_devolucao is not None else (planned_val if st == "devolucao" else 0.0))
        del_kg = max(0.0, planned_kg - ret_kg) if st == "devolucao" else (planned_kg if st == "entregue" else 0.0)
        del_val = max(0.0, planned_val - ret_val) if st == "devolucao" else (planned_val if st == "entregue" else 0.0)

        d["saiu_kg"] += planned_kg
        d["saiu_valor"] += planned_val
        d["entregue_kg"] += del_kg
        d["entregue_valor"] += del_val
        d["devolucao_kg"] += ret_kg
        d["devolucao_valor"] += ret_val

        cli = cli_map.get(r.client_id)
        cli_name = cli.name if cli else f"Cliente #{r.client_id}"
        start_t = r.delivery_started_at or r.start_time
        end_t = r.delivery_finished_at or r.end_time or r.delivery_returned_at
        # Duração por ciclos (cada par iniciar + finalizar/devolucao); evita somar reaberturas como tempo contínuo.
        dur = route_duration_minutes_mobile_only(r)
        tipo = "Devolução" if st == "devolucao" else "Entrega" if st == "entregue" else st

        d["paradas"].append({
            "cliente": cli_name,
            "tipo": tipo,
            "hora_inicio": _fmt_hora(start_t),
            "hora_fim": _fmt_hora(end_t),
            "duracao_min": dur,
            "duracao_fmt": _fmt_min(dur),
            "kg": planned_kg,
            "valor": planned_val,
            "entregue_kg": del_kg,
            "entregue_valor": del_val,
            "devolvido_kg": ret_kg,
            "devolvido_valor": ret_val,
        })

    reports = []
    for drv_id, d in by_driver.items():
        paradas = d["paradas"]
        paradas_ord = sorted(
            paradas,
            key=lambda x: (_tipo_priority(x.get("tipo")), x["hora_inicio"], x["cliente"])
        )
        top5_base = sorted(
            [p for p in paradas_ord if p["duracao_min"] is not None],
            key=lambda x: (-(x["duracao_min"] or 0), x["cliente"])
        )[:5]
        top5 = sorted(
            top5_base,
            key=lambda x: (_tipo_priority(x.get("tipo")), -(x["duracao_min"] or 0), x["cliente"])
        )

        clientes_resumo_map: dict[str, dict] = {}
        for parada in paradas_ord:
            cliente_key = (parada.get("cliente") or "Sem Cliente").strip() or "Sem Cliente"
            item = clientes_resumo_map.setdefault(cliente_key, {
                "cliente": cliente_key,
                "tipos": [],
                "paradas": 0,
                "duracao_total_min": 0,
                "hora_primeira_min": None,
                "hora_ultima_min": None,
                "kg_total": 0.0,
                "valor_total": 0.0,
            })
            item["paradas"] += 1
            item["kg_total"] += float(parada.get("kg") or 0.0)
            item["valor_total"] += float(parada.get("valor") or 0.0)
            if parada.get("tipo") and parada["tipo"] not in item["tipos"]:
                item["tipos"].append(parada["tipo"])

            duracao_min = parada.get("duracao_min")
            if duracao_min is not None:
                item["duracao_total_min"] += int(duracao_min)

            hora_inicio_min = _parse_hhmm(parada.get("hora_inicio"))
            if hora_inicio_min is not None and (
                item["hora_primeira_min"] is None or hora_inicio_min < item["hora_primeira_min"]
            ):
                item["hora_primeira_min"] = hora_inicio_min

            hora_fim_min = _parse_hhmm(parada.get("hora_fim"))
            if hora_fim_min is not None and (
                item["hora_ultima_min"] is None or hora_fim_min > item["hora_ultima_min"]
            ):
                item["hora_ultima_min"] = hora_fim_min

        clientes_resumo = []
        for item in clientes_resumo_map.values():
            hora_primeira_min = item["hora_primeira_min"]
            hora_ultima_min = item["hora_ultima_min"]
            tipo_principal = min((_tipo_priority(tipo) for tipo in item["tipos"]), default=2)
            clientes_resumo.append({
                "cliente": item["cliente"],
                "tipos": " / ".join(item["tipos"]) if item["tipos"] else "—",
                "tipo_principal": tipo_principal,
                "paradas": item["paradas"],
                "duracao_total_min": item["duracao_total_min"],
                "duracao_total_fmt": _fmt_min(item["duracao_total_min"]) if item["duracao_total_min"] else "--",
                "hora_primeira": f"{hora_primeira_min // 60:02d}:{hora_primeira_min % 60:02d}" if hora_primeira_min is not None else "--:--",
                "hora_ultima": f"{hora_ultima_min // 60:02d}:{hora_ultima_min % 60:02d}" if hora_ultima_min is not None else "--:--",
                "kg_total": round(item["kg_total"], 1),
                "valor_total": round(item["valor_total"], 2),
            })
        clientes_resumo.sort(
            key=lambda x: (x["tipo_principal"], x["hora_primeira"] == "--:--", x["hora_primeira"], x["cliente"].lower())
        )

        start_times = _valid_operation_times([p.get("hora_inicio") for p in paradas])
        end_times = _valid_operation_times([p.get("hora_fim") for p in paradas])

        hora_inicio = min(start_times) if start_times else None
        hora_fim = max(end_times) if end_times else (max(start_times) if start_times else None)

        d["hora_inicio"] = f"{hora_inicio // 60:02d}:{hora_inicio % 60:02d}" if hora_inicio is not None else "--:--"
        d["hora_fim"] = f"{hora_fim // 60:02d}:{hora_fim % 60:02d}" if hora_fim is not None else "--:--"

        if hora_inicio is not None and hora_fim is not None:
            d["tempo_operando_min"] = hora_fim - hora_inicio if hora_fim >= hora_inicio else ((24 * 60) - hora_inicio + hora_fim)
        else:
            d["tempo_operando_min"] = None

        base_valor = d["saiu_valor"] or 0.0
        devolucao_pct = (d["devolucao_valor"] / base_valor * 100.0) if base_valor > 0 else 0.0
        meta_pct = 2.0
        dentro_meta = devolucao_pct <= meta_pct

        # Verificar se fez checklist do caminhão (employee_id + placa + date)
        placa_raw = (d.get("placa") or "").strip()
        fez_checklist = False
        if placa_raw and placa_raw != "-":
            checklists = session.exec(
                select(models.TranspalletChecklist)
                .where(models.TranspalletChecklist.employee_id == drv_id)
                .where(models.TranspalletChecklist.date == date_str)
            ).all()
            placa_norm = placa_raw.upper().replace(" ", "").replace("-", "")
            for chk in checklists:
                eq = (chk.equipment_code or "").upper().replace(" ", "").replace("-", "")
                if eq == placa_norm:
                    fez_checklist = True
                    break

        reports.append({
            **d,
            "paradas_ordenadas": paradas_ord,
            "clientes_resumo": clientes_resumo,
            "total_clientes": len(clientes_resumo),
            "total_paradas": len(paradas_ord),
            "top5_tempo": top5,
            "top5_client_names": [p["cliente"] for p in top5],
            "tempo_operando_fmt": _fmt_min(d["tempo_operando_min"]),
            "devolucao_pct": round(devolucao_pct, 2),
            "meta_pct": meta_pct,
            "dentro_meta": dentro_meta,
            "fez_checklist_caminhao": fez_checklist,
            "turnos": sorted(d["turnos"]),
        })

    # Motoristas que tiveram rotas na data (não a lista completa)
    motoristas = [emp_map[eid] for eid in sorted(emp_map.keys(), key=lambda x: (emp_map[x].name or "").lower())]
    return {
        "date": date_str,
        "date_fmt": _fmt_br_data(date_str),
        "reports": reports,
        "motoristas": motoristas,
        "driver_ids": driver_ids or [],
    }


_RELATORIO_DRIVER_STATUS_ORDER = {
    "critico": 0,
    "pendente": 1,
    "atencao": 2,
    "concluido": 3,
}


def _coerce_relatorio_date(raw_date: Optional[str]) -> str:
    tz = ZoneInfo("America/Sao_Paulo")
    today_str = datetime.now(tz).date().strftime("%Y-%m-%d")
    value = (raw_date or "").strip() or today_str
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return today_str
    return value


def _parse_relatorio_driver_ids(raw_values) -> Optional[List[int]]:
    if not raw_values:
        return None
    values = raw_values if isinstance(raw_values, list) else [raw_values]
    parsed: list[int] = []
    seen: set[int] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text.isdigit():
            continue
        number = int(text)
        if number <= 0 or number in seen:
            continue
        seen.add(number)
        parsed.append(number)
    return parsed or None


def _normalize_relatorio_view(raw_view: Optional[str]) -> str:
    view = _norm_text(raw_view)
    if view in {"pendentes", "concluidos", "criticos", "hoje"}:
        return view
    return "todos"


def _normalize_relatorio_status(raw_status: Optional[str]) -> str:
    status_code = _norm_text(raw_status)
    if status_code in {"concluido", "atencao", "pendente", "critico"}:
        return status_code
    return ""


def _normalize_relatorio_checklist(raw_checklist: Optional[str]) -> str:
    checklist = _norm_text(raw_checklist)
    if checklist in {"com", "sem"}:
        return checklist
    return ""


def _coerce_relatorio_page_size(raw_per_page: Optional[int]) -> int:
    try:
        per_page = int(raw_per_page or 10)
    except (TypeError, ValueError):
        return 10
    return max(5, min(per_page, 100))


def _is_relatorio_driver_employee(emp) -> bool:
    role = _norm_text(getattr(emp, "role", None))
    return ("motorista" in role) and ("ajudante" not in role)


def _list_relatorio_driver_options(
    session: Session,
    selected_driver_ids: Optional[List[int]] = None,
) -> list[models.Employee]:
    selected_set = {int(x) for x in (selected_driver_ids or []) if str(x).isdigit()}
    employees = list(session.exec(select(models.Employee)).all())
    options = []
    seen: set[int] = set()
    for emp in sorted(employees, key=lambda item: ((getattr(item, "name", None) or "").casefold(), getattr(item, "id", 0) or 0)):
        emp_id = getattr(emp, "id", None)
        if not emp_id or emp_id in seen:
            continue
        status_code = _norm_text(getattr(emp, "status", None))
        if not _is_relatorio_driver_employee(emp) and emp_id not in selected_set:
            continue
        if status_code in {"fired", "demitido"} and emp_id not in selected_set:
            continue
        seen.add(emp_id)
        options.append(emp)
    return options


def _relatorio_driver_status(report: dict) -> dict:
    devolucao_pct = float(report.get("devolucao_pct") or 0.0)
    meta_pct = float(report.get("meta_pct") or 0.0)
    has_checklist = bool(report.get("fez_checklist_caminhao"))
    has_session_gap = (
        report.get("tempo_operando_min") is None
        or report.get("km_total") is None
        or (report.get("hora_inicio") or "--:--") == "--:--"
        or (report.get("hora_fim") or "--:--") == "--:--"
    )

    reasons: list[str] = []
    code = "concluido"
    label = "Concluido"
    badge = "ok"

    if devolucao_pct > meta_pct:
        code = "critico"
        label = "Critico"
        badge = "critical"
        reasons.append(
            f"Devolucao em {_fmt_br_2(devolucao_pct)}% acima da meta de {_fmt_br_2(meta_pct)}%."
        )

    if not has_checklist:
        reasons.append("Checklist do caminhao nao encontrado para o dia.")
        if code != "critico":
            code = "pendente"
            label = "Pendente"
            badge = "alert"

    if code not in {"critico", "pendente"} and has_session_gap:
        code = "atencao"
        label = "Atencao"
        badge = "alert"
        reasons.append("Sessao com horario ou quilometragem incompletos.")

    if not reasons:
        reasons.append("Meta, checklist e sessao dentro do esperado.")

    return {
        "code": code,
        "label": label,
        "badge": badge,
        "reasons": reasons,
        "has_checklist": has_checklist,
    }


def _relatorio_build_url(path: str, params: dict) -> str:
    payload = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item or "").strip()]
            if cleaned:
                payload[key] = cleaned
            continue
        text = str(value).strip()
        if text:
            payload[key] = text
    query = urlencode(payload, doseq=True)
    return f"{path}?{query}" if query else path


def _build_relatorio_summary_row(report: dict, date_str: str) -> dict:
    status_data = _relatorio_driver_status(report)
    clients = report.get("clientes_resumo") or []
    client_names = [str(item.get("cliente") or "").strip() for item in clients if str(item.get("cliente") or "").strip()]
    search_parts = [
        report.get("motorista") or "",
        " ".join(report.get("ajudantes") or []),
        report.get("placa") or "",
        report.get("modelo") or "",
        " ".join(client_names[:12]),
    ]
    top_stop = (report.get("top5_tempo") or [{}])[0] or {}
    driver_id = int(report.get("driver_id") or 0)
    km_total = report.get("km_total")
    return {
        "driver_id": driver_id,
        "motorista": report.get("motorista") or f"Motorista #{driver_id}",
        "ajudantes_label": ", ".join(report.get("ajudantes") or []) or "Sem ajudantes",
        "placa": report.get("placa") or "-",
        "modelo": report.get("modelo") or "-",
        "turnos_label": " / ".join(report.get("turnos") or []) or "-",
        "total_clientes": int(report.get("total_clientes") or 0),
        "total_paradas": int(report.get("total_paradas") or 0),
        "top_cliente": client_names[0] if client_names else "-",
        "top_parada_label": top_stop.get("cliente") or "-",
        "hora_inicio": report.get("hora_inicio") or "--:--",
        "hora_fim": report.get("hora_fim") or "--:--",
        "tempo_operando_fmt": report.get("tempo_operando_fmt") or "—",
        "saiu_valor": round(float(report.get("saiu_valor") or 0.0), 2),
        "saiu_valor_fmt": _fmt_br_moeda(report.get("saiu_valor") or 0.0),
        "entregue_valor_fmt": _fmt_br_moeda(report.get("entregue_valor") or 0.0),
        "devolucao_valor": round(float(report.get("devolucao_valor") or 0.0), 2),
        "devolucao_valor_fmt": _fmt_br_moeda(report.get("devolucao_valor") or 0.0),
        "devolucao_pct": round(float(report.get("devolucao_pct") or 0.0), 2),
        "devolucao_pct_fmt": f"{_fmt_br_2(report.get('devolucao_pct') or 0.0)}%",
        "meta_pct_fmt": f"{_fmt_br_2(report.get('meta_pct') or 0.0)}%",
        "meta_pct": round(float(report.get("meta_pct") or 0.0), 2),
        "checklist_label": "Conferido" if status_data["has_checklist"] else "Pendente",
        "checklist_badge": "ok" if status_data["has_checklist"] else "critical",
        "status_code": status_data["code"],
        "status_label": status_data["label"],
        "status_badge": status_data["badge"],
        "status_reason": status_data["reasons"][0],
        "status_reasons": status_data["reasons"],
        "km_total": km_total,
        "km_total_fmt": (f"{_fmt_br_1(km_total)} km" if km_total is not None else "—"),
        "has_checklist": status_data["has_checklist"],
        "date": date_str,
        "print_href": _relatorio_build_url(
            "/relatorio-avaliacao-motorista/impressao",
            {"date": date_str, "driver_id": [driver_id]},
        ),
        "search_blob": " ".join(search_parts).casefold(),
    }


def _make_relatorio_links(
    date_str: str,
    selected_driver_ids: Optional[List[int]],
    q: str,
    status_filter: str,
    checklist_filter: str,
    per_page: int,
    page: int,
    view: str,
) -> dict:
    base_params = {
        "date": date_str,
        "driver_id": selected_driver_ids or [],
        "q": q,
        "status": status_filter,
        "checklist": checklist_filter,
        "per_page": per_page,
    }
    paged_params = {**base_params, "page": page}
    links = {
        "todos": _relatorio_build_url("/relatorio-avaliacao-motorista", base_params),
        "pendentes": _relatorio_build_url("/relatorio-avaliacao-motorista", {**base_params, "view": "pendentes"}),
        "concluidos": _relatorio_build_url("/relatorio-avaliacao-motorista", {**base_params, "view": "concluidos"}),
        "criticos": _relatorio_build_url("/relatorio-avaliacao-motorista", {**base_params, "view": "criticos"}),
        "hoje": _relatorio_build_url(
            "/relatorio-avaliacao-motorista",
            {**base_params, "date": _coerce_relatorio_date(None), "view": "hoje"},
        ),
        "clear": "/relatorio-avaliacao-motorista",
        "current": _relatorio_build_url("/relatorio-avaliacao-motorista", {**paged_params, "view": ("" if view == "todos" else view)}),
        "export": _relatorio_build_url(
            "/relatorio-avaliacao-motorista/export.csv",
            {**base_params, "view": ("" if view == "todos" else view)},
        ),
        "print": _relatorio_build_url(
            "/relatorio-avaliacao-motorista/impressao",
            {"date": date_str, "driver_id": selected_driver_ids or []},
        ),
    }
    return links


def _build_relatorio_page_fallback(
    session: Session,
    date_str: str,
    selected_driver_ids: Optional[List[int]],
    q: str,
    view: str,
    status_filter: str,
    checklist_filter: str,
    page: int,
    per_page: int,
    load_error: Optional[str] = None,
) -> dict:
    driver_options = _list_relatorio_driver_options(session, selected_driver_ids)
    selected_map = {int(emp.id): emp for emp in driver_options if getattr(emp, "id", None)}
    selected_names = [
        selected_map[driver_id].name
        for driver_id in (selected_driver_ids or [])
        if driver_id in selected_map and getattr(selected_map[driver_id], "name", None)
    ]
    return {
        "date": date_str,
        "date_fmt": _fmt_br_data(date_str),
        "today_str": _coerce_relatorio_date(None),
        "filters": {
            "q": q,
            "status": status_filter,
            "checklist": checklist_filter,
            "page": 1,
            "per_page": per_page,
        },
        "view": view,
        "rows": [],
        "rows_all_filtered": [],
        "has_any_rows": False,
        "has_filtered_rows": False,
        "kpi": {
            "total": 0,
            "concluidos": 0,
            "criticos": 0,
            "pendentes": 0,
            "sem_checklist": 0,
        },
        "links": _make_relatorio_links(
            date_str=date_str,
            selected_driver_ids=selected_driver_ids,
            q=q,
            status_filter=status_filter,
            checklist_filter=checklist_filter,
            per_page=per_page,
            page=page,
            view=view,
        ),
        "pagination": {
            "page": 1,
            "per_page": per_page,
            "total_count": 0,
            "total_pages": 1,
            "page_start": 0,
            "page_end": 0,
            "has_prev": False,
            "has_next": False,
            "prev_href": "#",
            "next_href": "#",
        },
        "motoristas": driver_options,
        "selected_driver_ids": selected_driver_ids or [],
        "selected_driver_names": selected_names[:6],
        "selected_driver_names_more": max(0, len(selected_names) - 6),
        "load_error": load_error,
    }


def _build_relatorio_avaliacao_page_data(
    session: Session,
    date_str: str,
    selected_driver_ids: Optional[List[int]],
    q: str,
    view: str,
    status_filter: str,
    checklist_filter: str,
    page: int,
    per_page: int,
) -> dict:
    base_data = _build_relatorio_avaliacao_motorista(session, date_str, selected_driver_ids)
    rows_all = [_build_relatorio_summary_row(report, date_str) for report in base_data.get("reports") or []]
    rows_all.sort(
        key=lambda row: (
            _RELATORIO_DRIVER_STATUS_ORDER.get(row["status_code"], 99),
            -float(row.get("devolucao_pct") or 0.0),
            (row.get("motorista") or "").casefold(),
        )
    )

    q_norm = _norm_text(q)
    rows_scoped = rows_all
    if q_norm:
        rows_scoped = [row for row in rows_all if q_norm in row.get("search_blob", "")]

    kpi = {
        "total": len(rows_scoped),
        "concluidos": sum(1 for row in rows_scoped if row["status_code"] == "concluido"),
        "criticos": sum(1 for row in rows_scoped if row["status_code"] == "critico"),
        "pendentes": sum(1 for row in rows_scoped if row["status_code"] == "pendente"),
        "sem_checklist": sum(1 for row in rows_scoped if not row["has_checklist"]),
    }

    filtered_rows = list(rows_scoped)
    if status_filter:
        filtered_rows = [row for row in filtered_rows if row["status_code"] == status_filter]
    if checklist_filter == "com":
        filtered_rows = [row for row in filtered_rows if row["has_checklist"]]
    elif checklist_filter == "sem":
        filtered_rows = [row for row in filtered_rows if not row["has_checklist"]]

    if view == "pendentes":
        filtered_rows = [row for row in filtered_rows if row["status_code"] == "pendente"]
    elif view == "concluidos":
        filtered_rows = [row for row in filtered_rows if row["status_code"] == "concluido"]
    elif view == "criticos":
        filtered_rows = [row for row in filtered_rows if row["status_code"] == "critico"]

    total_count = len(filtered_rows)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    current_page = max(1, min(page, total_pages))
    start_idx = (current_page - 1) * per_page
    end_idx = start_idx + per_page
    rows_page = filtered_rows[start_idx:end_idx]

    driver_options = _list_relatorio_driver_options(session, selected_driver_ids)
    selected_map = {int(emp.id): emp for emp in driver_options if getattr(emp, "id", None)}
    selected_names = [
        selected_map[driver_id].name
        for driver_id in (selected_driver_ids or [])
        if driver_id in selected_map and getattr(selected_map[driver_id], "name", None)
    ]

    links = _make_relatorio_links(
        date_str=date_str,
        selected_driver_ids=selected_driver_ids,
        q=q,
        status_filter=status_filter,
        checklist_filter=checklist_filter,
        per_page=per_page,
        page=current_page,
        view=view,
    )

    def _page_href(target_page: int) -> str:
        return _relatorio_build_url(
            "/relatorio-avaliacao-motorista",
            {
                "date": date_str,
                "driver_id": selected_driver_ids or [],
                "q": q,
                "status": status_filter,
                "checklist": checklist_filter,
                "per_page": per_page,
                "page": target_page,
                "view": ("" if view == "todos" else view),
            },
        )

    page_start = (start_idx + 1) if total_count else 0
    page_end = min(end_idx, total_count) if total_count else 0

    return {
        "date": date_str,
        "date_fmt": _fmt_br_data(date_str),
        "today_str": _coerce_relatorio_date(None),
        "filters": {
            "q": q,
            "status": status_filter,
            "checklist": checklist_filter,
            "page": current_page,
            "per_page": per_page,
        },
        "view": view,
        "rows": rows_page,
        "rows_all_filtered": filtered_rows,
        "has_any_rows": bool(rows_all),
        "has_filtered_rows": bool(filtered_rows),
        "kpi": kpi,
        "links": links,
        "pagination": {
            "page": current_page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "page_start": page_start,
            "page_end": page_end,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
            "prev_href": _page_href(current_page - 1) if current_page > 1 else "#",
            "next_href": _page_href(current_page + 1) if current_page < total_pages else "#",
        },
        "motoristas": driver_options,
        "selected_driver_ids": selected_driver_ids or [],
        "selected_driver_names": selected_names[:6],
        "selected_driver_names_more": max(0, len(selected_names) - 6),
        "load_error": None,
    }


def _build_relatorio_detail_payload(report: dict, date_str: str) -> dict:
    status_data = _relatorio_driver_status(report)
    top_time = []
    for item in report.get("top5_tempo") or []:
        top_time.append(
            {
                "cliente": item.get("cliente") or "-",
                "tipo": item.get("tipo") or "-",
                "duracao": item.get("duracao_fmt") or "—",
            }
        )

    clients = []
    for item in report.get("clientes_resumo") or []:
        clients.append(
            {
                "cliente": item.get("cliente") or "-",
                "tipos": item.get("tipos") or "-",
                "paradas": int(item.get("paradas") or 0),
                "duracao": item.get("duracao_total_fmt") or "—",
                "janela": f"{item.get('hora_primeira') or '--:--'} -> {item.get('hora_ultima') or '--:--'}",
                "valor": _fmt_br_moeda(item.get("valor_total") or 0.0),
            }
        )

    stops = []
    for item in report.get("paradas_ordenadas") or []:
        stops.append(
            {
                "cliente": item.get("cliente") or "-",
                "tipo": item.get("tipo") or "-",
                "inicio": item.get("hora_inicio") or "--:--",
                "fim": item.get("hora_fim") or "--:--",
                "duracao": item.get("duracao_fmt") or "—",
                "kg": f"{_fmt_br_1(item.get('kg') or 0.0)} kg",
                "valor": _fmt_br_moeda(item.get("valor") or 0.0),
            }
        )

    driver_id = int(report.get("driver_id") or 0)
    km_total = report.get("km_total")
    return {
        "driver_id": driver_id,
        "date": date_str,
        "date_fmt": _fmt_br_data(date_str),
        "motorista": report.get("motorista") or f"Motorista #{driver_id}",
        "ajudantes": report.get("ajudantes") or [],
        "placa": report.get("placa") or "-",
        "modelo": report.get("modelo") or "-",
        "turnos_label": " / ".join(report.get("turnos") or []) or "-",
        "hora_inicio": report.get("hora_inicio") or "--:--",
        "hora_fim": report.get("hora_fim") or "--:--",
        "tempo_operando": report.get("tempo_operando_fmt") or "—",
        "km_inicial": (_fmt_br_1(report.get("km_inicial")) if report.get("km_inicial") is not None else "—"),
        "km_final": (_fmt_br_1(report.get("km_final")) if report.get("km_final") is not None else "—"),
        "km_total": (f"{_fmt_br_1(km_total)} km" if km_total is not None else "—"),
        "saiu_valor": _fmt_br_moeda(report.get("saiu_valor") or 0.0),
        "entregue_valor": _fmt_br_moeda(report.get("entregue_valor") or 0.0),
        "devolucao_valor": _fmt_br_moeda(report.get("devolucao_valor") or 0.0),
        "devolucao_pct": f"{_fmt_br_2(report.get('devolucao_pct') or 0.0)}%",
        "meta_pct": f"{_fmt_br_2(report.get('meta_pct') or 0.0)}%",
        "checklist_label": ("Checklist enviado" if report.get("fez_checklist_caminhao") else "Checklist pendente"),
        "checklist_badge": ("ok" if report.get("fez_checklist_caminhao") else "critical"),
        "status_label": status_data["label"],
        "status_badge": status_data["badge"],
        "status_reasons": status_data["reasons"],
        "total_clientes": int(report.get("total_clientes") or 0),
        "total_paradas": int(report.get("total_paradas") or 0),
        "top_time": top_time,
        "clients": clients,
        "stops": stops,
        "print_href": _relatorio_build_url(
            "/relatorio-avaliacao-motorista/impressao",
            {"date": date_str, "driver_id": [driver_id]},
        ),
    }


@router.get("/relatorio-avaliacao-motorista", response_class=HTMLResponse)
async def relatorio_avaliacao_motorista_page(
    request: Request,
    date: Optional[str] = None,
    q: str = "",
    view: str = "todos",
    status: str = "",
    checklist: str = "",
    page: int = 1,
    per_page: int = 10,
    driver_id: Optional[List[str]] = Query(None, alias="driver_id"),
    session: Session = Depends(get_session),
):
    """Pagina operacional do relatorio de avaliacao diaria do motorista."""
    view_norm = _normalize_relatorio_view(view)
    date_str = _coerce_relatorio_date(date)
    if view_norm == "hoje":
        date_str = _coerce_relatorio_date(None)
    q_value = (q or "").strip()
    parsed_ids = _parse_relatorio_driver_ids(driver_id)
    status_filter = _normalize_relatorio_status(status)
    checklist_filter = _normalize_relatorio_checklist(checklist)
    current_page = max(1, int(page or 1))
    page_size = _coerce_relatorio_page_size(per_page)

    try:
        data = _build_relatorio_avaliacao_page_data(
            session=session,
            date_str=date_str,
            selected_driver_ids=parsed_ids,
            q=q_value,
            view=view_norm,
            status_filter=status_filter,
            checklist_filter=checklist_filter,
            page=current_page,
            per_page=page_size,
        )
        status_code = 200
    except Exception:
        data = _build_relatorio_page_fallback(
            session=session,
            date_str=date_str,
            selected_driver_ids=parsed_ids,
            q=q_value,
            view=view_norm,
            status_filter=status_filter,
            checklist_filter=checklist_filter,
            page=current_page,
            per_page=page_size,
            load_error="Nao foi possivel carregar a avaliacao agora. Tente novamente com outro filtro ou recarregue a pagina.",
        )
        status_code = 500

    return templates.TemplateResponse(
        "relatorio_avaliacao_motorista_operacional.html",
        {
            "request": request,
            **data,
            "message": request.query_params.get("message"),
            "level": request.query_params.get("level") or "info",
        },
        status_code=status_code,
    )


@router.get("/relatorio-avaliacao-motorista/impressao", response_class=HTMLResponse)
async def relatorio_avaliacao_motorista_print_page(
    request: Request,
    date: Optional[str] = None,
    driver_id: Optional[List[str]] = Query(None, alias="driver_id"),
    session: Session = Depends(get_session),
):
    """Mantem a visao imprimivel do relatorio por motorista."""
    date_str = _coerce_relatorio_date(date)
    parsed_ids = _parse_relatorio_driver_ids(driver_id)
    data = _build_relatorio_avaliacao_motorista(session, date_str, parsed_ids)
    data["motoristas"] = _list_relatorio_driver_options(session, parsed_ids)
    return templates.TemplateResponse("relatorio_avaliacao_motorista.html", {"request": request, **data})


@router.get("/api/relatorio-avaliacao-motorista/detail", response_class=JSONResponse)
async def relatorio_avaliacao_motorista_detail_api(
    date: Optional[str] = None,
    driver_id: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """Detalhe lazy do motorista para modal operacional."""
    date_str = _coerce_relatorio_date(date)
    parsed_ids = _parse_relatorio_driver_ids(driver_id)
    if not parsed_ids:
        return JSONResponse({"error": "Motorista invalido."}, status_code=400)

    data = _build_relatorio_avaliacao_motorista(session, date_str, parsed_ids)
    report = next(
        (item for item in data.get("reports") or [] if int(item.get("driver_id") or 0) == int(parsed_ids[0])),
        None,
    )
    if not report:
        return JSONResponse({"error": "Nenhum relatorio encontrado para este motorista."}, status_code=404)

    return JSONResponse(_build_relatorio_detail_payload(report, date_str))


@router.get("/relatorio-avaliacao-motorista/export.csv")
async def relatorio_avaliacao_motorista_export_csv(
    date: Optional[str] = None,
    q: str = "",
    view: str = "todos",
    status: str = "",
    checklist: str = "",
    per_page: int = 5000,
    driver_id: Optional[List[str]] = Query(None, alias="driver_id"),
    session: Session = Depends(get_session),
):
    """Exporta a visao filtrada da avaliacao operacional."""
    view_norm = _normalize_relatorio_view(view)
    date_str = _coerce_relatorio_date(date)
    if view_norm == "hoje":
        date_str = _coerce_relatorio_date(None)

    data = _build_relatorio_avaliacao_page_data(
        session=session,
        date_str=date_str,
        selected_driver_ids=_parse_relatorio_driver_ids(driver_id),
        q=(q or "").strip(),
        view=view_norm,
        status_filter=_normalize_relatorio_status(status),
        checklist_filter=_normalize_relatorio_checklist(checklist),
        page=1,
        per_page=_coerce_relatorio_page_size(per_page),
    )

    rows = data.get("rows_all_filtered") or []
    stamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M")
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        [
            "data",
            "motorista",
            "turnos",
            "ajudantes",
            "placa",
            "modelo",
            "clientes",
            "paradas",
            "inicio",
            "fim",
            "tempo_operando",
            "km_total",
            "valor_expedido",
            "valor_entregue",
            "valor_devolvido",
            "pct_devolucao",
            "meta_pct",
            "checklist",
            "status",
            "observacao",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _fmt_br_data(row.get("date")),
                row.get("motorista") or "",
                row.get("turnos_label") or "",
                row.get("ajudantes_label") or "",
                row.get("placa") or "",
                row.get("modelo") or "",
                row.get("total_clientes") or 0,
                row.get("total_paradas") or 0,
                row.get("hora_inicio") or "",
                row.get("hora_fim") or "",
                row.get("tempo_operando_fmt") or "",
                row.get("km_total_fmt") or "",
                row.get("saiu_valor_fmt") or "",
                row.get("entregue_valor_fmt") or "",
                row.get("devolucao_valor_fmt") or "",
                row.get("devolucao_pct_fmt") or "",
                row.get("meta_pct_fmt") or "",
                row.get("checklist_label") or "",
                row.get("status_label") or "",
                row.get("status_reason") or "",
            ]
        )
    buffer = io.BytesIO(out.getvalue().encode("utf-8-sig"))
    return StreamingResponse(
        buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=avaliacao_motoristas_{stamp}.csv"},
    )


def _build_bi_vendedor_dataset(
    session: Session,
    date_from: Optional[str],
    date_to: Optional[str],
    vendedor_id: Optional[int] = None,
) -> dict:
    """Consolida vendas e devoluções por vendedor para ranking comercial."""
    delivery_dataset = _build_bi_delivery_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift="Todos",
        driver_id=None,
        plate="Todos",
        status="Todos",
    )

    route_rows = [
        r for r in (delivery_dataset.get("all_route_rows") or [])
        if str(r.get("source") or "").upper() == "ROTA"
    ]
    financial_rows = list(delivery_dataset.get("all_financial_rows") or [])

    client_ids = sorted({
        int(r.get("client_id"))
        for r in (route_rows + financial_rows)
        if r.get("client_id") is not None
    })
    clients = (
        session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all()
        if client_ids else []
    )
    client_map = {c.id: c for c in clients}

    seller_ids = sorted({
        int(c.vendedor_id)
        for c in clients
        if getattr(c, "vendedor_id", None) is not None
    })
    sellers = (
        session.exec(select(models.Employee).where(models.Employee.id.in_(seller_ids))).all()
        if seller_ids else []
    )
    seller_map = {s.id: s for s in sellers}

    def _seller_for_client(client_id: Optional[int]) -> tuple[Optional[int], str]:
        if client_id is None:
            return None, "Sem vendedor"
        cli = client_map.get(int(client_id))
        sid = getattr(cli, "vendedor_id", None) if cli else None
        if sid is None:
            return None, "Sem vendedor"
        seller = seller_map.get(int(sid))
        if seller:
            return int(sid), str(seller.name or f"Vendedor #{sid}")
        return int(sid), f"Vendedor #{sid}"

    seller_acc: dict[int, dict] = {}
    sem_vendedor_key = -1

    def _ensure_bucket(sid: Optional[int], name: str) -> dict:
        key = int(sid) if sid is not None else sem_vendedor_key
        if key not in seller_acc:
            seller_acc[key] = {
                "vendedor_id": None if sid is None else int(sid),
                "vendedor": name,
                "clientes_set": set(),
                "pedidos_total": 0,
                "pedidos_concluidos": 0,
                "vendas_planejadas": 0.0,
                "vendas_realizadas": 0.0,
                "devolucoes_qtd": 0,
                "devolucoes_valor": 0.0,
            }
        return seller_acc[key]

    for row in route_rows:
        sid, sname = _seller_for_client(row.get("client_id"))
        bucket = _ensure_bucket(sid, sname)
        cid = row.get("client_id")
        if cid is not None:
            bucket["clientes_set"].add(int(cid))
        bucket["pedidos_total"] += 1
        status = str(row.get("status") or "").lower()
        if status in ("entregue", "devolucao"):
            bucket["pedidos_concluidos"] += 1
        bucket["vendas_planejadas"] += float(row.get("planned_value") or 0.0)
        bucket["vendas_realizadas"] += float(row.get("delivered_value") or 0.0)

    for row in financial_rows:
        sid, sname = _seller_for_client(row.get("client_id"))
        bucket = _ensure_bucket(sid, sname)
        cid = row.get("client_id")
        if cid is not None:
            bucket["clientes_set"].add(int(cid))
        val = float(row.get("value") or row.get("returned_value") or 0.0)
        bucket["devolucoes_qtd"] += 1
        bucket["devolucoes_valor"] += val

    rows = []
    for bucket in seller_acc.values():
        base_valor = float(bucket["vendas_realizadas"] or 0.0) + float(bucket["devolucoes_valor"] or 0.0)
        taxa_devol = _safe_pct(bucket["devolucoes_valor"], base_valor)
        ticket_medio = (
            float(bucket["vendas_realizadas"]) / float(bucket["pedidos_concluidos"])
            if bucket["pedidos_concluidos"] > 0 else 0.0
        )
        rows.append({
            "vendedor_id": bucket["vendedor_id"],
            "vendedor": bucket["vendedor"],
            "clientes_ativos": len(bucket["clientes_set"]),
            "pedidos_total": int(bucket["pedidos_total"]),
            "pedidos_concluidos": int(bucket["pedidos_concluidos"]),
            "vendas_planejadas": round(float(bucket["vendas_planejadas"]), 2),
            "vendas_realizadas": round(float(bucket["vendas_realizadas"]), 2),
            "devolucoes_qtd": int(bucket["devolucoes_qtd"]),
            "devolucoes_valor": round(float(bucket["devolucoes_valor"]), 2),
            "taxa_devolucao_valor": round(float(taxa_devol), 2),
            "ticket_medio": round(float(ticket_medio), 2),
        })

    all_rows = sorted(rows, key=lambda x: (-x["vendas_realizadas"], -x["devolucoes_valor"], x["vendedor"]))
    filtered_rows = [
        r for r in all_rows
        if vendedor_id is None or r.get("vendedor_id") == vendedor_id
    ]

    base_rows = filtered_rows if filtered_rows else all_rows
    top_vendas = sorted(base_rows, key=lambda x: x["vendas_realizadas"], reverse=True)[:10]
    top_devolucoes = sorted(base_rows, key=lambda x: x["devolucoes_valor"], reverse=True)[:10]
    top_taxa = [
        r for r in sorted(base_rows, key=lambda x: x["taxa_devolucao_valor"])
        if (r.get("vendas_realizadas") or 0) > 0
    ][:10]

    maior_vendas = top_vendas[0] if top_vendas else None
    maior_devolucao = top_devolucoes[0] if top_devolucoes else None
    menor_taxa = top_taxa[0] if top_taxa else None
    soma_vendas = round(sum(float(r["vendas_realizadas"]) for r in base_rows), 2)
    soma_devolucoes = round(sum(float(r["devolucoes_valor"]) for r in base_rows), 2)
    taxa_geral = round(_safe_pct(soma_devolucoes, soma_vendas + soma_devolucoes), 2)

    filters_payload = {
        "date_from": delivery_dataset.get("filters", {}).get("date_from"),
        "date_to": delivery_dataset.get("filters", {}).get("date_to"),
        "vendedor_id": vendedor_id,
    }
    filters_query = urlencode({
        "date_from": filters_payload["date_from"] or "",
        "date_to": filters_payload["date_to"] or "",
        "vendedor_id": vendedor_id if vendedor_id is not None else "",
    })

    chart_payload = {
        "top_vendas": top_vendas,
        "top_devolucoes": top_devolucoes,
        "top_taxa": top_taxa,
    }

    sellers_filter = sorted(
        [{"id": r.get("vendedor_id"), "name": r.get("vendedor")} for r in all_rows if r.get("vendedor_id") is not None],
        key=lambda x: str(x["name"] or ""),
    )

    return {
        "filters": filters_payload,
        "filters_query": filters_query,
        "sellers_filter": sellers_filter,
        "rows": base_rows,
        "kpis": {
            "vendedores_ativos": len(base_rows),
            "vendas_realizadas": soma_vendas,
            "devolucoes_valor": soma_devolucoes,
            "taxa_devolucao_geral": taxa_geral,
        },
        "maior_vendas": maior_vendas,
        "maior_devolucao": maior_devolucao,
        "menor_taxa": menor_taxa,
        "chart_payload_json": json.dumps(chart_payload, ensure_ascii=False),
    }


@router.get("/bi/vendedor", response_class=HTMLResponse)
async def bi_vendedor_page(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    vendedor_id: Optional[str] = None,
    session: Session = Depends(get_session),
):
    parsed_vendedor_id: Optional[int] = int(vendedor_id) if (vendedor_id or "").strip().isdigit() else None
    dataset = _build_bi_vendedor_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        vendedor_id=parsed_vendedor_id,
    )
    return templates.TemplateResponse("bi_vendedor.html", {"request": request, **dataset})


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


@router.get("/bi/clientes", response_class=HTMLResponse)
async def bi_clientes_page(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    shift: str = "Todos",
    driver_id: Optional[str] = None,
    plate: str = "Todos",
    status: str = "Todos",
    client_id: Optional[str] = None,
    city: str = "Todos",
    priority: str = "Todos",
    client_status: str = "Todos",
    segmentos: Optional[list[str]] = Query(default=None),
    returns_filter: str = "Todos",
    detail_client_id: Optional[str] = None,
    client_scope: Optional[str] = None,
    session: Session = Depends(get_session),
):
    parsed_driver_id: Optional[int] = int(driver_id) if (driver_id or "").strip().isdigit() else None
    parsed_client_id: Optional[int] = int(client_id) if (client_id or "").strip().isdigit() else None
    parsed_detail = (detail_client_id or "").strip()
    if parsed_detail.startswith("-") and parsed_detail[1:].isdigit():
        parsed_detail_client_id = int(parsed_detail)
    elif parsed_detail.isdigit():
        parsed_detail_client_id = int(parsed_detail)
    else:
        parsed_detail_client_id = None
    dataset = _build_bi_clientes_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift=shift,
        driver_id=parsed_driver_id,
        plate=plate,
        status=status,
        client_id=parsed_client_id,
        city=city,
        priority=priority,
        client_status=client_status,
        segmentos=segmentos,
        returns_filter=returns_filter,
        detail_client_id=parsed_detail_client_id,
        client_filter_scope=(client_scope or "solo").strip().lower(),
    )
    return templates.TemplateResponse("bi_clientes.html", {"request": request, **dataset})


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
        c.drawString(
            30,
            y,
            f"Planejadas: {dataset['kpis']['planned_stops']} | Entregues: {dataset['kpis']['delivered_stops']} | "
            f"SLA conclusao: {_fmt_br_1(dataset['kpis']['sla_finish'])}% | Tempo medio: {dataset['kpis']['avg_duration_m']} min",
        )
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


@router.get("/bi/clientes/export")
async def bi_clientes_export(
    format: str = "csv",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    shift: str = "Todos",
    driver_id: Optional[str] = None,
    plate: str = "Todos",
    status: str = "Todos",
    client_id: Optional[str] = None,
    city: str = "Todos",
    priority: str = "Todos",
    client_status: str = "Todos",
    segmentos: Optional[list[str]] = Query(default=None),
    returns_filter: str = "Todos",
    client_scope: Optional[str] = None,
    session: Session = Depends(get_session),
):
    parsed_driver_id: Optional[int] = int(driver_id) if (driver_id or "").strip().isdigit() else None
    parsed_client_id: Optional[int] = int(client_id) if (client_id or "").strip().isdigit() else None
    dataset = _build_bi_clientes_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift=shift,
        driver_id=parsed_driver_id,
        plate=plate,
        status=status,
        client_id=parsed_client_id,
        city=city,
        priority=priority,
        client_status=client_status,
        segmentos=segmentos,
        returns_filter=returns_filter,
        client_filter_scope=(client_scope or "solo").strip().lower(),
    )
    rows = dataset["all_client_rows"]
    stamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M")
    fmt = (format or "csv").strip().lower()

    def _client_row_data_br(row: dict) -> list:
        return [
            row.get("client_id") or "",
            row.get("client_name") or "",
            row.get("city") or "",
            row.get("bairro") or "",
            row.get("segmento") or "",
            row.get("prioridade") or "",
            row.get("status_operacional") or "",
            row.get("visits") or 0,
            row.get("weekly_peak_visits") or 0,
            _fmt_br_1(row.get("total_duration_m") or 0),
            _fmt_br_1(row.get("avg_duration_m") or 0),
            row.get("returned_occurrences") or 0,
            _fmt_br_2(row.get("planned_value") or 0),
            _fmt_br_2(row.get("returned_value") or 0),
            _fmt_br_1(row.get("return_rate_qtd") or 0),
            _fmt_br_1(row.get("return_rate_value") or 0),
            row.get("reopen_count") or 0,
            row.get("top_driver_name") or "-",
            row.get("top_motivo_name") or "-",
            row.get("risk_label") or "-",
            row.get("risk_score") or 0,
        ]

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(
            [
                "cliente_id",
                "cliente",
                "cidade",
                "bairro",
                "segmento",
                "prioridade",
                "status_operacional",
                "visitas",
                "pico_semanal",
                "tempo_total_min",
                "tempo_medio_min",
                "devolucoes",
                "valor_planejado",
                "valor_devolvido",
                "devolucao_pct_qtd",
                "devolucao_pct_valor",
                "reaberturas",
                "motorista_principal",
                "motivo_principal",
                "risco",
                "score_risco",
            ]
        )
        for row in rows:
            writer.writerow(_client_row_data_br(row))
        buf = io.BytesIO(out.getvalue().encode("utf-8-sig"))
        return StreamingResponse(
            buf,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=bi_clientes_{stamp}.csv"},
        )

    if fmt == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "BI Clientes"
        sheet.append(
            [
                "Cliente ID",
                "Cliente",
                "Cidade",
                "Bairro",
                "Segmento",
                "Prioridade",
                "Status Operacional",
                "Visitas",
                "Pico Semanal",
                "Tempo Total (min)",
                "Tempo Medio (min)",
                "Devolucoes",
                "Valor Planejado",
                "Valor Devolvido",
                "Devolucao % Qtd",
                "Devolucao % Valor",
                "Reaberturas",
                "Motorista Principal",
                "Motivo Principal",
                "Risco",
                "Score de Risco",
            ]
        )
        for row in rows:
            sheet.append(_client_row_data_br(row))
        xbuf = io.BytesIO()
        workbook.save(xbuf)
        xbuf.seek(0)
        return StreamingResponse(
            xbuf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=bi_clientes_{stamp}.xlsx"},
        )

    return JSONResponse({"error": "Formato invalido. Use csv ou xlsx."}, status_code=400)


# ---------------------------------------------------------------------------
# BI DEVOLUÇÕES — Mega BI Page
# ---------------------------------------------------------------------------

def _build_bi_devolucoes_dataset(
    session: Session,
    date_from: Optional[str],
    date_to: Optional[str],
    responsabilidade_id: Optional[int] = None,
    motivo_id: Optional[int] = None,
    motorista_id: Optional[int] = None,
    vendedor_id: Optional[int] = None,
    client_id: Optional[int] = None,
    client_filter_scope: str = "solo",
    valor_faixa: Optional[str] = None,
    somente_criticas: bool = False,
    somente_acima_meta: bool = False,
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

    period_start, period_end, window_start, window_end = _competence_period_window(date_i, date_f)
    date_str_i = window_start
    date_str_f = window_end

    # --- carregar cadastros ---
    motivos_all = session.exec(select(models.DevolucaoMotivo)).all()
    resps_all = session.exec(select(models.DevolucaoResponsabilidade)).all()
    mot_map = {m.id: m for m in motivos_all}
    rsp_map = {r.id: r for r in resps_all}

    # --- query principal (janela alargada; corte real = competência em [period_start, period_end]) ---
    q = (
        select(models.Devolucao)
        .where(
            or_(
                and_(
                    models.Devolucao.data_romaneio >= window_start,
                    models.Devolucao.data_romaneio <= window_end,
                ),
                and_(
                    models.Devolucao.data_entrega >= window_start,
                    models.Devolucao.data_entrega <= window_end,
                ),
            )
        )
    )
    if responsabilidade_id:
        q = q.where(models.Devolucao.responsabilidade_id == responsabilidade_id)
    if motivo_id:
        q = q.where(models.Devolucao.motivo_id == motivo_id)
    if motorista_id:
        q = q.where(models.Devolucao.motorista_id == motorista_id)
    if vendedor_id:
        q = q.where(models.Devolucao.vendedor_id == vendedor_id)
    cfs = (client_filter_scope or "solo").strip().lower()
    if cfs not in ("solo", "group"):
        cfs = "solo"
    client_ids_dev: Optional[list] = None
    group_filter_note_dev: Optional[str] = None
    if client_id:
        if cfs == "group":
            c = session.get(models.Client, int(client_id))
            if c and getattr(c, "client_group_id", None):
                client_ids_dev = [int(x) for x in session.exec(select(models.Client.id).where(models.Client.client_group_id == c.client_group_id)).all() if x is not None]
            if not client_ids_dev:
                client_ids_dev = [int(client_id)]
            elif len(client_ids_dev) == 1:
                group_filter_note_dev = "Só há uma loja neste grupo."
        else:
            client_ids_dev = [int(client_id)]
    if client_ids_dev:
        if len(client_ids_dev) == 1:
            q = q.where(models.Devolucao.client_id == client_ids_dev[0])
        else:
            q = q.where(models.Devolucao.client_id.in_(client_ids_dev))

    devs_raw = session.exec(q.order_by(models.Devolucao.data_romaneio.desc())).all()
    # Alinhar ao consolidado / KPI mensal (main._kpi_devolucao_mes_romaneio_calendario): não somar duplicatas.
    devs_raw = [d for d in devs_raw if not getattr(d, "duplicate_of_id", None)]

    def _dev_op_date_raw(d: models.Devolucao) -> str:
        return str(getattr(d, "data_entrega", None) or getattr(d, "data_romaneio", None) or "").strip()[:10]

    devs_c = [d for d in devs_raw if _in_competence_period(_dev_op_date_raw(d), period_start, period_end)]
    devs_c.sort(
        key=lambda x: (_competence_date_or_self(_dev_op_date_raw(x)), x.data_romaneio or ""),
        reverse=True,
    )

    def _valor_faixa_ok(d: models.Devolucao, faixa: str) -> bool:
        v = float(d.valor or 0)
        f = (faixa or "all").strip().lower()
        if f in ("", "all", "todos"):
            return True
        if f == "ate100":
            return v <= 100
        if f in ("100_300", "v100_300"):
            return 100 < v <= 300
        if f in ("300_800", "v300_800"):
            return 300 < v <= 800
        if f in ("acima800", "v800"):
            return v > 800
        return True

    devs_work: List[models.Devolucao] = list(devs_c)
    devs_work = [d for d in devs_work if _valor_faixa_ok(d, valor_faixa or "all")]
    if somente_criticas:
        devs_work = [
            d
            for d in devs_work
            if float(d.valor or 0) >= 800.0 or (str(d.acima_300 or "").upper() == "SIM")
        ]

    devs: List[models.Devolucao] = list(devs_work)

    def _parse_route_helper_ids(helpers_json: Optional[str]) -> List[int]:
        """Parse delivery_helpers_json da rota para lista de employee_id."""
        if not helpers_json:
            return []
        try:
            data = json.loads(helpers_json) if isinstance(helpers_json, str) else helpers_json
            if not isinstance(data, list):
                return []
            return [int(x) for x in data if x is not None and str(x).strip().isdigit()]
        except Exception:
            return []

    def _parse_helpers_to_ids(helpers_json: Optional[str], emp_by_name: dict) -> List[int]:
        """Parse JSON (ids ou nomes) para lista de employee_id. emp_by_name: nome_lower -> id."""
        if not helpers_json or not emp_by_name:
            return []
        try:
            data = json.loads(helpers_json) if isinstance(helpers_json, str) else helpers_json
            if not isinstance(data, list):
                return []
            ids = []
            for h in data:
                if h is None:
                    continue
                if isinstance(h, int) and h > 0:
                    ids.append(h)
                elif isinstance(h, str) and str(h).strip().isdigit():
                    ids.append(int(h.strip()))
                elif isinstance(h, str) and (h or "").strip():
                    eid = emp_by_name.get((h or "").strip().lower())
                    if eid and eid not in ids:
                        ids.append(eid)
            return ids
        except Exception:
            return []

    # Mapa nome -> id para resolver ajudantes por nome (Route/Session podem enviar nomes)
    all_employees = list(session.exec(select(models.Employee)).all())
    emp_by_name: dict = {e.name.strip().lower(): e.id for e in all_employees if e and getattr(e, "name", None) and getattr(e, "id", None)}

    # Ajudantes das rotas vinculadas (para devoluções sem ajudante_id preenchido)
    route_ids = sorted({d.route_id for d in devs if getattr(d, "route_id", None)})
    route_helpers: dict = {}  # route_id -> [emp_id, ...]
    if route_ids:
        try:
            routes_linked = session.exec(
                select(models.Route).where(models.Route.id.in_(route_ids))
            ).all()
            for r in routes_linked:
                raw = getattr(r, "delivery_helpers_json", None)
                ids = _parse_route_helper_ids(raw) or _parse_helpers_to_ids(raw, emp_by_name)
                if ids:
                    route_helpers[r.id] = ids
        except Exception:
            pass

    # Fallback: ajudantes por (client_id, motorista_id, data) quando devolução não tem route_id
    # Busca rotas de entrega no período com helpers e monta lookup para casar com devoluções
    route_by_client_driver_date: dict = {}  # (client_id, employee_id, date_str) -> [helper_ids]
    try:
        routes_in_range = session.exec(
            select(models.Route)
            .where(models.Route.date >= date_str_i)
            .where(models.Route.date <= date_str_f)
            .where(models.Route.client_id.is_not(None))
            .where(models.Route.employee_id.is_not(None))
        ).all()
        for r in routes_in_range:
            raw = getattr(r, "delivery_helpers_json", None)
            ids = _parse_route_helper_ids(raw) or _parse_helpers_to_ids(raw, emp_by_name)
            if ids and r.client_id and r.employee_id:
                key = (r.client_id, r.employee_id, str(r.date)[:10])
                if key not in route_by_client_driver_date:
                    route_by_client_driver_date[key] = ids
    except Exception:
        pass

    # Fallback 2: ajudantes da sessão (date, motorista_id) quando rota não tem delivery_helpers_json
    session_helpers_by_driver_date: dict = {}  # (date_str, employee_id) -> [helper_ids]
    try:
        sessions_in_range = session.exec(
            select(models.DeliverySession)
            .where(models.DeliverySession.date >= date_str_i)
            .where(models.DeliverySession.date <= date_str_f)
        ).all()
        for ds in sessions_in_range:
            raw = getattr(ds, "helpers_json", None)
            ids = _parse_route_helper_ids(raw) or _parse_helpers_to_ids(raw, emp_by_name)
            if ids and ds.employee_id:
                key = (str(getattr(ds, "date", "") or "")[:10], ds.employee_id)
                if key not in session_helpers_by_driver_date:
                    session_helpers_by_driver_date[key] = ids
    except Exception:
        pass

    # --- mapas de lookup ---
    helper_ids_from_routes = set()
    for ids in route_helpers.values():
        helper_ids_from_routes.update(ids)
    for ids in route_by_client_driver_date.values():
        helper_ids_from_routes.update(ids)
    for ids in session_helpers_by_driver_date.values():
        helper_ids_from_routes.update(ids)
    emp_ids = sorted({d.motorista_id for d in devs if d.motorista_id} |
                     {d.ajudante_id for d in devs if d.ajudante_id} |
                     {d.vendedor_id for d in devs if d.vendedor_id} |
                     helper_ids_from_routes)
    cli_ids = sorted({d.client_id for d in devs if d.client_id})
    emp_map = {e.id: e for e in (session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all() if emp_ids else [])}
    cli_map = {c.id: c for c in (session.exec(select(models.Client).where(models.Client.id.in_(cli_ids))).all() if cli_ids else [])}

    # --- filtros para a UI ---
    drivers_filter = sorted(
        [e for e in session.exec(select(models.Employee)).all()
         if any(d.motorista_id == e.id for d in devs_c)],
        key=lambda e: e.name,
    )
    clients_filter = sorted(
        [c for c in session.exec(select(models.Client)).all()
         if any(d.client_id == c.id for d in devs_c)],
        key=lambda c: c.name,
    )
    vendedores_filter = sorted(
        [e for e in session.exec(select(models.Employee)).all()
         if any(d.vendedor_id == e.id for d in devs_c)],
        key=lambda e: e.name,
    )

    # Mesmo critério da Central de Comando (dashboard TV / devolucao_mes em main.py):
    # % = paradas com status "devolucao" / paradas concluídas ("entregue" + "devolucao"), só rotas type=delivery.
    rq_base = (
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= window_start)
        .where(models.Route.date <= window_end)
    )
    if motorista_id:
        rq_base = rq_base.where(models.Route.employee_id == motorista_id)
    if client_ids_dev:
        if len(client_ids_dev) == 1:
            rq_base = rq_base.where(models.Route.client_id == client_ids_dev[0])
        else:
            rq_base = rq_base.where(models.Route.client_id.in_(client_ids_dev))
    routes_delivery_period = session.exec(rq_base).all()
    routes_delivery_period = [
        r for r in routes_delivery_period
        if _in_competence_period(getattr(r, "date", None), period_start, period_end)
    ]
    pct_devolucao_rotas = pct_devolucao_sobre_rotas_concluidas(routes_delivery_period)

    # Receita (valor_financeiro) por dia de competência — base para meta 2% diária no gráfico (não linear no tempo)
    receita_por_dia_comp: dict[str, float] = {}
    for _r_fin in routes_delivery_period:
        _comp_r = _competence_date_or_self(getattr(_r_fin, "date", None))
        if not _comp_r:
            continue
        _vf = getattr(_r_fin, "valor_financeiro", None)
        if _vf is None:
            continue
        receita_por_dia_comp[_comp_r] = receita_por_dia_comp.get(_comp_r, 0.0) + float(_vf)

    # Base financeira (referência): soma valor_financeiro das rotas de entrega no período (mesmos filtros de rota)
    valor_base_rotas = sum(float(r.valor_financeiro or 0) for r in routes_delivery_period if r.valor_financeiro is not None)
    devs_pre_acima: List[models.Devolucao] = list(devs)
    total_valor_kpi = sum(float(d.valor or 0) for d in devs_pre_acima)
    total_qtd_kpi = len(devs_pre_acima)
    pct_devolucao_financeiro: Optional[float] = (
        round(100.0 * total_valor_kpi / valor_base_rotas, 2) if valor_base_rotas > 0 else None
    )
    meta_pp = 2.0
    valor_meta_permitido: Optional[float] = (
        round(valor_base_rotas * (meta_pp / 100.0), 2) if valor_base_rotas > 0 else None
    )
    excedente_sobre_meta: Optional[float] = (
        round(max(0.0, total_valor_kpi - (valor_meta_permitido or 0.0)), 2)
        if valor_meta_permitido is not None
        else None
    )
    desvio_pp: Optional[float] = (
        round(float(pct_devolucao_financeiro) - meta_pp, 2) if pct_devolucao_financeiro is not None else None
    )
    # Mesmo eixo da TV / informativo: meta de 2% aplicada ao % sobre rotas concluídas
    desvio_rotas_pp: float = round(float(pct_devolucao_rotas or 0.0) - float(meta_pp), 1)
    situacao_meta = "desconhecido"
    pr = float(pct_devolucao_rotas or 0.0)
    n_ret_r, n_done_r = counts_devolucao_rotas_concluidas(routes_delivery_period)
    if n_done_r > 0:
        situacao_meta = "dentro" if pr <= meta_pp else "acima"
    else:
        situacao_meta = "desconhecido"
    faixa_alerta_meta = "neutral"
    if n_done_r <= 0:
        faixa_alerta_meta = "neutral"
    elif pr <= meta_pp:
        faixa_alerta_meta = "ok"
    elif pr <= 2.5:
        faixa_alerta_meta = "warn"
    else:
        faixa_alerta_meta = "danger"

    acima_meta_filter_note: Optional[str] = None
    ids_listagem: set[int] = {d.id for d in devs_pre_acima if getattr(d, "id", None)}
    if somente_acima_meta:
        if pct_devolucao_financeiro is None or pct_devolucao_financeiro <= meta_pp:
            ids_listagem = set()
            acima_meta_filter_note = (
                "Filtro «somente acima da meta» ativo: o período está dentro ou na meta financeira de 2% "
                "sobre o valor base das rotas (ou não há valor base). A lista foi esvaziada."
            )
        else:
            devs_alto = [d for d in devs_pre_acima if float(d.valor or 0) >= 300.0]
            if devs_alto:
                ids_listagem = {d.id for d in devs_alto if getattr(d, "id", None)}
            else:
                acima_meta_filter_note = "Nenhuma ocorrência ≥ R$ 300; exibindo todas as devoluções do período."
    devs = list(devs_pre_acima)
    # --- agregações (gráficos e rankings usam o período completo após faixa/críticas; lista respeita ids_listagem) ---
    total_qtd = int(total_qtd_kpi)
    total_valor = float(total_valor_kpi)

    # Cores em hexadecimal (layout claro GA; sem depender de --color-* do tema escuro)
    _RESP_HEX_DETAIL = {"MERCADO": "#dc2626", "COMERCIAL": "#d97706"}
    _resp_hex_default = "#2563eb"

    def _resp_hex(nome: str) -> str:
        n = (nome or "").upper()
        return next((v for k, v in _RESP_HEX_DETAIL.items() if k in n), _resp_hex_default)

    def _resp_tom(nome: str) -> str:
        """Classe CSS semântica para selo de responsabilidade."""
        n = (nome or "").upper()
        if "MERCADO" in n:
            return "mercado"
        if "COMERCIAL" in n:
            return "comercial"
        if "LOG" in n:
            return "logistica"
        return "outro"

    # por dia
    per_day: dict[str, dict] = {}
    # por semana (ISO)
    per_week: dict[str, dict] = {}
    # por motivo
    per_motivo: dict[str, dict] = {}
    # por responsabilidade
    per_resp: dict[str, dict] = {}
    # drill responsabilidade -> motivos (para modal ao clicar no card)
    per_resp_motivo: dict[str, dict[str, dict]] = {}
    # por cluster
    per_cluster: dict[str, dict] = {}
    # por motorista
    per_motorista: dict[str, dict] = {}
    # por vendedor
    per_vendedor: dict[str, dict] = {}
    # drill vendedor: responsabilidade e motivos por vendedor
    per_vendedor_resp: dict[str, dict[str, dict]] = {}  # vendedor_nome -> resp_nome -> { responsabilidade, qtd, valor }
    per_vendedor_motivo: dict[str, dict[str, dict]] = {}  # vendedor_nome -> motivo_nome -> { motivo, qtd, valor }
    # por cliente
    per_cliente: dict[str, dict] = {}
    # heatmap dia-da-semana (0=Seg..6=Dom) x semana ISO
    heatmap_week: dict[str, dict[int, int]] = {}  # week_label -> {weekday: count}
    # heatmap dia-da-semana x hora_do_dia (não temos hora, então dia-da-semana x dia-do-mês para enriquecer)
    heatmap_dow_dom: dict[int, dict[int, int]] = {i: {} for i in range(7)}  # dow -> {dom: count}

    DOW_LABELS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

    rows_detail: list[dict] = []

    def _classificacao_impacto_valor(v: float) -> str:
        if v <= 100:
            return "Baixo impacto"
        if v <= 300:
            return "Médio impacto"
        if v <= 800:
            return "Alto impacto"
        return "Crítico"

    def _acao_corretiva_sugerida(resp_nome: str) -> str:
        n = (resp_nome or "").upper()
        if "COMERCIAL" in n:
            return "Revisar pedido, cadastro e alinhamento com o cliente antes da expedição."
        if "LOG" in n:
            return "Auditar separação, carga e conferência na entrega."
        if "MERCADO" in n:
            return "Verificar qualidade percebida e acordo comercial de troca."
        return "Registrar causa raiz e acionar o responsável pela área."

    for d in devs_pre_acima:
        motivo = mot_map.get(d.motivo_id)
        resp = rsp_map.get(d.responsabilidade_id)
        cli = cli_map.get(d.client_id)
        motorista = emp_map.get(d.motorista_id)
        ajudante = emp_map.get(d.ajudante_id) if d.ajudante_id else None
        vendedor = emp_map.get(d.vendedor_id) if d.vendedor_id else None

        motivo_nome = motivo.nome if motivo else "Não informado"
        resp_nome = resp.nome if resp else "Não informado"
        cli_nome = cli.name if cli else f"Cliente #{d.client_id}"
        motorista_nome = motorista.name if motorista else f"Motorista #{d.motorista_id}"
        # Ajudante: Devolucao.ajudante_id, ou rota vinculada (route_id), ou rota casada por (cliente, motorista, data)
        if ajudante:
            ajudante_nome = ajudante.name
        else:
            helper_ids = None
            if getattr(d, "route_id", None) and route_helpers.get(d.route_id):
                helper_ids = route_helpers[d.route_id]
            if not helper_ids and d.client_id and d.motorista_id and d.data_romaneio:
                dt_key = str(d.data_romaneio)[:10]
                key = (d.client_id, d.motorista_id, dt_key)
                helper_ids = route_by_client_driver_date.get(key)
            if not helper_ids and d.motorista_id and d.data_romaneio:
                dt_key = str(d.data_romaneio)[:10]
                session_key = (dt_key, d.motorista_id)
                helper_ids = session_helpers_by_driver_date.get(session_key)
            ajudante_id_from_route = helper_ids[0] if helper_ids else None
            if ajudante_id_from_route and ajudante_id_from_route == d.motorista_id and len(helper_ids) > 1:
                ajudante_id_from_route = helper_ids[1]
            elif ajudante_id_from_route == d.motorista_id:
                ajudante_id_from_route = None
            emp_ajud = emp_map.get(ajudante_id_from_route) if ajudante_id_from_route else None
            ajudante_nome = emp_ajud.name if emp_ajud else "—"
        vendedor_nome = vendedor.name if vendedor else "—"

        val = float(d.valor or 0)
        dt_str = _competence_date_or_self(_dev_op_date_raw(d))

        # per_day
        slot = per_day.setdefault(dt_str, {"data": dt_str, "qtd": 0, "valor": 0.0})
        slot["qtd"] += 1
        slot["valor"] = round(slot["valor"] + val, 2)

        # per_week
        try:
            _dt = datetime.strptime(dt_str, "%Y-%m-%d").date()
            iso = _dt.isocalendar()
            wk = f"{iso.year}-S{iso.week:02d}"
            dow = _dt.weekday()
            dom = _dt.day
        except Exception:
            wk = "Sem semana"
            dow = 0
            dom = 1
            _dt = date_i

        ws = per_week.setdefault(wk, {"semana": wk, "qtd": 0, "valor": 0.0})
        ws["qtd"] += 1
        ws["valor"] = round(ws["valor"] + val, 2)

        # per_motivo
        ms = per_motivo.setdefault(motivo_nome, {"motivo": motivo_nome, "qtd": 0, "valor": 0.0})
        ms["qtd"] += 1
        ms["valor"] = round(ms["valor"] + val, 2)

        # per_resp
        rs = per_resp.setdefault(resp_nome, {"responsabilidade": resp_nome, "qtd": 0, "valor": 0.0})
        rs["qtd"] += 1
        rs["valor"] = round(rs["valor"] + val, 2)
        # per_resp_motivo (drill: motivos por responsabilidade)
        prm = per_resp_motivo.setdefault(resp_nome, {})
        smr = prm.setdefault(motivo_nome, {"motivo": motivo_nome, "qtd": 0, "valor": 0.0})
        smr["qtd"] += 1
        smr["valor"] = round(smr["valor"] + val, 2)

        # per_cluster
        cluster = str(d.cluster or "Sem cluster")
        cs = per_cluster.setdefault(cluster, {"cluster": cluster, "qtd": 0, "valor": 0.0})
        cs["qtd"] += 1
        cs["valor"] = round(cs["valor"] + val, 2)

        # per_motorista
        mts = per_motorista.setdefault(motorista_nome, {
            "motorista": motorista_nome, "qtd": 0, "valor": 0.0,
            "acima300": 0,
        })
        mts["qtd"] += 1
        mts["valor"] = round(mts["valor"] + val, 2)
        if (d.acima_300 or "NAO") == "SIM":
            mts["acima300"] += 1

        # per_vendedor
        vs = per_vendedor.setdefault(vendedor_nome, {"vendedor": vendedor_nome, "qtd": 0, "valor": 0.0})
        vs["qtd"] += 1
        vs["valor"] = round(vs["valor"] + val, 2)

        # per_vendedor_resp (drill: responsabilidade por vendedor)
        pr = per_vendedor_resp.setdefault(vendedor_nome, {})
        sr = pr.setdefault(resp_nome, {"responsabilidade": resp_nome, "qtd": 0, "valor": 0.0})
        sr["qtd"] += 1
        sr["valor"] = round(sr["valor"] + val, 2)
        # per_vendedor_motivo (drill: motivos por vendedor)
        pm = per_vendedor_motivo.setdefault(vendedor_nome, {})
        sm = pm.setdefault(motivo_nome, {"motivo": motivo_nome, "qtd": 0, "valor": 0.0})
        sm["qtd"] += 1
        sm["valor"] = round(sm["valor"] + val, 2)

        # per_cliente
        cls_ = per_cliente.setdefault(
            cli_nome,
            {"cliente": cli_nome, "qtd": 0, "valor": 0.0, "motivos": {}, "ultima_data": dt_str},
        )
        cls_["qtd"] += 1
        cls_["valor"] = round(cls_["valor"] + val, 2)
        cls_["motivos"][motivo_nome] = cls_["motivos"].get(motivo_nome, 0) + 1
        if dt_str > cls_.get("ultima_data", ""):
            cls_["ultima_data"] = dt_str

        # heatmap semanal
        hw = heatmap_week.setdefault(wk, {i: 0 for i in range(7)})
        hw[dow] = hw.get(dow, 0) + 1

        # heatmap dia-da-semana × dia-do-mês
        heatmap_dow_dom[dow][dom] = heatmap_dow_dom[dow].get(dom, 0) + 1

        did = getattr(d, "id", None)
        if did is not None and did in ids_listagem:
            obs_parts = [
                (getattr(d, "observacao", None) or "").strip(),
                (getattr(d, "observacao_gestor", None) or "").strip(),
            ]
            obs_txt = " — ".join([p for p in obs_parts if p]) or "—"
            pct_imp = round(100.0 * val / total_valor_kpi, 2) if total_valor_kpi > 0 else 0.0
            rows_detail.append({
                "id": did,
                "data": dt_str,
                "cliente": cli_nome,
                "vendedor": vendedor_nome,
                "motorista": motorista_nome,
                "ajudante": ajudante_nome,
                "motivo": motivo_nome,
                "responsabilidade": resp_nome,
                "responsabilidade_hex": _resp_hex(resp_nome),
                "responsabilidade_tom": _resp_tom(resp_nome),
                "cluster": cluster,
                "valor": val,
                "acima_300": d.acima_300 or "NAO",
                "semana": d.semana or 0,
                "dia": d.dia or 0,
                "source": d.source or "—",
                "observacao": obs_txt,
                "pct_impacto": pct_imp,
                "impacto_classificacao": _classificacao_impacto_valor(val),
                "acao_corretiva": _acao_corretiva_sugerida(resp_nome),
                "status_operacional": (
                    "Crítica"
                    if (d.acima_300 or "").upper() == "SIM"
                    else ("Pendente" if (str(d.source or "").upper() == "EXCEL") else "Resolvida")
                ),
            })

    # --- top N (prioriza valor financeiro) ---
    top_clientes = sorted(per_cliente.values(), key=lambda x: x["valor"], reverse=True)[:20]
    top_motoristas = sorted(per_motorista.values(), key=lambda x: x["valor"], reverse=True)[:20]
    top_motivos = sorted(per_motivo.values(), key=lambda x: x["valor"], reverse=True)[:15]
    top_vendedores = sorted(per_vendedor.values(), key=lambda x: x["valor"], reverse=True)[:15]
    top_clusters = sorted(per_cluster.values(), key=lambda x: x["valor"], reverse=True)[:15]

    # Drill-down por vendedor: responsabilidade e motivos para detalhe no clique
    vendedor_drill: dict[str, dict] = {}
    for vendedor_nome in per_vendedor.keys():
        resp_list = sorted(
            per_vendedor_resp.get(vendedor_nome, {}).values(),
            key=lambda x: x["qtd"],
            reverse=True,
        )
        motivos_list = sorted(
            per_vendedor_motivo.get(vendedor_nome, {}).values(),
            key=lambda x: x["qtd"],
            reverse=True,
        )[:15]
        vendedor_drill[vendedor_nome] = {
            "responsabilidade": resp_list,
            "motivos": motivos_list,
        }

    # Evolução diária: todos os dias do filtro (inclui dias sem devolução), meta = 2% da receita real daquele dia
    def _date_str_range_inclusive(s: str, e: str) -> List[str]:
        out: List[str] = []
        try:
            s10 = (s or "").strip()[:10]
            e10 = (e or "").strip()[:10]
            if len(s10) < 10 or len(e10) < 10:
                return []
            di = datetime.strptime(s10, "%Y-%m-%d").date()
            df = datetime.strptime(e10, "%Y-%m-%d").date()
            if di > df:
                di, df = df, di
            cur = di
            while cur <= df:
                out.append(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)
        except Exception:
            return []
        return out

    days_sorted = _date_str_range_inclusive(period_start, period_end)
    if not days_sorted and date_i and date_f:
        cur = date_i
        while cur <= date_f:
            days_sorted.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
    evolucao_diaria: list[dict] = []
    for ds in days_sorted:
        slot_dev = per_day.get(ds, {"data": ds, "qtd": 0, "valor": 0.0})
        rec = round(float(receita_por_dia_comp.get(ds, 0.0)), 2)
        meta_2 = round(0.02 * rec, 2) if rec > 0 else None
        val_fl = float(slot_dev.get("valor") or 0)
        pct_dia = round(100.0 * val_fl / rec, 2) if rec > 0 else None
        evolucao_diaria.append(
            {
                "data": ds,
                "qtd": int(slot_dev.get("qtd") or 0),
                "valor": round(val_fl, 2),
                "receita_base": rec,
                "meta_2pct_valor": meta_2,
                "pct_devolucao_dia": pct_dia,
            }
        )
    # Linha constante (meta ÷ dias corridos) substituída por meta proporcional à receita de cada dia — manter null no JSON
    meta_valor_dia_ref: Optional[float] = None

    # Evolução semanal
    weeks_sorted = sorted(per_week.keys())
    evolucao_semanal = [per_week[k] for k in weeks_sorted]

    # responsabilidade breakdown — cor em hex para gráficos e cartões
    for _rk, _rv in per_resp.items():
        _rv["color"] = _resp_hex(_rk)
        _rv["tom"] = _resp_tom(_rk)
    resp_breakdown = sorted(per_resp.values(), key=lambda x: x["valor"], reverse=True)

    # Drill-down por responsabilidade: motivos com qtd, valor e % (para modal ao clicar no card)
    resp_drill: dict[str, dict] = {}
    for resp_nome, resp_totals in per_resp.items():
        motivos_raw = list(per_resp_motivo.get(resp_nome, {}).values())
        total_qtd_resp = resp_totals["qtd"]
        total_valor_resp = resp_totals["valor"]
        motivos_list = []
        for m in sorted(motivos_raw, key=lambda x: x["qtd"], reverse=True):
            pct_qtd = round(100.0 * m["qtd"] / total_qtd_resp, 1) if total_qtd_resp else 0
            pct_valor = round(100.0 * m["valor"] / total_valor_resp, 1) if total_valor_resp else 0
            motivos_list.append({
                "motivo": m["motivo"],
                "qtd": m["qtd"],
                "valor": m["valor"],
                "pct_qtd": pct_qtd,
                "pct_valor": pct_valor,
            })
        resp_drill[resp_nome] = {"responsabilidade": resp_nome, "motivos": motivos_list}

    # heatmap: matriz DOW (0-6) × semanas
    weeks_label = weeks_sorted[-12:] if len(weeks_sorted) > 12 else weeks_sorted
    heatmap_matrix = []
    for dow in range(7):
        row_vals = []
        for wk in weeks_label:
            cnt = heatmap_week.get(wk, {}).get(dow, 0)
            row_vals.append(cnt)
        heatmap_matrix.append({"dow": DOW_LABELS[dow], "values": row_vals})

    # heatmap DOM × DOW (dia-do-mês como eixo Y, dia-da-semana como eixo X)
    heatmap_dom_dow = []
    for dom in range(1, 32):
        vals = [heatmap_dow_dom[dow].get(dom, 0) for dow in range(7)]
        if any(v > 0 for v in vals):
            heatmap_dom_dow.append({"dom": dom, "values": vals})

    # acima_300 breakdown
    total_acima_300 = sum(1 for d in devs_pre_acima if (d.acima_300 or "NAO") == "SIM")
    pct_acima_300 = round(total_acima_300 / total_qtd * 100, 1) if total_qtd else 0.0

    # média por dia (dias com devolução)
    media_por_dia = round(total_qtd / len(days_sorted), 1) if days_sorted else 0.0
    media_valor_dia = round(total_valor / len(days_sorted), 2) if days_sorted else 0.0

    analise_destaque: list[str] = []
    if total_valor_kpi > 0 and top_motivos:
        m_fin = max(top_motivos, key=lambda x: float(x.get("valor") or 0))
        vm = float(m_fin.get("valor") or 0)
        if vm > 0:
            analise_destaque.append(
                f"O principal impacto financeiro veio do motivo {m_fin.get('motivo', '—')}, somando {_fmt_br_moeda(vm)}."
            )
    if total_valor_kpi > 0 and resp_breakdown:
        r_fin = max(resp_breakdown, key=lambda x: float(x.get("valor") or 0))
        rv = float(r_fin.get("valor") or 0)
        pct_r = round(100.0 * rv / total_valor_kpi, 1) if total_valor_kpi else 0.0
        if rv > 0:
            analise_destaque.append(
                f"A área {r_fin.get('responsabilidade', '—')} concentra {pct_r:.1f}% do valor devolvido no período."
            )
    crit_n = sum(1 for d in devs_pre_acima if float(d.valor or 0) >= 800.0)
    crit_v = sum(float(d.valor or 0) for d in devs_pre_acima if float(d.valor or 0) >= 800.0)
    if crit_n > 0 and total_valor_kpi > 0:
        pct_crit_v = round(100.0 * crit_v / total_valor_kpi, 1)
        if crit_n <= max(1, int(total_qtd_kpi * 0.25)) and pct_crit_v >= 30.0:
            analise_destaque.append(
                f"As devoluções acima de R$ 800 somam {crit_n} ocorrência(s), mas concentram cerca de {pct_crit_v:.0f}% do valor."
            )
    if desvio_pp is not None and desvio_pp > 0 and pct_devolucao_financeiro is not None:
        analise_destaque.append(
            f"Sobre valor base de rotas, o período está {desvio_pp:.2f} pontos percentuais acima da meta de 2%."
        )
    elif desvio_pp is not None and desvio_pp < 0 and pct_devolucao_financeiro is not None:
        analise_destaque.append(
            f"Sobre valor base de rotas, o período está {abs(desvio_pp):.2f} pontos percentuais abaixo da meta de 2%."
        )
    if n_done_r > 0 and desvio_rotas_pp > 0:
        analise_destaque.append(
            f"Sobre rotas concluídas (critério TV), o período está {desvio_rotas_pp:.1f} pontos percentuais acima da meta de 2%."
        )
    if excedente_sobre_meta is not None and excedente_sobre_meta > 0:
        analise_destaque.append(
            f"O excedente financeiro sobre a meta permitida é de {_fmt_br_moeda(excedente_sobre_meta)}."
        )
    if float(pct_devolucao_rotas or 0) >= 2.0 and pct_devolucao_financeiro is None:
        analise_destaque.append(
            f"Indicador operacional (paradas): {float(pct_devolucao_rotas):.1f}% de devoluções sobre rotas concluídas — "
            "sem valor base financeiro para calcular % sobre faturamento."
        )
    if not analise_destaque:
        if total_qtd_kpi == 0:
            analise_destaque.append("Sem devoluções no período com os filtros aplicados.")
        else:
            analise_destaque.append("Use os rankings e a lista para priorizar ações corretivas no período.")

    for m in top_motivos:
        m["pct_valor_total"] = round(100.0 * float(m["valor"]) / total_valor_kpi, 1) if total_valor_kpi else 0.0
    for r in resp_breakdown:
        r["pct_valor_total"] = round(100.0 * float(r["valor"]) / total_valor_kpi, 1) if total_valor_kpi else 0.0

    filters_query = urlencode({
        k: str(v) for k, v in {
            "date_from": date_from or "",
            "date_to": date_to or "",
            "responsabilidade_id": responsabilidade_id or "",
            "motivo_id": motivo_id or "",
            "motorista_id": motorista_id or "",
            "vendedor_id": vendedor_id or "",
            "client_id": client_id or "",
            "client_scope": cfs if client_id else "",
            "valor_faixa": (valor_faixa or "").strip().lower() if valor_faixa else "",
            "criticas": "1" if somente_criticas else "",
            "acima_meta": "1" if somente_acima_meta else "",
        }.items() if v not in ("", None, False, 0)
    })

    return {
        "filters": {
            "date_from": date_from or date_i.strftime("%Y-%m-%d"),
            "date_to": date_to or date_f.strftime("%Y-%m-%d"),
            "responsabilidade_id": responsabilidade_id,
            "motivo_id": motivo_id,
            "motorista_id": motorista_id,
            "vendedor_id": vendedor_id,
            "client_id": client_id,
            "client_scope": cfs if client_id else "solo",
            "valor_faixa": (valor_faixa or "all").strip().lower(),
            "somente_criticas": somente_criticas,
            "somente_acima_meta": somente_acima_meta,
            "group_filter_note": group_filter_note_dev,
            "acima_meta_filter_note": acima_meta_filter_note,
        },
        "filters_query": filters_query,
        # KPIs
        "total_qtd": total_qtd,
        "total_valor": total_valor,
        "total_acima_300": total_acima_300,
        "pct_acima_300": pct_acima_300,
        "media_por_dia": media_por_dia,
        "media_valor_dia": media_valor_dia,
        "total_clientes_afetados": len(per_cliente),
        "total_motoristas_envolvidos": len(per_motorista),
        "valor_base_rotas": round(valor_base_rotas, 2),
        "valor_base_disponivel": bool(valor_base_rotas and valor_base_rotas > 0),
        "pct_devolucao_rotas": pct_devolucao_rotas,
        "pct_devolucao_financeiro": pct_devolucao_financeiro,
        "meta_pp": meta_pp,
        "valor_meta_permitido": valor_meta_permitido,
        "excedente_sobre_meta": excedente_sobre_meta,
        "desvio_pp": desvio_pp,
        "desvio_rotas_pp": desvio_rotas_pp,
        "rotas_kpi_devolucao": int(n_ret_r),
        "rotas_kpi_concluidas": int(n_done_r),
        "situacao_meta": situacao_meta,
        "faixa_alerta_meta": faixa_alerta_meta,
        "meta_valor_dia_ref": meta_valor_dia_ref,
        "generated_at": datetime.now(tz).strftime("%d/%m/%Y %H:%M"),
        # evolução
        "evolucao_diaria": evolucao_diaria,
        "evolucao_semanal": evolucao_semanal,
        # breakdowns
        "resp_breakdown": resp_breakdown,
        "resp_drill": resp_drill,
        "top_motivos": top_motivos,
        "top_clientes": top_clientes,
        "top_motoristas": top_motoristas,
        "top_vendedores": top_vendedores,
        "top_clusters": top_clusters,
        # heatmap
        "heatmap_matrix": heatmap_matrix,
        "heatmap_weeks_labels": weeks_label,
        "heatmap_dom_dow": heatmap_dom_dow,
        "dow_labels": DOW_LABELS,
        # tabela detalhada (últimos 500 da query)
        "rows_detail": rows_detail[:500],
        # select de filtros
        "motivos_filter": sorted(motivos_all, key=lambda m: m.nome),
        "resps_filter": sorted(resps_all, key=lambda r: r.nome),
        "drivers_filter": drivers_filter,
        "clients_filter": clients_filter,
        "vendedores_filter": vendedores_filter,
        # json para charts
        "evolucao_diaria_json": _json_for_inline_script(evolucao_diaria),
        "evolucao_semanal_json": _json_for_inline_script(evolucao_semanal),
        "top_motivos_json": _json_for_inline_script(top_motivos),
        "resp_breakdown_json": _json_for_inline_script(resp_breakdown),
        "resp_drill_json": _json_for_inline_script(resp_drill),
        "top_motoristas_json": _json_for_inline_script(top_motoristas),
        "top_clientes_json": _json_for_inline_script(top_clientes),
        "top_vendedores_json": _json_for_inline_script(top_vendedores),
        "vendedor_drill_json": _json_for_inline_script(vendedor_drill),
        "top_clusters_json": _json_for_inline_script(top_clusters),
        "heatmap_matrix_json": _json_for_inline_script(heatmap_matrix),
        "heatmap_weeks_labels_json": _json_for_inline_script(weeks_label),
        "heatmap_dom_dow_json": _json_for_inline_script(heatmap_dom_dow),
        "dow_labels_json": _json_for_inline_script(DOW_LABELS),
        "rows_detail_json": _json_for_inline_script(rows_detail[:500]),
        "analise_destaque": analise_destaque,
    }


@router.get("/bi/devolucoes", response_class=HTMLResponse)
async def bi_devolucoes_page(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    responsabilidade_id: Optional[str] = None,
    motivo_id: Optional[str] = None,
    motorista_id: Optional[str] = None,
    vendedor_id: Optional[str] = None,
    client_id: Optional[str] = None,
    client_scope: Optional[str] = None,
    valor_faixa: Optional[str] = None,
    criticas: Optional[str] = None,
    acima_meta: Optional[str] = None,
    session: Session = Depends(get_session),
):
    parsed_resp_id: Optional[int] = int(responsabilidade_id) if (responsabilidade_id or "").strip().isdigit() else None
    parsed_motivo_id: Optional[int] = int(motivo_id) if (motivo_id or "").strip().isdigit() else None
    parsed_motorista_id: Optional[int] = int(motorista_id) if (motorista_id or "").strip().isdigit() else None
    parsed_vendedor_id: Optional[int] = int(vendedor_id) if (vendedor_id or "").strip().isdigit() else None
    parsed_client_id: Optional[int] = int(client_id) if (client_id or "").strip().isdigit() else None
    somente_criticas = (criticas or "").strip().lower() in ("1", "true", "on", "yes", "sim")
    somente_acima_meta = (acima_meta or "").strip().lower() in ("1", "true", "on", "yes", "sim")
    dataset = _build_bi_devolucoes_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        responsabilidade_id=parsed_resp_id,
        motivo_id=parsed_motivo_id,
        motorista_id=parsed_motorista_id,
        vendedor_id=parsed_vendedor_id,
        client_id=parsed_client_id,
        client_filter_scope=(client_scope or "solo").strip().lower(),
        valor_faixa=valor_faixa,
        somente_criticas=somente_criticas,
        somente_acima_meta=somente_acima_meta,
    )
    return templates.TemplateResponse("bi_devolucoes_refactor.html", {"request": request, **dataset})


@router.get("/bi/devolucoes/export")
async def bi_devolucoes_export(
    format: str = "csv",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    responsabilidade_id: Optional[str] = None,
    motivo_id: Optional[str] = None,
    motorista_id: Optional[str] = None,
    vendedor_id: Optional[str] = None,
    client_id: Optional[str] = None,
    client_scope: Optional[str] = None,
    valor_faixa: Optional[str] = None,
    criticas: Optional[str] = None,
    acima_meta: Optional[str] = None,
    session: Session = Depends(get_session),
):
    parsed_resp_id: Optional[int] = int(responsabilidade_id) if (responsabilidade_id or "").strip().isdigit() else None
    parsed_motivo_id: Optional[int] = int(motivo_id) if (motivo_id or "").strip().isdigit() else None
    parsed_motorista_id: Optional[int] = int(motorista_id) if (motorista_id or "").strip().isdigit() else None
    parsed_vendedor_id: Optional[int] = int(vendedor_id) if (vendedor_id or "").strip().isdigit() else None
    parsed_client_id: Optional[int] = int(client_id) if (client_id or "").strip().isdigit() else None
    somente_criticas = (criticas or "").strip().lower() in ("1", "true", "on", "yes", "sim")
    somente_acima_meta = (acima_meta or "").strip().lower() in ("1", "true", "on", "yes", "sim")
    dataset = _build_bi_devolucoes_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        responsabilidade_id=parsed_resp_id,
        motivo_id=parsed_motivo_id,
        motorista_id=parsed_motorista_id,
        vendedor_id=parsed_vendedor_id,
        client_id=parsed_client_id,
        client_filter_scope=(client_scope or "solo").strip().lower(),
        valor_faixa=valor_faixa,
        somente_criticas=somente_criticas,
        somente_acima_meta=somente_acima_meta,
    )
    rows = dataset["rows_detail"]
    stamp = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M")
    fmt = (format or "csv").strip().lower()

    headers_csv = ["data", "cliente", "vendedor", "motorista", "ajudante",
                   "motivo", "responsabilidade", "cluster", "valor", "acima_300", "source"]

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(headers_csv)
        for r in rows:
            writer.writerow([
                _fmt_br_data(r.get("data") or ""),
                r.get("cliente") or "",
                r.get("vendedor") or "",
                r.get("motorista") or "",
                r.get("ajudante") or "",
                r.get("motivo") or "",
                r.get("responsabilidade") or "",
                r.get("cluster") or "",
                _fmt_br_2(r.get("valor") or 0),
                r.get("acima_300") or "NAO",
                r.get("source") or "",
            ])
        out.seek(0)
        return StreamingResponse(
            iter([out.getvalue()]),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename=bi_devolucoes_{stamp}.csv"},
        )

    if fmt == "xlsx":
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws_sheet = wb.active
            ws_sheet.title = "Devoluções"
            ws_sheet.append(headers_csv)
            for r in rows:
                ws_sheet.append([
                    _fmt_br_data(r.get("data") or ""),
                    r.get("cliente") or "",
                    r.get("vendedor") or "",
                    r.get("motorista") or "",
                    r.get("ajudante") or "",
                    r.get("motivo") or "",
                    r.get("responsabilidade") or "",
                    r.get("cluster") or "",
                    float(r.get("valor") or 0),
                    r.get("acima_300") or "NAO",
                    r.get("source") or "",
                ])
            xbuf = io.BytesIO()
            wb.save(xbuf)
            xbuf.seek(0)
            return StreamingResponse(
                iter([xbuf.getvalue()]),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=bi_devolucoes_{stamp}.xlsx"},
            )
        except ImportError:
            pass

    return JSONResponse({"error": "Formato invalido. Use csv ou xlsx."}, status_code=400)
