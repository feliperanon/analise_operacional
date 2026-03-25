from typing import Any, Dict, List


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _format_br_number(value: Any, decimals: int = 0) -> str:
    number = _as_float(value)
    formatted = f"{number:.{decimals}f}"
    integer, _, fraction = formatted.partition(".")
    integer = f"{int(float(integer)):,}".replace(",", ".")
    if decimals <= 0:
        return integer
    return f"{integer},{fraction}"


def _format_percent(value: Any, decimals: int = 1) -> str:
    return f"{_format_br_number(value, decimals)}%"


def prioritize_mobile_hub_modules(modules: List[Dict[str, Any]], priority_keys: List[str]) -> List[Dict[str, Any]]:
    if not modules:
        return []
    rank = {
        str(key or "").strip().lower(): idx
        for idx, key in enumerate(priority_keys or [])
        if str(key or "").strip()
    }
    decorated = list(enumerate(modules))
    decorated.sort(
        key=lambda item: (
            rank.get(str(item[1].get("key") or "").strip().lower(), len(rank) + 50),
            item[0],
        )
    )
    return [module for _, module in decorated]


def _theme_styles(profile_key: str) -> Dict[str, str]:
    theme_by_key = {
        "delivery_driver": {
            "badge_style": "background: rgba(59,130,246,0.16); color: #93c5fd;",
            "icon_style": "background: rgba(59,130,246,0.16); color: #93c5fd; border: 1px solid rgba(96,165,250,0.16);",
            "button_style": "background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); box-shadow: 0 18px 32px rgba(37,99,235,0.28);",
            "pill_style": "background: rgba(59,130,246,0.14); color: #bfdbfe; border: 1px solid rgba(96,165,250,0.14);",
            "accent_panel_style": "background: linear-gradient(180deg, rgba(30,58,138,0.28) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(96,165,250,0.18);",
            "accent_value_style": "color: #93c5fd;",
        },
        "delivery_helper": {
            "badge_style": "background: rgba(14,165,233,0.16); color: #7dd3fc;",
            "icon_style": "background: rgba(14,165,233,0.16); color: #7dd3fc; border: 1px solid rgba(56,189,248,0.18);",
            "button_style": "background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%); box-shadow: 0 18px 32px rgba(2,132,199,0.26);",
            "pill_style": "background: rgba(14,165,233,0.14); color: #bae6fd; border: 1px solid rgba(56,189,248,0.14);",
            "accent_panel_style": "background: linear-gradient(180deg, rgba(8,145,178,0.26) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(34,211,238,0.18);",
            "accent_value_style": "color: #67e8f9;",
        },
        "manage_routes": {
            "badge_style": "background: rgba(59,130,246,0.16); color: #93c5fd;",
            "icon_style": "background: rgba(59,130,246,0.16); color: #93c5fd; border: 1px solid rgba(96,165,250,0.16);",
            "button_style": "background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); box-shadow: 0 18px 32px rgba(29,78,216,0.28);",
            "pill_style": "background: rgba(59,130,246,0.14); color: #bfdbfe; border: 1px solid rgba(96,165,250,0.14);",
            "accent_panel_style": "background: linear-gradient(180deg, rgba(30,64,175,0.28) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(96,165,250,0.18);",
            "accent_value_style": "color: #93c5fd;",
        },
        "gatehouse": {
            "badge_style": "background: rgba(16,185,129,0.16); color: #6ee7b7;",
            "icon_style": "background: rgba(16,185,129,0.16); color: #6ee7b7; border: 1px solid rgba(52,211,153,0.18);",
            "button_style": "background: linear-gradient(135deg, #10b981 0%, #059669 100%); box-shadow: 0 18px 32px rgba(5,150,105,0.28);",
            "pill_style": "background: rgba(16,185,129,0.14); color: #d1fae5; border: 1px solid rgba(52,211,153,0.14);",
            "accent_panel_style": "background: linear-gradient(180deg, rgba(5,150,105,0.24) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(52,211,153,0.18);",
            "accent_value_style": "color: #6ee7b7;",
        },
        "checklist": {
            "badge_style": "background: rgba(245,158,11,0.16); color: #fbbf24;",
            "icon_style": "background: rgba(245,158,11,0.16); color: #fbbf24; border: 1px solid rgba(251,191,36,0.18);",
            "button_style": "background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); box-shadow: 0 18px 32px rgba(217,119,6,0.26);",
            "pill_style": "background: rgba(245,158,11,0.14); color: #fde68a; border: 1px solid rgba(251,191,36,0.14);",
            "accent_panel_style": "background: linear-gradient(180deg, rgba(180,83,9,0.24) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(251,191,36,0.18);",
            "accent_value_style": "color: #fbbf24;",
        },
        "returns": {
            "badge_style": "background: rgba(244,63,94,0.16); color: #fda4af;",
            "icon_style": "background: rgba(244,63,94,0.16); color: #fda4af; border: 1px solid rgba(251,113,133,0.18);",
            "button_style": "background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%); box-shadow: 0 18px 32px rgba(225,29,72,0.26);",
            "pill_style": "background: rgba(244,63,94,0.14); color: #fecdd3; border: 1px solid rgba(251,113,133,0.14);",
            "accent_panel_style": "background: linear-gradient(180deg, rgba(190,24,93,0.24) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(251,113,133,0.18);",
            "accent_value_style": "color: #fda4af;",
        },
        "escala": {
            "badge_style": "background: rgba(99,102,241,0.16); color: #c7d2fe;",
            "icon_style": "background: rgba(99,102,241,0.16); color: #c7d2fe; border: 1px solid rgba(129,140,248,0.18);",
            "button_style": "background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); box-shadow: 0 18px 32px rgba(79,70,229,0.26);",
            "pill_style": "background: rgba(99,102,241,0.14); color: #e0e7ff; border: 1px solid rgba(129,140,248,0.14);",
            "accent_panel_style": "background: linear-gradient(180deg, rgba(79,70,229,0.24) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(129,140,248,0.18);",
            "accent_value_style": "color: #c7d2fe;",
        },
    }
    default_styles = {
        "badge_style": "background: rgba(148,163,184,0.16); color: #e2e8f0;",
        "icon_style": "background: rgba(148,163,184,0.16); color: #e2e8f0; border: 1px solid rgba(148,163,184,0.18);",
        "button_style": "background: linear-gradient(135deg, #334155 0%, #1e293b 100%); box-shadow: 0 18px 32px rgba(15,23,42,0.24);",
        "pill_style": "background: rgba(148,163,184,0.14); color: #e2e8f0; border: 1px solid rgba(148,163,184,0.14);",
        "accent_panel_style": "background: linear-gradient(180deg, rgba(51,65,85,0.26) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(148,163,184,0.18);",
        "accent_value_style": "color: #e2e8f0;",
    }
    return theme_by_key.get(profile_key, default_styles)


