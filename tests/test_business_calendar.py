# -*- coding: utf-8 -*-
"""Regras de competência comercial (calendário de negócio)."""

from pathlib import Path
import sys
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.business_calendar import (
    competence_date_for_operation,
    competence_date_str,
    previous_business_day,
)


def test_primeiro_dia_util_do_mes_vai_para_ultimo_util_mes_anterior_mesmo_se_dia_anterior_foi_util():
    # Abril/2026: 31/03 terça útil, 01/04 quarta útil — competência de 01/04 deve ser março.
    d = date(2026, 4, 1)
    assert competence_date_for_operation(d) == date(2026, 3, 31)


def test_primeiro_dia_util_apos_feriado_e_fds_na_virada():
    # 01/05 feriado, 02-03 fds, 04/05 segunda — competência abril (ex.: 30/04).
    d = date(2026, 5, 4)
    assert competence_date_for_operation(d) == date(2026, 4, 30)


def test_segundo_dia_util_apos_primeiro_fica_no_proprio_mes():
    # Após 04/05 (primeiro útil), 05/05 terça segue 05/05 se anterior foi útil.
    d = date(2026, 5, 5)
    assert competence_date_for_operation(d) == date(2026, 5, 5)


def test_dia_nao_util_retorna_ultimo_util_anterior():
    d = date(2026, 5, 2)  # sábado
    assert competence_date_for_operation(d) == date(2026, 4, 30)


def test_competence_date_str_formato_iso():
    assert competence_date_str("2026-04-01") == "2026-03-31"


def test_janeiro_primeiro_util_vai_para_dezembro_anterior():
    # 01/01/2026 feriado; 02/01/2026 sexta — primeiro útil de jan → último útil antes de 01/01.
    d = date(2026, 1, 2)
    assert competence_date_for_operation(d) == previous_business_day(date(2026, 1, 1))
