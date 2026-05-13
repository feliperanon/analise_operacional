"""Tipos canônicos para registro de devolução evitada (BI + API)."""

from __future__ import annotations

EVITADA_TIPO_LABELS: dict[str, str] = {
    "cliente_fechado": "Cliente fechado / não recebeu",
    "contato_comercial": "Resolvido via comercial / contato",
    "reagendamento": "Reagendamento de entrega",
    "endereco_acesso": "Endereço / acesso / localização",
    "documentacao": "Documentação / NF / pedido",
    "carga_conferencia": "Conferência / carga / avaria evitada",
    "outros": "Outros",
}

EVITADA_TIPOS_ORDENADOS: tuple[str, ...] = tuple(EVITADA_TIPO_LABELS.keys())


def label_tipo_evitada(tipo: str) -> str:
    t = (tipo or "").strip().lower()
    return EVITADA_TIPO_LABELS.get(t, tipo or "—")
