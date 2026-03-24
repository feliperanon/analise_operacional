from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.delivery_projection import compute_delivery_projection


TZ = ZoneInfo("America/Sao_Paulo")


def _now(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, 24, hour, minute, tzinfo=TZ)


def test_completed_average_drives_eta():
    bucket = {
        "total_deliveries": 5,
        "completed_deliveries": 2,
        "helper_count": 1,
        "routes": [
            {"delivery_status": "entregue", "duration_mins": 10},
            {"delivery_status": "devolucao", "duration_mins": 30},
        ],
    }

    projection = compute_delivery_projection(bucket, _now(10, 40))

    assert projection["projection_basis"] == "completed_average"
    assert projection["avg_minutes_per_delivery"] == 20.0
    assert projection["projected_remaining_minutes"] == 60
    assert projection["projected_finish_at"] == "11:40"
    assert projection["route_alert_level"] == "ok"


def test_more_helpers_reduce_planned_eta():
    base_bucket = {
        "total_deliveries": 9,
        "completed_deliveries": 6,
        "routes": [],
    }

    one_helper = compute_delivery_projection({**base_bucket, "helper_count": 1}, _now(13, 0))
    two_helpers = compute_delivery_projection({**base_bucket, "helper_count": 2}, _now(13, 0))

    assert one_helper["projection_basis"] == "planned_average"
    assert two_helpers["projection_basis"] == "planned_average"
    assert two_helpers["planned_avg_minutes_per_delivery"] < one_helper["planned_avg_minutes_per_delivery"]
    assert two_helpers["projected_finish_at"] < one_helper["projected_finish_at"]


def test_eta_after_deadline_becomes_critical():
    bucket = {
        "total_deliveries": 4,
        "completed_deliveries": 2,
        "helper_count": 1,
        "routes": [
            {"delivery_status": "entregue", "duration_mins": 30},
            {"delivery_status": "devolucao", "duration_mins": 30},
        ],
    }

    critical = compute_delivery_projection(bucket, _now(16, 30))
    attention = compute_delivery_projection(bucket, _now(16, 0))

    assert critical["projected_finish_at"] == "17:30"
    assert critical["route_alert_level"] == "critico"
    assert critical["projected_finish_delay_minutes"] == 30

    assert attention["projected_finish_at"] == "17:00"
    assert attention["route_alert_level"] == "atencao"
