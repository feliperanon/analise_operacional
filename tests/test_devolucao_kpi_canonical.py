"""Testes do critério canônico de % devolução (rotas)."""

from datetime import date, timedelta
from types import SimpleNamespace

from devolucao_kpi_canonical import (
    build_mes_fim_projecao_pct_financeiro,
    build_mes_fim_projecao_pct_rotas,
    counts_devolucao_rotas_concluidas,
    group_routes_by_operational_day,
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


def test_encerramento_tardio_com_acentos_conta_como_entregue():
    r = SimpleNamespace(
        delivery_status="devolucao",
        delivery_return_reason="Encerramento tardio automático",
    )
    assert normalized_delivery_status(r) == "entregue"


def test_encerramento_tardio_texto_composto_conta_como_entregue():
    r = SimpleNamespace(
        delivery_status="devolucao",
        delivery_return_reason="ENCERRAMENTO TARDIO AUTOMATICO - SISTEMA",
    )
    assert normalized_delivery_status(r) == "entregue"


def _r(d, st):
    return SimpleNamespace(date=d, delivery_status=st, delivery_return_reason="")


def test_group_routes_by_operational_day():
    d0 = date(2025, 4, 1)
    routes = [_r(d0, "Entregue"), _r(d0, "Devolucao")]
    g = group_routes_by_operational_day(routes)
    assert len(g) == 1
    k = d0.strftime("%Y-%m-%d")
    assert len(g[k]) == 2


def test_projecao_mes_fim_meses_distintos_retorna_none():
    r = _r(date(2025, 5, 10), "Entregue")
    out = build_mes_fim_projecao_pct_rotas(
        date(2025, 4, 1),
        date(2025, 5, 10),
        [r],
        [],
    )
    assert out is None


def test_projecao_mes_fim_com_baseline_encontravel():
    """Mês parcial: baseline com 14+ dias; projeção finita."""
    date_i = date(2025, 5, 1)
    date_f = date(2025, 5, 10)
    mtd = [_r(date(2025, 5, 3), "Entregue"), _r(date(2025, 5, 3), "Devolucao")]
    baseline = []
    d0 = date(2025, 1, 1)
    for i in range(20):
        dd = d0 + timedelta(days=i)
        baseline.append(_r(dd, "Entregue"))
        baseline.append(_r(dd, "Entregue"))
        baseline.append(_r(dd, "Devolucao"))
    out = build_mes_fim_projecao_pct_rotas(date_i, date_f, mtd, baseline, min_baseline_days=14)
    assert out is not None
    assert out["ativa"] is True
    assert 0 <= out["pct_projetado"] <= 100
    assert out["dias_restantes_no_mes"] == 21
    assert out["vs_meta"] in ("acima", "dentro")


def test_projecao_financeira_mes_distintos_retorna_none():
    out = build_mes_fim_projecao_pct_financeiro(
        date(2025, 4, 1),
        date(2025, 5, 10),
        {"2025-05-03": 1000.0},
        {"2025-05-03": 50.0},
        {"2025-01-01": 500.0},
        {"2025-01-01": 10.0},
    )
    assert out is None


def test_projecao_financeira_com_baseline():
    date_i = date(2025, 5, 1)
    date_f = date(2025, 5, 10)
    base_mtd = {"2025-05-03": 1000.0}
    dev_mtd = {"2025-05-03": 30.0}
    base_bl: dict[str, float] = {}
    dev_bl: dict[str, float] = {}
    d0 = date(2025, 1, 1)
    for i in range(20):
        ds = (d0 + timedelta(days=i)).strftime("%Y-%m-%d")
        base_bl[ds] = 1000.0
        dev_bl[ds] = 20.0
    out = build_mes_fim_projecao_pct_financeiro(
        date_i, date_f, base_mtd, dev_mtd, base_bl, dev_bl, min_baseline_days=14
    )
    assert out is not None
    assert out["ativa"] is True
    assert out["dias_restantes_no_mes"] == 21
    assert out["vs_meta"] in ("acima", "dentro")
    assert 0 <= out["pct_projetado"] <= 100
