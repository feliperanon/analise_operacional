from pathlib import Path
import sys

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bi_delivery_routes
import models


def test_bi_financial_kpis_use_consolidated_devolucao_rows():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        driver = models.Employee(
            registration_id="MOT-FIN-1",
            name="Motorista Consolidado",
            role="Motorista",
            status="active",
        )
        client = models.Client(
            name="Cliente Consolidado",
            municipio="Contagem",
            bairro="Centro",
            segmento="Atacado",
            prioridade_logistica="A",
            status_operacional="ATIVO",
        )
        responsabilidade = models.DevolucaoResponsabilidade(nome="Logistica")
        session.add(driver)
        session.add(client)
        session.add(responsabilidade)
        session.commit()
        session.refresh(driver)
        session.refresh(client)
        session.refresh(responsabilidade)

        motivo = models.DevolucaoMotivo(
            nome="Cliente fechado",
            responsabilidade_id=responsabilidade.id,
            nome_normalizado="cliente fechado",
        )
        session.add(motivo)
        session.commit()
        session.refresh(motivo)

        route_with_canonical = models.Route(
            date="2026-03-05",
            shift="Manhã",
            employee_id=driver.id,
            client_id=client.id,
            start_time="08:00",
            end_time="09:00",
            type="delivery",
            tonnage=100.0,
            valor_financeiro=1000.0,
            valor_devolucao=100.0,
            devolucao_volume=10.0,
            delivery_status="devolucao",
            delivery_started_at="08:00",
            delivery_finished_at="09:00",
            delivery_return_reason="Cliente fechado",
            delivery_return_category="Logistica",
            status="pending",
        )
        route_without_canonical = models.Route(
            date="2026-03-06",
            shift="Manhã",
            employee_id=driver.id,
            client_id=client.id,
            start_time="10:00",
            end_time="11:00",
            type="delivery",
            tonnage=80.0,
            valor_financeiro=800.0,
            valor_devolucao=300.0,
            devolucao_volume=8.0,
            delivery_status="devolucao",
            delivery_started_at="10:00",
            delivery_finished_at="11:00",
            delivery_return_reason="Cliente fechado",
            delivery_return_category="Logistica",
            status="pending",
        )
        session.add(route_with_canonical)
        session.add(route_without_canonical)
        session.commit()
        session.refresh(route_with_canonical)

        canonical = models.Devolucao(
            route_id=route_with_canonical.id,
            data_romaneio="2026-03-05",
            data_entrega="2026-03-05",
            client_id=client.id,
            vendedor_id=driver.id,
            motorista_id=driver.id,
            valor=100.0,
            motivo_id=motivo.id,
            responsabilidade_id=responsabilidade.id,
            dia=5,
            semana=10,
            acima_300="NAO",
            cluster="0-50",
            source="WEB",
        )
        standalone_excel = models.Devolucao(
            data_romaneio="2026-03-07",
            data_entrega="2026-03-07",
            client_id=client.id,
            vendedor_id=driver.id,
            motorista_id=driver.id,
            valor=250.0,
            motivo_id=motivo.id,
            responsabilidade_id=responsabilidade.id,
            dia=7,
            semana=10,
            acima_300="NAO",
            cluster="200-300",
            source="EXCEL",
        )
        session.add(canonical)
        session.add(standalone_excel)
        session.commit()
        session.refresh(canonical)

        duplicate_excel = models.Devolucao(
            route_id=route_with_canonical.id,
            data_romaneio="2026-03-05",
            data_entrega="2026-03-05",
            client_id=client.id,
            vendedor_id=driver.id,
            motorista_id=driver.id,
            valor=100.0,
            motivo_id=motivo.id,
            responsabilidade_id=responsabilidade.id,
            dia=5,
            semana=10,
            acima_300="NAO",
            cluster="0-50",
            source="EXCEL",
            duplicate_of_id=canonical.id,
            validation_status="DUPLICATE_EXCEL",
        )
        session.add(duplicate_excel)
        session.commit()

        delivery_dataset = bi_delivery_routes._build_bi_delivery_dataset(
            session=session,
            date_from="2026-03-01",
            date_to="2026-03-10",
            shift="Todos",
            driver_id=None,
            plate="Todos",
            status="Todos",
        )
        clientes_dataset = bi_delivery_routes._build_bi_clientes_dataset(
            session=session,
            date_from="2026-03-01",
            date_to="2026-03-10",
            shift="Todos",
            driver_id=None,
            plate="Todos",
            status="Todos",
            detail_client_id=client.id,
        )

    assert delivery_dataset["kpis"]["total_devolucoes"] == 3
    assert delivery_dataset["kpis"]["valor_total_devolvido"] == 350.0
    assert delivery_dataset["kpis"]["return_rate_value"] == 17.07
    assert delivery_dataset["kpis"]["devolucao_mes_anterior_valor"] == 0.0
    assert delivery_dataset["tactical_rows"][0]["returned_value"] == 350.0
    assert len(delivery_dataset["all_financial_rows"]) == 2

    client_row = clientes_dataset["all_client_rows"][0]
    assert clientes_dataset["executive_kpis"]["returned_value"] == 350.0
    assert clientes_dataset["executive_kpis"]["return_pct_value"] == 17.07
    assert client_row["returned_value"] == 350.0
    assert client_row["returned_occurrences"] == 2
