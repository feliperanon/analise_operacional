# -*- coding: utf-8 -*-
"""
Rotas e lógica de inicialização do módulo Devoluções.
"""
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Optional, List, Any, Callable, Dict
import io
import json
from fastapi import Request, Depends, UploadFile, File, APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlmodel import Session, select, func, delete
from sqlalchemy import tuple_, and_, or_, func
from types import SimpleNamespace
from pydantic import BaseModel

from database import get_session, engine as db_engine
import models
from devolucoes_service import (
    _reconcile_devolucao_with_route,
    reconcile_all_devolucoes_with_routes,
    reconnect_orphan_devolucoes,
    rematch_motoristas_from_ajudantes,
    parse_excel,
    validate_rows,
    save_batch,
    parse_valor_pt_br,
    compute_dia,
    compute_semana,
    compute_cluster,
    compute_acima_300,
    make_idempotency_hash,
    DevolucaoRow,
    precadastrar_vendedores_faltantes,
)
from devolucoes_service import backfill_duplicate_links_period, sync_route_to_devolucao
from devolucoes_service import (
    parse_excel as devolucoes_parse_excel,
    validate_rows as devolucoes_validate_rows,
    save_batch as devolucoes_save_batch,
    get_cadastro_health as devolucoes_get_cadastro_health,
    persist_import_batch as devolucoes_persist_import_batch,
)
from devolucoes_service import _load_cadastros as devolucoes_load_cadastros


def _fmt_data_hora_pt_br(s: Optional[str]) -> str:
    """Formata data/hora para pt-BR (dd/MM/yyyy HH:mm ou dd/MM/yyyy)."""
    if not s or not str(s).strip():
        return ""
    s = str(s).strip()
    try:
        if "T" in s or " " in s:
            if "T" in s:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                parts = s.split(" ", 1)
                dt = datetime.strptime(parts[0], "%Y-%m-%d")
                if len(parts) > 1 and parts[1]:
                    t = parts[1][:8]  # HH:MM:SS
                    if len(t) >= 5:
                        dt = dt.replace(hour=int(t[:2]), minute=int(t[3:5]), second=int(t[6:8]) if len(t) > 6 else 0)
            return dt.strftime("%d/%m/%Y %H:%M").strip()
        if len(s) >= 10:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    return s


def _build_devolucao_card(session: Session, d: models.Devolucao) -> dict:
    """Monta um card completo para uma devolução (cliente, endereço, kg, valor, motorista, ajudantes, caminhão, horários)."""
    route = session.get(models.Route, d.route_id) if d.route_id else None
    client = session.get(models.Client, d.client_id)
    motorista = session.get(models.Employee, d.motorista_id)
    motorista_id = d.motorista_id or (getattr(route, "employee_id", None) if route else None)
    motorista_name = (motorista.name if motorista else "").strip().lower()
    # Lista de nomes de ajudantes (sem duplicata, ordem preservada)
    ajudantes_names: List[str] = []
    def _add_ajudante_name(name: Optional[str]) -> None:
        if not name or not str(name).strip():
            return
        n = str(name).strip()
        if n.lower() == motorista_name:
            return
        if n not in ajudantes_names:
            ajudantes_names.append(n)

    ajudante = session.get(models.Employee, d.ajudante_id) if d.ajudante_id else None
    effective_ajudante_id = d.ajudante_id
    if ajudante:
        _add_ajudante_name(ajudante.name)
    # Ajudantes da rota (delivery_helpers_json, helpers_json)
    if route:
        for attr in ("delivery_helpers_json", "helpers_json"):
            raw = getattr(route, attr, None)
            if not raw:
                continue
            try:
                data = json.loads(raw) if isinstance(raw, str) else []
                helper_ids = [int(x) for x in (data or []) if x is not None and str(x).strip().isdigit()]
                for hid in helper_ids:
                    if hid != motorista_id:
                        emp = session.get(models.Employee, hid)
                        if emp:
                            _add_ajudante_name(emp.name)
                            if not ajudante:
                                ajudante = emp
                                effective_ajudante_id = hid
            except Exception:
                pass
        # Sessão do dia (mobile envia nomes em DeliverySession.helpers_json)
        if getattr(route, "date", None) and motorista_id:
            day = getattr(route, "date", None) or (str(d.data_romaneio)[:10] if getattr(d, "data_romaneio", None) else None)
            if day:
                try:
                    ds = session.exec(
                        select(models.DeliverySession)
                        .where(models.DeliverySession.date == day, models.DeliverySession.employee_id == motorista_id)
                        .limit(1)
                    ).first()
                    if ds and getattr(ds, "helpers_json", None):
                        hl = json.loads(ds.helpers_json) if isinstance(ds.helpers_json, str) else (ds.helpers_json or [])
                        if isinstance(hl, list):
                            for h in hl:
                                if isinstance(h, str) and h.strip():
                                    _add_ajudante_name(h.strip())
                                elif isinstance(h, (int, float)):
                                    aid = int(h)
                                    if aid != motorista_id:
                                        emp = session.get(models.Employee, aid)
                                        if emp:
                                            _add_ajudante_name(emp.name)
                                            if not ajudante:
                                                ajudante = emp
                                                effective_ajudante_id = aid
                except Exception:
                    pass
    motivo = session.get(models.DevolucaoMotivo, d.motivo_id)
    resp = session.get(models.DevolucaoResponsabilidade, d.responsabilidade_id)
    # Nome: preferir o mais completo (razao_social ou name)
    if client:
        rs = (getattr(client, "razao_social", None) or "").strip()
        nm = (getattr(client, "name", None) or "").strip()
        client_name = (rs if len(rs) >= len(nm) else nm) or rs or nm or "Cliente"
        client_fantasia = (getattr(client, "nome_fantasia", None) or "") or ""
    else:
        client_name = "Cliente"
        client_fantasia = ""
    address = ""
    bairro = ""
    city = ""
    state = ""
    cep = ""
    client_code = ""
    order_number = ""
    weight_kg = 0.0
    value = float(d.valor or 0)
    started_at = ""
    finished_at = ""
    returned_at = ""
    vehicle_plate = ""
    if route:
        address = route.delivery_address or ""
        bairro = route.delivery_neighborhood or ""
        city = route.delivery_city or ""
        state = route.delivery_state or ""
        cep = route.delivery_cep or ""
        client_code = route.delivery_client_code or ""
        order_number = route.delivery_order_number or ""
        weight_kg = float(route.devolucao_volume if route.devolucao_volume is not None else route.tonnage or 0)
        value = float(route.valor_devolucao if route.valor_devolucao is not None else d.valor or 0)
        started_at = route.delivery_started_at or route.start_time or ""
        finished_at = route.delivery_finished_at or route.end_time or ""
        returned_at = route.delivery_returned_at or ""
        vehicle_plate = route.delivery_vehicle_plate or ""
    if not address and client:
        address = getattr(client, "endereco", None) or ""
        bairro = getattr(client, "bairro", None) or ""
        city = getattr(client, "municipio", None) or ""
        state = getattr(client, "estado", None) or ""
        cep = getattr(client, "cep", None) or ""
    if not client_code and client:
        client_code = getattr(client, "nb", None) or ""
    obs_gestor_at = getattr(d, "observacao_gestor_edited_at", None)
    obs_gestor_at_fmt = (obs_gestor_at.strftime("%d/%m/%Y %H:%M") if obs_gestor_at else "") or ""
    return {
        "id": d.id,
        "route_id": d.route_id,
        "data_romaneio": d.data_romaneio,
        "data_romaneio_pt": _fmt_data_hora_pt_br(d.data_romaneio),
        "data_entrega": d.data_entrega,
        "data_entrega_pt": _fmt_data_hora_pt_br(d.data_entrega),
        "client_name": client_name,
        "client_fantasia": client_fantasia,
        "client_code": client_code,
        "order_number": order_number,
        "address": address,
        "bairro": bairro,
        "city": city,
        "state": state,
        "cep": cep,
        "weight_kg": round(weight_kg, 2),
        "value": round(value, 2),
        "started_at": started_at,
        "started_at_pt": _fmt_data_hora_pt_br(started_at),
        "finished_at": finished_at,
        "finished_at_pt": _fmt_data_hora_pt_br(finished_at),
        "returned_at": returned_at,
        "returned_at_pt": _fmt_data_hora_pt_br(returned_at),
        "motorista_id": d.motorista_id,
        "motorista_name": motorista.name if motorista else "-",
        "ajudante_id": effective_ajudante_id,
        "ajudante_name": ajudantes_names[0] if ajudantes_names else "-",
        "ajudantes_display": ", ".join(ajudantes_names) if ajudantes_names else "-",
        "vehicle_plate": vehicle_plate,
        "motivo_id": d.motivo_id,
        "motivo_nome": motivo.nome if motivo else "-",
        "responsabilidade_id": d.responsabilidade_id,
        "responsabilidade_nome": resp.nome if resp else "-",
        "valor": round(float(d.valor or 0), 2),
        "observacao": d.observacao or "",
        "observacao_gestor": getattr(d, "observacao_gestor", None) or "",
        "observacao_gestor_edited_by": getattr(d, "observacao_gestor_edited_by", None) or "",
        "observacao_gestor_edited_at": obs_gestor_at_fmt,
    }


