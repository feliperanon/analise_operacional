"""
Normalização de centro de custo / empresa (Souza Pinto vs Exemplar) para filtros consistentes.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Optional


def normalize_cost_center(value: Optional[str]) -> str:
    """Normaliza centro de custo para comparação consistente."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFD", str(value))
    cleaned = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    compact = " ".join(
        "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in cleaned).lower().split()
    )
    if not compact:
        return ""
    if "souza" in compact and "pinto" in compact:
        return "souza_pinto"
    if "exemplar" in compact:
        return "exemplar"
    return compact.replace(" ", "_")


def cost_center_display_label(value: Optional[str]) -> str:
    """Retorna rótulo amigável para centro de custo."""
    normalized = normalize_cost_center(value)
    if normalized == "souza_pinto":
        return "Souza Pinto"
    if normalized == "exemplar":
        return "Exemplar"
    raw = (value or "").strip()
    return raw if raw else "Sem Centro"


def parse_cost_center_filter(value: Optional[str]) -> Optional[str]:
    raw = (value or "").strip()
    if not raw or raw in {"Todos", "Geral", "null", "None"}:
        return None
    return cost_center_display_label(raw)


def employee_matches_cost_center(employee: Any, selected_cost_center: Optional[str]) -> bool:
    if not selected_cost_center:
        return True
    if not employee:
        return False
    return cost_center_display_label(getattr(employee, "cost_center", None)) == selected_cost_center
