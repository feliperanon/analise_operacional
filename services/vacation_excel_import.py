"""
Importação de planilhas de férias (Excel .xls/.xlsx).

Dois formatos (detecção automática pela linha de títulos nas primeiras 35 linhas):

1) Controle de vencimento: COLABORADOR, FUNÇÃO e colunas de período com datas
   (fim aquisitivo ou prazo concessivo). Atualiza ``EmployeeVacationProfile``.

2) Programação de gozo: COLABORADOR (e opcionalmente matrícula) com colunas de
   início e fim das férias (ex.: «Férias Início» / «Férias Fim»). Cria registros
   em ``VacationScheduleEntry`` (status aprovado, fonte planilha).

Opcional no formato (1): atualiza ``Employee.admission_date`` a partir da coluna
de admissão.
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
from services.vacation_planning_service import save_schedule_entry, simulate, upsert_profile


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


def _is_programmed_start_header(raw: Any) -> bool:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    hn = _norm_header(str(raw))
    if "FERIAS" not in hn and "FERIA" not in hn:
        return False
    return "INICIO" in hn or "COMECO" in hn


def _is_programmed_end_header(raw: Any) -> bool:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    hn = _norm_header(str(raw))
    if "INICIO" in hn or "COMECO" in hn:
        return False
    if "FERIAS" not in hn and "FERIA" not in hn:
        return False
    return "FIM" in hn


def _classify_programmed_columns(headers: List[Any]) -> Dict[str, Any]:
    col_idx: Dict[str, Any] = {"name": None, "registration": None, "start": None, "end": None}
    for i, raw in enumerate(headers):
        h = _norm_header(raw)
        if not h:
            continue
        if col_idx["name"] is None and (
            "COLABORADOR" in h or h == "NOME" or h.startswith("FUNCIONARIO")
        ):
            col_idx["name"] = i
            continue
        if col_idx["registration"] is None and any(
            x in h for x in ("MATRICULA", "MATRÍCULA", "REGISTRO", "RE", "CRACHA")
        ):
            col_idx["registration"] = i
            continue
        if _is_programmed_start_header(raw):
            if col_idx["start"] is None:
                col_idx["start"] = i
            continue
        if _is_programmed_end_header(raw):
            if col_idx["end"] is None:
                col_idx["end"] = i
            continue
    return col_idx


def find_programmed_header_row(df: pd.DataFrame) -> int:
    """Cabeçalho com colaborador + colunas de início e fim das férias (gozo)."""
    for i in range(min(35, len(df))):
        headers = [df.iloc[i, j] for j in range(len(df.columns))]
        cmap = _classify_programmed_columns(headers)
        if cmap["name"] is None or cmap["start"] is None or cmap["end"] is None:
            continue
        if cmap["start"] == cmap["end"]:
            continue
        return int(i)
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


def import_vacation_programmed_workbook(
    session: Session,
    *,
    df: pd.DataFrame,
    header_row: int,
    filename: str,
    approved_by_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Grava janelas de gozo (início/fim) como ``VacationScheduleEntry`` aprovadas.
    """
    headers = [df.iloc[header_row, j] for j in range(len(df.columns))]
    cmap = _classify_programmed_columns(headers)
    if cmap["name"] is None or cmap["start"] is None or cmap["end"] is None:
        return {
            "ok": False,
            "error": "Colunas de programação incompletas (COLABORADOR, início e fim das férias).",
        }

    created = 0
    skipped_invalid = 0
    skipped_empty_period = 0
    unmatched: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    row_errors: List[Dict[str, Any]] = []

    data_rows = df.iloc[header_row + 1 :]
    for offset, (_, row) in enumerate(data_rows.iterrows()):
        excel_row = header_row + 2 + offset
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

        if cmap["start"] >= len(row) or cmap["end"] >= len(row):
            skipped_invalid += 1
            continue
        s = parse_cell_date(row.iloc[cmap["start"]])
        e = parse_cell_date(row.iloc[cmap["end"]])
        if not s or not e:
            skipped_empty_period += 1
            continue
        if s > e:
            row_errors.append(
                {
                    "excel_row": excel_row,
                    "employee_id": emp.id,
                    "error": "Data de início posterior à data de fim.",
                }
            )
            continue

        sim = simulate(
            session,
            employee_id=emp.id,
            start=s,
            end=e,
            cost_center=None,
        )
        if not sim or not sim.get("ok"):
            row_errors.append(
                {
                    "excel_row": excel_row,
                    "employee_id": emp.id,
                    "error": (sim or {}).get("error") or "Falha na simulação do período.",
                }
            )
            continue

        conflicts = {
            "alerts": sim.get("alerts") if isinstance(sim, dict) else [],
            "blocks": sim.get("blocks") if isinstance(sim, dict) else [],
            "recommendation": sim.get("recommendation") if isinstance(sim, dict) else None,
            "recommendation_label": sim.get("recommendation_label") if isinstance(sim, dict) else None,
            "recommendation_explanation": sim.get("recommendation_explanation")
            if isinstance(sim, dict)
            else None,
            "scores": sim.get("scores") if isinstance(sim, dict) else None,
            "import_workbook": True,
        }
        conflicts["employee_vacation_sync"] = {
            "requested": False,
            "applied": False,
            "message": "Importação em lote não sincroniza vacation_start/end no cadastro.",
        }

        save_schedule_entry(
            session,
            employee_id=emp.id,
            start=s,
            end=e,
            status="approved",
            source="planilha",
            approved_by_user_id=approved_by_user_id,
            decision_reason="Importação de planilha (férias programadas / gozo).",
            leadership_notes=None,
            conflicts=conflicts,
            priority_score=(sim.get("scores") or {}).get("prioridade_composta")
            if isinstance(sim, dict)
            else None,
            employee_vacation_synced=False,
        )
        created += 1

    return {
        "ok": True,
        "workbook_kind": "programmed",
        "filename": filename,
        "header_row_0based": header_row,
        "created_schedule_entries": created,
        "skipped_invalid_dates": skipped_invalid,
        "skipped_empty_period": skipped_empty_period,
        "unmatched_rows": unmatched,
        "ambiguous_name_rows": ambiguous,
        "row_errors": row_errors,
    }


