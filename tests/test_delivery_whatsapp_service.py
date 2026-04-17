# -*- coding: utf-8 -*-
from pathlib import Path
import sys

from fastapi.encoders import jsonable_encoder
from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
from services.delivery_whatsapp_service import (
    WHATSAPP_DEFAULT_MESSAGE,
    WHATSAPP_ITEM_STATUS_BLOQUEADO,
    WHATSAPP_ITEM_STATUS_FALHA,
    WHATSAPP_ITEM_STATUS_SEM_CONTATO,
    WHATSAPP_ITEM_STATUS_JA_ENVIADO,
    WHATSAPP_ROUTE_STATUS_ENVIADO,
    WHATSAPP_ROUTE_STATUS_ENVIADO_PARCIAL,
    WHATSAPP_ROUTE_STATUS_FALHA,
    WHATSAPP_ROUTE_STATUS_PENDENTE,
    mark_delivery_group_whatsapp_ready,
    prepare_delivery_whatsapp_snapshot,
    remark_delivery_whatsapp_clients,
    send_delivery_whatsapp_notifications,
)
from services.whatsapp_provider import MockWhatsAppProvider


def _make_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_group(session: Session):
    driver = models.Employee(
        registration_id="D001",
        name="MOTORISTA TESTE",
        role="MOTORISTA",
        status="active",
        work_shift="Manhã",
    )
    session.add(driver)
    session.commit()
    session.refresh(driver)

    client_ok = models.Client(name="CLIENTE OK", fone="31987654321")
    client_fail = models.Client(name="CLIENTE FALHA", fone="31999990000")
    client_no_phone = models.Client(name="CLIENTE SEM TELEFONE")
    client_blocked = models.Client(name="CLIENTE BLOQUEADO", fone="31988887777", lgpd_nao_contatar=True)
    session.add(client_ok)
    session.add(client_fail)
    session.add(client_no_phone)
    session.add(client_blocked)
    session.commit()
    for client in (client_ok, client_fail, client_no_phone, client_blocked):
        session.refresh(client)

    route_date = "2026-04-14"
    shift = "Manhã"
    plate = "ABC1D23"
    routes = [
        models.Route(
            date=route_date,
            shift=shift,
            employee_id=driver.id,
            client_id=client_ok.id,
            start_time="08:00",
            tonnage=100.0,
            type="delivery",
            delivery_vehicle_plate=plate,
            delivery_status="pendente",
            delivery_order_number="1001",
            delivery_route_code="R-01",
        ),
        models.Route(
            date=route_date,
            shift=shift,
            employee_id=driver.id,
            client_id=client_fail.id,
            start_time="08:05",
            tonnage=80.0,
            type="delivery",
            delivery_vehicle_plate=plate,
            delivery_status="pendente",
            delivery_order_number="1002",
            delivery_route_code="R-01",
        ),
        models.Route(
            date=route_date,
            shift=shift,
            employee_id=driver.id,
            client_id=client_no_phone.id,
            start_time="08:10",
            tonnage=60.0,
            type="delivery",
            delivery_vehicle_plate=plate,
            delivery_status="pendente",
            delivery_order_number="1003",
            delivery_route_code="R-01",
        ),
        models.Route(
            date=route_date,
            shift=shift,
            employee_id=driver.id,
            client_id=client_blocked.id,
            start_time="08:15",
            tonnage=40.0,
            type="delivery",
            delivery_vehicle_plate=plate,
            delivery_status="pendente",
            delivery_order_number="1004",
            delivery_route_code="R-01",
        ),
    ]
    for route in routes:
        session.add(route)
    session.commit()

    delivery_session = models.DeliverySession(
        date=route_date,
        employee_id=driver.id,
        status="open",
        vehicle_plate=plate,
        km_departure=12345.0,
    )
    session.add(delivery_session)
    session.commit()

    return {
        "driver": driver,
        "route_date": route_date,
        "shift": shift,
        "plate": plate,
        "client_ok": client_ok,
        "client_fail": client_fail,
        "client_no_phone": client_no_phone,
        "client_blocked": client_blocked,
    }


