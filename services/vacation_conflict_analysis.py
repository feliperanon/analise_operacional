"""
Análise de conflitos operacionais no planejamento de férias (camada de inteligência).
Usado pelo painel (mês em foco) e pela simulação de lançamento.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlmodel import Session

import models
from services.vacation_planning_service import (
    employee_in_operational_vacation_queue,
    end_of_month,
    effective_role_limit,
    get_month_demand,
    headcount_by_role,
    list_employees_for_vacation,
    load_profiles,
    overlaps,
    role_bucket,
    scheduled_windows,
    substitute_coverage_required,
)

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# Saída típica: 1 motorista + 2 ajudantes; planejamento agregado ~1 : 1,7 ajudantes.
ROUTE_DISPATCH_MIN_MOTORISTS = 1
ROUTE_DISPATCH_MIN_HELPERS = 2
ROUTE_PLANNING_HELPER_RATIO_LABEL = "1,7"

_ROUTE_LABEL_SKIP = frozenset(
    {
        "",
        "-",
        "—",
        "n/a",
        "na",
        "sem",
        "sem rota",
        "nao informado",
        "não informado",
        "nao definido",
        "não definido",
        "s/n",
    }
)

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

_CRITICAL_RAW_SUBSTR = (
    "MOTORIST",
    "AJUDANT",
    "CONFERENT",
    "SEPARAD",
    "EMPILH",
    "EMPILADE",
    "PALET",
    "SUPERVIS",
    "COORDEN",
    "PATIO",
    "PÁTIO",
    "PORTAR",
    "ENTREG",
    "CARREG",
    "CARGA",
    "LOGIST",
    "OPERADOR",
)


def operational_role_tier(employee: models.Employee) -> str:
    """Nível de criticidade operacional inferido pelo cargo (texto livre)."""
    r = (employee.role or "").upper()
    if any(s in r for s in _CRITICAL_RAW_SUBSTR):
        return "critical"
    rb = role_bucket(employee.role)
    if rb in ("MOTORISTA", "AJUDANTE", "CONFERENTE", "SEPARADOR", "CARREGAMENTO", "EXPEDICAO"):
        return "critical"
    return "standard"


def _iso_week_key(d: date) -> Tuple[int, int]:
    y, w, _ = d.isocalendar()
    return (y, w)


def _append_conflict(
    out: List[Dict[str, Any]],
    *,
    ctype: str,
    severity: str,
    title: str,
    message: str,
    recommendation: str,
    employees: Optional[List[Dict[str, Any]]] = None,
    role: Optional[str] = None,
) -> None:
    out.append(
        {
            "type": ctype,
            "severity": severity,
            "title": title,
            "message": message,
            "recommendation": recommendation,
            "employees": employees or [],
            "role": role,
        }
    )


def build_operational_conflict_analysis(
    session: Session,
    *,
    year: int,
    month: int,
    cost_center: Optional[str],
    rows: Sequence[Dict[str, Any]],
    simulation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Conflitos operacionais para o mês civil (year/month) e recorte de empresa.

    ``simulation``: {"employee_id": int, "start": date, "end": date} — inclui um gozo fictício
    na análise (ex.: antes de aprovar).
    """
    ms = date(int(year), int(month), 1)
    me = end_of_month(ms)
    di, heat, _note, rjo = get_month_demand(session, int(year), int(month))
    profiles = load_profiles(session)
    employees = list_employees_for_vacation(session, cost_center)
    emp_by_id: Dict[Any, models.Employee] = {e.id: e for e in employees if e.id}
    hc_map = headcount_by_role(session, cost_center)

    cap_hint = 0
    for rk in hc_map.keys():
        cap_hint += max(1, int(effective_role_limit(rk, di, rjo or {})))
    if cap_hint <= 0:
        cap_hint = max(6, len(hc_map) * 2)

    windows_src = scheduled_windows(session, date(year, 1, 1), date(year, 12, 31), cost_center)
    windows: List[Dict[str, Any]] = []
    for w in windows_src:
        w2 = dict(w)
        eid = w2.get("employee_id")
        emp = emp_by_id.get(eid)
        w2["employee_role_raw"] = (emp.role if emp else "") or ""
        windows.append(w2)

    if simulation:
        eid = int(simulation["employee_id"])
        emp = emp_by_id.get(eid) or session.get(models.Employee, eid)
        if emp and emp.id:
            prof = profiles.get(int(emp.id))
            windows.append(
                {
                    "employee_id": int(emp.id),
                    "name": emp.name,
                    "role_bucket": role_bucket(emp.role),
                    "route_team": (prof.route_team if prof else None) or "",
                    "start": simulation["start"],
                    "end": simulation["end"],
                    "source": "simulation",
                    "entry_status": "simulation",
                    "employee_role_raw": emp.role or "",
                }
            )

    def _in_month(w: Dict[str, Any]) -> bool:
        es = str(w.get("entry_status") or "").strip().lower()
        if es not in ("approved", "cadastro", "suggested", "simulation"):
            return False
        return bool(overlaps(ms, me, w["start"], w["end"]))

    month_windows = [w for w in windows if _in_month(w)]

    conflicts: List[Dict[str, Any]] = []

    # --- Capacidade agregada (heurística) ---
    eids_month: Set[int] = set()
    for w in month_windows:
        eids_month.add(int(w["employee_id"]))
    sched_unique = len(eids_month)
    load_ratio = sched_unique / max(1, cap_hint)
    if load_ratio >= 1.08:
        _append_conflict(
            conflicts,
            ctype="capacity_exceeded",
            severity="critical",
            title="Capacidade do mês excedida",
            message=(
                f"No mês há {sched_unique} colaborador(es) de férias para uma capacidade estimada de "
                f"{cap_hint} vagas (soma dos limites por função na régua). Ocupação ~{load_ratio:.0%}."
            ),
            recommendation=(
                "Redistribuir gozos para meses mais folgados ou, com governança, revisar limites por função na calibragem."
            ),
        )
    elif load_ratio >= 0.95:
        _append_conflict(
            conflicts,
            ctype="capacity_tight",
            severity="high",
            title="Capacidade no teto",
            message=(
                f"O mês está com ~{load_ratio:.0%} da capacidade estimada ({sched_unique} de ~{cap_hint} vagas). "
                "Pouca margem para imprevistos."
            ),
            recommendation="Evite novos lançamentos em funções críticas até equilibrar a grade.",
        )

    # --- Mês sensível (demanda + calor) ---
    demand_high = di >= 72
    heat_high = heat >= 72
    demand_peak = di >= 80
    heat_peak = heat >= 78
    if demand_peak and heat_peak:
        sev = "critical"
    elif (demand_high and heat_high) or demand_peak or heat_peak:
        sev = "high"
    elif di >= 58 or heat >= 58:
        sev = "medium"
    else:
        sev = ""
    if sev:
        _append_conflict(
            conflicts,
            ctype="sensitive_month",
            severity=sev,
            title="Mês sensível (demanda × calor)",
            message=(
                f"Índice de demanda {di}/100 e de calor/sazonalidade {heat}/100. "
                + (
                    "Pico combinado — operação e clima pressionam ao mesmo tempo."
                    if demand_peak and heat_peak
                    else "Volume ou clima acima do padrão do ano para este mês."
                )
            ),
            recommendation=(
                "Evite concentrar férias de motorista, ajudante, conferente, separação, carga e entrega; "
                "antecipe substitutos e rota."
            ),
        )

    # --- Por função (limite efetivo) ---
    for rk, head in hc_map.items():
        seen_e: Set[int] = set()
        concurrent = 0
        for w in month_windows:
            if w.get("role_bucket") != rk:
                continue
            eid = int(w["employee_id"])
            if eid in seen_e:
                continue
            emp = emp_by_id.get(eid)
            if not emp or not employee_in_operational_vacation_queue(emp, profiles.get(eid)):
                continue
            seen_e.add(eid)
            concurrent += 1
        lim = effective_role_limit(rk, di, rjo)
        tier_any = False
        for w in month_windows:
            if w.get("role_bucket") != rk:
                continue
            emp = emp_by_id.get(int(w["employee_id"]))
            if emp and operational_role_tier(emp) == "critical":
                tier_any = True
                break
        if lim <= 0:
            continue
        if concurrent > lim:
            _append_conflict(
                conflicts,
                ctype="role_concentration",
                severity="critical" if tier_any or di >= 75 else "high",
                title="Função concentrada (acima do limite)",
                message=(
                    f"{concurrent} pessoa(s) em férias no mês na função «{rk}». "
                    f"Limite recomendado pela régua: {lim}."
                ),
                recommendation=(
                    f"Remanejar ao menos uma saída de {rk} para um mês com folga no limite, "
                    "ou ajustar com cautela os limites na calibragem mensal."
                ),
                role=rk,
            )
        elif concurrent == lim and (tier_any or di >= 65):
            _append_conflict(
                conflicts,
                ctype="role_at_limit",
                severity="high" if tier_any else "medium",
                title="Função no limite da régua",
                message=(
                    f"«{rk}» está em {concurrent}/{lim} no mês — qualquer imprevisto esgota a folga planejada."
                ),
                recommendation="Só aprovar novos gozos após validar cobertura diária e substitutos.",
                role=rk,
            )
        elif concurrent >= 3 and rk in ("AJUDANTE", "MOTORISTA", "CONFERENTE"):
            _append_conflict(
                conflicts,
                ctype="role_cluster",
                severity="medium",
                title="Concentração na mesma função",
                message=(
                    f"{concurrent} colaboradores em «{rk}» de férias no mesmo mês — risco de falta em rota ou pátio."
                ),
                recommendation="Espalhar inícios entre semanas ou deslocar parte do time para o mês seguinte.",
                role=rk,
            )

    # --- Sobreposição na mesma função (pares) ---
    by_rb: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for w in month_windows:
        by_rb[str(w.get("role_bucket") or "")].append(w)
    pair_added = 0
    for rk, lst in by_rb.items():
        if len(lst) < 2 or not rk:
            continue
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                a, b = lst[i], lst[j]
                if int(a["employee_id"]) == int(b["employee_id"]):
                    continue
                if overlaps(a["start"], a["end"], b["start"], b["end"]):
                    if pair_added >= 8:
                        break
                    pair_added += 1
                    _append_conflict(
                        conflicts,
                        ctype="date_overlap_same_role",
                        severity="medium",
                        title="Sobreposição de datas (mesma função)",
                        message=(
                            f"As férias de {a.get('name') or '—'} e {b.get('name') or '—'} "
                            f"(função «{rk}») coincidem no calendário — a função fica descoberta nesse intervalo."
                        ),
                        recommendation="Negociar nova data para um dos dois ou acionar substituto fixo antes de aprovar.",
                        role=rk,
                        employees=[
                            {"employee_id": int(a["employee_id"]), "name": a.get("name")},
                            {"employee_id": int(b["employee_id"]), "name": b.get("name")},
                        ],
                    )
            if pair_added >= 8:
                break

    # --- Rota / equipe ---
    by_rt: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for w in month_windows:
        rt = (w.get("route_team") or "").strip().lower()
        if len(rt) < 2:
            continue
        by_rt[rt].append(w)
    for rt, lst in by_rt.items():
        if len(lst) < 2:
            continue
        overlap_team = False
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                if overlaps(lst[i]["start"], lst[i]["end"], lst[j]["start"], lst[j]["end"]):
                    overlap_team = True
                    break
            if overlap_team:
                break
        if overlap_team:
            disp = lst[0].get("route_team") or rt
            _append_conflict(
                conflicts,
                ctype="route_team_overlap",
                severity="high",
                title="Equipe / rota com férias sobrepostas",
                message=(
                    f"Dois ou mais colaboradores da mesma equipe ou rota («{disp}») têm férias "
                    "com datas que se cruzam neste mês."
                ),
                recommendation="Garantir cobertura da rota (motorista/ajudante ou equivalente) antes de aprovar.",
            )

    # --- Cobertura por rota (motorista + ajudantes; meta 2 ajudantes por saída) ---
    route_display: Dict[str, str] = {}
    rost_moto: Dict[str, Set[int]] = defaultdict(set)
    rost_ajud: Dict[str, Set[int]] = defaultdict(set)
    for eid, emp in emp_by_id.items():
        if not eid:
            continue
        prof = profiles.get(int(eid))
        raw_rt = (prof.route_team if prof else None) or ""
        rt = raw_rt.strip().lower()
        if len(rt) < 2 or rt in _ROUTE_LABEL_SKIP:
            continue
        if rt not in route_display and raw_rt.strip():
            route_display[rt] = raw_rt.strip()
        rb = role_bucket(emp.role)
        if rb == "MOTORISTA":
            rost_moto[rt].add(int(eid))
        elif rb == "AJUDANTE":
            rost_ajud[rt].add(int(eid))

    vac_moto: Dict[str, Set[int]] = defaultdict(set)
    vac_ajud: Dict[str, Set[int]] = defaultdict(set)
    for w in month_windows:
        raw_rt = (w.get("route_team") or "") or ""
        rt = raw_rt.strip().lower()
        if len(rt) < 2 or rt in _ROUTE_LABEL_SKIP:
            continue
        if rt not in route_display and raw_rt.strip():
            route_display[rt] = raw_rt.strip()
        eid = int(w["employee_id"])
        emp = emp_by_id.get(eid)
        if not emp:
            continue
        rb = str(w.get("role_bucket") or "")
        if rb == "MOTORISTA":
            vac_moto[rt].add(eid)
        elif rb == "AJUDANTE":
            vac_ajud[rt].add(eid)

    all_routes = set(rost_moto.keys()) | set(rost_ajud.keys()) | set(vac_moto.keys()) | set(vac_ajud.keys())
    route_conflict_budget = 16
    route_conflicts_added = 0
    for rt in sorted(all_routes):
        if route_conflicts_added >= route_conflict_budget:
            break
        disp = route_display.get(rt) or rt.upper()
        m_tot = len(rost_moto.get(rt, set()))
        a_tot = len(rost_ajud.get(rt, set()))
        if m_tot == 0 and a_tot == 0:
            continue
        m_v = len(vac_moto.get(rt, set()) & rost_moto.get(rt, set()))
        a_v = len(vac_ajud.get(rt, set()) & rost_ajud.get(rt, set()))
        m_rem = m_tot - m_v
        a_rem = a_tot - a_v

        if m_tot >= ROUTE_DISPATCH_MIN_MOTORISTS and a_tot == 0:
            _append_conflict(
                conflicts,
                ctype="route_roster_thin",
                severity="medium",
                title="Rota sem ajudante no cadastro",
                message=(
                    f"Rota «{disp}»: há {m_tot} motorista(s) vinculado(s) a esta equipe/rota, "
                    "mas nenhum ajudante com a mesma rota no perfil — não dá para validar a saída típica (2 ajudantes)."
                ),
                recommendation="Informar rota/equipe nos perfis dos ajudantes da mesma linha de entrega.",
            )
            route_conflicts_added += 1
            if route_conflicts_added >= route_conflict_budget:
                break

        if m_tot >= 1 and 0 < a_tot < ROUTE_DISPATCH_MIN_HELPERS:
            _append_conflict(
                conflicts,
                ctype="route_roster_thin",
                severity="medium",
                title="Rota com poucos ajudantes no quadro",
                message=(
                    f"Rota «{disp}»: {a_tot} ajudante(s) cadastrado(s) na rota; a operação costuma sair com "
                    f"{ROUTE_DISPATCH_MIN_HELPERS} ajudantes (referência de planejamento ~1 motorista : "
                    f"{ROUTE_PLANNING_HELPER_RATIO_LABEL} ajudantes)."
                ),
                recommendation="Reforçar o quadro ou revisar o cadastro de rota/equipe antes de concentrar férias.",
            )
            route_conflicts_added += 1
            if route_conflicts_added >= route_conflict_budget:
                break

        if m_tot >= ROUTE_DISPATCH_MIN_MOTORISTS and m_rem < ROUTE_DISPATCH_MIN_MOTORISTS:
            _append_conflict(
                conflicts,
                ctype="route_staffing_driver",
                severity="critical",
                title="Rota: motoristas indisponíveis no mês",
                message=(
                    f"Rota «{disp}»: no mês, {m_v} de {m_tot} motorista(s) da rota estão de férias — "
                    "não sobra capacidade típica de condução na equipe."
                ),
                recommendation="Remarcar gozo, alocar motorista de apoio ou revisar a rota antes de aprovar.",
            )
            route_conflicts_added += 1
            if route_conflicts_added >= route_conflict_budget:
                break

        if a_tot >= ROUTE_DISPATCH_MIN_HELPERS and a_rem < ROUTE_DISPATCH_MIN_HELPERS:
            sev_h = "critical" if a_rem <= 0 else "high"
            _append_conflict(
                conflicts,
                ctype="route_staffing_helpers",
                severity=sev_h,
                title="Rota: ajudantes abaixo da saída típica (2)",
                message=(
                    f"Rota «{disp}»: com as férias do mês restam {a_rem} ajudante(s) disponível(is) "
                    f"de {a_tot} no quadro (saída típica com {ROUTE_DISPATCH_MIN_HELPERS} ajudantes por carregamento)."
                ),
                recommendation="Redistribuir férias ou reforçar cobertura para manter 2 ajudantes operando na rota.",
            )
            route_conflicts_added += 1
            if route_conflicts_added >= route_conflict_budget:
                break

    # --- Substituto (um card agregado: evita repetir a mesma mensagem por colaborador) ---
    missing_sub: List[Tuple[int, str]] = []
    seen_sub: Set[int] = set()
    for w in month_windows:
        eid = int(w["employee_id"])
        if eid in seen_sub:
            continue
        emp = emp_by_id.get(eid)
        if not emp:
            continue
        if not employee_in_operational_vacation_queue(emp, profiles.get(eid)):
            continue
        prof = profiles.get(eid)
        if substitute_coverage_required(prof) and not (
            prof and prof.substitute_employee_id and prof.substitute_trained
        ):
            seen_sub.add(eid)
            missing_sub.append((eid, (emp.name or "").strip() or f"ID {eid}"))
    if missing_sub:
        missing_sub.sort(key=lambda t: t[1].lower())
        n = len(missing_sub)
        if di >= 75 and heat >= 70:
            sev_sub = "critical"
        elif n >= 5 or di >= 75 or heat >= 75:
            sev_sub = "high"
        elif n >= 2 or di >= 65 or heat >= 65:
            sev_sub = "high"
        else:
            sev_sub = "medium" if n == 1 and di < 60 and heat < 60 else "high"
        names = [t[1] for t in missing_sub]
        show = names[:6]
        tail = f" e mais {n - len(show)}." if n > len(show) else "."
        if n == 1:
            msg = (
                f"{names[0]}: o perfil exige substituto e não há substituto treinado cadastrado "
                "para cobrir o período de férias."
            )
        else:
            msg = (
                f"{n} colaboradores com função crítica (perfil exige substituto) sem substituto treinado "
                f"no cadastro neste mês. Exemplos: {', '.join(show)}{tail}"
            )
        emp_payload = [{"employee_id": int(eid), "name": nm} for eid, nm in missing_sub[:18]]
        _append_conflict(
            conflicts,
            ctype="substitute_missing",
            severity=sev_sub,
            title="Substituto ausente ou não treinado",
            message=msg,
            recommendation=(
                "Cadastrar substituto, marcar treinamento concluído no perfil, ou remanejar o gozo "
                "até haver cobertura formal."
            ),
            employees=emp_payload,
        )

    # --- Concentração semanal (início) ---
    week_starts: Dict[Tuple[int, int], int] = defaultdict(int)
    for w in month_windows:
        s = w["start"]
        if isinstance(s, date):
            week_starts[_iso_week_key(s)] += 1
    for wk, cnt in week_starts.items():
        if cnt >= 4:
            _append_conflict(
                conflicts,
                ctype="weekly_start_cluster",
                severity="medium",
                title="Picos de início de férias",
                message=(
                    f"{cnt} períodos começam na mesma semana (semana ISO {wk[1]} de {wk[0]}). "
                    "Concentra troca de turno e briefing."
                ),
                recommendation="Deslocar alguns inícios para a semana seguinte ou anterior, se o concessivo permitir.",
            )
            break

    # --- Retornos na mesma semana ---
    week_ends: Dict[Tuple[int, int], int] = defaultdict(int)
    for w in month_windows:
        e = w["end"]
        if isinstance(e, date):
            week_ends[_iso_week_key(e)] += 1
    for wk, cnt in week_ends.items():
        if cnt >= 5:
            _append_conflict(
                conflicts,
                ctype="weekly_return_cluster",
                severity="low",
                title="Retornos na mesma semana",
                message=(
                    f"{cnt} retornos de férias na mesma semana (ISO {wk[1]}/{wk[0]}). "
                    "Pode gerar fila em DP/RH e picos de readaptação."
                ),
                recommendation="Informativo — alinhar recepção e treinamentos rápidos se necessário.",
            )
            break

    # --- Vencidos x mês sensível (usa janelas do mês, não o flag do painel «mês em foco») ---
    sensitive_flag = di >= 70 or heat >= 70
    for r in rows:
        if not r.get("operational_queue"):
            continue
        eid_row = int(r["employee_id"])
        if not any(int(w["employee_id"]) == eid_row for w in month_windows):
            continue
        ddead = r.get("days_until_deadline")
        if ddead is None or int(ddead) >= 0:
            continue
        if r.get("vacation_status") == "scheduled_coverage":
            continue
        if sensitive_flag:
            _append_conflict(
                conflicts,
                ctype="expired_sensitive_month",
                severity="high",
                title="Vencido em mês operacional difícil",
                message=(
                    f"{r.get('name')}: concessivo já vencido, mas o mês combina demanda e calor elevados — "
                    "tensão entre risco trabalhista e continuidade da operação."
                ),
                recommendation=(
                    "Alinhar com RH: gozo em janela mais favorável ou fechar substituto/cobertura antes de registrar."
                ),
                employees=[{"employee_id": int(r["employee_id"]), "name": r.get("name")}],
            )
            break

    # --- Resumo e severidade global ---
    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    affected_roles: Set[str] = set()
    affected_people: Set[int] = set()
    for c in conflicts:
        sev = str(c.get("severity") or "low").lower()
        if sev not in summary:
            sev = "low"
        summary[sev] = summary.get(sev, 0) + 1
        if c.get("role"):
            affected_roles.add(str(c["role"]))
        for e in c.get("employees") or []:
            if isinstance(e, dict) and e.get("employee_id") is not None:
                affected_people.add(int(e["employee_id"]))

    overall = "low"
    if summary["critical"]:
        overall = "critical"
    elif summary["high"]:
        overall = "high"
    elif summary["medium"]:
        overall = "medium"

    total = len(conflicts)
    recommendation_global = (
        "Sem conflitos relevantes para este mês. O mês está apto para novos lançamentos."
        if total == 0
        else _build_global_recommendation(conflicts, overall, MONTH_NAMES_PT[int(month)], int(year))
    )

    conflicts.sort(key=lambda c: -SEVERITY_RANK.get(str(c.get("severity") or "low"), 0))
    conflicts = conflicts[:14]

    return {
        "month": int(month),
        "year": int(year),
        "severity": overall,
        "demand_index": di,
        "heat_index": heat,
        "total_conflicts": total,
        "summary": summary,
        "affected_roles": sorted(affected_roles),
        "affected_employee_count": len(affected_people),
        "recommendation": recommendation_global,
        "conflicts": conflicts,
    }


