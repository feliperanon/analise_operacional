"""Regras de data mínima de gozo (período aquisitivo) no planejamento de férias."""
from datetime import date, datetime

import models
from services.vacation_planning_service import earliest_allowed_vacation_start_date


def test_earliest_vacation_after_twelve_months_from_admission():
    e = models.Employee(
        id=1,
        registration_id="T-VP-1",
        name="COLAB TESTE",
        admission_date=datetime(2026, 1, 10, 0, 0),
        role="AUXILIAR",
    )
    earliest = earliest_allowed_vacation_start_date(None, e, None)
    # Fim do aquisitivo: admissão + 12 meses − 1 dia → gozo só no dia seguinte.
    assert earliest == date(2027, 1, 10)
