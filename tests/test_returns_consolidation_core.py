# -*- coding: utf-8 -*-
"""Núcleo único de consolidação: paridade desktop/mobile e fechamento de série diária."""
from pathlib import Path
import sys

from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
from devolucoes_consolidado import (
    ajudante_returns_mobile_bundle,
    build_ajudante_consolidation_pure,
    build_motorista_consolidation_pure,
    consolidado_avaliar_resumo,
    load_ajustes_map,
    motorista_returns_mobile_bundle,
)


def _seed_base(session: Session):
    mot = models.Employee(registration_id="M1", name="Motorista Um", role="Motorista", status="active")
    aj = models.Employee(registration_id="A1", name="Ajudante Um", role="Ajudante", status="active")
    vend = models.Employee(registration_id="V1", name="Vendedor", role="Vendedor", status="active")
    cli = models.Client(name="Cliente X")
    session.add(mot)
    session.add(aj)
    session.add(vend)
    session.add(cli)
    session.commit()
    session.refresh(mot)
    session.refresh(aj)
    session.refresh(vend)
    session.refresh(cli)
    resp = models.DevolucaoResponsabilidade(nome="R_TEST")
    session.add(resp)
    session.commit()
    session.refresh(resp)
    motivo = models.DevolucaoMotivo(
        nome="Motivo", responsabilidade_id=resp.id, nome_normalizado="motivo"
    )
    session.add(motivo)
    session.commit()
    session.refresh(motivo)
    return mot, aj, vend, cli, motivo


def test_desktop_row_equals_motorista_bundle_row():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, _aj, vend, cli, motivo = _seed_base(session)
        route = models.Route(
            date="2026-04-01",
            shift="Manhã",
            employee_id=mot.id,
            client_id=cli.id,
            start_time="08:00",
            end_time="09:00",
            tonnage=100.0,
            type="delivery",
            valor_financeiro=500.0,
            delivery_status="entregue",
            status="completed",
        )
        session.add(route)
        d1 = models.Devolucao(
            data_romaneio="2026-04-01",
            data_entrega="2026-04-02",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            valor=50.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=1,
            semana=1,
            source="TEST",
        )
        d2 = models.Devolucao(
            data_romaneio="2026-04-01",
            data_entrega="2026-04-01",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            valor=30.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=1,
            semana=1,
            source="TEST",
        )
        session.add(d1)
        session.add(d2)
        session.commit()
        session.refresh(d1)
        session.refresh(d2)

        resumo = consolidado_avaliar_resumo(session, "2026-04-01", "2026-04-03")
        row_d = next(r for r in resumo["data"] if r["motorista_id"] == mot.id)
        bundle = motorista_returns_mobile_bundle(session, mot.id, "2026-04-01", "2026-04-03")
        assert row_d == bundle["row"]
        daily = bundle.get("_daily_by_iso") or {}
        assert "2026-04-01" in daily
        assert set(daily["2026-04-01"]["devolucao_ids"]) == {d1.id, d2.id}
        assert abs(sum(bundle["chart_values"]) - 80.0) < 1e-6
        assert bundle["_series_checks"]["sum_original_matches"]


def test_motorista_no_devolucoes_only_entregues():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, _a, _v, cli, _m = _seed_base(session)
        session.add(
            models.Route(
                date="2026-05-10",
                shift="Manhã",
                employee_id=mot.id,
                client_id=cli.id,
                start_time="08:00",
                end_time="09:00",
                tonnage=50.0,
                type="delivery",
                valor_financeiro=200.0,
                delivery_status="entregue",
                status="completed",
            )
        )
        session.commit()
        resumo = consolidado_avaliar_resumo(session, "2026-05-01", "2026-05-31")
        row_d = next(r for r in resumo["data"] if r["motorista_id"] == mot.id)
        assert row_d["devolucoes_total"] == 0
        assert row_d["entregues"] == 1
        b = motorista_returns_mobile_bundle(session, mot.id, "2026-05-01", "2026-05-31")
        assert b["row"] == row_d
        assert sum(b["chart_adjusted_values"]) == 0.0


