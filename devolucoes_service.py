# -*- coding: utf-8 -*-
"""
Service Layer para o módulo Devoluções.
Validação, parse, cálculo de campos derivados e persistência.
"""
from __future__ import annotations

import unicodedata
import re
import hashlib
import json
from io import BytesIO
from datetime import datetime, date
from typing import Any, Optional, List, Tuple, Dict
from dataclasses import dataclass, field

from sqlmodel import Session, select
from sqlalchemy import or_, func
import models
from models import (
    Client,
    Employee,
    Devolucao,
    DevolucaoMotivo,
    DevolucaoResponsabilidade,
    DevolucaoImportBatch,
    DevolucaoImportRowError,
    DevolucaoStaging,
    Route,
)

# Constantes de CLUSTER (faixas de valor)
CLUSTER_BOUNDARIES = [
    (0, 50, "0-50"),
    (50, 100, "50-100"),
    (100, 200, "100-200"),
    (200, 300, "200-300"),
    (300, 400, "300-400"),
    (400, 500, "400-500"),
    (500, 600, "500-600"),
    (600, 700, "600-700"),
    (700, 800, "700-800"),
    (800, 900, "800-900"),
    (900, 1000, "900-1.000"),
    (1000, 1100, "1.000-1.100"),
    (1100, 1200, "1.100-1.200"),
]
CLUSTER_ABOVE = "Acima 1.200"

# Sheet name preferido no Excel
DEVOLUCOES_SHEET_NAMES = ["Devoluções", "Devolucoes", "devolucoes", "Sheet1"]


def _norm_text(s: Optional[str]) -> str:
    """Normaliza texto: remove acentos, lowercase, strip."""
    if not s or not str(s).strip():
        return ""
    normalized = unicodedata.normalize("NFD", str(s).strip())
    cleaned = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return cleaned.lower().strip()


def normalize_code(value: Any) -> Optional[str]:
    """
    Normaliza código: trim, remove .0 no final (Excel float), múltiplos espaços.
    Para código puro numérico: também aceita variação só dígitos.
    Ex: 201, 201.0, " 201 ", "110.0" -> "201", "110"
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    s = re.sub(r"\.0+$", "", s)
    s = " ".join(s.split())
    if not s:
        return None
    return s


def normalize_name(value: Any) -> Optional[str]:
    """
    Normaliza nome: remove acentos, lower, trim, múltiplos espaços.
    Usa unicodedata (stdlib), sem libs externas.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    s = " ".join(s.split())
    return _norm_text(s) if s else None


