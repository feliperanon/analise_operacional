"""Detecção de execução na Google Cloud (Cloud Run, GKE, etc.)."""

from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _flag_active(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def gcp_platform_active(
    gcp_env: str | None = None,
    google_cloud_env: str | None = None,
    k_service: str | None = None,
) -> bool:
    """
    True se o processo parece rodar na Google Cloud.

    K_SERVICE é definido automaticamente no Cloud Run.
    GCP / GOOGLE_CLOUD podem ser definidos manualmente no .env ou no painel.
    """
    if _flag_active(gcp_env if gcp_env is not None else os.environ.get("GCP")):
        return True
    if _flag_active(
        google_cloud_env if google_cloud_env is not None else os.environ.get("GOOGLE_CLOUD")
    ):
        return True
    if (k_service if k_service is not None else os.environ.get("K_SERVICE") or "").strip():
        return True
    return False


def is_cloud_sql_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    h = hostname.lower()
    return ".sql.goog" in h or "cloudsql" in h