def _build_global_recommendation(
    conflicts: Sequence[Dict[str, Any]], overall: str, month_name: str, year: int
) -> str:
    top = list(conflicts)[:3]
    parts = [f"Prioridade {overall.upper()} em {month_name}/{year}."]
    for c in top:
        parts.append(f"{c.get('title')}: {c.get('message', '')[:160]}")
    parts.append("Revise os cards abaixo e a calibragem mensal (demanda + calor) se precisar ajustar limites.")
    return " ".join(parts)


def merge_conflict_analyses(
    analyses: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Agrega vários meses (ex.: simulação multi-mês) num único objeto."""
    if not analyses:
        return {
            "month": None,
            "year": None,
            "severity": "low",
            "total_conflicts": 0,
            "summary": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "affected_roles": [],
            "affected_employee_count": 0,
            "recommendation": "Sem conflitos relevantes para este mês. O mês está apto para novos lançamentos.",
            "conflicts": [],
        }
    merged: List[Dict[str, Any]] = []
    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    roles: Set[str] = set()
    people: Set[int] = set()
    seen_msg: Set[str] = set()
    for a in analyses:
        for c in a.get("conflicts") or []:
            key = (c.get("type"), c.get("message"))
            if key in seen_msg:
                continue
            seen_msg.add(key)
            merged.append(c)
        for k, v in (a.get("summary") or {}).items():
            if k in summary and isinstance(v, int):
                summary[k] += v
        for r in a.get("affected_roles") or []:
            roles.add(str(r))
        for c in a.get("conflicts") or []:
            for e in c.get("employees") or []:
                if isinstance(e, dict) and e.get("employee_id") is not None:
                    people.add(int(e["employee_id"]))
    merged.sort(key=lambda c: -SEVERITY_RANK.get(str(c.get("severity") or "low"), 0))
    overall = "low"
    if summary["critical"]:
        overall = "critical"
    elif summary["high"]:
        overall = "high"
    elif summary["medium"]:
        overall = "medium"
    first = analyses[0]
    return {
        "month": first.get("month"),
        "year": first.get("year"),
        "severity": overall,
        "total_conflicts": len(merged),
        "summary": summary,
        "affected_roles": sorted(roles),
        "affected_employee_count": len(people),
        "recommendation": _build_global_recommendation(merged, overall, "Período", int(first.get("year") or 0)),
        "conflicts": merged[:18],
    }


def build_conflicts_for_simulation_period(
    session: Session,
    *,
    start: date,
    end: date,
    cost_center: Optional[str],
    rows: Sequence[Dict[str, Any]],
    simulation: Dict[str, Any],
) -> Dict[str, Any]:
    """Mês a mês coberto por [start, end], com janela simulada em todos."""
    months: Set[Tuple[int, int]] = set()
    d = start
    while d <= end:
        months.add((d.year, d.month))
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    analyses = [
        build_operational_conflict_analysis(
            session,
            year=y,
            month=m,
            cost_center=cost_center,
            rows=rows,
            simulation=simulation,
        )
        for (y, m) in sorted(months)
    ]
    return merge_conflict_analyses(analyses)

