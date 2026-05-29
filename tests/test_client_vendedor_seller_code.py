# -*- coding: utf-8 -*-
"""Casamento de código de vendedor (201 vs 201.0) entre cliente e colaborador."""
import pytest
from sqlmodel import Session, SQLModel, create_engine

import models
from client_vendedor import (
    resolve_employee_id_by_seller_code,
    resolve_vendedor_id_for_select,
    vendedor_card_for_client,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_resolve_seller_code_matches_decimal_stored(session):
    emp = models.Employee(
        registration_id="9001",
        name="ADEILTON VAZ DOS SANTOS",
        role="VENDEDOR",
        seller_code="201.0",
        status="active",
    )
    session.add(emp)
    session.commit()
    session.refresh(emp)

    assert resolve_employee_id_by_seller_code(session, "201") == emp.id
    assert resolve_employee_id_by_seller_code(session, "201.0") == emp.id


def test_client_setor_resolves_vendedor_with_decimal_code(session):
    emp = models.Employee(
        registration_id="9002",
        name="VENDEDOR TESTE",
        role="VENDEDOR",
        seller_code="201.0",
        status="active",
    )
    client = models.Client(name="Cliente", setor="201")
    session.add(emp)
    session.add(client)
    session.commit()
    session.refresh(emp)
    session.refresh(client)

    assert resolve_vendedor_id_for_select(client, session) == emp.id
    card = vendedor_card_for_client(session, client)
    assert card and card["id"] == emp.id