def import_vacation_workbook(
    session: Session,
    *,
    file_bytes: bytes,
    filename: str,
    interpretation: str = "acquisition_end",
    update_admission: bool = True,
    approved_by_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Lê a planilha uma vez e encaminha ao importador adequado."""
    df = read_workbook_to_dataframe(file_bytes, filename)
    if df.empty:
        return {"ok": False, "error": "Planilha vazia."}
    programmed_hdr = find_programmed_header_row(df)
    if programmed_hdr >= 0:
        return import_vacation_programmed_workbook(
            session,
            df=df,
            header_row=programmed_hdr,
            filename=filename,
            approved_by_user_id=approved_by_user_id,
        )
    return import_vacation_control_workbook(
        session,
        file_bytes=file_bytes,
        filename=filename,
        interpretation=interpretation,
        update_admission=update_admission,
        _dataframe=df,
    )


def import_vacation_control_workbook(
    session: Session,
    *,
    file_bytes: bytes = b"",
    filename: str = "upload.xls",
    interpretation: str = "acquisition_end",
    update_admission: bool = True,
    _dataframe: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    interpretation:
      - acquisition_end: datas nas colunas de período = fim do período aquisitivo (comum em controles internos).
      - concessive_deadline: datas = último dia do período concessivo para gozar as férias.
    """
    if interpretation not in ("acquisition_end", "concessive_deadline"):
        interpretation = "acquisition_end"

    if _dataframe is not None:
        df = _dataframe
    else:
        df = read_workbook_to_dataframe(file_bytes, filename)
    if df.empty:
        return {"ok": False, "error": "Planilha vazia."}

    hdr = find_header_row(df)
    if hdr < 0:
        return {
            "ok": False,
            "error": (
                "Cabeçalho não reconhecido. Use (1) COLABORADOR e FUNÇÃO com colunas de período "
                "(controle de vencimento), ou (2) COLABORADOR com colunas de início e fim das férias "
                "(programação de gozo), na linha de títulos nas primeiras 35 linhas."
            ),
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
        "workbook_kind": "control",
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
