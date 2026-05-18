# -*- coding: utf-8 -*-
"""Classificação, score e insights do BI Clientes (sem dependência de rotas FastAPI)."""

from __future__ import annotations

from typing import Any, Optional

# --- 1. Meta principal de devolução (fração 0–1); espelho em pontos % no restante do código ---
RETURN_RATE_TARGET = 0.02
META_DEVOLUCAO_VALOR_PCT = RETURN_RATE_TARGET * 100.0

# --- 2. Faixas da decision_strip (pct_gl e meta em pontos percentuais, ex.: 2.0 = 2%) ---
RETURN_RATE_ATTENTION_MAX = 0.03
DECISION_ATTENTION_MAX_PCT_POINTS = RETURN_RATE_ATTENTION_MAX * 100.0

# --- 3. Impacto evitável: texto especial na faixa Atenção ---
TREATABLE_ATTENTION_MIN_SHARE = 0.30
TREATABLE_ATTENTION_MIN_VALUE_BRL = 1500.00

# --- 4. Alerta secundário: período OK com oportunidade evitável ---
TREATABLE_OK_SECONDARY_MIN_SHARE = 0.35
TREATABLE_OK_SECONDARY_MIN_VALUE_BRL = 2000.00

# --- 5. Alerta secundário: muitos críticos (OK / Atenção); *_SHARE_PAIR_MIN = piso no max(., round(n*share)) ---
CRITICAL_OK_SECONDARY_MIN_SHARE = 0.12
CRITICAL_OK_SECONDARY_MIN_COUNT = 15
CRITICAL_OK_SECONDARY_SHARE_PAIR_MIN = 12

CRITICAL_ATTENTION_SECONDARY_MIN_SHARE = 0.10
CRITICAL_ATTENTION_SECONDARY_MIN_COUNT = 12
CRITICAL_ATTENTION_SECONDARY_SHARE_PAIR_MIN = 8

# --- 6. Prioridade “O que fazer primeiro” ---
FIRST_ACTION_TREATABLE_MIN_VALUE_BRL = 2500.00
FIRST_ACTION_TREATABLE_MIN_SHARE = 0.22
FIRST_ACTION_CRITICAL_MIN_SHARE = 0.09
FIRST_ACTION_CRITICAL_MIN_COUNT = 10
FIRST_ACTION_CRITICAL_MIN_BASE = 8
FIRST_ACTION_LARGE_RISK_MIN_SHARE = 0.025
FIRST_ACTION_LARGE_RISK_MIN_COUNT = 3
FIRST_ACTION_SMALL_HIGH_MIN_SHARE = 0.10
FIRST_ACTION_SMALL_HIGH_MIN_COUNT = 12

# --- 7. Ranking: volume mínimo entregue para % principal (sem micro-distorção) ---
MIN_VOLUME_ENTREGUE_PAR_RANKING_PCT_BRL = 2500.00

# --- 8. Ranking: baixo volume com distorção percentual ---
LOW_VOLUME_DISTORTION_MAX_DELIVERED_BRL = 2500.00
LOW_VOLUME_DISTORTION_MIN_RETURN_RATE = 0.08

# --- 9. Ranking: grandes com risco (piso em R$ entregue + % mínimo) ---
LARGE_RISK_MIN_RETURN_RATE = 0.02
LARGE_RISK_MIN_DELIVERED_FLOOR_BRL = 2500.00

# --- 10. Ranking: melhores clientes ---
BEST_CLIENT_MAX_RETURN_RATE = 0.02
BEST_CLIENT_MIN_SCORE = 72
BEST_CLIENT_AVG_TIME_FACTOR = 1.25
BEST_CLIENT_MIN_TIME_FALLBACK_MINUTES = 35.0

# --- 11. Cores do KPI índice de devolução (fração; no template multiplica-se por 100) ---
KPI_RETURN_RATE_DANGER = 0.03
KPI_RETURN_RATE_WARNING = 0.02


def safe_share(value: float, total: float) -> float:
    """Parte do total com denominador seguro (evita divisão por zero)."""
    t = max(float(total or 0.0), 1.0)
    return float(value or 0.0) / t


def client_recurrence_fields(row: dict) -> dict[str, Any]:
    """Visitas, devoluções e recorrência para ranking/listagem BI Clientes."""
    visits = max(0, int(row.get("visits") or 0))
    return_count = max(0, int(row.get("returned_occurrences") or row.get("return_count") or 0))
    pct = round((return_count / visits) * 100.0, 1) if visits > 0 else 0.0
    return {
        "return_count": return_count,
        "return_recurrence_pct": pct,
        "recurrence_label": f"{return_count} de {visits} visitas",
        "leader_reason": str(row.get("top_motivo_name") or "—"),
        "dominant_responsibility": str(row.get("top_responsabilidade_name") or "—"),
        "classification": str(row.get("classification_title") or "—"),
    }


