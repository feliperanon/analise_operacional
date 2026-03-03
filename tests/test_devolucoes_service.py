# -*- coding: utf-8 -*-
"""Testes unitários para o service de Devoluções."""
import pytest
from datetime import datetime

from devolucoes_service import (
    parse_valor_pt_br,
    compute_dia,
    compute_semana,
    compute_acima_300,
    compute_cluster,
    parse_date_dd_mm_yyyy,
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
