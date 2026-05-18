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


def test_dominio_operacional_por_motivo_souza_pinto():
    assert bci.dominio_operacional_por_motivo("Pedido / produto errado") == "Comercial"
    assert bci.dominio_operacional_por_motivo("Cliente fechado") == "Mercado"
    assert bci.dominio_operacional_por_motivo("Pedido não entregue") == "Logística"
    assert bci.dominio_operacional_por_motivo("") == "Sem classificação"
    assert bci.dominio_operacional_por_motivo("Horário entrega") == "Sem classificação"
    assert bci.dominio_operacional_por_motivo("Horário entrega — atraso operacional") == "Logística"


def test_client_recurrence_fields():
    row = {"visits": 10, "returned_occurrences": 3, "top_motivo_name": "Pagamento", "top_responsabilidade_name": "Comercial"}
    out = bci.client_recurrence_fields(row)
    assert out["return_count"] == 3
    assert out["return_recurrence_pct"] == 30.0
    assert out["recurrence_label"] == "3 de 10 visitas"
    assert out["leader_reason"] == "Pagamento"


def test_client_recurrence_fields_zero_visits():
    out = bci.client_recurrence_fields({"visits": 0, "returned_occurrences": 0})
    assert out["return_recurrence_pct"] == 0.0
    assert out["recurrence_label"] == "0 de 0 visitas"


def test_client_priority_label_critical_recurrent():
    label, tone = bci.client_priority_label(
        {"returned_value": 900.0, "return_count": 2, "return_pct_planned": 8.0}
    )
    assert label == "Crítico recorrente"
    assert tone == "danger"


def test_client_priority_label_low_risk():
    label, tone = bci.client_priority_label(
        {"returned_value": 50.0, "return_count": 0, "return_pct_planned": 0.0}
    )
    assert label == "Baixo risco"
    assert tone == "ok"


def test_build_decision_strip_intel_thresholds():
    base = dict(
        treatable_total=0.0,
        returned_total=10000.0,
        critical_count=0,
        n_clients=50,
        main_motivo="X",
        main_responsibility="Comercial",
        main_responsibility_detail="60% do valor devolvido no recorte · demais áreas no restante",
    )
    ok = bci.build_decision_strip_intel(pct_gl=1.8, meta_pct=2.0, **base)
    assert ok["situation_key"] == "ok"
    assert "dentro da meta" in ok["situation_hint"].lower()

    warn = bci.build_decision_strip_intel(pct_gl=2.5, meta_pct=2.0, **base)
    assert warn["situation_key"] == "warn"

    crit = bci.build_decision_strip_intel(pct_gl=3.5, meta_pct=2.0, **base)
    assert crit["situation_key"] == "crit"
    assert "crítico" in crit["situation_hint"].lower()


def test_primeira_acao_prioridade_sp_order():
    fb = "Fallback recomendação."
    out = bci.primeira_acao_prioridade_sp(
        treatable_total=4000.0,
        returned_total=10000.0,
        critical_count=20,
        large_risk_count=10,
        small_high_count=30,
        n_clients=100,
        fallback=fb,
    )
    assert "tratável" in out.lower() or "tratavel" in out.lower()

    out2 = bci.primeira_acao_prioridade_sp(
        treatable_total=0.0,
        returned_total=50000.0,
        critical_count=15,
        large_risk_count=2,
        small_high_count=5,
        n_clients=100,
        fallback=fb,
    )
    assert "Comercial" in out2 and "Logística" in out2


def test_dominante_operacional_por_valor_devolvido_weights_by_motivo():
    rows = [
        {"top_motivo_name": "Cliente fechado", "returned_value": 100.0},
        {"top_motivo_name": "Pedido errado", "returned_value": 300.0},
    ]
    label, detail = bci.dominante_operacional_por_valor_devolvido(rows)
    assert label == "Comercial"
    assert "%" in detail


def test_ranking_pct_pool_excludes_low_volume_from_maior_pct_integration():
    """Clientes com entregue baixo não entram no ranking principal de % (lógica no dataset)."""
    rows = [
        {"delivered_value": 500.0, "returned_value": 400.0, "return_pct_planned": 80.0},
        {"delivered_value": 10000.0, "returned_value": 500.0, "return_pct_planned": 5.0},
    ]
    MIN_VOL = float(bci.MIN_VOLUME_ENTREGUE_PAR_RANKING_PCT_BRL)
    pct_rank_pool = [
        r
        for r in rows
        if float(r.get("delivered_value") or 0) >= MIN_VOL
        and float(r.get("delivered_value") or 0) + float(r.get("returned_value") or 0) > 0
    ]
    assert len(pct_rank_pool) == 1
    assert pct_rank_pool[0]["return_pct_planned"] == 5.0
