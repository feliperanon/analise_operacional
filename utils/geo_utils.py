# -*- coding: utf-8 -*-
"""Utilitários de cálculo geográfico para o sistema de entregas."""

import math
from typing import Optional, Tuple


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância em metros entre dois pontos GPS usando a fórmula Haversine.

    Args:
        lat1, lon1: Coordenadas do ponto de origem (graus decimais).
        lat2, lon2: Coordenadas do ponto de destino (graus decimais).

    Returns:
        Distância em metros entre os dois pontos.
    """
    R = 6_371_000  # Raio da Terra em metros

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def validate_coordinates(latitude: Optional[float], longitude: Optional[float]) -> bool:
    """Valida se um par de coordenadas geográficas é válido.

    Args:
        latitude: Latitude em graus decimais (-90 a 90).
        longitude: Longitude em graus decimais (-180 a 180).

    Returns:
        True se as coordenadas são válidas, False caso contrário.
    """
    if latitude is None or longitude is None:
        return False
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def format_distance(meters: float) -> str:
    """Formata uma distância em metros para exibição amigável.

    Args:
        meters: Distância em metros.

    Returns:
        String formatada (ex: "450m", "2.3km").
    """
    if meters < 1000:
        return f"{int(round(meters))}m"
    km = meters / 1000.0
    if km < 10:
        return f"{km:.1f}km"
    return f"{int(round(km))}km"
