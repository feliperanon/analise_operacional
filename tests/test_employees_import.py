# -*- coding: utf-8 -*-
"""Testes de importação de colaboradores (matrícula e seller_code)."""
import io

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import models
from employees_import import (
    _format_registration_cell,
    _registration_already_seen,
    _resolve_admission_and_birthday,
    import_employees_from_excel,
    registration_lookup_variants,
)


def _noop_phone(_):
    return None, None


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_format_registration_cell_numeric():
    assert _format_registration_cell(210) == "210.0"
    assert _format_registration_cell(210.0) == "210.0"
    assert _format_registration_cell("210") == "210.0"
    assert _format_registration_cell("ESP-999") == "ESP-999"


def test_registration_lookup_variants():
    assert "210.0" in registration_lookup_variants("210")
    assert "210" in registration_lookup_variants("210.0")


def test_registration_already_seen_dedupes_variants():
    seen = set()
    assert _registration_already_seen(seen, "210") is False
    assert _registration_already_seen(seen, "210.0") is True
    assert _registration_already_seen(seen, 210) is True


def test_import_skips_existing_by_registration_variant(session):
    session.add(
        models.Employee(
            name="JOAO SILVA",
            registration_id="210",
            role="MOTORISTA",
            work_shift="Manhã",
            cost_center="Souza Pinto",
            status="active",
        )
    )
    session.commit()

    df = pd.DataFrame(
        {
            "Nome Completo": ["JOAO SILVA"],
            "Matrícula": [210.0],
            "Código do Vendedor": [210.0],
            "Cargo": ["MOTORISTA"],
            "Empresa": ["Souza Pinto"],
            "Turno Operacional": ["Manhã"],
        }
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Colaboradores", index=False)
    buf.seek(0)

    count = import_employees_from_excel(session, buf.read(), _noop_phone)
    assert count == 0
    assert len(session.exec(select(models.Employee)).all()) == 1


def test_resolve_admission_and_birthday_swaps_inverted():
    adm, bday = _resolve_admission_and_birthday("19/03/1998", "07/02/2024")
    assert adm.year == 2024 and adm.month == 2 and adm.day == 7
    assert bday.year == 1998 and bday.month == 3 and bday.day == 19


def test_resolve_admission_and_birthday_keeps_valid_order():
    adm, bday = _resolve_admission_and_birthday("07/02/2024", "19/03/1998")
    assert adm.year == 2024
    assert bday.year == 1998


def test_import_swapped_legacy_date_columns(session):
    df = pd.DataFrame(
        {
            "Nome Funcionário": ["JOSE TESTE"],
            "Matrícula": ["99001"],
            "Nome Cargo": ["MOTORISTA"],
            "Adminissão": ["19/03/1998"],
            "Data de Nascimento": ["07/02/2024"],
        }
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Souza Pinto", index=False)
    buf.seek(0)

    count = import_employees_from_excel(session, buf.read(), _noop_phone)
    assert count == 1
    emp = session.exec(select(models.Employee)).first()
    assert emp.admission_date.year == 2024
    assert emp.birthday.year == 1998


def test_import_normalizes_seller_code(session):
    df = pd.DataFrame(
        {
            "Nome Completo": ["MARIA SOUZA"],
            "Matrícula": ["5001"],
            "Código do Vendedor": [210.0],
            "Cargo": ["VENDEDOR"],
            "Empresa": ["Souza Pinto"],
            "Turno Operacional": ["Manhã"],
        }
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Colaboradores", index=False)
    buf.seek(0)

    count = import_employees_from_excel(session, buf.read(), _noop_phone)
    assert count == 1
    emp = session.exec(select(models.Employee)).first()
    assert emp.seller_code == "210"
    assert emp.registration_id == "5001.0"


def test_import_fills_seller_code_on_existing_employee(session):
    session.add(
        models.Employee(
            name="JOAO SILVA",
            registration_id="210.0",
            role="VENDEDOR",
            work_shift="Manhã",
            cost_center="Souza Pinto",
            status="active",
        )
    )
    session.commit()

    df = pd.DataFrame(
        {
            "Nome Completo": ["JOAO SILVA"],
            "Matrícula": [210],
            "Código do Vendedor": [201.0],
            "Cargo": ["VENDEDOR"],
            "Empresa": ["Souza Pinto"],
            "Turno Operacional": ["Manhã"],
        }
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Colaboradores", index=False)
    buf.seek(0)

    count = import_employees_from_excel(session, buf.read(), _noop_phone)
    assert count == 0
    emp = session.exec(select(models.Employee)).first()
    assert emp.seller_code == "201"
