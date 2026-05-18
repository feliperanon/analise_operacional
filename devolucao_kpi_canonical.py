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
- Opcionalmente soma-se `suplemento_base_financeira` (ex.: devoluções cadastradas **sem** `route_id`,
  alinhado ao `prev_month_planned_val + prev_month_manual_valor` do BI Entregas). Se a base
  continuar ≤ 0 e o numerador for > 0, usa-se o próprio valor devolvido como base mínima
  (mesmo fechamento do BI quando `prev_month_base <= 0`).
- BI Entregas / Clientes / Vendedor podem exibir **outros** índices (ex.: devolvido ÷ planejado,
  ou devoluções ÷ faturamento do vendedor); o rótulo deixa explícito quando não for este KPI.

Projeção fim de mês:
- `build_mes_fim_projecao_pct_rotas`: % paradas (operacional), média por dia da semana no histórico pré-mês.
- `build_mes_fim_projecao_pct_financeiro`: % valor devolvido sobre faturamento; prioriza perfil por dia da semana
  no histórico pré-mês; se inviável (poucos dias de histórico, NaN/Inf nos agregados), usa extrapolação pela
  média diáncia já observada no recorte MTD do mês (`metodo_projecao`: `dow_baseline` | `linear_mtd`).
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import math
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

_DONE_STATUSES = frozenset({"entregue", "devolucao"})


