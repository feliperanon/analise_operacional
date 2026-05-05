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


def competence_date_for_operation(d: date) -> date:
    """
    Regra comercial:
    - toda operação do dia D pertence ao último dia útil anterior.
    """
    return previous_business_day(d)


def competence_date_str(operation_date_str: Optional[str]) -> Optional[str]:
    d = _parse_ymd(operation_date_str)
    if not d:
        return None
    return competence_date_for_operation(d).strftime("%Y-%m-%d")
