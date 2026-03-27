# -*- coding: utf-8 -*-
"""Testes unitários para o service de Devoluções."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
from pathlib import Path
import sys

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
from devolucoes_service import (
    parse_valor_pt_br,
    compute_dia,
    compute_semana,
    compute_acima_300,
    compute_cluster,
    parse_date_dd_mm_yyyy,
    safe_date_str,
    normalize_code,
    normalize_name,
    resolve_vendedor,
    validate_row,
    validate_rows,
    DevolucaoRow,
    ValidationResult,
    persist_import_batch,
    sync_route_to_devolucao,
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
    assert parse_date_dd_mm_yyyy("2026-02-02") == datetime(2026, 2, 2)
    assert parse_date_dd_mm_yyyy(None) is None
    assert parse_date_dd_mm_yyyy("") is None


def test_parse_date_dd_mm_yyyy_nat_returns_none():
    """pd.NaT deve retornar None, nunca causar 500."""
    import pandas as pd
    assert parse_date_dd_mm_yyyy(pd.NaT) is None


def test_safe_date_str_nunca_levanta():
    """safe_date_str nunca lança exceção, mesmo com NaT/None."""
    import pandas as pd
    assert safe_date_str(None) == "-"
    assert safe_date_str(pd.NaT) == "-"
    assert safe_date_str(datetime(2026, 2, 2)) == "2026-02-02"


def test_validate_row_nao_lanca_quando_data_nat(monkeypatch):
    """Validação não lança exceção quando data é NaT/None (evita 500)."""
    import pandas as pd
    client = MagicMock()
    client.id = 1
    cad = {
        "client_by_nb": {},
        "client_by_name": {},
        "vendedor_by_code": {"110": MagicMock(id=2)},
        "vendedor_by_name_exact": {},
        "motorista_by_name": {"joao": MagicMock(id=3)},
        "resp_by_norm": {"r": MagicMock(id=4)},
        "motivo_by_norm": {"m": MagicMock(id=5)},
    }
    row = DevolucaoRow(
        data_romaneio=pd.NaT,
        data_entrega=pd.NaT,
        codigo="10",
        nome_cliente="X",
        vendedor="110",
        motorista="Joao",
        valor=100.0,
        motivo="m",
        observacao=None,
        responsabilidade="r",
        row_index=2,
    )
    result = validate_row(row, cad)
    assert result.valid is False
    reasons = [e["reason"] for e in result.errors]
    assert any("DATA ROMANEIO inválida" in r for r in reasons)


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


def test_sync_route_to_devolucao_reuses_matching_excel_without_creating_web_duplicate():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(
            registration_id="EMP-DEV-1",
            name="Motorista Teste",
            role="Motorista",
            status="active",
        )
        client = models.Client(name="Cliente Teste")
        resp = models.DevolucaoResponsabilidade(nome="COMERCIAL")
        session.add(employee)
        session.add(client)
        session.add(resp)
        session.commit()
        session.refresh(employee)
        session.refresh(client)
        session.refresh(resp)

        motivo = models.DevolucaoMotivo(
            nome="CLIENTE NÃO FEZ PEDIDO",
            responsabilidade_id=resp.id,
            nome_normalizado="cliente nao fez pedido",
        )
        session.add(motivo)
        session.commit()
        session.refresh(motivo)

        route_excel = models.Route(
            date="2026-03-17",
            shift="Manhã",
            employee_id=employee.id,
            client_id=client.id,
            start_time="08:00",
            end_time="13:55",
            tonnage=100.0,
            type="delivery",
            valor_financeiro=680.0,
            valor_devolucao=680.0,
            delivery_status="devolucao",
            status="completed",
            delivery_return_reason="CLIENTE NÃO FEZ PEDIDO",
            delivery_return_category="COMERCIAL",
            delivery_order_number="180",
            delivery_vehicle_plate="TXG3J89",
        )
        route_web = models.Route(
            date="2026-03-16",
            shift="Manhã",
            employee_id=employee.id,
            client_id=client.id,
            start_time="08:00",
            end_time="14:44",
            tonnage=100.0,
            type="delivery",
            valor_financeiro=680.0,
            valor_devolucao=680.0,
            delivery_status="devolucao",
            status="completed",
            delivery_return_reason="CLIENTE NÃO FEZ PEDIDO",
            delivery_return_category="COMERCIAL",
            delivery_order_number="180",
            delivery_vehicle_plate="TXG3J89",
        )
        session.add(route_excel)
        session.add(route_web)
        session.commit()
        session.refresh(route_excel)
        session.refresh(route_web)

        existing = models.Devolucao(
            route_id=route_excel.id,
            data_romaneio="2026-03-16",
            data_entrega="2026-03-17",
            client_id=client.id,
            vendedor_id=employee.id,
            motorista_id=employee.id,
            valor=680.0,
            motivo_id=motivo.id,
            responsabilidade_id=resp.id,
            dia=16,
            semana=12,
            acima_300="SIM",
            cluster="600-700",
            source="EXCEL",
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)

        synced = sync_route_to_devolucao(session, route_web, source="WEB")
        session.commit()

        rows = session.exec(select(models.Devolucao).order_by(models.Devolucao.id)).all()
        assert synced is not None
        assert synced.id == existing.id
        assert len(rows) == 1
        assert rows[0].source == "EXCEL"
        assert rows[0].route_id == route_excel.id


def test_sync_route_to_devolucao_preserves_existing_excel_source_for_same_route():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        employee = models.Employee(
            registration_id="EMP-DEV-2",
            name="Motorista Teste 2",
            role="Motorista",
            status="active",
        )
        client = models.Client(name="Cliente Teste 2")
        resp = models.DevolucaoResponsabilidade(nome="MERCADO")
        session.add(employee)
        session.add(client)
        session.add(resp)
        session.commit()
        session.refresh(employee)
        session.refresh(client)
        session.refresh(resp)

        motivo = models.DevolucaoMotivo(
            nome="SEM DINHEIRO / CHEQUE",
            responsabilidade_id=resp.id,
            nome_normalizado="sem dinheiro cheque",
        )
        route = models.Route(
            date="2026-03-16",
            shift="Tarde",
            employee_id=employee.id,
            client_id=client.id,
            start_time="08:00",
            end_time="12:35",
            tonnage=50.0,
            type="delivery",
            valor_financeiro=332.26,
            valor_devolucao=48.02,
            delivery_status="devolucao",
            status="completed",
            delivery_return_reason="SEM DINHEIRO / CHEQUE",
            delivery_return_category="MERCADO",
        )
        session.add(motivo)
        session.add(route)
        session.commit()
        session.refresh(motivo)
        session.refresh(route)

        existing = models.Devolucao(
            route_id=route.id,
            data_romaneio="2026-03-16",
            data_entrega="2026-03-17",
            client_id=client.id,
            vendedor_id=employee.id,
            motorista_id=employee.id,
            valor=48.02,
            motivo_id=motivo.id,
            responsabilidade_id=resp.id,
            dia=16,
            semana=12,
            acima_300="NAO",
            cluster="0-50",
            source="EXCEL",
        )
        session.add(existing)
        session.commit()

        synced = sync_route_to_devolucao(session, route, source="WEB")
        session.commit()

        refreshed = session.get(models.Devolucao, existing.id)
        assert synced is not None
        assert refreshed is not None
        assert refreshed.id == existing.id
        assert refreshed.source == "EXCEL"
