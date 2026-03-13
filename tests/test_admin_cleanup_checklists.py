# -*- coding: utf-8 -*-
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import models


def _make_request():
    return SimpleNamespace(session={})


def test_admin_cleanup_all_checklists_uses_actor_label_and_deletes_records():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(
            registration_id="EMP-CHK-1",
            name="Operador Teste",
            role="Operador",
            status="active",
        )
        equipment = models.TranspalletEquipment(
            code="TR-01",
            status="blocked",
            blocked_reason="Checklist crítico",
        )
        session.add(employee)
        session.add(equipment)
        session.commit()
        session.refresh(employee)
        session.refresh(equipment)

        tx = models.GameXPTransaction(
            employee_id=employee.id,
            amount=15,
            source_type="checklist_auto",
            status="confirmed",
            reason="Checklist aprovado",
        )
        session.add(tx)
        session.commit()
        session.refresh(tx)

        employee.total_xp = 15
        checklist = models.TranspalletChecklist(
            employee_id=employee.id,
            equipment_code=equipment.code,
            date="2026-03-13",
            shift="Manhã",
            status="approved",
            xp_transaction_id=tx.id,
        )
        session.add(employee)
        session.add(checklist)
        session.commit()
        session.refresh(employee)
        session.refresh(checklist)

        equipment.last_checklist_id = checklist.id
        session.add(equipment)
        session.commit()

        response = asyncio.run(
            main.admin_cleanup_all_checklists(
                _make_request(),
                "apagar todos os checklists",
                session,
                user={"type": "user", "email": "lider@test.com", "role": "leader"},
            )
        )

        remaining_checklists = session.exec(select(models.TranspalletChecklist)).all()
        events = session.exec(select(models.Event)).all()
        session.refresh(employee)
        session.refresh(equipment)
        session.refresh(tx)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/routine/checklists/settings?message=Todos+os+checklists+foram+apagados+com+sucesso.&level=success"
    assert remaining_checklists == []
    assert len(events) == 1
    assert "lider@test.com" in events[0].text
    assert equipment.status == "available"
    assert equipment.last_checklist_id is None
    assert employee.total_xp == 0
    assert tx.status == "rejected"
    assert "cleanup global" in (tx.reason or "")
