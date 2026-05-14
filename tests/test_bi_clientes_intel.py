# -*- coding: utf-8 -*-
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bi_clientes_intel as bci


def test_build_operational_reading_cards_includes_drill_fields():
    cards = bci.build_operational_reading_cards(
        returned_total=1000.0,
        delivered_total=5000.0,
        planned_total=4800.0,
        n_clients=50,
        n_above_meta=3,
        n_small_high_impact=2,
        top10_delivered_share_pct=40.0,
        main_motivo="Pagamento",
        main_resp="Comercial",
        main_resp_value=200.0,
        treatable_value=150.0,
    )
    assert cards and cards[0].get("card_key") == "impacto_financeiro"
    assert isinstance(cards[0].get("context"), list) and isinstance(cards[0].get("hints"), list)


def test_treatable_motivo_breakdown_filters_and_sorts():
    m = {
        "preço errado na nota": {"value": 50.0, "count": 1},
        "Cliente ausente": {"value": 200.0, "count": 2},
        "Motivo genérico": {"value": 999.0, "count": 5},
    }
    rows = bci.treatable_motivo_breakdown(m)
    assert len(rows) == 2
    assert rows[0]["motivo"] == "Cliente ausente"
    assert rows[0]["value"] == 200.0
    assert rows[1]["value"] == 50.0


def test_large_risk_context_has_percent_line():
    lines = bci.large_risk_context_lines(
        {
            "return_pct_planned": 12.5,
            "returned_value": 100.0,
            "delivered_value": 800.0,
            "returned_occurrences": 2,
            "visits": 10,
            "top_motivo_name": "Pagamento",
            "top_responsabilidade_name": "Logística",
        }
    )
    assert any("%" in x for x in lines)
    sol = bci.large_risk_solution_lines({"action_recommendation": "Testar rota.", "top_motivo_name": "Pagamento"})
    assert any("rota" in x.lower() or "pagamento" in x.lower() for x in sol)


def test_suggest_treatable_resolutions_dedupes_and_limits():
    hints = bci.suggest_treatable_resolutions(
        treatable_motivos=[{"motivo": "Problema de pagamento", "value": 10, "count": 1}],
        top_motivo_name="Pagamento",
        top_responsabilidade_name="Logística",
        classification_code="CRITICO",
        action_recommendation="Plano de ação conjunto comercial + logística.",
    )
    assert any("Plano de ação" in h for h in hints)
    assert any("Pagamento" in h for h in hints)
    assert len(hints) <= 6
