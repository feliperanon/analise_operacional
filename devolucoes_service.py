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
from datetime import datetime
from typing import Any, Optional, List, Tuple, Dict
from dataclasses import dataclass, field

from sqlmodel import Session, select
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
    """Parse data dd/mm/yyyy ou dd-mm-yyyy."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    for sep in ["/", "-", "."]:
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
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
    norm_map = {_norm_text(c): c for c in columns}
    aliases = {
        "data_romaneio": ["data romaneio", "data romaneo", "data_romaneio"],
        "data_entrega": ["data entrega", "data_entrega"],
        "codigo": ["codigo", "codigo cliente", "cod"],
        "nome_cliente": ["nome do cliente", "nome cliente", "cliente", "razao social"],
        "vendedor": ["vendedor"],
        "motorista": ["motorista"],
        "valor": ["valor"],
        "motivo": ["motivo"],
        "observacao": ["observacao", "observação", "obs"],
        "responsabilidade": ["responsabilidade"],
        "ajudante": ["ajudante"],
    }
    out = {}
    for key, options in aliases.items():
        for opt in options:
            if opt in norm_map:
                out[key] = norm_map[opt]
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

    try:
        engine = "openpyxl" if ext.endswith((".xlsx", ".xlsm")) else "xlrd"
        df = pd.read_excel(BytesIO(content), engine=engine, header=0, sheet_name=0)
    except Exception:
        # Tentar aba específica
        sheet_names_try = sheet_names or DEVOLUCOES_SHEET_NAMES
        df = None
        for sheet in sheet_names_try:
            try:
                df = pd.read_excel(BytesIO(content), engine=engine, header=0, sheet_name=sheet)
                break
            except Exception:
                continue
        if df is None:
            try:
                df = pd.read_excel(BytesIO(content), engine=engine, header=0)
            except Exception as ex:
                return [], f"Erro ao ler planilha: {ex}"

    if df is None or df.empty:
        return [], "Planilha vazia."

    col_map = _find_col_map(list(df.columns))
    required = ["data_romaneio", "data_entrega", "codigo", "vendedor", "motorista", "valor", "motivo", "responsabilidade"]
    missing = [k for k in required if k not in col_map]
    if missing:
        return [], f"Colunas obrigatórias ausentes: {', '.join(missing)}. Colunas: {list(df.columns)}"

    rows = []
    for idx, row in df.iterrows():
        row_num = int(idx) + 2
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
    employees = session.exec(select(Employee).where(Employee.status != "fired")).all()
    motivos = session.exec(select(DevolucaoMotivo).where(DevolucaoMotivo.is_active == True)).all()
    resp_list = session.exec(select(DevolucaoResponsabilidade).where(DevolucaoResponsabilidade.is_active == True)).all()

    client_by_nb = {}
    for c in clients:
        if c.nb:
            client_by_nb[_norm_text(c.nb)] = c
            client_by_nb[_norm_text(str(c.nb).lstrip("0"))] = c

    vendedor_by_code = {}
    for e in employees:
        if e.seller_code:
            vendedor_by_code[_norm_text(str(e.seller_code))] = e

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
        "employees": employees,
        "vendedor_by_code": vendedor_by_code,
        "motorista_by_name": motorista_by_name,
        "motivo_by_norm": motivo_by_norm,
        "motivo_resp_map": motivo_resp_map,
        "resp_by_norm": resp_by_norm,
    }


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
        nb_norm = _norm_text(row.codigo)
        nb_nolead = _norm_text(str(row.codigo).lstrip("0"))
        client = cad["client_by_nb"].get(nb_norm) or cad["client_by_nb"].get(nb_nolead)
    if not client:
        errors.append({"column": "CODIGO", "value": row.codigo or "-", "reason": "Cliente não cadastrado."})

    vendedor = None
    if row.vendedor:
        vendedor = cad["vendedor_by_code"].get(_norm_text(str(row.vendedor)))
    if not vendedor:
        errors.append({"column": "VENDEDOR", "value": row.vendedor or "-", "reason": "Vendedor não cadastrado."})

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
