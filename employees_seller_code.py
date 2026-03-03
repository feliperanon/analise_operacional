# -*- coding: utf-8 -*-
"""
Preenchimento em lote de seller_code em colaboradores.
Suporta Excel/CSV e JSON.
"""
from __future__ import annotations

import re
import io
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from sqlmodel import Session, select
import models


def normalize_seller_code(value: Any) -> Optional[str]:
    """Normaliza seller_code: trim, remove .0, múltiplos espaços."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    s = re.sub(r"\.0+$", "", s)
    s = " ".join(s.split())
    return s if s else None


@dataclass
class BatchReport:
    updated: List[Dict] = field(default_factory=list)
    ignored: List[Dict] = field(default_factory=list)
    not_found: List[Dict] = field(default_factory=list)
    duplicates: List[Dict] = field(default_factory=list)


def batch_update_from_json(
    session: Session,
    items: List[Dict[str, Any]],
) -> BatchReport:
    """
    Atualiza seller_code a partir de lista JSON.
    Cada item deve ter registration_id OU name, e seller_code.
    """
    report = BatchReport()
    emp_by_reg = {str(e.registration_id).strip(): e for e in session.exec(select(models.Employee)).all()}
    emp_by_name = {}
    for e in session.exec(select(models.Employee)).all():
        n = (e.name or "").strip().upper()
        if n:
            emp_by_name[n] = e

    codes_seen: Dict[str, List[int]] = {}

    for idx, item in enumerate(items):
        reg = (item.get("registration_id") or "").strip() if item.get("registration_id") is not None else None
        name_raw = (item.get("name") or "").strip()
        name_norm = name_raw.upper() if name_raw else None
        code_raw = item.get("seller_code")
        code = normalize_seller_code(code_raw)

        if not code:
            report.ignored.append({"row": idx + 1, "reason": "seller_code vazio ou inválido", "item": item})
            continue

        emp = None
        if reg:
            emp = emp_by_reg.get(reg) or emp_by_reg.get(str(reg))
        if not emp and name_norm:
            emp = emp_by_name.get(name_norm)

        if not emp:
            report.not_found.append({"row": idx + 1, "item": item, "tried": {"registration_id": reg, "name": name_raw}})
            continue

        if code in codes_seen:
            codes_seen[code].append(emp.id)
        else:
            codes_seen[code] = [emp.id]

        if emp.seller_code == code:
            report.ignored.append({"row": idx + 1, "reason": "já tinha esse código", "employee_id": emp.id})
            continue

        emp.seller_code = code
        session.add(emp)
        report.updated.append({"row": idx + 1, "employee_id": emp.id, "name": emp.name, "seller_code": code})

    for code, ids in codes_seen.items():
        if len(ids) > 1:
            report.duplicates.append({"seller_code": code, "employee_ids": ids})

    return report


def batch_update_from_excel(
    session: Session,
    content: bytes,
    filename: str,
) -> Tuple[Optional[BatchReport], Optional[str]]:
    """
    Atualiza seller_code a partir de Excel ou CSV.
    Colunas: registration_id OU name, seller_code.
    Retorna (BatchReport, error_message).
    """
    try:
        import pandas as pd
    except ImportError:
        return None, "Pandas não instalado."

    ext = (filename or "").lower()
    if ext.endswith(".csv"):
        try:
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8", dtype=str)
        except Exception:
            try:
                df = pd.read_csv(io.BytesIO(content), encoding="latin-1", dtype=str)
            except Exception as e:
                return None, f"Erro ao ler CSV: {e}"
    elif ext.endswith((".xlsx", ".xls", ".xlsm")):
        try:
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl" if ext.endswith(".xlsx") else "xlrd", dtype=str)
        except Exception as e:
            return None, f"Erro ao ler Excel: {e}"
    else:
        return None, "Formato inválido. Use .csv, .xlsx, .xls ou .xlsm."

    if df.empty:
        return None, "Planilha vazia."

    cols = [str(c).strip().lower() for c in df.columns]
    col_reg = None
    col_name = None
    col_code = None
    for i, c in enumerate(cols):
        if c in ("registration_id", "matricula", "matrícula", "reg_id", "cod"):
            col_reg = df.columns[i]
        if c in ("name", "nome", "nome do colaborador"):
            col_name = df.columns[i]
        if c in ("seller_code", "codigo vendedor", "código vendedor", "cod vendedor", "codigo do vendedor"):
            col_code = df.columns[i]

    if not col_code:
        return None, "Coluna 'seller_code' (ou 'codigo vendedor') não encontrada. Colunas: " + ", ".join(cols[:15])

    if not col_reg and not col_name:
        return None, "Necessário coluna 'registration_id' ou 'name' para identificar o colaborador."

    items = []
    for _, row in df.iterrows():
        reg = str(row.get(col_reg, "")).strip() if col_reg else None
        name = str(row.get(col_name, "")).strip() if col_name else None
        code = str(row.get(col_code, "")).strip()
        if not reg and not name:
            continue
        items.append({"registration_id": reg or None, "name": name or None, "seller_code": code})

    if not items:
        return None, "Nenhuma linha válida encontrada."

    report = batch_update_from_json(session, items)
    return report, None