def client_priority_label(row: dict) -> tuple[str, str]:
    """
    Rótulo de prioridade operacional para o ranking.
    Retorna (label, tone) com tone em danger | warn | ok | neutral.
    """
    rv = float(row.get("returned_value") or 0)
    rc = max(0, int(row.get("returned_occurrences") or row.get("return_count") or 0))
    rp = float(row.get("return_pct_planned") or row.get("return_rate_value") or 0)
    high_value = rv >= 800.0

    if rv <= 0.01 and rc == 0:
        return "Baixo risco", "ok"
    if high_value and rc >= 2:
        return "Crítico recorrente", "danger"
    if rc >= 3:
        return "Recorrente operacional", "danger"
    if high_value and rc == 1:
        return "Alto impacto financeiro", "warn"
    if rp >= 5.0 and rc <= 1:
        return "Pontual com impacto", "warn"
    if rv < 300.0 and rc <= 1:
        return "Baixo risco", "ok"
    return "Atenção", "neutral"


def is_many_critical(
    n_clients: int,
    critical_count: int,
    *,
    min_clients: int,
    min_share: float,
    abs_floor: int,
) -> bool:
    """Carteira mínima e contagem de críticos >= max(piso, round(n * share))."""
    nc = int(n_clients or 0)
    if nc < int(min_clients):
        return False
    return int(critical_count or 0) >= max(int(abs_floor), int(round(nc * float(min_share))))


def is_high_treatable(value: float, total_returned: float, min_value: float, min_share: float) -> bool:
    """Valor evitável acima do piso e participação mínima sobre o devolvido."""
    return float(value or 0.0) >= float(min_value) and safe_share(value, total_returned) >= float(min_share)


# Palavras-chave em motivos (normalizado lower) para valor financeiro "evitável"
TREATABLE_MOTIVO_FRAGMENTS = (
    "pedido errado",
    "produto errado",
    "pagamento",
    "preco errado",
    "preço errado",
    "cliente ausente",
    "horario",
    "horário",
    "nao entregue",
    "não entregue",
    "nao foi entregue",
)


def _norm(s: str) -> str:
    return str(s or "").strip().lower()


def dominio_operacional_por_motivo(motivo: str) -> str:
    """Agrupa motivo de devolução em Comercial, Logística, Mercado ou Sem classificação (Souza Pinto)."""
    m = _norm(motivo)
    if not m or m in ("-", "—", "nao informado", "não informado", "nao informado."):
        return "Sem classificação"

    comercial_frags = (
        "pedido / produto",
        "pedido errado",
        "produto errado",
        "preco errado",
        "preço errado",
        "prazo errado",
        "forma de pagamento",
        "pagamento errad",
        "pagamento errado",
        "cliente nao fez pedido",
        "cliente não fez pedido",
        "nao fez pedido",
        "não fez pedido",
        "nao solicitou",
        "não solicitou",
    )
    if any(f in m for f in comercial_frags):
        return "Comercial"

    logistica_frags = (
        "caminhao quebrado",
        "caminhão quebrado",
        "quebrado na rota",
        "pedido nao entregue",
        "pedido não entregue",
        "nao entregue",
        "não entregue",
        "produto danificado",
        "danificado",
        "falta de produto",
        "falta produto",
        "avaria na carga",
        "avaria",
        "separacao errada",
        "separação errada",
        "conferencia errada",
        "conferência errada",
    )
    if any(f in m for f in logistica_frags):
        return "Logística"

    if "horario" in m or "horário" in m:
        if any(x in m for x in ("atraso operac", "atraso operacional", "motorista", "rota", "separac", "conferenc", "carga", "frota")):
            return "Logística"
        if any(x in m for x in ("cliente", "fechado", "ausente", "janela", "loja", "ponto", "restricao", "restrição")):
            return "Mercado"
        return "Sem classificação"

    mercado_frags = (
        "fechado",
        "ausente",
        "ponto de venda fechado",
        "loja fechada",
        "cliente fechado",
        "sem dinheiro",
        "sem cheque",
        "cheque sem",
        "desistiu",
        "desistencia",
        "desistência",
        "desistencia da compra",
    )
    if any(f in m for f in mercado_frags):
        return "Mercado"

    return "Sem classificação"


def dominante_operacional_por_valor_devolvido(ranking_rows: list[dict[str, Any]]) -> tuple[str, str]:
    """Soma valor devolvido por domínio (via motivo principal do cliente) e retorna (rótulo, linha de apoio)."""
    acc: dict[str, float] = {}
    for r in ranking_rows or []:
        lab = dominio_operacional_por_motivo(str(r.get("top_motivo_name") or ""))
        acc[lab] = acc.get(lab, 0.0) + float(r.get("returned_value") or 0.0)
    if not acc or sum(acc.values()) <= 0:
        return "Sem classificação", "Sem devolução ou motivo mapeável no recorte."
    ranked = sorted(((k, v) for k, v in acc.items() if v > 0.0), key=lambda x: -x[1])
    if not ranked:
        return "Sem classificação", "Sem devolução ou motivo mapeável no recorte."
    best_k, best_v = ranked[0]
    tot = sum(v for _, v in ranked)
    share = round(100.0 * best_v / tot, 0) if tot > 0 else 0.0
    detail = f"{share:.0f}% do valor devolvido no recorte · demais áreas no restante"
    return best_k, detail


