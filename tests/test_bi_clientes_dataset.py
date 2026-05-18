# -*- coding: utf-8 -*-
import json
from pathlib import Path
import sys

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bi_delivery_routes
import models


def test_build_bi_clientes_dataset_aggregates_time_frequency_and_returns():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        driver = models.Employee(
            registration_id="MOT-BI-1",
            name="Motorista BI",
            role="Motorista",
            status="active",
        )
        client_a = models.Client(
            name="Cliente Alfa",
            municipio="Campinas",
            bairro="Centro",
            segmento="Atacado",
            prioridade_logistica="A",
            status_operacional="ATIVO",
            janela_horario_inicio="08:00",
            janela_horario_fim="09:30",
        )
        client_b = models.Client(
            name="Cliente Beta",
            municipio="Sumare",
            bairro="Nova Veneza",
            segmento="Varejo",
            prioridade_logistica="B",
            status_operacional="ATIVO",
            janela_horario_inicio="08:30",
            janela_horario_fim="09:10",
        )
        responsabilidade = models.DevolucaoResponsabilidade(nome="Logistica")
        session.add(driver)
        session.add(client_a)
        session.add(client_b)
        session.add(responsabilidade)
        session.commit()
        session.refresh(driver)
        session.refresh(client_a)
        session.refresh(client_b)
        session.refresh(responsabilidade)

        motivo = models.DevolucaoMotivo(
            nome="Cliente fechado",
            responsabilidade_id=responsabilidade.id,
            nome_normalizado="cliente fechado",
        )
        session.add(motivo)
        session.commit()
        session.refresh(motivo)

        _gps = dict(
            driver_lat_start=-19.926,
            driver_lon_start=-43.950,
            driver_lat_end=-19.927,
            driver_lon_end=-43.951,
        )
        session.add_all(
            [
                models.Route(
                    date="2026-02-20",
                    shift="Manhã",
                    employee_id=driver.id,
                    client_id=client_a.id,
                    start_time="08:30",
                    end_time="09:00",
                    tonnage=80.0,
                    type="delivery",
                    valor_financeiro=1000.0,
                    valor_devolucao=50.0,
                    devolucao_volume=5.0,
                    delivery_status="devolucao",
                    delivery_started_at="08:30",
                    delivery_finished_at="09:00",
                    delivery_return_reason="Cliente fechado",
                    delivery_return_category="Logistica",
                    status="pending",
                ),
                models.Route(
                    date="2026-03-03",
                    shift="Manhã",
                    employee_id=driver.id,
                    client_id=client_a.id,
                    start_time="08:00",
                    end_time="09:00",
                    tonnage=100.0,
                    type="delivery",
                    valor_financeiro=1000.0,
                    delivery_status="entregue",
                    delivery_started_at="08:00",
                    delivery_finished_at="09:00",
                    status="pending",
                    **_gps,
                ),
                models.Route(
                    date="2026-03-05",
                    shift="Manhã",
                    employee_id=driver.id,
                    client_id=client_a.id,
                    start_time="10:00",
                    end_time="12:00",
                    tonnage=50.0,
                    type="delivery",
                    valor_financeiro=500.0,
                    valor_devolucao=100.0,
                    devolucao_volume=10.0,
                    delivery_status="devolucao",
                    delivery_started_at="10:00",
                    delivery_finished_at="12:00",
                    delivery_return_reason="Cliente fechado",
                    delivery_return_category="Logistica",
                    delivery_reopen_count=1,
                    status="pending",
                    **_gps,
                ),
                models.Route(
                    date="2026-03-11",
                    shift="Manhã",
                    employee_id=driver.id,
                    client_id=client_a.id,
                    start_time="08:00",
                    end_time="08:45",
                    tonnage=70.0,
                    type="delivery",
                    valor_financeiro=500.0,
                    delivery_status="entregue",
                    delivery_started_at="08:00",
                    delivery_finished_at="08:45",
                    status="pending",
                    **_gps,
                ),
                models.Route(
                    date="2026-03-04",
                    shift="Manhã",
                    employee_id=driver.id,
                    client_id=client_b.id,
                    start_time="09:00",
                    end_time="09:20",
                    tonnage=40.0,
                    type="delivery",
                    valor_financeiro=800.0,
                    delivery_status="entregue",
                    delivery_started_at="09:00",
                    delivery_finished_at="09:20",
                    status="pending",
                ),
                models.Route(
                    date="2026-03-12",
                    shift="Manhã",
                    employee_id=driver.id,
                    client_id=client_b.id,
                    start_time="09:00",
                    end_time="09:25",
                    tonnage=35.0,
                    type="delivery",
                    valor_financeiro=600.0,
                    delivery_status="entregue",
                    delivery_started_at="09:00",
                    delivery_finished_at="09:25",
                    status="pending",
                ),
            ]
        )
        session.commit()

        route_prev = session.exec(
            select(models.Route)
            .where(models.Route.client_id == client_a.id)
            .where(models.Route.date == "2026-02-20")
        ).one()
        route_current = session.exec(
            select(models.Route)
            .where(models.Route.client_id == client_a.id)
            .where(models.Route.date == "2026-03-05")
        ).one()

        session.add_all(
            [
                models.Devolucao(
                    route_id=route_prev.id,
                    data_romaneio="2026-02-20",
                    data_entrega="2026-02-20",
                    client_id=client_a.id,
                    vendedor_id=driver.id,
                    motorista_id=driver.id,
                    valor=50.0,
                    motivo_id=motivo.id,
                    responsabilidade_id=responsabilidade.id,
                    dia=20,
                    semana=8,
                    acima_300="NAO",
                    source="WEB",
                ),
                models.Devolucao(
                    route_id=route_current.id,
                    data_romaneio="2026-03-05",
                    data_entrega="2026-03-05",
                    client_id=client_a.id,
                    vendedor_id=driver.id,
                    motorista_id=driver.id,
                    valor=100.0,
                    motivo_id=motivo.id,
                    responsabilidade_id=responsabilidade.id,
                    dia=5,
                    semana=10,
                    acima_300="NAO",
                    source="WEB",
                ),
                models.Devolucao(
                    data_romaneio="2026-03-10",
                    data_entrega="2026-03-10",
                    client_id=client_a.id,
                    vendedor_id=driver.id,
                    motorista_id=driver.id,
                    valor=250.0,
                    motivo_id=motivo.id,
                    responsabilidade_id=responsabilidade.id,
                    dia=10,
                    semana=11,
                    acima_300="NAO",
                    source="MANUAL",
                ),
            ]
        )
        session.commit()

        dataset = bi_delivery_routes._build_bi_clientes_dataset(
            session=session,
            date_from="2026-03-01",
            date_to="2026-03-15",
            shift="Todos",
            driver_id=None,
            plate="Todos",
            status="Todos",
            detail_client_id=client_a.id,
        )

    alfa = next(row for row in dataset["all_client_rows"] if row["client_id"] == client_a.id)
    beta = next(row for row in dataset["all_client_rows"] if row["client_id"] == client_b.id)

    assert alfa["visits"] == 3
    assert alfa["weekly_peak_visits"] == 2
    assert alfa["returned_occurrences"] == 2
    assert alfa["returned_value"] == 350.0
    assert alfa["top_driver_name"] == "Motorista BI"
    assert alfa["top_driver_return_name"] == "Motorista BI"
    assert alfa["top_motivo_name"] == "Cliente fechado"
    assert alfa["total_duration_m"] == 225.0
    assert alfa["previous_returned_value"] == 50.0
    assert alfa["previous_return_rate_value"] == 5.0
    assert alfa["delta_return_rate_value"] == 10.56
    assert alfa["window_checks"] == 3
    assert alfa["window_hits"] == 2
    assert alfa["window_misses"] == 1
    assert alfa["window_adherence_pct"] == 66.67
    assert alfa["top_driver_return_share"] == 100.0
    assert alfa["top_responsabilidade_name"] == "Logistica"
    assert alfa["top_responsabilidade_return_share"] == 100.0
    assert beta["returned_occurrences"] == 0
    assert dataset["kpis"]["top_time_client"] == "Cliente Alfa"
    assert dataset["kpis"]["top_return_client"] == "Cliente Alfa"
    assert dataset["kpis"]["worsening_client"] == "Cliente Alfa"
    assert dataset["kpis"]["worsening_delta_pct"] == 10.56
    assert dataset["kpis"]["window_client"] == "Cliente Alfa"
    assert dataset["kpis"]["window_adherence_pct"] == 66.67
    assert dataset["kpis"]["driver_concentration_client"] == "Cliente Alfa"
    assert dataset["kpis"]["driver_concentration_driver"] == "Motorista BI"
    assert dataset["kpis"]["driver_concentration_pct"] == 100.0
    assert dataset["kpis"]["responsibility_concentration_client"] == "Cliente Alfa"
    assert dataset["kpis"]["responsibility_concentration_name"] == "Logistica"
    assert dataset["kpis"]["responsibility_concentration_pct"] == 100.0
    assert dataset["detail_client"]["client_id"] == client_a.id
    assert dataset["detail_total"] == 4
    assert "intel_clients_json" in dataset
    intel = json.loads(dataset["intel_clients_json"])
    assert isinstance(intel, list) and len(intel) >= 1
    assert any(r.get("client_id") == client_a.id for r in intel)
    assert "treatable_drilldown_json" in dataset
    assert isinstance(json.loads(dataset["treatable_drilldown_json"]), list)
    assert isinstance(json.loads(dataset["large_risk_drilldown_json"]), list)
    assert isinstance(json.loads(dataset["critical_drilldown_json"]), list)
    assert isinstance(json.loads(dataset["good_clients_drilldown_json"]), list)
    assert isinstance(json.loads(dataset["reading_cards_json"]), list)
    tabs = json.loads(dataset["client_ranking_tabs_json"])
    assert set(tabs.keys()) == {
        "maior_compra",
        "maior_devolucao",
        "maior_pct",
        "baixo_volume_pct",
        "maior_tempo",
        "pequeno_alto_impacto",
        "grandes_risco",
        "melhores",
    }
    ds = dataset["decision_strip"]
    assert ds["situation_key"] in ("ok", "warn", "crit")
    assert "situation_hint" in ds and len(ds["situation_hint"]) > 10
    assert "secondary_note" in ds
    assert dataset["primeira_acao_texto"]


