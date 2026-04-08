# -*- coding: utf-8 -*-
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import models
from devolucoes_consolidado import consolidado_avaliar_resumo, motorista_returns_mobile_bundle


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


def test_compute_employee_returns_metrics_aligns_with_desktop_consolidado():
    """Mobile usa o mesmo consolidado do desktop: % por contagem; valores só de Devolução."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        motorista = models.Employee(
            registration_id="EMP1",
            name="Motorista Teste",
            role="Motorista",
            status="active",
        )
        vendedor = models.Employee(
            registration_id="EMP2",
            name="Vendedor Teste",
            role="Vendedor",
            status="active",
        )
        client = models.Client(name="Cliente Teste")
        session.add(motorista)
        session.add(vendedor)
        session.add(client)
        session.commit()
        session.refresh(motorista)
        session.refresh(vendedor)
        session.refresh(client)

        resp = models.DevolucaoResponsabilidade(nome="MERCADO_TEST")
        session.add(resp)
        session.commit()
        session.refresh(resp)
        mot = models.DevolucaoMotivo(
            nome="Motivo Teste",
            responsabilidade_id=resp.id,
            nome_normalizado="motivoteste",
        )
        session.add(mot)
        session.commit()
        session.refresh(mot)

        route = models.Route(
            date="2026-03-05",
            shift="Manhã",
            employee_id=motorista.id,
            client_id=client.id,
            start_time="08:00",
            end_time="09:00",
            tonnage=500.0,
            type="delivery",
            valor_financeiro=1000.0,
            delivery_status="entregue",
            status="completed",
        )
        session.add(route)

        dev = models.Devolucao(
            data_romaneio="2026-03-05",
            data_entrega="2026-03-05",
            client_id=client.id,
            vendedor_id=vendedor.id,
            motorista_id=motorista.id,
            valor=100.0,
            motivo_id=mot.id,
            responsabilidade_id=resp.id,
            dia=5,
            semana=1,
            source="TEST",
        )
        session.add(dev)
        session.commit()

        metrics = main._compute_employee_returns_metrics(
            session=session,
            user_id=motorista.id,
            date_from="2026-03-01",
            date_to="2026-03-12",
        )

    assert metrics["total_value"] == 100.0
    assert metrics["total_value_adjusted"] == 100.0
    assert metrics["percent_valor"] == 50.0
    assert metrics["percent_valor_adjusted"] == 50.0
    assert metrics["total_entregas_value"] == 1000.0
    # Um ponto por dia no filtro (01/03 a 12/03 = 12 dias); soma da série = total do período
    assert len(metrics.get("chart_dates_iso") or []) == 12
    assert len(metrics.get("chart_values") or []) == 12
    assert abs(sum(metrics["chart_values"]) - 100.0) < 1e-6
    assert abs(sum(metrics["chart_adjusted_values"]) - 100.0) < 1e-6
    assert metrics.get("_debug", {}).get("series_closure_ok") is True

    resumo = consolidado_avaliar_resumo(session, "2026-03-01", "2026-03-12")
    row_desktop = next((r for r in resumo["data"] if r.get("motorista_id") == motorista.id), None)
    assert row_desktop is not None
    bundle = motorista_returns_mobile_bundle(session, motorista.id, "2026-03-01", "2026-03-12")
    assert row_desktop == bundle["row"], "desktop consolidado e mobile bundle devem ser idênticos"