def _decorate_stats(stats: List[Dict[str, Any]], accent_panel_style: str, accent_value_style: str) -> List[Dict[str, Any]]:
    tone_styles = {
        "success": {
            "panel_style": "background: linear-gradient(180deg, rgba(6,95,70,0.24) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(52,211,153,0.16);",
            "value_style": "color: #6ee7b7;",
        },
        "warning": {
            "panel_style": "background: linear-gradient(180deg, rgba(146,64,14,0.24) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(251,191,36,0.16);",
            "value_style": "color: #fbbf24;",
        },
        "danger": {
            "panel_style": "background: linear-gradient(180deg, rgba(159,18,57,0.24) 0%, rgba(15,23,42,0.88) 100%); border: 1px solid rgba(251,113,133,0.16);",
            "value_style": "color: #fda4af;",
        },
        "neutral": {
            "panel_style": "background: linear-gradient(180deg, rgba(30,41,59,0.88) 0%, rgba(15,23,42,0.92) 100%); border: 1px solid rgba(148,163,184,0.14);",
            "value_style": "color: #e2e8f0;",
        },
        "accent": {
            "panel_style": accent_panel_style,
            "value_style": accent_value_style,
        },
    }
    decorated: List[Dict[str, Any]] = []
    for stat in stats or []:
        tone = str(stat.get("tone") or "neutral").strip().lower()
        style = tone_styles.get(tone, tone_styles["neutral"])
        decorated.append({
            **stat,
            "panel_style": style["panel_style"],
            "value_style": style["value_style"],
        })
    return decorated


