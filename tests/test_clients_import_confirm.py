# -*- coding: utf-8 -*-
import asyncio
from types import SimpleNamespace

from sqlmodel import SQLModel, Session, create_engine, select

import main
import models


class _FakeRequest:
    def __init__(self, form_data):
        self.session = {"auth_user_id": 1, "auth_user_role": "admin"}
        self.url = SimpleNamespace(path="/clients/import/confirm/1")
        self._form_data = form_data

    async def form(self):
        return self._form_data


def test_clients_import_confirm_keeps_reimport_rows_as_merge_when_stale_form_posts_create():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        client = models.Client(name="Cliente Antigo", nb="123", setor="10")
        batch = models.ClientImportBatch(filename="clientes.xlsx", status="pending")
        session.add(client)
        session.add(batch)
        session.commit()
        session.refresh(client)
        session.refresh(batch)

        row = models.ClientImportStaging(
            batch_id=batch.id,
            row_index=0,
            name="Cliente Atualizado",
            nb="123",
            setor="20",
            conflict_type=None,
            conflict_client_id=client.id,
            action="merge",
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        request = _FakeRequest({f"action_{row.id}": "create"})
        response = asyncio.run(main.clients_import_confirm(request, batch.id, session))

        updated = session.get(models.Client, client.id)
        clients = session.exec(select(models.Client)).all()
        session.refresh(batch)

    assert response.status_code == 303
    assert len(clients) == 1
    assert updated.name == "Cliente Atualizado"
    assert batch.status == "completed"
    assert batch.log_updated == 1
    assert batch.log_created == 0


def test_client_import_row_has_changes_detects_seller_code_change():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        old_seller = models.Employee(
            registration_id="101",
            name="Vendedor 101",
            role="VENDEDOR",
            seller_code="101",
            status="active",
        )
        new_seller = models.Employee(
            registration_id="305",
            name="Vendedor 305",
            role="VENDEDOR",
            seller_code="305",
            status="active",
        )
        client = models.Client(name="Cliente", nb="19267", setor="101", me="100")
        session.add(old_seller)
        session.add(new_seller)
        session.add(client)
        session.commit()
        session.refresh(old_seller)
        session.refresh(client)
        client.vendedor_id = old_seller.id
        session.add(client)
        session.commit()
        session.refresh(client)

        row = models.ClientImportStaging(
            batch_id=1,
            row_index=0,
            name="Cliente",
            nb="19267",
            setor="305",
            me="100",
        )

        assert main._client_import_row_has_changes(session, client, row) is True


def test_client_import_row_has_changes_detects_non_seller_data_change():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        client = models.Client(name="Cliente", nb="19267", setor="305", me="100", visita="QUA")
        session.add(client)
        session.commit()
        session.refresh(client)

        row = models.ClientImportStaging(
            batch_id=1,
            row_index=0,
            name="Cliente",
            nb="19267",
            setor="305",
            me="100",
            visita="QUI",
        )

        assert main._client_import_row_has_changes(session, client, row) is True