def build_decision_strip_intel(
    *,
    pct_gl: float,
    meta_pct: float,
    treatable_total: float,
    returned_total: float,
    critical_count: int,
    n_clients: int,
    main_motivo: str,
    main_responsibility: str,
    main_responsibility_detail: str,
) -> dict[str, Any]:
    """Classifica OK / Atenção / Crítico (2% e 3%) e textos operacionais Souza Pinto."""
    pct = float(pct_gl or 0.0)
    meta = float(meta_pct or META_DEVOLUCAO_VALOR_PCT)
    diff_pp = round(pct - meta, 2)
    share_treat = safe_share(float(treatable_total or 0.0), float(returned_total or 0.0))

    if pct <= meta + 1e-9:
        sit_key, sit_label = "ok", "Dentro da meta"
        hint = "Período dentro da meta. Manter acompanhamento dos clientes com maior recorrência."
    elif pct <= DECISION_ATTENTION_MAX_PCT_POINTS:
        sit_key, sit_label = "warn", "Atenção"
        if is_high_treatable(
            float(treatable_total or 0.0),
            float(returned_total or 0.0),
            TREATABLE_ATTENTION_MIN_VALUE_BRL,
            TREATABLE_ATTENTION_MIN_SHARE,
        ):
            hint = (
                f"Devolução acima da meta de {META_DEVOLUCAO_VALOR_PCT:.0f}%, mas com oportunidade clara de redução nos motivos tratáveis."
            )
        else:
            hint = "Devolução acima da meta. Priorizar clientes com motivos tratáveis e alto valor devolvido."
    else:
        sit_key, sit_label = "crit", "Crítico"
        hint = "Devolução em nível crítico. Exige ação conjunta entre Comercial, Logística e Mercado."

    secondary: Optional[str] = None
    if sit_key == "ok" and is_high_treatable(
        float(treatable_total or 0.0),
        float(returned_total or 0.0),
        TREATABLE_OK_SECONDARY_MIN_VALUE_BRL,
        TREATABLE_OK_SECONDARY_MIN_SHARE,
    ):
        secondary = (
            f"Alerta: R$ {_br_money(float(treatable_total))} em motivos tratáveis "
            f"({share_treat * 100:.0f}% do devolvido) — vale atacar antes da próxima leva, mantendo a classificação global na meta."
        )
    elif sit_key == "ok" and is_many_critical(
        n_clients,
        critical_count,
        min_clients=CRITICAL_OK_SECONDARY_MIN_COUNT,
        min_share=CRITICAL_OK_SECONDARY_MIN_SHARE,
        abs_floor=CRITICAL_OK_SECONDARY_SHARE_PAIR_MIN,
    ):
        secondary = (
            f"Alerta: {critical_count} cliente(s) crítico(s) no recorte — revisar lista prioritária mesmo com índice global na meta."
        )
    elif sit_key == "warn" and is_many_critical(
        n_clients,
        critical_count,
        min_clients=CRITICAL_ATTENTION_SECONDARY_MIN_COUNT,
        min_share=CRITICAL_ATTENTION_SECONDARY_MIN_SHARE,
        abs_floor=CRITICAL_ATTENTION_SECONDARY_SHARE_PAIR_MIN,
    ):
        secondary = (
            f"Alerta: {critical_count} cliente(s) crítico(s) — reforçar plano de ataque sem alterar a faixa principal (até {DECISION_ATTENTION_MAX_PCT_POINTS:.0f}%)."
        )

    return {
        "situation_key": sit_key,
        "situation_label": sit_label,
        "situation_hint": hint,
        "meta_pct": meta,
        "current_pct": pct,
        "diff_pp": diff_pp,
        "returned_value": float(returned_total or 0.0),
        "treatable_value": float(treatable_total or 0.0),
        "main_motivo": main_motivo,
        "main_responsibility": main_responsibility,
        "main_responsibility_raw": main_responsibility_detail,
        "secondary_note": secondary,
    }


