"""Vínculo de cliente a colaborador (código de vendedor / seller_code)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import Session, select

import models


def employee_is_vendedor(emp: models.Employee) -> bool:
    r = (emp.role or "").strip().upper()
    return "VENDEDOR" in r


def resolve_employee_id_by_seller_code(session: Session, code: Optional[str]) -> Optional[int]:
    """Resolve employee.id a partir do código (seller_code), ignorando cargo."""
    if code is None or not str(code).strip():
        return None
    raw = str(code).strip()
    stmt = (
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .where(models.Employee.seller_code.is_not(None))
        .where(func.trim(models.Employee.seller_code) == raw)
    )
    emp = session.exec(stmt).first()
    if emp:
        return emp.id
    if raw.isdigit():
        nz = raw.lstrip("0") or "0"
        stmt2 = (
            select(models.Employee)
            .where(models.Employee.status != "fired")
            .where(models.Employee.seller_code.is_not(None))
            .where(func.trim(models.Employee.seller_code) == nz)
        )
        emp2 = session.exec(stmt2).first()
        if emp2:
            return emp2.id
    return None


def list_vendedores(session: Session) -> List[models.Employee]:
    """Colaboradores ativos (qualquer cargo) para vínculo comercial — validação por código do vendedor."""
    stmt = (
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .order_by(models.Employee.name)
    )
    return list(session.exec(stmt).all())


def parse_vendedor_id_form(raw: Any) -> Optional[int]:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def apply_vendedor_to_client(session: Session, client: models.Client, vendedor_id: Optional[int]) -> None:
    """Atualiza vendedor_id e sincroniza `setor` com seller_code do colaborador (legado / importações)."""
    if not vendedor_id:
        client.vendedor_id = None
        client.setor = None
        return
    emp = session.get(models.Employee, vendedor_id)
    if not emp or (emp.status or "").strip().lower() == "fired":
        client.vendedor_id = None
        client.setor = None
        return
    client.vendedor_id = emp.id
    client.setor = (emp.seller_code or "").strip() or None


def resolve_vendedor_id_for_select(client: models.Client, session: Session) -> Optional[int]:
    if getattr(client, "vendedor_id", None):
        return client.vendedor_id
    code = (client.setor or "").strip()
    if not code:
        return None
    eid = resolve_employee_id_by_seller_code(session, code)
    return eid


def vendedor_card_for_client(session: Session, client: models.Client) -> Optional[Dict[str, Any]]:
    emp = None
    if getattr(client, "vendedor_id", None):
        emp = session.get(models.Employee, client.vendedor_id)
    if not emp and client.setor:
        code = (client.setor or "").strip()
        if code:
            eid = resolve_employee_id_by_seller_code(session, code)
            if eid:
                emp = session.get(models.Employee, eid)
    if not emp:
        return None
    return {"id": emp.id, "name": emp.name or "", "seller_code": (emp.seller_code or "").strip() or None}
