# -*- coding: utf-8 -*-
"""Testes do perfil do hub mobile e priorização de módulos."""

from utils.mobile_hub import build_mobile_hub_profile, prioritize_mobile_hub_modules


def test_prioritize_mobile_hub_modules_preserves_priority_and_order():
    modules = [
        {"key": "manage_routes", "label": "Rotas"},
        {"key": "returns", "label": "Devolução"},
        {"key": "gatehouse", "label": "Portaria"},
        {"key": "checklist", "label": "Checklist"},
    ]

    ordered = prioritize_mobile_hub_modules(modules, ["gatehouse", "checklist"])

    assert [module["key"] for module in ordered] == [
        "gatehouse",
        "checklist",
        "manage_routes",
        "returns",
    ]


def test_build_mobile_hub_profile_for_gatehouse():
    launcher_modules = [
        {"key": "checklist", "label": "Checklist"},
        {"key": "gatehouse", "label": "Portaria"},
        {"key": "returns", "label": "Devolução"},
    ]

    profile = build_mobile_hub_profile(
        access_flags={"gatehouse": True},
        modules=list(launcher_modules),
        launcher_modules=list(launcher_modules),
        delivery_summary={},
        active_routes=[],
        completed_routes=[],
        returns_alert={},
        checklist_summary={},
        gatehouse_summary={
            "enabled": True,
            "total_pending": 6,
            "pending_exit": 2,
            "pending_arrival": 4,
        },
    )

    assert profile["key"] == "gatehouse"
    assert profile["primary_action"]["href"] == "/mobile/portaria"
    assert [module["key"] for module in profile["ordered_launcher_modules"]] == [
        "gatehouse",
        "checklist",
        "returns",
    ]
    assert profile["stats"][0]["value"] == "6"
    assert profile["stats"][1]["value"] == "2"
    assert profile["stats"][2]["value"] == "4"


def test_build_mobile_hub_profile_for_returns_formats_metrics():
    profile = build_mobile_hub_profile(
        access_flags={"returns": True},
        modules=[{"key": "returns", "label": "Devolução"}],
        launcher_modules=[{"key": "returns", "label": "Devolução"}],
        delivery_summary={},
        active_routes=[],
        completed_routes=[],
        returns_alert={
            "enabled": True,
            "actual_percent": 2.35,
            "target_percent": 2.0,
            "is_above_target": True,
        },
        checklist_summary={},
        gatehouse_summary={},
    )

    assert profile["key"] == "returns"
    assert profile["primary_action"]["href"] == "/mobile/returns"
    assert profile["stats"][0]["value"] == "2,35%"
    assert profile["stats"][1]["value"] == "2,00%"
    assert profile["stats"][2]["value"] == "Acima"


def test_build_mobile_hub_profile_for_driver_points_to_delivery():
    profile = build_mobile_hub_profile(
        access_flags={"delivery_driver": True},
        modules=[{"key": "delivery_start", "label": "Iniciar Entregas"}],
        launcher_modules=[{"key": "gatehouse", "label": "Portaria"}],
        delivery_summary={"total_today": 12, "open_today": 5, "completed_today": 7},
        active_routes=[{"status": "iniciada"}],
        completed_routes=[{"status": "entregue"} for _ in range(7)],
        returns_alert={},
        checklist_summary={},
        gatehouse_summary={},
    )

    assert profile["key"] == "delivery_driver"
    assert profile["primary_action"]["href"] == "/mobile/delivery"
    assert profile["stats"][0]["value"] == "12"
    assert profile["stats"][1]["value"] == "5"
    assert profile["stats"][2]["value"] == "7"
