"""Vínculo de cliente a vendedor (colaborador com cargo de vendedor)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func, literal
from sqlmodel import Session, select

import models


def employee_is_vendedor(emp: models.Employee) -> bool:
    r = (emp.role or "").strip().upper()
    return "VENDEDOR" in r


def list_vendedores(session: Session) -> List[models.Employee]:
    stmt = (
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .where(func.upper(func.coalesce(models.Employee.role, literal(""))).like("%VENDEDOR%"))
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
    if not emp or not employee_is_vendedor(emp):
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
    emp = session.exec(select(models.Employee).where(models.Employee.seller_code == code)).first()
    if emp and employee_is_vendedor(emp):
        return emp.id
    return None


def vendedor_card_for_client(session: Session, client: models.Client) -> Optional[Dict[str, Any]]:
    emp = None
    if getattr(client, "vendedor_id", None):
        emp = session.get(models.Employee, client.vendedor_id)
    if not emp and client.setor:
        code = (client.setor or "").strip()
        if code:
            emp = session.exec(select(models.Employee).where(models.Employee.seller_code == code)).first()
    if not emp:
        return None
    return {"id": emp.id, "name": emp.name or "", "seller_code": (emp.seller_code or "").strip() or None}
