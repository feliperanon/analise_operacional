# -*- coding: utf-8 -*-
"""Testes para compatibilidade de colunas na cópia entre bancos PostgreSQL."""

import pytest

from scripts.copy_postgres_data import _build_copy_plan


def _target_column(
    name: str,
    *,
    is_nullable: bool = True,
    column_default: str | None = None,
    is_identity: bool = False,
    is_generated: bool = False,
) -> dict[str, object]:
    return {
        "name": name,
        "is_nullable": is_nullable,
        "column_default": column_default,
        "is_identity": is_identity,
        "is_generated": is_generated,
    }


def test_build_copy_plan_ignora_colunas_existentes_so_na_origem():
    plan = _build_copy_plan(
        ["id", "name", "flow_step", "flow_override_sector"],
        [
            _target_column("id", is_nullable=False, is_identity=True),
            _target_column("name", is_nullable=False),
        ],
        schema="public",
        table="employee",
    )

    assert plan["columns"] == ["id", "name"]
    assert plan["source_only"] == ["flow_step", "flow_override_sector"]
    assert plan["target_only"] == []


def test_build_copy_plan_permite_coluna_extra_no_destino_quando_ha_default():
    plan = _build_copy_plan(
        ["id", "name"],
        [
            _target_column("id", is_nullable=False, is_identity=True),
            _target_column("name", is_nullable=False),
            _target_column("created_at", is_nullable=False, column_default="now()"),
        ],
        schema="public",
        table="employee",
    )

    assert plan["columns"] == ["id", "name"]
    assert plan["target_only"] == ["created_at"]


def test_build_copy_plan_falha_quando_destino_exige_coluna_ausente_na_origem():
    with pytest.raises(RuntimeError, match="destino exige coluna\\(s\\) ausente\\(s\\) na origem"):
        _build_copy_plan(
            ["id", "name"],
            [
                _target_column("id", is_nullable=False, is_identity=True),
                _target_column("name", is_nullable=False),
                _target_column("tenant_id", is_nullable=False),
            ],
            schema="public",
            table="employee",
        )
