# -*- coding: utf-8 -*-
"""Testes para preenchimento em lote de seller_code."""
import pytest
from unittest.mock import MagicMock

from employees_seller_code import (
    normalize_seller_code,
    batch_update_from_json,
    BatchReport,
)


def test_normalize_seller_code():
    assert normalize_seller_code(201) == "201"
    assert normalize_seller_code("201") == "201"
    assert normalize_seller_code(" 201 ") == "201"
    assert normalize_seller_code(201.0) == "201"
    assert normalize_seller_code("201.0") == "201"
    assert normalize_seller_code("110.0") == "110"
    assert normalize_seller_code(None) is None
    assert normalize_seller_code("") is None


def test_batch_update_from_json_atualiza_corretamente():
    """Preenchimento em lote atualiza seller_code corretamente."""
    emp1 = MagicMock()
    emp1.id = 1
    emp1.registration_id = "100"
    emp1.name = "JOSE MARIA"
    emp1.seller_code = None

    session = MagicMock()
    session.exec.return_value.all.return_value = [emp1]

    report = batch_update_from_json(
        session,
        [{"registration_id": "100", "seller_code": "110"}],
    )
    assert len(report.updated) == 1
    assert report.updated[0]["seller_code"] == "110"
    assert emp1.seller_code == "110"
    assert len(report.not_found) == 0


def test_batch_update_from_json_por_nome():
    """Batch update encontra por name quando registration_id não fornecido."""
    emp = MagicMock()
    emp.id = 2
    emp.registration_id = "200"
    emp.name = "JOSE MARIA CESAR"
    emp.seller_code = None

    session = MagicMock()
    session.exec.return_value.all.return_value = [emp]

    report = batch_update_from_json(
        session,
        [{"name": "JOSE MARIA CESAR", "seller_code": "311"}],
    )
    assert len(report.updated) == 1
    assert emp.seller_code == "311"


def test_batch_update_from_json_nao_encontrado():
    """Not found quando registration_id/name não existe."""
    session = MagicMock()
    session.exec.return_value.all.return_value = []

    report = batch_update_from_json(
        session,
        [{"registration_id": "999", "seller_code": "110"}],
    )
    assert len(report.not_found) == 1
    assert len(report.updated) == 0


def test_batch_update_normaliza_201_ponto_0():
    """seller_code 201.0 é normalizado para 201."""
    emp = MagicMock()
    emp.id = 1
    emp.registration_id = "100"
    emp.name = "X"
    emp.seller_code = None

    session = MagicMock()
    session.exec.return_value.all.return_value = [emp]

    report = batch_update_from_json(
        session,
        [{"registration_id": "100", "seller_code": "201.0"}],
    )
    assert emp.seller_code == "201"
    assert len(report.updated) == 1
