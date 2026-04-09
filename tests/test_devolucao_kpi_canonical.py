"""Testes do critério canônico de % devolução (rotas)."""

from types import SimpleNamespace

from devolucao_kpi_canonical import (
    counts_devolucao_rotas_concluidas,
    normalized_delivery_status,
    pct_devolucao_sobre_rotas_concluidas,
)


def test_encerramento_tardio_nao_conta_como_devolucao():
    r_ok = SimpleNamespace(delivery_status="Entregue", delivery_return_reason="")
    r_dev = SimpleNamespace(delivery_status="Devolucao", delivery_return_reason="")
    r_auto = SimpleNamespace(
        delivery_status="Devolucao",
        delivery_return_reason="Encerramento tardio automatico",
    )
    routes = [r_ok, r_dev, r_auto]
    n_ret, n_done = counts_devolucao_rotas_concluidas(routes)
    assert n_done == 3
    assert n_ret == 1
    assert pct_devolucao_sobre_rotas_concluidas(routes) == round(100 / 3, 1)


def test_normalized_delivery_status():
    r = SimpleNamespace(delivery_status="  DEVOLUCAO ", delivery_return_reason=" encerramento tardio automatico ")
    assert normalized_delivery_status(r) == "entregue"
