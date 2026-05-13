"""
Indicadores canônicos de devolução (BI / Central / TV).

Operacional (% rotas):
- Numerador: rotas com status normalizado = devolução.
- Denominador: rotas concluídas (entregue ou devolução), mesmo type=delivery.
- Exceção: status devolução com motivo de encerramento tardio automático (variações de texto,
  sem acentos na comparação) conta como entregue — alinhado ao painel TV e ao consolidado BI Entregas.

Financeiro (valor):
- O valor devolvido exibido nos KPIs agregados vem do cadastro `Devolucao` (+ lacunas de rota
  sem registro), em `bi_delivery_routes._build_bi_delivery_dataset` (`all_financial_rows`), sem
  usar ajuste de responsabilidade (isso é só por motorista no gamification).
- A taxa % valor usa denominador (valor entregue + valor devolvido), ou seja, faturamento
  efetivo que inclui todas as devoluções do período.

Projeção fim de mês (operacional):
- `build_mes_fim_projecao_pct_rotas`: média histórica por dia da semana em dias anteriores ao mês;
  não é modelo de ML externo.
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
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
