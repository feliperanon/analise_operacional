# -*- coding: utf-8 -*-
"""
Consolidação de devoluções (Avaliar) — mesma regra do desktop /devolucoes/avaliar.
% original e % ajustado são por CONTAGEM (devoluções / paradas), não por valor financeiro.

Arquitetura (fonte única de verdade):
- `build_motorista_consolidation_pure` / `build_ajudante_consolidation_pure`: núcleo determinístico
  (lista de devoluções do colaborador + entregues por dia + período + `load_ajustes_map`).
- Agrupamento diário do gráfico: sempre `data_romaneio` (YYYY-MM-DD), nunca `data_entrega`.
- `consolidado_avaliar_resumo` (tabela desktop): agrega listas no período e chama o núcleo com
  `include_daily=False`.
- `motorista_returns_mobile_bundle` / `ajudante_returns_mobile_bundle`: carregam do banco e chamam
  o núcleo com `include_daily=True` (série + `_daily_by_iso` para auditoria).
- `build_returns_consolidated_bundle(role, ...)`: fachada única para o mobile por papel.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Any, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

from sqlmodel import Session, select, func

import models
from utils.business_calendar import competence_date_str

DELIVERY_GAMIFICATION_RETURN_PRIZE_TIERS: List[Tuple[float, float]] = [
    (1.5, 300.0),
    (2.0, 250.0),
    (2.5, 180.0),
]


def _return_rate_to_prize(return_rate_pct: float) -> float:
    """Retorna o prêmio conforme a faixa da taxa de devolução ajustada."""
    for limit, prize in DELIVERY_GAMIFICATION_RETURN_PRIZE_TIERS:
        if float(return_rate_pct or 0.0) <= float(limit):
            return float(prize)
    return 0.0


def _iter_days_inclusive(date_from: str, date_to: str) -> List[str]:
    """Lista YYYY-MM-DD do início ao fim (inclusive), ordem cronológica crescente."""
    d0 = datetime.strptime(str(date_from)[:10], "%Y-%m-%d").date()
    d1 = datetime.strptime(str(date_to)[:10], "%Y-%m-%d").date()
    if d1 < d0:
        d0, d1 = d1, d0
    out: List[str] = []
    cur = d0
    while cur <= d1:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _series_arrays_from_daily_by_iso(
    daily_by_iso: Dict[str, Dict[str, Any]],
    date_from: str,
    date_to: str,
) -> Tuple[List[str], List[str], List[float], List[float], List[float], List[float]]:
    """Deriva arrays do gráfico sempre a partir do mapa diário ISO ordenado."""
    chart_dates_iso: List[str] = []
    chart_labels: List[str] = []
    chart_values: List[float] = []
    chart_adjusted_values: List[float] = []
    chart_percents: List[float] = []
    chart_adjusted_percents: List[float] = []
    for day in _iter_days_inclusive(date_from, date_to):
        b = daily_by_iso.get(day) or {}
        chart_dates_iso.append(day)
        chart_labels.append(f"{day[8:10]}/{day[5:7]}")
        chart_values.append(float(b.get("valor_original") or 0.0))
        chart_adjusted_values.append(float(b.get("valor_ajustado") or 0.0))
        chart_percents.append(float(b.get("pct_original") or 0.0))
        chart_adjusted_percents.append(float(b.get("pct_ajustado") or 0.0))
    return (
        chart_dates_iso,
        chart_labels,
        chart_values,
        chart_adjusted_values,
        chart_percents,
        chart_adjusted_percents,
    )


def _scalar_count(result: Any) -> int:
    """Normaliza retorno de select(func.count()) em int."""
    if result is None:
        return 0
    if hasattr(result, "__getitem__") and not isinstance(result, (int, float)):
        try:
            return int(result[0])
        except (TypeError, ValueError, IndexError):
            pass
    try:
        return int(result)
    except (TypeError, ValueError):
        return 0


def parse_route_helper_ids(helpers_json: Optional[str]) -> List[int]:
    if not helpers_json:
        return []
    try:
        data = json.loads(helpers_json) if isinstance(helpers_json, str) else helpers_json
        if not isinstance(data, list):
            return []
        return [int(x) for x in data if x is not None and str(x).strip().isdigit()]
    except Exception:
        return []


def parse_helpers_to_ids(helpers_json: Optional[str], emp_by_name: dict) -> List[int]:
    if not helpers_json or not emp_by_name:
        return []
    try:
        data = json.loads(helpers_json) if isinstance(helpers_json, str) else helpers_json
        if not isinstance(data, list):
            return []
        ids: List[int] = []
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


def effective_ajudante_id(
    d: models.Devolucao,
    route_helpers: dict,
    route_by_client_driver_date: dict,
    session_helpers_by_driver_date: dict,
) -> Optional[int]:
    """Ajudante efetivo: Devolucao.ajudante_id ou da rota/sessão (igual ao desktop)."""
    aid_raw = getattr(d, "ajudante_id", None)
    if aid_raw is not None:
        try:
            aid_int = int(aid_raw)
        except (TypeError, ValueError):
            aid_int = 0
        if aid_int > 0:
            return aid_int
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
    if not helper_ids:
        return None
    aid = helper_ids[0]
    if aid == d.motorista_id and len(helper_ids) > 1:
        aid = helper_ids[1]
    elif aid == d.motorista_id:
        return None
    return aid


def effective_ajudante_ids_for_summary(
    d: models.Devolucao,
    route_helpers: dict,
    route_by_client_driver_date: dict,
    session_helpers_by_driver_date: dict,
) -> List[int]:
    """Retorna TODOS os ajudantes efetivos da devolução para o resumo por ajudante."""
    out: List[int] = []
    seen = set()

    def _add_many(ids: Optional[List[int]], motorista_id: Optional[int]) -> None:
        if not ids:
            return
        drv = int(motorista_id) if motorista_id else 0
        for raw in ids:
            try:
                hid = int(raw)
            except (TypeError, ValueError):
                continue
            if hid <= 0 or hid == drv or hid in seen:
                continue
            seen.add(hid)
            out.append(hid)

    if d.ajudante_id:
        _add_many([d.ajudante_id], d.motorista_id)

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

    _add_many(helper_ids, d.motorista_id)
    return out


def load_ajustes_map(session: Session) -> Dict[int, Tuple[bool, bool]]:
    ajustes: Dict[int, Tuple[bool, bool]] = {}
    for aj in session.exec(select(models.DevolucaoAjusteResponsabilidade)).all():
        rm = getattr(aj, "responsavel_motorista", True)
        ra = getattr(aj, "responsavel_ajudante", True)
        ajustes[aj.devolucao_id] = (rm, ra)
    return ajustes


def _float_series_matches_total(series_sum: float, period_total: float, tol: float = 1e-5) -> bool:
    """Fechamento série diária vs total do período (mesma origem de dados, tolerância só por float)."""
    return math.isclose(float(series_sum), float(period_total), rel_tol=0.0, abs_tol=tol)


def motorista_entregues_by_motorista_all(session: Session, date_from: str, date_to: str) -> Dict[int, Dict[str, int]]:
    """
    Para cada motorista (employee_id), mapa YYYY-MM-DD -> quantidade de rotas entregues naquele dia.
    Uma única consulta agregada — mesma base que contar rotas por motorista no período.
    """
    rows = session.exec(
        select(models.Route.employee_id, models.Route.date, func.count())
        .select_from(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= date_from)
        .where(models.Route.date <= date_to)
        .where(models.Route.delivery_status == "entregue")
        .where(models.Route.employee_id.is_not(None))
        .group_by(models.Route.employee_id, models.Route.date)
    ).all()
    out: Dict[int, Dict[str, int]] = {}
    for row in rows:
        eid_raw, rd, cnt = row[0], row[1], row[2]
        if eid_raw is None:
            continue
        try:
            eid = int(eid_raw)
        except (TypeError, ValueError):
            continue
        dkey = str(rd)[:10] if rd is not None else ""
        if len(dkey) != 10:
            continue
        out.setdefault(eid, {})[dkey] = int(cnt or 0)
    return out


def motorista_entregues_by_day(session: Session, motorista_id: int, date_from: str, date_to: str) -> Dict[str, int]:
    """Contagem de rotas entregues por dia (YYYY-MM-DD) para o motorista no intervalo."""
    rows = session.exec(
        select(models.Route.date, func.count())
        .select_from(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= date_from)
        .where(models.Route.date <= date_to)
        .where(models.Route.delivery_status == "entregue")
        .where(models.Route.employee_id == motorista_id)
        .group_by(models.Route.date)
    ).all()
    out: Dict[str, int] = {}
    for row in rows:
        rd = row[0]
        dkey = str(rd)[:10] if rd is not None else ""
        if len(dkey) != 10:
            continue
        out[dkey] = int(row[1] or 0)
    return out


def _build_helper_maps(session: Session, date_from: str, date_to: str) -> Tuple[dict, dict, dict, dict]:
    """route_helpers, route_by_client_driver_date, session_helpers_by_driver_date, emp_by_name."""
    all_employees = list(session.exec(select(models.Employee)).all())
    emp_by_name = {
        e.name.strip().lower(): e.id
        for e in all_employees
        if e and getattr(e, "name", None) and getattr(e, "id", None)
    }
    emp_by_registration = {
        str(getattr(e, "registration_id", "") or "").strip(): e.id
        for e in all_employees
        if e and getattr(e, "id", None) and str(getattr(e, "registration_id", "") or "").strip()
    }
    valid_employee_ids = {int(e.id) for e in all_employees if getattr(e, "id", None) is not None}

    def _resolve_helper_ids(raw_value: Optional[str]) -> List[int]:
        parsed_ids = parse_route_helper_ids(raw_value)
        parsed_by_name = parse_helpers_to_ids(raw_value, emp_by_name)
        out: List[int] = []
        seen = set()
        for raw in (parsed_ids + parsed_by_name):
            try:
                hid = int(raw)
            except (TypeError, ValueError):
                continue
            resolved = hid
            if resolved not in valid_employee_ids:
                reg_key = str(resolved)
                mapped = emp_by_registration.get(reg_key)
                if mapped:
                    resolved = int(mapped)
            if resolved not in valid_employee_ids or resolved in seen:
                continue
            seen.add(resolved)
            out.append(resolved)
        return out

    devolucoes = session.exec(
        select(models.Devolucao)
        .where(models.Devolucao.data_romaneio >= date_from)
        .where(models.Devolucao.data_romaneio <= date_to)
    ).all()
    devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]
    route_ids = sorted({d.route_id for d in devolucoes if getattr(d, "route_id", None)})
    route_helpers: Dict[int, List[int]] = {}
    if route_ids:
        routes_linked = session.exec(select(models.Route).where(models.Route.id.in_(route_ids))).all()
        for r in routes_linked:
            raw = getattr(r, "delivery_helpers_json", None)
            ids = _resolve_helper_ids(raw)
            if ids:
                route_helpers[r.id] = ids

    route_by_client_driver_date: Dict[tuple, List[int]] = {}
    routes_in_range = session.exec(
        select(models.Route)
        .where(models.Route.date >= date_from)
        .where(models.Route.date <= date_to)
        .where(models.Route.client_id.is_not(None))
        .where(models.Route.employee_id.is_not(None))
    ).all()
    for r in routes_in_range:
        raw = getattr(r, "delivery_helpers_json", None)
        ids = _resolve_helper_ids(raw)
        if ids and r.client_id and r.employee_id:
            key = (r.client_id, r.employee_id, str(r.date)[:10])
            if key not in route_by_client_driver_date:
                route_by_client_driver_date[key] = ids

    session_helpers_by_driver_date: Dict[tuple, List[int]] = {}
    sessions_in_range = session.exec(
        select(models.DeliverySession)
        .where(models.DeliverySession.date >= date_from)
        .where(models.DeliverySession.date <= date_to)
    ).all()
    for ds in sessions_in_range:
        raw = getattr(ds, "helpers_json", None)
        ids = _resolve_helper_ids(raw)
        if ids and ds.employee_id:
            key = (str(getattr(ds, "date", "") or "")[:10], ds.employee_id)
            if key not in session_helpers_by_driver_date:
                session_helpers_by_driver_date[key] = ids

    return route_helpers, route_by_client_driver_date, session_helpers_by_driver_date, emp_by_name


def consolidado_avaliar_resumo(
    session: Session,
    date_from: str,
    date_to: str,
    *,
    use_competence_window: bool = False,
) -> Dict[str, Any]:
    """
    Mesmo payload lógico de GET /api/devolucoes/avaliar/consolidado/resumo:
    {"data": [... motoristas ...], "data_ajudantes": [...]} (sem wrapper ok).
    """
    date_from = date_from or "2020-01-01"
    date_to = date_to or "2099-12-31"
    try:
        d0 = datetime.strptime(str(date_from)[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(str(date_to)[:10], "%Y-%m-%d").date()
    except Exception:
        d0 = datetime.strptime("2020-01-01", "%Y-%m-%d").date()
        d1 = datetime.strptime("2099-12-31", "%Y-%m-%d").date()
    if d1 < d0:
        d0, d1 = d1, d0
    period_start = d0.strftime("%Y-%m-%d")
    period_end = d1.strftime("%Y-%m-%d")
    window_start = (d0 - timedelta(days=10)).strftime("%Y-%m-%d")
    window_end = (d1 + timedelta(days=10)).strftime("%Y-%m-%d")

    def _competencia_in_period(raw_date: Optional[str]) -> bool:
        comp = competence_date_str(raw_date) or str(raw_date or "")[:10]
        return period_start <= comp <= period_end

    devolucoes = session.exec(
        select(models.Devolucao)
        .where(models.Devolucao.data_romaneio >= (window_start if use_competence_window else period_start))
        .where(models.Devolucao.data_romaneio <= (window_end if use_competence_window else period_end))
        .order_by(models.Devolucao.motorista_id, models.Devolucao.id)
    ).all()
    devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]
    if use_competence_window:
        devolucoes = [
            d
            for d in devolucoes
            if _competencia_in_period(getattr(d, "data_entrega", None) or getattr(d, "data_romaneio", None))
        ]

    ajustes = load_ajustes_map(session)

    routes_delivered = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= (window_start if use_competence_window else period_start))
        .where(models.Route.date <= (window_end if use_competence_window else period_end))
        .where(models.Route.delivery_status == "entregue")
    ).all()
    if use_competence_window:
        routes_delivered = [r for r in routes_delivered if _competencia_in_period(getattr(r, "date", None))]

    route_helpers, route_by_client_driver_date, session_helpers_by_driver_date, emp_by_name = _build_helper_maps(
        session,
        (window_start if use_competence_window else period_start),
        (window_end if use_competence_window else period_end),
    )

    routes_in_range = session.exec(
        select(models.Route)
        .where(models.Route.date >= (window_start if use_competence_window else period_start))
        .where(models.Route.date <= (window_end if use_competence_window else period_end))
        .where(models.Route.client_id.is_not(None))
        .where(models.Route.employee_id.is_not(None))
    ).all()
    if use_competence_window:
        routes_in_range = [r for r in routes_in_range if _competencia_in_period(getattr(r, "date", None))]

    effective_ajudante_ids = set()
    for d in devolucoes:
        for hid in effective_ajudante_ids_for_summary(
            d, route_helpers, route_by_client_driver_date, session_helpers_by_driver_date
        ):
            effective_ajudante_ids.add(hid)

    emp_ids = list(
        {d.motorista_id for d in devolucoes}
        | {d.ajudante_id for d in devolucoes if d.ajudante_id}
        | {r.employee_id for r in routes_delivered}
        | set(effective_ajudante_ids)
    )
    employees = {e.id: e for e in session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all()}

    dev_by_motorista: Dict[int, List[models.Devolucao]] = defaultdict(list)
    for d in devolucoes:
        if d.motorista_id is not None:
            dev_by_motorista[int(d.motorista_id)].append(d)

    ent_all_motoristas = motorista_entregues_by_motorista_all(session, date_from, date_to)
    all_motorista_ids = sorted(
        (set(dev_by_motorista.keys()) | set(ent_all_motoristas.keys())) & set(employees.keys())
    )

    out = []
    for eid in all_motorista_ids:
        devs_m = dev_by_motorista.get(eid, [])
        ent_by_d = dict(ent_all_motoristas.get(eid, {}))
        emp = employees.get(eid)
        name = emp.name if emp else f"Motorista #{eid}"
        b = build_motorista_consolidation_pure(
            devs_m, ent_by_d, date_from, date_to, ajustes, int(eid), name, include_daily=False
        )
        out.append(b["row"])
    out.sort(key=lambda x: (-x["devolucoes_total"], x["motorista_name"]))

    day_union_helpers: Dict[tuple, List[int]] = {}
    for (_cid, mid, dtk), hlist in route_by_client_driver_date.items():
        key_d = (dtk, mid)
        drv_u = int(mid) if mid else 0
        acc = day_union_helpers.setdefault(key_d, [])
        seen_u = set(acc)
        for hid in hlist or []:
            try:
                hu = int(hid)
            except (TypeError, ValueError):
                continue
            if hu <= 0 or hu == drv_u or hu in seen_u:
                continue
            seen_u.add(hu)
            acc.append(hu)

    def _helpers_for_entregue_stop(route_ent: models.Route) -> List[int]:
        key_e = (str(route_ent.date)[:10], route_ent.employee_id)
        raw_e = getattr(route_ent, "delivery_helpers_json", None)
        ids_e = parse_route_helper_ids(raw_e) or parse_helpers_to_ids(raw_e, emp_by_name)
        if ids_e:
            return ids_e
        if getattr(route_ent, "client_id", None) and getattr(route_ent, "employee_id", None):
            exact_key = (route_ent.client_id, route_ent.employee_id, str(route_ent.date)[:10])
            exact_ids = route_by_client_driver_date.get(exact_key) or []
            if exact_ids:
                return list(exact_ids)
        sess = session_helpers_by_driver_date.get(key_e) or []
        if sess:
            return list(sess)
        emp = route_ent.employee_id
        dt = str(route_ent.date)[:10]
        drv_e = int(emp) if emp else 0
        merged: List[int] = []
        seen_m = set()
        for (_cid, mid, dtk), hlist in route_by_client_driver_date.items():
            if mid != emp or dtk != dt:
                continue
            for hid in hlist or []:
                try:
                    h = int(hid)
                except (TypeError, ValueError):
                    continue
                if h > 0 and h != drv_e and h not in seen_m:
                    seen_m.add(h)
                    merged.append(h)
        if merged:
            return merged
        return list(day_union_helpers.get(key_e) or [])

    ent_daily_by_ajudante: Dict[int, Dict[str, int]] = defaultdict(dict)
    for r in routes_delivered:
        ids = _helpers_for_entregue_stop(r)
        if not ids:
            continue
        seen_h = set()
        drv = int(r.employee_id) if r.employee_id else 0
        day = str(r.date)[:10]
        if len(day) < 10:
            continue
        for hid in ids:
            try:
                h = int(hid)
            except (TypeError, ValueError):
                continue
            if h <= 0 or h == drv or h in seen_h:
                continue
            seen_h.add(h)
            cur = ent_daily_by_ajudante[h].get(day, 0)
            ent_daily_by_ajudante[h][day] = cur + 1

    devs_by_ajudante: Dict[int, List[models.Devolucao]] = defaultdict(list)
    for d in devolucoes:
        # Mesma regra da lista / modal: toda a equipe da rota que aparece em ajudante_ids enxerga a devolução,
        # não só o primeiro helper (evita % e R$ zerados para o 2º ajudante).
        for hid in effective_ajudante_ids_for_summary(
            d, route_helpers, route_by_client_driver_date, session_helpers_by_driver_date
        ):
            devs_by_ajudante[int(hid)].append(d)

    out_ajudantes = []
    # Inclui ajudantes com devoluções e também os que só tiveram entregas no período.
    all_ajudante_ids = sorted(set(devs_by_ajudante.keys()) | set(ent_daily_by_ajudante.keys()))
    # Garante nome dos ajudantes que só aparecem nas entregas (sem devolução no período).
    missing_emp_ids = [eid for eid in all_ajudante_ids if eid not in employees]
    if missing_emp_ids:
        extra_emps = session.exec(select(models.Employee).where(models.Employee.id.in_(missing_emp_ids))).all()
        for emp in extra_emps:
            if getattr(emp, "id", None) is not None:
                employees[int(emp.id)] = emp
    # Evita exibir linhas órfãs ("Motorista/Ajudante #id") no resumo quando o colaborador não existe mais.
    all_ajudante_ids = [eid for eid in all_ajudante_ids if eid in employees]
    for eid in all_ajudante_ids:
        mine = devs_by_ajudante[eid]
        ent_by_d = dict(ent_daily_by_ajudante.get(eid, {}))
        emp = employees.get(eid)
        name = emp.name if emp else f"Ajudante #{eid}"
        b = build_ajudante_consolidation_pure(
            mine, ent_by_d, date_from, date_to, ajustes, int(eid), name, include_daily=False
        )
        out_ajudantes.append(b["row"])
    out_ajudantes.sort(key=lambda x: (-x["devolucoes_total"], x["ajudante_name"]))

    return {"data": out, "data_ajudantes": out_ajudantes}


def motorista_consolidado_row_dict(
    motorista_id: int,
    motorista_name: str,
    entregues: int,
    devolucoes_total: int,
    devolucoes_valor_total: float,
    devolucoes_attributed: int,
    devolucoes_valor_attributed: float,
) -> Dict[str, Any]:
    """
    Linha consolidada de motorista — ÚNICA fonte de fórmula/arredondamento para:
    - GET /api/devolucoes/avaliar/consolidado/resumo (tabela desktop)
    - mobile bundle / returns-data
    """
    ent = int(entregues or 0)
    dev_t = int(devolucoes_total or 0)
    dev_a = int(devolucoes_attributed or 0)
    vtot = float(devolucoes_valor_total or 0.0)
    vadj = float(devolucoes_valor_attributed or 0.0)
    total_paradas = ent + dev_t
    pct_original = (dev_t / total_paradas * 100) if total_paradas else 0.0
    total_attributed = ent + dev_a
    pct_ajustado = (dev_a / total_attributed * 100) if total_attributed else 0.0
    premio = _return_rate_to_prize(pct_ajustado)
    return {
        "motorista_id": motorista_id,
        "motorista_name": motorista_name,
        "entregues": ent,
        "devolucoes_total": dev_t,
        "devolucoes_valor_total": round(vtot, 2),
        "devolucoes_attributed": dev_a,
        "devolucoes_valor_attributed": round(vadj, 2),
        "pct_original": round(pct_original, 2),
        "pct_ajustado": round(pct_ajustado, 2),
        "valor_original": round(vtot, 2),
        "valor_ajustado": round(vadj, 2),
        "premio": round(float(premio), 2),
    }


def ajudante_consolidado_row_dict(
    ajudante_id: int,
    ajudante_name: str,
    entregues: int,
    devolucoes_total: int,
    devolucoes_valor_total: float,
    devolucoes_attributed: int,
    devolucoes_valor_attributed: float,
) -> Dict[str, Any]:
    """Linha consolidada de ajudante — mesma fórmula desktop + mobile."""
    ent = int(entregues or 0)
    dev_t = int(devolucoes_total or 0)
    dev_a = int(devolucoes_attributed or 0)
    vtot = float(devolucoes_valor_total or 0.0)
    vadj = float(devolucoes_valor_attributed or 0.0)
    total_paradas = ent + dev_t
    pct_original = (dev_t / total_paradas * 100) if total_paradas > 0 else (100.0 if dev_t else 0.0)
    total_ajust = ent + dev_a
    pct_ajustado = (dev_a / total_ajust * 100) if total_ajust > 0 else 0.0
    premio = _return_rate_to_prize(pct_ajustado)
    return {
        "ajudante_id": ajudante_id,
        "ajudante_name": ajudante_name,
        "entregues": ent,
        "devolucoes_total": dev_t,
        "devolucoes_valor_total": round(vtot, 2),
        "devolucoes_attributed": dev_a,
        "devolucoes_valor_attributed": round(vadj, 2),
        "pct_original": round(pct_original, 2),
        "pct_ajustado": round(pct_ajustado, 2),
        "valor_original": round(vtot, 2),
        "valor_ajustado": round(vadj, 2),
        "premio": round(float(premio), 2),
    }


def build_motorista_consolidation_pure(
    devolucoes: List[models.Devolucao],
    ent_by_day: Dict[str, int],
    date_from: str,
    date_to: str,
    ajustes: Dict[int, Tuple[bool, bool]],
    motorista_id: int,
    motorista_name: str,
    *,
    include_daily: bool = True,
) -> Dict[str, Any]:
    """
    NÚCLEO ÚNICO motorista: totais + (opcional) série diária.
    - Agrupamento por dia: sempre `data_romaneio` (YYYY-MM-DD), alinhado à listagem / desktop.
    - Entregues por dia: `ent_by_day` (rotas entregues do motorista na data da rota).
    """
    date_from = date_from or "2020-01-01"
    date_to = date_to or "2099-12-31"
    ent_n = int(sum(int(v) for v in (ent_by_day or {}).values()))

    by_day: Dict[str, List[models.Devolucao]] = defaultdict(list)
    for d in devolucoes:
        day = str(d.data_romaneio or "")[:10]
        if len(day) < 10:
            continue
        by_day[day].append(d)

    devolucoes_total = len(devolucoes)
    devolucoes_valor_total = sum(float(d.valor or 0) for d in devolucoes)
    devolucoes_attributed = sum(1 for d in devolucoes if ajustes.get(d.id, (True, True))[0])
    devolucoes_valor_attributed = sum(float(d.valor or 0) for d in devolucoes if ajustes.get(d.id, (True, True))[0])

    row = motorista_consolidado_row_dict(
        motorista_id,
        motorista_name,
        ent_n,
        devolucoes_total,
        devolucoes_valor_total,
        devolucoes_attributed,
        devolucoes_valor_attributed,
    )

    if not include_daily:
        return {
            "row": row,
            "chart_dates_iso": [],
            "chart_labels": [],
            "chart_values": [],
            "chart_adjusted_values": [],
            "chart_percents": [],
            "chart_adjusted_percents": [],
            "_series_checks": None,
            "_daily_by_iso": None,
        }

    daily_by_iso: Dict[str, Dict[str, Any]] = {}

    for day in _iter_days_inclusive(date_from, date_to):
        ent_d = int(ent_by_day.get(day, 0))
        devs = list(by_day.get(day, []))
        st = _motorista_day_stats_raw(devs, ent_d, ajustes)
        daily_by_iso[day] = {
            "entregues": ent_d,
            "devolucoes_count": len(devs),
            "valor_original": st["valor_original"],
            "valor_ajustado": st["valor_ajustado"],
            "pct_original": st["pct_original"],
            "pct_ajustado": st["pct_ajustado"],
            "devolucao_ids": [int(d.id) for d in devs if getattr(d, "id", None)],
            "devolucao_ids_ajustadas": [
                int(d.id) for d in devs if getattr(d, "id", None) and ajustes.get(d.id, (True, True))[0]
            ],
        }

    (
        chart_dates_iso,
        chart_labels,
        chart_values,
        chart_adjusted_values,
        chart_percents,
        chart_adjusted_percents,
    ) = _series_arrays_from_daily_by_iso(daily_by_iso, date_from, date_to)

    sum_series_o = sum(chart_values)
    sum_series_a = sum(chart_adjusted_values)
    ok_o = _float_series_matches_total(sum_series_o, devolucoes_valor_total)
    ok_a = _float_series_matches_total(sum_series_a, devolucoes_valor_attributed)
    if not ok_o or not ok_a:
        logger.error(
            "Fechamento série devoluções motorista (núcleo puro) falhou",
            extra={
                "motorista_id": motorista_id,
                "sum_series_original": sum_series_o,
                "valor_periodo_original": devolucoes_valor_total,
                "sum_series_adjusted": sum_series_a,
                "valor_periodo_adjusted": devolucoes_valor_attributed,
                "since": date_from,
                "until": date_to,
            },
        )

    return {
        "row": row,
        "chart_dates_iso": chart_dates_iso,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "chart_adjusted_values": chart_adjusted_values,
        "chart_percents": chart_percents,
        "chart_adjusted_percents": chart_adjusted_percents,
        "_series_checks": {
            "sum_original_matches": ok_o,
            "sum_adjusted_matches": ok_a,
            "sum_series_original": sum_series_o,
            "sum_series_adjusted": sum_series_a,
            "valor_periodo_original": devolucoes_valor_total,
            "valor_periodo_adjusted": devolucoes_valor_attributed,
            "ent_scalar": ent_n,
            "sum_ent_by_day": sum(int(v) for v in ent_by_day.values()),
            "grouping_field": "data_romaneio",
        },
        "_daily_by_iso": daily_by_iso,
    }


def build_ajudante_consolidation_pure(
    mine: List[models.Devolucao],
    ent_by_day: Dict[str, int],
    date_from: str,
    date_to: str,
    ajustes: Dict[int, Tuple[bool, bool]],
    ajudante_id: int,
    ajudante_name: str,
    *,
    include_daily: bool = True,
) -> Dict[str, Any]:
    """
    NÚCLEO ÚNICO ajudante: totais + série diária (A = responsavel_ajudante).
    Agrupamento por dia: `data_romaneio` (igual motorista / desktop).
    """
    date_from = date_from or "2020-01-01"
    date_to = date_to or "2099-12-31"
    ent_n = int(sum(int(v) for v in (ent_by_day or {}).values()))

    by_day: Dict[str, List[models.Devolucao]] = defaultdict(list)
    for d in mine:
        day = str(d.data_romaneio or "")[:10]
        if len(day) < 10:
            continue
        by_day[day].append(d)

    dev_t = len(mine)
    valor_t = sum(float(d.valor or 0) for d in mine)
    dev_a = sum(1 for d in mine if ajustes.get(d.id, (True, True))[1])
    valor_a = sum(float(d.valor or 0) for d in mine if ajustes.get(d.id, (True, True))[1])

    row = ajudante_consolidado_row_dict(
        ajudante_id,
        ajudante_name,
        ent_n,
        dev_t,
        valor_t,
        dev_a,
        valor_a,
    )

    if not include_daily:
        return {
            "row": row,
            "chart_dates_iso": [],
            "chart_labels": [],
            "chart_values": [],
            "chart_adjusted_values": [],
            "chart_percents": [],
            "chart_adjusted_percents": [],
            "_series_checks": None,
            "_daily_by_iso": None,
        }

    daily_by_iso: Dict[str, Dict[str, Any]] = {}

    for day in _iter_days_inclusive(date_from, date_to):
        ent_d = int(ent_by_day.get(day, 0))
        devs = list(by_day.get(day, []))
        dev_td = len(devs)
        valor_o = sum(float(d.valor or 0) for d in devs)
        dev_ad = sum(1 for d in devs if ajustes.get(d.id, (True, True))[1])
        valor_ad = sum(float(d.valor or 0) for d in devs if ajustes.get(d.id, (True, True))[1])
        total_paradas = ent_d + dev_td
        pct_original = (dev_td / total_paradas * 100) if total_paradas > 0 else (100.0 if dev_td else 0.0)
        total_ajust = ent_d + dev_ad
        pct_ajustado = (dev_ad / total_ajust * 100) if total_ajust > 0 else 0.0
        daily_by_iso[day] = {
            "entregues": ent_d,
            "devolucoes_count": dev_td,
            "valor_original": float(valor_o),
            "valor_ajustado": float(valor_ad),
            "pct_original": float(pct_original),
            "pct_ajustado": float(pct_ajustado),
            "devolucao_ids": [int(d.id) for d in devs if getattr(d, "id", None)],
            "devolucao_ids_ajustadas": [
                int(d.id) for d in devs if getattr(d, "id", None) and ajustes.get(d.id, (True, True))[1]
            ],
        }

    (
        chart_dates_iso,
        chart_labels,
        chart_values,
        chart_adjusted_values,
        chart_percents,
        chart_adjusted_percents,
    ) = _series_arrays_from_daily_by_iso(daily_by_iso, date_from, date_to)

    sum_series_o = sum(chart_values)
    sum_series_a = sum(chart_adjusted_values)
    ok_o = _float_series_matches_total(sum_series_o, valor_t)
    ok_a = _float_series_matches_total(sum_series_a, valor_a)
    if not ok_o or not ok_a:
        logger.error(
            "Fechamento série devoluções ajudante (núcleo puro) falhou",
            extra={
                "ajudante_id": ajudante_id,
                "sum_series_original": sum_series_o,
                "valor_periodo_original": valor_t,
                "sum_series_adjusted": sum_series_a,
                "valor_periodo_adjusted": valor_a,
                "since": date_from,
                "until": date_to,
            },
        )

    return {
        "row": row,
        "chart_dates_iso": chart_dates_iso,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "chart_adjusted_values": chart_adjusted_values,
        "chart_percents": chart_percents,
        "chart_adjusted_percents": chart_adjusted_percents,
        "_series_checks": {
            "sum_original_matches": ok_o,
            "sum_adjusted_matches": ok_a,
            "sum_series_original": sum_series_o,
            "sum_series_adjusted": sum_series_a,
            "valor_periodo_original": valor_t,
            "valor_periodo_adjusted": valor_a,
            "ent_sum_by_day": ent_n,
            "grouping_field": "data_romaneio",
        },
        "_daily_by_iso": daily_by_iso,
    }


def _motorista_day_stats_raw(
    devolucoes_day: List[models.Devolucao],
    entregues_d: int,
    ajustes: Dict[int, Tuple[bool, bool]],
) -> Dict[str, float]:
    """Métricas diárias motorista: valores em float pleno; % com precisão de cálculo (exibição arredonda na ponta)."""
    dev_total = len(devolucoes_day)
    valor_o = sum(float(d.valor or 0) for d in devolucoes_day)
    dev_attr = sum(1 for d in devolucoes_day if ajustes.get(d.id, (True, True))[0])
    valor_a = sum(float(d.valor or 0) for d in devolucoes_day if ajustes.get(d.id, (True, True))[0])
    total_paradas = entregues_d + dev_total
    pct_original = (dev_total / total_paradas * 100) if total_paradas else 0.0
    total_attributed = entregues_d + dev_attr
    pct_ajustado = (dev_attr / total_attributed * 100) if total_attributed else 0.0
    return {
        "valor_original": float(valor_o),
        "valor_ajustado": float(valor_a),
        "pct_original": float(pct_original),
        "pct_ajustado": float(pct_ajustado),
    }


def motorista_returns_mobile_bundle(
    session: Session, motorista_id: int, date_from: str, date_to: str
) -> Dict[str, Any]:
    """
    Carrega dados do período e delega ao núcleo `build_motorista_consolidation_pure`
    (o mesmo núcleo usado pelo resumo desktop com include_daily=False).
    """
    date_from = date_from or "2020-01-01"
    date_to = date_to or "2099-12-31"

    devolucoes = session.exec(
        select(models.Devolucao)
        .where(models.Devolucao.data_romaneio >= date_from)
        .where(models.Devolucao.data_romaneio <= date_to)
        .where(models.Devolucao.motorista_id == motorista_id)
        .order_by(models.Devolucao.id)
    ).all()
    devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]

    ent_by_day = motorista_entregues_by_day(session, motorista_id, date_from, date_to)
    sum_ent_day = sum(ent_by_day.values())
    ent_scalar = _scalar_count(
        session.exec(
            select(func.count())
            .select_from(models.Route)
            .where(models.Route.type == "delivery")
            .where(models.Route.date >= date_from)
            .where(models.Route.date <= date_to)
            .where(models.Route.delivery_status == "entregue")
            .where(models.Route.employee_id == motorista_id)
        ).one()
    )
    if sum_ent_day != ent_scalar:
        logger.warning(
            "motorista entregues: soma diária difere do count no período",
            extra={
                "motorista_id": motorista_id,
                "ent_scalar": ent_scalar,
                "sum_by_day": sum_ent_day,
                "since": date_from,
                "until": date_to,
            },
        )

    ajustes = load_ajustes_map(session)
    emp = session.get(models.Employee, motorista_id)
    name = emp.name if emp else f"Motorista #{motorista_id}"

    bundle = build_motorista_consolidation_pure(
        devolucoes, ent_by_day, date_from, date_to, ajustes, motorista_id, name, include_daily=True
    )
    checks = bundle.get("_series_checks")
    if isinstance(checks, dict):
        checks["ent_route_count_verify"] = ent_scalar
    return bundle


def motorista_consolidado_periodo(session: Session, motorista_id: int, date_from: str, date_to: str) -> Dict[str, Any]:
    """Uma linha do resumo por motorista (mesma fórmula do desktop); derivada do mesmo bundle do mobile."""
    return dict(motorista_returns_mobile_bundle(session, motorista_id, date_from, date_to)["row"])


def ajudante_returns_mobile_bundle(
    session: Session, ajudante_id: int, date_from: str, date_to: str
) -> Dict[str, Any]:
    """
    Consolidação única para mobile (ajudante): mesma base do desktop (A = responsavel_ajudante).
    Série diária: um ponto por dia civil no intervalo; soma da série = totais do período.
    """
    date_from = date_from or "2020-01-01"
    date_to = date_to or "2099-12-31"

    route_helpers, route_by_client_driver_date, session_helpers_by_driver_date, _emp_by_name = _build_helper_maps(
        session, date_from, date_to
    )

    devolucoes = session.exec(
        select(models.Devolucao)
        .where(models.Devolucao.data_romaneio >= date_from)
        .where(models.Devolucao.data_romaneio <= date_to)
        .order_by(models.Devolucao.id)
    ).all()
    devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]
    ajustes = load_ajustes_map(session)

    mine_by_day: Dict[str, List[models.Devolucao]] = {}
    for d in devolucoes:
        ids_d = effective_ajudante_ids_for_summary(
            d, route_helpers, route_by_client_driver_date, session_helpers_by_driver_date
        )
        if ajudante_id not in ids_d:
            continue
        day = str(d.data_romaneio or "")[:10]
        if len(day) < 10:
            continue
        mine_by_day.setdefault(day, []).append(d)

    routes_delivered = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= date_from)
        .where(models.Route.date <= date_to)
        .where(models.Route.delivery_status == "entregue")
    ).all()

    routes_in_range = session.exec(
        select(models.Route)
        .where(models.Route.date >= date_from)
        .where(models.Route.date <= date_to)
        .where(models.Route.client_id.is_not(None))
        .where(models.Route.employee_id.is_not(None))
    ).all()
    emp_by_name = {
        e.name.strip().lower(): e.id
        for e in session.exec(select(models.Employee)).all()
        if e and getattr(e, "name", None) and getattr(e, "id", None)
    }

    day_union_helpers: Dict[tuple, List[int]] = {}
    for r in routes_in_range:
        key_d = (str(r.date)[:10], r.employee_id)
        raw_u = getattr(r, "delivery_helpers_json", None)
        ids_u = parse_route_helper_ids(raw_u) or parse_helpers_to_ids(raw_u, emp_by_name)
        drv_u = int(r.employee_id) if r.employee_id else 0
        acc = day_union_helpers.setdefault(key_d, [])
        seen_u = set(acc)
        for hid in ids_u or []:
            try:
                hu = int(hid)
            except (TypeError, ValueError):
                continue
            if hu <= 0 or hu == drv_u or hu in seen_u:
                continue
            seen_u.add(hu)
            acc.append(hu)

    def _helpers_for_entregue_stop(route_ent: models.Route) -> List[int]:
        key_e = (str(route_ent.date)[:10], route_ent.employee_id)
        raw_e = getattr(route_ent, "delivery_helpers_json", None)
        ids_e = parse_route_helper_ids(raw_e) or parse_helpers_to_ids(raw_e, emp_by_name)
        if ids_e:
            return ids_e
        sess = session_helpers_by_driver_date.get(key_e) or []
        if sess:
            return list(sess)
        emp = route_ent.employee_id
        dt = str(route_ent.date)[:10]
        drv_e = int(emp) if emp else 0
        merged: List[int] = []
        seen_m = set()
        for (_cid, mid, dtk), hlist in route_by_client_driver_date.items():
            if mid != emp or dtk != dt:
                continue
            for hid in hlist or []:
                try:
                    h = int(hid)
                except (TypeError, ValueError):
                    continue
                if h > 0 and h != drv_e and h not in seen_m:
                    seen_m.add(h)
                    merged.append(h)
        if merged:
            return merged
        return list(day_union_helpers.get(key_e) or [])

    entregues_por_dia: Dict[str, int] = {}
    for r in routes_delivered:
        ids = _helpers_for_entregue_stop(r)
        if not ids:
            continue
        seen_h = set()
        drv = int(r.employee_id) if r.employee_id else 0
        day = str(r.date)[:10]
        for hid in ids:
            try:
                h = int(hid)
            except (TypeError, ValueError):
                continue
            if h <= 0 or h == drv or h in seen_h:
                continue
            seen_h.add(h)
            if h == ajudante_id:
                entregues_por_dia[day] = entregues_por_dia.get(day, 0) + 1

    all_mine: List[models.Devolucao] = []
    for devs in mine_by_day.values():
        all_mine.extend(devs)

    emp = session.get(models.Employee, ajudante_id)
    name = emp.name if emp else f"Ajudante #{ajudante_id}"

    return build_ajudante_consolidation_pure(
        all_mine,
        entregues_por_dia,
        date_from,
        date_to,
        ajustes,
        ajudante_id,
        name,
        include_daily=True,
    )


def ajudante_consolidado_periodo(session: Session, ajudante_id: int, date_from: str, date_to: str) -> Dict[str, Any]:
    """Uma linha do resumo por ajudante (mesma fórmula do desktop); derivada do mesmo bundle do mobile."""
    return dict(ajudante_returns_mobile_bundle(session, ajudante_id, date_from, date_to)["row"])


def build_returns_consolidated_bundle(
    session: Session,
    role: Literal["motorista", "ajudante"],
    collaborator_id: int,
    date_from: str,
    date_to: str,
) -> Dict[str, Any]:
    """
    API central: um colaborador + papel + período → bundle completo (linha + série + auditoria diária).
    Usado pelo mobile; o desktop usa o mesmo núcleo puro via `consolidado_avaliar_resumo` (sem série).
    """
    if role == "motorista":
        return motorista_returns_mobile_bundle(session, collaborator_id, date_from, date_to)
    return ajudante_returns_mobile_bundle(session, collaborator_id, date_from, date_to)


def top_clients_motorista(session: Session, motorista_id: int, date_from: str, date_to: str) -> List[Dict[str, Any]]:
    """Agrega valor devolvido por cliente (apenas Devolução, motorista)."""
    devolucoes = session.exec(
        select(models.Devolucao)
        .where(models.Devolucao.data_romaneio >= date_from)
        .where(models.Devolucao.data_romaneio <= date_to)
        .where(models.Devolucao.motorista_id == motorista_id)
    ).all()
    devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]
    client_ids = list({d.client_id for d in devolucoes if d.client_id})
    clients = (
        session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all() if client_ids else []
    )
    client_map = {c.id: c for c in clients}
    top_clients_map: Dict[str, Dict[str, Any]] = {}
    for d in devolucoes:
        c = client_map.get(d.client_id)
        name = (c.razao_social or c.name or "Cliente") if c else "Cliente"
        val = float(d.valor or 0)
        existing = top_clients_map.get(name)
        if existing:
            existing["value"] = existing.get("value", 0) + val
            existing["count"] = existing.get("count", 0) + 1
        else:
            top_clients_map[name] = {"name": name, "value": val, "volume": 0.0, "count": 1}
    return sorted(top_clients_map.values(), key=lambda x: x.get("value", 0), reverse=True)


def top_clients_ajudante(session: Session, ajudante_id: int, date_from: str, date_to: str) -> List[Dict[str, Any]]:
    """Agrega por cliente onde o ajudante efetivo é o colaborador."""
    route_helpers, route_by_client_driver_date, session_helpers_by_driver_date, _ = _build_helper_maps(
        session, date_from, date_to
    )
    devolucoes = session.exec(
        select(models.Devolucao)
        .where(models.Devolucao.data_romaneio >= date_from)
        .where(models.Devolucao.data_romaneio <= date_to)
    ).all()
    devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]
    filtered = [
        d
        for d in devolucoes
        if ajudante_id
        in effective_ajudante_ids_for_summary(
            d, route_helpers, route_by_client_driver_date, session_helpers_by_driver_date
        )
    ]
    client_ids = list({d.client_id for d in filtered if d.client_id})
    clients = (
        session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all() if client_ids else []
    )
    client_map = {c.id: c for c in clients}
    top_clients_map: Dict[str, Dict[str, Any]] = {}
    for d in filtered:
        c = client_map.get(d.client_id)
        name = (c.razao_social or c.name or "Cliente") if c else "Cliente"
        val = float(d.valor or 0)
        existing = top_clients_map.get(name)
        if existing:
            existing["value"] = existing.get("value", 0) + val
            existing["count"] = existing.get("count", 0) + 1
        else:
            top_clients_map[name] = {"name": name, "value": val, "volume": 0.0, "count": 1}
    return sorted(top_clients_map.values(), key=lambda x: x.get("value", 0), reverse=True)


def returns_mobile_bundle_for_user(
    session: Session, user_id: int, date_from: str, date_to: str
) -> Tuple[str, Dict[str, Any]]:
    """
    Uma única escolha motorista vs ajudante + bundle completo (linha + série diária).
    Prioriza motorista se houver entregas ou devoluções como motorista no período.
    """
    date_from = date_from or "2020-01-01"
    date_to = date_to or "2099-12-31"
    mb = build_returns_consolidated_bundle(session, "motorista", user_id, date_from, date_to)
    mr = mb["row"]
    if int(mr.get("entregues") or 0) > 0 or int(mr.get("devolucoes_total") or 0) > 0:
        return "motorista", mb
    ab = build_returns_consolidated_bundle(session, "ajudante", user_id, date_from, date_to)
    ar = ab["row"]
    if int(ar.get("entregues") or 0) > 0 or int(ar.get("devolucoes_total") or 0) > 0:
        return "ajudante", ab
    return "motorista", mb


def pick_consolidado_for_mobile_user(
    session: Session, user_id: int, date_from: str, date_to: str
) -> Tuple[str, Dict[str, Any]]:
    """
    Escolhe visão motorista vs ajudante: prioriza motorista se houver entregas ou devoluções como motorista.
    Retorna ("motorista"|"ajudante", row_dict).
    """
    role, bundle = returns_mobile_bundle_for_user(session, user_id, date_from, date_to)
    return role, dict(bundle["row"])