def primeira_acao_prioridade_sp(
    *,
    treatable_total: float,
    returned_total: float,
    critical_count: int,
    large_risk_count: int,
    small_high_count: int,
    n_clients: int,
    fallback: str,
) -> str:
    """Define a recomendação principal por maior oportunidade operacional."""
    if is_high_treatable(
        float(treatable_total or 0.0),
        float(returned_total or 0.0),
        FIRST_ACTION_TREATABLE_MIN_VALUE_BRL,
        FIRST_ACTION_TREATABLE_MIN_SHARE,
    ):
        return (
            "Começar pelos clientes com devolução tratável: pedido, pagamento, ausência, horário, preço ou prazo."
        )
    if is_many_critical(
        n_clients,
        critical_count,
        min_clients=FIRST_ACTION_CRITICAL_MIN_BASE,
        min_share=FIRST_ACTION_CRITICAL_MIN_SHARE,
        abs_floor=FIRST_ACTION_CRITICAL_MIN_COUNT,
    ):
        return "Montar lista de ataque com Comercial e Logística para os clientes acima da meta."
    thr_lr = (
        max(FIRST_ACTION_LARGE_RISK_MIN_COUNT, int(round(n_clients * FIRST_ACTION_LARGE_RISK_MIN_SHARE)))
        if n_clients
        else FIRST_ACTION_LARGE_RISK_MIN_COUNT
    )
    if large_risk_count >= thr_lr:
        return (
            f"Priorizar clientes grandes acima de {META_DEVOLUCAO_VALOR_PCT:.0f}%, pois pequenas correções geram maior retorno financeiro."
        )
    thr_sh = (
        max(FIRST_ACTION_SMALL_HIGH_MIN_COUNT, int(round(n_clients * FIRST_ACTION_SMALL_HIGH_MIN_SHARE)))
        if n_clients
        else FIRST_ACTION_SMALL_HIGH_MIN_COUNT
    )
    if small_high_count >= thr_sh:
        return (
            "Revisar frequência, janela e confirmação dos clientes pequenos que consomem muito esforço operacional."
        )
    return (fallback or "Manter acompanhamento diário da carteira e revisar filtros na próxima leitura.").strip()


def _br_money(v: float) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = 0.0
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def treatable_return_value(motivos: Optional[dict[str, dict]], returned_value: float) -> float:
    """Soma valor devolvido cujo motivo principal ou qualquer motivo tratável concentra valor."""
    if not motivos or returned_value <= 0:
        return 0.0
    total = 0.0
    for mot, data in motivos.items():
        nm = _norm(mot)
        if any(f in nm for f in TREATABLE_MOTIVO_FRAGMENTS):
            total += float(data.get("value") or 0.0)
    return round(min(total, float(returned_value)), 2)


def treatable_motivo_breakdown(motivos: Optional[dict[str, dict]]) -> list[dict[str, Any]]:
    """Motivos tratáveis com valor (para drill-down do KPI impacto evitável)."""
    out: list[dict[str, Any]] = []
    if not motivos:
        return out
    for mot, data in motivos.items():
        nm = _norm(mot)
        if not any(f in nm for f in TREATABLE_MOTIVO_FRAGMENTS):
            continue
        v = float(data.get("value") or 0.0)
        if v <= 0:
            continue
        out.append(
            {
                "motivo": str(mot).strip() or "—",
                "value": round(v, 2),
                "count": int(data.get("count") or 0),
            }
        )
    out.sort(key=lambda x: -float(x["value"]))
    return out[:8]


def suggest_treatable_resolutions(
    *,
    treatable_motivos: list[dict[str, Any]],
    top_motivo_name: str,
    top_responsabilidade_name: str,
    classification_code: str,
    action_recommendation: str,
) -> list[str]:
    """
    Roteiro curto priorizado a partir de classificação, motivos tratáveis e macro de responsabilidade.

    Heurística fixa no código (sem chamada a modelo de ML externo).
    """
    tips: list[str] = []
    ar = str(action_recommendation or "").strip()
    if ar:
        tips.append(ar)
    code = str(classification_code or "").strip().upper()
    if code == "PEQUENO_ALTO_IMPACTO":
        tips.append("Cliente de menor volume: padronizar pedido e confirmação D-1 para reduzir retrabalho.")

    seen_mot: set[str] = set()
    for row in treatable_motivos[:6]:
        mot = _norm(str(row.get("motivo") or ""))
        if not mot or mot in seen_mot:
            continue
        seen_mot.add(mot)
        if "pagamento" in mot:
            tips.append("Pagamento: validar limite, forma e conciliação antes da próxima expedição.")
        elif "horário" in mot or "horario" in mot:
            tips.append("Horário/janela: atualizar cadastro e confirmar recebimento na véspera.")
        elif "cliente ausente" in mot or ("ausente" in mot and "cliente" in mot):
            tips.append("Ausência no local: SLA de segunda visita e confirmação de contato.")
        elif "pedido errado" in mot or "produto errado" in mot or "preço errado" in mot or "preco errado" in mot:
            tips.append("Pedido/produto/preço: checklist SKU, quantidade e tabela na separação.")
        elif "nao entregue" in mot or "não entregue" in mot or "nao foi entregue" in mot:
            tips.append("Não entregue: revisar roteirização, prioridade da parada e comunicação com o motorista.")

    tr = _norm(top_responsabilidade_name)
    if tr and tr not in ("-", "—", "nao informado", "não informado", "nao informado."):
        if "logist" in tr:
            tips.append(f"Macro {top_responsabilidade_name}: reforçar conferência de carga e documentação de rota.")
        elif "comercial" in tr or "cliente" in tr or "mercado" in tr:
            tips.append(f"Macro {top_responsabilidade_name}: alinhar expectativa e documentos comerciais antes da rota.")

    out: list[str] = []
    seen: set[str] = set()
    for t in tips:
        tt = t.strip()
        if not tt:
            continue
        key = tt.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tt)
        if len(out) >= 6:
            break
    return out


