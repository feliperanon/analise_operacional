"""
Utilitários para importação em massa de colaboradores (modelo Excel e exclusão por matrícula).
"""
from __future__ import annotations

import io
import unicodedata
from typing import List, Optional, Tuple

import pandas as pd
from sqlmodel import Session, select

import models


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


def registrations_from_excel(content: bytes) -> List[str]:
    """Extrai matrículas únicas de um .xlsx (primeira aba com coluna de matrícula)."""
    excel = pd.ExcelFile(io.BytesIO(content))
    sheet_names = excel.sheet_names or [0]
    target_sheet = sheet_names[0]
    for s in sheet_names:
        if normalize_text(s) == "colaboradores":
            target_sheet = s
            break

    df_temp = pd.read_excel(io.BytesIO(content), sheet_name=target_sheet, header=None, nrows=10)
    header_row = 0
    expected_headers = {
        "matricula", "matrícula", "registration", "registration id", "registro",
    }
    for idx, row in df_temp.iterrows():
        row_values = {normalize_text(v) for v in row.values if pd.notna(v)}
        if row_values & expected_headers:
            header_row = idx
            break

    df = pd.read_excel(io.BytesIO(content), sheet_name=target_sheet, header=header_row)
    df.columns = df.columns.astype(str).str.strip()

    col_registration = pick_column(
        df.columns,
        "Matrícula", "Matricula", "Registration", "Registration ID", "Registro",
    )
    if not col_registration:
        raise ValueError(
            "Coluna de matrícula não encontrada. Use 'Registration' ou 'Matrícula' no cabeçalho."
        )

    seen = set()
    regs: List[str] = []
    for _, row in df.iterrows():
        reg_id = str(row.get(col_registration, "")).strip()
        if not reg_id or reg_id.lower() == "nan":
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
        emp = session.exec(
            select(models.Employee).where(models.Employee.registration_id == reg_id)
        ).first()
        if not emp:
            not_found.append(reg_id)
            continue
        delete_employee_cascade(session, emp.id)
        deleted += 1
    session.commit()
    return deleted, len(not_found), not_found


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
                "Menu Importar → Excluir por planilha. Apenas coluna Registration/Matrícula.",
            ],
        }
    )
    delete_example = pd.DataFrame([{"Registration": "12345"}, {"Registration": "12346"}])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name="Colaboradores", index=False)
        instructions.to_excel(writer, sheet_name="Instruções", index=False)
        delete_example.to_excel(writer, sheet_name="Excluir_exemplo", index=False)
    buf.seek(0)
    return buf.read()
