# -*- coding: utf-8 -*-
"""Testes do provedor Meta Cloud (HTTP mockado)."""

from unittest.mock import MagicMock, patch

import pytest

from services.whatsapp_provider import MetaCloudWhatsAppProvider, get_whatsapp_provider


def test_meta_cloud_success_extracts_wamid():
    provider = MetaCloudWhatsAppProvider(
        access_token="token-test",
        phone_number_id="123456789",
        api_version="21.0",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.json.return_value = {
        "messaging_product": "whatsapp",
        "contacts": [{"input": "5511987654321", "wa_id": "5511987654321"}],
        "messages": [{"id": "wamid.HBgNNTUxMTk4NzY1NDMyMRUCABEYEjQzQ0Y5N0M4Q0U5QjE4N0I4AA=="}],
    }
    with patch("services.whatsapp_provider.httpx.Client") as client_cls:
        instance = MagicMock()
        client_cls.return_value.__enter__.return_value = instance
        instance.post.return_value = mock_resp
        result = provider.send_message(
            phone_number="+5511987654321",
            message="Ola teste",
            metadata={"client_id": 1},
        )
    assert result.success is True
    assert result.provider_name == "meta_cloud"
    assert result.provider_message_id == mock_resp.json.return_value["messages"][0]["id"]
    assert result.error_message is None
    call_kw = instance.post.call_args
    assert "graph.facebook.com" in call_kw[0][0]
    assert call_kw[1]["json"]["to"] == "5511987654321"


def test_meta_cloud_graph_error():
    provider = MetaCloudWhatsAppProvider(
        access_token="token-test",
        phone_number_id="123456789",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = ""
    mock_resp.json.return_value = {
        "error": {
            "message": "Invalid OAuth access token.",
            "type": "OAuthException",
            "code": 190,
        }
    }
    with patch("services.whatsapp_provider.httpx.Client") as client_cls:
        instance = MagicMock()
        client_cls.return_value.__enter__.return_value = instance
        instance.post.return_value = mock_resp
        result = provider.send_message(phone_number="+5511987654321", message="Hi")
    assert result.success is False
    assert "190" in (result.error_message or "")
    assert "Invalid OAuth" in (result.error_message or "")


def test_meta_cloud_missing_config():
    provider = MetaCloudWhatsAppProvider(access_token="", phone_number_id="")
    result = provider.send_message(phone_number="+5511987654321", message="Hi")
    assert result.success is False
    assert "WHATSAPP_CLOUD_ACCESS_TOKEN" in (result.error_message or "")


def test_get_whatsapp_provider_meta_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WHATSAPP_PROVIDER_MODE", "meta_cloud")
    monkeypatch.setenv("WHATSAPP_CLOUD_ACCESS_TOKEN", "x")
    monkeypatch.setenv("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "y")
    p = get_whatsapp_provider()
    assert isinstance(p, MetaCloudWhatsAppProvider)


def test_meta_cloud_template_payload():
    provider = MetaCloudWhatsAppProvider(
        access_token="t",
        phone_number_id="1",
        template_name="aviso_teste",
        template_language="pt_BR",
        template_body_var_count=1,
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ""
    mock_resp.json.return_value = {"messages": [{"id": "wamid.x"}]}
    with patch("services.whatsapp_provider.httpx.Client") as client_cls:
        instance = MagicMock()
        client_cls.return_value.__enter__.return_value = instance
        instance.post.return_value = mock_resp
        provider.send_message(phone_number="+5511987654321", message="Texto do aviso")
    posted = instance.post.call_args[1]["json"]
    assert posted["type"] == "template"
    assert posted["template"]["name"] == "aviso_teste"
    assert posted["template"]["components"][0]["parameters"][0]["text"] == "Texto do aviso"