def large_risk_context_lines(row: dict[str, Any]) -> list[str]:
    """Por que o cliente aparece em 'grandes com risco' (% devolução alto + volume)."""
    rp = float(row.get("return_pct_planned") or 0)
    rv = float(row.get("returned_value") or 0)
    dv = float(row.get("delivered_value") or 0)
    ro = int(row.get("returned_occurrences") or 0)
    vi = int(row.get("visits") or 0)
    tm = str(row.get("top_motivo_name") or "").strip()
    tr = str(row.get("top_responsabilidade_name") or "").strip()
    lines: list[str] = [
        f"Índice de devolução sobre base comercial: {rp:.1f}% (referência interna > {META_DEVOLUCAO_VALOR_PCT:.0f}% indica risco).",
        f"Valor devolvido no período: R$ {_br_money(rv)} · valor entregue: R$ {_br_money(dv)}.",
    ]
    if vi > 0:
        lines.append(f"Paradas com registro: {vi}; ocorrências com devolução: {ro}.")
    if tm and tm not in ("-", "—"):
        lines.append(f"Motivo principal nas devoluções: {tm}.")
    if tr and tr not in ("-", "—", "Não informado", "nao informado"):
        lines.append(f"Responsabilidade dominante no valor devolvido: {tr}.")
    return lines[:6]


def large_risk_solution_lines(row: dict[str, Any]) -> list[str]:
    tips: list[str] = []
    ar = str(row.get("action_recommendation") or "").strip()
    if ar:
        tips.append(ar)
    tips.extend(_motivo_heuristic_lines(str(row.get("top_motivo_name") or "")))
    return _dedupe_tip_lines(tips, max_items=6)


def critical_client_context_lines(row: dict[str, Any]) -> list[str]:
    code = str(row.get("classification_code") or "").strip().upper()
    title = str(row.get("classification_title") or "").strip()
    rs = int(row.get("risk_score") or 0)
    rp = float(row.get("return_pct_planned") or 0)
    lines: list[str] = []
    if title:
        lines.append(f"Classificação: {title}.")
    elif code:
        lines.append(f"Perfil de classificação: {code}.")
    if rs >= 70:
        lines.append(f"Score de risco operacional elevado ({rs}/100 — combina devolução, tempo e recorrência).")
    if rp >= DECISION_ATTENTION_MAX_PCT_POINTS:
        lines.append(
            f"Índice de devolução (valor) {rp:.1f}% acima do patamar de atenção ({DECISION_ATTENTION_MAX_PCT_POINTS:.0f}%)."
        )
    rv = float(row.get("returned_value") or 0)
    if rv > 0:
        lines.append(f"Valor devolvido no período: R$ {_br_money(rv)}.")
    tm = str(row.get("top_motivo_name") or "").strip()
    if tm and tm not in ("-", "—"):
        lines.append(f"Motivo principal: {tm}.")
    if row.get("has_previous_data"):
        d = float(row.get("delta_return_rate_value") or 0)
        lines.append(f"Comparativo ao período anterior: variação do índice financeiro de devolução {d:+.1f} p.p.")
    return lines[:7]


def critical_client_solution_lines(row: dict[str, Any]) -> list[str]:
    tips: list[str] = []
    ar = str(row.get("action_recommendation") or "").strip()
    if ar:
        tips.append(ar)
    tips.extend(_motivo_heuristic_lines(str(row.get("top_motivo_name") or "")))
    if int(row.get("reopen_count") or 0) > 0:
        tips.append("Há reaberturas de entrega: revisar conferência de carga e comunicação com o cliente.")
    return _dedupe_tip_lines(tips, max_items=7)


def good_client_summary_line(row: dict[str, Any]) -> str:
    sc = int(row.get("cliente_score") or 0)
    rp = float(row.get("return_pct_planned") or 0)
    dv = float(row.get("delivered_value") or 0)
    title = str(row.get("classification_title") or "").strip() or str(row.get("classification_code") or "")
    return f"Score {sc} · {title} · devolução {rp:.1f}% · R$ entregue {_br_money(dv)}"


def _motivo_heuristic_lines(top_motivo: str) -> list[str]:
    m = _norm(top_motivo)
    out: list[str] = []
    if "pagamento" in m:
        out.append("Fluxo financeiro: antecipar validação de limite e forma de pagamento com o cliente.")
    if "horário" in m or "horario" in m or "janela" in m:
        out.append("Janela de atendimento: cruzar horário cadastrado com confirmação na véspera.")
    if "ausente" in m or "fechad" in m:
        out.append("Recebimento: reforçar contato e segunda tentativa com SLA definido.")
    if "pedido" in m and "err" in m:
        out.append("Qualidade do pedido: checklist comercial + separação (SKU, quantidade, preço).")
    return out