def test_prepare_snapshot_classifies_clients_and_route_pending():
    with _make_session() as session:
        seed = _seed_group(session)
        mark_delivery_group_whatsapp_ready(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )

        snapshot = prepare_delivery_whatsapp_snapshot(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )

        assert snapshot["status"] == WHATSAPP_ROUTE_STATUS_PENDENTE
        assert snapshot["summary"]["sendable"] == 2
        assert snapshot["summary"]["no_contact"] == 1
        assert snapshot["summary"]["blocked"] == 1
        assert snapshot["preview_message"] == WHATSAPP_DEFAULT_MESSAGE

        client_map = {row["client_name"]: row for row in snapshot["clients"]}
        assert client_map["CLIENTE SEM TELEFONE"]["status"] == WHATSAPP_ITEM_STATUS_SEM_CONTATO
        assert client_map["CLIENTE BLOQUEADO"]["status"] == WHATSAPP_ITEM_STATUS_BLOQUEADO


def test_prepare_snapshot_accepts_normalized_shift_and_json_encoding():
    with _make_session() as session:
        seed = _seed_group(session)
        mark_delivery_group_whatsapp_ready(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )

        snapshot = prepare_delivery_whatsapp_snapshot(
            session,
            route_date=seed["route_date"],
            shift="Manha",
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )

        encoded = jsonable_encoder({"success": True, "snapshot": snapshot})
        assert encoded["success"] is True
        assert encoded["snapshot"]["route_date"] == seed["route_date"]
        assert encoded["snapshot"]["ready_at"] is not None


def test_send_notifications_creates_batch_and_item_audit():
    with _make_session() as session:
        seed = _seed_group(session)
        mark_delivery_group_whatsapp_ready(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )

        result = send_delivery_whatsapp_notifications(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            operator_label="Operador Teste",
            operator_user_id=7,
        )

        assert result["batch_status"] == WHATSAPP_ROUTE_STATUS_ENVIADO_PARCIAL
        assert result["summary"]["sent"] == 1
        assert result["summary"]["failed"] == 1

        batch = session.exec(select(models.DeliveryWhatsAppBatch)).first()
        assert batch is not None
        assert batch.sent_count == 1
        assert batch.failed_count == 1
        assert batch.operator_label == "Operador Teste"

        items = list(session.exec(select(models.DeliveryWhatsAppItem).order_by(models.DeliveryWhatsAppItem.client_name)).all())
        assert len(items) == 2
        assert {item.status for item in items} == {"enviado", "falha"}
        assert all(item.request_payload_json for item in items)
        assert all(item.response_json for item in items)


def test_retry_only_failed_items_and_marks_client_as_sent():
    with _make_session() as session:
        seed = _seed_group(session)

        # Remove os clientes que nao interessam neste cenÃ¡rio.
        session.exec(select(models.Route))
        extra_routes = session.exec(
            select(models.Route).where(models.Route.client_id.in_([seed["client_no_phone"].id, seed["client_blocked"].id]))
        ).all()
        for route in extra_routes:
            session.delete(route)
        session.commit()

        mark_delivery_group_whatsapp_ready(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )

        first_result = send_delivery_whatsapp_notifications(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            operator_label="Operador Teste",
            operator_user_id=7,
            provider=MockWhatsAppProvider(fail_suffixes=["0000"]),
        )
        assert first_result["batch_status"] == WHATSAPP_ROUTE_STATUS_ENVIADO_PARCIAL

        retry_result = send_delivery_whatsapp_notifications(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            operator_label="Operador Teste",
            operator_user_id=7,
            retry_failed=True,
            provider=MockWhatsAppProvider(fail_suffixes=[]),
        )

        assert retry_result["batch_status"] == WHATSAPP_ROUTE_STATUS_ENVIADO
        assert retry_result["summary"]["sent"] == 2
        assert retry_result["summary"]["failed"] == 0

        fail_client_items = list(
            session.exec(
                select(models.DeliveryWhatsAppItem)
                .where(models.DeliveryWhatsAppItem.client_id == seed["client_fail"].id)
                .order_by(models.DeliveryWhatsAppItem.attempt_number)
            ).all()
        )
        assert len(fail_client_items) == 2
        assert fail_client_items[0].status == WHATSAPP_ITEM_STATUS_FALHA
        assert fail_client_items[1].status == "enviado"
        assert fail_client_items[1].attempt_number == 2

        snapshot = prepare_delivery_whatsapp_snapshot(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )
        client_map = {row["client_name"]: row for row in snapshot["clients"]}
        assert client_map["CLIENTE FALHA"]["status"] == WHATSAPP_ITEM_STATUS_JA_ENVIADO
        assert snapshot["status"] == WHATSAPP_ROUTE_STATUS_ENVIADO


