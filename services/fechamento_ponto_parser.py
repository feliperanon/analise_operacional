# -*- coding: utf-8 -*-
"""
Parser para planilha "Fechamento de Ponto" - extrai faltas e atestados por dia.
Formato de saída: MATRICULA | NOME | DATA | OCORRÊNCIA (uma linha por dia)
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, date
from typing import List, Tuple, Optional
import pandas as pd
import io
import calendar

MESES_BR = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _normalize_text(s: str) -> str:
    if s is None or (isinstance(s, float) and (s != s or s == 0)):  # NaN or 0
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip()


def _sheet_to_year_month(sheet_name: str) -> Tuple[Optional[int], Optional[int]]:
    """Extrai ano e mês do nome da aba (ex: 'Janeiro 2025', 'Março 2025')."""
    s = _normalize_text(sheet_name).lower()
    for mes_nome, mes_num in MESES_BR.items():
        if mes_nome in s:
            match = re.search(r"20\d{2}", s)
            if match:
                return int(match.group()), mes_num
    return None, None


def _find_column(columns: List[str], *candidates: str) -> Optional[str]:
    """Retorna a coluna que corresponde a um dos candidatos (case-insensitive, normalizado)."""
    norm_cols = {_normalize_text(c).lower(): c for c in columns}
    for cand in candidates:
        key = _normalize_text(cand).lower()
        for k, v in norm_cols.items():
            if key in k or k in key:
                return v
    return None


def _is_empty(val) -> bool:
    if val is None or (isinstance(val, float) and (val != val or val == 0)):
        return True
    s = _normalize_text(val)
    return s in ("", "0", "-")


def _is_afastamento(val: str) -> bool:
    v = _normalize_text(val).lower()
    return v in ("inss", "afastado", "justiça", "justica", "licença", "licenca")


def _is_tudo_falta(val: str) -> bool:
    return "tudo falta" in _normalize_text(val).lower()


def _working_days_in_month(year: int, month: int) -> List[date]:
    """Dias úteis (segunda a sexta) do mês."""
    days = []
    _, last = calendar.monthrange(year, month)
    for d in range(1, last + 1):
        dt = date(year, month, d)
        if dt.weekday() < 5:  # 0=Mon, 4=Fri
            days.append(dt)
    return days


def _parse_date_part(part: str, year: int, month: int) -> List[date]:
    """Parse um fragmento como '05/01', '05 e 07/01', '02 a 06/01'."""
    part = part.strip()
    dates = []

    # "02 a 06/01" - intervalo
    match_range = re.search(r"(\d{1,2})\s*a\s*(\d{1,2})/(\d{1,2})", part)
    if match_range:
        d1, d2, m = int(match_range.group(1)), int(match_range.group(2)), int(match_range.group(3))
        for d in range(min(d1, d2), max(d1, d2) + 1):
            try:
                dates.append(date(year, m, d))
            except ValueError:
                pass
        return dates

    # "05 e 07/01" - lista de dias: antes da barra estão os dias, após / está o mês
    if "/" in part:
        mm_match = re.search(r"/(\d{1,2})(?:\s|$|\)|/)", part)
        if mm_match:
            part_month = int(mm_match.group(1))
            before_slash = part.split("/")[0]
            day_candidates = re.findall(r"\b(\d{1,2})\b", before_slash)
            for d_str in day_candidates:
                d = int(d_str)
                if 1 <= d <= 31:
                    try:
                        dates.append(date(year, part_month, d))
                    except ValueError:
                        pass
    # "05/01" - pares DD/MM adicionais (ex: "10/01" em "3 dias (01 a 03/01) + 1 dia (10/01)")
    all_ddmm = re.findall(r"(\d{1,2})/(\d{1,2})", part)
    for d_str, m_str in all_ddmm:
        try:
            d, m = int(d_str), int(m_str)
            dates.append(date(year, m, d))
        except ValueError:
            pass
    if dates:
        return sorted(set(dates))

    # "05/01" - único DD/MM
    single = re.search(r"(\d{1,2})/(\d{1,2})", part)
    if single:
        d, m = int(single.group(1)), int(single.group(2))
        try:
            dates.append(date(year, m, d))
        except ValueError:
            pass
    return dates


def _parse_cell_dates(cell_val, year: int, month: int) -> List[date]:
    """
    Interpreta o valor da célula e retorna lista de datas.
    - "0", "-", vazio -> []
    - "INSS", "AFASTADO", etc -> [] (afastamento, não gera datas)
    - "Tudo Falta" -> todos os dias úteis
    - "1 dia (05/01)" -> [05/01]
    - "2 dias (05 e 07/01)" ou "(24, 26 e 27/02)" -> [datas]
    - "24, 26 e 27/02" (sem parênteses) -> [24/02, 26/02, 27/02]
    """
    if _is_empty(cell_val):
        return []
    # Garantir string: Excel às vezes devolve só o número (ex: 3)
    raw = cell_val
    if isinstance(cell_val, (int, float)) and not _is_empty(cell_val):
        raw = str(int(cell_val)) if isinstance(cell_val, float) and cell_val == int(cell_val) else str(cell_val)
    s = _normalize_text(str(raw))
    if _is_afastamento(s):
        return []
    if _is_tudo_falta(s):
        return _working_days_in_month(year, month)

    dates = []
    # Extrair partes entre parênteses: (05/01), (05 e 07/01), (24, 26 e 27/02), etc
    parts = re.findall(r"\(([^)]+)\)", s)
    for part in parts:
        dates.extend(_parse_date_part(part, year, month))

    # Sem parênteses: tratar texto inteiro como parte (ex: "24, 26 e 27/02" ou "3 24, 26 e 27/02")
    if not dates and "/" in s and re.search(r"\d{1,2}", s):
        dates.extend(_parse_date_part(s, year, month))

    # Se ainda não achou, tentar DD/MM soltos
    if not dates:
        loose = re.findall(r"\b(\d{1,2}/\d{1,2})\b", s)
        for p in loose:
            dates.extend(_parse_date_part(p, year, month))

    return sorted(set(dates))


def _col_matches(header_val: str, *keywords: str) -> bool:
    v = _normalize_text(str(header_val)).lower()
    for kw in keywords:
        if kw in v or v in kw:
            return True
    return False


def parse_fechamento_ponto_excel(contents: bytes, filename: str = "") -> List[dict]:
    """
    Lê todas as abas do Excel e extrai faltas/atestados.
    Retorna lista de {"nome": str, "data": date, "ocorrencia": "Falta"|"Atestado"}.
    """
    engine = "xlrd" if filename.lower().endswith(".xls") else "openpyxl"
    results = []

    try:
        xl = pd.ExcelFile(io.BytesIO(contents), engine=engine)
    except Exception:
        try:
            xl = pd.ExcelFile(io.BytesIO(contents), engine="openpyxl")
        except Exception:
            xl = pd.ExcelFile(io.BytesIO(contents))

    for sheet_name in xl.sheet_names:
        year, month = _sheet_to_year_month(sheet_name)
        if not year or not month:
            continue

        df = pd.read_excel(xl, sheet_name=sheet_name, header=None)
        if df.empty or len(df.columns) < 2:
            continue

        # Localizar linha do cabeçalho e índices das colunas
        idx_func = None
        idx_atest = None
        idx_faltas = None
        header_row = -1

        for row_idx in range(min(20, len(df))):
            row = df.iloc[row_idx]
            tmp_func, tmp_atest, tmp_faltas = None, None, None
            candidates_atest, candidates_faltas = [], []
            for col_idx, cell in enumerate(row):
                v = _normalize_text(str(cell)).lower()
                # Nome: preferir NOME COMPLETO / FUNCIONÁRIO; não usar coluna "ID. EMPREGADO"
                if tmp_func is None:
                    if _col_matches(v, "nome completo", "funcionario", "funcionário"):
                        tmp_func = col_idx
                    elif _col_matches(v, "nome", "empregado") and "id" not in v and "id." not in v:
                        tmp_func = col_idx
                # ATESTADOS: priorizar "DIAS (ATESTADOS)" sobre "NÚMERO DE ATESTADOS" (que tem só o count)
                if "atestado" in v:
                    if "dias" in v:
                        tmp_atest = col_idx  # preferir coluna com datas
                    else:
                        candidates_atest.append(col_idx)
                # FALTAS: priorizar "DIAS (FALTAS)" ou "FALTAS S/J" sobre "NÚMERO DE FALTAS"
                if "falta" in v:
                    if "dias" in v or "s/j" in v:
                        tmp_faltas = col_idx
                    else:
                        candidates_faltas.append(col_idx)
            if tmp_atest is None and candidates_atest:
                tmp_atest = candidates_atest[0]
            if tmp_faltas is None and candidates_faltas:
                tmp_faltas = candidates_faltas[0]
            if tmp_func is not None and (tmp_atest is not None or tmp_faltas is not None):
                idx_func, idx_atest, idx_faltas = tmp_func, tmp_atest, tmp_faltas
                header_row = row_idx
                break

        if header_row < 0 or idx_func is None:
            continue

        for row_idx in range(header_row + 1, len(df)):
            row = df.iloc[row_idx]
            try:
                nome_val = row.iloc[idx_func] if idx_func < len(row) else ""
            except (IndexError, KeyError):
                continue
            nome = _normalize_text(nome_val)
            if not nome or len(nome) < 3:
                continue
            # Ignorar linhas que parecem cabeçalho repetido ou totais
            if nome.isdigit() or nome.upper() in ("TOTAL", "TOTAIS", "SUBTOTAL"):
                continue

            if idx_atest is not None and idx_atest < len(row):
                try:
                    cell_atest = row.iloc[idx_atest]
                    dates_atest = _parse_cell_dates(cell_atest, year, month)
                    # Se célula tem valor mas não gerou datas (ex: "3" separado de "24, 26 e 27/02")
                    if not dates_atest and not _is_empty(cell_atest) and idx_atest + 1 < len(row):
                        cell_next = row.iloc[idx_atest + 1]
                        dates_atest = _parse_cell_dates(cell_next, year, month)
                    for d in dates_atest:
                        results.append({"nome": nome, "data": d, "ocorrencia": "Atestado"})
                except (IndexError, ValueError):
                    pass

            if idx_faltas is not None and idx_faltas < len(row):
                try:
                    cell_faltas = row.iloc[idx_faltas]
                    dates_faltas = _parse_cell_dates(cell_faltas, year, month)
                    if not dates_faltas and not _is_empty(cell_faltas) and idx_faltas + 1 < len(row):
                        cell_next = row.iloc[idx_faltas + 1]
                        dates_faltas = _parse_cell_dates(cell_next, year, month)
                    for d in dates_faltas:
                        results.append({"nome": nome, "data": d, "ocorrencia": "Falta"})
                except (IndexError, ValueError):
                    pass

    return results
