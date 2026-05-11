"""
Motor de planejamento inteligente de férias — logística de bebidas.

Lógica explícita: pontuação 0–100, janelas verde/amarelo/vermelho, limites por função
ajustados pela demanda do mês (tabela VacationMonthDemand ou régua padrão).
"""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import desc
from sqlmodel import Session, col, select

import models

MONTH_NAMES_PT = (
    "",
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)

# Índice de demanda 0 (muito baixa) a 100 (pico). Calibrável por mês no cadastro.
DEFAULT_DEMAND_BY_MONTH: Dict[int, int] = {
    1: 52,
    2: 42,
    3: 42,
    4: 38,
    5: 22,
    6: 32,
    7: 32,
    8: 18,
    9: 44,
    10: 58,
    11: 78,
    12: 92,
}

ROLE_DEFAULT_LIMIT: Dict[str, int] = {
    "MOTORISTA": 2,
    "AJUDANTE": 3,
    "CONFERENTE": 1,
    "SEPARADOR": 2,
    "CARREGAMENTO": 2,
    "EXPEDICAO": 2,
    "ADMINISTRATIVO": 1,
    "OUTROS": 2,
}

CRITICALITY_RANK = {"baixa": 1, "media": 2, "alta": 3, "muito_alta": 4}

RECOMMENDATION_LABEL_PT = {
    "aprovado": "Recomendado",
    "atencao": "Atenção",
    "nao_recomendado": "Não recomendado",
}


def default_demand_index_for_month(month: int) -> int:
    return DEFAULT_DEMAND_BY_MONTH.get(int(month), 50)


def validate_function_limits_json(raw: Any) -> Tuple[Optional[Dict[str, int]], Optional[str]]:
    """
    Valida JSON opcional de limites por função (ex.: {"MOTORISTA": 1}).
    Objeto vazio ou None → None (usa régua do motor).
    """
    if raw is None:
        return None, None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None, None
        try:
            raw = json.loads(s)
        except json.JSONDecodeError:
            return None, "JSON de limites por função inválido."
    if not isinstance(raw, dict):
        return None, "Limites por função devem ser um objeto JSON (mapa função → número)."
    if len(raw) == 0:
        return None, None
    out: Dict[str, int] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if not key:
            return None, "Chaves de função não podem ser vazias."
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None, f"Valor inválido para a função {key!r}: use inteiro ≥ 0."
        if iv < 0:
            return None, f"Limite para {key!r} não pode ser negativo."
        out[key.upper()] = iv
    return out, None