def test_remark_clients_clears_sent_history_and_makes_sendable_again():
    with _make_session() as session:
        seed = _seed_group(session)
        mark_delivery_group_whatsapp_ready(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )

        send_delivery_whatsapp_notifications(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            operator_label="Operador Teste",
            operator_user_id=7,
            provider=MockWhatsAppProvider(fail_suffixes=["0000"]),
        )

        snapshot_before = prepare_delivery_whatsapp_snapshot(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )
        client_before = next(row for row in snapshot_before["clients"] if row["client_id"] == seed["client_ok"].id)
        assert client_before["status"] in (WHATSAPP_ITEM_STATUS_JA_ENVIADO, "enviado")
        assert client_before["sendable"] is False

        snapshot_after = remark_delivery_whatsapp_clients(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            client_ids=[seed["client_ok"].id],
        )
        client_after = next(row for row in snapshot_after["clients"] if row["client_id"] == seed["client_ok"].id)
        assert client_after["status"] == "elegivel"
        assert client_after["sendable"] is True


def test_skip_session_ready_sends_only_selected():
    """Sem sessão mobile: envio manual só para clientes marcados (operador)."""
    with _make_session() as session:
        seed = _seed_group(session)
        result = send_delivery_whatsapp_notifications(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            operator_label="Operador",
            operator_user_id=1,
            only_client_ids=[seed["client_ok"].id],
            skip_session_ready=True,
            provider=MockWhatsAppProvider(fail_suffixes=[]),
        )
        assert result["batch_status"] == WHATSAPP_ROUTE_STATUS_ENVIADO
        items = list(session.exec(select(models.DeliveryWhatsAppItem)).all())
        assert len(items) == 1
        assert items[0].client_id == seed["client_ok"].id


def test_allow_repeat_resends_to_already_sent():
    with _make_session() as session:
        seed = _seed_group(session)
        mark_delivery_group_whatsapp_ready(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
        )
        send_delivery_whatsapp_notifications(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            operator_label="Op",
            operator_user_id=1,
            only_client_ids=[seed["client_ok"].id],
            provider=MockWhatsAppProvider(fail_suffixes=[]),
        )
        second = send_delivery_whatsapp_notifications(
            session,
            route_date=seed["route_date"],
            shift=seed["shift"],
            employee_id=seed["driver"].id,
            vehicle_plate=seed["plate"],
            operator_label="Op",
            operator_user_id=1,
            only_client_ids=[seed["client_ok"].id],
            allow_repeat=True,
            provider=MockWhatsAppProvider(fail_suffixes=[]),
        )
        assert second["batch_status"] == WHATSAPP_ROUTE_STATUS_ENVIADO
        items = list(
            session.exec(
                select(models.DeliveryWhatsAppItem).where(
                    models.DeliveryWhatsAppItem.client_id == seed["client_ok"].id
                )
            ).all()
        )
        assert len(items) == 2
