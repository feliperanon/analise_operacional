"""
Utilitários para importação em massa de colaboradores (modelo Excel e exclusão por matrícula).
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pandas as pd
from fastapi import Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlmodel import Session, select

import models
from employees_seller_code import normalize_seller_code

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


def _registration_already_seen(seen: set, reg_id: str) -> bool:
    """Evita duplicata na planilha quando a matrícula aparece como 210 e 210.0."""
    reg_id = _format_registration_cell(reg_id) or str(reg_id or "").strip()
    if not reg_id:
        return True
    keys = registration_lookup_variants(reg_id) or [reg_id]
    if any(k in seen for k in keys):
        return True
    for k in keys:
        seen.add(k)
    return False


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


# Cabeçalhos do modelo (mesma ordem do formulário "Novo Colaborador")
EMPLOYEE_IMPORT_COLUMNS = [
    "Nome Completo",
    "Matrícula",
    "Telefone",
    "Código do Vendedor",
    "Cargo",
    "Empresa",
    "Turno Operacional",
    "Data Admissão",
    "Aniversário",
]


def _normalize_shift(value) -> str:
    shift_raw = str(value or "Manhã").strip()
    if not shift_raw or shift_raw.lower() == "nan":
        shift_raw = "Manhã"
    shift_clean = shift_raw.strip().title()
    if "Manha" in shift_clean or "Manhã" in shift_clean:
        return "Manhã"
    if "Tarde" in shift_clean:
        return "Tarde"
    if "Noite" in shift_clean:
        return "Noite"
    return shift_clean


def _schedule_for_shift(shift_val: str) -> Optional[str]:
    s_lower = (shift_val or "").lower()
    if "manhã" in s_lower or "manha" in s_lower:
        return "05:00 - 13:20"
    if "tarde" in s_lower:
        return "12:00 - 20:20"
    if "noite" in s_lower:
        return "18:00 - 06:00"
    return None


def _parse_excel_date(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
        if pd.isna(dt):
            return None
        return dt.to_pydatetime()
    except Exception:
        return None


def _resolve_admission_and_birthday(admission_raw, birthday_raw):
    """
    Interpreta admissão e nascimento da planilha.

    Planilhas legadas (ex.: Souza Pinto) costumam trazer as colunas trocadas
    ou com rótulos invertidos. Se o nascimento ficar depois da admissão, inverte.
    """
    admission = _parse_excel_date(admission_raw)
    birthday = _parse_excel_date(birthday_raw)
    if admission and birthday and birthday > admission:
        admission, birthday = birthday, admission
    return admission, birthday


def build_import_template_bytes() -> bytes:
    """Gera planilha modelo alinhada ao formulário Novo Colaborador."""
    data = pd.DataFrame(
        [
            {
                "Nome Completo": "JOÃO DA SILVA",
                "Matrícula": "12345",
                "Telefone": "(31) 99940-9789",
                "Código do Vendedor": "110",
                "Cargo": "MOTORISTA",
                "Empresa": "Souza Pinto",
                "Turno Operacional": "Manhã",
                "Data Admissão": "01/03/2024",
                "Aniversário": "15/07/1990",
            },
            {
                "Nome Completo": "MARIA SANTOS",
                "Matrícula": "12346",
                "Telefone": "31999887766",
                "Código do Vendedor": "201",
                "Cargo": "AJUDANTE",
                "Empresa": "Exemplar",
                "Turno Operacional": "Tarde",
                "Data Admissão": "10/01/2025",
                "Aniversário": "",
            },
        ]
    )
    instructions = pd.DataFrame(
        {
            "Campo": [
                "Nome Completo (obrigatório)",
                "Matrícula (obrigatório)",
                "Telefone",
                "Código do Vendedor",
                "Cargo (obrigatório)",
                "Empresa",
                "Turno Operacional",
                "Data Admissão",
                "Aniversário",
                "",
                "Empresa",
                "Turno Operacional",
                "Importação",
                "Exclusão em lote",
            ],
            "Descrição": [
                "Igual ao formulário na tela. Nome será gravado em maiúsculas.",
                "Matrícula única. Não repetir na planilha.",
                "DDD + número. Ex.: (31) 99940-9789 ou 31999409789. Opcional.",
                "Para importação de devoluções. Ex.: 110, 201. Opcional.",
                "Ex.: MOTORISTA, AJUDANTE. Cadastre em /funcoes se precisar.",
                "Souza Pinto, Exemplar, Geral, Outubro 2020, etc. Padrão: Souza Pinto.",
                "Manhã, Tarde ou Noite. Padrão: Manhã.",
                "Formato dd/mm/aaaa. Opcional.",
                "Data de nascimento, dd/mm/aaaa. Opcional.",
                "",
                "Use o nome exato como nos cards da tela Colaboradores.",
                "Valores aceitos: Manhã | Tarde | Noite",
                "Colaboradores → Importar → Planilha Excel. Só matrículas novas.",
                "Menu Excluir por planilha — não use Fechamento de Ponto.",
            ],
        }
    )
    delete_example = pd.DataFrame({"Matrícula": DEFAULT_WRONG_IMPORT_REGISTRATIONS[:5]})

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name="Colaboradores", index=False)
        instructions.to_excel(writer, sheet_name="Instruções", index=False)
        delete_example.to_excel(writer, sheet_name="Excluir_exemplo", index=False)
    buf.seek(0)
    return buf.read()


def _xlsx_attachment_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _serve_template_file(static_rel: str, builder, filename: str) -> Response:
    path = Path("static/templates") / static_rel
    if path.is_file():
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
            headers={"Cache-Control": "no-store"},
        )
    return _xlsx_attachment_response(builder(), filename)


@dataclass
class EmployeeImportResult:
    """Resultado da importação: novos criados e códigos de vendedor atualizados."""

    created: int = 0
    seller_updated: int = 0


def import_employees_from_excel(
    session: Session,
    content: bytes,
    normalize_phone_br,
) -> EmployeeImportResult:
    """
    Importa colaboradores da aba Colaboradores (cabeçalhos do formulário Novo Colaborador).

    - Cria matrículas novas.
    - Para matrículas já existentes, atualiza o `seller_code` (Código do Vendedor)
      quando a planilha trouxer um código diferente do atual.

    Retorna EmployeeImportResult(created, seller_updated).
    """
    excel = pd.ExcelFile(io.BytesIO(content))
    sheet_names = excel.sheet_names or [0]
    target_sheet = sheet_names[0]
    for s in sheet_names:
        ns = normalize_text(s)
        if ns in ("colaboradores", "souza pinto"):
            target_sheet = s
            break

    df_temp = pd.read_excel(io.BytesIO(content), sheet_name=target_sheet, header=None, nrows=12)
    header_row = 0
    expected_headers = {
        "matricula", "matrícula", "registration", "nome completo", "nome", "colaborador",
        "telefone", "cargo", "empresa", "turno operacional", "turno",
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
        col_registration = pick_column_contains(df.columns, "matricula", "matrícula")
    if not col_registration:
        col_registration = pick_column_contains(df.columns, "matricula", "matrícula", "registro")

    col_name = pick_column(
        df.columns,
        "Nome Completo", "Colaborador", "Nome Funcionário", "Nome Funcionario", "Nome", "Name",
    )
    col_phone = pick_column(df.columns, "Telefone", "Phone", "Celular", "Fone")
    col_seller = pick_column(
        df.columns, "Código do Vendedor", "Codigo do Vendedor", "Seller Code", "Codigo Vendedor",
    )
    col_role = pick_column(df.columns, "Cargo", "Nome Cargo", "Função", "Funcao", "Role")
    col_cost_center = pick_column(df.columns, "Empresa", "Centro de Custo", "CostCenter", "Cost Center")
    col_shift = pick_column(df.columns, "Turno Operacional", "Turno", "Shift")
    col_admission = pick_column(
        df.columns,
        "Data Admissão",
        "Admissão",
        "Admissao",
        "Adminissão",
        "Adminissao",
        "Dt.Admissão",
        "Dt.Admissao",
        "Dt Admissão",
        "Dt Admissao",
    )
    col_birthday = pick_column(
        df.columns,
        "Aniversário",
        "Aniversario",
        "Data Nascimento",
        "Nascimento",
        "Data de Nascimento",
        "Dt.Nascimento",
        "Dt Nascimento",
        "Dt. Nascimento",
    )
    if col_admission and col_birthday and col_admission == col_birthday:
        col_birthday = None

    if not col_registration:
        raise ValueError(
            "Coluna Matrícula não encontrada. Use a aba Colaboradores do modelo baixado em Importar."
        )

    result = EmployeeImportResult()
    seen_registration = set()
    default_company = "Souza Pinto"

    for _, row in df.iterrows():
        reg_id = _format_registration_cell(row.get(col_registration, ""))
        if not reg_id:
            continue
        if _registration_already_seen(seen_registration, reg_id):
            continue

        existing = _find_employee_by_registration(session, reg_id)
        if existing:
            if col_seller and pd.notna(row.get(col_seller)):
                new_code = normalize_seller_code(row.get(col_seller))
                current_code = normalize_seller_code(existing.seller_code)
                if new_code and new_code != current_code:
                    existing.seller_code = new_code
                    session.add(existing)
                    result.seller_updated += 1
            continue

        shift_val = _normalize_shift(row.get(col_shift, "Manhã") if col_shift else "Manhã")
        name_raw = (str(row.get(col_name, "Sem Nome")).strip() if col_name else "Sem Nome") or "Sem Nome"

        phone_store = None
        if col_phone and pd.notna(row.get(col_phone)):
            phone_e164, _ = normalize_phone_br(str(row.get(col_phone, "")).strip())
            phone_store = phone_e164[3:] if (phone_e164 and len(phone_e164) >= 13) else None

        seller_code = None
        if col_seller and pd.notna(row.get(col_seller)):
            seller_code = normalize_seller_code(row.get(col_seller))

        cost_center = default_company
        if col_cost_center and pd.notna(row.get(col_cost_center)):
            cc = str(row.get(col_cost_center, "")).strip()
            if cc and cc.lower() != "nan":
                cost_center = cc

        admission_date, birthday = _resolve_admission_and_birthday(
            row.get(col_admission) if col_admission else None,
            row.get(col_birthday) if col_birthday else None,
        )

        emp = models.Employee(
            name=name_raw.upper(),
            registration_id=reg_id.strip(),
            phone=phone_store,
            seller_code=seller_code,
            role=(str(row.get(col_role, "Operador")).strip() or "Operador").upper(),
            work_shift=str(shift_val).strip(),
            cost_center=cost_center,
            admission_date=admission_date,
            birthday=birthday,
            work_schedule=_schedule_for_shift(shift_val),
            status="active",
        )
        session.add(emp)
        result.created += 1

    session.commit()
    return result


def register_download_routes(app, require_login: Callable) -> None:
    """Rotas curtas /download/*.xlsx (sem conflito com /employees/{id})."""

    @app.get("/download/colaboradores-modelo.xlsx", include_in_schema=False)
    async def download_colaboradores_modelo(request: Request):
        require_login(request)
        return _serve_template_file(
            "planilha_colaboradores_modelo.xlsx",
            build_import_template_bytes,
            "planilha_colaboradores_modelo.xlsx",
        )

    @app.get("/download/excluir-colaboradores-lista.xlsx", include_in_schema=False)
    async def download_excluir_colaboradores_lista(request: Request):
        require_login(request)
        return _serve_template_file(
            "excluir_colaboradores_lista.xlsx",
            build_bulk_delete_list_bytes,
            "excluir_colaboradores_lista.xlsx",
        )

    @app.get("/employees/import/template", include_in_schema=False)
    async def employees_import_template_redirect(request: Request):
        return RedirectResponse(url="/download/colaboradores-modelo.xlsx", status_code=307)

    @app.get("/employees/import/template-excluir", include_in_schema=False)
    async def employees_import_template_excluir_redirect(request: Request):
        return RedirectResponse(url="/download/excluir-colaboradores-lista.xlsx", status_code=307)

    @app.get("/employees/template", include_in_schema=False)
    async def employees_template_legacy(request: Request):
        return RedirectResponse(url="/download/colaboradores-modelo.xlsx", status_code=307)

    @app.get("/employees/template/excluir", include_in_schema=False)
    async def employees_template_excluir_legacy(request: Request):
        return RedirectResponse(url="/download/excluir-colaboradores-lista.xlsx", status_code=307)
