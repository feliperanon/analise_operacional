# -*- coding: utf-8 -*-
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bi_clientes_intel as bci


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
