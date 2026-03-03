# -*- coding: utf-8 -*-
"""Testes unitários para o service de Devoluções."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from devolucoes_service import (
    parse_valor_pt_br,
    compute_dia,
    compute_semana,
    compute_acima_300,
    compute_cluster,
    parse_date_dd_mm_yyyy,
    normalize_code,
    normalize_name,
    resolve_vendedor,
)


def test_parse_valor_pt_br():
    assert parse_valor_pt_br("702,77") == 702.77
    assert parse_valor_pt_br("1.115,67") == 1115.67
    assert parse_valor_pt_br("10.149,20") == 10149.20
    assert parse_valor_pt_br("107,99") == 107.99
    assert parse_valor_pt_br(100.5) == 100.5
    assert parse_valor_pt_br(None) == 0.0
    assert parse_valor_pt_br("") == 0.0


def test_compute_dia():
    dt = datetime(2026, 2, 2)
    assert compute_dia(dt) == 2
    dt = datetime(2026, 12, 31)
    assert compute_dia(dt) == 31


def test_compute_semana():
    # 02/02/2026 cai na semana 6
    dt = datetime(2026, 2, 2)
    assert compute_semana(dt) == 6
    # 09/02/2026 na semana 7
    dt = datetime(2026, 2, 9)
    assert compute_semana(dt) == 7


def test_compute_acima_300():
    assert compute_acima_300(300.0) == "SIM"
    assert compute_acima_300(301.0) == "SIM"
    assert compute_acima_300(299.99) == "NAO"
    assert compute_acima_300(0.0) == "NAO"


def test_compute_cluster():
    assert compute_cluster(50) == "50-100"
    assert compute_cluster(49) == "0-50"
    assert compute_cluster(100) == "100-200"
    assert compute_cluster(702.77) == "700-800"
    assert compute_cluster(1200) == "Acima 1.200"
    assert compute_cluster(1500) == "Acima 1.200"


def test_parse_date_dd_mm_yyyy():
    assert parse_date_dd_mm_yyyy("02/02/2026") == datetime(2026, 2, 2)
    assert parse_date_dd_mm_yyyy("02-02-2026") == datetime(2026, 2, 2)
    assert parse_date_dd_mm_yyyy(None) is None
    assert parse_date_dd_mm_yyyy("") is None


def test_normalize_code():
    assert normalize_code(201) == "201"
    assert normalize_code("201") == "201"
    assert normalize_code(" 201 ") == "201"
    assert normalize_code(201.0) == "201"
    assert normalize_code("201.0") == "201"
    assert normalize_code("110.0") == "110"
    assert normalize_code("  108.0  ") == "108"
    assert normalize_code(None) is None
    assert normalize_code("") is None


def test_normalize_name():
    assert normalize_name("José Maria Cesar") == "jose maria cesar"
    assert normalize_name("  João  Silva  ") == "joao silva"
    assert normalize_name(None) is None
    assert normalize_name("") is None


def test_resolve_vendedor_por_seller_code():
    """201, '201', ' 201 ', 201.0 resolvem por seller_code."""
    emp = MagicMock()
    emp.id = 1
    emp.name = "Vendedor 201"
    emp.seller_code = "201"
    cad = {
        "vendedor_by_code": {"201": emp, "108": emp, "110": emp},
        "vendedor_by_name_exact": {},
    }
    v, err = resolve_vendedor(201, cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor("201", cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor(" 201 ", cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor(201.0, cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor("110.0", cad)
    assert v is emp
    assert err is None


def test_resolve_vendedor_por_nome():
    """José Maria Cesar resolve por nome (case-insensitive)."""
    emp = MagicMock()
    emp.id = 2
    emp.name = "José Maria Cesar"
    emp.seller_code = None
    cad = {
        "vendedor_by_code": {},
        "vendedor_by_name_exact": {"jose maria cesar": [emp]},
    }
    v, err = resolve_vendedor("José Maria Cesar", cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor("jose maria cesar", cad)
    assert v is emp
    assert err is None


def test_resolve_vendedor_ambiguo():
    """Nome ambíguo retorna erro de ambiguidade."""
    emp1 = MagicMock()
    emp1.id = 1
    emp2 = MagicMock()
    emp2.id = 2
    cad = {
        "vendedor_by_code": {},
        "vendedor_by_name_exact": {"joao silva": [emp1, emp2]},
    }
    v, err = resolve_vendedor("João Silva", cad)
    assert v is None
    assert "ambíguo" in err
    assert "João Silva" in err


def test_resolve_vendedor_numerico_nao_encontrado():
    """Valor numérico sem seller_code: erro direto, sem tentar nome."""
    cad = {
        "vendedor_by_code": {},
        "vendedor_by_name_exact": {},
    }
    v, err = resolve_vendedor(999, cad)
    assert v is None
    assert "seller_code" in err
