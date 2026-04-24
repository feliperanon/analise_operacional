# -*- coding: utf-8 -*-
"""Utilitários para importação e higienização de clientes (CSV/Excel)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Optional, Tuple

PhoneImportKind = Literal["celular", "fixo", "invalido"]


@dataclass
class ImportPhoneParse:
    """Resultado da normalização de telefone na importação (planilhas)."""

    original: str
    ddd: Optional[str]
    subscriber: Optional[str]
    normalized_national: Optional[str]
    kind: PhoneImportKind
    valid: bool
    e164: Optional[str]
    display: Optional[str]


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


def normalize_import_phone_br(raw: Optional[str]) -> ImportPhoneParse:
    """Normalização de telefone brasileiro para importação Excel/CSV.

    Regras:
    - Só dígitos; remover o primeiro 0 do número completo se existir.
    - Opcional: remover prefixo 55 (DDI) quando sobrar 12+ dígitos nacionais.
    - DDD = 2 primeiros dígitos; assinante = restante.
    - Se o assinante tiver 9 dígitos e começar com 0, remover esse 0 (erro comum em fixo).
    - 9 dígitos começando com 9 → celular; 8 dígitos → fixo.
    """
    empty = ImportPhoneParse(
        original="",
        ddd=None,
        subscriber=None,
        normalized_national=None,
        kind="invalido",
        valid=False,
        e164=None,
        display=None,
    )
    if raw is None or not str(raw).strip():
        return empty

    original = str(raw).strip()
    d = re.sub(r"\D", "", original)
    if not d:
        return ImportPhoneParse(
            original=original,
            ddd=None,
            subscriber=None,
            normalized_national=None,
            kind="invalido",
            valid=False,
            e164=None,
            display=None,
        )

    if d.startswith("0"):
        d = d[1:]

    if d.startswith("55") and len(d) >= 12:
        d = d[2:]

    if len(d) < 10:
        return ImportPhoneParse(
            original=original,
            ddd=None,
            subscriber=None,
            normalized_national=None,
            kind="invalido",
            valid=False,
            e164=None,
            display=original,
        )

    ddd = d[:2]
    sub = d[2:]

    if not ddd.isdigit() or ddd == "00":
        return ImportPhoneParse(
            original=original,
            ddd=ddd,
            subscriber=sub,
            normalized_national=None,
            kind="invalido",
            valid=False,
            e164=None,
            display=original,
        )

    if len(sub) == 9 and sub.startswith("0"):
        sub = sub[1:]

    kind: PhoneImportKind
    if len(sub) == 9 and sub[0] == "9":
        kind = "celular"
    elif len(sub) == 8:
        kind = "fixo"
    else:
        return ImportPhoneParse(
            original=original,
            ddd=ddd,
            subscriber=sub,
            normalized_national=None,
            kind="invalido",
            valid=False,
            e164=None,
            display=original,
        )

    normalized = ddd + sub
    e164 = "+55" + normalized
    if kind == "celular":
        # (DD) 9 XXXX-XXXX — nove dígitos após o DDD
        display = f"({ddd}) {sub[0]} {sub[1:5]}-{sub[5:]}"
    else:
        display = f"({ddd}) {sub[:4]}-{sub[4:]}"

    return ImportPhoneParse(
        original=original,
        ddd=ddd,
        subscriber=sub,
        normalized_national=normalized,
        kind=kind,
        valid=True,
        e164=e164,
        display=display,
    )


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


def norm_nb_key(nb: Optional[str]) -> Optional[str]:
    """Chave estável para reimportação por NB (números sem zeros à esquerda)."""
    if nb is None:
        return None
    t = str(nb).strip()
    if not t:
        return None
    if t.isdigit():
        return t.lstrip("0") or "0"
    return t.casefold()


def norm_me_sheet_compare(val: Optional[str]) -> str:
    """Comparação estável do campo Setor (antigo ME): dígitos sem zeros à esquerda; texto sem acento e minúsculo."""
    if val is None or not str(val).strip():
        return ""
    t = str(val).strip()
    if t.isdigit():
        return t.lstrip("0") or "0"
    return _norm_nfd(t).lower()


def norm_cnpj_digits(raw: Optional[str]) -> Optional[str]:
    """Somente dígitos para casar CPF/CNPJ na reimportação."""
    if raw is None or not str(raw).strip():
        return None
    d = re.sub(r"\D", "", str(raw).strip())
    if len(d) < 11:
        return None
    return d


def find_col_map(columns: list, norm_func=None) -> dict:
    """Mapeia colunas do arquivo para campos padrão.

    Cabeçalhos esperados (modelo atual):
    NB, SETOR (código vendedor), Setor (antigo ME — segunda coluna cujo nome normaliza a "setor"),
    VISITA, FANTAS, Razão Social, CNPJ/CPF, MUNICÍPIO, BAIRRO, ENDEREÇO, FONE, SEGMENTO, STATUS, MESA (antigo SA).

    Compatível com planilhas antigas: ME, SA, uma única coluna SETOR.
    """
    if norm_func is None:
        def norm_func(s):
            s = (s or "").strip().lower()
            return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")

    col_map: dict = {}
    columns_stripped = [str(c).strip() for c in columns if str(c).strip()]

    # CNPJ/CPF
    for c in columns_stripped:
        n = norm_func(c)
        if "cnpj" in n and "cpf" in n:
            col_map["cnpj_cpf"] = c
            break
    if "cnpj_cpf" not in col_map:
        for c in columns_stripped:
            n = norm_func(c)
            if n in ("cnpj", "cpf"):
                col_map["cnpj_cpf"] = c
                break

    # SETOR (código vendedor) + coluna "Setor" (ME): duas colunas cujo nome vira "setor" após norm — ordem preserva
    setor_hits = [c for c in columns_stripped if norm_func(c) == "setor"]
    if len(setor_hits) >= 1:
        col_map["setor"] = setor_hits[0]
    if len(setor_hits) >= 2:
        col_map["me"] = setor_hits[1]
    if "me" not in col_map:
        for c in columns_stripped:
            if norm_func(c) == "me":
                col_map["me"] = c
                break

    for c in columns_stripped:
        n = norm_func(c)
        if n in ("sa", "mesa"):
            col_map["sa"] = c
            break

    used = set(col_map.values())
    singles = {
        "nb": ["nb"],
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
    for std, kws in singles.items():
        if std in col_map:
            continue
        for c in columns_stripped:
            if c in used:
                continue
            cn = norm_func(c)
            for kw in kws:
                kn = norm_func(kw)
                if cn == kn or (len(kn) >= 2 and kn in cn):
                    col_map[std] = c
                    used.add(c)
                    break
            if std in col_map:
                break
    return col_map
