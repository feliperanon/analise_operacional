# -*- coding: utf-8 -*-
"""Serviço de geocodificação usando Nominatim (OpenStreetMap).

Respeita o rate limit de 1 requisição/segundo conforme política de uso da API.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

from utils.geo_utils import validate_coordinates

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AnaliseOperacional/1.0"
TIMEOUT_SECONDS = 10
_last_request_time: float = 0.0  # controle global de rate limit


@dataclass
class GeocodingResult:
    """Resultado de uma operação de geocodificação."""

    success: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    display_name: Optional[str] = None
    source: str = "nominatim"
    error: Optional[str] = None


class GeocodingService:
    """Serviço de geocodificação usando Nominatim (OpenStreetMap)."""

    def __init__(self, user_agent: str = USER_AGENT, timeout: int = TIMEOUT_SECONDS):
        self.user_agent = user_agent
        self.timeout = timeout

    def _respect_rate_limit(self) -> None:
        """Aguarda se necessário para respeitar o rate limit de 1 req/segundo."""
        global _last_request_time
        elapsed = time.monotonic() - _last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_request_time = time.monotonic()

    def geocode_address(
        self,
        street: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: str = "Brasil",
    ) -> GeocodingResult:
        """Geocodifica um endereço usando Nominatim.

        Args:
            street: Logradouro + número (ex: "Rua das Flores, 123").
            city: Cidade/Município.
            state: Estado (sigla ou nome).
            country: País (default: "Brasil").

        Returns:
            GeocodingResult com coordenadas ou mensagem de erro.
        """
        if not _HTTPX_AVAILABLE:
            return GeocodingResult(
                success=False,
                error="httpx não instalado. Execute: pip install httpx",
            )

        # Monta query de busca
        parts = [p for p in [street, city, state, country] if p]
        if not parts:
            return GeocodingResult(success=False, error="Endereço vazio")

        query = ", ".join(parts)
        self._respect_rate_limit()

        try:
            headers = {"User-Agent": self.user_agent}
            params = {
                "q": query,
                "format": "json",
                "limit": 1,
                "countrycodes": "br",
            }
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(NOMINATIM_URL, params=params, headers=headers)
                response.raise_for_status()
                results = response.json()

            if not results:
                return GeocodingResult(
                    success=False,
                    error=f"Endereço não encontrado: {query}",
                )

            result = results[0]
            lat_raw = result.get("lat")
            lon_raw = result.get("lon")
            if lat_raw is None or lon_raw is None:
                return GeocodingResult(
                    success=False,
                    error=f"Resposta sem coordenadas para: {query}",
                )
            lat = float(lat_raw)
            lon = float(lon_raw)

            if not validate_coordinates(lat, lon):
                return GeocodingResult(
                    success=False,
                    error=f"Coordenadas inválidas retornadas: {lat}, {lon}",
                )

            return GeocodingResult(
                success=True,
                latitude=lat,
                longitude=lon,
                display_name=result.get("display_name"),
                source="nominatim",
            )

        except httpx.TimeoutException:
            return GeocodingResult(success=False, error="Timeout ao consultar Nominatim")
        except httpx.HTTPStatusError as e:
            return GeocodingResult(success=False, error=f"HTTP {e.response.status_code}: {e.response.text[:200]}")
        except httpx.RequestError as e:
            return GeocodingResult(success=False, error=f"Erro de rede: {str(e)}")
        except Exception as e:
            logger.exception("Erro inesperado na geocodificação: %s", e)
            return GeocodingResult(success=False, error=f"Erro inesperado: {str(e)}")

    def geocode_cliente(self, client) -> GeocodingResult:
        """Geocodifica um objeto Cliente usando seus campos de endereço.

        Tenta geocodificar com progressivamente menos detalhes caso falhe.
        Nunca lança exceção — retorna GeocodingResult com sucesso ou erro.

        Args:
            client: Objeto Client do SQLModel.

        Returns:
            GeocodingResult com resultado da geocodificação.
        """
        # Monta componentes de endereço priorizando logradouro/numero sobre endereco
        street = None
        logradouro = client.logradouro or client.endereco
        if logradouro:
            street = logradouro
            if client.numero:
                street = f"{logradouro}, {client.numero}"

        city = client.municipio
        # Para busca no Brasil, "estado" não é necessário se há cidade

        if not street and not city:
            return GeocodingResult(
                success=False,
                error="Cliente sem endereço ou município para geocodificar",
            )

        # Tentativa 1: endereço completo
        result = self.geocode_address(street=street, city=city)
        if result.success:
            return result

        # Tentativa 2: apenas cidade (fallback)
        if city:
            logger.debug("Geocodificação fallback: apenas cidade '%s'", city)
            result2 = self.geocode_address(city=city)
            if result2.success:
                result2.error = f"Coordenadas aproximadas (centro de {city})"
                return result2

        return result


# Instância singleton para uso compartilhado
geocoding_service = GeocodingService()
