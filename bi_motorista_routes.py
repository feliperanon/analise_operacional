# -*- coding: utf-8 -*-
"""Rotas de BI de Avaliação de Motoristas."""

from datetime import datetime, date
from typing import Optional
import statistics
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from bi_delivery_routes import (
    _build_bi_delivery_dataset,
    _fmt_br_1,
    _fmt_br_2,
    _fmt_br_int,
    _fmt_br_data,
    _fmt_br_moeda,
    _fmt_br_duracao,
)
from database import get_session

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.filters["fmt_br_1"] = _fmt_br_1
templates.env.filters["fmt_br_2"] = _fmt_br_2
templates.env.filters["fmt_br_int"] = _fmt_br_int
templates.env.filters["fmt_br_data"] = _fmt_br_data
templates.env.filters["fmt_br_moeda"] = _fmt_br_moeda
templates.env.filters["fmt_br_duracao"] = _fmt_br_duracao

META_PREMIACAO_PCT = 2.0
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def _build_bi_motorista_dataset(delivery_dataset: dict) -> dict:
    """Estende o dataset do BI Delivery com análises específicas para avaliação de motoristas."""
    tactical = delivery_dataset.get("tactical_rows", [])
    detail_rows = delivery_dataset.get("detail_rows", [])
    route_rows = delivery_dataset.get("all_route_rows", delivery_dataset.get("detail_rows", []))
    all_rows = route_rows if route_rows else detail_rows

    # 1. Elegibilidade à premiação (meta financeira: % devolução em valor < 2%)
    def _pct_valor(row: dict) -> float:
        v = row.get("returned_value_pct")
        if v is None:
            v = row.get("return_rate")
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    elegiveis = [
        r for r in tactical
        if _pct_valor(r) < META_PREMIACAO_PCT and (r.get("planned_stops") or 0) >= 5
    ]
    nao_elegiveis = [
        r for r in tactical
        if _pct_valor(r) >= META_PREMIACAO_PCT or ((r.get("planned_stops") or 0) < 5 and float(r.get("returned_value") or 0) > 0)
    ]

    # 2. Ranking mais lento / mais rápido (por tempo médio)
    com_tempo = [r for r in tactical if (r.get("avg_duration") or 0) > 0]
    mais_rapido = min(com_tempo, key=lambda x: x.get("avg_duration", 9999)) if com_tempo else None
    mais_lento = max(com_tempo, key=lambda x: x.get("avg_duration", 0)) if com_tempo else None

    # 3. Dia da semana com mais devoluções
    dia_semana_agg: dict[int, dict] = {}
    for r in all_rows:
        if r.get("status") != "devolucao":
            continue
        dt_str = r.get("date") or ""
        try:
            d = datetime.strptime(dt_str, "%Y-%m-%d").date()
            wd = d.weekday()  # 0=seg, 6=dom
            if wd not in dia_semana_agg:
                dia_semana_agg[wd] = {"dia": DIAS_SEMANA[wd], "qtd": 0, "valor": 0.0}
            dia_semana_agg[wd]["qtd"] += 1
            dia_semana_agg[wd]["valor"] += float(r.get("returned_value") or 0)
        except Exception:
            pass
    dia_semana_rows = [dia_semana_agg[i] for i in range(7) if i in dia_semana_agg]
    dia_semana_rows.sort(key=lambda x: -x["valor"])
    dia_mais_devolucoes = dia_semana_rows[0]["dia"] if dia_semana_rows else "-"

    # 4. Performance por placa (caminhão) — inclui frota inteira + placas das rotas
    fleet_plates = delivery_dataset.get("fleet_plates") or []
    por_placa: dict[str, dict] = {}
    for pl in fleet_plates:
        placa = (pl or "").strip().upper()
        if placa and placa not in por_placa:
            por_placa[placa] = {"placa": placa, "paradas": 0, "devolucoes": 0, "valor_entregue": 0.0, "valor_devolvido": 0.0, "durations": []}
    for r in all_rows:
        placa = (r.get("plate") or "-").strip().upper()
        if placa in ("-", ""):
            continue
        if placa not in por_placa:
            por_placa[placa] = {"placa": placa, "paradas": 0, "devolucoes": 0, "valor_entregue": 0.0, "valor_devolvido": 0.0, "durations": []}
        por_placa[placa]["paradas"] += 1
        if (r.get("status") or "").lower() == "devolucao":
            por_placa[placa]["devolucoes"] += 1
            por_placa[placa]["valor_devolvido"] += float(r.get("returned_value") or 0)
        if (r.get("status") or "").lower() in ("entregue", "devolucao"):
            del_v = float(r.get("delivered_value") or 0)
            ret_v = float(r.get("returned_value") or 0)
            por_placa[placa]["valor_entregue"] += del_v + (ret_v if (r.get("status") or "").lower() == "devolucao" else 0)
        dur = r.get("duration_m")
        if dur is not None:
            por_placa[placa]["durations"].append(float(dur))
    plate_rows = []
    for p, data in por_placa.items():
        paradas = max(1, data["paradas"])
        tax_dev = round(data["devolucoes"] / paradas * 100, 2) if paradas else 0
        val_real = data["valor_entregue"] + data["valor_devolvido"]
        pct_val = round(data["valor_devolvido"] / val_real * 100, 2) if val_real > 0 else 0
        tempo_med = round(statistics.mean(data["durations"]), 1) if data["durations"] else 0
        plate_rows.append({
            "placa": p,
            "paradas": data["paradas"],
            "devolucoes": data["devolucoes"],
            "taxa_devolucao": tax_dev,
            "valor_devolvido": round(data["valor_devolvido"], 2),
            "pct_valor": pct_val,
            "tempo_medio": tempo_med,
        })
    plate_rows.sort(key=lambda x: (-x["paradas"], -x["devolucoes"], -x["valor_devolvido"]))

    # 5. Relativização qtd × peso × devolução
    rel_rows = []
    for r in tactical:
        planned = max(1, r.get("planned_stops") or 1)
        ret = r.get("returned_stops") or 0
        kg_pl = r.get("planned_kg") or 0
        val_pl = r.get("planned_value") or 0.01
        dev_por_parada = round(ret / planned * 100, 2)
        dev_por_kg = round(ret / max(0.01, kg_pl) * 100, 2) if kg_pl else 0
        dev_por_valor = round((r.get("returned_value") or 0) / val_pl * 100, 2)
        rel_rows.append({
            "driver_name": r.get("driver_name"),
            "driver_id": r.get("driver_id"),
            "paradas": planned,
            "devolucoes": ret,
            "devolucao_pct": r.get("return_rate") or 0,
            "devol_por_parada_pct": dev_por_parada,
            "kg_planejado": kg_pl,
            "valor_planejado": val_pl,
            "returned_value": r.get("returned_value") or 0,
        })
    rel_rows.sort(key=lambda x: -x["returned_value"])

    # 6. Oscilação motorista (simplificado: usar variância entre dias se houver; senão usar desvio da média)
    driver_daily: dict[str, list[float]] = {}
    for r in all_rows:
        drv = r.get("driver_name") or "-"
        if drv not in driver_daily:
            driver_daily[drv] = []
        if (r.get("status") or "").lower() == "devolucao":
            driver_daily[drv].append(1.0)
        elif (r.get("status") or "").lower() in ("entregue", "devolucao"):
            driver_daily[drv].append(0.0)
    oscilacao_rows = []
    for r in tactical:
        drv = r.get("driver_name") or "-"
        rates_diarios = driver_daily.get(drv, [])
        sigma = round(statistics.stdev(rates_diarios) * 100, 2) if len(rates_diarios) > 1 else 0
        oscilacao_rows.append({
            "driver_name": drv,
            "driver_id": r.get("driver_id"),
            "return_rate": r.get("return_rate") or 0,
            "sigma": sigma,
            "estavel": sigma < 3,
        })
    oscilacao_rows.sort(key=lambda x: -x["sigma"])

    chart_payload = delivery_dataset.get("chart_payload_json", "{}")
    try:
        chart_obj = json.loads(chart_payload) if isinstance(chart_payload, str) else chart_payload
    except Exception:
        chart_obj = {}

    # Dia da semana para gráfico (Segu-Sáb sempre, 0 onde não houver dados)
    dia_semana_labels = []
    dia_semana_qtd = []
    dia_semana_valor = []
    for i in range(7):
        dia_semana_labels.append(DIAS_SEMANA[i])
        if i in dia_semana_agg:
            dia_semana_qtd.append(dia_semana_agg[i]["qtd"])
            dia_semana_valor.append(round(dia_semana_agg[i]["valor"], 2))
        else:
            dia_semana_qtd.append(0)
            dia_semana_valor.append(0.0)
    chart_obj["dia_semana"] = {"labels": dia_semana_labels, "qtd": dia_semana_qtd, "valor": dia_semana_valor}

    return {
        **delivery_dataset,
        "elegiveis": elegiveis,
        "nao_elegiveis": nao_elegiveis,
        "mais_rapido": mais_rapido,
        "mais_lento": mais_lento,
        "dia_mais_devolucoes": dia_mais_devolucoes,
        "dia_semana_rows": dia_semana_rows,
        "plate_rows": plate_rows,
        "rel_rows": rel_rows[:20],
        "oscilacao_rows": oscilacao_rows[:15],
        "meta_premiacao": META_PREMIACAO_PCT,
        "chart_payload_json": json.dumps(chart_obj, ensure_ascii=False),
    }


@router.get("/bi/motorista", response_class=HTMLResponse)
async def bi_motorista_page(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    shift: str = "Todos",
    driver_id: Optional[str] = None,
    plate: str = "Todos",
    status: str = "Todos",
    detail_driver_id: Optional[str] = None,
    detail_status: str = "Todos",
    session: Session = Depends(get_session),
):
    parsed_driver_id: Optional[int] = int(driver_id) if (driver_id or "").strip().isdigit() else None
    parsed_detail_driver_id: Optional[int] = int(detail_driver_id) if (detail_driver_id or "").strip().isdigit() else None

    delivery_dataset = _build_bi_delivery_dataset(
        session=session,
        date_from=date_from,
        date_to=date_to,
        shift=shift,
        driver_id=parsed_driver_id,
        plate=plate,
        status=status,
        detail_driver_id=parsed_detail_driver_id,
        detail_status=detail_status,
    )
    dataset = _build_bi_motorista_dataset(delivery_dataset)
    return templates.TemplateResponse("bi_motorista.html", {"request": request, **dataset})