def _dedupe_tip_lines(tips: list[str], *, max_items: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tips:
        tt = str(t or "").strip()
        if not tt:
            continue
        k = tt.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(tt)
        if len(out) >= max_items:
            break
    return out


def impacto_operacional(
    return_pct_val: float,
    return_pct_stops: float,
    avg_duration_m: float,
    avg_duration_global: float,
    reopen_count: int,
) -> float:
    """Combinação linear pedida (pesos 4,3,2,1)."""
    dur_excess_ratio = 0.0
    if avg_duration_global > 0 and avg_duration_m > avg_duration_global:
        dur_excess_ratio = min(1.0, (avg_duration_m - avg_duration_global) / max(avg_duration_global, 1.0))
    return round(
        float(return_pct_val) * 4.0
        + float(return_pct_stops) * 3.0
        + dur_excess_ratio * 100.0 * 2.0
        + float(reopen_count) * 1.0,
        2,
    )


def score_cliente(
    delivered_value: float,
    return_pct_planned: float,
    avg_duration_m: float,
    avg_duration_global: float,
    returned_occurrences: int,
    visits: int,
    reopen_count: int,
) -> tuple[int, str, str, str, dict[str, float]]:
    """
    Score 0–100 (maior = melhor).
    Composição: compra até 25, devolução até 30, tempo até 20, recorrência até 15, reabertura até 10.
    Retorna (score, band, tone, class_text_short, parts dict for tooltip).
    """
    parts: dict[str, float] = {}

    # Compra (valor entregue vs referência — usa log suave)
    ref = max(delivered_value, 1.0)
    purchase_pts = min(25.0, 25.0 * (ref / (ref + 8000.0)))
    parts["compra"] = round(purchase_pts, 1)

    # Baixo índice de devolução por valor planejado
    dev_pts = max(0.0, 30.0 - min(30.0, return_pct_planned * 6.0))
    parts["devolucao"] = round(dev_pts, 1)

    # Tempo médio
    if avg_duration_global <= 0:
        time_pts = 15.0
    else:
        ratio = avg_duration_m / max(avg_duration_global, 1.0)
        if ratio <= 1.0:
            time_pts = 20.0
        elif ratio <= 1.35:
            time_pts = 14.0
        elif ratio <= 1.7:
            time_pts = 8.0
        else:
            time_pts = 3.0
    parts["tempo"] = round(time_pts, 1)

    # Recorrência devolução (visitas com devolução)
    rec_ratio = (returned_occurrences / max(visits, 1)) if visits else 0.0
    rec_pts = max(0.0, 15.0 - min(15.0, rec_ratio * 40.0))
    parts["recorrencia"] = round(rec_pts, 1)

    # Reaberturas
    reb_pts = max(0.0, 10.0 - min(10.0, reopen_count * 2.5))
    parts["reabertura"] = round(reb_pts, 1)

    total = int(round(min(100.0, max(0.0, purchase_pts + dev_pts + time_pts + rec_pts + reb_pts))))
    if total >= 80:
        band, tone = "Excelente", "success"
    elif total >= 60:
        band, tone = "Controlado", "neutral"
    elif total >= 40:
        band, tone = "Atenção", "warning"
    else:
        band, tone = "Crítico", "danger"
    return total, band, tone, band, parts


def classificacao_cliente(
    *,
    delivered_value: float,
    planned_value: float,
    returned_value: float,
    return_pct_planned: float,
    avg_duration_m: float,
    avg_duration_global: float,
    reopen_count: int,
    returned_occurrences: int,
    visits: int,
    median_delivered: float,
    p75_delivered: float,
    top_motivo_name: str,
    top_resp_name: str,
) -> tuple[str, str, str]:
    """
    Retorna (codigo, titulo, mensagem).
    codigo: PREMIUM_OPERACIONAL | ALTO_VALOR_RISCO | PEQUENO_ALTO_IMPACTO | CRITICO | ESTAVEL | OBSERVACAO
    """
    low_data = visits < 2 and delivered_value < 300

    pay_problem = any(
        x in _norm(top_motivo_name) + " " + _norm(top_resp_name)
        for x in ("pagamento", "financeiro", "ausente", "horario", "horário", "pedido errado", "produto errado")
    )

    is_high_return_pct = return_pct_planned >= META_DEVOLUCAO_VALOR_PCT * 1.5
    is_recurring = returned_occurrences >= 2
    high_reopen = reopen_count >= 2
    slow = avg_duration_global > 0 and avg_duration_m > avg_duration_global * 1.25

    # Crítico
    if (
        is_high_return_pct
        and (is_recurring or returned_value >= max(median_delivered * 0.5, 500))
        and (pay_problem or is_recurring)
    ):
        return (
            "CRITICO",
            "Cliente crítico",
            "Cliente exige plano de ação comercial/logístico.",
        )

    # Alto valor com risco
    if delivered_value >= p75_delivered and return_pct_planned > META_DEVOLUCAO_VALOR_PCT:
        return (
            "ALTO_VALOR_RISCO",
            "Alto valor com risco",
            "Cliente importante, mas precisa de acompanhamento para reduzir perdas.",
        )

    # Pequeno com alto impacto
    if delivered_value < median_delivered and (
        returned_value > 0 or slow or reopen_count > 0 or (returned_occurrences > 0 and visits <= 3)
    ):
        return (
            "PEQUENO_ALTO_IMPACTO",
            "Pequeno com alto impacto",
            "Cliente de baixo retorno e alto custo operacional.",
        )

    # Premium operacional
    if (
        delivered_value >= max(median_delivered, 1.0)
        and return_pct_planned <= META_DEVOLUCAO_VALOR_PCT
        and (avg_duration_global <= 0 or avg_duration_m <= avg_duration_global * 1.05)
        and reopen_count <= 1
        and returned_occurrences <= 1
    ):
        return (
            "PREMIUM_OPERACIONAL",
            "Cliente premium operacional",
            "Cliente saudável, bom volume e baixo impacto operacional.",
        )

    # Estável
    if (
        delivered_value >= median_delivered * 0.35
        and return_pct_planned <= META_DEVOLUCAO_VALOR_PCT * 1.2
        and reopen_count <= 2
    ):
        return (
            "ESTAVEL",
            "Cliente estável",
            "Cliente com comportamento operacional controlado.",
        )

    if low_data:
        return (
            "OBSERVACAO",
            "Em observação",
            "Necessário acompanhar por mais dias antes de concluir.",
        )

    return (
        "ESTAVEL",
        "Cliente estável",
        "Cliente com comportamento operacional controlado.",
    )


def acao_recomendada_por_classificacao(codigo: str, top_motivo: str, top_resp: str) -> str:
    if codigo == "CRITICO":
        return "Plano de ação conjunto comercial + logística; revisar cadastro e confirmação de entrega."
    if codigo == "ALTO_VALOR_RISCO":
        return "Monitorar devoluções e alinhar pedido/prazo com o vendedor antes da próxima rota."
    if codigo == "PEQUENO_ALTO_IMPACTO":
        return "Avaliar se o cliente compensa operacionalmente; reduzir retrabalho e janela."
    if codigo == "PREMIUM_OPERACIONAL":
        return "Manter relacionamento; replicar boas práticas de atendimento."
    if codigo == "OBSERVACAO":
        return "Coletar mais visitas no período antes de decisões drásticas."
    m = _norm(top_motivo)
    if "pagamento" in m:
        return "Confirmar forma de pagamento antes da rota."
    if "horário" in m or "horario" in m:
        return "Confirmar horário de recebimento e janela."
    return "Revisão operacional leve; manter monitoramento."


def build_operational_reading_cards(
    *,
    returned_total: float,
    delivered_total: float,
    planned_total: float,
    n_clients: int,
    n_above_meta: int,
    n_small_high_impact: int,
    top10_delivered_share_pct: float,
    main_motivo: str,
    main_resp: str,
    main_resp_value: float,
    treatable_value: float,
) -> list[dict[str, Any]]:
    """Cards da seção 'Leitura operacional' com texto resumido + contexto e sugestões para drill-down."""
    cards: list[dict[str, Any]] = []
    if returned_total > 0:
        cards.append(
            {
                "card_key": "impacto_financeiro",
                "title": "Impacto financeiro",
                "body": f"Os clientes do recorte concentram R$ {_br_money(returned_total)} em devoluções no período.",
                "context": [
                    f"Valor devolvido consolidado no recorte: R$ {_br_money(returned_total)}.",
                    f"Valor entregue no mesmo recorte (rotas): R$ {_br_money(delivered_total)}.",
                    f"Valor planejado nas paradas (referência): R$ {_br_money(planned_total)}.",
                    "O número inclui devoluções de rota e registros manuais vinculados ao período e aos filtros atuais.",
                ],
                "hints": [
                    "Abrir o ranking 'Top 10 · valor devolvido' e a tabela de clientes ordenada por R$ devolvido.",
                    "Cruzar com o card 'Motivo líder' e com o mapa de responsabilidades no painel executivo.",
                    "Priorizar reunião comercial + operação nos 5 maiores valores antes de ações amplas.",
                ],
            }
        )
    if n_small_high_impact > 0:
        cards.append(
            {
                "card_key": "baixo_retorno",
                "title": "Baixo retorno, alto custo",
                "body": f"{n_small_high_impact} cliente(s) compram pouco, mas geram tempo ou devolução acima da mediana.",
                "context": [
                    f"Contagem de clientes: {n_small_high_impact} em um universo de {n_clients} monitorados no recorte.",
                    "Critério: valor entregue abaixo da mediana do recorte e (devolução OU tempo médio acima da mediana OU reaberturas).",
                    "Indica desproporção entre esforço operacional (tempo, retrabalho) e faturamento entregue.",
                ],
                "hints": [
                    "Revisar janela, confirmação de presença e tamanho econômico do pedido nesses pontos.",
                    "Agrupar entregas ou ajustar frequência onde o custo por visita estiver alto.",
                    "Avaliar com comercial se o mix ou o dia de visita ainda faz sentido para o perfil da loja.",
                ],
            }
        )
    if top10_delivered_share_pct > 0:
        cards.append(
            {
                "card_key": "concentracao",
                "title": "Concentração",
                "body": f"Os 10 maiores clientes representam {top10_delivered_share_pct:.1f}% do valor entregue no período.",
                "context": [
                    f"Participação dos 10 maiores em relação ao total entregue no recorte: {top10_delivered_share_pct:.1f}%.",
                    "Concentração elevada aumenta risco de queda de serviço se poucos pontos falharem ao mesmo tempo.",
                ],
                "hints": [
                    "Garantir plano de contingência (frota e pessoal) nos dias de pico desses clientes.",
                    "Diversificar crescimento: metas por região ou vendedor para não depender só dos top 10.",
                ],
            }
        )
    if n_above_meta > 0:
        cards.append(
            {
                "card_key": "meta_2",
                "title": "Meta 2%",
                "body": f"{n_above_meta} cliente(s) estão acima da meta de {META_DEVOLUCAO_VALOR_PCT:.0f}% de devolução sobre valor planejado.",
                "context": [
                    f"Clientes acima da referência interna de {META_DEVOLUCAO_VALOR_PCT:.0f}% no índice '% dev. valor' (por cliente): {n_above_meta}.",
                    "O índice por cliente usa como base max(planejado, entregue, devolvido) para evitar distorção sem planejado.",
                    "Não confundir com o KPI global da tela, que usa a mesma filosofia agregada no período.",
                ],
                "hints": [
                    "Filtrar na tabela principal por '% dev. valor' e atuar primeiro nos maiores valores devolvidos.",
                    "Repetir análise após corrigir cadastro (preço, grade, janela) nos casos dominados por 'pedido/produto errado'.",
                    "Usar a classificação automática (crítico / alto risco) para priorizar visita ou call do responsável comercial.",
                ],
            }
        )
    if main_motivo and main_motivo not in ("-", "—"):
        mh = _motivo_heuristic_lines(main_motivo)
        cards.append(
            {
                "card_key": "motivo_lider",
                "title": "Motivo líder",
                "body": f"O principal motivo de devolução no período foi: {main_motivo}.",
                "context": [
                    f"Motivo mais frequente no recorte (ponderado por ocorrências): {main_motivo}.",
                    "Útil para alinhar treinamento de separação, comercial e mensagem ao motorista.",
                ],
                "hints": mh
                if mh
                else [
                    "Detalhar no BI Devoluções por motivo e por cliente para ver concentração.",
                    "Definir dono da ação (comercial, logística ou cadastro) conforme o subtipo do motivo.",
                ],
            }
        )
    if main_resp and main_resp not in ("-", "—"):
        mv = f"R$ {_br_money(main_resp_value)}"
        cards.append(
            {
                "card_key": "responsabilidade",
                "title": "Responsabilidade",
                "body": f"A responsabilidade com maior impacto financeiro foi {main_resp} ({mv} em devoluções).",
                "context": [
                    f"Macro de responsabilidade com maior soma de valor devolvido: {main_resp}.",
                    f"Valor aproximado associado: {mv} (pode sobrepor motivos no mesmo romaneio).",
                ],
                "hints": [
                    "Levar o número para a reunião da área dona do macro e quebrar por motivo e por cliente.",
                    "Se for Logística: foco em carga, documento e sequência de rota; se Comercial: pedido, preço e prazo.",
                    "Registrar ações corretivas com prazo e acompanhar queda no valor devolvido na próxima semana.",
                ],
            }
        )
    if treatable_value > 0:
        tv = f"R$ {_br_money(treatable_value)}"
        cards.append(
            {
                "card_key": "oportunidade",
                "title": "Oportunidade",
                "body": f"Há oportunidade de reduzir {tv} atuando nos motivos tratáveis (pedido, pagamento, horário, ausência).",
                "context": [
                    f"Estimativa de valor devolvido ligado a motivos considerados tratáveis no modelo atual: {tv}.",
                    "Motivos tratáveis incluem trechos como pedido errado, pagamento, horário, cliente ausente, não entregue, etc.",
                ],
                "hints": [
                    "No KPI 'Impacto evitável', abrir a lista de clientes e sugestões automáticas por motivo.",
                    "Padronizar checklist D-1 (confirmação de janela e pagamento) nos clientes que mais aparecem.",
                    "Medir queda desse montante após duas semanas de ação focada nos top casos.",
                ],
            }
        )
    if not cards:
        cards.append(
            {
                "card_key": "periodo_neutro",
                "title": "Período",
                "body": "Recorte sem alertas extremos; manter monitoramento semanal dos principais clientes.",
                "context": [
                    "Nenhum dos gatilhos habituais (volume de devolução, meta 2%, motivo dominante, etc.) disparou com força.",
                    "Continue acompanhando tendência semanal mesmo sem alerta vermelho.",
                ],
                "hints": [
                    "Manter revisão leve dos top 20 clientes por valor entregue.",
                    "Revalidar filtros (período curto demais pode esconder problema sazonal).",
                ],
            }
        )
    return cards[:8]


def pick_main_motivo_from_agg(macro_v: dict[str, float], motivo_rows: list[dict]) -> str:
    if motivo_rows:
        return str(motivo_rows[0].get("motivo") or motivo_rows[0].get("name") or "—")
    return "—"


def aggregate_treatable_from_rows(client_rows: list[dict]) -> float:
    s = 0.0
    for r in client_rows:
        s += float(r.get("treatable_returned_value") or 0.0)
    return round(s, 2)
