# -*- coding: utf-8 -*-
"""Testes unitários para o service de Devoluções."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from devolucoes_service import (
    parse_valor_pt_br,
    compute_dia,
    compute_semana,
    compute_acima_300,
    compute_cluster,
    parse_date_dd_mm_yyyy,
    normalize_code,
    normalize_name,
    resolve_vendedor,
    validate_row,
    validate_rows,
    DevolucaoRow,
    ValidationResult,
    persist_import_batch,
)


def test_parse_valor_pt_br():
    assert parse_valor_pt_br("702,77") == 702.77
    assert parse_valor_pt_br("1.115,67") == 1115.67
    assert parse_valor_pt_br("10.149,20") == 10149.20
    assert parse_valor_pt_br("107,99") == 107.99
    assert parse_valor_pt_br(100.5) == 100.5
    assert parse_valor_pt_br(None) == 0.0
    assert parse_valor_pt_br("") == 0.0


def test_compute_dia():
    dt = datetime(2026, 2, 2)
    assert compute_dia(dt) == 2
    dt = datetime(2026, 12, 31)
    assert compute_dia(dt) == 31


def test_compute_semana():
    # 02/02/2026 cai na semana 6
    dt = datetime(2026, 2, 2)
    assert compute_semana(dt) == 6
    # 09/02/2026 na semana 7
    dt = datetime(2026, 2, 9)
    assert compute_semana(dt) == 7


def test_compute_acima_300():
    assert compute_acima_300(300.0) == "SIM"
    assert compute_acima_300(301.0) == "SIM"
    assert compute_acima_300(299.99) == "NAO"
    assert compute_acima_300(0.0) == "NAO"


def test_compute_cluster():
    assert compute_cluster(50) == "50-100"
    assert compute_cluster(49) == "0-50"
    assert compute_cluster(100) == "100-200"
    assert compute_cluster(702.77) == "700-800"
    assert compute_cluster(1200) == "Acima 1.200"
    assert compute_cluster(1500) == "Acima 1.200"


def test_parse_date_dd_mm_yyyy():
    assert parse_date_dd_mm_yyyy("02/02/2026") == datetime(2026, 2, 2)
    assert parse_date_dd_mm_yyyy("02-02-2026") == datetime(2026, 2, 2)
    assert parse_date_dd_mm_yyyy(None) is None
    assert parse_date_dd_mm_yyyy("") is None


def test_normalize_code():
    assert normalize_code(201) == "201"
    assert normalize_code("201") == "201"
    assert normalize_code(" 201 ") == "201"
    assert normalize_code(201.0) == "201"
    assert normalize_code("201.0") == "201"
    assert normalize_code("110.0") == "110"
    assert normalize_code("  108.0  ") == "108"
    assert normalize_code(None) is None
    assert normalize_code("") is None


def test_normalize_name():
    assert normalize_name("José Maria Cesar") == "jose maria cesar"
    assert normalize_name("  João  Silva  ") == "joao silva"
    assert normalize_name(None) is None
    assert normalize_name("") is None


def test_resolve_vendedor_por_seller_code():
    """201, '201', ' 201 ', 201.0 resolvem por seller_code."""
    emp = MagicMock()
    emp.id = 1
    emp.name = "Vendedor 201"
    emp.seller_code = "201"
    cad = {
        "vendedor_by_code": {"201": emp, "108": emp, "110": emp},
        "vendedor_by_name_exact": {},
    }
    v, err = resolve_vendedor(201, cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor("201", cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor(" 201 ", cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor(201.0, cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor("110.0", cad)
    assert v is emp
    assert err is None


def test_resolve_vendedor_por_nome():
    """José Maria Cesar resolve por nome (case-insensitive)."""
    emp = MagicMock()
    emp.id = 2
    emp.name = "José Maria Cesar"
    emp.seller_code = None
    cad = {
        "vendedor_by_code": {},
        "vendedor_by_name_exact": {"jose maria cesar": [emp]},
    }
    v, err = resolve_vendedor("José Maria Cesar", cad)
    assert v is emp
    assert err is None
    v, err = resolve_vendedor("jose maria cesar", cad)
    assert v is emp
    assert err is None


def test_resolve_vendedor_ambiguo():
    """Nome ambíguo retorna erro de ambiguidade."""
    emp1 = MagicMock()
    emp1.id = 1
    emp2 = MagicMock()
    emp2.id = 2
    cad = {
        "vendedor_by_code": {},
        "vendedor_by_name_exact": {"joao silva": [emp1, emp2]},
    }
    v, err = resolve_vendedor("João Silva", cad)
    assert v is None
    assert "ambíguo" in err
    assert "João Silva" in err


def test_resolve_vendedor_numerico_nao_encontrado():
    """Valor numérico sem seller_code: erro direto, sem tentar nome."""
    cad = {
        "vendedor_by_code": {},
        "vendedor_by_name_exact": {},
    }
    v, err = resolve_vendedor(999, cad)
    assert v is None
    assert "seller_code" in err


def test_get_cadastro_health_vendedor_by_code_vazio():
    """Quando vendedor_by_code vazio, retorna erro global."""
    from devolucoes_service import get_cadastro_health

    cad = {
        "employees": [MagicMock()],
        "employees_with_seller_code": 0,
        "vendedor_by_code": {},
        "clients": [MagicMock()],
        "client_by_nb": {"x": MagicMock()},
        "motivos": [MagicMock()],
        "resp_list": [MagicMock()],
    }
    diag, errors = get_cadastro_health(cad)
    assert len(errors) > 0
    assert any("seller_code" in e or "vendedor" in e.lower() for e in errors)


def test_get_cadastro_health_ok():
    """Quando cadastros ok, global_errors vazio."""
    from devolucoes_service import get_cadastro_health

    cad = {
        "employees": [MagicMock()],
        "employees_with_seller_code": 2,
        "vendedor_by_code": {"110": MagicMock(), "201": MagicMock()},
        "clients": [MagicMock()],
        "client_by_nb": {"x": MagicMock()},
        "motivos": [MagicMock()],
        "resp_list": [MagicMock()],
    }
    diag, errors = get_cadastro_health(cad)
    assert len(errors) == 0
    assert diag["vendedor_by_code_size"] == 2


def test_validate_rows_global_error_quando_vendedor_vazio(monkeypatch):
    """Quando vendedor_by_code vazio, validate_rows retorna global_errors, não N erros por linha."""
    from devolucoes_service import validate_rows, _load_cadastros, get_cadastro_health

    cad_vazio_vendedor = {
        "employees": [MagicMock()],
        "employees_with_seller_code": 0,
        "vendedor_by_code": {},
        "clients": [MagicMock()],
        "client_by_nb": {"x": MagicMock()},
        "motivos": [MagicMock()],
        "resp_list": [MagicMock()],
        "client_by_name": {},
        "vendedor_by_name_exact": {},
        "motorista_by_name": {},
        "motivo_by_norm": {},
        "motivo_resp_map": {},
        "resp_by_norm": {},
    }

    def fake_load(_session):
        return cad_vazio_vendedor

    monkeypatch.setattr("devolucoes_service._load_cadastros", fake_load)
    from devolucoes_service import DevolucaoRow
    from datetime import datetime

    rows = [
        DevolucaoRow(
            data_romaneio=datetime(2026, 2, 2),
            data_entrega=datetime(2026, 2, 2),
            codigo="x",
            nome_cliente="Cliente X",
            vendedor="110",
            motorista="Motorista",
            valor=100.0,
            motivo="x",
            observacao=None,
            responsabilidade="x",
            row_index=i + 2,
        )
        for i in range(5)
    ]
    valid, invalid, _, _, global_errors = validate_rows(rows, MagicMock())
    assert len(global_errors) > 0
    assert len(invalid) == 0
    assert len(valid) == 0


def test_get_cadastro_health_com_seller_code_duplicado():
    from devolucoes_service import get_cadastro_health
    cad = {
        "employees": [MagicMock(), MagicMock()],
        "employees_with_seller_code": 2,
        "vendedor_by_code": {"110": MagicMock()},
        "clients": [MagicMock()],
        "client_by_nb": {"x": MagicMock()},
        "motivos": [MagicMock()],
        "resp_list": [MagicMock()],
        "seller_code_collisions": {"110": [1, 2]},
    }
    diag, errors = get_cadastro_health(cad)
    assert diag["seller_code_duplicates_count"] == 1
    assert any("duplicado" in e.lower() for e in errors)


def test_validate_row_rejeita_data_invertida_e_valor_zero():
    client = MagicMock()
    client.id = 1
    vendedor = MagicMock()
    vendedor.id = 2
    motorista = MagicMock()
    motorista.id = 3
    resp = MagicMock()
    resp.id = 4
    motivo = MagicMock()
    motivo.id = 5
    motivo.nome_normalizado = "pedidoerrado"

    row = DevolucaoRow(
        data_romaneio=datetime(2026, 2, 10),
        data_entrega=datetime(2026, 2, 9),
        codigo="123",
        nome_cliente="Cliente",
        vendedor="201",
        motorista="Joao",
        valor=0.0,
        motivo="Pedido errado",
        observacao=None,
        responsabilidade="COMERCIAL",
        row_index=2,
    )
    cad = {
        "client_by_nb": {"123": client},
        "client_by_name": {"cliente": client},
        "vendedor_by_code": {"201": vendedor},
        "vendedor_by_name_exact": {},
        "motorista_by_name": {"joao": motorista},
        "resp_by_norm": {"comercial": resp},
        "motivo_by_norm": {"pedido errado": motivo, "pedidoerrado": motivo},
    }
    result = validate_row(row, cad)
    assert result.valid is False
    reasons = [e["reason"] for e in result.errors]
    assert any("Data entrega anterior" in r for r in reasons)
    assert any("maior que zero" in r for r in reasons)


def test_validate_rows_detecta_duplicidade_no_arquivo(monkeypatch):
    def fake_load(_session):
        return {}
    def fake_health(_cad):
        return {}, []
    def fake_validate(_row, _cad):
        return ValidationResult(
            valid=True,
            client_id=1,
            vendedor_id=2,
            motorista_id=3,
            ajudante_id=None,
            motivo_id=4,
            responsabilidade_id=5,
        )

    monkeypatch.setattr("devolucoes_service._load_cadastros", fake_load)
    monkeypatch.setattr("devolucoes_service.get_cadastro_health", fake_health)
    monkeypatch.setattr("devolucoes_service.validate_row", fake_validate)

    row_a = DevolucaoRow(
        data_romaneio=datetime(2026, 2, 2),
        data_entrega=datetime(2026, 2, 2),
        codigo="10",
        nome_cliente="A",
        vendedor="201",
        motorista="M",
        valor=100.0,
        motivo="X",
        observacao=None,
        responsabilidade="R",
        row_index=2,
    )
    row_b = DevolucaoRow(
        data_romaneio=datetime(2026, 2, 2),
        data_entrega=datetime(2026, 2, 2),
        codigo="10",
        nome_cliente="A",
        vendedor="201",
        motorista="M",
        valor=100.0,
        motivo="X",
        observacao=None,
        responsabilidade="R",
        row_index=3,
    )
    valid, invalid, _, _, global_errors = validate_rows([row_a, row_b], MagicMock())
    assert global_errors == []
    assert len(valid) == 1
    assert len(invalid) == 1
    assert "Duplicidade no arquivo" in invalid[0]["errors"][0]["reason"]


def test_persist_import_batch_grava_batch_erros_e_staging():
    class FakeSession:
        def __init__(self):
            self.added = []
        def add(self, obj):
            if obj.__class__.__name__ == "DevolucaoImportBatch" and getattr(obj, "id", None) is None:
                obj.id = 999
            self.added.append(obj)
        def flush(self):
            return None

    session = FakeSession()
    rows = [
        DevolucaoRow(
            data_romaneio=datetime(2026, 2, 2),
            data_entrega=datetime(2026, 2, 2),
            codigo="10",
            nome_cliente="A",
            vendedor="201",
            motorista="M",
            valor=100.0,
            motivo="X",
            observacao=None,
            responsabilidade="R",
            row_index=2,
        )
    ]
    invalid = [{
        "row_index": 2,
        "errors": [{"column": "VENDEDOR", "value": "201", "reason": "Nao cadastrado"}],
    }]
    batch_id = persist_import_batch(
        session=session,
        filename="arquivo.xlsx",
        rows=rows,
        valid_rows=[],
        invalid_rows=invalid,
        created_by="tester",
        create_staging=True,
    )
    assert batch_id == 999
    types = [x.__class__.__name__ for x in session.added]
    assert "DevolucaoImportBatch" in types
    assert "DevolucaoImportRowError" in types
    assert "DevolucaoStaging" in types
