# -*- coding: utf-8 -*-
"""Utilitários para importação e higienização de clientes (CSV/Excel)."""
import re
import unicodedata
from typing import Tuple, Optional


def _norm_nfd(s: str) -> str:
    """Remove acentos (NFD -> ASCII)."""
    s = (s or "").strip()
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")


def normalize_address(raw: Optional[str]) -> str:
    """Higieniza endereço:
    - Remove prefixos estranhos (||RUA:, ||AV :, etc.)
    - Remove sufixos (||:, ||)
    - Remove frases de instrução (Remover e padronizar)
    - Padroniza RUA/AV/ROD
    """
    if not raw or not str(raw).strip():
        return ""
    s = str(raw).strip()
    # Remove prefixos ||TIPO : ou ||TIPO:
    s = re.sub(r"^\|\|*\s*(?:RUA|AV|ROD|AVENIDA)\s*:\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\|\|+", "", s)
    s = s.strip()
    # Remove sufixos || : ou ||
    s = re.sub(r"\s*\|\|\s*:?\s*$", "", s)
    s = re.sub(r"\s*:\s*$", "", s)
    # Remove frases de instrução comuns
    s = re.sub(r"\s*remover\s+e\s+padronizar\s*", " ", s, flags=re.IGNORECASE)
    s = s.strip()
    # Padronizar abreviações
    s = re.sub(r"\bAV\s*[:\s]+", "AV. ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bAVENIDA\s+", "AV. ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bRUA\s*[:\s]+", "RUA ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bROD\s*[:\s]+", "ROD. ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_phone_br(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Normaliza telefone Brasil.
    Retorna (e164, amigavel).
    E.164: +55XXXXXXXXXXX (DDD + 9 dígitos para cel, 8 para fixo).
    Amigável: (XX) XXXXX-XXXX ou (XX) XXXX-XXXX
    """
    if not raw or not str(raw).strip():
        return None, None
    digits = re.sub(r"\D", "", str(raw).strip())
    digits = digits.lstrip("0")
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    if len(digits) > 11:
        digits = digits[-11:]
    if len(digits) < 10:
        return None, str(raw).strip()
    if len(digits) == 11:
        e164 = "+55" + digits
        amigavel = f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    elif len(digits) == 10:
        e164 = "+55" + digits
        amigavel = f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    else:
        return None, str(raw).strip()
    return (e164, amigavel) if e164 else (None, amigavel)


def normalize_key(text: Optional[str]) -> str:
    """Caixa alta e remoção de acentos para chaves internas (município, bairro)."""
    if not text or not str(text).strip():
        return ""
    return _norm_nfd(str(text).strip()).upper()


def find_col_map(columns: list, norm_func=None) -> dict:
    """Mapeia colunas do arquivo para campos padrão.
    Nomes canônicos (Excel/CSV): NB, SETOR, ME, SA, VISITA, FANTAS, Razão Social,
    MUNICÍPIO, BAIRRO, ENDEREÇO, FONE, SEGMENTO, STATUS.
    """
    if norm_func is None:
        def norm_func(s):
            s = (s or "").strip().lower()
            return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")

    col_map = {}
    keywords = {
        "nb": ["nb"],
        "setor": ["setor"],
        "me": ["me"],
        "sa": ["sa"],
        "visita": ["visita"],
        "fantas": ["fantas", "fantasia", "nome fantasia", "nome_fantasia"],
        "razao_social": ["razao social", "razão social", "razao_social"],
        "municipio": ["municipio", "município"],
        "bairro": ["bairro"],
        "endereco": ["endereco", "endereço"],
        "fone": ["fone", "fone(1)", "telefone", "fone 1"],
        "segmento": ["segmento"],
        "status": ["status"],
    }
    for std, kws in keywords.items():
        for c in columns:
            cn = norm_func(str(c))
            for kw in kws:
                kn = norm_func(kw)
                if cn == kn or kn in cn:
                    col_map[std] = c
                    break
            if std in col_map:
                break
    return col_map
