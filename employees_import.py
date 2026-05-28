"""
Utilitários para importação em massa de colaboradores (modelo Excel e exclusão por matrícula).
"""
from __future__ import annotations

import io
import re
import unicodedata
from typing import List, Optional, Tuple

import pandas as pd
from sqlmodel import Session, select

import models

# Matrículas dos cadastros importados incorretamente (lista operacional conhecida).
DEFAULT_WRONG_IMPORT_REGISTRATIONS: List[str] = (
    ["ESP-999", "ESP-777", "ESP-900"]
    + [f"{i}.0" for i in range(1, 37)]
)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.strip().lower()


def pick_column(columns, *candidates):
    normalized = {normalize_text(col): col for col in columns}
    for candidate in candidates:
        key = normalize_text(candidate)
        if key in normalized:
            return normalized[key]
    candidate_keys = [normalize_text(c) for c in candidates]
    for norm_col, original_col in normalized.items():
        compact_col = norm_col.replace(" ", "").replace(".", "")
        for ck in candidate_keys:
            compact_ck = ck.replace(" ", "").replace(".", "")
            if compact_ck and (compact_ck in compact_col or compact_col in compact_ck):
                return original_col
    return None


def _excel_engine(filename: str) -> Optional[str]:
    name = (filename or "").lower()
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        return "xlrd"
    return None


def _read_excel_bytes(content: bytes, filename: str = "", **kwargs) -> pd.DataFrame:
    bio = io.BytesIO(content)
    engine = _excel_engine(filename)
    if engine:
        return pd.read_excel(bio, engine=engine, **kwargs)
    return pd.read_excel(bio, **kwargs)


def _excel_sheet_names(content: bytes, filename: str = "") -> List[str]:
    bio = io.BytesIO(content)
    engine = _excel_engine(filename)
    if engine:
        return list(pd.ExcelFile(bio, engine=engine).sheet_names)
    return list(pd.ExcelFile(bio).sheet_names)


def _detect_fechamento_de_ponto(content: bytes, filename: str) -> bool:
    name = normalize_text(filename)
    if "fechamento" in name and "ponto" in name:
        return True
    try:
        for sheet in _excel_sheet_names(content, filename)[:4]:
            df = _read_excel_bytes(content, filename, sheet_name=sheet, header=None, nrows=12)
            blob = normalize_text(" ".join(str(v) for v in df.values.flatten() if pd.notna(v)))
            if "fechamento de ponto" in blob or "fechamento de ponto e comiss" in blob:
                return True
    except Exception:
        pass
    return False


def _format_registration_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value)}.0"
        return str(value).strip()
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return ""
    if re.fullmatch(r"\d+", s):
        return f"{s}.0"
    return s


