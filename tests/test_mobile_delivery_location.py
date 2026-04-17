# -*- coding: utf-8 -*-
import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import models


def _make_request(user_id: int):
    return SimpleNamespace(session={"user_id": user_id})


def test_api_mobile_delivery_location_updates_session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    with Session(engine) as session:
        emp = models.Employee(
            registration_id="EMP-LOC-1",
            name="MOTORISTA LOC",
            role="Motorista",
            status="active",
        )
        session.add(emp)
        session.commit()
        session.refresh(emp)
        ds = models.DeliverySession(
            date=today,
            employee_id=emp.id,
            status="open",
            vehicle_plate="ABC1D23",
            km_departure=500.0,
            started_at=datetime.now(ZoneInfo("America/Sao_Paulo")),
        )
        session.add(ds)
        session.commit()
        session.refresh(ds)

        resp = asyncio.run(
            main.api_mobile_delivery_location(
                _make_request(emp.id),
                main.MobileDeliveryLocationPayload(
                    latitude=-19.9167,
                    longitude=-43.9345,
                    vehicle_plate="ABC-1D23",
                ),
                session,
            )
        )
        assert resp.status_code == 200
        assert json.loads(resp.body).get("success") is True

        session.refresh(ds)
        assert ds.driver_last_lat is not None and abs(ds.driver_last_lat + 19.9167) < 0.01
        assert ds.driver_last_lon is not None and abs(ds.driver_last_lon + 43.9345) < 0.01
        assert ds.driver_last_location_at is not None
