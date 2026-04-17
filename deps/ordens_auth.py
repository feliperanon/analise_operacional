# -*- coding: utf-8 -*-
"""Auth para rotas de ordens de serviço (gerente) e líder, sem importar main."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request

_require_login: Optional[Callable[[Request], Any]] = None
_require_leader: Optional[Callable[[Request], Any]] = None


def init_ordens_auth(require_login_fn: Callable[[Request], Any], require_leader_fn: Callable[[Request], Any]) -> None:
    global _require_login, _require_leader
    _require_login = require_login_fn
    _require_leader = require_leader_fn


def _session_has_gerente_pages(request: Request) -> bool:
    """Página 'gerente' nas permissões (lista na sessão ou JSON legado no user)."""
    raw = request.session.get("allowed_pages")
    if isinstance(raw, list):
        return "gerente" in raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return isinstance(data, list) and "gerente" in data
        except Exception:
            return False
    return False


def require_gerente(request: Request):
    """Admin, papel gerente/gm ou líder com menu Gerente liberado."""
    if _require_login is None:
        raise RuntimeError("init_ordens_auth() não foi chamado")
    user = _require_login(request)
    role = user.get("role", "").lower() if isinstance(user, dict) else ""
    if role in ("admin", "gm", "gerente"):
        return user
    if role == "leader" and _session_has_gerente_pages(request):
        return user
    raise HTTPException(status_code=403, detail="Acesso restrito ao Gerente")


def require_leader_ordens(request: Request):
    if _require_leader is None:
        raise RuntimeError("init_ordens_auth() não foi chamado")
    return _require_leader(request)
