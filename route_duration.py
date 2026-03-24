# -*- coding: utf-8 -*-
"""
Cálculo de duração de entrega por ciclos operacionais.

Cada entrega pode ter vários ciclos (reaberturas). Cada ciclo é um par:
  iniciado_em (evento "iniciar") + fechado_em (evento "finalizar" ou "devolucao").
Só entra na soma quando os dois existirem para aquele ciclo.
Total = soma das durações de cada ciclo (não primeiro início até última finalização).
"""

from typing import Optional, Any
from datetime import datetime, date
from zoneinfo import ZoneInfo
import json


def _parse_hhmm(v: Optional[str]) -> Optional[int]:
    """Converte string HH:MM em minutos desde meia-noite. Retorna None se inválido."""
    if not v:
        return None
    try:
        parts = str(v).strip().split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        return h * 60 + m
    except (ValueError, IndexError, TypeError):
        return None


def _duration_single_min(start_v: Optional[str], end_v: Optional[str]) -> Optional[int]:
    """Duração em minutos entre dois horários HH:MM. Se end < start, considera virada de dia (+24h)."""
    s, e = _parse_hhmm(start_v), _parse_hhmm(end_v)
    if s is None or e is None:
        return None
    if e < s:
        e += 24 * 60
    return max(0, e - s)


def route_duration_minutes(route: Any) -> Optional[int]:
    """
    Retorna a duração total da entrega em minutos, somando apenas ciclos completos
    (cada par iniciar + finalizar/devolucao do delivery_time_log).
    Se não houver log ou pares completos, usa fallback: um único par
    (delivery_started_at ou start_time, delivery_finished_at ou end_time).
    """
    history: list = []
    try:
        if getattr(route, "delivery_time_log", None):
            raw = json.loads(route.delivery_time_log)
            if isinstance(raw, list):
                history = raw
    except Exception:
        pass

    total = 0
    pending_start: Optional[str] = None
    for entry in history:
        if not isinstance(entry, dict):
            continue
        ev = (entry.get("event") or "").strip().lower()
        t = entry.get("time")
        if not t:
            continue
        time_str = str(t).strip() if t else None
        if not time_str:
            continue
        if ev == "iniciar":
            pending_start = time_str
        elif ev in ("finalizar", "devolucao") and pending_start is not None:
            d = _duration_single_min(pending_start, time_str)
            if d is not None:
                total += d
            pending_start = None

    if total > 0:
        return total

    # Fallback: um único par início/fim
    start_ref = getattr(route, "delivery_started_at", None) or getattr(route, "start_time", None)
    end_ref = getattr(route, "delivery_finished_at", None) or getattr(route, "end_time", None)
    return _duration_single_min(start_ref, end_ref)


def route_duration_minutes_mobile_only(route: Any) -> Optional[int]:
    """
    Duração para métricas (BI, custo operacional): só quando início e fim foram
    registrados pelo app do motorista (GPS em iniciar e em finalizar/devolução).
    Finalização só pela web (separação) não preenche driver_lat_end — não entra.
    """
    if getattr(route, "driver_lat_start", None) is None:
        return None
    if getattr(route, "driver_lon_start", None) is None:
        return None
    if getattr(route, "driver_lat_end", None) is None:
        return None
    if getattr(route, "driver_lon_end", None) is None:
        return None
    return route_duration_minutes(route)


def iniciada_elapsed_wall_minutes(route: Any, route_day: date, now_br: datetime) -> Optional[int]:
    """
    Minutos decorridos desde o horário de início da parada (HH:MM no dia route_day)
    até now_br. Só para rotas com delivery_status iniciada; alinhado ao painel TV / alertas.
    """
    st = (getattr(route, "delivery_status", None) or "").strip().lower()
    if st != "iniciada":
        return None
    started_at_str = getattr(route, "delivery_started_at", None) or getattr(route, "start_time", None)
    if not started_at_str or str(started_at_str).strip() in ("", "00:00"):
        return None
    try:
        parts = str(started_at_str).strip().split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        tz = now_br.tzinfo or ZoneInfo("America/Sao_Paulo")
        started_dt = datetime(route_day.year, route_day.month, route_day.day, h, m, 0, tzinfo=tz)
        return max(0, int((now_br - started_dt).total_seconds() // 60))
    except Exception:
        return None