def _is_numeric_value(value: Any) -> bool:
    """Indica se o valor parece numérico (código do Excel)."""
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    s = str(value).strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def parse_valor_pt_br(value: Any) -> float:
    """
    Parse valor em formato pt-BR: vírgula decimal, ponto milhar.
    Ex: "1.115,67" -> 1115.67, "702,77" -> 702.77
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def compute_dia(data_romaneio: datetime) -> int:
    """DIA = dia do mês de DATA ROMANEIO."""
    return data_romaneio.day


def compute_semana(data_romaneio: datetime) -> int:
    """SEMANA = número da semana do ano (ISO week) baseado em DATA ROMANEIO."""
    return data_romaneio.isocalendar()[1]


def compute_acima_300(valor: float) -> str:
    """Se VALOR >= 300 → 'SIM' senão 'NÃO'."""
    return "SIM" if valor >= 300.0 else "NAO"


def compute_cluster(valor: float) -> str:
    """
    Converte VALOR em faixa de cluster:
    Até 50 (0-50), 50-100 (>50-100), 100-200, ..., Acima 1.200
    """
    for lo, hi, label in CLUSTER_BOUNDARIES:
        if lo <= valor < hi:
            return label
    return CLUSTER_ABOVE


def _is_valid_dt(dt: Any) -> bool:
    """Retorna True se dt for datetime válido (não None, não NaT)."""
    if dt is None:
        return False
    try:
        import pandas as pd
        if hasattr(pd, "isna") and pd.isna(dt):
            return False
    except ImportError:
        pass
    return True


def safe_date_str(dt: Any, fmt: str = "%Y-%m-%d") -> str:
    """
    Converte datetime para string de forma segura; nunca lança exceção.
    Retorna dt.strftime(fmt) se for datetime válido, senão retorna "-".
    """
    if not _is_valid_dt(dt):
        return "-"
    if hasattr(dt, "strftime"):
        try:
            return dt.strftime(fmt)
        except (ValueError, TypeError):
            return "-"
    return str(dt) if dt is not None else "-"


def _safe_strftime(dt: Any, fmt: str = "%Y-%m-%d") -> Optional[str]:
    """Converte datetime para string; retorna None se for NaT, None ou inválido (para payloads opcionais)."""
    if not _is_valid_dt(dt):
        return None
    if hasattr(dt, "strftime"):
        try:
            return dt.strftime(fmt)
        except (ValueError, TypeError):
            return None
    return None


def parse_date_dd_mm_yyyy(value: Any) -> Optional[datetime]:
    """
    Parse data dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd, datetime, date ou Timestamp do Excel.
    Detecta NaT explicitamente e retorna None. Nunca retorna NaT.
    """
    if value is None:
        return None
    try:
        import pandas as pd
        if hasattr(pd, "isna") and pd.isna(value):
            return None
    except ImportError:
        pd = None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    if hasattr(value, "to_pydatetime"):
        try:
            import pandas as _pd
            dt = value.to_pydatetime()
            if not isinstance(dt, datetime):
                return None
            if hasattr(_pd, "isna") and _pd.isna(dt):
                return None
            return dt
        except Exception:
            pass
    if isinstance(value, datetime):
        try:
            import pandas as _pd
            if hasattr(_pd, "isna") and _pd.isna(value):
                return None
        except ImportError:
            pass
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)) and value > 0:
        try:
            import pandas as pd
            ts = pd.Timestamp(value)
            if pd.isna(ts):
                return None
            dt = ts.to_pydatetime()
            if not isinstance(dt, datetime):
                return None
            return dt
        except Exception:
            pass
    s = s.split()[0] if " " in s else s
    for sep in ["/", "-", "."]:
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    p0, p1, p2 = int(parts[0]), int(parts[1]), int(parts[2])
                    if p0 > 31 or (len(str(parts[0])) == 4 and p0 >= 1900):
                        y, m, d = p0, p1, p2
                    else:
                        d, m, y = p0, p1, p2
                        if y < 100:
                            y += 2000
                    return datetime(y, m, d)
                except (ValueError, IndexError):
                    pass
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            pass
    return None


@dataclass
class DevolucaoRow:
    """Linha normalizada de devolução (antes de validação)."""
    data_romaneio: Optional[datetime]
    data_entrega: Optional[datetime]
    codigo: Optional[str]
    nome_cliente: Optional[str]
    vendedor: Optional[str]
    motorista: Optional[str]
    valor: float
    motivo: Optional[str]
    observacao: Optional[str]
    responsabilidade: Optional[str]
    ajudante: Optional[str] = None
    row_index: int = 0


@dataclass
class ValidationResult:
    """Resultado da validação de uma linha."""
    valid: bool
    errors: List[Dict[str, Any]] = field(default_factory=list)
    client_id: Optional[int] = None
    vendedor_id: Optional[int] = None
    motorista_id: Optional[int] = None
    ajudante_id: Optional[int] = None
    motivo_id: Optional[int] = None
    responsabilidade_id: Optional[int] = None


def _find_col_map(columns: List[str]) -> Dict[str, str]:
    """Mapeia colunas do Excel para campos canônicos (flexível a espaços/acentos)."""
    cols_str = [str(c).strip() for c in columns if c is not None]
    norm_map = {}
    for c in cols_str:
        n = _norm_text(c)
        if n:
            norm_map[n] = c
    # Também mapear por "contém" para colunas como "DATA ROMANEIO (dd/mm/aaaa)"
    norm_cols = list(norm_map.keys())
    aliases = {
        "data_romaneio": ["data romaneio", "data romaneo", "data_romaneio", "romaneio", "data"],
        "data_entrega": ["data entrega", "data_entrega", "entrega"],
        "codigo": ["codigo", "codigo cliente", "cod", "código"],
        "nome_cliente": ["nome do cliente", "nome cliente", "cliente", "razao social", "nome cliente"],
        "vendedor": [
            "vendedor", "comercia (sv / vd)", "comercia", "sv", "vd",
            "codigo do vendedor", "código do vendedor", "seller_code", "cod vendedor", "cod. vendedor",
        ],
        "motorista": ["motorista"],
        "valor": ["valor", "r$ devolução", "r$ devolucao", "devolucao", "r$ venda bruta"],
        "motivo": ["motivo", "motivos de devolução", "motivos comercial", "motivos cliente", "motivos logistica"],
        "observacao": ["observacao", "observação", "observacão", "obs"],
        "responsabilidade": ["responsabilidade", "setor"],
        "ajudante": ["ajudante"],
    }
    out = {}
    for key, options in aliases.items():
        for opt in options:
            opt_n = _norm_text(opt)
            if opt_n in norm_map:
                out[key] = norm_map[opt_n]
                break
            for nc in norm_cols:
                if opt_n in nc or nc in opt_n:
                    out[key] = norm_map[nc]
                    break
            if key in out:
                break
    return out


def _as_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def parse_excel(
    content: bytes,
    filename: str,
    sheet_names: Optional[List[str]] = None,
) -> Tuple[List[DevolucaoRow], Optional[str]]:
    """
    Parse arquivo Excel (xlsx/xls/xlsm) e retorna linhas normalizadas.
    Retorna (rows, error_message). Se error_message, rows pode estar vazio.
    """
    try:
        import pandas as pd
    except ImportError:
        return [], "Pandas não instalado."

    ext = (filename or "").lower()
    if not ext.endswith((".xlsx", ".xls", ".xlsm")):
        return [], "Formato inválido. Use .xlsx, .xls ou .xlsm."

    engine = "openpyxl" if ext.endswith((".xlsx", ".xlsm")) else "xlrd"
    last_err = None
    required = ["data_romaneio", "data_entrega", "codigo", "vendedor", "motorista", "valor", "motivo", "responsabilidade"]

    def _try_read(header_row: int = 0, sheet=0):
        try:
            return pd.read_excel(BytesIO(content), engine=engine, header=header_row, sheet_name=sheet)
        except Exception:
            return None

    def _find_header_row(sheet) -> int:
        """Encontra a linha que contém os cabeçalhos (scan nas primeiras 20 linhas)."""
        try:
            df_raw = pd.read_excel(BytesIO(content), engine=engine, header=None, sheet_name=sheet)
            if df_raw is None or df_raw.empty:
                return 0
            best_row, best_score = 0, 0
            for row_idx in range(min(20, len(df_raw))):
                row_vals = df_raw.iloc[row_idx].tolist()
                cols_str = [str(v).strip() for v in row_vals if v is not None and str(v).strip() and str(v).lower() not in ("nan", "")]
                if not cols_str:
                    continue
                col_map = _find_col_map(cols_str)
                score = sum(1 for k in required if k in col_map)
                if score > best_score:
                    best_score = score
                    best_row = row_idx
            return best_row
        except Exception:
            return 0

    sheets_to_try = list(sheet_names or DEVOLUCOES_SHEET_NAMES) + [0]
    df, raw_cols, col_map, missing, header_row_used, used_sheet = None, [], {}, required.copy(), 0, None

    for sheet in sheets_to_try:
        df_cand = _try_read(0, sheet)
        if df_cand is None or df_cand.empty:
            continue
        raw_cand = list(df_cand.columns)
        col_map_cand = _find_col_map(raw_cand)
        missing_cand = [k for k in required if k not in col_map_cand]
        hdr_used = 0
        if missing_cand and any(str(c).startswith("Unnamed:") for c in raw_cand):
            hdr_row = _find_header_row(sheet)
            df2 = _try_read(hdr_row, sheet)
            if df2 is not None and not df2.empty:
                raw2 = [str(c) for c in df2.columns]
                col_map2 = _find_col_map(raw2)
                missing2 = [k for k in required if k not in col_map2]
                if len(missing2) < len(missing_cand):
                    df_cand, raw_cand, col_map_cand, missing_cand = df2, raw2, col_map2, missing2
                    hdr_used = hdr_row
        if not missing_cand:
            df, raw_cols, col_map, missing, header_row_used, used_sheet = df_cand, raw_cand, col_map_cand, [], hdr_used, sheet
            break
        if df is None or len(missing_cand) < len(missing):
            df, raw_cols, col_map, missing, header_row_used, used_sheet = df_cand, raw_cand, col_map_cand, missing_cand, hdr_used, sheet

    if df is None or df.empty:
        return [], f"Planilha vazia ou erro ao ler. {last_err or ''}"
    if missing:
        cols_found = [str(c) for c in raw_cols][:20]
        hint = ""
        if any("comercia" in str(c).lower() or "r$ devolução" in str(c).lower() for c in raw_cols):
            hint = " Seu arquivo parece ser um relatório resumido. "
        return [], (
            f"Colunas obrigatórias ausentes: {', '.join(missing).upper()}. "
            f"Colunas encontradas (top 20): {cols_found}. "
            f"{hint}Use o Modelo Excel (botão 'Modelo Excel' na tela) ou planilha com: "
            f"DATA ROMANEIO, DATA ENTREGA, CODIGO, NOME DO CLIENTE, VENDEDOR, MOTORISTA, VALOR, MOTIVO, RESPONSABILIDADE."
        )

    rows = []
    for idx, row in df.iterrows():
        row_num = int(idx) + header_row_used + 2
        dr = parse_date_dd_mm_yyyy(row.get(col_map["data_romaneio"]))
        de = parse_date_dd_mm_yyyy(row.get(col_map["data_entrega"]))
        cod = _as_str(row.get(col_map["codigo"]))
        nome = _as_str(row.get(col_map.get("nome_cliente")))
        vend = _as_str(row.get(col_map["vendedor"]))
        mot = _as_str(row.get(col_map["motorista"]))
        valor = parse_valor_pt_br(row.get(col_map["valor"]))
        motivo = _as_str(row.get(col_map["motivo"]))
        obs = _as_str(row.get(col_map.get("observacao")))
        resp = _as_str(row.get(col_map["responsabilidade"]))
        ajud = _as_str(row.get(col_map.get("ajudante"))) if "ajudante" in col_map else None

        rows.append(DevolucaoRow(
            data_romaneio=dr,
            data_entrega=de or dr,
            codigo=cod,
            nome_cliente=nome,
            vendedor=vend,
            motorista=mot,
            valor=valor,
            motivo=motivo,
            observacao=obs,
            responsabilidade=resp,
            ajudante=ajud,
            row_index=row_num,
        ))
    return rows, None


def _load_cadastros(session: Session) -> Dict[str, Any]:
    """Carrega cadastros em dict para validação rápida (evitar N+1)."""
    clients = session.exec(select(Client)).all()
    # Filtro seguro: incluir status NULL como ativo; excluir apenas fired
    employees = session.exec(
        select(Employee).where(
            or_(Employee.status.is_(None), Employee.status != "fired")
        )
    ).all()
    if not employees:
        employees = session.exec(select(Employee)).all()
    motivos = session.exec(select(DevolucaoMotivo).where(DevolucaoMotivo.is_active == True)).all()
    resp_list = session.exec(select(DevolucaoResponsabilidade).where(DevolucaoResponsabilidade.is_active == True)).all()

    client_by_nb = {}
    client_by_name = {}
    for c in clients:
        if c.nb:
            n = _norm_text(str(c.nb))
            client_by_nb[n] = c
            client_by_nb[n.lstrip("0") or "0"] = c
            client_by_nb[n.replace("/", "").replace("-", "").replace(".", "")] = c
        for f in (c.name, c.nome_fantasia, c.razao_social):
            if f and _norm_text(f):
                client_by_name[_norm_text(f)] = c

    vendedor_by_code = {}
    vendedor_by_name_exact: Dict[str, List[Any]] = {}
    employees_with_seller_code = 0
    seller_code_collisions: Dict[str, List[int]] = {}
    for e in employees:
        if e.seller_code:
            employees_with_seller_code += 1
            sc = normalize_code(e.seller_code)
            if sc:
                seller_code_collisions.setdefault(sc, []).append(e.id)
                vendedor_by_code[sc] = e
                vendedor_by_code[sc.lstrip("0") or "0"] = e
                digits_only = re.sub(r"\D", "", sc)
                if digits_only:
                    vendedor_by_code[digits_only] = e
        nn = normalize_name(e.name)
        if nn:
            if nn not in vendedor_by_name_exact:
                vendedor_by_name_exact[nn] = []
            vendedor_by_name_exact[nn].append(e)

    def _is_motorista_role(emp: Employee) -> bool:
        r = _norm_text(getattr(emp, "role", "") or "")
        return "motorista" in r and "ajudante" not in r

    motorista_by_name = {}
    motoristas_first = sorted(employees, key=lambda e: (0 if _is_motorista_role(e) else 1, e.name))
    for e in motoristas_first:
        name_norm = _norm_text(e.name)
        motorista_by_name[name_norm] = e
        tokens = name_norm.split()
        for t in tokens:
            if len(t) >= 3 and t not in motorista_by_name:
                motorista_by_name[t] = e
        for n in range(2, min(4, len(tokens) + 1)):
            prefix = " ".join(tokens[:n])
            if prefix not in motorista_by_name:
                motorista_by_name[prefix] = e

    motivo_by_norm = {}
    motivo_resp_map = {}
    for m in motivos:
        n = _norm_text(m.nome)
        motivo_by_norm[n] = m
        motivo_by_norm[_norm_nospace(m.nome)] = m
        if m.nome_normalizado:
            for token in (m.nome_normalizado or "").split():
                t = token.strip()
                if t:
                    motivo_by_norm[t] = m
        motivo_resp_map[m.id] = m.responsabilidade_id

    resp_by_norm = {}
    for r in resp_list:
        resp_by_norm[_norm_text(r.nome)] = r

    return {
        "clients": clients,
        "client_by_nb": client_by_nb,
        "client_by_name": client_by_name,
        "employees": employees,
        "employees_with_seller_code": employees_with_seller_code,
        "seller_code_collisions": seller_code_collisions,
        "vendedor_by_code": vendedor_by_code,
        "vendedor_by_name_exact": vendedor_by_name_exact,
        "motorista_by_name": motorista_by_name,
        "motivo_by_norm": motivo_by_norm,
        "motivo_resp_map": motivo_resp_map,
        "resp_by_norm": resp_by_norm,
        "motivos": motivos,
        "resp_list": resp_list,
    }


def get_cadastro_health(cad: Dict) -> Tuple[Dict[str, Any], List[str]]:
    """
    Diagnóstico automático dos cadastros.
    Retorna (diagnostics, global_errors).
    Se global_errors não for vazio, a validação deve ser abortada e retornar erro global.
    """
    employees = cad.get("employees", [])
    employees_with_seller_code = cad.get("employees_with_seller_code", 0)
    vendedor_by_code_size = len(cad.get("vendedor_by_code", {}))
    clients_total = len(cad.get("clients", []))
    client_by_nb_size = len(cad.get("client_by_nb", {}))
    motivos = cad.get("motivos", [])
    resp_list = cad.get("resp_list", [])

    seller_code_collisions = cad.get("seller_code_collisions", {})
    collision_count = sum(1 for ids in seller_code_collisions.values() if len(ids) > 1)
    collision_details = [{"seller_code": sc, "employee_ids": ids} for sc, ids in seller_code_collisions.items() if len(ids) > 1]

    diagnostics = {
        "employees_total": len(employees),
        "employees_with_seller_code": employees_with_seller_code,
        "vendedor_by_code_size": vendedor_by_code_size,
        "clients_total": clients_total,
        "client_by_nb_size": client_by_nb_size,
        "motivos_total": len(motivos),
        "responsabilidades_total": len(resp_list),
        "seller_code_duplicates_count": collision_count,
        "seller_code_duplicates": collision_details,
    }

    global_errors = []

    if vendedor_by_code_size == 0:
        if len(employees) == 0:
            global_errors.append(
                "Cadastro de vendedores não carregou (employees=0). Verifique a base de colaboradores."
            )
        elif employees_with_seller_code == 0:
            global_errors.append(
                "Nenhum colaborador com seller_code preenchido (employees_with_seller_code=0). "
                "Preencha o campo 'Codigo do Vendedor' em Colaboradores para cada vendedor."
            )
        else:
            global_errors.append(
                "Cadastro de vendedores vazio (vendedor_by_code=0). "
                "Verifique preenchimento do seller_code nos colaboradores."
            )

    if collision_count > 0:
        global_errors.append(
            f"seller_code duplicado em {collision_count} código(s). "
            f"Detalhes: {collision_details}. Cada vendedor deve ter código único."
        )

    if len(motivos) == 0:
        global_errors.append("Cadastro de motivos de devolução vazio (motivos_total=0). Execute o seed de motivos.")

    if len(resp_list) == 0:
        global_errors.append("Cadastro de responsabilidades vazio (responsabilidades_total=0). Execute o seed de responsabilidades.")

    if clients_total == 0 or client_by_nb_size == 0:
        global_errors.append(
            "Cadastro de clientes vazio (clients_total=0 ou client_by_nb vazio). "
            "Importe clientes antes de importar devoluções."
        )

    return diagnostics, global_errors


def precadastrar_vendedores_faltantes(
    session: Session, invalid: List[Dict[str, Any]]
) -> List[str]:
    """
    Cria colaboradores em pré-cadastro para códigos de vendedor que falharam na validação
    com erro "Vendedor não cadastrado". Retorna lista de códigos criados.
    """
    codes_to_create: set = set()
    for inv in invalid:
        for err in inv.get("errors", []):
            reason = err.get("reason") or ""
            if "Vendedor não cadastrado" in reason and "normalizado=" in reason:
                m = re.search(r"normalizado='([^']+)'", reason)
                if m:
                    codes_to_create.add(m.group(1))
    # Também extrair da mensagem alternativa (valor sem normalizado explícito)
    for inv in invalid:
        for err in inv.get("errors", []):
            reason = err.get("reason") or ""
            if "Vendedor não cadastrado" in reason and "Cadastre o vendedor" in reason:
                m = re.search(r"valor='([^']+)'", reason)
                if m:
                    code = normalize_code(m.group(1))
                    if code and code not in codes_to_create:
                        codes_to_create.add(code)

    created: List[str] = []
    for code in sorted(codes_to_create):
        existing = session.exec(
            select(Employee).where(Employee.seller_code == code)
        ).first()
        if existing:
            continue
        reg_id = f"PRECAD-{code}"
        existing_reg = session.exec(
            select(Employee).where(Employee.registration_id == reg_id)
        ).first()
        if existing_reg:
            if not existing_reg.seller_code:
                existing_reg.seller_code = code
                session.add(existing_reg)
            continue
        emp = Employee(
            registration_id=reg_id,
            name=f"Vendedor {code} (pré-cadastro)",
            seller_code=code,
            role="Vendedor",
            work_shift="Manhã",
            status="active",
        )
        session.add(emp)
        created.append(code)
    return created


def resolve_vendedor(
    value_from_excel: Any, cad: Dict
) -> Tuple[Optional[Employee], Optional[str]]:
    """
    Resolve vendedor por seller_code (prioritário) ou por nome (fallback).
    Retorna (Employee|None, error_reason|None).
    """
    if value_from_excel is None or (isinstance(value_from_excel, str) and not value_from_excel.strip()):
        return None, None

    code = normalize_code(value_from_excel)
    if code:
        emp = (
            cad["vendedor_by_code"].get(code)
            or cad["vendedor_by_code"].get(code.lstrip("0") or "0")
            or cad["vendedor_by_code"].get(re.sub(r"\D", "", code))
        )
        if emp:
            return emp, None
        if _is_numeric_value(value_from_excel):
            return None, f"Vendedor não cadastrado (valor='{value_from_excel}', normalizado='{code}'). Preencha seller_code no cadastro de colaboradores."

    name = normalize_name(value_from_excel)
    if name:
        candidates = cad["vendedor_by_name_exact"].get(name, [])
        if len(candidates) > 1:
            return None, f"Vendedor ambíguo: mais de um cadastro combina com '{value_from_excel}'"
        if len(candidates) == 1:
            return candidates[0], None
        matches = []
        for norm_n, emps in cad["vendedor_by_name_exact"].items():
            if name in norm_n or norm_n in name:
                matches.extend(emps)
        if len(matches) > 1:
            return None, f"Vendedor ambíguo: mais de um cadastro combina com '{value_from_excel}'"
        if len(matches) == 1:
            return matches[0], None

    return None, (
        f"Vendedor não cadastrado (valor='{value_from_excel}'). "
        f"Cadastre o vendedor e preencha seller_code no cadastro de colaboradores."
    )


def _find_motorista(name: Optional[str], cad: Dict) -> Optional[Employee]:
    if not name or not _norm_text(name):
        return None
    target = _norm_text(name)
    emp = cad["motorista_by_name"].get(target)
    if emp:
        return emp
    tokens = target.split()
    if tokens:
        emp = cad["motorista_by_name"].get(tokens[0])
        if emp:
            return emp
    return None


def _norm_nospace(s: str) -> str:
    """Remove espaços para match com nome_normalizado."""
    return _norm_text(s).replace(" ", "").replace("/", "").replace("-", "")

def _match_motivo(motivo_raw: Optional[str], resp_nome: Optional[str], cad: Dict) -> Optional[DevolucaoMotivo]:
    if not motivo_raw:
        return None
    target = _norm_text(motivo_raw)
    target_ns = _norm_nospace(motivo_raw)
    m = cad["motivo_by_norm"].get(target)
    if m:
        return m
    m = cad["motivo_by_norm"].get(target_ns)
    if m:
        return m
    for norm, motivo in cad["motivo_by_norm"].items():
        norm_ns = norm.replace(" ", "").replace("/", "").replace("-", "")
        if target_ns in norm_ns or norm_ns in target_ns:
            return motivo
    # Checar nome_normalizado (contém aliases como "pedidonaoentregue encomendanaopudoser")
    for motivo in cad["motivo_by_norm"].values():
        nn = (motivo.nome_normalizado or "").replace(" ", "")
        if target_ns and target_ns in nn:
            return motivo
    return None


def validate_row(row: DevolucaoRow, cad: Dict) -> ValidationResult:
    """Valida uma linha contra os cadastros."""
    errors = []

    if not _is_valid_dt(row.data_romaneio):
        errors.append({"column": "DATA ROMANEIO", "value": safe_date_str(row.data_romaneio), "reason": "DATA ROMANEIO inválida ou ausente."})
    if not _is_valid_dt(row.data_entrega):
        row.data_entrega = row.data_romaneio
    if _is_valid_dt(row.data_romaneio) and _is_valid_dt(row.data_entrega) and row.data_entrega < row.data_romaneio:
        errors.append({
            "column": "DATA ENTREGA",
            "value": safe_date_str(row.data_entrega),
            "reason": "Data entrega anterior à data romaneio.",
        })
    if _is_valid_dt(row.data_romaneio):
        try:
            dr_date = row.data_romaneio.date() if hasattr(row.data_romaneio, "date") else row.data_romaneio
            if dr_date and dr_date > date.today():
                errors.append({
                    "column": "DATA ROMANEIO",
                    "value": safe_date_str(row.data_romaneio),
                    "reason": "Data romaneio não pode ser futura.",
                })
        except (ValueError, TypeError):
            pass
    if not row.codigo:
        errors.append({"column": "CODIGO", "value": str(row.codigo), "reason": "Código do cliente ausente."})
    if row.valor <= 0:
        errors.append({"column": "VALOR", "value": str(row.valor), "reason": "Valor deve ser maior que zero."})
    if row.valor > 1_000_000:
        errors.append({"column": "VALOR", "value": str(row.valor), "reason": "Valor muito alto; validar planilha."})

    client = None
    if row.codigo:
        nb_raw = _norm_text(str(row.codigo))
        nb_nolead = nb_raw.lstrip("0") or "0"
        nb_compact = nb_raw.replace("/", "").replace("-", "").replace(".", "")
        client = (
            cad["client_by_nb"].get(nb_raw)
            or cad["client_by_nb"].get(nb_nolead)
            or cad["client_by_nb"].get(nb_compact)
        )
    if not client and row.nome_cliente:
        client = cad["client_by_name"].get(_norm_text(row.nome_cliente))
    if not client:
        errors.append({"column": "CODIGO", "value": row.codigo or "-", "reason": "Cliente não cadastrado."})

    vendedor = None
    vendedor_reason = None
    if row.vendedor:
        vendedor, vendedor_reason = resolve_vendedor(row.vendedor, cad)
    if not vendedor:
        reason = vendedor_reason or "Vendedor não cadastrado."
        errors.append({"column": "VENDEDOR", "value": str(row.vendedor) if row.vendedor else "-", "reason": reason})

    motorista = _find_motorista(row.motorista, cad)
    if not motorista:
        errors.append({"column": "MOTORISTA", "value": row.motorista or "-", "reason": "Motorista não cadastrado."})

    responsabilidade = None
    if row.responsabilidade:
        responsabilidade = cad["resp_by_norm"].get(_norm_text(row.responsabilidade))
    if not responsabilidade:
        errors.append({"column": "RESPONSABILIDADE", "value": row.responsabilidade or "-", "reason": "Responsabilidade não cadastrada."})

    motivo = _match_motivo(row.motivo, row.responsabilidade, cad)
    if not motivo:
        errors.append({"column": "MOTIVO", "value": row.motivo or "-", "reason": "Motivo não cadastrado ou não confere com responsabilidade."})

    ajudante_id = None
    if row.ajudante:
        ajud = _find_motorista(row.ajudante, cad)  # ajudante é Employee
        if not ajud:
            errors.append({"column": "AJUDANTE", "value": row.ajudante, "reason": "Ajudante não cadastrado."})
        else:
            ajudante_id = ajud.id

    if errors:
        return ValidationResult(
            valid=False,
            errors=errors,
        )

    return ValidationResult(
        valid=True,
        client_id=client.id if client else None,
        vendedor_id=vendedor.id if vendedor else None,
        motorista_id=motorista.id if motorista else None,
        ajudante_id=ajudante_id,
        motivo_id=motivo.id if motivo else None,
        responsabilidade_id=responsabilidade.id if responsabilidade else None,
    )


def compute_fields(row: DevolucaoRow, val: ValidationResult) -> Dict[str, Any]:
    """Enriquece linha validada com DIA, SEMANA, ACIMA_300, CLUSTER. Usa data_entrega quando disponível."""
    dt = (
        row.data_entrega if _is_valid_dt(row.data_entrega) else
        (row.data_romaneio if _is_valid_dt(row.data_romaneio) else datetime.now())
    )
    valor = row.valor
    return {
        "dia": compute_dia(dt),
        "semana": compute_semana(dt),
        "acima_300": compute_acima_300(valor),
        "cluster": compute_cluster(valor),
    }


def _source_rank(src: Optional[str]) -> int:
    """Prioridade: mobile > web/separação > manual > excel (planilha)."""
    s = (src or "").upper()
    if s == "MOBILE":
        return 4
    if s in ("WEB", "ROTA"):
        return 3
    if s == "MANUAL":
        return 2
    return 1


VAL_DUP_TOL = 1.0  # R$ — mesma devolução cliente+motorista+dia+valor próximo


def _duplicate_candidates(
    session: Session,
    client_id: int,
    motorista_id: int,
    data_romaneio: str,
    valor: float,
    exclude_id: Optional[int] = None,
) -> List[Devolucao]:
    rows = session.exec(
        select(Devolucao).where(
            Devolucao.client_id == client_id,
            Devolucao.motorista_id == motorista_id,
            Devolucao.data_romaneio == data_romaneio,
        )
    ).all()
    out: List[Devolucao] = []
    for d in rows:
        if exclude_id and d.id == exclude_id:
            continue
        if abs(float(d.valor or 0) - float(valor or 0)) <= VAL_DUP_TOL:
            out.append(d)
    return out


def _best_canonical_among_duplicates(candidates: List[Devolucao]) -> Optional[Devolucao]:
    if not candidates:
        return None
    real = [d for d in candidates if not getattr(d, "duplicate_of_id", None)]
    if not real:
        return None

    def sort_key(d: Devolucao):
        rk = _source_rank(d.source)
        has_route = 1 if getattr(d, "route_id", None) else 0
        ca = d.created_at or datetime.min
        return (rk, has_route, -ca.timestamp() if hasattr(ca, "timestamp") else 0)

    return max(real, key=sort_key)


def link_excel_rows_to_canonical(session: Session, canonical: Devolucao) -> int:
    """Marca importações Excel duplicadas da mesma devolução (mobile/rota prevalece)."""
    if not canonical.client_id or not canonical.motorista_id:
        return 0
    cands = _duplicate_candidates(
        session,
        canonical.client_id,
        canonical.motorista_id,
        canonical.data_romaneio,
        float(canonical.valor or 0),
        exclude_id=canonical.id,
    )
    n = 0
    for d in cands:
        if (d.source or "").upper() != "EXCEL":
            continue
        if getattr(d, "duplicate_of_id", None):
            continue
        if d.id == canonical.id:
            continue
        d.duplicate_of_id = canonical.id
        d.validation_status = "DUPLICATE_EXCEL"
        session.add(d)
        n += 1
    return n


def backfill_duplicate_links_period(session: Session, start_date: str, end_date: str) -> int:
    """No período, agrupa por cliente+motorista+dia+valor e liga Excel ao registro de maior prioridade."""
    rows = session.exec(
        select(Devolucao)
        .where(Devolucao.data_romaneio >= start_date)
        .where(Devolucao.data_romaneio <= end_date)
    ).all()
    groups: Dict[tuple, List[Devolucao]] = {}
    for d in rows:
        k = (d.client_id, d.motorista_id, d.data_romaneio, round(float(d.valor or 0), 2))
        groups.setdefault(k, []).append(d)
    updated = 0
    for lst in groups.values():
        if len(lst) < 2:
            continue
        canon = _best_canonical_among_duplicates(lst)
        if not canon or _source_rank(canon.source) <= _source_rank("EXCEL"):
            continue
        for d in lst:
            if d.id == canon.id:
                continue
            if (d.source or "").upper() != "EXCEL":
                continue
            if getattr(d, "duplicate_of_id", None):
                continue
            d.duplicate_of_id = canon.id
            d.validation_status = "DUPLICATE_EXCEL"
            session.add(d)
            updated += 1
    return updated


def make_idempotency_hash(
    data_romaneio: str,
    client_id: int,
    vendedor_id: int,
    motorista_id: int,
    valor: float,
    motivo_id: int,
) -> str:
    """Chave idempotente para evitar duplicatas."""
    key = f"{data_romaneio}|{client_id}|{vendedor_id}|{motorista_id}|{valor:.2f}|{motivo_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def validate_rows(
    rows: List[DevolucaoRow],
    session: Session,
    to_staging_on_invalid: bool = False,
) -> Tuple[List[Dict], List[Dict], List[Dict], Optional[int], List[str]]:
    """
    Valida todas as linhas.
    Retorna (valid_rows, invalid_errors, staging_rows, batch_id, global_errors).
    Se global_errors não for vazio, valid/invalid podem estar vazios — retornar erro global.
    """
    cad = _load_cadastros(session)
    diagnostics, global_errors = get_cadastro_health(cad)

    if global_errors:
        return [], [], None, None, global_errors

    valid = []
    invalid = []
    staging = []
    batch_id = None
    seen_hashes: set[str] = set()

    for row in rows:
        val = validate_row(row, cad)
        if val.valid:
            dr = row.data_romaneio if _is_valid_dt(row.data_romaneio) else datetime.now()
            de = row.data_entrega if _is_valid_dt(row.data_entrega) else dr
            dt_str = _safe_strftime(dr) or datetime.now().strftime("%Y-%m-%d")
            de_str = _safe_strftime(de) or dt_str
            comp = compute_fields(row, val)
            h = make_idempotency_hash(
                dt_str, val.client_id, val.vendedor_id, val.motorista_id, row.valor, val.motivo_id
            )
            if h in seen_hashes:
                invalid.append({
                    "row_index": row.row_index,
                    "errors": [{
                        "column": "LINHA",
                        "value": str(row.row_index),
                        "reason": "Duplicidade no arquivo (mesma devolução repetida).",
                    }],
                })
                continue
            seen_hashes.add(h)
            valid.append({
                "data_romaneio": dt_str,
                "data_entrega": de_str,
                "client_id": val.client_id,
                "vendedor_id": val.vendedor_id,
                "motorista_id": val.motorista_id,
                "ajudante_id": val.ajudante_id,
                "valor": row.valor,
                "motivo_id": val.motivo_id,
                "observacao": row.observacao,
                "responsabilidade_id": val.responsabilidade_id,
                "dia": comp["dia"],
                "semana": comp["semana"],
                "acima_300": comp["acima_300"],
                "cluster": comp["cluster"],
                "idempotency_hash": h,
            })
        else:
            err_entry = {"row_index": row.row_index, "errors": val.errors}
            invalid.append(err_entry)
            if to_staging_on_invalid:
                staging.append({
                    "row": row,
                    "errors": val.errors,
                })
    return valid, invalid, staging, batch_id, []


def _reconcile_devolucao_with_route(
    session: Session,
    r: Dict,
    motivo_nome: str,
    resp_nome: str,
) -> Optional[int]:
    """
    Busca Route compatível (cliente, motorista, data) e atualiza para devolução.
    Tenta data_entrega primeiro (quando a entrega ocorreu), depois data_romaneio.
    Retorna route_id se atualizou, None caso contrário.
    """
    dates_to_try = [r.get("data_entrega"), r.get("data_romaneio")]
    dates_to_try = [d for d in dates_to_try if d]
    if not dates_to_try:
        return None
    client_id = r.get("client_id")
    motorista_id = r.get("motorista_id")
    if not client_id or not motorista_id:
        return None
    routes = []
    for date_str in dates_to_try:
        routes = list(session.exec(
            select(Route)
            .where(Route.type == "delivery")
            .where(Route.client_id == client_id)
            .where(Route.employee_id == motorista_id)
            .where(Route.date == date_str)
            .where(Route.delivery_status.in_(["entregue", "pendente", "iniciada", "reaberta"]))
        ).all())
        if routes:
            break
    if not routes:
        return None
    route = routes[0]
    now = datetime.now().strftime("%H:%M")
    route.delivery_status = "devolucao"
    route.status = "completed"
    route.valor_devolucao = float(r.get("valor") or 0.0)
    route.devolucao_volume = route.tonnage
    route.delivery_return_category = resp_nome or "IMPORT"
    route.delivery_return_reason = motivo_nome or "Importado"
    if not route.delivery_returned_at:
        route.delivery_returned_at = now
    if not route.delivery_finished_at:
        route.delivery_finished_at = now
    route.end_time = route.end_time or now
    session.add(route)
    return route.id


def reconnect_orphan_devolucoes(
    session: Session,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """
    Reconecta devoluções com ORPHAN_ROUTE às rotas existentes.
    - Se a rota já tem devolução Mobile/Web: marca órfão Excel como DUPLICATE_EXCEL (duplicata).
    - Caso contrário: vincula route_id e limpa validation_status.
    Não altera o status da Route.
    Retorna quantidade de devoluções processadas (vinculadas ou marcadas como duplicata).
    """
    eff_date = func.coalesce(Devolucao.data_entrega, Devolucao.data_romaneio)
    q = (
        select(Devolucao)
        .where(Devolucao.validation_status == "ORPHAN_ROUTE")
        .where(Devolucao.route_id.is_(None))
        .where(Devolucao.client_id.is_not(None))
        .where(Devolucao.motorista_id.is_not(None))
    )
    if start_date:
        q = q.where(eff_date >= start_date)
    if end_date:
        q = q.where(eff_date <= end_date)
    orphans = session.exec(q.order_by(Devolucao.data_romaneio, Devolucao.id)).all()
    updated = 0
    for d in orphans:
        dates_to_try = [d.data_entrega, d.data_romaneio]
        dates_to_try = [str(x)[:10] if x else None for x in dates_to_try]
        dates_to_try = [x for x in dates_to_try if x]
        for date_str in dates_to_try:
            routes = list(session.exec(
                select(Route)
                .where(Route.type == "delivery")
                .where(Route.client_id == d.client_id)
                .where(Route.employee_id == d.motorista_id)
                .where(Route.date == date_str)
            ).all())
            if not routes:
                continue
            route_id = routes[0].id
            # Verifica se já existe devolução Mobile/Web nessa rota (canônica)
            canon = session.exec(
                select(Devolucao)
                .where(Devolucao.route_id == route_id)
                .where(Devolucao.id != d.id)
            ).first()
            if canon and _source_rank(canon.source) > _source_rank("EXCEL"):
                # Órfão Excel é duplicata da devolução Mobile/Web — marcar como tal
                d.duplicate_of_id = canon.id
                d.validation_status = "DUPLICATE_EXCEL"
                session.add(d)
                updated += 1
            else:
                # Nenhuma devolução canônica na rota — vincular o órfão
                d.route_id = route_id
                d.validation_status = ""
                session.add(d)
                updated += 1
            break
    return updated


def reconcile_all_devolucoes_with_routes(
    session: Session,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """
    Percorre Devoluções no período e atualiza Rotas correspondentes para status devolução.
    Retorna quantidade de rotas atualizadas.
    """
    q = select(Devolucao).order_by(Devolucao.data_romaneio, Devolucao.id)
    if start_date:
        q = q.where(Devolucao.data_romaneio >= start_date)
    if end_date:
        q = q.where(Devolucao.data_romaneio <= end_date)
    devolucoes = session.exec(q).all()
    motivos = {m.id: m.nome for m in session.exec(select(DevolucaoMotivo)).all()}
    resp_map = {r.id: r.nome for r in session.exec(select(DevolucaoResponsabilidade)).all()}
    updated = 0
    for d in devolucoes:
        r = {
            "data_romaneio": d.data_romaneio,
            "data_entrega": d.data_entrega,
            "client_id": d.client_id,
            "motorista_id": d.motorista_id,
            "valor": d.valor,
        }
        motivo_nome = motivos.get(d.motivo_id, "Importado")
        resp_nome = resp_map.get(d.responsabilidade_id, "IMPORT")
        rid = _reconcile_devolucao_with_route(session, r, motivo_nome, resp_nome)
        if rid:
            updated += 1
            if not d.route_id:
                d.route_id = rid
                if getattr(d, "validation_status", "").strip() == "ORPHAN_ROUTE":
                    d.validation_status = ""
                session.add(d)
    return updated


def _parse_route_helper_ids(helpers_json: Optional[str]) -> List[int]:
    """Parse delivery_helpers_json da rota para lista de employee_id (ajudantes)."""
    if not helpers_json:
        return []
    try:
        data = json.loads(helpers_json) if isinstance(helpers_json, str) else helpers_json
        if not isinstance(data, list):
            return []
        return [int(x) for x in data if x is not None and str(x).strip().isdigit()]
    except Exception:
        return []


def sync_route_to_devolucao(
    session: Session,
    route: "Route",
    source: str = "WEB",
) -> Optional["Devolucao"]:
    """
    Sincroniza Route (devolucao) com Devolucao. Chamado quando devolução é
    marcada em /separacao ou mobile, para que apareça em /devolucoes.
    Retorna o Devolucao criado/atualizado ou None.
    """
    if (route.delivery_status or "").lower() != "devolucao":
        return None
    if not route.id or not route.client_id or not route.employee_id:
        return None
    valor = float(route.valor_devolucao or route.valor_financeiro or 0.0)
    motivo_nome = (route.delivery_return_reason or "").strip() or "Nao informado"
    resp_nome = (route.delivery_return_category or "").strip() or "IMPORT"
    if resp_nome.upper() == "MOBILE":
        resp_nome = "COMERCIAL"
    motivos = {m.nome: m for m in session.exec(select(DevolucaoMotivo).where(DevolucaoMotivo.is_active == True)).all()}
    motivos_norm = {_norm_text(k): m for k, m in motivos.items()}
    resp_list = list(session.exec(select(DevolucaoResponsabilidade).where(DevolucaoResponsabilidade.is_active == True)).all())
    resp_by_name = {r.nome: r for r in resp_list}
    resp_by_norm = {_norm_text(r.nome): r for r in resp_list}
    motivo = motivos.get(motivo_nome) or motivos_norm.get(_norm_text(motivo_nome))
    if not motivo and motivos:
        motivo = next(iter(motivos.values()), None)
    resp = resp_by_name.get(resp_nome) or resp_by_norm.get(_norm_text(resp_nome))
    if not resp and resp_list:
        resp = resp_list[0]
    if not motivo or not resp:
        return None
    motorista_id = route.employee_id
    helper_ids = _parse_route_helper_ids(getattr(route, "delivery_helpers_json", None))
    ajudante_id = (helper_ids[0] if helper_ids else None)
    if ajudante_id and ajudante_id == motorista_id and len(helper_ids) > 1:
        ajudante_id = helper_ids[1]
    elif ajudante_id == motorista_id:
        ajudante_id = None
    existing = session.exec(select(Devolucao).where(Devolucao.route_id == route.id)).first()
    if existing:
        existing.valor = valor
        existing.motivo_id = motivo.id
        existing.responsabilidade_id = resp.id
        existing.source = source
        existing.ajudante_id = ajudante_id
        session.add(existing)
        session.flush()
        link_excel_rows_to_canonical(session, existing)
        return existing
    try:
        dt = datetime.strptime(route.date, "%Y-%m-%d") if isinstance(route.date, str) else datetime.now()
    except (ValueError, TypeError):
        dt = datetime.now()
    h = make_idempotency_hash(route.date, route.client_id, motorista_id, motorista_id, valor, motivo.id)
    if session.exec(select(Devolucao).where(Devolucao.idempotency_hash == h)).first():
        return None
    dev = Devolucao(
        route_id=route.id,
        data_romaneio=route.date,
        data_entrega=route.date,
        client_id=route.client_id,
        vendedor_id=motorista_id,
        motorista_id=motorista_id,
        ajudante_id=ajudante_id,
        valor=valor,
        motivo_id=motivo.id,
        responsabilidade_id=resp.id,
        dia=compute_dia(dt),
        semana=compute_semana(dt),
        acima_300=compute_acima_300(valor),
        cluster=compute_cluster(valor),
        source=source,
        idempotency_hash=h,
    )
    session.add(dev)
    session.flush()
    link_excel_rows_to_canonical(session, dev)
    return dev


def rematch_motoristas_from_ajudantes(
    session: Session,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """
    Corrige devoluções cujo motorista_id aponta para ajudante: substitui pelo
    motorista correto quando o primeiro nome coincide (ex: Marcos Henrique -> Marcos Antonio).
    Retorna quantidade de devoluções atualizadas.
    """
    cad = _load_cadastros(session)
    motorista_by_name = cad.get("motorista_by_name", {})

    def _is_ajudante(emp: Employee) -> bool:
        r = _norm_text(getattr(emp, "role", "") or "")
        return "ajudante" in r

    def _is_motorista(emp: Employee) -> bool:
        r = _norm_text(getattr(emp, "role", "") or "")
        return "motorista" in r and "ajudante" not in r

    q = select(Devolucao).order_by(Devolucao.data_romaneio, Devolucao.id)
    if start_date:
        q = q.where(Devolucao.data_romaneio >= start_date)
    if end_date:
        q = q.where(Devolucao.data_romaneio <= end_date)
    devolucoes = session.exec(q).all()
    updated = 0
    for d in devolucoes:
        emp = session.get(Employee, d.motorista_id)
        if not emp or not _is_ajudante(emp):
            continue
        tokens = _norm_text(emp.name).split()
        if not tokens or len(tokens[0]) < 3:
            continue
        first = tokens[0]
        correct = motorista_by_name.get(first)
        if not correct or correct.id == emp.id:
            continue
        if not _is_motorista(correct):
            continue
        d.motorista_id = correct.id
        session.add(d)
        updated += 1
    return updated


def save_batch(
    session: Session,
    valid_rows: List[Dict],
    metadata: Dict[str, Any],
    source: str = "EXCEL",
    created_by: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """
    Persiste devoluções válidas em transação.
    Sobrepõe Route correspondente (cliente, motorista, data) para status devolução.
    metadata: {filename, batch_id, ...}
    Retorna (created_count, idempotency_hashes_skipped)
    """
    created = 0
    skipped = []
    motivos = {m.id: m.nome for m in session.exec(select(DevolucaoMotivo)).all()}
    resp_map = {r.id: r.nome for r in session.exec(select(DevolucaoResponsabilidade)).all()}
    for r in valid_rows:
        motivo_nome = motivos.get(r.get("motivo_id"), "Importado")
        resp_nome = resp_map.get(r.get("responsabilidade_id"), "IMPORT")
        existing = session.exec(
            select(Devolucao).where(Devolucao.idempotency_hash == r["idempotency_hash"])
        ).first()
        if existing:
            r_existing = {
                "data_romaneio": existing.data_romaneio,
                "data_entrega": existing.data_entrega,
                "client_id": existing.client_id,
                "motorista_id": existing.motorista_id,
                "valor": existing.valor,
            }
            motivo_ex = motivos.get(existing.motivo_id, "Importado")
            resp_ex = resp_map.get(existing.responsabilidade_id, "IMPORT")
            _reconcile_devolucao_with_route(session, r_existing, motivo_ex, resp_ex)
            skipped.append(r["idempotency_hash"])
            continue
        cands = _duplicate_candidates(
            session,
            r["client_id"],
            r["motorista_id"],
            r["data_romaneio"],
            float(r["valor"] or 0),
        )
        canon = _best_canonical_among_duplicates(cands)
        dup_of_id = None
        val_stat = ""
        is_shadow_excel = (
            (source or "").upper() == "EXCEL"
            and canon is not None
            and _source_rank(canon.source) > _source_rank("EXCEL")
        )
        if is_shadow_excel:
            dup_of_id = canon.id
            val_stat = "DUPLICATE_EXCEL"
            route_id = None
        else:
            route_id = _reconcile_devolucao_with_route(session, r, motivo_nome, resp_nome)
        if (source or "").upper() == "EXCEL" and not route_id and not dup_of_id:
            val_stat = "ORPHAN_ROUTE"
        dev = Devolucao(
            route_id=route_id,
            data_romaneio=r["data_romaneio"],
            data_entrega=r["data_entrega"],
            client_id=r["client_id"],
            vendedor_id=r["vendedor_id"],
            motorista_id=r["motorista_id"],
            ajudante_id=r.get("ajudante_id"),
            valor=r["valor"],
            motivo_id=r["motivo_id"],
            observacao=r.get("observacao"),
            responsabilidade_id=r["responsabilidade_id"],
            dia=r["dia"],
            semana=r["semana"],
            acima_300=r["acima_300"],
            cluster=r["cluster"],
            idempotency_hash=r["idempotency_hash"],
            source=source,
            created_by=created_by,
            duplicate_of_id=dup_of_id,
            validation_status=val_stat,
        )
        session.add(dev)
        created += 1
    batch_id = metadata.get("batch_id") if metadata else None
    if batch_id:
        batch = session.get(DevolucaoImportBatch, batch_id)
        if batch:
            batch.status = "committed"
            batch.committed_at = datetime.now()
            # valid_count é o total validado no preview; aqui guardamos o que foi de fato criado.
            batch.valid_count = created
            batch.pending_count = max(0, (batch.invalid_count or 0))
            session.add(batch)
    return created, skipped


def persist_import_batch(
    session: Session,
    filename: str,
    rows: List[DevolucaoRow],
    valid_rows: List[Dict],
    invalid_rows: List[Dict],
    created_by: Optional[str] = None,
    create_staging: bool = True,
) -> int:
    """
    Persiste o preview de importação em lote auditável.
    - Cria DevolucaoImportBatch
    - Cria DevolucaoImportRowError por erro
    - Cria DevolucaoStaging por linha inválida (opcional)
    Retorna batch_id.
    """
    batch = DevolucaoImportBatch(
        filename=filename,
        status="preview",
        total_rows=len(rows),
        valid_count=len(valid_rows),
        invalid_count=len(invalid_rows),
        pending_count=len(invalid_rows),
        created_by=created_by,
    )
    session.add(batch)
    session.flush()

    row_by_index = {r.row_index: r for r in rows}
    for inv in invalid_rows:
        row_index = int(inv.get("row_index") or 0)
        errors = inv.get("errors") or []
        raw_row = row_by_index.get(row_index)
        raw_payload = None
        if raw_row:
            raw_payload = {
                "data_romaneio": safe_date_str(raw_row.data_romaneio),
                "data_entrega": safe_date_str(raw_row.data_entrega),
                "codigo": raw_row.codigo,
                "nome_cliente": raw_row.nome_cliente,
                "vendedor": raw_row.vendedor,
                "motorista": raw_row.motorista,
                "valor": raw_row.valor,
                "motivo": raw_row.motivo,
                "observacao": raw_row.observacao,
                "responsabilidade": raw_row.responsabilidade,
                "ajudante": raw_row.ajudante,
            }

        for err in errors:
            session.add(
                DevolucaoImportRowError(
                    batch_id=batch.id,
                    row_index=row_index,
                    column_name=str(err.get("column") or ""),
                    value=str(err.get("value") or ""),
                    reason=str(err.get("reason") or "Erro de validação"),
                    raw_row_json=json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
                )
            )

        if create_staging:
            session.add(
                DevolucaoStaging(
                    batch_id=batch.id,
                    row_index=row_index,
                    status="PENDENTE_VALIDACAO",
                    data_romaneio=safe_date_str(raw_row.data_romaneio) if raw_row else None,
                    data_entrega=safe_date_str(raw_row.data_entrega) if raw_row else None,
                    codigo_cliente=(raw_row.codigo if raw_row else None),
                    nome_cliente=(raw_row.nome_cliente if raw_row else None),
                    codigo_vendedor=(raw_row.vendedor if raw_row else None),
                    nome_motorista=(raw_row.motorista if raw_row else None),
                    valor=(raw_row.valor if raw_row else 0.0),
                    motivo_raw=(raw_row.motivo if raw_row else None),
                    responsabilidade_raw=(raw_row.responsabilidade if raw_row else None),
                    observacao=(raw_row.observacao if raw_row else None),
                    ajudante_raw=(raw_row.ajudante if raw_row else None),
                    validation_errors=json.dumps(errors, ensure_ascii=False),
                )
            )

    return batch.id