def test_partial_motorista_adjustment_zero_adjusted_day():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, _a, vend, cli, motivo = _seed_base(session)
        session.add(
            models.Route(
                date="2026-06-01",
                shift="Manhã",
                employee_id=mot.id,
                client_id=cli.id,
                start_time="08:00",
                end_time="09:00",
                tonnage=50.0,
                type="delivery",
                valor_financeiro=100.0,
                delivery_status="entregue",
                status="completed",
            )
        )
        dev = models.Devolucao(
            data_romaneio="2026-06-01",
            data_entrega="2026-06-01",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            valor=40.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=1,
            semana=1,
            source="TEST",
        )
        session.add(dev)
        session.commit()
        session.refresh(dev)
        session.add(
            models.DevolucaoAjusteResponsabilidade(
                devolucao_id=dev.id, responsavel_motorista=False, responsavel_ajudante=True
            )
        )
        session.commit()

        ajustes = load_ajustes_map(session)
        ent_by_day = {"2026-06-01": 1}
        b = build_motorista_consolidation_pure(
            [dev], ent_by_day, "2026-06-01", "2026-06-01", ajustes, mot.id, "M", include_daily=True
        )
        assert b["row"]["valor_ajustado"] == 0.0
        assert b["row"]["devolucoes_attributed"] == 0
        day = b["_daily_by_iso"]["2026-06-01"]
        assert day["valor_original"] == 40.0
        assert day["valor_ajustado"] == 0.0
        assert day["devolucao_ids_ajustadas"] == []


def test_data_romaneio_not_data_entrega_for_bucket():
    """Devolução entra no dia do romaneio; data_entrega diferente não desloca a barra."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, _a, vend, cli, motivo = _seed_base(session)
        for dt in ("2026-07-01", "2026-07-02"):
            session.add(
                models.Route(
                    date=dt,
                    shift="Manhã",
                    employee_id=mot.id,
                    client_id=cli.id,
                    start_time="08:00",
                    end_time="09:00",
                    tonnage=50.0,
                    type="delivery",
                    valor_financeiro=100.0,
                    delivery_status="entregue",
                    status="completed",
                )
            )
        dev = models.Devolucao(
            data_romaneio="2026-07-01",
            data_entrega="2026-07-05",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            valor=25.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=1,
            semana=1,
            source="TEST",
        )
        session.add(dev)
        session.commit()
        session.refresh(dev)
        b = motorista_returns_mobile_bundle(session, mot.id, "2026-07-01", "2026-07-02")
        iso = b["chart_dates_iso"]
        idx = iso.index("2026-07-02")
        assert b["chart_values"][idx] == 0.0
        idx1 = iso.index("2026-07-01")
        assert b["chart_values"][idx1] == 25.0
        assert dev.id in (b["_daily_by_iso"]["2026-07-01"]["devolucao_ids"])


def test_pure_matches_desktop_after_refactor():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, _a, vend, cli, motivo = _seed_base(session)
        session.add(
            models.Route(
                date="2026-08-01",
                shift="Manhã",
                employee_id=mot.id,
                client_id=cli.id,
                start_time="08:00",
                end_time="09:00",
                tonnage=50.0,
                type="delivery",
                valor_financeiro=1000.0,
                delivery_status="entregue",
                status="completed",
            )
        )
        dev = models.Devolucao(
            data_romaneio="2026-08-01",
            data_entrega="2026-08-01",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            valor=100.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=1,
            semana=1,
            source="TEST",
        )
        session.add(dev)
        session.commit()

        resumo = consolidado_avaliar_resumo(session, "2026-08-01", "2026-08-07")
        row_d = next(r for r in resumo["data"] if r["motorista_id"] == mot.id)
        ajustes = load_ajustes_map(session)
        pure = build_motorista_consolidation_pure(
            [dev],
            {"2026-08-01": 1},
            "2026-08-01",
            "2026-08-07",
            ajustes,
            mot.id,
            "Motorista Um",
            include_daily=False,
        )
        assert pure["row"] == row_d


def test_ajudante_bundle_matches_desktop_when_ajudante_explicit():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, aj, vend, cli, motivo = _seed_base(session)
        session.add(
            models.Route(
                date="2026-09-01",
                shift="Manhã",
                employee_id=mot.id,
                client_id=cli.id,
                start_time="08:00",
                end_time="09:00",
                tonnage=50.0,
                type="delivery",
                valor_financeiro=300.0,
                delivery_status="entregue",
                status="completed",
                delivery_helpers_json=f"[{aj.id}]",
            )
        )
        dev = models.Devolucao(
            data_romaneio="2026-09-01",
            data_entrega="2026-09-01",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            ajudante_id=aj.id,
            valor=60.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=1,
            semana=1,
            source="TEST",
        )
        session.add(dev)
        session.commit()

        resumo = consolidado_avaliar_resumo(session, "2026-09-01", "2026-09-05")
        row_aj_list = [r for r in resumo["data_ajudantes"] if r["ajudante_id"] == aj.id]
        assert len(row_aj_list) == 1
        row_d = row_aj_list[0]
        bundle = ajudante_returns_mobile_bundle(session, aj.id, "2026-09-01", "2026-09-05")
        assert bundle["row"] == row_d
        assert bundle["_series_checks"]["sum_original_matches"]


def test_two_days_only_one_has_adjusted_value():
    """Dois dias com devolução: ajustado só em um dia não pode contaminar o outro."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, _aj, vend, cli, motivo = _seed_base(session)
        for dt in ("2026-10-01", "2026-10-02"):
            session.add(
                models.Route(
                    date=dt,
                    shift="Manhã",
                    employee_id=mot.id,
                    client_id=cli.id,
                    start_time="08:00",
                    end_time="09:00",
                    tonnage=10.0,
                    type="delivery",
                    valor_financeiro=100.0,
                    delivery_status="entregue",
                    status="completed",
                )
            )
        d1 = models.Devolucao(
            data_romaneio="2026-10-01",
            data_entrega="2026-10-01",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            valor=80.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=1,
            semana=1,
            source="TEST",
        )
        d2 = models.Devolucao(
            data_romaneio="2026-10-02",
            data_entrega="2026-10-02",
            client_id=cli.id,
            vendedor_id=vend.id,
            motorista_id=mot.id,
            valor=20.0,
            motivo_id=motivo.id,
            responsabilidade_id=motivo.responsabilidade_id,
            dia=2,
            semana=1,
            source="TEST",
        )
        session.add(d1)
        session.add(d2)
        session.commit()
        session.refresh(d1)
        session.refresh(d2)
        session.add(
            models.DevolucaoAjusteResponsabilidade(
                devolucao_id=d1.id, responsavel_motorista=False, responsavel_ajudante=True
            )
        )
        session.commit()

        b = motorista_returns_mobile_bundle(session, mot.id, "2026-10-01", "2026-10-02")
        iso = b["chart_dates_iso"]
        i1 = iso.index("2026-10-01")
        i2 = iso.index("2026-10-02")
        # Original dos dois dias, ajustado só no dia 2
        assert b["chart_values"][i1] == 80.0
        assert b["chart_values"][i2] == 20.0
        assert b["chart_adjusted_values"][i1] == 0.0
        assert b["chart_adjusted_values"][i2] == 20.0
        # Fechamento estrito
        assert abs(sum(b["chart_values"]) - b["row"]["valor_original"]) < 1e-6
        assert abs(sum(b["chart_adjusted_values"]) - b["row"]["valor_ajustado"]) < 1e-6


