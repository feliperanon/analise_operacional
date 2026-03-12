# -*- coding: utf-8 -*-
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import models


def test_delivery_route_return_metrics_uses_planned_value_when_return_has_only_volume():
    route = SimpleNamespace(
        valor_financeiro=1000.0,
        tonnage=500.0,
        delivery_status="pendente",
        valor_devolucao=0.0,
        devolucao_volume=10.0,
    )

    metrics = main._delivery_route_return_metrics(route)

    assert metrics["has_return"] is True
    assert metrics["returned_value"] == 1000.0
    assert metrics["returned_weight"] == 10.0


def test_compute_employee_returns_metrics_matches_gamification_route_rule():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(
            registration_id="EMP1",
            name="Motorista Teste",
            role="Motorista",
            status="active",
        )
        client = models.Client(name="Cliente Teste")
        session.add(employee)
        session.add(client)
        session.commit()
        session.refresh(employee)
        session.refresh(client)

        route = models.Route(
            date="2026-03-05",
            shift="Manhã",
            employee_id=employee.id,
            client_id=client.id,
            start_time="08:00",
            end_time="09:00",
            tonnage=500.0,
            type="delivery",
            valor_financeiro=1000.0,
            devolucao_volume=10.0,
            valor_devolucao=0.0,
            delivery_status="pendente",
            status="pending",
        )
        session.add(route)
        session.commit()

        metrics = main._compute_employee_returns_metrics(
            session=session,
            user_id=employee.id,
            date_from="2026-03-01",
            date_to="2026-03-12",
        )

    assert metrics["total_value"] == 1000.0
    assert metrics["total_entregas_value"] == 1000.0
    assert metrics["percent_valor"] == 100.0
