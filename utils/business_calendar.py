from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Optional, Set


# Feriados nacionais fixos (Brasil). Feriados móveis podem ser adicionados por env.
_FIXED_BR_HOLIDAYS = {
    (1, 1),   # Confraternização Universal
    (4, 21),  # Tiradentes
    (5, 1),   # Dia do Trabalho
    (9, 7),   # Independência do Brasil
    (10, 12), # Nossa Senhora Aparecida
    (11, 2),  # Finados
    (11, 15), # Proclamação da República
    (12, 25), # Natal
}


def _parse_ymd(raw: Optional[str]) -> Optional[date]:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _env_holidays() -> Set[date]:
    """
    Lê feriados extras de BUSINESS_HOLIDAYS em formato:
    YYYY-MM-DD,YYYY-MM-DD
    """
    raw = os.getenv("BUSINESS_HOLIDAYS", "")
    out: Set[date] = set()
    for item in raw.split(","):
        d = _parse_ymd(item)
        if d:
            out.add(d)
    return out


def is_non_working_day(d: date) -> bool:
    if d.weekday() >= 5:  # sábado/domingo
        return True
    if (d.month, d.day) in _FIXED_BR_HOLIDAYS:
        return True
    if d in _env_holidays():
        return True
    return False


def previous_business_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while is_non_working_day(cur):
        cur -= timedelta(days=1)
    return cur


def first_business_day_of_month(y: int, m: int) -> date:
    """Primeiro dia útil do calendário (dia 1 em diante) no mês y-m."""
    d = date(y, m, 1)
    while is_non_working_day(d):
        d += timedelta(days=1)
    return d


def competence_date_for_operation(d: date) -> date:
    """
    Regra comercial:
    - Se D for dia não útil, competência = último dia útil anterior.
    - Virada de mês: o primeiro dia útil do mês de D sempre fecha no último
      dia útil do mês anterior (ciclo contábil do mês anterior).
    - Demais dias úteis: se o dia calendário anterior for não útil,
      competência = último dia útil antes de D; senão mantém D.
    """
    if is_non_working_day(d):
        return previous_business_day(d)
    if d == first_business_day_of_month(d.year, d.month):
        return previous_business_day(date(d.year, d.month, 1))
    prev_day = d - timedelta(days=1)
    if is_non_working_day(prev_day):
        return previous_business_day(d)
    return d


def competence_date_str(operation_date_str: Optional[str]) -> Optional[str]:
    d = _parse_ymd(operation_date_str)
    if not d:
        return None
    return competence_date_for_operation(d).strftime("%Y-%m-%d")


def commercial_month_start_date(y: int, m: int) -> date:
    """
    Primeiro dia civil do mês m em que a competência da operação já cai no próprio mês y-m
    (virada do mês anterior encerrada — ex.: maio/2026 começa em 05/05: entregas de 01–04/05
    ainda competem em abril).
    """
    if m == 12:
        last_c = date(y, 12, 31)
    else:
        last_c = date(y, m + 1, 1) - timedelta(days=1)
    d = date(y, m, 1)
    while d <= last_c:
        comp = competence_date_for_operation(d)
        if comp.year == y and comp.month == m:
            return d
        d += timedelta(days=1)
    return first_business_day_of_month(y, m)


def commercial_month_end_calendar_date(y: int, m: int) -> date:
    """Último dia civil do mês m (teto das competências que ainda são 'mês m')."""
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


def commercial_competence_period_iso_bounds(y: int, m: int) -> tuple[str, str]:
    """
    Intervalo inclusivo de datas de competência (YYYY-MM-DD) do mês comercial (y, m).
    Início = primeiro dia civil em que a competência já é mês m; fim = último dia civil de m.
    """
    s = commercial_month_start_date(y, m)
    e = commercial_month_end_calendar_date(y, m)
    return s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")
