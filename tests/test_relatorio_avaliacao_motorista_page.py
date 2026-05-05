# -*- coding: utf-8 -*-
"""Smoke tests da pagina operacional de avaliacao de motoristas."""

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Evita lock local do logs.txt ao importar a app em ambiente Windows.
logging.handlers.RotatingFileHandler = lambda *args, **kwargs: logging.NullHandler()

import main


@asynccontextmanager
async def _no_lifespan(app):
    yield


def _request(method: str, path: str):
    original_lifespan = main.app.router.lifespan_context
    main.app.router.lifespan_context = _no_lifespan
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        return client.request(method, path)
    finally:
        main.app.router.lifespan_context = original_lifespan


def test_relatorio_avaliacao_motorista_operational_page_renders():
    response = _request("GET", "/relatorio-avaliacao-motorista")

    assert response.status_code in {200, 500}
    assert "Avaliacao operacional de motoristas" in response.text
    assert 'id="relatorioFilterForm"' in response.text
    assert "/api/relatorio-avaliacao-motorista/detail" in response.text


def test_relatorio_avaliacao_motorista_detail_api_rejects_invalid_driver():
    response = _request("GET", "/api/relatorio-avaliacao-motorista/detail?driver_id=abc")

    assert response.status_code == 400
    assert response.json()["error"] == "Motorista invalido."


def test_relatorio_avaliacao_motorista_export_csv_returns_header():
    response = _request("GET", "/relatorio-avaliacao-motorista/export.csv")

    assert response.status_code == 200
    assert "attachment; filename=avaliacao_motoristas_" in response.headers.get("content-disposition", "")
    assert "data;motorista;turnos;" in response.text
