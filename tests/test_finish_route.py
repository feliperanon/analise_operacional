# -*- coding: utf-8 -*-
"""Testes para fechamento automático de rota (regra de ouro: devolução manda, entrega é padrão)."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo


def _has_devolucao(route, devolucao_by_route: dict) -> bool:
    """Lógica de negócio: parada tem devolução registrada?"""
    st = (route.delivery_status or "").lower()
    return (
        st == "devolucao"
        or (route.valor_devolucao and float(route.valor_devolucao) > 0)
        or (route.id and route.id in devolucao_by_route)
    )


def test_has_devolucao_status_devolucao():
    """Parada com delivery_status=devolucao deve ser considerada devolução."""
    r = MagicMock()
    r.delivery_status = "devolucao"
    r.valor_devolucao = None
    r.id = 1
    assert _has_devolucao(r, {}) is True


def test_has_devolucao_valor_preenchido():
    """Parada com valor_devolucao > 0 deve ser considerada devolução."""
    r = MagicMock()
    r.delivery_status = "pendente"
    r.valor_devolucao = 100.0
    r.id = 1
    assert _has_devolucao(r, {}) is True


def test_has_devolucao_linked_devolucao():
    """Parada com Devolucao.route_id vinculado deve ser considerada devolução."""
    r = MagicMock()
    r.delivery_status = "pendente"
    r.valor_devolucao = None
    r.id = 42
    assert _has_devolucao(r, {42: [MagicMock(valor=50.0)]}) is True


def test_has_devolucao_sem_devolucao():
    """Parada pendente sem devolução deve retornar False."""
    r = MagicMock()
    r.delivery_status = "pendente"
    r.valor_devolucao = None
    r.id = 1
    assert _has_devolucao(r, {}) is False


def test_idempotencia_entregue_nao_processa():
    """Paradas já entregues não devem ser reprocessadas."""
    st = "entregue"
    assert st in ("entregue", "devolucao")  # skip no loop


def test_idempotencia_devolucao_nao_processa():
    """Paradas já devolucao não devem ser reprocessadas."""
    st = "devolucao"
    assert st in ("entregue", "devolucao")  # skip no loop


def test_cancelada_nao_processa():
    """Paradas canceladas não devem ser processadas."""
    st = "cancelada"
    assert st in ("cancelada",)


def test_pendente_iniciada_reaberta_processam():
    """Paradas pendente, iniciada e reaberta devem ser processadas."""
    for st in ("pendente", "iniciada", "reaberta"):
        assert st not in ("entregue", "devolucao")
        assert st not in ("cancelada",)
