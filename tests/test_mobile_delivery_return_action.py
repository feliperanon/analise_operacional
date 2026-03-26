# -*- coding: utf-8 -*-
import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import models


def _make_request(user_id: int):
    return SimpleNamespace(session={"user_id": user_id})


def _seed_mobile_delivery_return_context(session: Session):
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    employee = models.Employee(
        registration_id="EMP-RET-1",
        name="Motorista Teste",
        role="Motorista",
        status="active",
        mobile_access_separation=True,
    )
    client = models.Client(name="Cliente Retorno")
    responsabilidade = models.DevolucaoResponsabilidade(nome="COMERCIAL")
    session.add(employee)
    session.add(client)
    session.add(responsabilidade)
    session.commit()
    session.refresh(employee)
    session.refresh(client)
    session.refresh(responsabilidade)

    motivo_nome = main.DELIVERY_RETURN_REASONS["COMERCIAL"][0]
    motivo = models.DevolucaoMotivo(
        nome=motivo_nome,
        responsabilidade_id=responsabilidade.id,
        nome_normalizado=motivo_nome.lower(),
    )
    route = models.Route(
        date=today,
        shift="Manhã",
        employee_id=employee.id,
        client_id=client.id,
        start_time="08:00",
        tonnage=120.0,
        type="delivery",
        valor_financeiro=600.0,
        delivery_status="iniciada",
        status="pending",
    )
    delivery_session = models.DeliverySession(
        date=today,
        employee_id=employee.id,
        status="open",
        vehicle_plate="ABC1D23",
        km_departure=1000.0,
        started_at=datetime.now(ZoneInfo("America/Sao_Paulo")),
    )
    session.add(motivo)
    session.add(route)
    session.add(delivery_session)
    session.commit()
    session.refresh(motivo)
    session.refresh(route)
    return employee, client, route, motivo_nome


def test_api_mobile_delivery_return_requires_commercial_and_logistics_flags():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee, _, route, motivo_nome = _seed_mobile_delivery_return_context(session)

        response = asyncio.run(
            main.api_mobile_delivery_route_action(
                _make_request(employee.id),
                route.id,
                main.MobileDeliveryActionPayload(
                    action="devolucao",
                    return_reason=motivo_nome,
                ),
                session,
            )
        )

    payload = json.loads(response.body)
    assert response.status_code == 400
    assert payload["error"] == "Informe se avisou o Comercial."


def test_api_mobile_delivery_return_requires_contact_name_when_answer_is_yes():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee, _, route, motivo_nome = _seed_mobile_delivery_return_context(session)

        response = asyncio.run(
            main.api_mobile_delivery_route_action(
                _make_request(employee.id),
                route.id,
                main.MobileDeliveryActionPayload(
                    action="devolucao",
                    return_reason=motivo_nome,
                    return_notified_commercial=True,
                    return_notified_logistics=False,
                ),
                session,
            )
        )

    payload = json.loads(response.body)
    assert response.status_code == 400
    assert payload["error"] == "Informe o nome da pessoa do Comercial avisada."


def test_api_mobile_delivery_return_requires_photo_for_closed_store_reason():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee, _, route, _ = _seed_mobile_delivery_return_context(session)
        closed_reason = "PONTO VENDA FECHADO / AUSENTE"

        response = asyncio.run(
            main.api_mobile_delivery_route_action(
                _make_request(employee.id),
                route.id,
                main.MobileDeliveryActionPayload(
                    action="devolucao",
                    return_reason=closed_reason,
                    return_notified_commercial=False,
                    return_notified_logistics=False,
                ),
                session,
            )
        )

    payload = json.loads(response.body)
    assert response.status_code == 400
    assert payload["error"] == "Para cliente fechado, anexe a foto do estabelecimento."


def test_api_mobile_delivery_return_saves_required_observations_and_syncs_devolucao():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee, _, route, motivo_nome = _seed_mobile_delivery_return_context(session)

        response = asyncio.run(
            main.api_mobile_delivery_route_action(
                _make_request(employee.id),
                route.id,
                main.MobileDeliveryActionPayload(
                    action="devolucao",
                    return_reason=motivo_nome,
                    return_notified_commercial=True,
                    return_notified_commercial_name="Maria Comercial",
                    return_notified_logistics=False,
                ),
                session,
            )
        )
        payload = json.loads(response.body)
        session.refresh(route)
        devolucao = session.exec(select(models.Devolucao).where(models.Devolucao.route_id == route.id)).first()

    assert response.status_code == 200
    assert payload["success"] is True
    assert route.delivery_status == "devolucao"
    assert route.delivery_notified_commercial is True
    assert route.delivery_notified_commercial_name == "Maria Comercial"
    assert route.delivery_notified_logistics is False
    assert route.delivery_notified_logistics_name is None
    assert devolucao is not None
    assert devolucao.observacao == "Avisou o Comercial: Sim (Maria Comercial) | Avisou a Logística: Não"


def test_api_mobile_delivery_reopen_clears_synced_devolucao_and_observations():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee, _, route, motivo_nome = _seed_mobile_delivery_return_context(session)

        asyncio.run(
            main.api_mobile_delivery_route_action(
                _make_request(employee.id),
                route.id,
                main.MobileDeliveryActionPayload(
                    action="devolucao",
                    return_reason=motivo_nome,
                    return_notified_commercial=False,
                    return_notified_logistics=True,
                    return_notified_logistics_name="Paulo Logística",
                ),
                session,
            )
        )

        response = asyncio.run(
            main.api_mobile_delivery_route_action(
                _make_request(employee.id),
                route.id,
                main.MobileDeliveryActionPayload(action="reabrir"),
                session,
            )
        )
        payload = json.loads(response.body)
        session.refresh(route)
        devolucao = session.exec(select(models.Devolucao).where(models.Devolucao.route_id == route.id)).first()

    assert response.status_code == 200
    assert payload["success"] is True
    assert route.delivery_status == "reaberta"
    assert route.delivery_notified_commercial is None
    assert route.delivery_notified_commercial_name is None
    assert route.delivery_notified_logistics is None
    assert route.delivery_notified_logistics_name is None
    assert devolucao is None
