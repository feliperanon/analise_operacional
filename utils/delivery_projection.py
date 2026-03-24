from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def _parse_time_value(value: Optional[str], ref_dt: datetime) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    try:
        if "T" in raw or " " in raw:
            iso_value = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_value)
            if dt.tzinfo is None:
                return ref_dt.replace(
                    hour=dt.hour,
                    minute=dt.minute,
                    second=0,
                    microsecond=0,
                )
            if ref_dt.tzinfo is None:
                return dt.replace(second=0, microsecond=0)
            return dt.astimezone(ref_dt.tzinfo).replace(second=0, microsecond=0)
    except Exception:
        pass

    try:
        parts = raw.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return ref_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except Exception:
        return None


def compute_delivery_projection(
    bucket: Dict[str, Any],
    now_br: datetime,
    *,
    operation_start_hour: int = 8,
    operation_end_hour: int = 17,
    baseline_crew_size: float = 2.0,
    attention_buffer_minutes: int = 45,
) -> Dict[str, Any]:
    total = int(bucket.get("total_deliveries") or len(bucket.get("routes") or []) or 0)
    completed = int(bucket.get("completed_deliveries") or 0)
    remaining = max(0, total - completed)

    helper_count = int(bucket.get("helper_count") or len(bucket.get("helper_names") or []) or 0)
    crew_size = max(1, 1 + helper_count)

    routes = bucket.get("routes") or []
    completed_durations = []
    open_elapsed_samples = []
    started_times = []

    for route in routes:
        status = str(route.get("delivery_status") or "").strip().lower()
        duration = route.get("duration_mins")
        if status in ("entregue", "devolucao"):
            try:
                duration_value = float(duration or 0)
                if duration_value > 0:
                    completed_durations.append(duration_value)
            except Exception:
                pass

        start_dt = _parse_time_value(route.get("start_time"), now_br)
        if start_dt:
            started_times.append(start_dt)
            if status == "iniciada":
                elapsed = max(0, int((now_br - start_dt).total_seconds() // 60))
                if elapsed > 0:
                    open_elapsed_samples.append(float(elapsed))

    operation_start_dt = now_br.replace(
        hour=operation_start_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    operation_end_dt = now_br.replace(
        hour=operation_end_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    if operation_end_dt <= operation_start_dt:
        operation_end_dt += timedelta(days=1)

    total_window_minutes = max(
        60,
        int((operation_end_dt - operation_start_dt).total_seconds() // 60),
    )
    planned_avg_minutes = total_window_minutes / max(total, 1)
    planned_avg_minutes *= float(baseline_crew_size) / float(crew_size)
    planned_avg_minutes = max(1.0, planned_avg_minutes)

    projection_basis = "planned_average"
    if completed_durations:
        avg_minutes = sum(completed_durations) / len(completed_durations)
        projection_basis = "completed_average"
    elif open_elapsed_samples:
        avg_minutes = sum(open_elapsed_samples) / len(open_elapsed_samples)
        projection_basis = "open_elapsed_average"
    else:
        avg_minutes = planned_avg_minutes

    avg_minutes = max(1.0, float(avg_minutes))
    projected_remaining_minutes = int(round(remaining * avg_minutes))
    projected_finish_dt = now_br + timedelta(minutes=projected_remaining_minutes)
    slack_minutes = int((operation_end_dt - projected_finish_dt).total_seconds() // 60)
    delay_minutes = max(0, -slack_minutes)

    if remaining <= 0:
        alert_level = "ok"
    elif projected_finish_dt > operation_end_dt:
        alert_level = "critico"
    elif slack_minutes <= attention_buffer_minutes:
        alert_level = "atencao"
    else:
        alert_level = "ok"

    return {
        "helper_count": helper_count,
        "crew_size": crew_size,
        "first_delivery_started_at": min(started_times).strftime("%H:%M") if started_times else None,
        "avg_minutes_per_delivery": round(avg_minutes, 1),
        "planned_avg_minutes_per_delivery": round(planned_avg_minutes, 1),
        "completed_duration_samples": len(completed_durations),
        "projection_basis": projection_basis,
        "projected_remaining_minutes": projected_remaining_minutes,
        "projected_finish_at": projected_finish_dt.strftime("%H:%M") if total > 0 else None,
        "projected_finish_delay_minutes": delay_minutes,
        "projected_finish_slack_minutes": slack_minutes,
        "operation_start_time": operation_start_dt.strftime("%H:%M"),
        "operation_end_time": operation_end_dt.strftime("%H:%M"),
        "route_alert_level": alert_level,
        "route_alert_label": (
            "Crítico" if alert_level == "critico"
            else "Atenção" if alert_level == "atencao"
            else "Normal"
        ),
    }