def test_period_with_empty_days_keeps_iso_axis_and_zero_bars():
    """Período com dias vazios deve manter eixo completo e barras zero nos dias sem devolução."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mot, _aj, vend, cli, motivo = _seed_base(session)
        # Só uma devolução no 1º dia; período inclui mais 2 dias vazios.
        session.add(
            models.Route(
                date="2026-11-01",
                shift="Manhã",
                employee_id=mot.id,
                client_id=cli.id,
                start_time="08:00",
                end_time="09:00",
                tonnage=10.0,
                type="delivery",
                valor_financeiro=100.0,
                delivery_status="entregue",
                status="completed",
            )
        )
        session.add(
            models.Devolucao(
                data_romaneio="2026-11-01",
                data_entrega="2026-11-01",
                client_id=cli.id,
                vendedor_id=vend.id,
                motorista_id=mot.id,
                valor=33.0,
                motivo_id=motivo.id,
                responsabilidade_id=motivo.responsabilidade_id,
                dia=1,
                semana=1,
                source="TEST",
            )
        )
        session.commit()

        b = motorista_returns_mobile_bundle(session, mot.id, "2026-11-01", "2026-11-03")
        assert b["chart_dates_iso"] == ["2026-11-01", "2026-11-02", "2026-11-03"]
        i2 = b["chart_dates_iso"].index("2026-11-02")
        i3 = b["chart_dates_iso"].index("2026-11-03")
        assert b["chart_values"][i2] == 0.0
        assert b["chart_adjusted_values"][i2] == 0.0
        assert b["chart_values"][i3] == 0.0
        assert b["chart_adjusted_values"][i3] == 0.0
        assert b["_series_checks"]["sum_original_matches"] is True
        assert b["_series_checks"]["sum_adjusted_matches"] is True
