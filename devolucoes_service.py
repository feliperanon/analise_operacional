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
from sqlalchemy import or_
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


def parse_date_dd_mm_yyyy(value: Any) -> Optional[datetime]:
    """Parse data dd/mm/yyyy, dd-mm-yyyy, ou datetime/Timestamp do Excel."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):  # pd.Timestamp
        try:
            return value.to_pydatetime()
        except Exception:
            pass
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)) and value > 0:
        try:
            import pandas as pd
            return pd.Timestamp(value).to_pydatetime()
        except Exception:
            pass
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    s = s.split()[0] if " " in s else s
    for sep in ["/", "-", "."]:
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    p0, p1, p2 = int(parts[0]), int(parts[1]), int(parts[2])
                    if p0 > 31 or (len(parts[0]) == 4 and p0 >= 1900):
                        y, m, d = p0, p1, p2
                    else:
                        d, m, y = p0, p1, p2
                        if y < 100:
                            y += 2000
                    return datetime(y, m, d)
                except (ValueError, IndexError):
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
        try:
            from pathlib import Path
            log_path = Path(__file__).resolve().parent / "debug-c5b864.log"
            with open(log_path, "a", encoding="utf-8") as f:
                import json as _j
                f.write(_j.dumps({
                    "sessionId": "c5b864", "message": "parse_excel_missing_cols",
                    "data": {"missing": missing, "raw_cols": [str(c) for c in raw_cols], "col_map": col_map},
                    "timestamp": datetime.now().isoformat()
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
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
    for e in employees:
        if e.seller_code:
            sc = normalize_code(e.seller_code)
            if sc:
                vendedor_by_code[sc] = e
                vendedor_by_code[sc.lstrip("0") or "0"] = e
        nn = normalize_name(e.name)
        if nn:
            if nn not in vendedor_by_name_exact:
                vendedor_by_name_exact[nn] = []
            vendedor_by_name_exact[nn].append(e)

    motorista_by_name = {}
    for e in employees:
        motorista_by_name[_norm_text(e.name)] = e
        tokens = set(_norm_text(e.name).split())
        for t in tokens:
            if len(t) >= 3:
                motorista_by_name[t] = e  # primeiro nome

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
        "vendedor_by_code": vendedor_by_code,
        "vendedor_by_name_exact": vendedor_by_name_exact,
        "motorista_by_name": motorista_by_name,
        "motivo_by_norm": motivo_by_norm,
        "motivo_resp_map": motivo_resp_map,
        "resp_by_norm": resp_by_norm,
    }


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
        emp = cad["vendedor_by_code"].get(code) or cad["vendedor_by_code"].get(
            code.lstrip("0") or "0"
        )
        if emp:
            return emp, None
        if _is_numeric_value(value_from_excel):
            return None, "Vendedor não cadastrado (tentado por seller_code)"

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

    return None, "Vendedor não cadastrado (tentado por seller_code e por nome)"


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

    if not row.data_romaneio:
        errors.append({"column": "DATA ROMANEIO", "value": str(row.data_romaneio), "reason": "Data inválida ou ausente."})
    if not row.data_entrega:
        row.data_entrega = row.data_romaneio
    if not row.codigo:
        errors.append({"column": "CODIGO", "value": str(row.codigo), "reason": "Código do cliente ausente."})

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
    """Enriquece linha validada com DIA, SEMANA, ACIMA_300, CLUSTER."""
    dt = row.data_romaneio or datetime.now()
    valor = row.valor
    return {
        "dia": compute_dia(dt),
        "semana": compute_semana(dt),
        "acima_300": compute_acima_300(valor),
        "cluster": compute_cluster(valor),
    }


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
) -> Tuple[List[Dict], List[Dict], List[Dict], Optional[int]]:
    """
    Valida todas as linhas.
    Retorna (valid_rows, invalid_errors, staging_rows, batch_id ou None).
    valid_rows: lista de dict prontos para Devolucao
    invalid_errors: lista de {row_index, column, value, reason}
    staging_rows: se to_staging_on_invalid, linhas que vão para fila de pendências
    batch_id: ID do batch se criado (para staging)
    """
    cad = _load_cadastros(session)
    valid = []
    invalid = []
    staging = []
    batch_id = None

    for row in rows:
        val = validate_row(row, cad)
        if val.valid:
            dt_str = (row.data_romaneio or datetime.now()).strftime("%Y-%m-%d")
            de_str = (row.data_entrega or row.data_romaneio or datetime.now()).strftime("%Y-%m-%d")
            comp = compute_fields(row, val)
            h = make_idempotency_hash(
                dt_str, val.client_id, val.vendedor_id, val.motorista_id, row.valor, val.motivo_id
            )
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
    return valid, invalid, staging, batch_id


def save_batch(
    session: Session,
    valid_rows: List[Dict],
    metadata: Dict[str, Any],
    source: str = "EXCEL",
    created_by: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """
    Persiste devoluções válidas em transação.
    metadata: {filename, batch_id, ...}
    Retorna (created_count, idempotency_hashes_skipped)
    """
    created = 0
    skipped = []
    for r in valid_rows:
        existing = session.exec(
            select(Devolucao).where(Devolucao.idempotency_hash == r["idempotency_hash"])
        ).first()
        if existing:
            skipped.append(r["idempotency_hash"])
            continue
        dev = Devolucao(
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
        )
        session.add(dev)
        created += 1
    return created, skipped
