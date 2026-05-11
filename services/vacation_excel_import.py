"""
Importação de planilhas tipo «acompanhamento vencimento férias» (Excel .xls/.xlsx).

Associa linhas ao cadastro de Employee (nome e/ou matrícula) e grava datas no
EmployeeVacationProfile (acquisition_period_end), alinhado ao motor de
planejamento (concessivo = fim aquisitivo + ~365 dias no serviço atual).

Opcional: atualiza Employee.admission_date a partir da coluna de admissão.
"""
from __future__ import annotations

import io
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlmodel import Session, col, select

import models
from services.vacation_planning_service import upsert_profile


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _norm_header(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = _strip_accents(str(val).strip().upper())
    return s.replace("º", "O").replace("°", "O")


def _norm_name_key(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    return " ".join(_strip_accents(name).upper().split())


def parse_cell_date(val: Any) -> Optional[date]:
    """Aceita datetime Excel, Timestamp, string dd/mm/aaaa ou iso."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if hasattr(val, "date") and callable(getattr(val, "date")):
        try:
            return val.date()  # type: ignore[no-any-return]
        except Exception:
            pass
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s[:10], fmt).date()
        except ValueError:
            continue
    try:
        if len(s) >= 10 and s[4] == "-":
            return date.fromisoformat(s[:10])
    except ValueError:
        pass
    return None


def _is_period_column(h: str) -> bool:
    if not h:
        return False
    hn = _norm_header(h)
    return "PERIODO" in hn and bool(re.search(r"\d", hn))


def _classify_columns(headers: List[str]) -> Dict[str, Any]:
    col_idx = {"name": None, "role": None, "registration": None, "admission": None, "periods": []}
    for i, raw in enumerate(headers):
        h = _norm_header(raw)
        if not h:
            continue
        if col_idx["name"] is None and ("COLABORADOR" in h or h == "NOME" or h.startswith("FUNCIONARIO")):
            col_idx["name"] = i
            continue
        if col_idx["registration"] is None and any(
            x in h for x in ("MATRICULA", "MATRÍCULA", "REGISTRO", "RE", "CRACHA")
        ):
            col_idx["registration"] = i
            continue
        if col_idx["role"] is None and ("FUNCAO" in h or "CARGO" in h):
            col_idx["role"] = i
            continue
        if col_idx["admission"] is None and ("ADMISSAO" in h or "ADMISSÃO" in _strip_accents(str(raw)).upper()):
            col_idx["admission"] = i
            continue
        if _is_period_column(str(raw)):
            col_idx["periods"].append(i)
    col_idx["periods"].sort()
    return col_idx


def find_header_row(df: pd.DataFrame) -> int:
    for i in range(min(35, len(df))):
        row = [_norm_header(x) for x in df.iloc[i].tolist()]
        joined = " | ".join(row)
        if "COLABORADOR" in joined and ("FUNCAO" in joined or "CARGO" in joined):
            return i
    return -1


def read_workbook_to_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    bio = io.BytesIO(file_bytes)
    fn = (filename or "upload.xls").lower()
    if fn.endswith(".xls") and not fn.endswith(".xlsx"):
        return pd.read_excel(bio, engine="xlrd", header=None)
    return pd.read_excel(bio, engine="openpyxl", header=None)


def pick_control_date(period_dates: List[date], ref: date) -> Optional[date]:
    """
    Escolhe a data «em foco» entre as colunas de período.
    Prioriza a menor data ainda não vencida (>= ref); se todas passaram, usa a maior (mais atrasada).
    """
    dates = sorted({d for d in period_dates if d})
    if not dates:
        return None
    futureish = [d for d in dates if d >= ref]
    if futureish:
        return min(futureish)
    return max(dates)


def acquisition_for_interpretation(sheet_date: date, interpretation: str) -> date:
    """
    interpretation:
      - acquisition_end: grava fim do período aquisitivo como está na planilha.
      - concessive_deadline: data na planilha é o prazo concessivo (término para gozar);
        o motor usa acquisition_period_end + 365 → gravamos sheet_date - 365 dias.
    """
    if interpretation == "concessive_deadline":
        return sheet_date - timedelta(days=365)
    return sheet_date


def find_employee_by_registration(session: Session, reg: str) -> Optional[models.Employee]:
    r = (reg or "").strip()
    if not r:
        return None
    return session.exec(
        select(models.Employee).where(
            col(models.Employee.registration_id) == r,
            col(models.Employee.status) == "active",
        )
    ).first()


def find_employee_by_name(session: Session, name_key: str) -> List[models.Employee]:
    nk = _norm_name_key(name_key)
    if not nk:
        return []
    up = nk.upper()
    return list(
        session.exec(
            select(models.Employee).where(
                col(models.Employee.status) == "active",
                col(models.Employee.name) == up,
            )
        ).all()
    )


def import_vacation_control_workbook(
    session: Session,
    *,
    file_bytes: bytes,
    filename: str,
    interpretation: str = "acquisition_end",
    update_admission: bool = True,
) -> Dict[str, Any]:
    """
    interpretation:
      - acquisition_end: datas nas colunas de período = fim do período aquisitivo (comum em controles internos).
      - concessive_deadline: datas = último dia do período concessivo para gozar as férias.
    """
    if interpretation not in ("acquisition_end", "concessive_deadline"):
        interpretation = "acquisition_end"

    df = read_workbook_to_dataframe(file_bytes, filename)
    if df.empty:
        return {"ok": False, "error": "Planilha vazia."}

    hdr = find_header_row(df)
    if hdr < 0:
        return {
            "ok": False,
            "error": "Cabeçalho não encontrado. Inclua colunas COLABORADOR e FUNÇÃO (linha de títulos nas primeiras 35 linhas).",
        }

    headers = [df.iloc[hdr, j] for j in range(len(df.columns))]
    cmap = _classify_columns(headers)
    if cmap["name"] is None:
        return {"ok": False, "error": "Coluna COLABORADOR (ou NOME) não encontrada."}

    ref = date.today()
    updated_profiles = 0
    updated_admissions = 0
    skipped_no_dates = 0
    unmatched: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    row_errors: List[Dict[str, Any]] = []

    data_rows = df.iloc[hdr + 1 :]
    for offset, (_, row) in enumerate(data_rows.iterrows()):
        excel_row = hdr + 2 + offset
        name_raw = row.iloc[cmap["name"]] if cmap["name"] < len(row) else None
        name_key = _norm_name_key(str(name_raw) if name_raw is not None else "")
        if not name_key or name_key in ("NAN", "NONE"):
            continue

        emp: Optional[models.Employee] = None
        if cmap["registration"] is not None and cmap["registration"] < len(row):
            reg_val = row.iloc[cmap["registration"]]
            if reg_val is not None and not (isinstance(reg_val, float) and pd.isna(reg_val)):
                if isinstance(reg_val, float) and reg_val == int(reg_val):
                    reg_s = str(int(reg_val))
                else:
                    reg_s = str(reg_val).strip()
                if reg_s and reg_s.lower() != "nan":
                    emp = find_employee_by_registration(session, reg_s)

        if not emp:
            hits = find_employee_by_name(session, name_key)
            if len(hits) == 1:
                emp = hits[0]
            elif len(hits) > 1:
                ambiguous.append(
                    {
                        "excel_row": excel_row,
                        "name": name_key,
                        "employee_ids": [e.id for e in hits],
                    }
                )
                continue
            else:
                unmatched.append({"excel_row": excel_row, "name": name_key})
                continue

        period_dates: List[date] = []
        for pi in cmap["periods"]:
            if pi >= len(row):
                continue
            d = parse_cell_date(row.iloc[pi])
            if d:
                period_dates.append(d)

        sheet_control = pick_control_date(period_dates, ref)
        if not sheet_control:
            skipped_no_dates += 1
            continue

        try:
            acq_end = acquisition_for_interpretation(sheet_control, interpretation)
        except Exception as exc:
            row_errors.append({"excel_row": excel_row, "employee_id": emp.id, "error": str(exc)})
            continue

        prof = session.exec(
            select(models.EmployeeVacationProfile).where(
                models.EmployeeVacationProfile.employee_id == emp.id
            )
        ).first()
        prev_notes = (prof.notes if prof else None) or ""
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        extra = f"\n[import planilha {stamp}] período ref. planilha {sheet_control.isoformat()} ({interpretation})."
        merged_notes = (prev_notes + extra).strip()[-2000:]

        upsert_profile(
            session,
            emp.id,
            {
                "acquisition_period_end": acq_end.isoformat(),
                "notes": merged_notes,
            },
        )
        updated_profiles += 1

        if update_admission and cmap["admission"] is not None and cmap["admission"] < len(row):
            adm = parse_cell_date(row.iloc[cmap["admission"]])
            if adm:
                emp_reload = session.get(models.Employee, emp.id)
                if emp_reload:
                    emp_reload.admission_date = datetime.combine(adm, datetime.min.time())
                    session.add(emp_reload)
                    session.commit()
                    session.refresh(emp_reload)
                    updated_admissions += 1

    return {
        "ok": True,
        "filename": filename,
        "interpretation": interpretation,
        "header_row_0based": hdr,
        "updated_profiles": updated_profiles,
        "updated_admissions": updated_admissions,
        "skipped_no_period_dates": skipped_no_dates,
        "unmatched_rows": unmatched,
        "ambiguous_name_rows": ambiguous,
        "row_errors": row_errors,
    }