def build_mobile_hub_profile(
    *,
    access_flags: Dict[str, Any],
    modules: List[Dict[str, Any]],
    launcher_modules: List[Dict[str, Any]],
    delivery_summary: Dict[str, Any],
    active_routes: List[Dict[str, Any]],
    completed_routes: List[Dict[str, Any]],
    returns_alert: Dict[str, Any],
    checklist_summary: Dict[str, Any],
    gatehouse_summary: Dict[str, Any],
) -> Dict[str, Any]:
    access_flags = access_flags or {}
    modules = list(modules or [])
    launcher_modules = list(launcher_modules or [])
    delivery_summary = delivery_summary or {}
    returns_alert = returns_alert or {}
    checklist_summary = checklist_summary or {}
    gatehouse_summary = gatehouse_summary or {}

    delivery_total = _as_int(delivery_summary.get("total_today"))
    delivery_open = _as_int(delivery_summary.get("open_today"))
    delivery_completed = _as_int(delivery_summary.get("completed_today"))
    active_count = len(active_routes or [])
    completed_count = len(completed_routes or [])
    module_count = len(launcher_modules or modules)

    if access_flags.get("delivery_driver"):
        profile_key = "delivery_driver"
        primary_module_key = "delivery_start"
        stats = [
            {"label": "Paradas hoje", "value": _format_br_number(delivery_total), "hint": "liberadas", "tone": "accent"},
            {"label": "Em aberto", "value": _format_br_number(delivery_open), "hint": "aguardando baixa", "tone": "warning"},
            {"label": "Concluídas", "value": _format_br_number(delivery_completed), "hint": "finalizadas", "tone": "success"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Operação do motorista",
            "title": "Sua rota e seus módulos do dia",
            "description": "Abra a operação, acompanhe suas entregas e use os módulos complementares sem sair da home.",
            "icon": "truck",
            "primary_action": {"label": "Abrir rota", "href": "/mobile/delivery", "icon": "truck"},
            "section_heading": "Acessos complementares",
            "section_description": "Fluxos extras disponíveis para o seu cadastro operacional.",
            "empty_title": "Sem módulos complementares visíveis",
            "empty_description": "Sua operação principal continua disponível na rota de entregas.",
            "priority_keys": [primary_module_key, "checklist", "returns", "gatehouse", "manage_routes", "escala", "history"],
            "stats": stats,
        }
    elif access_flags.get("helper_only"):
        profile_key = "delivery_helper"
        primary_module_key = "active_route"
        stats = [
            {"label": "Rotas ativas", "value": _format_br_number(active_count), "hint": "em acompanhamento", "tone": "accent"},
            {"label": "Concluídas", "value": _format_br_number(completed_count), "hint": "encerradas no dia", "tone": "success"},
            {"label": "Paradas hoje", "value": _format_br_number(delivery_total), "hint": "vinculadas ao seu apoio", "tone": "neutral"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Acompanhamento do ajudante",
            "title": "Veja a rota ativa e o andamento do dia",
            "description": "Use esta home para entrar rápido na rota, acompanhar o progresso e acessar os módulos extras liberados.",
            "icon": "users",
            "primary_action": {"label": "Abrir rota ativa", "href": "/mobile/delivery", "icon": "map-pin"},
            "section_heading": "Apoios liberados",
            "section_description": "Outros módulos disponíveis para complementar sua rotina no dia.",
            "empty_title": "Somente a rota ativa está disponível",
            "empty_description": "Quando o motorista iniciar a operação, o acompanhamento ficará disponível aqui.",
            "priority_keys": [primary_module_key, "gatehouse", "manage_routes", "escala", "returns"],
            "stats": stats,
        }
    elif access_flags.get("admin_start"):
        profile_key = "manage_routes"
        primary_module_key = "manage_routes"
        pending_count = max(delivery_total - completed_count, 0)
        stats = [
            {"label": "Rotas ativas", "value": _format_br_number(active_count), "hint": "em progresso agora", "tone": "accent"},
            {"label": "Concluídas", "value": _format_br_number(completed_count), "hint": "baixadas no dia", "tone": "success"},
            {"label": "Pendências", "value": _format_br_number(pending_count), "hint": "ainda em aberto", "tone": "warning"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Gestão da operação",
            "title": "Monitoramento das entregas em tempo real",
            "description": "Acompanhe o avanço das rotas, identifique gargalos e entre direto no painel operacional.",
            "icon": "route",
            "primary_action": {"label": "Abrir monitoramento", "href": "/mobile/admin/routes", "icon": "route"},
            "section_heading": "Módulos liberados",
            "section_description": "Ferramentas complementares para consulta e apoio da operação.",
            "empty_title": "Painel de monitoramento pronto",
            "empty_description": "O acesso principal desta home continua sendo o acompanhamento das rotas.",
            "priority_keys": [primary_module_key, "gatehouse", "checklist", "returns", "escala", "history"],
            "stats": stats,
        }
    elif access_flags.get("gatehouse"):
        profile_key = "gatehouse"
        primary_module_key = "gatehouse"
        stats = [
            {"label": "Pendências", "value": _format_br_number(gatehouse_summary.get("total_pending")), "hint": "para conferência", "tone": "accent"},
            {"label": "Saídas", "value": _format_br_number(gatehouse_summary.get("pending_exit")), "hint": "aguardando liberação", "tone": "warning"},
            {"label": "Chegadas", "value": _format_br_number(gatehouse_summary.get("pending_arrival")), "hint": "aguardando retorno", "tone": "success"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Conferência de portaria",
            "title": "Saídas, chegadas e checklist do pátio",
            "description": "Valide KM, checklist e dados do motorista com uma entrada direta para o fluxo de portaria.",
            "icon": "shield",
            "primary_action": {"label": "Abrir portaria", "href": "/mobile/portaria", "icon": "shield"},
            "section_heading": "Fluxos liberados",
            "section_description": "Use os módulos abaixo para complementar a conferência operacional.",
            "empty_title": "Portaria pronta para uso",
            "empty_description": "O acesso principal desta home continua sendo a conferência de saída e chegada.",
            "priority_keys": [primary_module_key, "manage_routes", "checklist", "escala", "returns"],
            "stats": stats,
        }
    elif access_flags.get("checklist"):
        profile_key = "checklist"
        primary_module_key = "checklist"
        stats = [
            {"label": "Feitos hoje", "value": _format_br_number(checklist_summary.get("total_today")), "hint": "checklists enviados", "tone": "accent"},
            {"label": "Com apontamento", "value": _format_br_number(checklist_summary.get("issues_today")), "hint": "itens que exigem atenção", "tone": "warning"},
            {"label": "Dias pendentes", "value": _format_br_number(checklist_summary.get("missing_days")), "hint": "nos últimos 14 dias", "tone": "danger"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Rotina operacional",
            "title": "Checklist diário e histórico de pendências",
            "description": "Entre direto no checklist, acompanhe suas pendências e siga para os fluxos liberados no seu cadastro.",
            "icon": "clipboard-check",
            "primary_action": {"label": "Abrir checklist", "href": "/mobile/routine/checklist", "icon": "clipboard-check"},
            "section_heading": "Fluxos de apoio",
            "section_description": "Ferramentas adicionais disponíveis junto do checklist operacional.",
            "empty_title": "Checklist pronto para uso",
            "empty_description": "O seu acesso principal está centrado no checklist diário.",
            "priority_keys": [primary_module_key, "returns", "gatehouse", "escala", "manage_routes"],
            "stats": stats,
        }
    elif access_flags.get("returns"):
        profile_key = "returns"
        primary_module_key = "returns"
        returns_enabled = bool(returns_alert.get("enabled"))
        is_above_target = bool(returns_alert.get("is_above_target"))
        stats = [
            {"label": "Taxa atual", "value": _format_percent(returns_alert.get("actual_percent"), 2) if returns_enabled else "--", "hint": "janela monitorada", "tone": "accent"},
            {"label": "Meta", "value": _format_percent(returns_alert.get("target_percent"), 2) if returns_enabled else "--", "hint": "limite esperado", "tone": "neutral"},
            {"label": "Status", "value": "Acima" if (returns_enabled and is_above_target) else ("Dentro" if returns_enabled else "--"), "hint": "comparado com a meta", "tone": "danger" if is_above_target else "success"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Avaliação de devolução",
            "title": "Sua taxa de devolução em destaque",
            "description": "Abra o painel de devolução para avaliar resultado, meta e evolução do período.",
            "icon": "package-search",
            "primary_action": {"label": "Abrir devolução", "href": "/mobile/returns", "icon": "package-search"},
            "section_heading": "Módulos relacionados",
            "section_description": "Outros acessos liberados para apoiar sua análise operacional.",
            "empty_title": "Painel de devolução pronto",
            "empty_description": "O seu acesso principal está centrado no acompanhamento das devoluções.",
            "priority_keys": [primary_module_key, "checklist", "manage_routes", "gatehouse", "escala"],
            "stats": stats,
        }
    elif access_flags.get("escala"):
        profile_key = "escala"
        primary_module_key = "escala"
        stats = [
            {"label": "Módulos", "value": _format_br_number(module_count), "hint": "acessos disponíveis", "tone": "accent"},
            {"label": "Consulta", "value": "Escala", "hint": "visão operacional", "tone": "neutral"},
            {"label": "Status", "value": "Pronta", "hint": "home liberada para consulta", "tone": "success"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Consulta operacional",
            "title": "Escala e módulos liberados no seu perfil",
            "description": "Use esta home para abrir a escala e navegar para outros módulos liberados no seu cadastro.",
            "icon": "calendar-days",
            "primary_action": {"label": "Abrir escala", "href": "/mobile/escala", "icon": "calendar-days"},
            "section_heading": "Módulos liberados",
            "section_description": "Selecione um acesso habilitado para continuar.",
            "empty_title": "Escala pronta para consulta",
            "empty_description": "Quando novos acessos forem liberados, eles aparecerão aqui.",
            "priority_keys": [primary_module_key, "gatehouse", "manage_routes", "checklist", "returns"],
            "stats": stats,
        }
    else:
        profile_key = "hub"
        primary_module_key = str((launcher_modules[0] if launcher_modules else {}).get("key") or "").strip().lower()
        stats = [
            {"label": "Módulos", "value": _format_br_number(module_count), "hint": "liberados agora", "tone": "accent"},
        ]
        profile = {
            "key": profile_key,
            "eyebrow": "Acessos liberados",
            "title": "Central operacional",
            "description": "Os módulos abaixo foram liberados para o seu cadastro.",
            "icon": "layout-grid",
            "primary_action": None,
            "section_heading": "Seus módulos liberados",
            "section_description": "Escolha um módulo habilitado para continuar.",
            "empty_title": "Sem módulos visíveis nesta home",
            "empty_description": "Seu cadastro está ativo, mas não há acessos operacionais exibidos neste painel agora.",
            "priority_keys": [primary_module_key],
            "stats": stats,
        }

    ordered_launcher_modules = prioritize_mobile_hub_modules(launcher_modules, profile.get("priority_keys") or [])
    primary_key = str(profile.get("primary_module_key") or primary_module_key or "").strip().lower()
    pills = [
        str(module.get("label") or "").strip()
        for module in ordered_launcher_modules
        if str(module.get("key") or "").strip().lower() != primary_key and str(module.get("label") or "").strip()
    ][:3]

    theme = _theme_styles(profile_key)
    profile["primary_module_key"] = primary_key
    profile["ordered_launcher_modules"] = ordered_launcher_modules
    profile["pills"] = pills
    profile["stats"] = _decorate_stats(profile.get("stats") or [], theme["accent_panel_style"], theme["accent_value_style"])
    profile.update(theme)
    return profile