def month_demand_calendar(session: Session, year: int) -> Dict[str, Any]:
    """12 meses com índice efetivo, origem (padrão/calibrado) e metadados."""
    y = int(year)
    months: List[Dict[str, Any]] = []
    for m in range(1, 13):
        row = session.exec(
            select(models.VacationMonthDemand).where(
                models.VacationMonthDemand.year == y,
                models.VacationMonthDemand.month == m,
            )
        ).first()
        default_idx = default_demand_index_for_month(m)
        if row:
            months.append(
                {
                    "month": m,
                    "month_name": MONTH_NAMES_PT[m],
                    "demand_index": row.demand_index,
                    "default_demand_index": default_idx,
                    "risk_notes": row.risk_notes,
                    "function_limits_json": row.role_limits_json,
                    "source": "calibrated",
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
            )
        else:
            months.append(
                {
                    "month": m,
                    "month_name": MONTH_NAMES_PT[m],
                    "demand_index": default_idx,
                    "default_demand_index": default_idx,
                    "risk_notes": None,
                    "function_limits_json": None,
                    "source": "default",
                    "updated_at": None,
                }
            )
    return {"year": y, "months": months}


def upsert_vacation_month_demand(
    session: Session,
    *,
    year: int,
    month: int,
    demand_index: int,
    risk_notes: Optional[str],
    function_limits_json: Any,
) -> Tuple[Optional[models.VacationMonthDemand], Optional[str]]:
    if not (1 <= int(month) <= 12):
        return None, "Mês deve estar entre 1 e 12."
    di = int(demand_index)
    if not (0 <= di <= 100):
        return None, "demand_index deve estar entre 0 e 100."
    limits, err = validate_function_limits_json(function_limits_json)
    if err:
        return None, err
    y = int(year)
    m = int(month)
    row = session.exec(
        select(models.VacationMonthDemand).where(
            models.VacationMonthDemand.year == y,
            models.VacationMonthDemand.month == m,
        )
    ).first()
    if not row:
        row = models.VacationMonthDemand(year=y, month=m)
        session.add(row)
    row.demand_index = di
    row.risk_notes = (risk_notes or "").strip() or None
    row.role_limits_json = limits
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, None


def vacation_profile_get(session: Session, employee_id: int) -> Optional[Dict[str, Any]]:
    emp = session.get(models.Employee, employee_id)
    if not emp:
        return None
    prof = session.exec(
        select(models.EmployeeVacationProfile).where(
            models.EmployeeVacationProfile.employee_id == employee_id
        )
    ).first()

    def iso_d(dt: Optional[datetime]) -> Optional[str]:
        d = _d(dt)
        return d.isoformat() if d else None

    empty_profile = {
        "has_record": False,
        "department_sector": None,
        "route_team": None,
        "criticality": "media",
        "substitute_employee_id": None,
        "substitute_trained": False,
        "fixed_route": False,
        "specific_knowledge": False,
        "peak_area_worker": False,
        "same_role_headcount_override": None,
        "acquisition_period_end": None,
        "last_vacation_end": None,
        "vacation_days_available": None,
        "notes": None,
        "updated_at": None,
    }

    if not prof:
        return {
            "employee_id": emp.id,
            "name": emp.name,
            "role": emp.role,
            "cost_center": emp.cost_center,
            "vacation_profile": empty_profile,
        }

    return {
        "employee_id": emp.id,
        "name": emp.name,
        "role": emp.role,
        "cost_center": emp.cost_center,
        "vacation_profile": {
            "has_record": True,
            "department_sector": prof.department_sector,
            "route_team": prof.route_team,
            "criticality": prof.criticality,
            "substitute_employee_id": prof.substitute_employee_id,
            "substitute_trained": bool(prof.substitute_trained),
            "fixed_route": bool(prof.fixed_route),
            "specific_knowledge": bool(prof.specific_knowledge),
            "peak_area_worker": bool(prof.peak_area_worker),
            "same_role_headcount_override": prof.same_role_headcount_override,
            "acquisition_period_end": iso_d(prof.acquisition_period_end),
            "last_vacation_end": iso_d(prof.last_vacation_end),
            "vacation_days_available": prof.vacation_days_available,
            "notes": prof.notes,
            "updated_at": prof.updated_at.isoformat() if prof.updated_at else None,
        },
    }


def try_sync_employee_vacation_fields(
    session: Session,
    employee: models.Employee,
    start: date,
    end: date,
) -> Tuple[bool, str]:
    """Atualiza vacation_start/vacation_end no Employee se existirem no modelo."""
    if not hasattr(employee, "vacation_start") or not hasattr(employee, "vacation_end"):
        return False, "Modelo de colaborador sem campos vacation_start/vacation_end; sincronização não aplicada."
    try:
        employee.vacation_start = datetime.combine(start, datetime.min.time())
        employee.vacation_end = datetime.combine(end, datetime.min.time())
        session.add(employee)
        session.commit()
        session.refresh(employee)
        return True, "Férias sincronizadas no cadastro do colaborador (vacation_start / vacation_end)."
    except Exception as exc:
        session.rollback()
        return False, f"Sincronização com o cadastro falhou: {exc}"


def _build_operational_explanation(
    *,
    recommendation: str,
    blocks: List[str],
    alerts: List[str],
    rb: str,
    concurrent: int,
    demand_max: int,
    sub_ok: bool,
    crit_high: bool,
) -> str:
    if blocks:
        tail = " ".join(blocks[:2])
        return f"Não recomendado: {tail}"

    if recommendation == "atencao":
        parts: List[str] = []
        if concurrent > 0:
            parts.append(
                f"Existe outro colaborador da função {rb} com férias programadas no mesmo período."
            )
        if demand_max >= 75:
            parts.append("O período inclui mês de pico operacional.")
        if crit_high and not sub_ok:
            parts.append("Colaborador crítico sem substituto treinado cadastrado.")
        for a in (alerts or [])[:2]:
            if a not in parts:
                parts.append(a)
        body = " ".join(parts) if parts else "Revise os alertas antes de aprovar."
        return f"Atenção: {body}"

    bits: List[str] = []
    if demand_max <= 38:
        bits.append("Baixa demanda prevista no período.")
    elif demand_max < 58:
        bits.append("Demanda moderada.")
    if sub_ok:
        bits.append("Substituto treinado disponível.")
    elif bool(alerts):
        pass
    if concurrent == 0:
        bits.append("Sem sobreposição de férias na mesma função.")
    if not bits:
        bits.append("Sem bloqueios automáticos no período analisado.")
    return f"Recomendado: {' '.join(bits)}"


def _d(dt: Optional[datetime]) -> Optional[date]:
    if not dt:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    return dt.date()


def role_bucket(role: Optional[str]) -> str:
    r = (role or "").upper()
    if "MOTORIST" in r:
        return "MOTORISTA"
    if "AJUDANT" in r:
        return "AJUDANTE"
    if "CONFERENT" in r:
        return "CONFERENTE"
    if "SEPAR" in r:
        return "SEPARADOR"
    if "CARREG" in r:
        return "CARREGAMENTO"
    if "EXPEDI" in r:
        return "EXPEDICAO"
    if "ADMIN" in r or "ESCRIT" in r:
        return "ADMINISTRATIVO"
    return "OUTROS"


def concessive_deadline(profile: Optional[models.EmployeeVacationProfile]) -> Optional[date]:
    if not profile or not profile.acquisition_period_end:
        return None
    end = _d(profile.acquisition_period_end)
    if not end:
        return None
    return end + timedelta(days=365)


def days_until_deadline(profile: Optional[models.EmployeeVacationProfile], ref: date) -> Optional[int]:
    dl = concessive_deadline(profile)
    if not dl:
        return None
    return (dl - ref).days


def vacation_window_status(demand_index: int) -> Tuple[str, str]:
    if demand_index >= 80:
        return "red", "Pico de demanda — evitar férias salvo exceção."
    if demand_index >= 58:
        return "yellow", "Demanda elevada — exige substituto e controle por função."
    if demand_index <= 38:
        return "green", "Janela favorável — baixa demanda típica."
    return "yellow", "Demanda moderada — planejar com atenção."


def effective_role_limit(
    role_key: str,
    demand_index: int,
    role_limits_override: Optional[Dict[str, int]],
) -> int:
    if role_limits_override:
        if role_key in role_limits_override:
            return max(0, int(role_limits_override[role_key]))
        if "_all" in role_limits_override:
            return max(0, int(role_limits_override["_all"]))
    base = ROLE_DEFAULT_LIMIT.get(role_key, ROLE_DEFAULT_LIMIT["OUTROS"])
    if demand_index >= 88:
        return 0
    if demand_index >= 75:
        return max(0, base - 2)
    if demand_index >= 60:
        return max(0, base - 1)
    if demand_index <= 28:
        return base + 1
    return base


def get_month_demand(
    session: Session,
    year: int,
    month: int,
) -> Tuple[int, Optional[str], Optional[Dict[str, int]]]:
    row = session.exec(
        select(models.VacationMonthDemand).where(
            models.VacationMonthDemand.year == year,
            models.VacationMonthDemand.month == month,
        )
    ).first()
    if row:
        return row.demand_index, row.risk_notes, row.role_limits_json
    return DEFAULT_DEMAND_BY_MONTH.get(month, 50), None, None


def _employee_query(cost_center: Optional[str]):
    q = select(models.Employee).where(col(models.Employee.status) == "active")
    if cost_center and cost_center.strip() and cost_center.strip().lower() not in ("todos", "all"):
        q = q.where(models.Employee.cost_center == cost_center.strip())
    return q


def load_profiles(session: Session) -> Dict[int, models.EmployeeVacationProfile]:
    rows = session.exec(select(models.EmployeeVacationProfile)).all()
    return {p.employee_id: p for p in rows}


def headcount_by_role(session: Session, cost_center: Optional[str]) -> Dict[str, int]:
    employees = session.exec(_employee_query(cost_center)).all()
    c: Dict[str, int] = defaultdict(int)
    for e in employees:
        c[role_bucket(e.role)] += 1
    return dict(c)


def _parse_date_str(s: str) -> date:
    return date.fromisoformat(s.strip()[:10])


def scheduled_windows(
    session: Session,
    from_date: date,
    to_date: date,
    cost_center: Optional[str],
    exclude_employee_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Intervalos de férias já marcadas (cadastro + entradas planejadas)."""
    out: List[Dict[str, Any]] = []
    emps = list(session.exec(_employee_query(cost_center)).all())
    emp_by_id = {e.id: e for e in emps if e.id}

    for e in emps:
        if exclude_employee_id and e.id == exclude_employee_id:
            continue
        vs, ve = _d(e.vacation_start), _d(e.vacation_end)
        if vs and ve and ve >= from_date and vs <= to_date:
            prof = None
            p = session.exec(
                select(models.EmployeeVacationProfile).where(
                    models.EmployeeVacationProfile.employee_id == e.id
                )
            ).first()
            if p:
                prof = p
            out.append(
                {
                    "employee_id": e.id,
                    "name": e.name,
                    "role_bucket": role_bucket(e.role),
                    "route_team": (prof.route_team if prof else None) or "",
                    "start": vs,
                    "end": ve,
                    "source": "employee",
                }
            )

    entries = session.exec(
        select(models.VacationScheduleEntry).where(
            col(models.VacationScheduleEntry.status).in_(["suggested", "approved"])
        )
    ).all()
    for ent in entries:
        if exclude_employee_id and ent.employee_id == exclude_employee_id:
            continue
        vs, ve = _d(ent.start_date), _d(ent.end_date)
        if not vs or not ve or ve < from_date or vs > to_date:
            continue
        e = emp_by_id.get(ent.employee_id)
        if not e:
            continue
        prof = session.exec(
            select(models.EmployeeVacationProfile).where(
                models.EmployeeVacationProfile.employee_id == ent.employee_id
            )
        ).first()
        out.append(
            {
                "employee_id": ent.employee_id,
                "name": e.name,
                "role_bucket": role_bucket(e.role),
                "route_team": (prof.route_team if prof else None) or "",
                "start": vs,
                "end": ve,
                "source": ent.source,
                "entry_id": ent.id,
            }
        )
    return out


def overlaps(a0: date, a1: date, b0: date, b1: date) -> bool:
    return a0 <= b1 and b0 <= a1


def end_of_month(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def count_role_overlapping(
    windows: Sequence[Dict[str, Any]],
    role_key: str,
    start: date,
    end: date,
    skip_employee_id: Optional[int],
) -> int:
    seen: set = set()
    for w in windows:
        eid = w["employee_id"]
        if skip_employee_id and eid == skip_employee_id:
            continue
        if w["role_bucket"] != role_key:
            continue
        if overlaps(start, end, w["start"], w["end"]):
            seen.add(eid)
    return len(seen)


def route_conflict(
    windows: Sequence[Dict[str, Any]],
    route_team: str,
    start: date,
    end: date,
    skip_employee_id: Optional[int],
) -> bool:
    if not (route_team or "").strip():
        return False
    rt = route_team.strip().lower()
    for w in windows:
        if skip_employee_id and w["employee_id"] == skip_employee_id:
            continue
        other = (w.get("route_team") or "").strip().lower()
        if not other or other != rt:
            continue
        if overlaps(start, end, w["start"], w["end"]):
            return True
    return False


@dataclass
class ScoreBreakdown:
    urgency: float
    operational_risk: float
    period_opportunity: float
    coverage: float
    priority_total: float
    details: Dict[str, Any]


def compute_four_scores(
    *,
    profile: Optional[models.EmployeeVacationProfile],
    employee: models.Employee,
    headcount_same_role: int,
    demand_index: int,
    concurrent_same_role: int,
    role_limit: int,
) -> ScoreBreakdown:
    """Quatro notas 0–100 + prioridade composta (interpretação para gestão)."""
    ref = date.today()
    ddead = days_until_deadline(profile, ref)

    urgency = 15.0
    if ddead is not None:
        if ddead < 0:
            urgency = 100.0
        elif ddead <= 30:
            urgency = 85.0
        elif ddead <= 60:
            urgency = 65.0
        elif ddead <= 90:
            urgency = 45.0
        else:
            urgency = max(15.0, 55.0 - ddead / 6.0)

    lv = _d(profile.last_vacation_end) if profile else None
    if lv:
        months_since = (ref - lv).days / 30.44
        urgency = min(100.0, urgency + min(25.0, months_since * 2.5))

    crit_key = (profile.criticality if profile else "media").lower()
    crit_rank = CRITICALITY_RANK.get(crit_key, 2)
    operational_risk = min(100.0, crit_rank * 22.0)
    if profile and profile.substitute_trained and profile.substitute_employee_id:
        operational_risk *= 0.45
    elif profile and profile.substitute_employee_id:
        operational_risk *= 0.72
    else:
        operational_risk = min(100.0, operational_risk + 12.0)

    period_opportunity = max(0.0, min(100.0, 100.0 - float(demand_index)))

    coverage = 50.0
    if headcount_same_role > 0:
        spare = max(0, headcount_same_role - 1 - concurrent_same_role)
        coverage = min(100.0, spare * (100.0 / max(1, headcount_same_role)))

    if role_limit <= 0 and concurrent_same_role > 0:
        coverage *= 0.35

    priority_linear = (
        urgency * 0.28
        + period_opportunity * 0.22
        + coverage * 0.22
        + (100.0 - operational_risk) * 0.18
        + (20.0 if demand_index <= 35 else (-15.0 if demand_index >= 72 else 0.0))
    )
    priority_total = max(0.0, min(100.0, priority_linear))

    return ScoreBreakdown(
        urgency=round(urgency, 1),
        operational_risk=round(operational_risk, 1),
        period_opportunity=round(period_opportunity, 1),
        coverage=round(coverage, 1),
        priority_total=round(priority_total, 1),
        details={
            "days_until_deadline": ddead,
            "criticality": crit_key,
            "demand_index": demand_index,
            "concurrent_same_role": concurrent_same_role,
            "role_limit": role_limit,
            "headcount_same_role": headcount_same_role,
        },
    )


def priority_index_for_month(
    *,
    profile: Optional[models.EmployeeVacationProfile],
    employee: models.Employee,
    demand_index: int,
    windows: Sequence[Dict[str, Any]],
    month_start: date,
    headcount_by_role_map: Dict[str, int],
) -> Tuple[float, List[str]]:
    """Índice 0–100 estilo checklist (pesos explícitos para a UI)."""
    reasons: List[str] = []
    score = 0.0
    rb = role_bucket(employee.role)
    ref = date.today()
    ddead = days_until_deadline(profile, ref)

    if ddead is not None and ddead < 0:
        score += 40
        reasons.append("Férias em atraso (risco trabalhista).")
    elif ddead is not None and ddead <= 60:
        score += 25
        reasons.append("Prazo concessivo crítico (até 60 dias).")
    elif ddead is not None and ddead <= 90:
        score += 15
        reasons.append("Concessivo se aproxima (até 90 dias).")

    if profile and profile.substitute_trained and profile.substitute_employee_id:
        score += 20
        reasons.append("Substituto treinado cadastrado.")
    elif profile and profile.substitute_employee_id:
        score += 10
        reasons.append("Substituto indicado (validar treinamento).")

    crit = (profile.criticality if profile else "media").lower()
    if crit in ("baixa", "media"):
        score += 15
        reasons.append("Criticidade moderada para a operação.")
    elif crit == "muito_alta":
        score -= 10
        reasons.append("Função muito crítica — exige cobertura.")

    if demand_index <= 38:
        score += 20
        reasons.append("Mês tipicamente de menor demanda.")
    elif demand_index >= 75:
        score -= 30
        reasons.append("Mês de alta demanda operacional.")

    mend = end_of_month(month_start)
    concurrent = count_role_overlapping(windows, rb, month_start, mend, employee.id)
    role_lim = effective_role_limit(rb, demand_index, None)
    if concurrent >= role_lim and role_lim > 0:
        score -= 25
        reasons.append("Limite de férias simultâneas na função já pressionado.")

    headcount = headcount_by_role_map.get(rb, 1)
    if headcount <= 2 and crit in ("alta", "muito_alta"):
        score -= 15
        reasons.append("Poucos colaboradores na função.")

    return max(0.0, min(100.0, score)), reasons


def simulate(
    session: Session,
    *,
    employee_id: int,
    start: date,
    end: date,
    cost_center: Optional[str],
) -> Dict[str, Any]:
    employee = session.get(models.Employee, employee_id)
    if not employee:
        return {"ok": False, "error": "Colaborador não encontrado."}

    profile = session.exec(
        select(models.EmployeeVacationProfile).where(
            models.EmployeeVacationProfile.employee_id == employee_id
        )
    ).first()

    windows = scheduled_windows(
        session, start - timedelta(days=370), end + timedelta(days=370), cost_center
    )
    rb = role_bucket(employee.role)
    hc_map = headcount_by_role(session, cost_center)
    headcount = hc_map.get(rb, 1)

    alerts: List[str] = []
    blocks: List[str] = []

    touched_months: Dict[Tuple[int, int], int] = defaultdict(int)
    d = start
    while d <= end:
        touched_months[(d.year, d.month)] = get_month_demand(session, d.year, d.month)[0]
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)

    demand_max = max(touched_months.values()) if touched_months else 50
    demand_min = min(touched_months.values()) if touched_months else 50
    _, month_note, role_ovr = get_month_demand(session, start.year, start.month)
    role_limit = effective_role_limit(rb, demand_max, role_ovr)

    concurrent = count_role_overlapping(windows, rb, start, end, employee_id)
    if concurrent >= role_limit:
        blocks.append(
            f"Limite de férias simultâneas para {rb} neste período ({concurrent}/{role_limit})."
        )

    crit = (profile.criticality if profile else "media").lower()
    sub_ok = bool(profile and profile.substitute_employee_id and profile.substitute_trained)
    if crit in ("alta", "muito_alta") and not sub_ok:
        alerts.append("Função crítica sem substituto treinado cadastrado.")

    if demand_max >= 75:
        alerts.append("Período inclui meses de alta demanda prevista.")

    rt = (profile.route_team if profile else "") or ""
    if route_conflict(windows, rt, start, end, employee_id):
        alerts.append("Conflito: outro colaborador da mesma rota/equipe já está de férias.")

    _dd = days_until_deadline(profile, date.today())
    if _dd is not None and _dd < -30:
        alerts.append("Férias muito atrasadas — priorizar negociação com RH.")

    sb = compute_four_scores(
        profile=profile,
        employee=employee,
        headcount_same_role=headcount,
        demand_index=demand_max,
        concurrent_same_role=concurrent,
        role_limit=role_limit,
    )

    recommendation = "aprovado"
    if blocks:
        recommendation = "nao_recomendado"
    elif alerts or sb.operational_risk >= 68 or demand_max >= 72:
        recommendation = "atencao"

    crit_high = crit in ("alta", "muito_alta")
    explanation = _build_operational_explanation(
        recommendation=recommendation,
        blocks=blocks,
        alerts=alerts,
        rb=rb,
        concurrent=concurrent,
        demand_max=demand_max,
        sub_ok=sub_ok,
        crit_high=crit_high,
    )

    return {
        "ok": True,
        "employee": {"id": employee.id, "name": employee.name, "role": employee.role, "role_bucket": rb},
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "impact_team": "baixo" if concurrent == 0 and headcount >= 4 else ("alto" if headcount <= 2 else "medio"),
        "substitute_available": bool(profile and profile.substitute_employee_id),
        "substitute_trained": bool(profile and profile.substitute_trained),
        "demand_index_range": {"min": demand_min, "max": demand_max},
        "concurrent_same_role": concurrent,
        "role_limit": role_limit,
        "alerts": alerts,
        "blocks": blocks,
        "scores": {
            "urgencia_trabalhista": sb.urgency,
            "criticidade_operacional": sb.operational_risk,
            "oportunidade_periodo": sb.period_opportunity,
            "cobertura_equipe": sb.coverage,
            "prioridade_composta": sb.priority_total,
            "detalhes": sb.details,
        },
        "recommendation": recommendation,
        "recommendation_label": RECOMMENDATION_LABEL_PT.get(
            recommendation, recommendation
        ),
        "recommendation_explanation": explanation,
        "month_calibration_note": month_note,
    }


def suggest_vacations(
    session: Session,
    *,
    year: int,
    cost_center: Optional[str],
    default_duration_days: int = 22,
) -> Dict[str, Any]:
    profiles = load_profiles(session)
    employees = list(session.exec(_employee_query(cost_center)).all())
    hc_map = headcount_by_role(session, cost_center)
    suggestions: List[Dict[str, Any]] = []
    windows = scheduled_windows(session, date(year, 1, 1), date(year, 12, 31), cost_center)

    ranked: List[Tuple[float, models.Employee, Optional[models.EmployeeVacationProfile], str, date, date, List[str]]] = []

    for e in employees:
        if not e.id:
            continue
        prof = profiles.get(e.id)
        best_prio = -1.0
        best_month = 5
        best_start = date(year, 5, 1)
        best_end = date(year, 5, 1) + timedelta(days=default_duration_days - 1)
        best_reasons: List[str] = []

        for m in range(1, 13):
            ms = date(year, m, 1)
            me = end_of_month(ms)
            di, _, rjo = get_month_demand(session, year, m)
            prio, rsn = priority_index_for_month(
                profile=prof,
                employee=e,
                demand_index=di,
                windows=windows,
                month_start=ms,
                headcount_by_role_map=hc_map,
            )
            rb = role_bucket(e.role)
            conc = count_role_overlapping(windows, rb, ms, me, e.id)
            lim = effective_role_limit(rb, di, rjo)
            if conc >= lim:
                continue
            if prio > best_prio:
                best_prio = prio
                best_month = m
                best_start = ms
                best_end = ms + timedelta(days=default_duration_days - 1)
                best_reasons = rsn

        if best_prio >= 0:
            ranked.append((best_prio, e, prof, MONTH_NAMES_PT[best_month], best_start, best_end, best_reasons))

    ranked.sort(key=lambda x: -x[0])

    for i, (prio, e, prof, mlabel, ds, de, rsn) in enumerate(ranked[:40], start=1):
        suggestions.append(
            {
                "priority_rank": i,
                "priority_score": round(prio, 1),
                "employee_id": e.id,
                "name": e.name,
                "role": e.role,
                "role_bucket": role_bucket(e.role),
                "suggested_start": ds.isoformat(),
                "suggested_end": de.isoformat(),
                "month_label": mlabel,
                "reasons": rsn,
            }
        )

    return {"year": year, "suggestions": suggestions}


def dashboard_payload(
    session: Session,
    *,
    year: int,
    cost_center: Optional[str],
    view_month: Optional[int] = None,
) -> Dict[str, Any]:
    ref = date.today()
    cal_month = view_month if view_month and 1 <= view_month <= 12 else (ref.month if year == ref.year else 1)
    profiles = load_profiles(session)
    employees = list(session.exec(_employee_query(cost_center)).all())
    hc_map = headcount_by_role(session, cost_center)

    expired = 0
    d30 = d60 = d90 = 0
    rows: List[Dict[str, Any]] = []

    windows_year = scheduled_windows(session, date(year, 1, 1), date(year, 12, 31), cost_center)

    for e in employees:
        if not e.id:
            continue
        prof = profiles.get(e.id)
        ddead = days_until_deadline(prof, ref)
        status = "ok"
        status_label = "Em dia"
        if ddead is not None:
            if ddead < 0:
                status, status_label, expired = "expired", "Vencida", expired + 1
            elif ddead <= 30:
                status, status_label, d30 = "urgent_30", f"Vence em {ddead}d", d30 + 1
            elif ddead <= 60:
                status, status_label, d60 = "urgent_60", f"Vence em {ddead}d", d60 + 1
            elif ddead <= 90:
                status, status_label, d90 = "urgent_90", f"Vence em {ddead}d", d90 + 1
            else:
                status_label = f"Concessivo em {ddead}d"

        di_jan, _, _ = get_month_demand(session, year, ref.month if ref.year == year else 1)
        ms = date(year, ref.month, 1) if ref.year == year else date(year, 6, 1)
        prio, _ = priority_index_for_month(
            profile=prof,
            employee=e,
            demand_index=di_jan,
            windows=windows_year,
            month_start=ms,
            headcount_by_role_map=hc_map,
        )

        rb = role_bucket(e.role)
        best_month = None
        best_label = ""
        best_score = -1.0
        for m in range(1, 13):
            ms2 = date(year, m, 1)
            di, _, rjo = get_month_demand(session, year, m)
            ps, _ = priority_index_for_month(
                profile=prof,
                employee=e,
                demand_index=di,
                windows=windows_year,
                month_start=ms2,
                headcount_by_role_map=hc_map,
            )
            me = end_of_month(ms2)
            conc = count_role_overlapping(windows_year, rb, ms2, me, e.id)
            lim = effective_role_limit(rb, di, rjo)
            if conc >= lim:
                continue
            if ps > best_score:
                best_score = ps
                best_month = m
        if best_month:
            best_label = f"{MONTH_NAMES_PT[best_month]}/{year}"

        st_color, st_hint = vacation_window_status(get_month_demand(session, year, ref.month if ref.year == year else 6)[0])

        sub_name = ""
        if prof and prof.substitute_employee_id:
            sub = session.get(models.Employee, prof.substitute_employee_id)
            sub_name = sub.name if sub else str(prof.substitute_employee_id)

        rows.append(
            {
                "employee_id": e.id,
                "name": e.name,
                "role": e.role,
                "role_bucket": rb,
                "sector": (prof.department_sector if prof else None) or (e.cost_center or ""),
                "vacation_status": status,
                "vacation_status_label": status_label,
                "days_until_deadline": ddead,
                "criticality": (prof.criticality if prof else "media"),
                "substitute": sub_name or "—",
                "substitute_trained": bool(prof and prof.substitute_trained),
                "best_period_hint": best_label or "Revisar limites por mês",
                "priority_index": round(prio, 1),
                "window_color": st_color,
                "route_team": (prof.route_team if prof else None) or "",
            }
        )

    rows.sort(key=lambda r: (-(r["priority_index"] or 0), r["days_until_deadline"] if r["days_until_deadline"] is not None else 9999))

    ref_ms = date(year, cal_month, 1)
    ref_me = end_of_month(ref_ms)
    scheduled_this_month_ids: set = set()
    for w in windows_year:
        if overlaps(ref_ms, ref_me, w["start"], w["end"]):
            scheduled_this_month_ids.add(w["employee_id"])
    scheduled_month = len(scheduled_this_month_ids)

    monthly: List[Dict[str, Any]] = []
    risk_scores = []
    for m in range(1, 13):
        di, note, rjo = get_month_demand(session, year, m)
        ms = date(year, m, 1)
        me = end_of_month(ms)
        sched_ids: set = set()
        for w in windows_year:
            if overlaps(ms, me, w["start"], w["end"]):
                sched_ids.add(w["employee_id"])
        count_v = len(sched_ids)
        cap = sum(effective_role_limit(rk, di, rjo) for rk in hc_map.keys()) if hc_map else 6
        cap = max(1, cap)
        color, hint = vacation_window_status(di)
        load_ratio = count_v / cap
        month_risk = min(100, int(di * 0.65 + load_ratio * 35))
        risk_scores.append(month_risk)
        monthly.append(
            {
                "month": m,
                "month_name": MONTH_NAMES_PT[m],
                "demand_index": di,
                "demand_label": "Baixa" if di <= 38 else ("Alta" if di >= 72 else "Média"),
                "capacity_hint": cap,
                "scheduled_count": count_v,
                "status_color": color,
                "risk_score": month_risk,
                "hint": hint if not note else f"{hint} {note}",
            }
        )

    op_risk = int(sum(risk_scores) / max(1, len(risk_scores)))
    if 1 <= cal_month <= 12:
        op_risk = monthly[cal_month - 1]["risk_score"]

    return {
        "year": year,
        "kpis": {
            "expired": expired,
            "due_30": d30,
            "due_60": d60,
            "due_90": d90,
            "scheduled_in_month": scheduled_month,
            "operational_risk_month": op_risk,
        },
        "rows": rows,
        "monthly": monthly,
        "employees_options": [{"id": e.id, "name": e.name, "role": e.role} for e in employees if e.id],
    }


def save_schedule_entry(
    session: Session,
    *,
    employee_id: int,
    start: date,
    end: date,
    status: str,
    source: str,
    approved_by_user_id: Optional[int],
    decision_reason: Optional[str],
    leadership_notes: Optional[str],
    conflicts: Optional[dict],
    priority_score: Optional[float],
    employee_vacation_synced: bool = False,
) -> models.VacationScheduleEntry:
    ent = models.VacationScheduleEntry(
        employee_id=employee_id,
        start_date=datetime.combine(start, datetime.min.time()),
        end_date=datetime.combine(end, datetime.min.time()),
        status=status,
        source=source,
        approved_by_user_id=approved_by_user_id,
        decision_reason=decision_reason,
        leadership_notes=leadership_notes,
        conflicts_json=conflicts,
        priority_score=priority_score,
        employee_vacation_synced=bool(employee_vacation_synced),
        updated_at=datetime.now(),
    )
    session.add(ent)
    session.commit()
    session.refresh(ent)
    return ent


def upsert_profile(
    session: Session,
    employee_id: int,
    data: Dict[str, Any],
) -> models.EmployeeVacationProfile:
    row = session.exec(
        select(models.EmployeeVacationProfile).where(
            models.EmployeeVacationProfile.employee_id == employee_id
        )
    ).first()
    if not row:
        row = models.EmployeeVacationProfile(employee_id=employee_id)
        session.add(row)

    for key in (
        "department_sector",
        "route_team",
        "criticality",
        "substitute_employee_id",
        "substitute_trained",
        "fixed_route",
        "specific_knowledge",
        "peak_area_worker",
        "same_role_headcount_override",
        "notes",
    ):
        if key in data:
            setattr(row, key, data[key])

    for key in ("acquisition_period_end", "last_vacation_end"):
        if key not in data:
            continue
        val = data[key]
        if val is None or val == "":
            setattr(row, key, None)
        elif isinstance(val, str):
            setattr(row, key, datetime.combine(_parse_date_str(val), datetime.min.time()))
        elif isinstance(val, date):
            setattr(row, key, datetime.combine(val, datetime.min.time()))

    if "vacation_days_available" in data:
        v = data["vacation_days_available"]
        row.vacation_days_available = int(v) if v is not None and str(v).strip() != "" else None

    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_history(session: Session, limit: int = 80) -> List[Dict[str, Any]]:
    rows = session.exec(
        select(models.VacationScheduleEntry).order_by(desc(models.VacationScheduleEntry.created_at)).limit(limit)
    ).all()
    out = []
    for ent in rows:
        emp = session.get(models.Employee, ent.employee_id)
        approver = session.get(models.User, ent.approved_by_user_id) if ent.approved_by_user_id else None
        sync_info = None
        if isinstance(ent.conflicts_json, dict):
            sync_info = ent.conflicts_json.get("employee_vacation_sync")
        out.append(
            {
                "id": ent.id,
                "employee_name": emp.name if emp else str(ent.employee_id),
                "start": _d(ent.start_date).isoformat() if _d(ent.start_date) else "",
                "end": _d(ent.end_date).isoformat() if _d(ent.end_date) else "",
                "status": ent.status,
                "source": ent.source,
                "approved_by": (approver.username if approver else None),
                "decision_reason": ent.decision_reason,
                "leadership_notes": ent.leadership_notes,
                "conflicts": ent.conflicts_json,
                "employee_vacation_synced": bool(getattr(ent, "employee_vacation_synced", False)),
                "employee_vacation_sync_detail": sync_info,
                "created_at": ent.created_at.isoformat() if ent.created_at else "",
            }
        )
    return out