def test_build_bi_clientes_dataset_ignores_placeholder_midnight_start_for_duration():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        driver = models.Employee(
            registration_id="MOT-BI-2",
            name="Motorista Placeholder",
            role="Motorista",
            status="active",
        )
        client = models.Client(
            name="Cliente Placeholder",
            municipio="Betim",
            bairro="Centro",
            segmento="Atacado",
            prioridade_logistica="A",
            status_operacional="ATIVO",
            janela_horario_inicio="08:00",
            janela_horario_fim="12:00",
        )
        session.add(driver)
        session.add(client)
        session.commit()
        session.refresh(driver)
        session.refresh(client)

        session.add(
            models.Route(
                date="2026-03-06",
                shift="Manhã",
                employee_id=driver.id,
                client_id=client.id,
                start_time="00:00",
                end_time="16:35",
                type="delivery",
                valor_financeiro=2392.5,
                delivery_status="entregue",
                delivery_started_at=None,
                delivery_finished_at="16:35",
                delivery_vehicle_plate="PWJ2808",
                delivery_order_number="147",
                status="completed",
            )
        )
        session.commit()

        dataset = bi_delivery_routes._build_bi_clientes_dataset(
            session=session,
            date_from="2026-03-01",
            date_to="2026-03-15",
            shift="Todos",
            driver_id=None,
            plate="Todos",
            status="Todos",
            detail_client_id=client.id,
        )

    row = next(row for row in dataset["detail_rows"] if row["order_number"] == "147")
    client_row = next(row for row in dataset["all_client_rows"] if row["client_id"] == client.id)

    assert row["duration_m"] is None
    assert row["visit_time"] == ""
    assert client_row["total_duration_m"] == 0.0
    assert client_row["window_checks"] == 0


def test_bi_client_return_pct_planned_avoids_tiny_planned_denominator():
    """Sem planejado, % não deve usar R$ 0,01 (explodia com devoluções manuais)."""
    pct = bi_delivery_routes._bi_client_return_pct_planned(0.0, 9748.75, 500.0)
    assert abs(pct - (500.0 / 9748.75 * 100.0)) < 0.02
    assert bi_delivery_routes._bi_client_return_pct_planned(0.0, 9748.75, 9748.75) == 100.0
    assert bi_delivery_routes._bi_client_return_pct_planned(0.0, 0.0, 9748.75) == 100.0
    assert bi_delivery_routes._safe_pct(9748.75, 0.01) > 1_000_000


def test_json_for_inline_script_replaces_nan_with_null():
    payload = {
        "exec_compare_bars": {
            "previous": [float("nan"), 44719.12, float("inf"), -float("inf")],
        },
        "delta": float("nan"),
    }
    raw = bi_delivery_routes._json_for_inline_script(payload)
    parsed = json.loads(raw)
    assert parsed["exec_compare_bars"]["previous"] == [None, 44719.12, None, None]
    assert parsed["delta"] is None
    assert "NaN" not in raw
