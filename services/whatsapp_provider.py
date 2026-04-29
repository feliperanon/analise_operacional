# -*- coding: utf-8 -*-
"""Camada desacoplada para envio de WhatsApp.

- mock: padrao (desenvolvimento / testes);
- meta_cloud: API oficial WhatsApp Cloud (Graph API).

Variaveis para meta_cloud (definir no .env ou painel):
  WHATSAPP_PROVIDER_MODE=meta_cloud
  WHATSAPP_CLOUD_ACCESS_TOKEN   — token permanente ou de sistema do app Meta
  WHATSAPP_CLOUD_PHONE_NUMBER_ID — ID do numero na API (nao e o telefone em si)
  WHATSAPP_CLOUD_API_VERSION     — opcional (padrao v21.0)

  Opcional — template aprovado na Meta (recomendado para avisos proativos):
  WHATSAPP_CLOUD_TEMPLATE_NAME       — nome do template (ex.: aviso_rota_saida)
  WHATSAPP_CLOUD_TEMPLATE_LANGUAGE   — padrao pt_BR
  WHATSAPP_CLOUD_TEMPLATE_BODY_VARS  — quantidade de variaveis no corpo (0 ou 1; padrao 1).
    Com 1, o texto completo do aviso preenche o primeiro placeholder do template.

Aliases aceitos: META_WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)


def _sanitize_env_value(raw_value: str) -> str:
    """Normaliza valores de env para evitar erros comuns de configuracao."""
    value = (raw_value or "").strip().strip('"').strip("'")
    # Evita erros quando comentario foi colocado na mesma linha do valor no .env.
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    return value


@dataclass
class WhatsAppSendResult:
    success: bool
    provider_name: str
    request_payload: Dict[str, Any]
    response_payload: Dict[str, Any]
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None


class BaseWhatsAppProvider:
    provider_name = "base"

    def prepare_payload(
        self,
        *,
        phone_number: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "to": phone_number,
            "message": message,
            "metadata": metadata or {},
        }

    def send_message(
        self,
        *,
        phone_number: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WhatsAppSendResult:
        raise NotImplementedError

    def send_batch(self, payloads: List[Dict[str, Any]]) -> List[WhatsAppSendResult]:
        results: List[WhatsAppSendResult] = []
        for payload in payloads:
            results.append(
                self.send_message(
                    phone_number=str(payload.get("to") or ""),
                    message=str(payload.get("message") or ""),
                    metadata=payload.get("metadata") or {},
                )
            )
        return results

    def normalize_response(self, response_payload: Dict[str, Any]) -> Dict[str, Any]:
        return response_payload

    def normalize_error(self, error_message: str) -> Dict[str, Any]:
        return {"ok": False, "error": error_message}


class MockWhatsAppProvider(BaseWhatsAppProvider):
    provider_name = "mock"

    def __init__(self, fail_suffixes: Optional[List[str]] = None):
        configured = fail_suffixes
        if configured is None:
            raw = os.getenv("WHATSAPP_MOCK_FAIL_SUFFIXES", "0000,9999")
            configured = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
        self.fail_suffixes = configured

    def _should_fail(self, phone_number: str, metadata: Optional[Dict[str, Any]]) -> bool:
        meta = metadata or {}
        if bool(meta.get("force_fail")):
            return True
        digits = "".join(ch for ch in (phone_number or "") if ch.isdigit())
        return any(digits.endswith(suffix) for suffix in self.fail_suffixes)

    def send_message(
        self,
        *,
        phone_number: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WhatsAppSendResult:
        request_payload = self.prepare_payload(
            phone_number=phone_number,
            message=message,
            metadata=metadata,
        )

        now = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
        if self._should_fail(phone_number, metadata):
            response_payload = {
                "ok": False,
                "provider": self.provider_name,
                "timestamp": now,
                "error_code": "mock_delivery_failure",
                "detail": "Falha simulada pelo provider mock.",
            }
            return WhatsAppSendResult(
                success=False,
                provider_name=self.provider_name,
                request_payload=request_payload,
                response_payload=response_payload,
                error_message="Falha simulada pelo provider mock.",
            )

        provider_message_id = f"mock-{secrets.token_hex(8)}"
        response_payload = {
            "ok": True,
            "provider": self.provider_name,
            "timestamp": now,
            "message_id": provider_message_id,
            "accepted": True,
        }
        return WhatsAppSendResult(
            success=True,
            provider_name=self.provider_name,
            request_payload=request_payload,
            response_payload=response_payload,
            provider_message_id=provider_message_id,
        )


def _recipient_digits_e164(phone_number: str) -> str:
    """Converte +5511... ou 5511... para apenas digitos (formato esperado pela Cloud API)."""
    return "".join(ch for ch in (phone_number or "") if ch.isdigit())


class MetaCloudWhatsAppProvider(BaseWhatsAppProvider):
    """Envio via WhatsApp Cloud API (Meta Graph API)."""

    provider_name = "meta_cloud"

    def __init__(
        self,
        *,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_version: Optional[str] = None,
        template_name: Optional[str] = None,
        template_language: Optional[str] = None,
        template_body_var_count: Optional[int] = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.access_token = (
            access_token
            or os.getenv("WHATSAPP_CLOUD_ACCESS_TOKEN")
            or os.getenv("META_WHATSAPP_ACCESS_TOKEN")
            or ""
        ).strip()
        self.phone_number_id = (
            (phone_number_id or os.getenv("WHATSAPP_CLOUD_PHONE_NUMBER_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "")
            .strip()
        )
        ver = (api_version or os.getenv("WHATSAPP_CLOUD_API_VERSION") or "21.0").strip()
        if ver.lower().startswith("v"):
            ver = ver[1:].strip()
        self.api_version = f"v{ver}" if ver else "v21.0"
        self.timeout_seconds = timeout_seconds
        self.template_name = (template_name or os.getenv("WHATSAPP_CLOUD_TEMPLATE_NAME") or "").strip()
        self.template_language = (template_language or os.getenv("WHATSAPP_CLOUD_TEMPLATE_LANGUAGE") or "pt_BR").strip()
        raw_vars = os.getenv("WHATSAPP_CLOUD_TEMPLATE_BODY_VARS", "1").strip()
        if template_body_var_count is not None:
            self.template_body_var_count = max(0, min(1, int(template_body_var_count)))
        else:
            try:
                n = int(raw_vars)
            except ValueError:
                n = 1
            self.template_body_var_count = 0 if n <= 0 else 1

    def _graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    def _build_graph_message_body(self, *, to_digits: str, message: str) -> Dict[str, Any]:
        if self.template_name:
            tpl: Dict[str, Any] = {
                "name": self.template_name,
                "language": {"code": self.template_language},
            }
            if self.template_body_var_count >= 1:
                text = (message or "")[:4096]
                tpl["components"] = [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": text}],
                    }
                ]
            else:
                tpl["components"] = []
            return {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_digits,
                "type": "template",
                "template": tpl,
            }
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_digits,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }

    def send_message(
        self,
        *,
        phone_number: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WhatsAppSendResult:
        to_digits = _recipient_digits_e164(phone_number)
        body_graph = self._build_graph_message_body(to_digits=to_digits, message=message)
        request_payload = self.prepare_payload(
            phone_number=phone_number,
            message=message,
            metadata=metadata,
        )
        request_payload["graph_body"] = body_graph
        request_payload["graph_url"] = self._graph_url()

        now = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()

        if not self.access_token or not self.phone_number_id:
            detail = "Configure WHATSAPP_CLOUD_ACCESS_TOKEN e WHATSAPP_CLOUD_PHONE_NUMBER_ID."
            return WhatsAppSendResult(
                success=False,
                provider_name=self.provider_name,
                request_payload=request_payload,
                response_payload={"ok": False, "timestamp": now, "error": detail},
                error_message=detail,
            )

        if not to_digits or len(to_digits) < 10:
            detail = "Numero de destino invalido ou vazio."
            return WhatsAppSendResult(
                success=False,
                provider_name=self.provider_name,
                request_payload=request_payload,
                response_payload={"ok": False, "timestamp": now, "error": detail},
                error_message=detail,
            )

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self._graph_url(), headers=headers, json=body_graph)
        except httpx.HTTPError as exc:
            err = f"Erro de rede ao chamar Graph API: {exc}"
            return WhatsAppSendResult(
                success=False,
                provider_name=self.provider_name,
                request_payload=request_payload,
                response_payload={"ok": False, "timestamp": now, "error": err, "exception": str(exc)},
                error_message=err,
            )

        try:
            data = response.json()
        except Exception:
            text = (response.text or "")[:2000]
            err = f"Resposta nao-JSON da Graph API (HTTP {response.status_code}): {text}"
            return WhatsAppSendResult(
                success=False,
                provider_name=self.provider_name,
                request_payload=request_payload,
                response_payload={"ok": False, "timestamp": now, "raw_status": response.status_code, "raw_body": text},
                error_message=err,
            )

        if response.status_code >= 400 or data.get("error"):
            fb_err = data.get("error") if isinstance(data.get("error"), dict) else {}
            msg = (
                fb_err.get("message")
                or (str(data.get("error")) if data.get("error") else None)
                or response.text[:500]
            )
            code = fb_err.get("code")
            err_out = f"Graph API erro ({response.status_code})" + (f" [{code}]" if code is not None else "") + f": {msg}"
            payload = dict(data)
            payload["ok"] = False
            payload["timestamp"] = now
            return WhatsAppSendResult(
                success=False,
                provider_name=self.provider_name,
                request_payload=request_payload,
                response_payload=payload,
                error_message=err_out,
            )

        messages = data.get("messages") or []
        wamid = None
        if messages and isinstance(messages[0], dict):
            wamid = messages[0].get("id")

        ok_payload = dict(data)
        ok_payload["ok"] = True
        ok_payload["timestamp"] = now
        return WhatsAppSendResult(
            success=True,
            provider_name=self.provider_name,
            request_payload=request_payload,
            response_payload=ok_payload,
            provider_message_id=wamid,
        )


def get_whatsapp_provider() -> BaseWhatsAppProvider:
    mode = (os.getenv("WHATSAPP_PROVIDER_MODE", "mock") or "mock").strip().lower()
    if mode in ("mock", ""):
        return MockWhatsAppProvider()
    if mode in ("meta_cloud", "meta", "cloud", "graph", "facebook", "whatsapp_cloud"):
        return MetaCloudWhatsAppProvider()
    return MockWhatsAppProvider()