# DELIVERY_RETURN_REASONS do main - duplicado aqui para seed (evitar import circular)
DELIVERY_RETURN_REASONS = {
    "COMERCIAL": [
        "PEDIDO / PRODUTO ERRADO",
        "CLIENTE NÃO FEZ PEDIDO",
        "PRAZO ERRADO",
        "PREÇO ERRADO",
        "SEM VASILHAME",
        "FORMA DE PAGAMENTO ERRADA",
        "VENDEDOR NÃO PASSOU",
        "TROCAS NÃO AUTORIZADAS",
        "TROCAS NÃO ENVIADAS",
    ],
    "MERCADO": [
        "HORÁRIO ENTREGA",
        "PONTO VENDA FECHADO / AUSENTE",
        "SEM DINHEIRO / CHEQUE",
        "CLIENTE DESISTIU DA COMPRA",
    ],
    "LOGÍSTICA": [
        "DIFÍCIL ACESSO",
        "PRODUTO DANIFICADO E/OU FALTA",
        "LOCAL ENTREGA NÃO LOCALIZADA",
        "ÁREA DE RISCO",
        "CAMINHÃO QUEBRADO NA ROTA",
        "FURTO / ROUBO",
        "QUANTIDADE ERRADA CARREGAMENTO",
        "PEDIDO NÃO ENTREGUE",
        "FALTA DE PRODUTO NO ESTOQUE",
    ],
}

# Variações comuns do Excel (nome_normalizado para match)
MOTIVO_ALIASES = {
    "PEDIDO/PRODUTO ERRADO": "PEDIDO / PRODUTO ERRADO",
    "PEDIDO PRODUTO ERRADO": "PEDIDO / PRODUTO ERRADO",
    "ENCOMENDA NAO PUDO SER": "PEDIDO NÃO ENTREGUE",
    "MERCADORIA COM DEFEITO/AVARIAS": "PRODUTO DANIFICADO E/OU FALTA",
    "CLIENTE NAO ENCONTRADO": "LOCAL ENTREGA NÃO LOCALIZADA",
    "PRAZO VENCIDO": "PRAZO ERRADO",
    "MA QUALIDADE": "PRODUTO DANIFICADO E/OU FALTA",
}


def ensure_devolucao_seed(session: Session):
    """Popula cadastros de Responsabilidade e Motivo se vazios."""
    existing = session.exec(select(models.DevolucaoResponsabilidade)).first()
    if existing:
        return

    resp_by_name = {}
    for nome in DELIVERY_RETURN_REASONS.keys():
        r = models.DevolucaoResponsabilidade(nome=nome)
        session.add(r)
        session.flush()
        resp_by_name[nome] = r

    for resp_nome, motivos in DELIVERY_RETURN_REASONS.items():
        resp_id = resp_by_name[resp_nome].id
        for m_nome in motivos:
            norm = m_nome.lower().replace(" ", "").replace("/", "").replace("-", "").replace("ã", "a").replace("ó", "o")
            mot = models.DevolucaoMotivo(nome=m_nome, responsabilidade_id=resp_id, nome_normalizado=norm)
            session.add(mot)
    session.flush()

    # Adicionar aliases ao nome_normalizado dos motivos canônicos
    for alias, canonic in MOTIVO_ALIASES.items():
        alias_norm = alias.lower().replace(" ", "").replace("/", "").replace("-", "").replace("ã", "a").replace("ó", "o")
        for m in session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.nome == canonic)).all():
            if alias_norm and alias_norm not in (m.nome_normalizado or ""):
                m.nome_normalizado = ((m.nome_normalizado or "") + " " + alias_norm).strip()
            break
    session.commit()


VENDEDORES_ESPECIAIS = [
    ("ESP-999", "999", "999 - Varejo"),
    ("ESP-777", "777", "777 - Venda particular"),
    ("ESP-900", "900", "900 - SV Balcão"),
]


def _devolucoes_backfill_span(session: Session, rows: List[dict]) -> None:
    """Executa vínculo de duplicatas Excel só após mutação (import), não a cada abertura da lista."""
    dates = []
    for v in rows or []:
        dr = v.get("data_romaneio")
        if dr:
            dates.append(str(dr)[:10])
    if not dates or len(dates[0]) < 10:
        return
    try:
        backfill_duplicate_links_period(session, min(dates), max(dates))
        session.commit()
    except Exception:
        session.rollback()


def _plate_by_client_motorista_date(session: Session, devolucoes, route_map: dict) -> Dict[tuple, str]:
    """Placas só para combinações da página atual que não têm route_id — evita carregar todas as rotas do mês."""
    needed: set = set()
    for dev in devolucoes:
        if dev.route_id and dev.route_id in route_map:
            continue
        # Usar data da entrega (quando disponível) para bater com Route.date
        dt = str(dev.data_entrega or dev.data_romaneio or "")[:10]
        needed.add((dev.client_id, dev.motorista_id, dt))
    if not needed:
        return {}
    pairs = list(needed)
    plate_by_cmd: Dict[tuple, str] = {}
    is_sqlite = "sqlite" in str(db_engine.url).lower()
    CHUNK = 80 if is_sqlite else 200
    for i in range(0, len(pairs), CHUNK):
        chunk = pairs[i : i + CHUNK]
        if is_sqlite:
            conds = [
                and_(
                    models.Route.client_id == a,
                    models.Route.employee_id == b,
                    models.Route.date == c,
                )
                for a, b, c in chunk
            ]
            q = select(models.Route).where(models.Route.type == "delivery", or_(*conds))
        else:
            q = select(models.Route).where(
                models.Route.type == "delivery",
                tuple_(models.Route.client_id, models.Route.employee_id, models.Route.date).in_(chunk),
            )
        for r in session.exec(q).all():
            if not r.client_id or not r.employee_id or not r.date:
                continue
            k = (r.client_id, r.employee_id, str(r.date)[:10])
            pl = (r.delivery_vehicle_plate or "").strip()
            if pl and k not in plate_by_cmd:
                plate_by_cmd[k] = pl
    return plate_by_cmd


def ensure_vendedores_especiais(session: Session):
    """Cria vendedores especiais (canais) que não vêm do cadastro de colaboradores."""
    for reg_id, seller_code, name in VENDEDORES_ESPECIAIS:
        existing = session.exec(
            select(models.Employee).where(models.Employee.registration_id == reg_id)
        ).first()
        if existing:
            if not existing.seller_code or str(existing.seller_code) != seller_code:
                existing.seller_code = seller_code
                session.add(existing)
            continue
        emp = models.Employee(
            registration_id=reg_id,
            seller_code=seller_code,
            name=name,
            role="Canal",
            work_shift="Manhã",
            cost_center="Geral",
            status="active",
        )
        session.add(emp)
    session.commit()