def _coerce_fin(x: Any) -> float:
    """Converte para float finito; valores inválidos ou não finitos viram 0 (evita NaN na projeção)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


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


def _iso_date_from_datetime_value(val: Any, tz_name: str = "America/Sao_Paulo") -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        try:
            z = ZoneInfo(tz_name)
            dt = val.replace(tzinfo=z) if val.tzinfo is None else val.astimezone(z)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return val.strftime("%Y-%m-%d")[:10]
    s = str(val).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    if "T" in s:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(tz_name))
            return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""


def _iso_from_returned_at(raw: Optional[str]) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    if "T" in s or " " in s:
        return _iso_date_from_datetime_value(s)
    return ""


def _iso_from_route_delivery_log(route: Any, event: str = "devolucao") -> str:
    raw = getattr(route, "delivery_time_log", None)
    if not raw:
        return ""
    try:
        history = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return ""
    if not isinstance(history, list):
        return ""
    want = (event or "").strip().lower()
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if (item.get("event") or "").strip().lower() != want:
            continue
        for key in ("at", "time"):
            d = _iso_date_from_datetime_value(item.get(key))
            if len(d) == 10:
                return d
    return ""


def devolucao_resolved_operacional_iso(d: Any, route: Any = None) -> str:
    """
    Dia civil em que a devolução ocorreu (exibição BI / listagem).

    Mobile grava romaneio (competência) e muitas vezes data_entrega = Route.date (dia da rota),
    não o dia em que o motorista registrou a devolução — usa log da rota e created_at como fallback.
    """
    raw_ent = str(getattr(d, "data_entrega", None) or "").strip()
    raw_rom = str(getattr(d, "data_romaneio", None) or "").strip()
    ent = raw_ent[:10] if len(raw_ent) >= 10 else ""
    rom = raw_rom[:10] if len(raw_rom) >= 10 else ""

    if route is not None:
        for candidate in (
            _iso_from_returned_at(getattr(route, "delivery_returned_at", None)),
            _iso_from_route_delivery_log(route, "devolucao"),
        ):
            if len(candidate) == 10:
                return candidate

    cdate = _iso_date_from_datetime_value(getattr(d, "created_at", None))
    src = str(getattr(d, "source", None) or "").strip().upper()
    if len(cdate) == 10 and src in ("MOBILE", "WEB", "ROTA"):
        if len(rom) == 10 and cdate > rom:
            return cdate
        if len(ent) == 10 and len(rom) == 10 and ent == rom and cdate > rom:
            return cdate
        if len(ent) < 10 and len(rom) == 10:
            return cdate

    if len(ent) == 10 and len(rom) == 10 and ent != rom:
        return ent if ent >= rom else rom
    if len(ent) == 10:
        return ent
    if len(rom) == 10:
        return rom
    return cdate if len(cdate) == 10 else ""


def devolucao_operacional_iso(d: Any, route: Any = None) -> str:
    """Dia civil da operação (entrega efetiva quando resolvível)."""
    return devolucao_resolved_operacional_iso(d, route)


def devolucao_operacional_in_period(d: Any, period_start: str, period_end: str, route: Any = None) -> bool:
    op = devolucao_operacional_iso(d, route)
    return len(op) == 10 and period_start <= op <= period_end


def devolucao_in_user_period(d: Any, period_start: str, period_end: str, route: Any = None) -> bool:
    """
    Recorte do BI / listagem por intervalo civil escolhido pelo usuário.

    Inclui por competência (KPI mensal) ou quando a data operacional resolvida cai no período.
    """
    return devolucao_competencia_in_period(d, period_start, period_end) or devolucao_operacional_in_period(
        d, period_start, period_end, route
    )


def devolucao_chart_day_iso(d: Any, period_start: str, period_end: str, route: Any = None) -> str:
    """Dia civil no eixo do gráfico e listagem BI (data real da ocorrência)."""
    op = devolucao_resolved_operacional_iso(d, route)
    comp = devolucao_competencia_iso(d) or ""

    def _inwin(p: str) -> bool:
        return len(p) == 10 and period_start <= p <= period_end

    if len(op) == 10 and _inwin(op):
        return op
    if len(op) == 10:
        return op
    if len(comp) >= 10 and _inwin(comp[:10]):
        return comp[:10]
    return comp[:10] if len(comp) >= 10 else ""


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


def pct_valor_devolvido_sobre_base_rotas(
    valor_devolvido: float,
    routes_delivery: Iterable[Any],
    *,
    suplemento_base_financeira: float = 0.0,
) -> Tuple[Optional[float], float]:
    """% valor devolvido (cadastro agregado) sobre base R$ nas rotas do mesmo recorte."""
    base = 0.0
    for r in routes_delivery:
        contrib = route_base_financeiro_kpi(r)
        if contrib is not None:
            base += contrib
    base += max(0.0, float(suplemento_base_financeira or 0.0))
    vd = float(valor_devolvido or 0)
    if base <= 0 and vd > 0:
        base = vd
    if base <= 0:
        return None, 0.0
    pct = round(100.0 * vd / base, 2)
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
    para recorte mensal parcial. Tenta perfil por dia da semana no histórico pré-mês; se faltar
    histórico ou o resultado não for numérico válido, extrapola pela média diária do MTD no mês.
    """
    if (date_i.year, date_i.month) != (date_f.year, date_f.month):
        return None
    m_last_d = monthrange(date_f.year, date_f.month)[1]
    month_last = date(date_f.year, date_f.month, m_last_d)
    if date_f >= month_last:
        return None

    mtd_base = sum(_coerce_fin(v) for v in base_por_dia_mtd.values())
    mtd_dev = sum(_coerce_fin(v) for v in dev_por_dia_mtd.values())
    if not math.isfinite(mtd_base + mtd_dev) or mtd_base <= 0:
        return {
            "ativa": False,
            "mensagem": (
                "Projeção ao fim do mês: indisponível — ainda não há faturamento (base financeira das rotas) "
                "no período."
            ),
        }

    dias_restantes = 0
    d = date_f + timedelta(days=1)
    while d <= month_last:
        dias_restantes += 1
        d += timedelta(days=1)
    if dias_restantes <= 0:
        return None

    mtd_span = max(1, (date_f - date_i).days + 1)

    disclaimer = (
        "Indicativo: pressupõe que o ritmo recente se mantenha; "
        "não utiliza modelo de aprendizado de máquina treinado fora desta regra."
    )

    def _payload_ok(
        proj_b: float,
        proj_v: float,
        exp_b: float,
        exp_v: float,
        resumo_metodo: str,
        metodo_projecao: str,
        n_day_obs: int,
    ) -> Dict[str, Any]:
        proj_pct = round(100.0 * proj_v / proj_b, 2)
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
            "resumo_metodo": resumo_metodo,
            "disclaimer": disclaimer,
            "metodo_projecao": metodo_projecao,
        }

    def _try_linear_mtd() -> Optional[Dict[str, Any]]:
        rate_b = mtd_base / float(mtd_span)
        rate_v = mtd_dev / float(mtd_span)
        exp_b = rate_b * float(dias_restantes)
        exp_v = rate_v * float(dias_restantes)
        proj_b = mtd_base + exp_b
        proj_v = mtd_dev + exp_v
        if not math.isfinite(proj_b + proj_v + exp_b + exp_v) or proj_b <= 0:
            return None
        proj_pct = round(100.0 * proj_v / proj_b, 2)
        if not math.isfinite(proj_pct):
            return None
        return _payload_ok(
            proj_b,
            proj_v,
            exp_b,
            exp_v,
            (
                f"Média diária do recorte no mês ({mtd_span} dia(s) com dados agregados) aplicada aos "
                f"{dias_restantes} dia(s) restante(s) do mês civil — usado quando o histórico pré-mês não permite "
                "perfil semanal confiável ou o perfil semanal gerou valor inválido."
            ),
            "linear_mtd",
            0,
        )

    baseline_days = set(base_por_dia_baseline.keys()) | set(dev_por_dia_baseline.keys())
    if len(baseline_days) < min_baseline_days:
        out_lin = _try_linear_mtd()
        if out_lin:
            return out_lin
        return {
            "ativa": False,
            "mensagem": (
                "Projeção ao fim do mês: histórico insuficiente para perfil por dia da semana "
                f"(mínimo {min_baseline_days} dias antes do mês) e não foi possível extrapolar pela média diária "
                "do período (base ou dias inválidos)."
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
        b = _coerce_fin(base_por_dia_baseline.get(day_iso, 0.0))
        v = _coerce_fin(dev_por_dia_baseline.get(day_iso, 0.0))
        sums_b[dow] += b
        sums_v[dow] += v
        cnt_w[dow] += 1
        tot_b += b
        tot_v += v
        n_day_obs += 1

    if n_day_obs <= 0:
        out_lin = _try_linear_mtd()
        if out_lin:
            return out_lin
        return {"ativa": False, "mensagem": "Projeção ao fim do mês: baseline sem dias válidos."}

    mean_b: List[float] = []
    mean_v: List[float] = []
    has_w: List[bool] = []
    for dow in range(7):
        c = cnt_w[dow]
        if c > 0:
            mb = _coerce_fin(sums_b[dow] / c)
            mv = _coerce_fin(sums_v[dow] / c)
            mean_b.append(mb)
            mean_v.append(mv)
            has_w.append(True)
        else:
            mean_b.append(0.0)
            mean_v.append(0.0)
            has_w.append(False)

    fb_b = _coerce_fin(tot_b / n_day_obs)
    fb_v = _coerce_fin(tot_v / n_day_obs)

    exp_b = 0.0
    exp_v = 0.0
    d2 = date_f + timedelta(days=1)
    while d2 <= month_last:
        w = d2.weekday()
        exp_b += mean_b[w] if has_w[w] else fb_b
        exp_v += mean_v[w] if has_w[w] else fb_v
        d2 += timedelta(days=1)

    exp_b = _coerce_fin(exp_b)
    exp_v = _coerce_fin(exp_v)
    proj_b = _coerce_fin(mtd_base + exp_b)
    proj_v = _coerce_fin(mtd_dev + exp_v)

    if proj_b > 0 and math.isfinite(proj_b + proj_v):
        proj_pct = round(100.0 * proj_v / proj_b, 2)
        if math.isfinite(proj_pct):
            return _payload_ok(
                proj_b,
                proj_v,
                exp_b,
                exp_v,
                (
                    "Perfil por dia da semana com base em dias anteriores ao mês corrente "
                    f"({n_day_obs} dia(s) com base ou devolução no histórico)."
                ),
                "dow_baseline",
                n_day_obs,
            )

    out_lin = _try_linear_mtd()
    if out_lin:
        return out_lin

    return {
        "ativa": False,
        "mensagem": (
            "Projeção ao fim do mês: indisponível — o perfil semanal do histórico e a extrapolação linear "
            "pela média diária do mês não produziram percentual válido; verifique valores nas rotas e devoluções."
        ),
    }
