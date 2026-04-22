# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

import pytest

from services.whatsapp_provider import TwilioWhatsAppProvider, get_whatsapp_provider


def test_twilio_success_returns_message_sid():
    provider = TwilioWhatsAppProvider(
        account_sid="ACxxxxxxxx",
        auth_token="secret",
        whatsapp_from="whatsapp:+14155238886",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.text = ""
    mock_resp.json.return_value = {
        "sid": "SMxxxxxxxx",
        "status": "queued",
        "to": "whatsapp:+5511987654321",
    }
    with patch("services.whatsapp_provider.httpx.Client") as client_cls:
        instance = MagicMock()
        client_cls.return_value.__enter__.return_value = instance
        instance.post.return_value = mock_resp
        result = provider.send_message(phone_number="+5511987654321", message="Ola")
    assert result.success is True
    assert result.provider_message_id == "SMxxxxxxxx"
    call_kw = instance.post.call_args
    assert call_kw[1]["data"]["To"] == "whatsapp:+5511987654321"
    assert call_kw[1]["data"]["From"] == "whatsapp:+14155238886"
    assert call_kw[1]["auth"] == ("ACxxxxxxxx", "secret")


def test_twilio_from_adds_prefix():
    provider = TwilioWhatsAppProvider(
        account_sid="ACx",
        auth_token="y",
        whatsapp_from="+14155238886",
    )
    assert provider.whatsapp_from == "whatsapp:+14155238886"


def test_twilio_env_values_strip_inline_comments(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxxxxxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+15559359500 # producao")
    monkeypatch.setenv("TWILIO_WHATSAPP_CONTENT_SID", "HX2b691353b708edb8c0be23bb3de069a1 # template aviso")
    monkeypatch.setenv("TWILIO_WHATSAPP_CONTENT_MESSAGE_VAR", "1 # placeholder")
    provider = TwilioWhatsAppProvider()
    assert provider.whatsapp_from == "whatsapp:+15559359500"
    assert provider.content_sid == "HX2b691353b708edb8c0be23bb3de069a1"
    assert provider.content_message_var == "1"


def test_twilio_api_error():
    provider = TwilioWhatsAppProvider(
        account_sid="ACx",
        auth_token="y",
        whatsapp_from="whatsapp:+1",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = ""
    mock_resp.json.return_value = {"code": 21211, "message": "Invalid To"}
    with patch("services.whatsapp_provider.httpx.Client") as client_cls:
        instance = MagicMock()
        client_cls.return_value.__enter__.return_value = instance
        instance.post.return_value = mock_resp
        result = provider.send_message(phone_number="+5511987654321", message="Hi")
    assert result.success is False
    assert "21211" in (result.error_message or "")


def test_twilio_invalid_content_sid_fails_fast():
    provider = TwilioWhatsAppProvider(
        account_sid="ACx",
        auth_token="y",
        whatsapp_from="whatsapp:+15559359500",
        content_sid="INVALID_SID",
        content_message_var="1",
    )
    result = provider.send_message(phone_number="+5511987654321", message="Texto aviso")
    assert result.success is False
    assert "CONTENT_SID invalido" in (result.error_message or "")


def test_get_whatsapp_provider_twilio(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WHATSAPP_PROVIDER_MODE", "twilio")
    p = get_whatsapp_provider()
    assert isinstance(p, TwilioWhatsAppProvider)


def test_twilio_content_sid_fixed_template_omits_content_variables():
    provider = TwilioWhatsAppProvider(
        account_sid="ACxxxxxxxx",
        auth_token="secret",
        whatsapp_from="whatsapp:+14155238886",
        content_sid="HXb5b62575e6e4ff6129ad7c8efe1f983e",
        content_message_var="",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.text = ""
    mock_resp.json.return_value = {"sid": "SMx", "status": "queued"}
    with patch("services.whatsapp_provider.httpx.Client") as client_cls:
        instance = MagicMock()
        client_cls.return_value.__enter__.return_value = instance
        instance.post.return_value = mock_resp
        provider.send_message(phone_number="+5511987654321", message="ignored for fixed tpl")
    data = instance.post.call_args[1]["data"]
    assert "Body" not in data
    assert "ContentVariables" not in data
    assert data["ContentSid"] == "HXb5b62575e6e4ff6129ad7c8efe1f983e"


def test_twilio_content_sid_uses_content_variables_not_body():
    provider = TwilioWhatsAppProvider(
        account_sid="ACxxxxxxxx",
        auth_token="secret",
        whatsapp_from="whatsapp:+14155238886",
        content_sid="HXb5b62575e6e4ff6129ad7c8efe1f983e",
        content_message_var="1",
        content_variables_extra={"2": "3pm"},
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.text = ""
    mock_resp.json.return_value = {"sid": "SMx", "status": "queued"}
    with patch("services.whatsapp_provider.httpx.Client") as client_cls:
        instance = MagicMock()
        client_cls.return_value.__enter__.return_value = instance
        instance.post.return_value = mock_resp
        provider.send_message(phone_number="+5511987654321", message="Texto aviso")
    data = instance.post.call_args[1]["data"]
    assert "Body" not in data
    assert data["ContentSid"] == "HXb5b62575e6e4ff6129ad7c8efe1f983e"
    assert '"1": "Texto aviso"' in data["ContentVariables"]
    assert '"2": "3pm"' in data["ContentVariables"]
