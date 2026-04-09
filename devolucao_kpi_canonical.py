"""
Indicador operacional único de devolução (rotas de entrega).

Critério oficial em todo o produto (Central / TV, informativo, BI):
- Numerador: rotas com status normalizado = devolução.
- Denominador: rotas concluídas (entregue ou devolução), mesmo type=delivery.
- Exceção: status devolução com motivo ENCERRAMENTO TARDIO AUTOMATICO conta como entregue
  (alinhado ao consolidado BI Entregas).
"""

from __future__ import annotations

from typing import Any, Iterable, Tuple

_DONE_STATUSES = frozenset({"entregue", "devolucao"})


def normalized_delivery_status(route: Any) -> str:
    raw = (getattr(route, "delivery_status", None) or "").strip().lower()
    if raw == "devolucao":
        reason = (getattr(route, "delivery_return_reason", None) or "").strip().upper()
        if reason == "ENCERRAMENTO TARDIO AUTOMATICO":
            return "entregue"
    return raw


def counts_devolucao_rotas_concluidas(routes: Iterable[Any]) -> Tuple[int, int]:
    """Retorna (qtd_devolucoes, qtd_rotas_concluidas) no critério canônico."""
    n_done = 0
    n_ret = 0
    for r in routes:
        s = normalized_delivery_status(r)
        if s in _DONE_STATUSES:
            n_done += 1
            if s == "devolucao":
                n_ret += 1
    return n_ret, n_done


def pct_devolucao_sobre_rotas_concluidas(routes: Iterable[Any]) -> float:
    n_ret, n_done = counts_devolucao_rotas_concluidas(routes)
    return round((n_ret / n_done * 100.0), 1) if n_done else 0.0