def init_devolucoes_router(
    *,
    templates,
    require_login: Callable[[Request], Any],
    logger,
    dbg_log: Optional[Callable[[str, dict], None]] = None,
) -> APIRouter:
    """Cria router do modulo de devolucoes sem acoplamento direto com main.py."""
    router = APIRouter()

    class DevolucaoManualPayload(BaseModel):
        data_romaneio: str
        data_entrega: str
        client_id: int
        vendedor_id: int
        motorista_id: int
        ajudante_id: Optional[int] = None
        valor: float
        motivo_id: int
        observacao: Optional[str] = None
        responsabilidade_id: int

    @router.get("/devolucoes", response_class=HTMLResponse)
    async def devolucoes_page(
        request: Request,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        hoje: Optional[str] = Query(None),
        page: int = 1,
        per_page: Optional[int] = None,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        now = datetime.now()
        today = now.date()
        start_date: str
        end_date: str
        period_label: Optional[str] = None

        def parse_ymd(s: Optional[str]):
            if not s or not str(s).strip():
                return None
            s = str(s).strip()[:10]
            try:
                if len(s) == 10 and s[4] == "-" and s[7] == "-":
                    return datetime.strptime(s, "%Y-%m-%d").date()
                if len(s) == 10 and s[2] == "/" and s[5] == "/":
                    return datetime.strptime(s, "%d/%m/%Y").date()
            except ValueError:
                pass
            return None

        if (hoje or "").strip().lower() in ("1", "true", "sim", "s", "hoje"):
            start_date = end_date = today.strftime("%Y-%m-%d")
            period_label = "Hoje"
        elif date_from and date_to:
            d1 = parse_ymd(date_from)
            d2 = parse_ymd(date_to)
            if d1 and d2:
                if d1 > d2:
                    d1, d2 = d2, d1
                start_date = d1.strftime("%Y-%m-%d")
                end_date = d2.strftime("%Y-%m-%d")
                period_label = f"Período {start_date} a {end_date}"
            else:
                start_date = today.strftime("%Y-%m-%d")
                end_date = start_date
                period_label = "Hoje"
        else:
            year = now.year
            month = now.month
            _, last_day = monthrange(year, month)
            start_date = f"{year:04d}-{month:02d}-01"
            end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
            period_label = f"{year:04d}-{month:02d}"

        # Só colunas usadas nos selects (menos tráfego Redis/Postgres que ORM completo)
        cr = session.exec(
            select(models.Client.id, models.Client.name, models.Client.nb).order_by(models.Client.name)
        ).all()
        clients = [SimpleNamespace(id=a, name=b, nb=c) for a, b, c in cr]
        er = session.exec(
            select(models.Employee.id, models.Employee.name, models.Employee.seller_code)
            .where(models.Employee.status != "fired")
            .order_by(models.Employee.name)
        ).all()
        employees = [SimpleNamespace(id=a, name=b, seller_code=c) for a, b, c in er]
        motivos = session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.is_active == True)).all()
        responsabilidades = session.exec(
            select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.is_active == True)
        ).all()

        # Trazer para a lista as devoluções feitas no mobile/desktop (Route com status devolucao)
        # que ainda não têm registro em Devolucao — assim passam a aparecer em /devolucoes.
        try:
            routes_devolucao = session.exec(
                select(models.Route)
                .where(models.Route.type == "delivery")
                .where(models.Route.date >= start_date)
                .where(models.Route.date <= end_date)
                .where(func.lower(models.Route.delivery_status) == "devolucao")
            ).all()
            eff_date_col = func.coalesce(models.Devolucao.data_entrega, models.Devolucao.data_romaneio)
            rids_raw = session.exec(
                select(models.Devolucao.route_id).where(
                    models.Devolucao.route_id.isnot(None),
                    eff_date_col >= start_date,
                    eff_date_col <= end_date,
                )
            ).all()
            existing_route_ids = {int(x[0]) if isinstance(x, (tuple, list)) else int(x) for x in rids_raw if x is not None}
            synced = 0
            for r in routes_devolucao:
                if r.id not in existing_route_ids:
                    dev = sync_route_to_devolucao(session, r, source="WEB")
                    if dev:
                        synced += 1
                        existing_route_ids.add(r.id)
            if synced:
                session.commit()
        except Exception:
            session.rollback()

        # Filtra por data da entrega (quando disponível), senão data do romaneio
        eff_date = func.coalesce(models.Devolucao.data_entrega, models.Devolucao.data_romaneio)
        count_q = (
            select(func.count(models.Devolucao.id))
            .where(eff_date >= start_date)
            .where(eff_date <= end_date)
        )
        total_count = session.exec(count_q).one()

        base_q = (
            select(models.Devolucao)
            .where(eff_date >= start_date)
            .where(eff_date <= end_date)
            .order_by(eff_date.desc(), models.Devolucao.created_at.desc())
        )
        per_page_effective = min(max(1, per_page or 250), 10000)
        offset = max(0, (page - 1) * per_page_effective)
        devolucoes = session.exec(base_q.offset(offset).limit(per_page_effective)).all()

        client_ids = {d.client_id for d in devolucoes}
        motorista_ids = {d.motorista_id for d in devolucoes}
        route_ids = {d.route_id for d in devolucoes if d.route_id}
        client_map = {c.id: c for c in session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all()} if client_ids else {}
        emp_map = {e.id: e for e in session.exec(select(models.Employee).where(models.Employee.id.in_(motorista_ids))).all()} if motorista_ids else {}
        route_map = {r.id: r for r in session.exec(select(models.Route).where(models.Route.id.in_(route_ids))).all()} if route_ids else {}
        plate_by_cmd = _plate_by_client_motorista_date(session, devolucoes, route_map)

        rows = []
        aguardando_n = 0
        for dev in devolucoes:
            c = client_map.get(dev.client_id)
            m = emp_map.get(dev.motorista_id)
            dup_of = getattr(dev, "duplicate_of_id", None)
            vstat = (getattr(dev, "validation_status", None) or "").strip()
            data_efetiva = str(dev.data_entrega or dev.data_romaneio or "")[:10]
            plate = ""
            if dev.route_id and dev.route_id in route_map:
                plate = (route_map[dev.route_id].delivery_vehicle_plate or "").strip()
            if not plate:
                plate = plate_by_cmd.get((dev.client_id, dev.motorista_id, data_efetiva), "")
            aguardando = bool(dup_of) or vstat in ("DUPLICATE_EXCEL", "ORPHAN_ROUTE")
            if aguardando:
                aguardando_n += 1
            # Nome do cliente: preferir o mais completo (razao_social ou name, o que for mais longo)
            cname = "-"
            if c:
                rs = (getattr(c, "razao_social", None) or "").strip()
                nm = (getattr(c, "name", None) or "").strip()
                cname = (rs if len(rs) >= len(nm) else nm) or rs or nm or "-"
            rows.append(
                {
                    "id": dev.id,
                    "data_romaneio": str(dev.data_romaneio)[:10] if dev.data_romaneio else "",
                    "data_entrega": str(dev.data_entrega)[:10] if dev.data_entrega else "",
                    "data_efetiva": data_efetiva,
                    "valor": float(dev.valor) if dev.valor is not None else 0.0,
                    "cluster": (dev.cluster or "") or "",
                    "acima_300": ("SIM" if dev.acima_300 in (True, "SIM", "sim", "Sim") else "NAO"),
                    "source": (dev.source or "").strip().upper() or "EXCEL",
                    "client_name": cname,
                    "motorista_id": dev.motorista_id,
                    "motorista_name": (m.name if m else "-") or "",
                    "vehicle_plate": plate or "—",
                    "is_duplicate_excel": bool(dup_of),
                    "validation_status": vstat,
                    "aguardando": aguardando,
                    "can_delete_aguardando": bool(dup_of) or vstat in ("ORPHAN_ROUTE", "DUPLICATE_EXCEL"),
                }
            )

        total_pages = (total_count + per_page_effective - 1) // per_page_effective if total_count > 0 else 1

        return templates.TemplateResponse(
            "devolucoes.html",
            {
                "request": request,
                "clients": clients,
                "employees": employees,
                "motivos": motivos,
                "responsabilidades": responsabilidades,
                "devolucoes": rows,
                "import_result": getattr(request.state, "devolucoes_import_result", None),
                "filters": {
                    "date_from": date_from or start_date,
                    "date_to": date_to or end_date,
                    "start_date": start_date,
                    "end_date": end_date,
                    "period_label": period_label,
                },
                "pagination": {
                    "page": page,
                    "per_page": per_page_effective,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "has_prev": page > 1,
                    "has_next": page < total_pages,
                    "prev_page": page - 1 if page > 1 else 1,
                    "next_page": page + 1 if page < total_pages else total_pages,
                },
                "aguardando_count": aguardando_n,
                "devolucoes_table_rows": rows,
            },
        )

    @router.get("/devolucoes/template")
    async def devolucoes_template(request: Request):
        import pandas as pd

        require_login(request)
        df = pd.DataFrame(
            [
                {
                    "DATA ROMANEIO": "02/02/2026",
                    "DATA ENTREGA": "02/02/2026",
                    "CODIGO": "61/50",
                    "NOME DO CLIENTE": "FIMA CENTRAL DE COMPRA",
                    "VENDEDOR": "110",
                    "MOTORISTA": "GILMAR",
                    "VALOR": "702,77",
                    "MOTIVO": "CLIENTE DESISTIU DA COMPRA",
                    "OBSERVACAO": "",
                    "RESPONSABILIDADE": "MERCADO",
                },
                {
                    "DATA ROMANEIO": "03/02/2026",
                    "DATA ENTREGA": "03/02/2026",
                    "CODIGO": "164M0",
                    "NOME DO CLIENTE": "WANASINAMON",
                    "VENDEDOR": "310",
                    "MOTORISTA": "JOSE MARIA CESAR",
                    "VALOR": "107,99",
                    "MOTIVO": "PEDIDO/PRODUTO ERRADO",
                    "OBSERVACAO": "",
                    "RESPONSABILIDADE": "COMERCIAL",
                },
            ]
        )
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=planilha_devolucoes_modelo.xlsx"},
        )

    @router.get("/api/devolucoes/health", response_class=JSONResponse)
    async def api_devolucoes_health(
        request: Request,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        try:
            cad = devolucoes_load_cadastros(session)
            diagnostics, global_errors = devolucoes_get_cadastro_health(cad)
            problems = list(global_errors)
            return JSONResponse(
                {
                    "ok": len(problems) == 0,
                    "diagnostics": diagnostics,
                    "problems": problems,
                    "global_errors": global_errors,
                    "ok_vendedores": diagnostics.get("vendedor_by_code_size", 0) > 0,
                    "ok_motivos": diagnostics.get("motivos_total", 0) > 0,
                    "ok_responsabilidades": diagnostics.get("responsabilidades_total", 0) > 0,
                    "ok_clientes": diagnostics.get("client_by_nb_size", 0) > 0,
                }
            )
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def _run_devolucoes_import(request: Request, file: UploadFile, session: Session):
        max_size = 50 * 1024 * 1024
        if not file or not file.filename:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Nenhum arquivo enviado. Selecione um arquivo Excel (.xlsx, .xls ou .xlsm).",
                },
                status_code=400,
            )
        fn = (file.filename or "").lower()
        if not fn.endswith((".xlsx", ".xls", ".xlsm")):
            return JSONResponse({"ok": False, "error": "Arquivo invalido. Use .xlsx, .xls ou .xlsm."}, status_code=400)
        content = await file.read()
        if len(content) > max_size:
            return JSONResponse({"ok": False, "error": "Arquivo muito grande (max. 50MB)."}, status_code=400)
        try:
            rows, err = devolucoes_parse_excel(content, file.filename or "upload.xlsx")
        except Exception as ex:
            logger.exception(f"Erro parse Excel: {ex}")
            return JSONResponse({"ok": False, "error": f"Erro ao processar planilha: {ex}"}, status_code=400)
        if err:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
        valid, invalid, _, _, global_errors = devolucoes_validate_rows(rows, session, to_staging_on_invalid=False)
        if global_errors:
            return JSONResponse(
                {
                    "ok": False,
                    "error": " | ".join(global_errors),
                    "global_errors": global_errors,
                },
                status_code=400,
            )
        # Pré-cadastro automático de vendedores faltantes para não perder dados
        created_codes: List[str] = precadastrar_vendedores_faltantes(session, invalid)
        if created_codes:
            session.commit()
            valid, invalid, _, _, global_errors = devolucoes_validate_rows(rows, session, to_staging_on_invalid=False)
            if global_errors:
                return JSONResponse(
                    {"ok": False, "error": " | ".join(global_errors), "global_errors": global_errors},
                    status_code=400,
                )
        try:
            created_by = None
            if request.session.get("user_id"):
                u = session.get(models.User, request.session["user_id"])
                if u:
                    created_by = u.username
            batch_id = devolucoes_persist_import_batch(
                session=session,
                filename=file.filename or "upload.xlsx",
                rows=rows,
                valid_rows=valid,
                invalid_rows=invalid,
                created_by=created_by,
                create_staging=True,
            )
            session.commit()
            payload = {
                "ok": True,
                "batch_id": batch_id,
                "total": len(rows),
                "valid_count": len(valid),
                "invalid_count": len(invalid),
                "invalid_details": invalid[:50],
                "valid_rows": valid,
                "valid_preview": valid[:10],
            }
            if created_codes:
                payload["precadastrados"] = created_codes
            return JSONResponse(payload)
        except Exception as e:
            logger.exception(f"Erro ao processar import de devolucoes: {e}")
            msg = str(e)[:200] if str(e) else "Erro desconhecido"
            return JSONResponse(
                {"ok": False, "error": f"Erro ao processar arquivo: {msg}. Verifique datas/planilha."},
                status_code=500,
            )

    @router.post("/api/devolucoes/import", response_class=JSONResponse)
    async def api_devolucoes_import(
        request: Request,
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        try:
            return await _run_devolucoes_import(request, file, session)
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            logger.exception(f"Erro import devolucoes: {e}")
            if dbg_log:
                dbg_log("devolucoes_import_500", {"error": str(e), "traceback": tb})
            msg = str(e)[:200] if str(e) else "Erro desconhecido"
            return JSONResponse(
                {"ok": False, "error": f"Erro ao processar arquivo: {msg}. Verifique datas/planilha."},
                status_code=500,
            )

    @router.post("/api/devolucoes/import/commit", response_class=JSONResponse)
    async def api_devolucoes_import_commit(
        request: Request,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        try:
            body = await request.json()
            valid_rows = body.get("valid_rows", [])
            batch_id = body.get("batch_id")
            filename = body.get("filename", "import.xlsx")
            if not valid_rows:
                return JSONResponse({"ok": False, "error": "Nenhuma linha valida para gravar."}, status_code=400)
            created_by = None
            if request.session.get("user_id"):
                u = session.get(models.User, request.session["user_id"])
                if u:
                    created_by = u.username
            created, skipped = devolucoes_save_batch(
                session,
                valid_rows,
                {"filename": filename, "batch_id": batch_id},
                source="EXCEL",
                created_by=created_by,
            )
            session.commit()
            _devolucoes_backfill_span(session, valid_rows)
            return JSONResponse({"ok": True, "batch_id": batch_id, "created": created, "skipped": len(skipped)})
        except Exception as e:
            logger.exception(f"Erro ao commitar importacao de devolucoes: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    def _clear_route_devolucao(session: Session, route_id: Optional[int]) -> None:
        """Remove estado de devolução da rota para que BI/mobile não exibam mais essa devolução."""
        if not route_id:
            return
        route = session.get(models.Route, route_id)
        if not route or (route.delivery_status or "").lower() != "devolucao":
            return
        route.delivery_status = "entregue"
        route.valor_devolucao = None
        route.devolucao_volume = None
        route.delivery_return_category = None
        route.delivery_return_reason = None
        route.delivery_returned_at = None
        session.add(route)

    def _can_delete_devolucao(d: models.Devolucao) -> bool:
        """Permite excluir: duplicata de planilha, órfão, ou devolução com origem EXCEL, WEB ou MOBILE."""
        dup_of = getattr(d, "duplicate_of_id", None)
        vstat = (getattr(d, "validation_status", None) or "").strip()
        src = (getattr(d, "source", None) or "").strip().upper()
        if dup_of or vstat in ("ORPHAN_ROUTE", "DUPLICATE_EXCEL"):
            return True
        if src in ("EXCEL", "WEB", "MOBILE"):
            return True
        return False

    @router.delete("/api/devolucoes/{devolucao_id}", response_class=JSONResponse)
    async def api_devolucoes_delete_shadow_or_orphan(
        devolucao_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Remove duplicata de planilha, órfão ou devolução com origem EXCEL. Se tiver rota vinculada, limpa o status de devolução da rota para refletir em BI/mobile."""
        require_login(request)
        d = session.get(models.Devolucao, devolucao_id)
        if not d:
            return JSONResponse({"ok": False, "error": "Não encontrado."}, status_code=404)
        if not _can_delete_devolucao(d):
            return JSONResponse(
                {"ok": False, "error": "Só é possível excluir duplicata de planilha, órfão ou devoluções com origem Excel, Web ou Mobile."},
                status_code=400,
            )
        route_id = getattr(d, "route_id", None)
        _clear_route_devolucao(session, route_id)
        session.exec(delete(models.DevolucaoAjusteResponsabilidade).where(models.DevolucaoAjusteResponsabilidade.devolucao_id == devolucao_id))
        session.delete(d)
        session.commit()
        return JSONResponse({"ok": True})

    class BulkDeletePayload(BaseModel):
        ids: List[int]

    @router.post("/api/devolucoes/bulk-delete", response_class=JSONResponse)
    async def api_devolucoes_bulk_delete(
        request: Request,
        payload: BulkDeletePayload,
        session: Session = Depends(get_session),
    ):
        """Exclui em lote duplicatas, órfãos ou devoluções com origem Excel. Se tiver rota vinculada, limpa o status de devolução da rota (BI/mobile atualizam)."""
        require_login(request)
        if not payload.ids:
            return JSONResponse({"ok": True, "deleted": [], "skipped": []})
        deleted = []
        skipped = []
        for devolucao_id in payload.ids:
            d = session.get(models.Devolucao, devolucao_id)
            if not d:
                skipped.append({"id": devolucao_id, "reason": "Não encontrado."})
                continue
            if not _can_delete_devolucao(d):
                skipped.append({"id": devolucao_id, "reason": "Só é possível excluir duplicata de planilha, órfão ou devoluções com origem Excel, Web ou Mobile."})
                continue
            route_id = getattr(d, "route_id", None)
            _clear_route_devolucao(session, route_id)
            session.exec(delete(models.DevolucaoAjusteResponsabilidade).where(models.DevolucaoAjusteResponsabilidade.devolucao_id == devolucao_id))
            session.delete(d)
            deleted.append(devolucao_id)
        session.commit()
        return JSONResponse({"ok": True, "deleted": deleted, "skipped": skipped})

    @router.post("/api/devolucoes/{devolucao_id}/approve", response_class=JSONResponse)
    async def api_devolucoes_approve(
        devolucao_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Marca devolução como aprovada (limpa validation_status e duplicate_of_id). Sai da aba Aguardando."""
        require_login(request)
        d = session.get(models.Devolucao, devolucao_id)
        if not d:
            return JSONResponse({"ok": False, "error": "Não encontrado."}, status_code=404)
        dup_of = getattr(d, "duplicate_of_id", None)
        vstat = (getattr(d, "validation_status", None) or "").strip()
        if not dup_of and vstat not in ("DUPLICATE_EXCEL", "ORPHAN_ROUTE"):
            return JSONResponse(
                {"ok": False, "error": "Apenas itens em aguardando (duplicata ou sem rota) podem ser aprovados."},
                status_code=400,
            )
        if hasattr(d, "duplicate_of_id"):
            d.duplicate_of_id = None
        if hasattr(d, "validation_status"):
            d.validation_status = ""
        session.add(d)
        session.commit()
        return JSONResponse({"ok": True})

    class BulkApprovePayload(BaseModel):
        ids: List[int]

    @router.post("/api/devolucoes/bulk-approve", response_class=JSONResponse)
    async def api_devolucoes_bulk_approve(
        request: Request,
        payload: BulkApprovePayload,
        session: Session = Depends(get_session),
    ):
        """Aprova em lote devoluções em aguardando (duplicata ou sem rota)."""
        require_login(request)
        if not payload.ids:
            return JSONResponse({"ok": True, "approved": [], "skipped": []})
        approved = []
        skipped = []
        for devolucao_id in payload.ids:
            d = session.get(models.Devolucao, devolucao_id)
            if not d:
                skipped.append({"id": devolucao_id, "reason": "Não encontrado."})
                continue
            dup_of = getattr(d, "duplicate_of_id", None)
            vstat = (getattr(d, "validation_status", None) or "").strip()
            if not dup_of and vstat not in ("DUPLICATE_EXCEL", "ORPHAN_ROUTE"):
                skipped.append({"id": devolucao_id, "reason": "Apenas itens em aguardando podem ser aprovados."})
                continue
            if hasattr(d, "duplicate_of_id"):
                d.duplicate_of_id = None
            if hasattr(d, "validation_status"):
                d.validation_status = ""
            session.add(d)
            approved.append(devolucao_id)
        session.commit()
        return JSONResponse({"ok": True, "approved": approved, "skipped": skipped})

    @router.get("/api/devolucoes/import/{batch_id}/errors.xlsx")
    async def api_devolucoes_import_errors_xlsx(
        batch_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        batch = session.get(models.DevolucaoImportBatch, batch_id)
        if not batch:
            return JSONResponse({"ok": False, "error": "Lote nao encontrado."}, status_code=404)

        errors = session.exec(
            select(models.DevolucaoImportRowError)
            .where(models.DevolucaoImportRowError.batch_id == batch_id)
            .order_by(models.DevolucaoImportRowError.row_index, models.DevolucaoImportRowError.id)
        ).all()

        try:
            from openpyxl import Workbook
        except Exception:
            return JSONResponse({"ok": False, "error": "openpyxl nao disponivel."}, status_code=500)

        wb = Workbook()
        ws = wb.active
        ws.title = "Erros Importacao"
        ws.append(["batch_id", "row_index", "column_name", "value", "reason", "raw_row_json"])
        for err in errors:
            ws.append([batch_id, err.row_index, err.column_name, err.value, err.reason, err.raw_row_json])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=devolucoes_erros_batch_{batch_id}.xlsx"},
        )

    @router.post("/api/devolucoes", response_class=JSONResponse)
    async def api_devolucoes_create(
        request: Request,
        payload: DevolucaoManualPayload,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        try:
            uid = request.session.get("user_id")
            user = session.get(models.User, uid) if uid else None
            created_by = user.username if user else None

            dt = datetime.strptime(payload.data_romaneio, "%Y-%m-%d")
            motivo = session.get(models.DevolucaoMotivo, payload.motivo_id)
            resp = session.get(models.DevolucaoResponsabilidade, payload.responsabilidade_id)
            motivo_nome = motivo.nome if motivo else "Importado"
            resp_nome = resp.nome if resp else "IMPORT"
            r_dict = {
                "data_romaneio": payload.data_romaneio,
                "data_entrega": payload.data_entrega,
                "client_id": payload.client_id,
                "motorista_id": payload.motorista_id,
                "valor": payload.valor,
            }
            route_id = _reconcile_devolucao_with_route(session, r_dict, motivo_nome, resp_nome)
            dev = models.Devolucao(
                route_id=route_id,
                data_romaneio=payload.data_romaneio,
                data_entrega=payload.data_entrega,
                client_id=payload.client_id,
                vendedor_id=payload.vendedor_id,
                motorista_id=payload.motorista_id,
                ajudante_id=payload.ajudante_id,
                valor=payload.valor,
                motivo_id=payload.motivo_id,
                observacao=payload.observacao,
                responsabilidade_id=payload.responsabilidade_id,
                dia=compute_dia(dt),
                semana=compute_semana(dt),
                acima_300=compute_acima_300(payload.valor),
                cluster=compute_cluster(payload.valor),
                idempotency_hash=make_idempotency_hash(
                    payload.data_romaneio,
                    payload.client_id,
                    payload.vendedor_id,
                    payload.motorista_id,
                    payload.valor,
                    payload.motivo_id,
                ),
                source="MANUAL",
                created_by=created_by,
            )
            session.add(dev)
            session.commit()
            return JSONResponse({"ok": True, "id": dev.id})
        except Exception as e:
            logger.exception(f"Erro ao criar devolucao manual: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @router.post("/api/devolucoes/reconnect-orphans", response_class=JSONResponse)
    async def api_devolucoes_reconnect_orphans(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Reconecta devoluções ORPHAN_ROUTE às rotas existentes (vincula route_id, limpa fila).
        Não altera o status da rota. Exige período (start_date e end_date)."""
        require_login(request)
        try:
            body = {}
            try:
                body = await request.json()
            except Exception:
                pass
            start_date = body.get("start_date") or ""
            end_date = body.get("end_date") or ""
            if not start_date or not end_date:
                return JSONResponse(
                    {"ok": False, "error": "Período obrigatório. Informe start_date e end_date."},
                    status_code=400,
                )
            if start_date > end_date:
                return JSONResponse(
                    {"ok": False, "error": "Data início deve ser anterior à data fim."},
                    status_code=400,
                )
            reconnected = reconnect_orphan_devolucoes(session, start_date, end_date)
            backfill_updated = backfill_duplicate_links_period(session, start_date, end_date)
            session.commit()
            return JSONResponse({
                "ok": True,
                "reconnected": reconnected,
                "duplicates_linked": backfill_updated,
            })
        except Exception as e:
            logger.exception(f"Erro ao reconectar órfãos: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @router.post("/api/devolucoes/reconcile-routes", response_class=JSONResponse)
    async def api_devolucoes_reconcile_routes(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Reconcilia devoluções existentes com rotas: atualiza Route para devolução quando houver match.
        Exige período (start_date e end_date) obrigatório."""
        require_login(request)
        try:
            body = {}
            try:
                body = await request.json()
            except Exception:
                pass
            start_date = body.get("start_date") or ""
            end_date = body.get("end_date") or ""
            if not start_date or not end_date:
                return JSONResponse(
                    {"ok": False, "error": "Período obrigatório. Informe data início e data fim."},
                    status_code=400,
                )
            if start_date > end_date:
                return JSONResponse(
                    {"ok": False, "error": "Data início deve ser anterior à data fim."},
                    status_code=400,
                )
            updated = reconcile_all_devolucoes_with_routes(session, start_date, end_date)
            session.commit()
            return JSONResponse({"ok": True, "updated_routes": updated})
        except Exception as e:
            logger.exception(f"Erro ao reconciliar devolucoes com rotas: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @router.post("/api/devolucoes/rematch-motoristas", response_class=JSONResponse)
    async def api_devolucoes_rematch_motoristas(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Corrige devoluções que ficaram com motorista_id = ajudante: substitui pelo motorista correto."""
        require_login(request)
        try:
            body = {}
            try:
                body = await request.json()
            except Exception:
                pass
            start_date = body.get("start_date")
            end_date = body.get("end_date")
            updated = rematch_motoristas_from_ajudantes(session, start_date, end_date)
            session.commit()
            return JSONResponse({"ok": True, "updated_devolucoes": updated})
        except Exception as e:
            logger.exception(f"Erro ao corrigir motoristas: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @router.get("/api/devolucoes", response_class=JSONResponse)
    async def api_devolucoes_list(
        request: Request,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        q = select(models.Devolucao).order_by(models.Devolucao.data_romaneio.desc(), models.Devolucao.created_at.desc())
        if start_date:
            q = q.where(models.Devolucao.data_romaneio >= start_date)
        if end_date:
            q = q.where(models.Devolucao.data_romaneio <= end_date)
        rows = session.exec(q.limit(500)).all()
        out = []
        for d in rows:
            c = session.get(models.Client, d.client_id)
            m = session.get(models.Employee, d.motorista_id)
            v = session.get(models.Employee, d.vendedor_id)
            motivo = session.get(models.DevolucaoMotivo, d.motivo_id)
            resp = session.get(models.DevolucaoResponsabilidade, d.responsabilidade_id)
            out.append(
                {
                    "id": d.id,
                    "data_romaneio": d.data_romaneio,
                    "data_entrega": d.data_entrega,
                    "valor": d.valor,
                    "cluster": d.cluster,
                    "acima_300": d.acima_300,
                    "source": d.source,
                    "client_name": c.name if c else "-",
                    "motorista_name": m.name if m else "-",
                    "vendedor_name": v.name if v else "-",
                    "motivo": motivo.nome if motivo else "-",
                    "responsabilidade": resp.nome if resp else "-",
                }
            )
        return JSONResponse({"ok": True, "data": out})

    # --- Página Avaliar e Validar Devoluções ---
    @router.get("/devolucoes/avaliar", response_class=HTMLResponse)
    async def devolucoes_avaliar_page(
        request: Request,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        month_start_str = now.replace(day=1).strftime("%Y-%m-%d")
        # Sem filtros na URL: período = início do mês até hoje (ex.: 01/03 → 18/03)
        if not date_from and not date_to:
            date_from = month_start_str
            date_to = today_str
        else:
            if not date_from:
                date_from = today_str
            if not date_to:
                date_to = today_str
        clients = session.exec(select(models.Client).order_by(models.Client.name)).all()
        employees = session.exec(
            select(models.Employee).where(models.Employee.status != "fired").order_by(models.Employee.name)
        ).all()
        motivos = session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.is_active == True)).all()
        responsabilidades = session.exec(
            select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.is_active == True)
        ).all()
        avaliar_employees = [{"id": e.id, "name": getattr(e, "name", "") or ""} for e in employees]
        avaliar_clients = [{"id": c.id, "name": getattr(c, "name", "") or "", "razao_social": getattr(c, "razao_social", "") or ""} for c in clients]
        return templates.TemplateResponse(
            "devolucoes_avaliar.html",
            {
                "request": request,
                "clients": clients,
                "employees": employees,
                "avaliar_employees": avaliar_employees,
                "avaliar_clients": avaliar_clients,
                "motivos": motivos,
                "responsabilidades": responsabilidades,
                "date_from": date_from,
                "date_to": date_to,
            },
        )

    @router.get("/api/devolucoes/avaliar/list", response_class=JSONResponse)
    async def api_devolucoes_avaliar_list(
        request: Request,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        motorista_ids: Optional[str] = None,
        client_ids: Optional[str] = None,
        q: Optional[str] = None,
        ajudante_ids: Optional[str] = None,
        colaborador_ids: Optional[str] = None,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        q_devol = (
            select(models.Devolucao)
            .where(models.Devolucao.data_romaneio >= (date_from or "2020-01-01"))
            .where(models.Devolucao.data_romaneio <= (date_to or "2099-12-31"))
            .order_by(models.Devolucao.data_romaneio.desc(), models.Devolucao.id.desc())
        )
        devolucoes = session.exec(q_devol).all()
        devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]
        motorista_id_list = []
        if motorista_ids and str(motorista_ids).strip():
            for x in str(motorista_ids).split(","):
                try:
                    i = int(x.strip())
                    if i and i not in motorista_id_list:
                        motorista_id_list.append(i)
                except ValueError:
                    pass
        client_id_list = []
        if client_ids and str(client_ids).strip():
            for x in str(client_ids).split(","):
                try:
                    i = int(x.strip())
                    if i and i not in client_id_list:
                        client_id_list.append(i)
                except ValueError:
                    pass
        if motorista_id_list:
            devolucoes = [d for d in devolucoes if d.motorista_id in motorista_id_list]
        if client_id_list:
            devolucoes = [d for d in devolucoes if d.client_id in client_id_list]
        if q and str(q).strip():
            search = str(q).strip().lower()
            from sqlalchemy import or_
            clients_match = session.exec(
                select(models.Client).where(
                    or_(
                        func.lower(models.Client.name).contains(search),
                        (models.Client.razao_social.is_not(None)) & (func.lower(models.Client.razao_social).contains(search)),
                    )
                )
            ).all()
            try:
                client_ids_from_q = [c.id for c in clients_match]
            except Exception:
                client_ids_from_q = []
            if client_ids_from_q:
                devolucoes = [d for d in devolucoes if d.client_id in client_ids_from_q]
            else:
                devolucoes = []
        ids = [d.id for d in devolucoes]
        ajustes = {}
        if ids:
            for aj in session.exec(
                select(models.DevolucaoAjusteResponsabilidade).where(
                    models.DevolucaoAjusteResponsabilidade.devolucao_id.in_(ids)
                )
            ).all():
                ajustes[aj.devolucao_id] = (getattr(aj, "responsavel_motorista", True), getattr(aj, "responsavel_ajudante", True))
        cards = [_build_devolucao_card(session, d) for d in devolucoes]
        ajudante_id_list = []
        if ajudante_ids and str(ajudante_ids).strip():
            for x in str(ajudante_ids).split(","):
                try:
                    i = int(x.strip())
                    if i and i not in ajudante_id_list:
                        ajudante_id_list.append(i)
                except ValueError:
                    pass
        colaborador_id_list = []
        if colaborador_ids and str(colaborador_ids).strip():
            for x in str(colaborador_ids).split(","):
                try:
                    i = int(x.strip())
                    if i and i not in colaborador_id_list:
                        colaborador_id_list.append(i)
                except ValueError:
                    pass
        if ajudante_id_list:
            cards = [c for c in cards if (c.get("ajudante_id") or 0) in ajudante_id_list]
        if colaborador_id_list:
            cards = [c for c in cards if (c.get("motorista_id") in colaborador_id_list) or (c.get("ajudante_id") in colaborador_id_list)]
        for c in cards:
            pair = ajustes.get(c["id"], (True, True))
            c["responsavel_motorista"] = pair[0] if isinstance(pair, tuple) else pair
            c["responsavel_ajudante"] = pair[1] if isinstance(pair, tuple) else True
            c["edited"] = c["id"] in ajustes
        return JSONResponse({"ok": True, "data": cards})

    class DevolucaoPatchPayload(BaseModel):
        motivo_id: Optional[int] = None
        motorista_id: Optional[int] = None
        ajudante_id: Optional[int] = None
        valor: Optional[float] = None
        peso_kg: Optional[float] = None
        observacao_gestor: Optional[str] = None  # Observação do gestor (quem alterou fica em edited_by/edited_at)

    @router.patch("/api/devolucoes/{devolucao_id}", response_class=JSONResponse)
    async def api_devolucoes_patch(
        request: Request,
        devolucao_id: int,
        payload: DevolucaoPatchPayload,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        dev = session.get(models.Devolucao, devolucao_id)
        if not dev:
            return JSONResponse({"ok": False, "error": "Devolução não encontrada."}, status_code=404)
        try:
            if payload.motivo_id is not None:
                motivo = session.get(models.DevolucaoMotivo, payload.motivo_id)
                if motivo:
                    dev.motivo_id = payload.motivo_id
                    if dev.route_id:
                        route = session.get(models.Route, dev.route_id)
                        if route:
                            route.delivery_return_reason = motivo.nome
                            session.add(route)
            if payload.motorista_id is not None:
                dev.motorista_id = payload.motorista_id
                if dev.route_id:
                    route = session.get(models.Route, dev.route_id)
                    if route:
                        route.employee_id = payload.motorista_id
                        session.add(route)
            if payload.ajudante_id is not None:
                dev.ajudante_id = payload.ajudante_id if payload.ajudante_id else None
            if payload.observacao_gestor is not None:
                dev.observacao_gestor = (payload.observacao_gestor or "").strip() or None
                dev.observacao_gestor_edited_at = datetime.now()
                if request.session.get("user_id"):
                    u = session.get(models.User, request.session["user_id"])
                    dev.observacao_gestor_edited_by = u.username if u and getattr(u, "username", None) else str(request.session["user_id"])
                else:
                    dev.observacao_gestor_edited_by = None
            if payload.valor is not None and payload.valor >= 0:
                dev.valor = round(float(payload.valor), 2)
                dev.acima_300 = "SIM" if dev.valor >= 300 else "NAO"
                dev.cluster = compute_cluster(dev.valor)
                if dev.route_id:
                    route = session.get(models.Route, dev.route_id)
                    if route:
                        route.valor_devolucao = dev.valor
                        session.add(route)
            if payload.peso_kg is not None and dev.route_id:
                route = session.get(models.Route, dev.route_id)
                if route:
                    route.devolucao_volume = round(float(payload.peso_kg), 2)
                    route.tonnage = route.devolucao_volume
                    session.add(route)
            session.add(dev)
            session.commit()
            return JSONResponse({"ok": True, "data": _build_devolucao_card(session, dev)})
        except Exception as e:
            logger.exception(f"Erro ao atualizar devolucao: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @router.post("/api/devolucoes/avaliar/consolidado", response_class=JSONResponse)
    async def api_devolucoes_avaliar_consolidado_set(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Define se a responsabilidade da devolução é do motorista e/ou do ajudante (para visão consolidada; não altera dados reais)."""
        require_login(request)
        try:
            body = await request.json()
            devolucao_id = int(body.get("devolucao_id", 0))
            responsavel_motorista = bool(body.get("responsavel_motorista", True))
            responsavel_ajudante = bool(body.get("responsavel_ajudante", True))
            if not devolucao_id:
                return JSONResponse({"ok": False, "error": "devolucao_id obrigatório."}, status_code=400)
            dev = session.get(models.Devolucao, devolucao_id)
            if not dev:
                return JSONResponse({"ok": False, "error": "Devolução não encontrada."}, status_code=404)
            updated_by = None
            if request.session.get("user_id"):
                u = session.get(models.User, request.session["user_id"])
                if u:
                    updated_by = u.username
            existing = session.exec(
                select(models.DevolucaoAjusteResponsabilidade).where(
                    models.DevolucaoAjusteResponsabilidade.devolucao_id == devolucao_id
                )
            ).first()
            if existing:
                existing.responsavel_motorista = responsavel_motorista
                existing.responsavel_ajudante = responsavel_ajudante
                existing.updated_at = datetime.now()
                existing.updated_by = updated_by
                session.add(existing)
            else:
                session.add(
                    models.DevolucaoAjusteResponsabilidade(
                        devolucao_id=devolucao_id,
                        responsavel_motorista=responsavel_motorista,
                        responsavel_ajudante=responsavel_ajudante,
                        updated_by=updated_by,
                    )
                )
            session.commit()
            return JSONResponse({"ok": True})
        except Exception as e:
            logger.exception(f"Erro ao salvar ajuste consolidado: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    def _parse_route_helper_ids(helpers_json: Optional[str]) -> List[int]:
        if not helpers_json:
            return []
        try:
            data = json.loads(helpers_json) if isinstance(helpers_json, str) else helpers_json
            if not isinstance(data, list):
                return []
            return [int(x) for x in data if x is not None and str(x).strip().isdigit()]
        except Exception:
            return []

    def _parse_helpers_to_ids(helpers_json: Optional[str], emp_by_name: dict) -> List[int]:
        if not helpers_json or not emp_by_name:
            return []
        try:
            data = json.loads(helpers_json) if isinstance(helpers_json, str) else helpers_json
            if not isinstance(data, list):
                return []
            ids = []
            for h in data:
                if h is None:
                    continue
                if isinstance(h, int) and h > 0:
                    ids.append(h)
                elif isinstance(h, str) and str(h).strip().isdigit():
                    ids.append(int(h.strip()))
                elif isinstance(h, str) and (h or "").strip():
                    eid = emp_by_name.get((h or "").strip().lower())
                    if eid and eid not in ids:
                        ids.append(eid)
            return ids
        except Exception:
            return []

    def _effective_ajudante_id(
        d: models.Devolucao,
        route_helpers: dict,
        route_by_client_driver_date: dict,
        session_helpers_by_driver_date: dict,
    ) -> Optional[int]:
        """Retorna o ajudante_id efetivo: Devolucao.ajudante_id ou da rota/sessão."""
        if d.ajudante_id:
            return d.ajudante_id
        helper_ids = None
        if getattr(d, "route_id", None) and route_helpers.get(d.route_id):
            helper_ids = route_helpers[d.route_id]
        if not helper_ids and d.client_id and d.motorista_id and d.data_romaneio:
            dt_key = str(d.data_romaneio)[:10]
            key = (d.client_id, d.motorista_id, dt_key)
            helper_ids = route_by_client_driver_date.get(key)
        if not helper_ids and d.motorista_id and d.data_romaneio:
            dt_key = str(d.data_romaneio)[:10]
            session_key = (dt_key, d.motorista_id)
            helper_ids = session_helpers_by_driver_date.get(session_key)
        if not helper_ids:
            return None
        aid = helper_ids[0]
        if aid == d.motorista_id and len(helper_ids) > 1:
            aid = helper_ids[1]
        elif aid == d.motorista_id:
            return None
        return aid

    @router.get("/api/devolucoes/avaliar/consolidado/resumo", response_class=JSONResponse)
    async def api_devolucoes_avaliar_consolidado_resumo(
        request: Request,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        session: Session = Depends(get_session),
    ):
        """Resumo por motorista e por ajudante (ajudante efetivo: devolução, rota ou sessão)."""
        require_login(request)
        date_from = date_from or "2020-01-01"
        date_to = date_to or "2099-12-31"
        devolucoes = session.exec(
            select(models.Devolucao)
            .where(models.Devolucao.data_romaneio >= date_from)
            .where(models.Devolucao.data_romaneio <= date_to)
            .order_by(models.Devolucao.motorista_id, models.Devolucao.id)
        ).all()
        devolucoes = [d for d in devolucoes if not getattr(d, "duplicate_of_id", None)]
        ajustes_list = session.exec(select(models.DevolucaoAjusteResponsabilidade)).all()
        ajustes = {}
        for aj in ajustes_list:
            rm = getattr(aj, "responsavel_motorista", True)
            ra = getattr(aj, "responsavel_ajudante", True)
            ajustes[aj.devolucao_id] = (rm, ra)
        routes_delivered = session.exec(
            select(models.Route)
            .where(models.Route.type == "delivery")
            .where(models.Route.date >= date_from)
            .where(models.Route.date <= date_to)
            .where(models.Route.delivery_status == "entregue")
        ).all()
        all_employees = list(session.exec(select(models.Employee)).all())
        emp_by_name = {e.name.strip().lower(): e.id for e in all_employees if e and getattr(e, "name", None) and getattr(e, "id", None)}
        route_ids = sorted({d.route_id for d in devolucoes if getattr(d, "route_id", None)})
        route_helpers = {}
        if route_ids:
            routes_linked = session.exec(select(models.Route).where(models.Route.id.in_(route_ids))).all()
            for r in routes_linked:
                raw = getattr(r, "delivery_helpers_json", None)
                ids = _parse_route_helper_ids(raw) or _parse_helpers_to_ids(raw, emp_by_name)
                if ids:
                    route_helpers[r.id] = ids
        route_by_client_driver_date = {}
        routes_in_range = session.exec(
            select(models.Route)
            .where(models.Route.date >= date_from)
            .where(models.Route.date <= date_to)
            .where(models.Route.client_id.is_not(None))
            .where(models.Route.employee_id.is_not(None))
        ).all()
        for r in routes_in_range:
            raw = getattr(r, "delivery_helpers_json", None)
            ids = _parse_route_helper_ids(raw) or _parse_helpers_to_ids(raw, emp_by_name)
            if ids and r.client_id and r.employee_id:
                key = (r.client_id, r.employee_id, str(r.date)[:10])
                if key not in route_by_client_driver_date:
                    route_by_client_driver_date[key] = ids
        session_helpers_by_driver_date = {}
        sessions_in_range = session.exec(
            select(models.DeliverySession)
            .where(models.DeliverySession.date >= date_from)
            .where(models.DeliverySession.date <= date_to)
        ).all()
        for ds in sessions_in_range:
            raw = getattr(ds, "helpers_json", None)
            ids = _parse_route_helper_ids(raw) or _parse_helpers_to_ids(raw, emp_by_name)
            if ids and ds.employee_id:
                key = (str(getattr(ds, "date", "") or "")[:10], ds.employee_id)
                if key not in session_helpers_by_driver_date:
                    session_helpers_by_driver_date[key] = ids
        effective_ajudante_ids = {
            _effective_ajudante_id(d, route_helpers, route_by_client_driver_date, session_helpers_by_driver_date)
            for d in devolucoes
        }
        effective_ajudante_ids.discard(None)
        emp_ids = list(
            {d.motorista_id for d in devolucoes}
            | {d.ajudante_id for d in devolucoes if d.ajudante_id}
            | {r.employee_id for r in routes_delivered}
            | effective_ajudante_ids
        )
        employees = {e.id: e for e in session.exec(select(models.Employee).where(models.Employee.id.in_(emp_ids))).all()}
        by_driver = {}
        for r in routes_delivered:
            eid = r.employee_id
            if eid not in by_driver:
                by_driver[eid] = {"entregues": 0, "devolucoes_total": 0, "devolucoes_valor_total": 0.0, "devolucoes_attributed": 0, "devolucoes_valor_attributed": 0.0}
            by_driver[eid]["entregues"] += 1
        for d in devolucoes:
            eid = d.motorista_id
            if eid not in by_driver:
                by_driver[eid] = {"entregues": 0, "devolucoes_total": 0, "devolucoes_valor_total": 0.0, "devolucoes_attributed": 0, "devolucoes_valor_attributed": 0.0}
            by_driver[eid]["devolucoes_total"] += 1
            by_driver[eid]["devolucoes_valor_total"] += float(d.valor or 0)
            if ajustes.get(d.id, (True, True))[0]:
                by_driver[eid]["devolucoes_attributed"] += 1
                by_driver[eid]["devolucoes_valor_attributed"] += float(d.valor or 0)
        out = []
        for eid, stats in by_driver.items():
            emp = employees.get(eid)
            name = emp.name if emp else f"Motorista #{eid}"
            total_paradas = stats["entregues"] + stats["devolucoes_total"]
            pct_original = (stats["devolucoes_total"] / total_paradas * 100) if total_paradas else 0
            total_attributed = stats["entregues"] + stats["devolucoes_attributed"]
            pct_ajustado = (stats["devolucoes_attributed"] / total_attributed * 100) if total_attributed else 0
            out.append({
                "motorista_id": eid,
                "motorista_name": name,
                "entregues": stats["entregues"],
                "devolucoes_total": stats["devolucoes_total"],
                "devolucoes_valor_total": round(stats["devolucoes_valor_total"], 2),
                "devolucoes_attributed": stats["devolucoes_attributed"],
                "devolucoes_valor_attributed": round(stats["devolucoes_valor_attributed"], 2),
                "pct_original": round(pct_original, 2),
                "pct_ajustado": round(pct_ajustado, 2),
                "valor_original": round(stats["devolucoes_valor_total"], 2),
                "valor_ajustado": round(stats["devolucoes_valor_attributed"], 2),
            })
        out.sort(key=lambda x: (-x["devolucoes_total"], x["motorista_name"]))
        # Ajudantes do dia (motorista + data): união de IDs vindos de qualquer rota do período
        # (entregue, devolução, etc.) — alinha com a lógica de devolução (sessão / outras paradas).
        day_union_helpers: Dict[tuple, List[int]] = {}
        for r in routes_in_range:
            key_d = (str(r.date)[:10], r.employee_id)
            raw_u = getattr(r, "delivery_helpers_json", None)
            ids_u = _parse_route_helper_ids(raw_u) or _parse_helpers_to_ids(raw_u, emp_by_name)
            drv_u = int(r.employee_id) if r.employee_id else 0
            acc = day_union_helpers.setdefault(key_d, [])
            seen_u = set(acc)
            for hid in ids_u or []:
                try:
                    hu = int(hid)
                except (TypeError, ValueError):
                    continue
                if hu <= 0 or hu == drv_u or hu in seen_u:
                    continue
                seen_u.add(hu)
                acc.append(hu)

        def _helpers_for_entregue_stop(route_ent: models.Route) -> List[int]:
            key_e = (str(route_ent.date)[:10], route_ent.employee_id)
            raw_e = getattr(route_ent, "delivery_helpers_json", None)
            ids_e = _parse_route_helper_ids(raw_e) or _parse_helpers_to_ids(raw_e, emp_by_name)
            if ids_e:
                return ids_e
            sess = session_helpers_by_driver_date.get(key_e) or []
            if sess:
                return list(sess)
            emp = route_ent.employee_id
            dt = str(route_ent.date)[:10]
            drv_e = int(emp) if emp else 0
            merged: List[int] = []
            seen_m = set()
            for (_cid, mid, dtk), hlist in route_by_client_driver_date.items():
                if mid != emp or dtk != dt:
                    continue
                for hid in hlist or []:
                    try:
                        h = int(hid)
                    except (TypeError, ValueError):
                        continue
                    if h > 0 and h != drv_e and h not in seen_m:
                        seen_m.add(h)
                        merged.append(h)
            if merged:
                return merged
            return list(day_union_helpers.get(key_e) or [])

        # Entregas em que cada funcionário atuou como ajudante (parada entregue + mesma equipe do dia)
        by_ajudante_entregues: Dict[int, int] = {}
        for r in routes_delivered:
            ids = _helpers_for_entregue_stop(r)
            if not ids:
                continue
            seen_h = set()
            drv = int(r.employee_id) if r.employee_id else 0
            for hid in ids:
                try:
                    h = int(hid)
                except (TypeError, ValueError):
                    continue
                if h <= 0 or h == drv or h in seen_h:
                    continue
                seen_h.add(h)
                by_ajudante_entregues[h] = by_ajudante_entregues.get(h, 0) + 1
        by_ajudante: Dict[int, Any] = {}
        for d in devolucoes:
            eid = _effective_ajudante_id(d, route_helpers, route_by_client_driver_date, session_helpers_by_driver_date)
            if eid is None:
                continue
            if eid not in by_ajudante:
                by_ajudante[eid] = {
                    "entregues": by_ajudante_entregues.get(int(eid), 0),
                    "devolucoes_total": 0,
                    "devolucoes_valor_total": 0.0,
                    "devolucoes_attributed": 0,
                    "devolucoes_valor_attributed": 0.0,
                }
            by_ajudante[eid]["devolucoes_total"] += 1
            by_ajudante[eid]["devolucoes_valor_total"] += float(d.valor or 0)
            if ajustes.get(d.id, (True, True))[1]:
                by_ajudante[eid]["devolucoes_attributed"] += 1
                by_ajudante[eid]["devolucoes_valor_attributed"] += float(d.valor or 0)
        out_ajudantes = []
        for eid, stats in by_ajudante.items():
            emp = employees.get(eid)
            name = emp.name if emp else f"Ajudante #{eid}"
            ent = int(stats["entregues"] or 0)
            dev_t = stats["devolucoes_total"]
            dev_a = stats["devolucoes_attributed"]
            total_paradas = ent + dev_t
            pct_original = (dev_t / total_paradas * 100) if total_paradas > 0 else (100.0 if dev_t else 0.0)
            total_ajust = ent + dev_a
            pct_ajustado = (dev_a / total_ajust * 100) if total_ajust > 0 else 0.0
            out_ajudantes.append({
                "ajudante_id": eid,
                "ajudante_name": name,
                "entregues": ent,
                "devolucoes_total": dev_t,
                "devolucoes_valor_total": round(stats["devolucoes_valor_total"], 2),
                "devolucoes_attributed": dev_a,
                "devolucoes_valor_attributed": round(stats["devolucoes_valor_attributed"], 2),
                "pct_original": round(pct_original, 2),
                "pct_ajustado": round(pct_ajustado, 2),
                "valor_original": round(stats["devolucoes_valor_total"], 2),
                "valor_ajustado": round(stats["devolucoes_valor_attributed"], 2),
            })
        out_ajudantes.sort(key=lambda x: (-x["devolucoes_total"], x["ajudante_name"]))
        return JSONResponse({"ok": True, "data": out, "data_ajudantes": out_ajudantes})

    return router
