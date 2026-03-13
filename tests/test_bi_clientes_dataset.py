# -*- coding: utf-8 -*-
from pathlib import Path
import sys

from sqlmodel import SQLModel, Session, create_engine

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
        )
        client_b = models.Client(
            name="Cliente Beta",
            municipio="Sumare",
            bairro="Nova Veneza",
            segmento="Varejo",
            prioridade_logistica="B",
            status_operacional="ATIVO",
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

        session.add_all(
            [
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
                ),
                models.Route(
                    date="2026-03-05",
                    shift="Manhã",
                    employee_id=driver.id,
                    client_id=client_a.id,
                    start_time="08:00",
                    end_time="10:00",
                    tonnage=50.0,
                    type="delivery",
                    valor_financeiro=500.0,
                    valor_devolucao=100.0,
                    devolucao_volume=10.0,
                    delivery_status="devolucao",
                    delivery_started_at="08:00",
                    delivery_finished_at="10:00",
                    delivery_return_reason="Cliente fechado",
                    delivery_return_category="Logistica",
                    delivery_reopen_count=1,
                    status="pending",
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

        session.add(
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
            detail_client_id=client_a.id,
        )

    alfa = next(row for row in dataset["all_client_rows"] if row["client_id"] == client_a.id)
    beta = next(row for row in dataset["all_client_rows"] if row["client_id"] == client_b.id)

    assert alfa["visits"] == 3
    assert alfa["weekly_peak_visits"] == 2
    assert alfa["returned_occurrences"] == 2
    assert alfa["returned_value"] == 350.0
    assert alfa["top_driver_name"] == "Motorista BI"
    assert alfa["top_motivo_name"] == "Cliente fechado"
    assert alfa["total_duration_m"] == 225.0
    assert beta["returned_occurrences"] == 0
    assert dataset["kpis"]["top_time_client"] == "Cliente Alfa"
    assert dataset["kpis"]["top_return_client"] == "Cliente Alfa"
    assert dataset["detail_client"]["client_id"] == client_a.id
    assert dataset["detail_total"] == 4
