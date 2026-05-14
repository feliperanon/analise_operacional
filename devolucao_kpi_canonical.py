"""
Indicadores canônicos de devolução (BI / Central / TV).

Operacional (% rotas):
- Numerador: rotas com status normalizado = devolução.
- Denominador: rotas concluídas (entregue ou devolução), mesmo type=delivery.
- Exceção: status devolução com motivo de encerramento tardio automático (variações de texto,
  sem acentos na comparação) conta como entregue — alinhado ao painel TV e ao consolidado BI Entregas.

Financeiro (valor) — KPI meta ≤ 2% (BI Devoluções / Central / TV):
- Numerador: soma `Devolucao.valor` no período, **competência operacional** (mesma regra de
  `competence_date_str` em data de entrega ou romaneio), excluindo `duplicate_of_id`.
- Denominador: soma nas rotas `type=delivery` cuja **competência** da `Route.date` cai no período:
  `valor_financeiro` quando informado; se a rota for devolução sem `valor_financeiro`, usa
  `valor_devolucao` (paridade com `pct_valor_devolvido_sobre_base_rotas`).
- BI Entregas / Clientes / Vendedor podem exibir **outros** índices (ex.: devolvido ÷ planejado,
  ou devoluções ÷ faturamento do vendedor); o rótulo deixa explícito quando não for este KPI.

Projeção fim de mês:
- `build_mes_fim_projecao_pct_rotas`: % paradas (operacional), média por dia da semana no histórico pré-mês.
- `build_mes_fim_projecao_pct_financeiro`: % valor devolvido sobre faturamento (mesma lógica do KPI financeiro),
  projetando numerador e denominador por dia da semana no histórico pré-mês; não é modelo de ML externo.
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
import math
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

_DONE_STATUSES = frozenset({"entregue", "devolucao"})


def _normalize_return_reason_for_match(val: Optional[str]) -> str:
    """Maiúsculas + sem acentos para comparação tolerante de motivo (igual critério do painel TV)."""
    s = (val or "").strip().upper()
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def is_encerramento_tardio_automatico_return(reason_raw: Optional[str]) -> bool:
    """True se o motivo da rota indica encerramento tardio automático (não conta como devolução operacional)."""
    r = _normalize_return_reason_for_match(reason_raw)
    if not r:
        return False
    if r == "ENCERRAMENTO TARDIO AUTOMATICO":
        return True
    return "ENCERRAMENTO" in r and "TARDIO" in r and "AUTOMATICO" in r


def normalized_delivery_status(route: Any) -> str:
    raw = (getattr(route, "delivery_status", None) or "").strip().lower()
    if raw == "devolucao":
        if is_encerramento_tardio_automatico_return(getattr(route, "delivery_return_reason", None)):
            return "entregue"
    return raw


def counts_devolucao_rotas_concluidas(routes: Iterable[Any]) -> Tuple[int, int]:
    """Retorna (qtd_devolucoes, qtd_rotas_concluidas) no critério canônico."""
    n_done = 0
    n_ret = 0
    for r in routes:
        s = normalized_delivery_status(r)
        if s in _DONE_STATUSES:
            n_done += 1
            if s == "devolucao":
                n_ret += 1
    return n_ret, n_done


def pct_devolucao_sobre_rotas_concluidas(routes: Iterable[Any]) -> float:
    n_ret, n_done = counts_devolucao_rotas_concluidas(routes)
    return round((n_ret / n_done * 100.0), 1) if n_done else 0.0


def devolucao_competencia_iso(d: Any) -> str:
    """Data YYYY-MM-DD de competência do cadastro Devolucao (entrega ou romaneio)."""
    from utils.business_calendar import competence_date_str

    raw_ent = getattr(d, "data_entrega", None)
    raw_rom = getattr(d, "data_romaneio", None)
    comp = competence_date_str(raw_ent or raw_rom)
    if comp and len(str(comp).strip()) >= 10:
        return str(comp).strip()[:10]
    rom = str(raw_rom or "").strip()[:10]
    return rom if len(rom) == 10 else ""


def devolucao_competencia_in_period(d: Any, period_start: str, period_end: str) -> bool:
    comp = devolucao_competencia_iso(d)
    return bool(comp) and len(comp) == 10 and period_start <= comp <= period_end


def route_competencia_operacional_iso(route: Any) -> str:
    """Competência da data operacional da rota de entrega (Route.date)."""
    from utils.business_calendar import competence_date_str

    raw = getattr(route, "date", None)
    comp = competence_date_str(raw) if raw else ""
    if comp and len(str(comp).strip()) >= 10:
        return str(comp).strip()[:10]
    s = str(raw or "").strip()[:10]
    return s if len(s) == 10 else ""


def route_competencia_in_period(route: Any, period_start: str, period_end: str) -> bool:
    comp = route_competencia_operacional_iso(route)
    return bool(comp) and period_start <= comp <= period_end


def route_base_financeiro_kpi(route: Any) -> Optional[float]:
    """
    Contribuição de uma rota ao denominador do KPI financeiro (faturamento/base R$),
    ou None se a rota não entra na base (sem valor financeiro e sem fallback de devolução).
    """
    vf = getattr(route, "valor_financeiro", None)
    if vf is not None:
        return float(vf)
    if normalized_delivery_status(route) == "devolucao":
        vd = getattr(route, "valor_devolucao", None)
        if vd is not None:
            return float(vd)
    return None


def pct_valor_devolvido_sobre_base_rotas(valor_devolvido: float, routes_delivery: Iterable[Any]) -> Tuple[Optional[float], float]:
    """% valor devolvido (cadastro agregado) sobre base R$ nas rotas do mesmo recorte."""
    base = 0.0
    for r in routes_delivery:
        contrib = route_base_financeiro_kpi(r)
        if contrib is not None:
            base += contrib
    if base <= 0:
        return None, 0.0
    pct = round(100.0 * float(valor_devolvido or 0) / base, 2)
    if not math.isfinite(pct):
        return None, round(base, 2)
    return pct, round(base, 2)


def _route_operational_day_iso(route: Any) -> str:
    s = str(getattr(route, "date", None) or "").strip()[:10]
    return s if len(s) == 10 else ""


def group_routes_by_operational_day(routes: Iterable[Any]) -> Dict[str, List[Any]]:
    """Agrupa rotas pela data operacional (YYYY-MM-DD)."""
    out: Dict[str, List[Any]] = {}
    for r in routes:
        d = _route_operational_day_iso(r)
        if len(d) != 10:
            continue
        out.setdefault(d, []).append(r)
    return out


def build_mes_fim_projecao_pct_rotas(
    date_i: date,
    date_f: date,
    routes_periodo: Iterable[Any],
    routes_baseline: Iterable[Any],
    *,
    meta_pp: float = 2.0,
    min_baseline_days: int = 14,
) -> Optional[Dict[str, Any]]:
    """
    Estimativa do % devolução (rotas) ao último dia do mês, para recorte mensal parcial.

    Usa perfil por dia da semana: para cada DOW, a média de (n_ret, n_done) por *dia calendário*
    no histórico baseline (normalmente ~18 semanas antes do 1º do mês), e soma as expectativas
    dos dias futuros do mês (date_f+1 .. fim do mês). Não é modelo de ML treinado; é projeção
    por sazonalidade semanal explícita, útil como indicativo operacional.
    """
    if (date_i.year, date_i.month) != (date_f.year, date_f.month):
        return None
    m_last_d = monthrange(date_f.year, date_f.month)[1]
    month_last = date(date_f.year, date_f.month, m_last_d)
    if date_f >= month_last:
        return None

    routes_p = list(routes_periodo)
    n_ret_mtd, n_done_mtd = counts_devolucao_rotas_concluidas(routes_p)
    if n_done_mtd <= 0:
        return {
            "ativa": False,
            "mensagem": "Projeção ao fim do mês: indisponível — ainda não há rotas concluídas no período.",
        }

    buckets = group_routes_by_operational_day(routes_baseline)
    if len(buckets) < min_baseline_days:
        return {
            "ativa": False,
            "mensagem": (
                "Projeção ao fim do mês: histórico insuficiente para perfil por dia da semana "
                f"(mínimo {min_baseline_days} dias com rotas antes do mês)."
            ),
        }

    sums_r: defaultdict[int, float] = defaultdict(float)
    sums_d: defaultdict[int, float] = defaultdict(float)
    cnt_w: defaultdict[int, int] = defaultdict(int)
    tot_r = 0.0
    tot_d = 0.0
    n_day_obs = 0
    for day_iso, day_routes in buckets.items():
        try:
            y, m, dd = int(day_iso[:4]), int(day_iso[5:7]), int(day_iso[8:10])
            dow = date(y, m, dd).weekday()
        except (TypeError, ValueError):
            continue
        nr, nd = counts_devolucao_rotas_concluidas(day_routes)
        sums_r[dow] += float(nr)
        sums_d[dow] += float(nd)
        cnt_w[dow] += 1
        tot_r += float(nr)
        tot_d += float(nd)
        n_day_obs += 1

    if n_day_obs <= 0:
        return {"ativa": False, "mensagem": "Projeção ao fim do mês: baseline sem dias válidos."}

    mean_r: List[float] = []
    mean_d: List[float] = []
    has_w: List[bool] = []
    for dow in range(7):
        c = cnt_w[dow]
        if c > 0:
            mean_r.append(sums_r[dow] / c)
            mean_d.append(sums_d[dow] / c)
            has_w.append(True)
        else:
            mean_r.append(0.0)
            mean_d.append(0.0)
            has_w.append(False)

    fb_r = tot_r / n_day_obs
    fb_d = tot_d / n_day_obs

    exp_r = 0.0
    exp_d = 0.0
    d = date_f + timedelta(days=1)
    dias_restantes = 0
    while d <= month_last:
        dias_restantes += 1
        w = d.weekday()
        exp_r += mean_r[w] if has_w[w] else fb_r
        exp_d += mean_d[w] if has_w[w] else fb_d
        d += timedelta(days=1)

    if dias_restantes <= 0:
        return None

    proj_r = float(n_ret_mtd) + exp_r
    proj_d = float(n_done_mtd) + exp_d
    if proj_d <= 0:
        return {"ativa": False, "mensagem": "Projeção ao fim do mês: volume projetado de rotas nulo."}

    proj_pct = round(100.0 * proj_r / proj_d, 1)
    vs_meta = "dentro" if proj_pct <= meta_pp else "acima"

    return {
        "ativa": True,
        "pct_projetado": proj_pct,
        "vs_meta": vs_meta,
        "meta_pp": float(meta_pp),
        "dias_restantes_no_mes": dias_restantes,
        "dias_baseline_calendario": n_day_obs,
        "n_ret_mtd": int(n_ret_mtd),
        "n_done_mtd": int(n_done_mtd),
        "proj_n_ret": round(proj_r, 2),
        "proj_n_done": round(proj_d, 2),
        "resumo_metodo": (
            "Perfil por dia da semana com base em dias anteriores ao mês corrente "
            f"({n_day_obs} dia(s) com rotas no histórico)."
        ),
        "disclaimer": (
            "Indicativo: pressupõe que o ritmo e o padrão semanal recentes se mantenham; "
            "não utiliza modelo de aprendizado de máquina treinado fora desta regra."
        ),
    }


def build_mes_fim_projecao_pct_financeiro(
    date_i: date,
    date_f: date,
    base_por_dia_mtd: Dict[str, float],
    dev_por_dia_mtd: Dict[str, float],
    base_por_dia_baseline: Dict[str, float],
    dev_por_dia_baseline: Dict[str, float],
    *,
    meta_pp: float = 2.0,
    min_baseline_days: int = 14,
) -> Optional[Dict[str, Any]]:
    """
    Estimativa do % financeiro (valor devolvido ÷ faturamento das rotas) ao último dia do mês,
    para recorte mensal parcial. Mesma ideia que `build_mes_fim_projecao_pct_rotas`: por cada dia
    futuro do mês, soma a média histórica (por dia da semana) de base e de valor devolvido
    observados no baseline; combina com o MTD já realizado.
    """
    if (date_i.year, date_i.month) != (date_f.year, date_f.month):
        return None
    m_last_d = monthrange(date_f.year, date_f.month)[1]
    month_last = date(date_f.year, date_f.month, m_last_d)
    if date_f >= month_last:
        return None

    mtd_base = sum(float(v) for v in base_por_dia_mtd.values())
    mtd_dev = sum(float(v) for v in dev_por_dia_mtd.values())
    if mtd_base <= 0:
        return {
            "ativa": False,
            "mensagem": (
                "Projeção ao fim do mês: indisponível — ainda não há faturamento (base financeira das rotas) "
                "no período."
            ),
        }

    baseline_days = set(base_por_dia_baseline.keys()) | set(dev_por_dia_baseline.keys())
    if len(baseline_days) < min_baseline_days:
        return {
            "ativa": False,
            "mensagem": (
                "Projeção ao fim do mês: histórico insuficiente para perfil por dia da semana "
                f"(mínimo {min_baseline_days} dias com movimento antes do mês)."
            ),
        }

    sums_b: defaultdict[int, float] = defaultdict(float)
    sums_v: defaultdict[int, float] = defaultdict(float)
    cnt_w: defaultdict[int, int] = defaultdict(int)
    tot_b = 0.0
    tot_v = 0.0
    n_day_obs = 0
    for day_iso in baseline_days:
        if len(str(day_iso)) != 10:
            continue
        try:
            y, m, dd = int(day_iso[:4]), int(day_iso[5:7]), int(day_iso[8:10])
            dow = date(y, m, dd).weekday()
        except (TypeError, ValueError):
            continue
        b = float(base_por_dia_baseline.get(day_iso, 0.0))
        v = float(dev_por_dia_baseline.get(day_iso, 0.0))
        sums_b[dow] += b
        sums_v[dow] += v
        cnt_w[dow] += 1
        tot_b += b
        tot_v += v
        n_day_obs += 1

    if n_day_obs <= 0:
        return {"ativa": False, "mensagem": "Projeção ao fim do mês: baseline sem dias válidos."}

    mean_b: List[float] = []
    mean_v: List[float] = []
    has_w: List[bool] = []
    for dow in range(7):
        c = cnt_w[dow]
        if c > 0:
            mean_b.append(sums_b[dow] / c)
            mean_v.append(sums_v[dow] / c)
            has_w.append(True)
        else:
            mean_b.append(0.0)
            mean_v.append(0.0)
            has_w.append(False)

    fb_b = tot_b / n_day_obs
    fb_v = tot_v / n_day_obs

    exp_b = 0.0
    exp_v = 0.0
    d = date_f + timedelta(days=1)
    dias_restantes = 0
    while d <= month_last:
        dias_restantes += 1
        w = d.weekday()
        exp_b += mean_b[w] if has_w[w] else fb_b
        exp_v += mean_v[w] if has_w[w] else fb_v
        d += timedelta(days=1)

    if dias_restantes <= 0:
        return None

    proj_b = mtd_base + exp_b
    proj_v = mtd_dev + exp_v
    if proj_b <= 0:
        return {
            "ativa": False,
            "mensagem": "Projeção ao fim do mês: faturamento projetado para o mês é nulo ou negativo.",
        }

    proj_pct = round(100.0 * proj_v / proj_b, 2)
    if not math.isfinite(proj_pct):
        return {
            "ativa": False,
            "mensagem": (
                "Projeção ao fim do mês: indisponível — combinação de MTD e histórico gerou valor não numérico; "
                "verifique consistência de datas e valores no período."
            ),
        }
    vs_meta = "dentro" if proj_pct <= meta_pp else "acima"

    return {
        "ativa": True,
        "pct_projetado": proj_pct,
        "vs_meta": vs_meta,
        "meta_pp": float(meta_pp),
        "dias_restantes_no_mes": dias_restantes,
        "dias_baseline_calendario": n_day_obs,
        "mtd_base": round(mtd_base, 2),
        "mtd_dev": round(mtd_dev, 2),
        "proj_base": round(proj_b, 2),
        "proj_dev": round(proj_v, 2),
        "resumo_metodo": (
            "Perfil por dia da semana com base em dias anteriores ao mês corrente "
            f"({n_day_obs} dia(s) com base ou devolução no histórico)."
        ),
        "disclaimer": (
            "Indicativo: pressupõe que o ritmo e o padrão semanal recentes se mantenham; "
            "não utiliza modelo de aprendizado de máquina treinado fora desta regra."
        ),
    }