def registration_lookup_variants(reg_id: str) -> List[str]:
    """Variantes para buscar matrícula no banco (ex.: 1 ↔ 1.0)."""
    reg_id = (reg_id or "").strip()
    if not reg_id:
        return []
    variants = [reg_id]
    try:
        f = float(reg_id.replace(",", "."))
        if f == int(f):
            n = int(f)
            variants.extend([f"{n}.0", str(n)])
    except ValueError:
        pass
    out: List[str] = []
    seen = set()
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def registrations_from_excel(content: bytes, filename: str = "") -> List[str]:
    """Extrai matrículas únicas de planilha .xlsx/.xls (aba Excluir_exemplo ou coluna Matrícula/Registration)."""
    if _detect_fechamento_de_ponto(content, filename):
        raise ValueError(
            "Este arquivo é Fechamento de Ponto (faltas/comissões), não lista de matrículas. "
            "Baixe a planilha 'excluir_colaboradores_lista.xlsx' no menu Excluir por planilha, "
            "ou use a aba Excluir_exemplo do modelo de colaboradores."
        )

    sheet_names = _excel_sheet_names(content, filename) or [0]
    target_sheet = sheet_names[0]
    for s in sheet_names:
        ns = normalize_text(s)
        if ns in ("excluir_exemplo", "excluir", "exclusao", "matriculas", "matrículas"):
            target_sheet = s
            break

    df_temp = _read_excel_bytes(content, filename, sheet_name=target_sheet, header=None, nrows=15)
    header_row = 0
    expected_headers = {
        "matricula",
        "matrícula",
        "registration",
        "registration id",
        "registro",
        "matriculas",
    }
    for idx, row in df_temp.iterrows():
        row_values = {normalize_text(v) for v in row.values if pd.notna(v)}
        if row_values & expected_headers:
            header_row = idx
            break

    df = _read_excel_bytes(content, filename, sheet_name=target_sheet, header=header_row)
    df.columns = df.columns.astype(str).str.strip()

    col_registration = pick_column(
        df.columns,
        "Matrícula",
        "Matricula",
        "Registration",
        "Registration ID",
        "Registro",
        "Registro ID",
        "Nº",
        "Nº.",
        "No",
        "Numero",
        "Número",
    )

    if not col_registration and len(df.columns) == 1:
        col_registration = df.columns[0]

    if not col_registration:
        for c in df.columns:
            sample = df[c].dropna().head(20).tolist()
            if not sample:
                continue
            hits = sum(
                1
                for v in sample
                if _format_registration_cell(v)
                and normalize_text(_format_registration_cell(v)) not in expected_headers
            )
            if hits >= max(2, len(sample) // 2):
                col_registration = c
                break

    if not col_registration:
        raise ValueError(
            "Coluna de matrícula não encontrada. Use um .xlsx com cabeçalho "
            "'Registration' ou 'Matrícula' (uma matrícula por linha). "
            "Não use Fechamento de Ponto — baixe 'excluir_colaboradores_lista.xlsx' na tela."
        )

    seen = set()
    regs: List[str] = []
    for _, row in df.iterrows():
        reg_id = _format_registration_cell(row.get(col_registration, ""))
        if not reg_id:
            continue
        key = normalize_text(reg_id)
        if key in expected_headers:
            continue
        if reg_id in seen:
            continue
        seen.add(reg_id)
        regs.append(reg_id)
    return regs


def delete_employee_cascade(session: Session, emp_id: int) -> None:
    """Remove colaborador e registros dependentes (mesma regra de /employees/{id}/status delete)."""
    from sqlmodel import delete as sql_delete

    stmt = select(models.Event).where(models.Event.employee_id == emp_id)
    for event in session.exec(stmt).all():
        event.employee_id = None
        session.add(event)

    session.exec(sql_delete(models.GameXPTransaction).where(models.GameXPTransaction.employee_id == emp_id))
    session.exec(sql_delete(models.XPLedger).where(models.XPLedger.employee_id == emp_id))
    session.exec(sql_delete(models.EmployeeAchievement).where(models.EmployeeAchievement.employee_id == emp_id))
    session.exec(sql_delete(models.EmployeeRoutine).where(models.EmployeeRoutine.employee_id == emp_id))
    session.exec(sql_delete(models.EmployeeAllocation).where(models.EmployeeAllocation.employee_id == emp_id))

    for route in session.exec(select(models.Route).where(models.Route.employee_id == emp_id)).all():
        session.delete(route)
    for cl in session.exec(
        select(models.TranspalletChecklist).where(models.TranspalletChecklist.employee_id == emp_id)
    ).all():
        session.delete(cl)
    for ticket in session.exec(
        select(models.EquipmentTicket).where(models.EquipmentTicket.employee_id == emp_id)
    ).all():
        session.delete(ticket)

    session.exec(sql_delete(models.AbsenceAlertLog).where(models.AbsenceAlertLog.employee_id == emp_id))
    session.exec(sql_delete(models.PalletCount).where(models.PalletCount.employee_id == emp_id))
    session.exec(
        sql_delete(models.PalletMaintenanceTicket).where(
            models.PalletMaintenanceTicket.employee_id == emp_id
        )
    )
    session.exec(
        sql_delete(models.LeaderTaskResponse).where(models.LeaderTaskResponse.employee_id == emp_id)
    )

    for r in session.exec(select(models.Employee).where(models.Employee.replaced_by == emp_id)).all():
        r.replaced_by = None
        session.add(r)

    session.exec(
        sql_delete(models.SubstitutionHistory).where(
            models.SubstitutionHistory.original_employee_id == emp_id
        )
    )
    session.exec(
        sql_delete(models.SubstitutionHistory).where(models.SubstitutionHistory.new_employee_id == emp_id)
    )

    user_linked = session.exec(select(models.User).where(models.User.employee_id == emp_id)).first()
    if user_linked:
        user_linked.employee_id = None
        session.add(user_linked)

    emp = session.get(models.Employee, emp_id)
    if emp:
        session.delete(emp)


def _find_employee_by_registration(session: Session, reg_id: str) -> Optional[models.Employee]:
    for variant in registration_lookup_variants(reg_id):
        emp = session.exec(
            select(models.Employee).where(models.Employee.registration_id == variant)
        ).first()
        if emp:
            return emp
    return None


def bulk_delete_by_registrations(
    session: Session, registrations: List[str]
) -> Tuple[int, int, List[str]]:
    """
    Exclui colaboradores pelas matrículas informadas.
    Retorna (excluídos, não encontrados, matrículas não encontradas).
    """
    deleted = 0
    not_found: List[str] = []
    for reg_id in registrations:
        emp = _find_employee_by_registration(session, reg_id)
        if not emp:
            not_found.append(reg_id)
            continue
        delete_employee_cascade(session, emp.id)
        deleted += 1
    session.commit()
    return deleted, len(not_found), not_found


def build_bulk_delete_list_bytes(registrations: Optional[List[str]] = None) -> bytes:
    """Planilha só com coluna Registration para exclusão em lote."""
    regs = registrations if registrations is not None else list(DEFAULT_WRONG_IMPORT_REGISTRATIONS)
    df = pd.DataFrame({"Registration": regs})
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl", sheet_name="Excluir")
    buf.seek(0)
    return buf.read()


def build_import_template_bytes() -> bytes:
    """Gera planilha modelo para cadastro em massa."""
    data = pd.DataFrame(
        [
            {
                "Name": "JOÃO DA SILVA",
                "Registration": "12345",
                "Role": "MOTORISTA",
                "Shift": "Manhã",
                "CostCenter": "Souza Pinto",
                "Data Admissão": "01/03/2024",
                "Data Nascimento": "15/07/1990",
            },
            {
                "Name": "MARIA SANTOS",
                "Registration": "12346",
                "Role": "AJUDANTE",
                "Shift": "Tarde",
                "CostCenter": "Exemplar",
                "Data Admissão": "10/01/2025",
                "Data Nascimento": "",
            },
        ]
    )
    instructions = pd.DataFrame(
        {
            "Campo": [
                "Name (obrigatório)",
                "Registration (obrigatório)",
                "Role (obrigatório)",
                "Shift",
                "CostCenter",
                "Data Admissão",
                "Data Nascimento",
                "",
                "Turno (Shift)",
                "Empresa (CostCenter)",
                "Importação",
                "Exclusão em lote",
            ],
            "Descrição": [
                "Nome completo do colaborador (será gravado em maiúsculas).",
                "Matrícula única no sistema. Não repita na mesma planilha.",
                "Cargo/função (ex.: MOTORISTA, AJUDANTE). Cadastre funções em /funcoes se precisar.",
                "Manhã, Tarde ou Noite. Padrão: Manhã.",
                "Empresa/centro de custo: Souza Pinto, Exemplar, Geral, Outubro 2020, etc.",
                "Opcional. Formato dd/mm/aaaa.",
                "Opcional. Formato dd/mm/aaaa.",
                "",
                "Valores aceitos: Manhã | Tarde | Noite",
                "Use o nome exato da empresa como aparece nos cards da tela Colaboradores.",
                "Na tela Colaboradores → Importar → Planilha Excel. Só insere matrículas novas.",
                "Importar → Excluir por planilha. Use excluir_colaboradores_lista.xlsx (NÃO Fechamento de Ponto).",
            ],
        }
    )
    delete_example = pd.DataFrame({"Registration": DEFAULT_WRONG_IMPORT_REGISTRATIONS[:5]})

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name="Colaboradores", index=False)
        instructions.to_excel(writer, sheet_name="Instruções", index=False)
        delete_example.to_excel(writer, sheet_name="Excluir_exemplo", index=False)
    buf.seek(0)
    return buf.read()
