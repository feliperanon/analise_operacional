# -*- coding: utf-8 -*-
"""
Regra única para rótulos de perda / agrupamento no BI e relatórios.

Prioriza a área de responsabilidade cadastrada (mesma base que “Top áreas por valor”).
Só aplica a macrocausa semântica (motivo + texto auxiliar) quando a área não veio informada
ou é placeholder.
"""

from __future__ import annotations

from typing import Optional

__all__ = (
    "MISSING_RESP_FOR_MACRO",
    "norm_text_for_macro",
    "canonical_responsabilidade_for_macro_loss",
    "classify_macro_cause",
    "macro_loss_label",
)


def norm_text_for_macro(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


MISSING_RESP_FOR_MACRO = frozenset(
    {
        "",
        "-",
        "—",
        "nao informado",
        "não informado",
        "import",
        "n/a",
        "na",
    }
)


def canonical_responsabilidade_for_macro_loss(responsabilidade: Optional[str]) -> Optional[str]:
    """Área explícita no cadastro/rota — mesma base do ranking 'Top áreas por valor' na BI de devoluções."""
    raw = str(responsabilidade or "").strip()
    if not raw:
        return None
    if norm_text_for_macro(raw) in MISSING_RESP_FOR_MACRO:
        return None
    return raw


def classify_macro_cause(motivo: Optional[str], responsabilidade: Optional[str]) -> str:
    """Macrocausa semântica (motivo + responsabilidade como texto auxiliar)."""
    m = norm_text_for_macro(motivo or "")
    r = norm_text_for_macro(responsabilidade or "")
    t = f"{m} {r}"
    if any(
        k in t
        for k in (
            "sem dinheiro",
            "cheque",
            "credito",
            "crédito",
            "limite",
            "financeiro",
            "pagamento",
            "inadimpl",
        )
    ):
        return "Financeiro / pagamento"
    if any(k in t for k in ("fechado", "ausente", "nao estava", "não estava", "nao recebeu", "não recebeu", "desistiu")):
        return "Cliente / mercado"
    if any(
        k in t
        for k in (
            "localiz",
            "endereco",
            "endereço",
            "nao localizado",
            "não localizado",
            "cadastro",
            "janela",
            "horario entrega",
            "horário",
            "acesso dificil",
            "difícil acesso",
            "planejamento",
        )
    ):
        return "Cadastro / planejamento"
    if any(
        k in t
        for k in (
            "carregamento",
            "separacao",
            "separação",
            "expedicao",
            "expedição",
            "embalagem",
            "carga errada",
            "quantidade errada",
        )
    ):
        return "Logística"
    if "logist" in t:
        return "Logística"
    if any(k in t for k in ("preco", "preço", "prazo", "pedido", "produto", "comercial", "nao fez pedido", "não fez pedido", "venda")):
        return "Comercial"
    return "Comercial"


def macro_loss_label(motivo: Optional[str], responsabilidade: Optional[str]) -> str:
    """Prioriza área cadastrada; só cai na macrocausa semântica se a área não existir."""
    canon = canonical_responsabilidade_for_macro_loss(responsabilidade)
    if canon is not None:
        return canon
    return classify_macro_cause(motivo, responsabilidade)
