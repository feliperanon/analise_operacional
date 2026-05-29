"""Vínculo de cliente a colaborador (código de vendedor / seller_code)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import Session, select

import models
from employees_seller_code import normalize_seller_code


def _seller_codes_equivalent(a: Optional[str], b: Optional[str]) -> bool:
    """True quando dois códigos de vendedor representam o mesmo valor (201 == 201.0)."""
    na = normalize_seller_code(a)
    nb = normalize_seller_code(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na.isdigit() and nb.isdigit():
        return (na.lstrip("0") or "0") == (nb.lstrip("0") or "0")
    return False


def employee_is_vendedor(emp: models.Employee) -> bool:
    r = (emp.role or "").strip().upper()
    return "VENDEDOR" in r


def resolve_employee_id_by_seller_code(session: Session, code: Optional[str]) -> Optional[int]:
    """Resolve employee.id a partir do código (seller_code), ignorando cargo."""
    want = normalize_seller_code(code)
    if not want:
        return None
    raw = str(code).strip()
    variants = {raw, want}
    if want.isdigit():
        variants.add(want.lstrip("0") or "0")
    for variant in variants:
        stmt = (
            select(models.Employee)
            .where(models.Employee.status != "fired")
            .where(models.Employee.seller_code.is_not(None))
            .where(func.trim(models.Employee.seller_code) == variant)
        )
        emp = session.exec(stmt).first()
        if emp:
            return emp.id
    stmt_all = (
        select(models.Employee)
        .where(models.Employee.status != "fired")
        .where(models.Employee.seller_code.is_not(None))
        .where(func.trim(models.Employee.seller_code) != "")
    )
    for emp in session.exec(stmt_all).all():
        if _seller_codes_equivalent(emp.seller_code, want):
            return emp.id
    return None


def resolve_employee_id_by_code_or_name(session: Session, raw: Optional[str]) -> Optional[int]:
    """Resolve vendedor por código (seller_code), prefixo numérico ou nome do colaborador."""
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    rid = resolve_employee_id_by_seller_code(session, text)
    if rid:
        return rid
    m = re.match(r"^(\d+)", text)
    if m:
        rid = resolve_employee_id_by_seller_code(session, m.group(1))
        if rid:
            return rid
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFD", s or "")
        return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()

    needle = _norm(text)
    if not needle:
        return None
    for emp in list_vendedores(session):
        name_n = _norm(emp.name or "")
        if needle == name_n or (len(needle) >= 3 and needle in name_n):
            return emp.id
        sc = normalize_seller_code(emp.seller_code)
        if sc and (needle == _norm(sc) or _seller_codes_equivalent(sc, text)):
            return emp.id
    return None


def resolve_vendedor_id_from_import_fields(
    session: Session,
    setor: Optional[str],
    me: Optional[str],
) -> Optional[int]:
    """Resolve vendedor na importação de clientes (coluna SETOR e fallback ME)."""
    for raw in (setor, me):
        rid = resolve_employee_id_by_code_or_name(session, raw)
        if rid:
            return rid
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
    for code in ((client.setor or "").strip(), (client.me or "").strip()):
        if not code:
            continue
        eid = resolve_employee_id_by_seller_code(session, code)
        if eid:
            return eid
    return None


def vendedor_card_for_client(session: Session, client: models.Client) -> Optional[Dict[str, Any]]:
    emp = None
    if getattr(client, "vendedor_id", None):
        emp = session.get(models.Employee, client.vendedor_id)
    if not emp:
        for code in ((client.setor or "").strip(), (client.me or "").strip()):
            if not code:
                continue
            eid = resolve_employee_id_by_seller_code(session, code)
            if eid:
                emp = session.get(models.Employee, eid)
                break
    if not emp:
        return None
    return {"id": emp.id, "name": emp.name or "", "seller_code": (emp.seller_code or "").strip() or None}
