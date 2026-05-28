# -*- coding: utf-8 -*-
from client_import_utils import compute_entrega_from_visita, find_col_map


def test_compute_entrega_segunda_to_terca():
    assert compute_entrega_from_visita("SEGUNDA-FEIRA") == "TERÇA-FEIRA"


def test_compute_entrega_sexta_to_segunda():
    assert compute_entrega_from_visita("SEXTA-FEIRA") == "SEGUNDA-FEIRA"


def test_compute_entrega_quinta_to_sexta():
    assert compute_entrega_from_visita("QUINTA-FEIRA") == "SEXTA-FEIRA"


def test_compute_entrega_unknown_returns_none():
    assert compute_entrega_from_visita("Semanal") is None


def test_find_col_map_souza_pinto_columns():
    cols = [
        "NB",
        "SETOR",
        "MESA",
        "VISITA",
        "FANTASIA",
        "Municipio",
        "Bairro",
        "ENDEREÇO",
        "Telefone",
        "CNPJ/CPF",
        "SEGUNDA-FEIRAMENTO",
        "STATUS",
        "Razão Social",
        "Data Cadastro",
    ]
    m = find_col_map(cols)
    assert m.get("nb") == "NB"
    assert m.get("setor") == "SETOR"
    assert m.get("sa") == "MESA"
    assert m.get("fantas") == "FANTASIA"
    assert m.get("segmento") == "SEGUNDA-FEIRAMENTO"
    assert m.get("fone") == "Telefone"
