import asyncio
import os
from pathlib import Path
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace

from sqlmodel import SQLModel, Session, create_engine, select
from starlette.datastructures import UploadFile

import main
import models


def _admin_request(path: str = "/workshop/service-orders/1"):
    return SimpleNamespace(
        session={"auth_user_id": 1, "auth_user_role": "admin", "auth_user_email": "admin@test.local"},
        url=SimpleNamespace(path=path),
    )


def _seed_vehicle(session: Session) -> models.Vehicle:
    vehicle = models.Vehicle(placa="XYZ1234", vehicle_type="caminhao", marca="VW", modelo="Constellation")
    session.add(vehicle)
    session.commit()
    session.refresh(vehicle)
    return vehicle


def test_close_requires_resolution_notes():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vehicle = _seed_vehicle(session)
        order = models.WorkshopServiceOrder(vehicle_id=vehicle.id, status="done")
        session.add(order)
        session.commit()
        session.refresh(order)

        response = asyncio.run(
            main.workshop_service_order_close(
                request=_admin_request(f"/workshop/service-orders/{order.id}"),
                order_id=order.id,
                resolution_notes="",
                return_to=f"/workshop/service-orders/{order.id}",
                session=session,
            )
        )
        session.refresh(order)
        assert response.status_code == 303
        assert "informe+nota+de+conclus%C3%A3o" in response.headers["location"]
        assert order.status == "done"


def test_all_actions_done_marks_done_but_not_closed():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vehicle = _seed_vehicle(session)
        order = models.WorkshopServiceOrder(
            vehicle_id=vehicle.id,
            status="in_progress",
            action_plan_json=[{"action": "A", "response_status": "pending"}],
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        response = asyncio.run(
            main.workshop_service_order_respond_action(
                request=_admin_request(f"/workshop/service-orders/{order.id}"),
                order_id=order.id,
                action_index=0,
                response_status="done",
                response_note="Finalizado",
                return_to=f"/workshop/service-orders/{order.id}",
                session=session,
            )
        )
        session.refresh(order)
        assert response.status_code == 303
        assert order.status == "done"
        assert order.closed_at is None


def test_generate_pdf_updates_service_order():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vehicle = _seed_vehicle(session)
        order = models.WorkshopServiceOrder(
            vehicle_id=vehicle.id,
            status="open",
            action_plan_json=[{"action": "Trocar pastilha", "owner": "Oficina", "response_status": "pending"}],
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        response = asyncio.run(
            main.workshop_service_order_generate_pdf(
                request=_admin_request(f"/workshop/service-orders/{order.id}"),
                order_id=order.id,
                return_to=f"/workshop/service-orders/{order.id}",
                session=session,
            )
        )
        session.refresh(order)
        assert response.status_code == 303
        assert order.latest_pdf_path
        pdf_path = Path(main.BASE_DIR / order.latest_pdf_path.strip("/").replace("/", os.sep))
        assert pdf_path.exists()

        events = session.exec(
            select(models.WorkshopServiceOrderEvent).where(models.WorkshopServiceOrderEvent.service_order_id == order.id)
        ).all()
        assert any(e.event_type == "pdf_generated" for e in events)


def test_close_calculates_total_cost():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vehicle = _seed_vehicle(session)
        order = models.WorkshopServiceOrder(vehicle_id=vehicle.id, status="done")
        session.add(order)
        session.commit()
        session.refresh(order)

        response = asyncio.run(
            main.workshop_service_order_close(
                request=_admin_request(f"/workshop/service-orders/{order.id}"),
                order_id=order.id,
                resolution_notes="Serviço validado.",
                parts_cost="100",
                labor_cost="50",
                third_party_cost="25",
                return_to=f"/workshop/service-orders/{order.id}",
                session=session,
            )
        )
        session.refresh(order)
        assert response.status_code == 303
        assert order.status == "closed"
        assert order.total_cost == 175.0


def test_upload_attachment_links_to_service_order():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vehicle = _seed_vehicle(session)
        order = models.WorkshopServiceOrder(vehicle_id=vehicle.id, status="open")
        session.add(order)
        session.commit()
        session.refresh(order)

        stream = SpooledTemporaryFile()
        stream.write(b"fake-image-content")
        stream.seek(0)
        upload = UploadFile(filename="evidencia.jpg", file=stream)

        response = asyncio.run(
            main.workshop_service_order_upload_attachment(
                request=_admin_request(f"/workshop/service-orders/{order.id}"),
                order_id=order.id,
                attachment_type="problem",
                file=upload,
                return_to=f"/workshop/service-orders/{order.id}",
                session=session,
            )
        )
        assert response.status_code == 303
        attachments = session.exec(
            select(models.WorkshopServiceOrderAttachment).where(models.WorkshopServiceOrderAttachment.service_order_id == order.id)
        ).all()
        assert len(attachments) == 1
        assert attachments[0].attachment_type == "problem"
        file_path = Path(main.BASE_DIR / attachments[0].file_path.strip("/").replace("/", os.sep))
        assert file_path.exists()


def test_supplier_update_changes_status_and_values():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vehicle = _seed_vehicle(session)
        order = models.WorkshopServiceOrder(vehicle_id=vehicle.id, status="open")
        session.add(order)
        session.commit()
        session.refresh(order)

        response = asyncio.run(
            main.workshop_service_order_supplier_update(
                request=_admin_request(f"/workshop/service-orders/{order.id}"),
                order_id=order.id,
                external_supplier_required="1",
                supplier_name="Oficina XPTO",
                supplier_contact="31999999999",
                supplier_service_type="Freio",
                supplier_status="quote_received",
                supplier_expected_return_at="2026-05-10",
                quoted_amount="1234,56",
                approved_amount="1200,00",
                final_amount="1190,00",
                return_to=f"/workshop/service-orders/{order.id}",
                session=session,
            )
        )
        session.refresh(order)
        assert response.status_code == 303
        assert order.external_supplier_required is True
        assert order.supplier_status == "quote_received"
        assert order.supplier_name == "Oficina XPTO"
        assert order.quoted_amount == 1234.56

