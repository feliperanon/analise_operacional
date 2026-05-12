"""
Motor de planejamento inteligente de férias — logística de bebidas.

Lógica explícita: pontuação 0–100, janelas verde/amarelo/vermelho, limites por função
ajustados pela demanda do mês (tabela VacationMonthDemand ou régua padrão).
"""
from __future__ import annotations

import calendar
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Date, cast, desc, func
from sqlmodel import Session, col, select

import models
from services.cost_center_utils import cost_center_display_label

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

# Índice de «calor» / sazonalidade operacional (0–100). Calibrável por mês junto com a demanda.
DEFAULT_HEAT_BY_MONTH: Dict[int, int] = {
    1: 78,
    2: 76,
    3: 62,
    4: 48,
    5: 28,
    6: 26,
    7: 26,
    8: 48,
    9: 52,
    10: 64,
    11: 74,
    12: 80,
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

LAUNCH_VERDICT_LABEL_PT = {
    "aprovado": "Pode lançar",
    "atencao": "Lançar com atenção",
    "nao_recomendado": "Não recomendado",
}

# Prazos além deste limite absoluto são tratados como cadastro inválido (evita «vencido há 8000 dias»).
_MAX_PLAUSIBLE_DEADLINE_DRIFT_DAYS = 800


def _heuristic_non_operational_employee(emp: models.Employee) -> bool:
    """Sócio, diretoria, canal, pré-cadastro etc. — fora da fila operacional padrão."""
    role = (emp.role or "").upper()
    name = (emp.name or "").upper()
    needles = (
        "SOCIO",
        "SÓCIO",
        "DIRETOR",
        "DIRETORIA",
        "CANAL",
        "CANDIDATO",
        "ESTAGIARIO",
        "ESTÁGIARIO",
        "TRAINEE",
        "PRE CADASTRO",
        "PRE-CADASTRO",
        "PRÉ-CADASTRO",
        "CONSELHO",
        "ASSESSORIA",
    )
    if any(n in role for n in needles):
        return True
    if "SÓCIO" in name or "SOCIO" in name:
        return True
    rid = (str(emp.registration_id or "")).strip().upper()
    if rid.startswith("PRE") or rid.startswith("TEMP") or rid.startswith("XXX"):
        return True
    return False


def employee_in_operational_vacation_queue(
    emp: models.Employee, prof: Optional[models.EmployeeVacationProfile]
) -> bool:
    if not emp.id:
        return False
    st = (emp.status or "").strip().lower()
    if st in ("fired", "terminated", "dismissed"):
        return False
    if prof is not None and bool(getattr(prof, "exclude_from_operational_vacation", False)):
        return False
    if _heuristic_non_operational_employee(emp):
        return False
    return True


def substitute_coverage_required(profile: Optional[models.EmployeeVacationProfile]) -> bool:
    c = (profile.criticality if profile else "media") or "media"
    return str(c).strip().lower() in ("alta", "muito_alta")


def classify_deadline_row(
    ddead: Optional[int], deadline_basis: str
) -> Tuple[str, Optional[int], str]:
    """
    bucket: ok | incomplete | invalid_data
    dias_ui: valor para ordenação/exibição quando ok; None se inválido ou incompleto.
    """
    if ddead is None:
        if deadline_basis == "sem_dados":
            return "incomplete", None, "Cadastro incompleto"
        return "incomplete", None, "Prazo indisponível"
    di = int(ddead)
    if abs(di) > _MAX_PLAUSIBLE_DEADLINE_DRIFT_DAYS:
        return "invalid_data", None, "Datas inconsistentes"
    return "ok", di, ""


def employee_ids_approved_vacation_start_on_or_before_deadline(
    session: Session,
    ref: date,
    deadline_by_eid: Dict[int, date],
) -> set:
    """
    Colaboradores com gozo **aprovado** ainda vigente ou futuro (fim ≥ ref) cujo **início**
    é anterior ou igual ao fim do período concessivo calculado — não devem ser tratados
    como «vencidos» na operação (já há programação dentro do concessivo).
    """
    if not deadline_by_eid:
        return set()
    u = sorted({int(x) for x in deadline_by_eid if x})
    if not u:
        return set()
    ref_start = datetime.combine(ref, datetime.min.time())
    stmt = select(models.VacationScheduleEntry).where(
        col(models.VacationScheduleEntry.employee_id).in_(u),
        models.VacationScheduleEntry.status == "approved",
        models.VacationScheduleEntry.end_date >= ref_start,
    )
    satisfied: set = set()
    for ent in session.exec(stmt).all():
        eid = int(ent.employee_id)
        deadline = deadline_by_eid.get(eid)
        if not deadline:
            continue
        sd = _d(ent.start_date)
        if sd and sd <= deadline:
            satisfied.add(eid)
    return satisfied


def employee_ids_with_approved_future_vacation(
    session: Session, ref: date, employee_ids: List[int]
) -> set:
    if not employee_ids:
        return set()
    u = sorted({int(x) for x in employee_ids if x})
    if not u:
        return set()
    ref_dt = datetime.combine(ref, datetime.min.time())
    stmt = (
        select(models.VacationScheduleEntry.employee_id)
        .where(
            col(models.VacationScheduleEntry.employee_id).in_(u),
            models.VacationScheduleEntry.status == "approved",
            models.VacationScheduleEntry.end_date >= ref_dt,
        )
        .distinct()
    )
    out: set = set()
    for item in session.exec(stmt).all():
        if item is None:
            continue
        if hasattr(item, "employee_id"):
            out.add(int(getattr(item, "employee_id")))
        elif isinstance(item, (tuple, list)) and item:
            out.add(int(item[0]))
        else:
            out.add(int(item))
    return out


def scheduled_vacations_in_month_detail(
    session: Session,
    *,
    year: int,
    month: int,
    cost_center: Optional[str],
) -> Tuple[List[Dict[str, Any]], int]:
    """Gozos aprovados no planejamento que interceptam o mês civil. Retorna (lista deduplicada, nº de duplicatas fundidas)."""
    ms = date(year, month, 1)
    me = end_of_month(ms)
    emps = list_employees_for_vacation(session, cost_center)
    emp_by_id = {e.id: e for e in emps if e.id}
    stmt = (
        select(models.VacationScheduleEntry)
        .where(
            models.VacationScheduleEntry.status == "approved",
            models.VacationScheduleEntry.start_date <= datetime.combine(me, datetime.max.time()),
            models.VacationScheduleEntry.end_date >= datetime.combine(ms, datetime.min.time()),
        )
        .order_by(models.VacationScheduleEntry.start_date)
    )
    out: List[Dict[str, Any]] = []
    for ent in session.exec(stmt).all():
        eid = int(ent.employee_id)
        emp = emp_by_id.get(eid)
        if not emp:
            continue
        s_d = _d(ent.start_date)
        e_d = _d(ent.end_date)
        if not s_d or not e_d:
            continue
        if not overlaps(ms, me, s_d, e_d):
            continue
        days = (e_d - s_d).days + 1
        out.append(
            {
                "employee_id": eid,
                "name": emp.name,
                "role": emp.role,
                "start": s_d.isoformat(),
                "end": e_d.isoformat(),
                "days": days,
                "source": ent.source or "manual",
                "employee_vacation_synced": bool(getattr(ent, "employee_vacation_synced", False)),
                "entry_id": ent.id,
            }
        )
    raw_len = len(out)
    ded = dedupe_scheduled_vacation_month_rows(out)
    return ded, max(0, raw_len - len(ded))


def scheduled_vacations_year_list(
    session: Session,
    *,
    year: int,
    cost_center: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Todos os intervalos de férias que interceptam o ano civil (cadastro + planejamento),
    incluindo sugestões pendentes, para visão consolidada e busca por nome.
    """
    y0 = date(year, 1, 1)
    y1 = date(year, 12, 31)
    wins = scheduled_windows(session, y0, y1, cost_center)
    emps = list_employees_for_vacation(session, cost_center)
    emp_by_id = {e.id: e for e in emps if e.id}
    rows_raw: List[Dict[str, Any]] = []
    for w in wins:
        es = str(w.get("entry_status") or "").strip().lower()
        if es not in ("approved", "cadastro", "suggested"):
            continue
        eid = w.get("employee_id")
        emp = emp_by_id.get(eid)
        if not emp:
            continue
        vs, ve = w.get("start"), w.get("end")
        if not isinstance(vs, date) or not isinstance(ve, date):
            continue
        if not overlaps(y0, y1, vs, ve):
            continue
        days = (ve - vs).days + 1
        rows_raw.append(
            {
                "employee_id": int(eid),
                "name": emp.name,
                "role": emp.role,
                "start": vs.isoformat(),
                "end": ve.isoformat(),
                "days": days,
                "source": str(w.get("source") or "manual"),
                "entry_status": es,
                "entry_id": w.get("entry_id"),
                "employee_vacation_synced": bool(w.get("employee_vacation_synced", False)),
            }
        )
    rows_sorted = sorted(rows_raw, key=lambda r: (str(r["start"]), int(r["employee_id"])))
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows_sorted:
        key = (
            int(r["employee_id"]),
            str(r.get("start") or "")[:10],
            str(r.get("end") or "")[:10],
            (r.get("source") or "").strip().lower(),
            str(r.get("entry_status") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda x: str(x.get("start") or ""))
    return out


def dedupe_scheduled_vacation_month_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Um gozo aprovado por (colaborador + início + fim + origem); mantém o menor entry_id."""
    rows_sorted = sorted(rows, key=lambda r: int(r.get("entry_id") or 0))
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows_sorted:
        eid = int(r["employee_id"])
        src = (r.get("source") or "manual").strip().lower()
        key = (eid, str(r.get("start") or "")[:10], str(r.get("end") or "")[:10], src)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda x: str(x.get("start") or ""))
    return out


def scheduled_month_detail_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "gozo_count": 0,
            "unique_employees": 0,
            "unique_roles": 0,
            "avg_days": None,
            "sources_breakdown": {},
        }
    days_list = [int(r["days"]) for r in rows if r.get("days") is not None]
    roles = {str(r.get("role") or "").strip() for r in rows if (r.get("role") or "").strip()}
    eids = {int(r["employee_id"]) for r in rows}
    src = Counter((r.get("source") or "manual").strip().lower() for r in rows)
    avg = None
    if days_list:
        avg = round(sum(days_list) / len(days_list), 1)
    return {
        "gozo_count": len(rows),
        "unique_employees": len(eids),
        "unique_roles": len(roles),
        "avg_days": avg,
        "sources_breakdown": dict(src),
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
        default_idx = default_demand_index_for_month(m)
        default_heat = default_heat_index_for_month(m)
        row = session.exec(
            select(models.VacationMonthDemand).where(
                models.VacationMonthDemand.year == y,
                models.VacationMonthDemand.month == m,
            )
        ).first()
        if row:
            hi_raw = getattr(row, "heat_index", None)
            hi = int(hi_raw) if hi_raw is not None else default_heat
            hi = max(0, min(100, hi))
            months.append(
                {
                    "month": m,
                    "month_name": MONTH_NAMES_PT[m],
                    "demand_index": row.demand_index,
                    "heat_index": hi,
                    "default_demand_index": default_idx,
                    "default_heat_index": default_heat,
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
                    "heat_index": default_heat,
                    "default_demand_index": default_idx,
                    "default_heat_index": default_heat,
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
    heat_index: Optional[int] = None,
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
    def_h = default_heat_index_for_month(m)
    row = session.exec(
        select(models.VacationMonthDemand).where(
            models.VacationMonthDemand.year == y,
            models.VacationMonthDemand.month == m,
        )
    ).first()
    existed = row is not None
    if not row:
        row = models.VacationMonthDemand(year=y, month=m)
        session.add(row)
    row.demand_index = di
    row.risk_notes = (risk_notes or "").strip() or None
    row.role_limits_json = limits
    if heat_index is not None:
        hi = int(heat_index)
        if not (0 <= hi <= 100):
            return None, "heat_index deve estar entre 0 e 100."
        row.heat_index = hi
    elif not existed:
        row.heat_index = def_h
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
        "exclude_from_operational_vacation": False,
    }

    def _deadline_preview() -> Dict[str, Any]:
        mc = consolidated_completed_vacation_end_by_employee(session, [emp], ref=date.today())
        sch_end = mc.get(int(emp.id))
        acq, basis = effective_acquisition_period_end(prof, emp, sch_end)
        conc = concessive_deadline_effective(prof, emp, sch_end)
        dleft = days_until_deadline(prof, emp, date.today(), sch_end)
        return {
            "deadline_basis": basis,
            "deadline_basis_label": deadline_basis_public_label(basis),
            "acquisition_period_end_effective": acq.isoformat() if acq else None,
            "concessive_deadline": conc.isoformat() if conc else None,
            "days_until_concessive": dleft,
        }

    if not prof:
        out = {
            "employee_id": emp.id,
            "name": emp.name,
            "role": emp.role,
            "cost_center": emp.cost_center,
            "admission_date": iso_d(emp.admission_date),
            "vacation_profile": empty_profile,
        }
        out["vacation_deadline_preview"] = _deadline_preview()
        return out

    return {
        "employee_id": emp.id,
        "name": emp.name,
        "role": emp.role,
        "cost_center": emp.cost_center,
        "admission_date": iso_d(emp.admission_date),
        "vacation_deadline_preview": _deadline_preview(),
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
            "exclude_from_operational_vacation": bool(
                getattr(prof, "exclude_from_operational_vacation", False)
            ),
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
        return False, "Cadastro do colaborador sem campos de férias; sincronização não aplicada."
    try:
        employee.vacation_start = datetime.combine(start, datetime.min.time())
        employee.vacation_end = datetime.combine(end, datetime.min.time())
        session.add(employee)
        session.commit()
        session.refresh(employee)
        return True, "Férias gravadas também no cadastro do colaborador (início e fim)."
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


def add_months(d: date, months: int) -> date:
    """Soma meses ao calendário (ex.: admissão + 12 meses)."""
    month_idx = d.month - 1 + months
    year = d.year + month_idx // 12
    month = month_idx % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def _coerce_iso_date(val: Any) -> Optional[date]:
    """Converte string ISO (YYYY-MM-DD) ou date em ``date``, ou None."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    s = str(val).strip()[:10]
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _latest_completed_vacation_end(
    employee: models.Employee,
    profile: Optional[models.EmployeeVacationProfile],
    schedule_last_vacation_end: Optional[date],
) -> Optional[date]:
    """
    Maior data de fim de férias já concluídas entre: lançamentos aprovados no planejamento,
    perfil de férias e cadastro do colaborador (somente períodos já encerrados).
    """
    ref = date.today()
    candidates: List[date] = []
    # Lançamentos futuros no planejamento não podem servir de âncora do aquisitivo atual.
    if schedule_last_vacation_end and schedule_last_vacation_end < ref:
        candidates.append(schedule_last_vacation_end)
    if profile and profile.last_vacation_end:
        lv = _d(profile.last_vacation_end)
        if lv and lv < ref:
            candidates.append(lv)
    ve = _d(employee.vacation_end) if employee.vacation_end else None
    if ve and ve < ref:
        candidates.append(ve)
    if not candidates:
        return None
    return max(candidates)


def _anchor_start_current_acquisition(
    employee: models.Employee,
    profile: Optional[models.EmployeeVacationProfile],
    schedule_last_vacation_end: Optional[date] = None,
) -> Tuple[Optional[date], str]:
    """
    Primeiro dia do período aquisitivo atual: após o fim da última folga concluída
    (consolidando perfil, cadastro e planejamento) ou, na falta, data de admissão.
    """
    latest = _latest_completed_vacation_end(employee, profile, schedule_last_vacation_end)
    if latest:
        return latest + timedelta(days=1), "pos_ferias_consolidado"
    adm = _d(employee.admission_date) if employee.admission_date else None
    if adm:
        return adm, "admissao"
    return None, "sem_dados"


def effective_acquisition_period_end(
    profile: Optional[models.EmployeeVacationProfile],
    employee: models.Employee,
    schedule_last_vacation_end: Optional[date] = None,
) -> Tuple[Optional[date], str]:
    """
    Fim do período aquisitivo usado pelo motor.
    Prioriza ``acquisition_period_end`` do perfil quando ainda coerente com as férias
    já registradas; caso contrário estima 12 meses após o início do aquisitivo atual.
    """
    latest_vac = _latest_completed_vacation_end(employee, profile, schedule_last_vacation_end)
    anchor, tag = _anchor_start_current_acquisition(
        employee, profile, schedule_last_vacation_end
    )
    max_plausible: Optional[date] = None
    if anchor:
        max_plausible = add_months(anchor, 12) - timedelta(days=1)

    if profile and profile.acquisition_period_end:
        d = _d(profile.acquisition_period_end)
        if d:
            stale_by_vacation = latest_vac is not None and latest_vac > d
            if not stale_by_vacation:
                slack = timedelta(days=120)
                if max_plausible is not None:
                    if d <= max_plausible + slack:
                        return d, "cadastro_perfil"
                    dl_est = max_plausible + timedelta(days=365)
                    if abs((d - dl_est).days) <= 60:
                        return max_plausible, tag
                    if latest_vac is not None and d > max_plausible + slack:
                        pass
                    else:
                        return d, "cadastro_perfil"
                else:
                    return d, "cadastro_perfil"

    if not anchor:
        return None, tag
    assert max_plausible is not None
    return max_plausible, tag


def concessive_deadline_effective(
    profile: Optional[models.EmployeeVacationProfile],
    employee: models.Employee,
    schedule_last_vacation_end: Optional[date] = None,
) -> Optional[date]:
    """Último dia do período concessivo (aprox. 12 meses após o fim do aquisitivo)."""
    acq_end, _ = effective_acquisition_period_end(
        profile, employee, schedule_last_vacation_end
    )
    if not acq_end:
        return None
    return acq_end + timedelta(days=365)


def days_until_deadline(
    profile: Optional[models.EmployeeVacationProfile],
    employee: models.Employee,
    ref: date,
    schedule_last_vacation_end: Optional[date] = None,
) -> Optional[int]:
    dl = concessive_deadline_effective(profile, employee, schedule_last_vacation_end)
    if not dl:
        return None
    return (dl - ref).days


def earliest_allowed_vacation_start_date(
    profile: Optional[models.EmployeeVacationProfile],
    employee: models.Employee,
    schedule_last_vacation_end: Optional[date] = None,
) -> Optional[date]:
    """
    Primeiro dia em que o colaborador pode **iniciar** férias no ciclo atual:
    dia seguinte ao fim do período aquisitivo (12 meses após a âncora do ciclo).
    Sem dados para estimar o aquisitivo (ex.: sem admissão e sem folga consolidada),
    retorna None — o motor não deve sugerir datas arbitrárias.
    """
    acq_end, _ = effective_acquisition_period_end(
        profile, employee, schedule_last_vacation_end
    )
    if not acq_end:
        return None
    return acq_end + timedelta(days=1)


_DEADLINE_BASIS_LABEL_PT = {
    "cadastro_perfil": "Prazo pelo perfil de férias (fim do aquisitivo informado).",
    "admissao": "Prazo estimado pela data de admissão no cadastro (ciclo aquisitivo de 12 meses + concessivo).",
    "pos_ferias_perfil": "Prazo estimado após o fim das férias registradas no perfil.",
    "pos_ferias_cadastro": "Prazo estimado após o fim das férias no cadastro do colaborador.",
    "pos_ferias_consolidado": "Prazo estimado após o fim das férias (perfil, cadastro ou último lançamento aprovado no planejamento).",
    "sem_dados": "Sem data de admissão nem fim de aquisitivo no perfil — informe no perfil ou importe a planilha.",
}


def deadline_basis_public_label(basis: str) -> str:
    return _DEADLINE_BASIS_LABEL_PT.get(basis, basis or "—")


def role_bucket(role: Optional[str]) -> str:
    """
    Agrupa cargo livre em buckets operacionais. Ordem importa: substrings mais específicas
    antes de genéricas (ex.: «AJUDANTE DE MOTORISTA» contém «MOTORIST» mas é ajudante).
    """
    r = (role or "").upper()
    if "AJUDANT" in r:
        return "AJUDANTE"
    if "AUXILIAR" in r and "MOTOR" in r:
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
    if "MOTORIST" in r:
        return "MOTORISTA"
    return "OUTROS"


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


def default_heat_index_for_month(month: int) -> int:
    return DEFAULT_HEAT_BY_MONTH.get(int(month), 50)


def get_month_demand(
    session: Session,
    year: int,
    month: int,
) -> Tuple[int, int, Optional[str], Optional[Dict[str, int]]]:
    """
    Retorna (demand_index, heat_index, risk_notes, limites_por_função).
    ``heat_index`` mede sazonalidade / «calor» operacional (bebidas, clima, pico logístico).
    """
    m = int(month)
    y = int(year)
    default_di = DEFAULT_DEMAND_BY_MONTH.get(m, 50)
    default_hi = default_heat_index_for_month(m)
    row = session.exec(
        select(models.VacationMonthDemand).where(
            models.VacationMonthDemand.year == y,
            models.VacationMonthDemand.month == m,
        )
    ).first()
    if row:
        hi_raw = getattr(row, "heat_index", None)
        hi = int(hi_raw) if hi_raw is not None else default_hi
        hi = max(0, min(100, hi))
        return int(row.demand_index), hi, row.risk_notes, row.role_limits_json
    return default_di, default_hi, None, None


def list_employees_for_vacation(session: Session, cost_center: Optional[str]) -> List[models.Employee]:
    """
    Colaboradores ativos, filtrados por empresa (Souza Pinto / Exemplar) usando o mesmo
    mapeamento de `cost_center` que o People Intelligence — não compara string cru do banco.
    """
    q = select(models.Employee).where(col(models.Employee.status) == "active")
    rows = list(session.exec(q).all())
    if not cost_center or str(cost_center).strip().lower() in ("todos", "all", ""):
        return rows
    sel = cost_center_display_label(str(cost_center).strip())
    return [e for e in rows if cost_center_display_label(e.cost_center) == sel]


def load_profiles(session: Session) -> Dict[int, models.EmployeeVacationProfile]:
    rows = session.exec(select(models.EmployeeVacationProfile)).all()
    return {p.employee_id: p for p in rows}


def headcount_by_role(session: Session, cost_center: Optional[str]) -> Dict[str, int]:
    employees = list_employees_for_vacation(session, cost_center)
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
    emps = list_employees_for_vacation(session, cost_center)
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
                    "entry_status": "cadastro",
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
                "entry_status": str(ent.status or ""),
                "employee_vacation_synced": bool(getattr(ent, "employee_vacation_synced", False)),
            }
        )
    return out


def overlaps(a0: date, a1: date, b0: date, b1: date) -> bool:
    return a0 <= b1 and b0 <= a1


def end_of_month(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def calendar_month_is_still_open(month_start: date, ref: date) -> bool:
    """
    False se o mês civil já terminou antes de `ref` (ex.: Abril/2026 quando hoje é maio/2026).
    Usado para não sugerir «Melhor janela» em meses que já passaram.
    """
    return end_of_month(month_start) >= ref


def best_future_vacation_month_label(
    session: Session,
    *,
    planning_year: int,
    ref: date,
    profile: Optional[models.EmployeeVacationProfile],
    employee: models.Employee,
    role_b: str,
    headcount_by_role_map: Dict[str, int],
    cost_center: Optional[str],
    schedule_last_vacation_end: Optional[date] = None,
) -> str:
    """
    Escolhe o melhor mês (pontuação do motor) entre meses ainda planejáveis a partir de `ref`
    e com folga no limite por função. Considera o ano do painel e, se necessário, o ano seguinte
    até `max(ref.year + 1, planning_year + 1)` para não ficar sem resposta quando o ano focado
    já passou quase todo.
    """
    end_scan_year = max(planning_year + 1, ref.year + 1)
    win_from = date(planning_year, 1, 1)
    win_to = date(end_scan_year, 12, 31)
    windows = scheduled_windows(session, win_from, win_to, cost_center)
    earliest = earliest_allowed_vacation_start_date(
        profile, employee, schedule_last_vacation_end
    )
    if earliest is None:
        return ""

    candidates: List[Tuple[float, int, int, int]] = []  # ps, neg_ordinal, y, m

    for y in range(planning_year, end_scan_year + 1):
        for m in range(1, 13):
            ms2 = date(y, m, 1)
            if not calendar_month_is_still_open(ms2, ref):
                continue
            if earliest > end_of_month(ms2):
                continue
            di, _heat_m, _note_m, rjo = get_month_demand(session, y, m)
            ps, _ = priority_index_for_month(
                profile=profile,
                employee=employee,
                demand_index=di,
                windows=windows,
                month_start=ms2,
                headcount_by_role_map=headcount_by_role_map,
                schedule_last_vacation_end=schedule_last_vacation_end,
            )
            me = end_of_month(ms2)
            conc = count_role_overlapping(windows, role_b, ms2, me, employee.id)
            lim = effective_role_limit(role_b, di, rjo)
            if conc >= lim:
                continue
            neg_ord = -(y * 12 + m)
            candidates.append((float(ps), neg_ord, y, m))

    if not candidates:
        return ""

    _ps, _no, best_y, best_m = max(candidates, key=lambda t: (t[0], t[1]))
    label = f"{MONTH_NAMES_PT[best_m]}/{best_y}"
    if best_y != planning_year:
        label += " · próximo ano"
    return label


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
    schedule_last_vacation_end: Optional[date] = None,
) -> ScoreBreakdown:
    """Quatro notas 0–100 + prioridade composta (interpretação para gestão)."""
    ref = date.today()
    ddead = days_until_deadline(profile, employee, ref, schedule_last_vacation_end)

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

    lv = _latest_completed_vacation_end(employee, profile, schedule_last_vacation_end)
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
    schedule_last_vacation_end: Optional[date] = None,
) -> Tuple[float, List[str]]:
    """Índice 0–100 estilo checklist (pesos explícitos para a UI)."""
    reasons: List[str] = []
    score = 0.0
    rb = role_bucket(employee.role)
    ref = date.today()
    ddead = days_until_deadline(profile, employee, ref, schedule_last_vacation_end)

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

    sch_end_sim = consolidated_completed_vacation_end_by_employee(
        session, [employee], ref=date.today()
    ).get(employee_id)

    touched_demands: Dict[Tuple[int, int], int] = {}
    touched_heats: Dict[Tuple[int, int], int] = {}
    d = start
    while d <= end:
        key = (d.year, d.month)
        di_m, heat_m, _, _ = get_month_demand(session, d.year, d.month)
        touched_demands[key] = di_m
        touched_heats[key] = heat_m
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)

    demand_max = max(touched_demands.values()) if touched_demands else 50
    demand_min = min(touched_demands.values()) if touched_demands else 50
    heat_max = max(touched_heats.values()) if touched_heats else 50
    heat_min = min(touched_heats.values()) if touched_heats else 50
    _, _, month_note, role_ovr = get_month_demand(session, start.year, start.month)
    role_limit = effective_role_limit(rb, demand_max, role_ovr)

    concurrent_before = count_role_overlapping(windows, rb, start, end, employee_id)
    sim_window: Dict[str, Any] = {
        "employee_id": employee_id,
        "name": employee.name or "",
        "role_bucket": rb,
        "route_team": (profile.route_team if profile else None) or "",
        "start": start,
        "end": end,
        "source": "simulation",
        "entry_status": "simulation",
    }
    concurrent_after = count_role_overlapping(windows + [sim_window], rb, start, end, None)

    if concurrent_before >= role_limit:
        blocks.append(
            f"Limite de férias simultâneas para {rb} neste período ({concurrent_before}/{role_limit})."
        )

    crit = (profile.criticality if profile else "media").lower()
    sub_ok = bool(profile and profile.substitute_employee_id and profile.substitute_trained)
    if crit in ("alta", "muito_alta") and not sub_ok:
        alerts.append("Função crítica sem substituto treinado cadastrado.")

    if demand_max >= 75:
        alerts.append("Período inclui meses de alta demanda prevista.")
    if heat_max >= 72:
        alerts.append("Período inclui meses de calor/sazonalidade elevados para operação.")

    rt = (profile.route_team if profile else "") or ""
    if route_conflict(windows, rt, start, end, employee_id):
        alerts.append("Conflito: outro colaborador da mesma rota/equipe já está de férias.")

    _dd = days_until_deadline(profile, employee, date.today(), sch_end_sim)
    if _dd is not None and _dd < -30:
        alerts.append("Férias muito atrasadas — priorizar negociação com RH.")

    sb = compute_four_scores(
        profile=profile,
        employee=employee,
        headcount_same_role=headcount,
        demand_index=demand_max,
        concurrent_same_role=concurrent_before,
        role_limit=role_limit,
        schedule_last_vacation_end=sch_end_sim,
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
        concurrent=concurrent_before,
        demand_max=demand_max,
        sub_ok=sub_ok,
        crit_high=crit_high,
    )

    emp_all = list_employees_for_vacation(session, cost_center)
    profiles_all = load_profiles(session)
    last_comp = consolidated_completed_vacation_end_by_employee(session, emp_all, ref=date.today())
    light_rows: List[Dict[str, Any]] = []
    for e in emp_all:
        if not e.id:
            continue
        p = profiles_all.get(e.id)
        if not employee_in_operational_vacation_queue(e, p):
            continue
        sch_e = last_comp.get(e.id)
        ddead_e = days_until_deadline(p, e, date.today(), sch_e)
        light_rows.append(
            {
                "employee_id": e.id,
                "name": e.name,
                "operational_queue": True,
                "vacation_status": "",
                "days_until_deadline": ddead_e,
            }
        )

    from services.vacation_conflict_analysis import build_conflicts_for_simulation_period

    conflict_bundle = build_conflicts_for_simulation_period(
        session,
        start=start,
        end=end,
        cost_center=cost_center,
        rows=light_rows,
        simulation={
            "employee_id": employee_id,
            "start": start,
            "end": end,
        },
    )

    csev = str(conflict_bundle.get("severity") or "low").lower()
    if blocks or csev == "critical":
        launch_verdict = "nao_recomendado"
    elif recommendation == "nao_recomendado" or csev == "high":
        launch_verdict = "nao_recomendado"
    elif recommendation == "atencao" or csev == "medium":
        launch_verdict = "atencao"
    else:
        launch_verdict = "aprovado"

    suggestion_month_label = best_future_vacation_month_label(
        session,
        planning_year=start.year,
        ref=date.today(),
        profile=profile,
        employee=employee,
        role_b=rb,
        headcount_by_role_map=hc_map,
        cost_center=cost_center,
        schedule_last_vacation_end=sch_end_sim,
    )

    return {
        "ok": True,
        "employee": {"id": employee.id, "name": employee.name, "role": employee.role, "role_bucket": rb},
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "impact_team": "baixo" if concurrent_before == 0 and headcount >= 4 else ("alto" if headcount <= 2 else "medio"),
        "substitute_available": bool(profile and profile.substitute_employee_id),
        "substitute_trained": bool(profile and profile.substitute_trained),
        "demand_index_range": {"min": demand_min, "max": demand_max},
        "heat_index_range": {"min": heat_min, "max": heat_max},
        "concurrent_same_role": concurrent_before,
        "concurrent_same_role_after": concurrent_after,
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
        "operational_conflicts": conflict_bundle,
        "launch_verdict": launch_verdict,
        "launch_verdict_label": LAUNCH_VERDICT_LABEL_PT.get(launch_verdict, launch_verdict),
        "alternative_window_hint": suggestion_month_label or None,
    }


def _vacation_urgency_sort_key(
    employee: models.Employee,
    profile: Optional[models.EmployeeVacationProfile],
    ref: date,
    schedule_last_completed_end: Optional[date] = None,
) -> Tuple[int, int]:
    """
    Ordenação crescente = mais urgente primeiro.
    Usa prazo concessivo (perfil, admissão ou pós-férias) como na fila do painel.
    """
    ddead = days_until_deadline(profile, employee, ref, schedule_last_completed_end)
    if ddead is None:
        return (5, 99999)
    if ddead < 0:
        return (0, ddead)
    if ddead <= 30:
        return (1, ddead)
    if ddead <= 90:
        return (2, ddead)
    if ddead <= 180:
        return (3, ddead)
    return (4, ddead)


def _synthetic_schedule_window(
    *,
    employee_id: int,
    name: str,
    role_bucket: str,
    route_team: str,
    start: date,
    end: date,
) -> Dict[str, Any]:
    """Janela compatível com ``scheduled_windows`` para simular lotes de sugestão."""
    return {
        "employee_id": employee_id,
        "name": name,
        "role_bucket": role_bucket,
        "route_team": (route_team or "").strip(),
        "start": start,
        "end": end,
        "source": "suggestion_plan",
    }


def _month_candidates_for_employee(
    session: Session,
    *,
    year: int,
    ref: date,
    employee: models.Employee,
    profile: Optional[models.EmployeeVacationProfile],
    windows: List[Dict[str, Any]],
    hc_map: Dict[str, int],
    default_duration_days: int,
    schedule_last_vacation_end: Optional[date] = None,
) -> List[Tuple[float, int, int, date, date, List[str], int]]:
    """
    Meses viáveis para o colaborador, com (prioridade, mês, demanda, início, fim, motivos, concorrentes).
    Ordenação externa: maior prioridade, menor demanda, menos gente da função já de férias naquele mês.
    """
    rb = role_bucket(employee.role)
    opts: List[Tuple[float, int, int, date, date, List[str], int]] = []
    earliest = earliest_allowed_vacation_start_date(
        profile, employee, schedule_last_vacation_end
    )
    if earliest is None:
        return []
    year_end = date(year, 12, 31)
    if earliest > year_end:
        return []
    for m in range(1, 13):
        ms = date(year, m, 1)
        me = end_of_month(ms)
        if not calendar_month_is_still_open(ms, ref):
            continue
        di, _, _, rjo = get_month_demand(session, year, m)
        prio, rsn = priority_index_for_month(
            profile=profile,
            employee=employee,
            demand_index=di,
            windows=windows,
            month_start=ms,
            headcount_by_role_map=hc_map,
            schedule_last_vacation_end=schedule_last_vacation_end,
        )
        conc = count_role_overlapping(windows, rb, ms, me, employee.id)
        lim = effective_role_limit(rb, di, rjo)
        if lim <= 0 or conc >= lim:
            continue
        ds = max(ms, earliest)
        if ds > me:
            continue
        de = ds + timedelta(days=default_duration_days - 1)
        reasons = list(rsn)
        if ds > ms:
            reasons.append(
                f"Início em {ds.strftime('%d/%m/%Y')}: primeiro dia permitido após o período aquisitivo."
            )
        opts.append((prio, m, di, ds, de, reasons, conc))
    opts.sort(key=lambda x: (-x[0], x[2], x[6]))
    return opts


def suggest_vacations(
    session: Session,
    *,
    year: int,
    cost_center: Optional[str],
    default_duration_days: int = 22,
) -> Dict[str, Any]:
    """
    Sugere até 40 períodos priorizando quem está vencido ou próximo do concessivo
    (incluindo estimativa por admissão), e **distribui no ano** sem lotar a mesma função:
    cada nova sugestão entra num plano simulado de janelas para respeitar limite por função
    e meses de maior demanda (índice calibrado).
    """
    ref = date.today()
    profiles = load_profiles(session)
    employees = [e for e in list_employees_for_vacation(session, cost_center) if e.id]
    hc_map = headcount_by_role(session, cost_center)
    suggestions: List[Dict[str, Any]] = []
    base_windows = scheduled_windows(session, date(year, 1, 1), date(year, 12, 31), cost_center)
    sim_windows: List[Dict[str, Any]] = [dict(w) for w in base_windows]

    last_completed_vac = consolidated_completed_vacation_end_by_employee(session, employees, ref=ref)
    employees.sort(
        key=lambda emp: _vacation_urgency_sort_key(
            emp, profiles.get(emp.id), ref, last_completed_vac.get(emp.id)
        )
    )

    for e in employees:
        if len(suggestions) >= 40:
            break
        prof = profiles.get(e.id)
        rb = role_bucket(e.role)
        rt = (prof.route_team if prof else None) or ""
        sch_sg = last_completed_vac.get(e.id)
        opts = _month_candidates_for_employee(
            session,
            year=year,
            ref=ref,
            employee=e,
            profile=prof,
            windows=sim_windows,
            hc_map=hc_map,
            default_duration_days=default_duration_days,
            schedule_last_vacation_end=sch_sg,
        )
        for prio, m, di, ds, de, rsn, _conc in opts:
            ms = date(year, m, 1)
            me = end_of_month(ms)
            _, _, _, rjo = get_month_demand(session, year, m)
            conc = count_role_overlapping(sim_windows, rb, ms, me, e.id)
            lim = effective_role_limit(rb, di, rjo)
            if conc >= lim:
                continue
            reasons = list(rsn)
            reasons.append(
                "Distribuição inteligente: respeita limite por função no mês e evita concentrar saídas no mesmo lote."
            )
            sim_windows.append(
                _synthetic_schedule_window(
                    employee_id=int(e.id),
                    name=e.name or "",
                    role_bucket=rb,
                    route_team=rt,
                    start=ds,
                    end=de,
                )
            )
            suggestions.append(
                {
                    "priority_rank": len(suggestions) + 1,
                    "priority_score": round(prio, 1),
                    "employee_id": e.id,
                    "name": e.name,
                    "role": e.role,
                    "role_bucket": rb,
                    "suggested_start": ds.isoformat(),
                    "suggested_end": de.isoformat(),
                    "month_label": MONTH_NAMES_PT[m],
                    "reasons": reasons,
                }
            )
            break

    return {"year": year, "suggestions": suggestions}


def last_approved_vacation_by_employee(session: Session, employee_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Último lançamento aprovado por colaborador (prioriza o período que termina mais tarde)."""
    if not employee_ids:
        return {}
    unique_ids = sorted({int(x) for x in employee_ids if x is not None})
    if not unique_ids:
        return {}
    stmt = (
        select(models.VacationScheduleEntry)
        .where(
            col(models.VacationScheduleEntry.employee_id).in_(unique_ids),
            models.VacationScheduleEntry.status == "approved",
        )
        .order_by(
            desc(models.VacationScheduleEntry.end_date),
            desc(models.VacationScheduleEntry.created_at),
        )
    )
    found = session.exec(stmt).all()
    out: Dict[int, Dict[str, Any]] = {}
    for ent in found:
        eid = int(ent.employee_id)
        if eid in out:
            continue
        s_d = _d(ent.start_date)
        e_d = _d(ent.end_date)
        out[eid] = {
            "start": s_d.isoformat() if s_d else "",
            "end": e_d.isoformat() if e_d else "",
            "created_at": ent.created_at.isoformat() if ent.created_at else "",
        }
    return out


def max_completed_approved_vacation_end_by_employee(
    session: Session,
    employee_ids: List[int],
    *,
    ref: Optional[date] = None,
) -> Dict[int, date]:
    """
    Maior data de fim de gozo entre **todos** os lançamentos aprovados já encerrados
    (vários períodos retroativos no planejamento entram no histórico; não depende só
    do registro com ``end_date`` mais recente se esse ainda for futuro).
    """
    ref = ref or date.today()
    if not employee_ids:
        return {}
    unique_ids = sorted({int(x) for x in employee_ids if x is not None})
    if not unique_ids:
        return {}
    stmt = (
        select(
            models.VacationScheduleEntry.employee_id,
            func.max(models.VacationScheduleEntry.end_date).label("max_end"),
        )
        .where(
            col(models.VacationScheduleEntry.employee_id).in_(unique_ids),
            models.VacationScheduleEntry.status == "approved",
            cast(models.VacationScheduleEntry.end_date, Date) < ref,
        )
        .group_by(models.VacationScheduleEntry.employee_id)
    )
    out: Dict[int, date] = {}
    for row in session.exec(stmt).all():
        eid = int(row[0])
        md = row[1]
        if md is not None:
            d = _d(md)
            if d:
                out[eid] = d
    return out


def max_ferias_hist_event_date_by_employee(
    session: Session,
    employee_ids: List[int],
    *,
    ref: date,
) -> Dict[int, date]:
    """
    Maior data civil com evento ``ferias_hist`` no prontuário (rotina), estritamente antes de ``ref``.
    Complementa o planejamento quando o gozo existe no histórico de eventos mas não há entrada aprovada.
    """
    if not employee_ids:
        return {}
    u = sorted({int(x) for x in employee_ids if x is not None})
    if not u:
        return {}
    day_col = cast(models.Event.timestamp, Date)
    stmt = (
        select(
            models.Event.employee_id,
            func.max(day_col).label("mx"),
        )
        .where(
            col(models.Event.employee_id).in_(u),
            models.Event.type == "ferias_hist",
            day_col < ref,
        )
        .group_by(models.Event.employee_id)
    )
    out: Dict[int, date] = {}
    for row in session.exec(stmt).all():
        eid = int(row[0])
        mx = row[1]
        if mx is None:
            continue
        if isinstance(mx, datetime):
            d = mx.date()
        elif isinstance(mx, date):
            d = mx
        else:
            d = _d(mx)
        if d:
            out[eid] = d
    return out


def consolidated_completed_vacation_end_by_employee(
    session: Session,
    employees: Sequence[models.Employee],
    *,
    ref: date,
) -> Dict[int, date]:
    """
    Maior data de fim de gozo **já concluído** conhecida por colaborador, unindo:
    lançamentos aprovados no planejamento, ``vacation_end`` no cadastro (se já passou) e
    último dia com ``ferias_hist`` no prontuário.
    """
    eids = [int(e.id) for e in employees if e.id]
    if not eids:
        return {}
    sched = max_completed_approved_vacation_end_by_employee(session, eids, ref=ref)
    hist = max_ferias_hist_event_date_by_employee(session, eids, ref=ref)
    out: Dict[int, date] = {}
    for e in employees:
        if not e.id:
            continue
        eid = int(e.id)
        cands: List[date] = []
        sd = sched.get(eid)
        if sd:
            cands.append(sd)
        hd = hist.get(eid)
        if hd:
            cands.append(hd)
        ve = _d(e.vacation_end) if e.vacation_end else None
        if ve and ve < ref:
            cands.append(ve)
        if cands:
            out[eid] = max(cands)
    return out


def refresh_profile_last_vacation_from_schedule_batch(
    session: Session, employee_ids: List[int]
) -> None:
    """Atualiza ``last_vacation_end`` no perfil com o maior fim de gozo já concluído no planejamento."""
    ref = date.today()
    ids = sorted({int(x) for x in employee_ids if x})
    if not ids:
        return
    m = max_completed_approved_vacation_end_by_employee(session, ids, ref=ref)
    changed = False
    for eid in ids:
        d = m.get(eid)
        if not d:
            continue
        row = session.exec(
            select(models.EmployeeVacationProfile).where(
                models.EmployeeVacationProfile.employee_id == eid
            )
        ).first()
        if not row:
            continue
        row.last_vacation_end = datetime.combine(d, datetime.min.time())
        row.updated_at = datetime.now()
        session.add(row)
        changed = True
    if changed:
        session.commit()


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
    employees = list_employees_for_vacation(session, cost_center)
    hc_map = headcount_by_role(session, cost_center)

    rows: List[Dict[str, Any]] = []

    windows_year = scheduled_windows(session, date(year, 1, 1), date(year, 12, 31), cost_center)

    eids_for_last = [int(e.id) for e in employees if e.id]
    emp_by_id = {e.id: e for e in employees if e.id}
    last_vac_map = last_approved_vacation_by_employee(session, eids_for_last)
    max_completed_map = consolidated_completed_vacation_end_by_employee(
        session, employees, ref=ref
    )
    future_approved_set = employee_ids_with_approved_future_vacation(session, ref, eids_for_last)

    for e in employees:
        if not e.id:
            continue
        prof = profiles.get(e.id)
        operational = employee_in_operational_vacation_queue(e, prof)
        schedule_end = max_completed_map.get(e.id)
        acq_eff, deadline_basis = effective_acquisition_period_end(prof, e, schedule_end)
        conc_eff = concessive_deadline_effective(prof, e, schedule_end)
        ddead = days_until_deadline(prof, e, ref, schedule_end)
        dl_bucket, _, _ = classify_deadline_row(ddead, deadline_basis)
        has_future = int(e.id) in future_approved_set
        sub_cov = substitute_coverage_required(prof)
        sub_risk_flag = bool(sub_cov and not (prof and prof.substitute_employee_id))
        show_sub_badge = bool(sub_risk_flag)

        status = "ok"
        status_label = "Em dia"
        if dl_bucket == "invalid_data":
            status, status_label = "invalid", "Datas inconsistentes — revisar cadastro"
        elif dl_bucket == "incomplete":
            status, status_label = "incomplete", "Cadastro incompleto — informe admissão ou fim do aquisitivo"
        elif ddead is not None:
            d = int(ddead)
            if d < 0:
                status = "expired"
                dv = min(-d, 999)
                status_label = f"Vencido há {dv}d" if operational else f"Vencido há {dv}d (fora da escala)"
            elif d <= 30:
                status, status_label = "urgent_30", f"Vence em {d}d"
            elif d <= 60:
                status, status_label = "urgent_60", f"Vence em {d}d"
            elif d <= 90:
                status, status_label = "urgent_90", f"Vence em {d}d"
            else:
                status_label = f"Concessivo: {d}d"

        di_view, _heat_view, _, _ = get_month_demand(session, year, cal_month)
        ms = date(year, cal_month, 1)
        prio, _ = priority_index_for_month(
            profile=prof,
            employee=e,
            demand_index=di_view,
            windows=windows_year,
            month_start=ms,
            headcount_by_role_map=hc_map,
            schedule_last_vacation_end=schedule_end,
        )

        rb = role_bucket(e.role)
        best_label = best_future_vacation_month_label(
            session,
            planning_year=year,
            ref=ref,
            profile=prof,
            employee=e,
            role_b=rb,
            headcount_by_role_map=hc_map,
            cost_center=cost_center,
            schedule_last_vacation_end=schedule_end,
        )

        st_color, st_hint = vacation_window_status(di_view)

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
                "deadline_basis": deadline_basis,
                "deadline_bucket": dl_bucket,
                "deadline_basis_label": deadline_basis_public_label(deadline_basis),
                "acquisition_period_end_effective": acq_eff.isoformat() if acq_eff else None,
                "concessive_deadline": conc_eff.isoformat() if conc_eff else None,
                "admission_date": _d(e.admission_date).isoformat() if e.admission_date else None,
                "criticality": (prof.criticality if prof else "media"),
                "substitute": sub_name or "—",
                "substitute_trained": bool(prof and prof.substitute_trained),
                "substitute_risk_relevant": sub_risk_flag,
                "show_substitute_badge": show_sub_badge,
                "operational_queue": operational,
                "heuristic_non_operational": _heuristic_non_operational_employee(e),
                "exclude_operational_flag": bool(
                    prof and getattr(prof, "exclude_from_operational_vacation", False)
                ),
                "has_future_approved_vacation": has_future,
                "best_period_hint": best_label
                or "Sem mês futuro com folga — ajuste régua, limite por função ou o ano do painel",
                "priority_index": round(prio, 1),
                "window_color": st_color,
                "window_hint": st_hint,
                "route_team": (prof.route_team if prof else None) or "",
                "last_completed_vacation_end": schedule_end.isoformat() if schedule_end else None,
            }
        )

    rows.sort(
        key=lambda r: (
            -(r["priority_index"] or 0),
            r["days_until_deadline"] if r["days_until_deadline"] is not None else 9999,
        )
    )

    deadline_map: Dict[int, date] = {}
    for r in rows:
        cd = r.get("concessive_deadline")
        if not cd:
            continue
        try:
            deadline_map[int(r["employee_id"])] = date.fromisoformat(str(cd)[:10])
        except ValueError:
            continue
    covered_ids = employee_ids_approved_vacation_start_on_or_before_deadline(session, ref, deadline_map)
    for r in rows:
        eid = int(r["employee_id"])
        ddead = r.get("days_until_deadline")
        if (
            r.get("operational_queue")
            and r.get("deadline_bucket") == "ok"
            and ddead is not None
            and int(ddead) < 0
            and eid in covered_ids
        ):
            dv = min(-int(ddead), 999)
            r["concessive_covered_by_approval"] = True
            r["vacation_status"] = "scheduled_coverage"
            r["vacation_status_label"] = (
                f"Gozo aprovado no concessivo (início ≤ limite; atraso calendário {dv}d)"
            )

    expired = d30 = d60 = d90 = 0
    for r in rows:
        if not r.get("operational_queue"):
            continue
        if r.get("deadline_bucket") != "ok" or r.get("days_until_deadline") is None:
            continue
        if r.get("vacation_status") == "scheduled_coverage":
            continue
        dd = int(r["days_until_deadline"])
        if dd < 0:
            expired += 1
        elif dd <= 30:
            d30 += 1
        elif dd <= 60:
            d60 += 1
        elif dd <= 90:
            d90 += 1

    ref_ms = date(year, cal_month, 1)
    ref_me = end_of_month(ref_ms)
    scheduled_this_month_ids: set = set()
    on_vacation_ids: set = set()
    returning_7_ids: set = set()
    lim7 = ref + timedelta(days=7)
    for w in windows_year:
        eid = int(w["employee_id"])
        emp = emp_by_id.get(eid)
        if not emp:
            continue
        es = w.get("entry_status")
        if es not in ("approved", "cadastro"):
            continue
        vs, ve = w["start"], w["end"]
        if overlaps(ref_ms, ref_me, vs, ve):
            scheduled_this_month_ids.add(eid)
        if employee_in_operational_vacation_queue(emp, profiles.get(eid)):
            if vs <= ref <= ve:
                on_vacation_ids.add(eid)
            if ref < ve <= lim7:
                returning_7_ids.add(eid)
    scheduled_month = len(scheduled_this_month_ids)
    on_vacation_today = len(on_vacation_ids)
    returning_within_7d = len(returning_7_ids)

    for r in rows:
        eid = int(r["employee_id"])
        r["scheduled_in_focus_month"] = eid in scheduled_this_month_ids
        r["last_approved_vacation"] = last_vac_map.get(eid)
        r["on_vacation_today"] = eid in on_vacation_ids
        r["returning_within_7d"] = eid in returning_7_ids

    sched_detail, sched_dup_merged = scheduled_vacations_in_month_detail(
        session, year=year, month=cal_month, cost_center=cost_center
    )
    sched_stats = scheduled_month_detail_stats(sched_detail)
    scheduled_kpi_gozos = int(sched_stats.get("gozo_count") or 0)

    monthly: List[Dict[str, Any]] = []
    risk_scores = []
    for m in range(1, 13):
        di, heat, note, rjo = get_month_demand(session, year, m)
        ms = date(year, m, 1)
        me = end_of_month(ms)
        sched_ids: set = set()
        for w in windows_year:
            if w.get("entry_status") not in ("approved", "cadastro"):
                continue
            if overlaps(ms, me, w["start"], w["end"]):
                sched_ids.add(w["employee_id"])
        count_v = len(sched_ids)
        cap = sum(effective_role_limit(rk, di, rjo) for rk in hc_map.keys()) if hc_map else 6
        cap = max(1, cap)
        color, hint = vacation_window_status(di)
        load_ratio = count_v / cap
        month_risk = min(100, int(di * 0.65 + load_ratio * 35))
        risk_scores.append(month_risk)
        roles_at_limit: List[str] = []
        for rk in hc_map.keys():
            conc_r = count_role_overlapping(windows_year, rk, ms, me, None)
            lim_r = effective_role_limit(rk, di, rjo)
            if lim_r > 0 and conc_r >= lim_r:
                roles_at_limit.append(rk)
        due_deadlines_count = 0
        for r in rows:
            if not r.get("operational_queue"):
                continue
            if r.get("deadline_bucket") != "ok":
                continue
            cd = r.get("concessive_deadline")
            if not cd:
                continue
            try:
                dcd = date.fromisoformat(str(cd)[:10])
            except ValueError:
                continue
            if ms <= dcd <= me:
                due_deadlines_count += 1
        monthly.append(
            {
                "month": m,
                "month_name": MONTH_NAMES_PT[m],
                "demand_index": di,
                "heat_index": heat,
                "demand_label": "Baixa" if di <= 38 else ("Alta" if di >= 72 else "Média"),
                "heat_label": "Alto" if heat >= 72 else ("Baixo" if heat <= 35 else "Médio"),
                "capacity_hint": cap,
                "scheduled_count": count_v,
                "due_deadlines_count": due_deadlines_count,
                "status_color": color,
                "risk_score": month_risk,
                "hint": hint if not note else f"{hint} {note}",
                "roles_at_limit": roles_at_limit,
                "roles_at_limit_count": len(roles_at_limit),
            }
        )

    op_risk = int(sum(risk_scores) / max(1, len(risk_scores)))
    if 1 <= cal_month <= 12:
        op_risk = monthly[cal_month - 1]["risk_score"]

    mr_cur = monthly[cal_month - 1] if 1 <= cal_month <= 12 else monthly[0]
    cap_cur = max(1, int(mr_cur["capacity_hint"]))
    sched_cur = int(mr_cur["scheduled_count"])
    load_ratio = sched_cur / cap_cur
    base_color = str(mr_cur.get("status_color") or "yellow")
    situation_color = base_color
    if load_ratio >= 1.0:
        situation_color = "red"
    elif load_ratio >= 0.82 and base_color == "green":
        situation_color = "yellow"
    elif load_ratio >= 0.95 and base_color != "red":
        situation_color = "red" if load_ratio >= 1.05 else "yellow"

    decision_key = "aprovado"
    if base_color == "red" or situation_color == "red":
        decision_key = "nao_recomendado"
    elif base_color == "yellow" or situation_color == "yellow":
        decision_key = "atencao"
    elif load_ratio >= 0.72:
        decision_key = "atencao"

    greens = [x for x in monthly if x.get("status_color") == "green"]
    pool = greens if greens else monthly
    best_m = min(
        pool,
        key=lambda x: (
            int(x.get("risk_score") or 0),
            int(x.get("scheduled_count") or 0) / max(1, int(x.get("capacity_hint") or 1)),
        ),
    )
    best_month_num = int(best_m["month"])
    best_month_name = str(best_m["month_name"])

    mn = MONTH_NAMES_PT[cal_month]
    dem_l = str(mr_cur.get("demand_label") or "").lower()
    cur_roles_trouble: List[str] = list(mr_cur.get("roles_at_limit") or [])
    guidance_parts: List[str] = []
    if decision_key == "aprovado":
        guidance_parts.append(f"{mn}/{year} com folga relativa para novos lançamentos.")
    elif decision_key == "atencao":
        guidance_parts.append(f"{mn}/{year} em atenção: combine vencidos e evite picos na mesma função.")
    else:
        guidance_parts.append(f"{mn}/{year} pressionado — capacidade no limite ou demanda alta.")

    if dem_l:
        guidance_parts.append(f"Demanda {dem_l}.")
    guidance_parts.append(
        f"{sched_cur} colaborador(es) com férias no mês de ~{cap_cur} vagas estimadas (aprovadas ou em cadastro)."
    )
    if cur_roles_trouble:
        guidance_parts.append(
            "Funções no limite: "
            + ", ".join(cur_roles_trouble[:5])
            + ("…" if len(cur_roles_trouble) > 5 else "")
            + "."
        )
    if expired > 0:
        guidance_parts.append(f"Prioridade: {expired} concessivo(s) vencido(s) na operação.")
    if best_month_num != cal_month:
        guidance_parts.append(f"Melhor mês coletivo sugerido: {best_month_name}/{year}.")

    guidance_joined = " ".join(guidance_parts)
    if len(guidance_joined) > 240:
        guidance_joined = guidance_joined[:237].rstrip() + "…"

    month_situation: Dict[str, Any] = {
        "month": cal_month,
        "month_name": mn,
        "year": year,
        "status_color": situation_color,
        "demand_label": mr_cur.get("demand_label"),
        "capacity_hint": cap_cur,
        "scheduled_count": sched_cur,
        "due_deadlines_in_month": int(mr_cur.get("due_deadlines_count") or 0),
        "scheduled_gozo_count": scheduled_kpi_gozos,
        "scheduled_unique_employees": int(sched_stats.get("unique_employees") or 0),
        "operational_risk": op_risk,
        "load_ratio": round(load_ratio, 2),
        "decision_key": decision_key,
        "decision_label": RECOMMENDATION_LABEL_PT.get(decision_key, decision_key),
        "guidance_text": guidance_joined,
        "best_month": best_month_num,
        "best_month_name": best_month_name,
        "operational_headline": (
            "Livre"
            if decision_key == "aprovado" and load_ratio < 0.75
            else ("Travado" if load_ratio >= 1.0 or situation_color == "red" else "Atenção")
        ),
        "critical_roles": cur_roles_trouble,
        "critical_roles_count": len(cur_roles_trouble),
    }

    immediate_actions: List[Dict[str, Any]] = []
    for r in rows:
        if not r.get("operational_queue"):
            continue
        if r.get("vacation_status") == "scheduled_coverage":
            continue
        if r.get("deadline_bucket") != "ok" or r.get("days_until_deadline") is None:
            continue
        d = int(r["days_until_deadline"])
        if r.get("has_future_approved_vacation") and d > 30 and d >= 0:
            continue
        needs = (
            d < 0
            or d <= 30
            or (
                r.get("substitute_risk_relevant")
                and ((r.get("substitute") or "—") == "—" or not r.get("substitute_trained"))
            )
            or r.get("window_color") == "red"
        )
        if not needs:
            continue
        if d < 0:
            risk = "alto"
        elif d <= 14 or r.get("substitute_risk_relevant"):
            risk = "medio" if d > 7 else "alto"
        else:
            risk = "baixo"
        lav = r.get("last_approved_vacation") or {}
        le = lav.get("end") if isinstance(lav, dict) else None
        immediate_actions.append(
            {
                "employee_id": r["employee_id"],
                "name": r["name"],
                "role": r["role"],
                "sector": r.get("sector"),
                "status_label": r.get("vacation_status_label"),
                "days_until_deadline": d,
                "best_period_hint": r.get("best_period_hint"),
                "risk_level": risk,
                "priority_index": r.get("priority_index"),
                "last_vacation_end": (str(le)[:10] if le else None),
            }
        )
    immediate_actions.sort(
        key=lambda x: (-(x.get("priority_index") or 0), x.get("days_until_deadline", 9999))
    )
    immediate_actions = immediate_actions[:28]

    nd = sum(1 for e in employees if e.id and not e.admission_date)
    inv_c = sum(1 for r in rows if r.get("deadline_bucket") == "invalid_data")
    inc_c = sum(1 for r in rows if r.get("deadline_bucket") == "incomplete")
    nh = sum(1 for r in rows if r.get("heuristic_non_operational"))
    nrf = sum(1 for r in rows if r.get("exclude_operational_flag"))
    n_sem_funcao = sum(1 for e in employees if e.id and not (str(e.role or "").strip()))
    n_sem_setor = sum(
        1
        for r in rows
        if r.get("operational_queue")
        and r.get("deadline_bucket") == "ok"
        and not (str(r.get("sector") or "").strip())
    )

    dq_groups: Dict[str, Dict[str, Any]] = {
        "invalid": {"label": "Data inválida ou prazo incoerente", "count": inv_c},
        "incomplete": {"label": "Cadastro incompleto (sem prazo)", "count": inc_c},
        "duplicate": {"label": "Gozos duplicados no mês (mesmo colaborador/período)", "count": sched_dup_merged},
        "non_operational": {"label": "Fora da escala operacional (heurística)", "count": nh},
        "exclude_manual": {"label": "Exclusão manual da fila operacional", "count": nrf},
        "admission": {"label": "Sem data de admissão", "count": nd},
        "no_role": {"label": "Sem função no cadastro", "count": n_sem_funcao},
        "no_sector": {"label": "Sem setor/função operacional no perfil", "count": n_sem_setor},
    }
    dq_alerts: List[str] = []
    for _gk, gv in dq_groups.items():
        c = int(gv.get("count") or 0)
        if c > 0:
            dq_alerts.append(f"{gv['label']}: {c}")

    from services.vacation_conflict_analysis import build_operational_conflict_analysis

    operational_conflicts = build_operational_conflict_analysis(
        session,
        year=year,
        month=cal_month,
        cost_center=cost_center,
        rows=rows,
    )

    sched_year = scheduled_vacations_year_list(session, year=year, cost_center=cost_center)

    roster_on_leave: List[Dict[str, Any]] = []
    roster_expired: List[Dict[str, Any]] = []
    roster_due_30: List[Dict[str, Any]] = []
    for r in rows:
        if not r.get("operational_queue"):
            continue
        eid = int(r["employee_id"])
        base = {
            "employee_id": eid,
            "name": r.get("name"),
            "role": r.get("role"),
            "vacation_status_label": r.get("vacation_status_label"),
        }
        if r.get("on_vacation_today"):
            roster_on_leave.append({"employee_id": eid, "name": r.get("name"), "role": r.get("role")})
        ddead = r.get("days_until_deadline")
        if (
            r.get("deadline_bucket") == "ok"
            and ddead is not None
            and r.get("vacation_status") != "scheduled_coverage"
        ):
            dd = int(ddead)
            if dd < 0:
                roster_expired.append({**base, "days_until_deadline": dd})
            elif dd <= 30:
                roster_due_30.append({**base, "days_until_deadline": dd})

    return {
        "year": year,
        "view_month": cal_month,
        "kpis": {
            "expired": expired,
            "due_30": d30,
            "due_60": d60,
            "due_90": d90,
            "due_60_90": d60 + d90,
            "scheduled_in_month": scheduled_kpi_gozos,
            "on_vacation_today": on_vacation_today,
            "returning_within_7d": returning_within_7d,
            "operational_risk_month": op_risk,
        },
        "month_situation": month_situation,
        "operational_conflicts": operational_conflicts,
        "rows": rows,
        "monthly": monthly,
        "immediate_actions": immediate_actions,
        "scheduled_in_month_detail": sched_detail,
        "scheduled_in_month_stats": sched_stats,
        "scheduled_vacations_year": sched_year,
        "roster_snapshots": {
            "on_vacation_today": roster_on_leave,
            "concessive_expired": roster_expired,
            "concessive_due_30": roster_due_30,
        },
        "data_quality": {
            "has_issues": any(int(g.get("count") or 0) > 0 for g in dq_groups.values()),
            "groups": dq_groups,
            "alerts": dq_alerts,
        },
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
    refresh_profile_last_vacation: bool = True,
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
    if refresh_profile_last_vacation:
        refresh_profile_last_vacation_from_schedule_batch(session, [int(employee_id)])
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

    if "exclude_from_operational_vacation" in data:
        row.exclude_from_operational_vacation = bool(data["exclude_from_operational_vacation"])

    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_history(session: Session, limit: int = 80, employee_id: Optional[int] = None) -> List[Dict[str, Any]]:
    stmt = select(models.VacationScheduleEntry)
    if employee_id is not None:
        stmt = stmt.where(models.VacationScheduleEntry.employee_id == int(employee_id))
    stmt = stmt.order_by(desc(models.VacationScheduleEntry.created_at)).limit(limit)
    rows = session.exec(stmt).all()
    out = []
    for ent in rows:
        emp = session.get(models.Employee, ent.employee_id)
        approver = session.get(models.User, ent.approved_by_user_id) if ent.approved_by_user_id else None
        sync_info = None
        if isinstance(ent.conflicts_json, dict):
            sync_info = ent.conflicts_json.get("employee_vacation_sync")
        if bool(getattr(ent, "employee_vacation_synced", False)):
            cadastro_sync_label = "Sim — cadastro atualizado"
        elif (ent.source or "").strip().lower() == "planilha":
            cadastro_sync_label = "Histórico (importação; cadastro não alterado)"
        else:
            cadastro_sync_label = "Não — apenas planejamento"
        out.append(
            {
                "id": ent.id,
                "employee_id": ent.employee_id,
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
                "cadastro_sync_label": cadastro_sync_label,
                "created_at": ent.created_at.isoformat() if ent.created_at else "",
            }
        )
    return out
