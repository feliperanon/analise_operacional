# -*- coding: utf-8 -*-
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devolucao_perda_labels import (
    canonical_responsabilidade_for_macro_loss,
    classify_macro_cause,
    macro_loss_label,
)


def test_macro_loss_label_prioriza_area_sobre_motivo_comercial():
    assert macro_loss_label("CLIENTE NÃO FEZ PEDIDO", "MERCADO") == "MERCADO"
    assert macro_loss_label("qualquer motivo", "COMERCIAL") == "COMERCIAL"


def test_macro_loss_label_sem_area_usa_classify():
    assert macro_loss_label("Cliente fechado", "-") == "Cliente / mercado"
    assert macro_loss_label("Cliente fechado", "") == "Cliente / mercado"


def test_canonical_none_para_placeholder():
    assert canonical_responsabilidade_for_macro_loss("Não informado") is None
    assert canonical_responsabilidade_for_macro_loss("IMPORT") is None


def test_classify_macro_independente():
    assert classify_macro_cause("Cliente fechado", "MERCADO") == "Cliente / mercado"
