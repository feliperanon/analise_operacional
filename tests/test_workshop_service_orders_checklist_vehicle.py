# -*- coding: utf-8 -*-

import asyncio
import logging
import logging.handlers
from pathlib import Path
from types import SimpleNamespace
import sys

from sqlmodel import Session, SQLModel, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Evita lock local do logs.txt ao importar a app em ambiente Windows.
logging.handlers.RotatingFileHandler = lambda *args, **kwargs: logging.NullHandler()

import main
import models


def _admin_request():
    return SimpleNamespace(
        session={"auth_user_id": 1, "auth_user_role": "admin", "auth_user_email": "admin@test.local"},
        url=SimpleNamespace(path="/workshop/service-orders"),
    )


def test_service_order_rejects_checklist_from_different_vehicle():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(registration_id="EMP1", name="Motorista", role="Motorista", status="active")
        vehicle_from_checklist = models.Vehicle(
            placa="PUF1357",
            vehicle_type="caminhao",
            marca="VW",
            modelo="Delivery",
        )
        other_vehicle = models.Vehicle(
            placa="ABC1234",
            vehicle_type="caminhao",
            marca="Ford",
            modelo="Cargo",
        )
        session.add(employee)
        session.add(vehicle_from_checklist)
        session.add(other_vehicle)
        session.commit()
        session.refresh(employee)
        session.refresh(other_vehicle)

        checklist = models.TranspalletChecklist(
            employee_id=employee.id,
            equipment_code="PUF1357",
            date="2026-04-24",
            shift="Manhã",
            nonconforming_keys=["freio"],
        )
        session.add(checklist)
        session.commit()
        session.refresh(checklist)

        response = asyncio.run(
            main.workshop_service_order_create(
                request=_admin_request(),
                vehicle_id=other_vehicle.id,
                checklist_id=checklist.id,
                actions_text="Verificar freio | Oficina | 25/04",
                session=session,
            )
        )

        orders = session.exec(select(models.WorkshopServiceOrder)).all()
        assert response.status_code == 303
        assert "checklist_id=" + str(checklist.id) in response.headers["location"]
        assert "mesmo+ve%C3%ADculo" in response.headers["location"]
        assert orders == []


def test_service_order_created_from_checklist_keeps_reported_problem():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(registration_id="EMP1", name="Motorista", role="Motorista", status="active")
        vehicle = models.Vehicle(
            placa="PUF1357",
            vehicle_type="caminhao",
            marca="VW",
            modelo="Delivery",
        )
        session.add(employee)
        session.add(vehicle)
        session.commit()
        session.refresh(employee)
        session.refresh(vehicle)

        checklist = models.TranspalletChecklist(
            employee_id=employee.id,
            equipment_code="PUF1357",
            date="2026-04-24",
            shift="Manha",
            nonconforming_keys=["freios", "parte_eletrica"],
            observations="Luz de freio falhando e ruido ao frear.",
        )
        session.add(checklist)
        session.commit()
        session.refresh(checklist)

        response = asyncio.run(
            main.workshop_service_order_create(
                request=_admin_request(),
                vehicle_id=vehicle.id,
                checklist_id=checklist.id,
                driver_employee_id=None,
                origin="checklist",
                order_type="corretiva",
                priority="medium",
                problem_description="",
                issues_text="",
                actions_text="",
                preventive_note=None,
                return_to=None,
                session=session,
            )
        )

        orders = session.exec(select(models.WorkshopServiceOrder)).all()
        assert response.status_code == 303
        assert len(orders) == 1
        assert "Problemas apresentados no checklist:" in orders[0].problem_description
        assert "- Freios" in orders[0].problem_description
        assert "- Parte Eletrica" in orders[0].problem_description
        assert "Luz de freio falhando" in orders[0].problem_description
        assert any(action["action"] == "Tratar: Freios" for action in orders[0].action_plan_json)
