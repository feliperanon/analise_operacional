# -*- coding: utf-8 -*-
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import models


def _make_request(user_id: int):
    return SimpleNamespace(session={"user_id": user_id})


def test_api_mobile_delivery_history_counts_route_return_signal():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(
            registration_id="EMP-HIST-1",
            name="Tiago Teste",
            role="Motorista",
            status="active",
            mobile_access_separation=True,
        )
        client = models.Client(name="Cliente Historico")
        session.add(employee)
        session.add(client)
        session.commit()
        session.refresh(employee)
        session.refresh(client)

        session.add(
            models.Route(
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
                delivery_status="entregue",
                status="pending",
            )
        )
        session.commit()

        response = asyncio.run(
            main.api_mobile_delivery_history(
                _make_request(employee.id),
                "2026-03-01",
                "2026-03-12",
                session,
            )
        )

    payload = json.loads(response.body)
    assert payload["success"] is True
    assert payload["days"][0]["clientes_devolucao"] == 1
    assert payload["days"][0]["taxa_devolucao_pct"] == 100.0


def test_api_mobile_delivery_history_includes_standalone_devolucao_day():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(
            registration_id="EMP-HIST-2",
            name="Tiago Teste",
            role="Motorista",
            status="active",
            mobile_access_separation=True,
        )
        client = models.Client(name="Cliente Standalone")
        responsabilidade = models.DevolucaoResponsabilidade(nome="Logistica")
        session.add(employee)
        session.add(client)
        session.add(responsabilidade)
        session.commit()
        session.refresh(employee)
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

        session.add(
            models.Devolucao(
                data_romaneio="2026-03-07",
                data_entrega="2026-03-07",
                client_id=client.id,
                vendedor_id=employee.id,
                motorista_id=employee.id,
                valor=250.0,
                motivo_id=motivo.id,
                responsabilidade_id=responsabilidade.id,
                dia=7,
                semana=10,
                acima_300="NAO",
                source="MANUAL",
            )
        )
        session.commit()

        response = asyncio.run(
            main.api_mobile_delivery_history(
                _make_request(employee.id),
                "2026-03-01",
                "2026-03-12",
                session,
            )
        )

    payload = json.loads(response.body)
    assert payload["success"] is True
    assert payload["days"][0]["date"] == "2026-03-07"
    assert payload["days"][0]["clientes_devolucao"] == 1
    assert payload["days"][0]["valor_devolucao"] == 250.0
