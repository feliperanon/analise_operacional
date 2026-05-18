# -*- coding: utf-8 -*-
"""KPI financeiro do BI Devoluções alinhado ao TV / dashboard informativo (só competência)."""

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bi_delivery_routes
import models


def test_bi_devolucoes_pct_financeiro_ignora_recorte_operacional_civil_extra():
    """
    Devolução registrada no mobile com romaneio no mês anterior e created_at no mês atual
    entra na listagem (dia operacional), mas não no % valor do KPI (competência fora do período).
    """
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        driver = models.Employee(
            registration_id="MOT-DEV-KPI",
            name="Motorista KPI",
            role="Motorista",
            status="active",
        )
        client = models.Client(
            name="Cliente KPI",
            municipio="Contagem",
            bairro="Centro",
            segmento="Atacado",
            prioridade_logistica="A",
            status_operacional="ATIVO",
        )
        resp = models.DevolucaoResponsabilidade(nome="Logistica")
        session.add(driver)
        session.add(client)
        session.add(resp)
        session.commit()
        session.refresh(driver)
        session.refresh(client)
        session.refresh(resp)

        motivo = models.DevolucaoMotivo(
            nome="Avaria",
            responsabilidade_id=resp.id,
            nome_normalizado="avaria",
        )
        session.add(motivo)
        session.commit()
        session.refresh(motivo)

        route = models.Route(
            date="2026-05-10",
            shift="Manhã",
            employee_id=driver.id,
            client_id=client.id,
            start_time="08:00",
            end_time="09:00",
            type="delivery",
            tonnage=100.0,
            valor_financeiro=1000.0,
            delivery_status="entregue",
            status="pending",
        )
        session.add(route)
        session.commit()
        session.refresh(route)

        # Competência abril; operação civil 10/05 (created_at) — listagem sim, KPI não.
        late_mobile = models.Devolucao(
            data_romaneio="2026-04-28",
            data_entrega="2026-04-28",
            client_id=client.id,
            vendedor_id=driver.id,
            motorista_id=driver.id,
            valor=200.0,
            motivo_id=motivo.id,
            responsabilidade_id=resp.id,
            source="MOBILE",
            created_at=datetime(2026, 5, 10, 9, 0, tzinfo=ZoneInfo("America/Sao_Paulo")),
        )
        in_month = models.Devolucao(
            data_romaneio="2026-05-12",
            data_entrega="2026-05-12",
            client_id=client.id,
            vendedor_id=driver.id,
            motorista_id=driver.id,
            valor=20.0,
            motivo_id=motivo.id,
            responsabilidade_id=resp.id,
            source="WEB",
        )
        session.add(late_mobile)
        session.add(in_month)
        session.commit()

        data = bi_delivery_routes._build_bi_devolucoes_dataset(
            session=session,
            date_from="2026-05-01",
            date_to="2026-05-31",
        )

    assert data["total_qtd"] == 1
    assert data["total_valor"] == 20.0
    assert data["pct_devolucao_financeiro"] is not None
    assert data["pct_devolucao_financeiro"] < 2.5
    assert len(data["rows_detail"]) == 2
