# -*- coding: utf-8 -*-
"""Compatibilidade para abertura direta de /employees/{id}/status."""

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


def test_employee_status_get_redirects_to_employee_detail():
    original_lifespan = main.app.router.lifespan_context
    main.app.router.lifespan_context = _no_lifespan
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.get("/employees/781/status", follow_redirects=False)
    finally:
        main.app.router.lifespan_context = original_lifespan

    assert response.status_code == 303
    assert response.headers["location"] == "/employees/781"
