# -*- coding: utf-8 -*-
"""
Rotas e lógica de inicialização do módulo Devoluções.
"""
from datetime import datetime, timedelta
from calendar import monthrange
import unicodedata
from typing import Optional, List, Any, Callable, Dict, Tuple
import io
import json
from urllib.parse import urlencode
from fastapi import Request, Depends, UploadFile, File, APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlmodel import Session, select, func, delete
from sqlalchemy import tuple_, and_, or_, func, literal, case
from sqlalchemy.exc import IntegrityError
from types import SimpleNamespace
from pydantic import BaseModel

from database import get_session, engine as db_engine
import models
from client_import_utils import normalize_phone_br
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
from devolucoes_consolidado import consolidado_avaliar_resumo
from utils.business_calendar import competence_date_str

# Período padrão em /devolucoes/avaliar: somente a partir deste dia do mês (competência operacional).
AVALIAR_DEFAULT_MONTH_START_DAY = 5


def _normalized_employee_role_text(role: Optional[str]) -> str:
    """Alinha a `main._normalized_employee_role` / cargo motorista vs ajudante."""
    role_value = str(role or "").strip()
    if not role_value:
        return ""
    return (
        unicodedata.normalize("NFKD", role_value)
        .encode("ascii", "ignore")
        .decode()
        .upper()
    )


def _is_motorista_cargo(role: Optional[str]) -> bool:
    r = _normalized_employee_role_text(role)
    return ("MOTORISTA" in r) and ("AJUDANTE" not in r)


def _parse_optional_query_int(value: Any) -> Optional[int]:
    """GET com campos vazios (ex.: motorista_id='' em 'Todos') não deve gerar 422 no FastAPI."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


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


def _extract_hhmm(value: Optional[Any]) -> str:
    """Extrai HH:MM de strings como 'HH:MM', 'HH:MM:SS', ISO 8601 ou 'YYYY-MM-DD HH:MM:SS'."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        try:
            return value.strftime("%H:%M")
        except Exception:
            return ""
    s = str(value).strip()
    if not s:
        return ""
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        if " " in s:
            tail = s.split(" ", 1)[1].strip()
            return tail[:5] if ":" in tail[:5] else ""
        return s[:5] if ":" in s[:5] else ""
    except Exception:
        return s[:5] if len(s) >= 5 and ":" in s[:5] else ""


def _fmt_moeda_br(v: float) -> str:
    s = f"{float(v):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_int_br(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return "0"


def _fmt_month_year_pt_br(year: int, month: int) -> str:
    meses = [
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    if 1 <= int(month) <= 12:
        return f"{meses[int(month) - 1].capitalize()} de {int(year):04d}"
    return f"{int(month):02d}/{int(year):04d}"


def _fmt_nb_br(value: Any) -> str:
    if value is None:
        return "-"
    raw = str(value).strip()
    if not raw:
        return "-"
    if raw.replace(".", "").replace(",", "").isdigit():
        digits = raw.replace(".", "").replace(",", "")
        try:
            return f"{int(digits):,}".replace(",", ".")
        except Exception:
            return raw
    return raw


def _employee_phone_whatsapp_pair(stored: Optional[str]) -> Tuple[str, str]:
    """Converte Employee.phone legado em (wa_digits, friendly_display)."""
    raw = str(stored or "").strip()
    if not raw:
        return "", ""

    digits = "".join(ch for ch in raw if ch.isdigit()).lstrip("0")
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    if len(digits) > 11:
        digits = digits[-11:]

    if len(digits) in (10, 11):
        phone_e164, phone_display = normalize_phone_br("+55" + digits)
    else:
        phone_e164, phone_display = normalize_phone_br(raw)

    wa_digits = "".join(ch for ch in str(phone_e164 or "") if ch.isdigit())
    return wa_digits, str(phone_display or raw).strip()


def _build_devolucao_whatsapp_text(
    *,
    client_name: str,
    client_code: str,
    valor_fmt: str,
    motivo_label: str,
    data_display: str,
    motorista_name: str,
    motorista_phone_display: str,
    vendedor_name: str = "",
    vendedor_phone_display: str = "",
) -> str:
    motorista_phone_label = motorista_phone_display or "Nao informado"
    vendedor_phone_label = vendedor_phone_display or "Nao informado"
    nb_label = client_code or "-"
    return (
        "Ola, tudo bem?\n\n"
        "Segue informacao de devolucao:\n\n"
        f"Cliente: {client_name}\n"
        f"NB: {nb_label}\n"
        f"Valor: {valor_fmt}\n"
        f"Motivo: {motivo_label}\n"
        f"Data: {data_display}\n"
        f"Motorista: {motorista_name or '-'}\n"
        f"Telefone motorista: {motorista_phone_label}\n"
        f"Vendedor: {vendedor_name or '-'}\n"
        f"Telefone vendedor: {vendedor_phone_label}\n\n"
        "Por gentileza, verificar o caso e alinhar com o cliente, se necessario.\n\n"
        "Obrigado."
    )


def _normalize_devolucao_source(value: Optional[str]) -> str:
    normalized = (value or "").strip().upper()
    if not normalized:
        return "EXCEL"
    if normalized == "ROTA":
        return "WEB"
    return normalized


def _best_client_name(client: Optional[models.Client]) -> str:
    if not client:
        return "-"
    razao = (getattr(client, "razao_social", None) or "").strip()
    nome = (getattr(client, "name", None) or "").strip()
    fantasia = (getattr(client, "nome_fantasia", None) or "").strip()
    longest = razao if len(razao) >= len(nome) else nome
    return longest or razao or nome or fantasia or "-"


def _devolucao_status_meta(duplicate_of_id: Optional[int], validation_status: Optional[str]) -> Dict[str, str]:
    vstat = (validation_status or "").strip().upper()
    if duplicate_of_id:
        return {
            "key": "duplicata",
            "label": "Duplicata",
            "tone": "critical",
            "hint": "Registro importado em planilha que conflita com um lançamento já existente.",
        }
    if vstat == "ORPHAN_ROUTE":
        return {
            "key": "orfao",
            "label": "Sem rota",
            "tone": "alert",
            "hint": "Ocorrência sem vínculo automático com rota no dia.",
        }
    if vstat == "DUPLICATE_EXCEL":
        return {
            "key": "aguardando",
            "label": "Aguardando",
            "tone": "pending",
            "hint": "Registro aguardando validação administrativa.",
        }
    return {
        "key": "validado",
        "label": "Validado",
        "tone": "ok",
        "hint": "Registro consolidado e liberado para uso nas demais visões.",
    }


def _norm_plate_escala_ord(v: Any) -> str:
    """Mesma normalização de placa usada em `escalas_routes._build_escala_groups`."""
    if v is None:
        return ""
    s = str(v).strip().upper().replace("-", "").replace(" ", "").replace(".", "")
    return s


def _delivery_escala_group_order_map(session: Session, date_from: str, date_to: str) -> Dict[Tuple[str, int, str], int]:
    """Ordem dos grupos (data, motorista, placa) como na escala: primeira aparição na lista de rotas delivery."""
    routes = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date >= date_from)
        .where(models.Route.date <= date_to)
        .order_by(models.Route.date, models.Route.employee_id, models.Route.id)
    ).all()
    order: Dict[Tuple[str, int, str], int] = {}
    i = 0
    for r in routes:
        plate_norm = _norm_plate_escala_ord(getattr(r, "delivery_vehicle_plate", None)) or "-"
        emp_id = int(r.employee_id or 0)
        key = (r.date, emp_id, plate_norm)
        if key not in order:
            order[key] = i
            i += 1
    return order


def _ajudante_first_seen_day_order(session: Session, day_str: str) -> Dict[int, int]:
    """Ordem do dia: primeiro ajudante visto nas rotas delivery (mesma ordem de leitura da escala por motorista/placa)."""
    routes = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == day_str)
        .order_by(models.Route.date, models.Route.employee_id, models.Route.id)
    ).all()
    order: Dict[int, int] = {}
    pos = 0
    for r in routes:
        emp_id = int(r.employee_id or 0)
        raw = getattr(r, "delivery_helpers_json", None)
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            data = []
        if not isinstance(data, list):
            continue
        for x in data:
            if x is None or not str(x).strip().isdigit():
                continue
            hid = int(x)
            if not hid or hid == emp_id:
                continue
            if hid not in order:
                order[hid] = pos
                pos += 1
    return order


def _motorista_first_seen_day_order(session: Session, day_str: str) -> Dict[int, int]:
    """Ordem do dia: primeira aparição de cada motorista nas rotas delivery (alinhado à escala)."""
    routes = session.exec(
        select(models.Route)
        .where(models.Route.type == "delivery")
        .where(models.Route.date == day_str)
        .order_by(models.Route.date, models.Route.employee_id, models.Route.id)
    ).all()
    order: Dict[int, int] = {}
    pos = 0
    for r in routes:
        mid = int(r.employee_id or 0)
        if mid and mid not in order:
            order[mid] = pos
            pos += 1
    return order


def _devolucao_card_escala_group_key(
    card: Dict[str, Any],
    routes_by_id: Dict[int, models.Route],
) -> Tuple[str, int, str]:
    rid = card.get("route_id")
    r = routes_by_id.get(int(rid)) if rid is not None else None
    if r:
        plate_norm = _norm_plate_escala_ord(getattr(r, "delivery_vehicle_plate", None)) or "-"
        return (r.date, int(r.employee_id or 0), plate_norm)
    dr = card.get("data_romaneio")
    day = str(dr)[:10] if dr else ""
    mid = int(card.get("motorista_id") or 0)
    plate_norm = _norm_plate_escala_ord(card.get("vehicle_plate")) or "-"
    return (day, mid, plate_norm)


def _avaliar_card_romaneio_day_ord(c: Dict[str, Any]) -> int:
    s = str(c.get("data_romaneio") or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").toordinal()
    except Exception:
        return 0


def _avaliar_card_time_tie_str(c: Dict[str, Any]) -> str:
    for k in ("returned_at", "finished_at", "started_at"):
        v = c.get(k)
        if v:
            return str(v)
    return ""


def _sort_avaliar_cards_por_romaneio(cards: List[Dict[str, Any]], *, ascending: bool) -> None:
    """Ordena in-place por data do romaneio (dia), depois horário de rota/devolução, depois id."""

    def sk(c: Dict[str, Any]) -> Tuple[int, str, int]:
        return (_avaliar_card_romaneio_day_ord(c), _avaliar_card_time_tie_str(c), int(c.get("id") or 0))

    cards.sort(key=sk, reverse=not ascending)


def _sort_avaliar_cards_por_escala(session: Session, cards: List[Dict[str, Any]], date_from: str, date_to: str) -> None:
    """Ordena in-place: mesma ordem de caminhões/motoristas da escala operacional; desempate por horário e id."""
    df = (date_from or "2020-01-01")[:10]
    dt = (date_to or "2099-12-31")[:10]
    escala_order = _delivery_escala_group_order_map(session, df, dt)
    route_ids = [int(c["route_id"]) for c in cards if c.get("route_id") is not None]
    routes_by_id: Dict[int, models.Route] = {}
    if route_ids:
        uniq = list(dict.fromkeys(route_ids))
        for rr in session.exec(select(models.Route).where(models.Route.id.in_(uniq))).all():
            routes_by_id[int(rr.id)] = rr

    def sort_key(c: Dict[str, Any]) -> Tuple[Any, ...]:
        gkey = _devolucao_card_escala_group_key(c, routes_by_id)
        ei = escala_order.get(gkey)
        sid = int(c.get("id") or 0)
        tt = _avaliar_card_time_tie_str(c)
        if ei is not None:
            return (0, ei, tt, sid)
        return (1, -_avaliar_card_romaneio_day_ord(c), -sid)

    cards.sort(key=sort_key)


def _build_devolucoes_href(params: Dict[str, Any]) -> str:
    clean: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        clean[key] = value
    qs = urlencode(clean, doseq=True)
    return "/devolucoes" + (f"?{qs}" if qs else "")


def _build_devolucao_card(session: Session, d: models.Devolucao) -> dict:
    """Monta um card completo para uma devolução (cliente, endereço, kg, valor, motorista, ajudantes, caminhão, horários)."""
    route = session.get(models.Route, d.route_id) if d.route_id else None
    client = session.get(models.Client, d.client_id)
    motorista = session.get(models.Employee, d.motorista_id)
    motorista_id = d.motorista_id or (getattr(route, "employee_id", None) if route else None)
    motorista_name = (motorista.name if motorista else "").strip().lower()
    # Lista de ajudantes (sem duplicata, ordem preservada)
    ajudantes_names: List[str] = []
    ajudantes_ids: List[int] = []
    def _add_ajudante_name(name: Optional[str]) -> None:
        if not name or not str(name).strip():
            return
        n = str(name).strip()
        if n.lower() == motorista_name:
            return
        if n not in ajudantes_names:
            ajudantes_names.append(n)
    def _add_ajudante_id(emp_id: Optional[int]) -> None:
        try:
            i = int(emp_id) if emp_id is not None else 0
        except Exception:
            i = 0
        if not i:
            return
        if motorista_id and i == motorista_id:
            return
        if i not in ajudantes_ids:
            ajudantes_ids.append(i)

    ajudante = session.get(models.Employee, d.ajudante_id) if d.ajudante_id else None
    effective_ajudante_id = d.ajudante_id
    if ajudante:
        _add_ajudante_id(d.ajudante_id)
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
                            _add_ajudante_id(hid)
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
                                            _add_ajudante_id(aid)
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
        "ajudante_ids": ajudantes_ids,
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
        q: Optional[str] = None,
        source: Optional[str] = None,
        status_view: str = Query(default="all"),
        motorista_id: Optional[str] = Query(default=None),
        sort: str = Query(default="data"),
        dir: str = Query(default="desc"),
        page: Optional[str] = Query(default="1"),
        per_page: Optional[str] = Query(default=None),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        motorista_id = _parse_optional_query_int(motorista_id)
        page = max(1, _parse_optional_query_int(page) or 1)
        now = datetime.now()
        today = now.date()
        today_active = False
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
            period_label = f"Hoje · {_fmt_data_hora_pt_br(start_date)}"
            today_active = True
        elif date_from and date_to:
            d1 = parse_ymd(date_from)
            d2 = parse_ymd(date_to)
            if d1 and d2:
                if d1 > d2:
                    d1, d2 = d2, d1
                start_date = d1.strftime("%Y-%m-%d")
                end_date = d2.strftime("%Y-%m-%d")
                period_label = f"Período {_fmt_data_hora_pt_br(start_date)} a {_fmt_data_hora_pt_br(end_date)}"
            else:
                start_date = today.strftime("%Y-%m-%d")
                end_date = start_date
                period_label = f"Hoje · {_fmt_data_hora_pt_br(start_date)}"
                today_active = True
        else:
            year = now.year
            month = now.month
            _, last_day = monthrange(year, month)
            start_date = f"{year:04d}-{month:02d}-01"
            end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
            period_label = _fmt_month_year_pt_br(year, month)

        search_term = (q or "").strip()
        source_filter = _normalize_devolucao_source(source) if source and str(source).strip() else ""
        if source_filter not in {"EXCEL", "MOBILE", "WEB", "MANUAL"}:
            source_filter = ""
        status_view = (status_view or "all").strip().lower()
        if status_view not in {"all", "aguardando", "duplicata", "orfao", "validado"}:
            status_view = "all"
        sort_key = (sort or "data").strip().lower()
        if sort_key not in {"data", "client", "motorista", "valor", "source", "status"}:
            sort_key = "data"
        sort_dir = (dir or "").strip().lower()
        if sort_dir not in {"asc", "desc"}:
            sort_dir = "desc" if sort_key in {"data", "valor"} else "asc"
        per_page_effective = min(max(25, _parse_optional_query_int(per_page) or 50), 200)

        # Só colunas usadas nos selects (menos tráfego Redis/Postgres que ORM completo)
        er = session.exec(
            select(models.Employee.id, models.Employee.name, models.Employee.seller_code, models.Employee.role)
            .where(models.Employee.status != "fired")
            .order_by(models.Employee.name)
        ).all()
        employees = [SimpleNamespace(id=a, name=b, seller_code=c, role=d) for a, b, c, d in er]
        motoristas = [e for e in employees if _is_motorista_cargo(getattr(e, "role", None))]
        if motorista_id:
            mid = int(motorista_id)
            if not any(e.id == mid for e in motoristas):
                extra = next((e for e in employees if e.id == mid), None)
                if extra:
                    motoristas = sorted(motoristas + [extra], key=lambda x: (x.name or "").upper())
        motivos = session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.is_active == True)).all()
        motivo_map = {int(m.id): (m.nome or "").strip() for m in motivos if getattr(m, "id", None) is not None}
        responsabilidades = session.exec(
            select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.is_active == True)
        ).all()

        # Trazer para a lista apenas devoluções com evidência de origem MOBILE
        # (evita criar registros WEB automáticos que poluem indicadores e duplicatas).
        try:
            routes_devolucao = session.exec(
                select(models.Route)
                .outerjoin(models.Devolucao, models.Devolucao.route_id == models.Route.id)
                .where(models.Route.type == "delivery")
                .where(models.Route.date >= start_date)
                .where(models.Route.date <= end_date)
                .where(func.lower(models.Route.delivery_status) == "devolucao")
                .where(models.Devolucao.id.is_(None))
                .where(
                    or_(
                        models.Route.delivery_notified_commercial.isnot(None),
                        models.Route.delivery_notified_logistics.isnot(None),
                        and_(
                            models.Route.driver_lat_end.isnot(None),
                            models.Route.driver_lon_end.isnot(None),
                        ),
                    )
                )
            ).all()
            synced = 0
            for r in routes_devolucao:
                dev = sync_route_to_devolucao(session, r, source="MOBILE")
                if dev:
                    synced += 1
            if synced:
                session.commit()
        except Exception:
            session.rollback()

        # Período principal = DATA ROMANEIO (como planilha Excel: coluna DATA ROMANEIO, linhas de dados após cabeçalhos).
        # Data efetiva (entrega senão romaneio) pode incluir mais linhas no mesmo mês civil e inflava o total vs Excel.
        eff_date = func.coalesce(models.Devolucao.data_entrega, models.Devolucao.data_romaneio)
        rom_in_period = and_(
            models.Devolucao.data_romaneio >= start_date,
            models.Devolucao.data_romaneio <= end_date,
        )
        count_q = select(func.count(models.Devolucao.id)).where(rom_in_period)
        total_count = session.exec(count_q).one()

        sum_valor_q = (
            select(func.coalesce(func.sum(models.Devolucao.valor), 0.0)).where(rom_in_period)
        )
        period_total_valor = float(session.exec(sum_valor_q).one() or 0.0)

        aguard_period_q = (
            select(func.count(models.Devolucao.id))
            .where(rom_in_period)
            .where(
                or_(
                    models.Devolucao.duplicate_of_id.isnot(None),
                    models.Devolucao.validation_status.in_(["DUPLICATE_EXCEL", "ORPHAN_ROUTE"]),
                )
            )
        )
        period_aguardando_count = session.exec(aguard_period_q).one()

        dup_period_q = (
            select(func.count(models.Devolucao.id))
            .where(rom_in_period)
            .where(models.Devolucao.duplicate_of_id.isnot(None))
        )
        period_duplicate_excel_count = session.exec(dup_period_q).one()
        orphan_period_q = (
            select(func.count(models.Devolucao.id))
            .where(rom_in_period)
            .where(func.upper(func.coalesce(func.trim(models.Devolucao.validation_status), literal(""))) == "ORPHAN_ROUTE")
        )
        period_orphan_count = session.exec(orphan_period_q).one()
        period_validated_count = max(0, int(total_count or 0) - int(period_aguardando_count or 0))

        # Referência operacional: mesma janela de datas, mas por data efetiva (pode divergir do Excel).
        eff_count_q = select(func.count(models.Devolucao.id)).where(eff_date >= start_date).where(eff_date <= end_date)
        period_effetiva_count = session.exec(eff_count_q).one()
        sum_valor_eff_q = (
            select(func.coalesce(func.sum(models.Devolucao.valor), 0.0))
            .where(eff_date >= start_date)
            .where(eff_date <= end_date)
        )
        period_effetiva_valor = float(session.exec(sum_valor_eff_q).one() or 0.0)

        # Origem no período por DATA ROMANEIO (alinhado à listagem e aos KPIs principais).
        src_key = func.upper(func.coalesce(func.trim(models.Devolucao.source), literal("")))
        src_label = case(
            (src_key == literal(""), literal("EXCEL")),
            else_=src_key,
        )
        group_src_q = (
            select(
                src_label.label("origem"),
                func.count(models.Devolucao.id).label("cnt"),
                func.coalesce(func.sum(models.Devolucao.valor), 0.0).label("sv"),
            )
            .where(rom_in_period)
            .group_by(src_label)
        )
        by_source: Dict[str, Dict[str, Any]] = {}
        for row in session.exec(group_src_q).all():
            label = (getattr(row, "origem", None) or "EXCEL").strip() or "EXCEL"
            sv = float(row.sv or 0.0)
            by_source[label] = {
                "count": int(row.cnt),
                "count_fmt": _fmt_int_br(int(row.cnt)),
                "valor": sv,
                "valor_fmt": _fmt_moeda_br(sv),
            }

        latest_import_batch = session.exec(
            select(models.DevolucaoImportBatch)
            .where(models.DevolucaoImportBatch.status == "committed")
            .order_by(models.DevolucaoImportBatch.committed_at.desc(), models.DevolucaoImportBatch.id.desc())
        ).first()
        last_import_summary = None
        if latest_import_batch:
            total_rows = int(latest_import_batch.total_rows or 0)
            invalid_count = int(latest_import_batch.invalid_count or 0)
            created_count = int(latest_import_batch.valid_count or 0)
            skipped_count = max(0, total_rows - invalid_count - created_count)
            last_import_summary = {
                "batch_id": latest_import_batch.id,
                "filename": latest_import_batch.filename or "import.xlsx",
                "total_rows": total_rows,
                "total_rows_fmt": _fmt_int_br(total_rows),
                "invalid_count": invalid_count,
                "invalid_count_fmt": _fmt_int_br(invalid_count),
                "created_count": created_count,
                "created_count_fmt": _fmt_int_br(created_count),
                "skipped_count": skipped_count,
                "skipped_count_fmt": _fmt_int_br(skipped_count),
                "committed_at": latest_import_batch.committed_at.isoformat() if latest_import_batch.committed_at else None,
                "committed_at_fmt": _fmt_data_hora_pt_br(latest_import_batch.committed_at.isoformat()) if latest_import_batch.committed_at else "",
            }

        source_expr = func.upper(func.coalesce(func.trim(models.Devolucao.source), literal("")))
        source_label_expr = case(
            (source_expr == literal(""), literal("EXCEL")),
            (source_expr == literal("ROTA"), literal("WEB")),
            else_=source_expr,
        )
        validation_expr = func.upper(func.coalesce(func.trim(models.Devolucao.validation_status), literal("")))
        effective_date_expr = func.coalesce(models.Devolucao.data_entrega, models.Devolucao.data_romaneio)
        client_name_expr = func.upper(
            func.coalesce(models.Client.razao_social, models.Client.name, models.Client.nome_fantasia, literal(""))
        )
        motorista_name_expr = func.upper(func.coalesce(models.Employee.name, literal("")))
        plate_expr = func.upper(func.coalesce(models.Route.delivery_vehicle_plate, literal("")))
        status_rank_expr = case(
            (models.Devolucao.duplicate_of_id.isnot(None), 0),
            (validation_expr == literal("ORPHAN_ROUTE"), 1),
            (validation_expr == literal("DUPLICATE_EXCEL"), 2),
            else_=3,
        )
        aguardando_expr = or_(
            models.Devolucao.duplicate_of_id.isnot(None),
            validation_expr.in_(["DUPLICATE_EXCEL", "ORPHAN_ROUTE"]),
        )

        def apply_list_filters(stmt):
            stmt = stmt.where(rom_in_period)
            if motorista_id:
                stmt = stmt.where(models.Devolucao.motorista_id == motorista_id)
            if source_filter:
                stmt = stmt.where(source_label_expr == source_filter)
            if status_view == "aguardando":
                stmt = stmt.where(aguardando_expr)
            elif status_view == "duplicata":
                stmt = stmt.where(models.Devolucao.duplicate_of_id.isnot(None))
            elif status_view == "orfao":
                stmt = stmt.where(validation_expr == "ORPHAN_ROUTE")
            elif status_view == "validado":
                stmt = stmt.where(and_(models.Devolucao.duplicate_of_id.is_(None), ~validation_expr.in_(["DUPLICATE_EXCEL", "ORPHAN_ROUTE"])))
            if search_term:
                like = f"%{search_term.lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(func.coalesce(models.Client.razao_social, literal(""))).like(like),
                        func.lower(func.coalesce(models.Client.name, literal(""))).like(like),
                        func.lower(func.coalesce(models.Client.nome_fantasia, literal(""))).like(like),
                        func.lower(func.coalesce(models.Client.nb, literal(""))).like(like),
                        func.lower(func.coalesce(models.Employee.name, literal(""))).like(like),
                        func.lower(func.coalesce(models.Route.delivery_vehicle_plate, literal(""))).like(like),
                        func.lower(source_label_expr).like(like),
                        func.lower(func.coalesce(models.Devolucao.observacao, literal(""))).like(like),
                        func.lower(func.coalesce(models.Devolucao.data_romaneio, literal(""))).like(like),
                        func.lower(func.coalesce(models.Devolucao.data_entrega, literal(""))).like(like),
                    )
                )
            return stmt

        def apply_list_sort(stmt):
            expr = effective_date_expr
            if sort_key == "client":
                expr = client_name_expr
            elif sort_key == "motorista":
                expr = motorista_name_expr
            elif sort_key == "valor":
                expr = models.Devolucao.valor
            elif sort_key == "source":
                expr = source_label_expr
            elif sort_key == "status":
                expr = status_rank_expr

            ordered = expr.desc() if sort_dir == "desc" else expr.asc()
            secondary = effective_date_expr.desc()
            if sort_key == "data":
                secondary = models.Devolucao.created_at.desc()
            return stmt.order_by(ordered, secondary, models.Devolucao.id.desc())

        joins = (
            select(models.Devolucao)
            .outerjoin(models.Client, models.Client.id == models.Devolucao.client_id)
            .outerjoin(models.Employee, models.Employee.id == models.Devolucao.motorista_id)
            .outerjoin(models.Route, models.Route.id == models.Devolucao.route_id)
        )
        count_joins = (
            select(func.count(models.Devolucao.id))
            .select_from(models.Devolucao)
            .outerjoin(models.Client, models.Client.id == models.Devolucao.client_id)
            .outerjoin(models.Employee, models.Employee.id == models.Devolucao.motorista_id)
            .outerjoin(models.Route, models.Route.id == models.Devolucao.route_id)
        )

        filtered_total_count = int(session.exec(apply_list_filters(count_joins)).one() or 0)
        total_pages = max(1, (filtered_total_count + per_page_effective - 1) // per_page_effective) if filtered_total_count else 1
        if page > total_pages:
            page = total_pages
        offset = max(0, (page - 1) * per_page_effective)
        devolucoes = session.exec(
            apply_list_sort(apply_list_filters(joins)).offset(offset).limit(per_page_effective)
        ).all()

        client_ids = {d.client_id for d in devolucoes}
        motorista_ids = {d.motorista_id for d in devolucoes if d.motorista_id}
        vendedor_ids = {d.vendedor_id for d in devolucoes if d.vendedor_id}
        employee_contact_ids = motorista_ids | vendedor_ids
        route_ids = {d.route_id for d in devolucoes if d.route_id}
        client_map = {c.id: c for c in session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all()} if client_ids else {}
        employee_contact_map = {
            e.id: e for e in session.exec(select(models.Employee).where(models.Employee.id.in_(employee_contact_ids))).all()
        } if employee_contact_ids else {}
        route_map = {r.id: r for r in session.exec(select(models.Route).where(models.Route.id.in_(route_ids))).all()} if route_ids else {}
        plate_by_cmd = _plate_by_client_motorista_date(session, devolucoes, route_map)

        rows = []
        for dev in devolucoes:
            c = client_map.get(dev.client_id)
            m = employee_contact_map.get(dev.motorista_id)
            vendedor = employee_contact_map.get(dev.vendedor_id)
            dup_of = getattr(dev, "duplicate_of_id", None)
            vstat = (getattr(dev, "validation_status", None) or "").strip()
            data_efetiva = str(dev.data_entrega or dev.data_romaneio or "")[:10]
            plate = ""
            if dev.route_id and dev.route_id in route_map:
                plate = (route_map[dev.route_id].delivery_vehicle_plate or "").strip()
            if not plate:
                plate = plate_by_cmd.get((dev.client_id, dev.motorista_id, data_efetiva), "")
            status_meta = _devolucao_status_meta(dup_of, vstat)
            cname = _best_client_name(c)
            motivo_label = motivo_map.get(int(dev.motivo_id), "Sem motivo informado") if getattr(dev, "motivo_id", None) else "Sem motivo informado"
            client_code = getattr(c, "nb", None) or ""
            client_fantasia = (getattr(c, "nome_fantasia", None) or "").strip() if c else ""
            client_razao_social = (getattr(c, "razao_social", None) or "").strip() if c else ""
            motorista_name = (m.name if m else "-") or "-"
            motorista_wa_phone, motorista_phone_display = _employee_phone_whatsapp_pair(getattr(m, "phone", None))
            vendedor_wa_phone, vendedor_phone_display = _employee_phone_whatsapp_pair(getattr(vendedor, "phone", None))
            vendedor_name = (vendedor.name if vendedor else "-") or "-"
            data_display = _fmt_data_hora_pt_br(data_efetiva) or data_efetiva or "-"
            linked_route = route_map.get(dev.route_id) if dev.route_id else None
            hora_devolucao = _extract_hhmm(getattr(linked_route, "delivery_returned_at", None))
            if not hora_devolucao:
                hora_devolucao = _extract_hhmm(getattr(dev, "created_at", None))
            if hora_devolucao and data_display and data_display != "-" and ":" not in data_display:
                data_display = f"{data_display} {hora_devolucao}"
            valor_fmt = _fmt_moeda_br(float(dev.valor or 0.0))
            whatsapp_url = ""
            if vendedor_wa_phone:
                whatsapp_text = _build_devolucao_whatsapp_text(
                    client_name=cname,
                    client_code=str(client_code or "").strip(),
                    valor_fmt=valor_fmt,
                    motivo_label=motivo_label,
                    data_display=data_display,
                    motorista_name=motorista_name,
                    motorista_phone_display=motorista_phone_display,
                    vendedor_name=vendedor_name,
                    vendedor_phone_display=vendedor_phone_display,
                )
                whatsapp_url = f"https://wa.me/{vendedor_wa_phone}?{urlencode({'text': whatsapp_text})}"
            secondary_parts = []
            if client_code:
                secondary_parts.append(f"NB {_fmt_nb_br(client_code)}")
            if client_fantasia:
                secondary_parts.append(client_fantasia)
            row_payload = {
                "id": dev.id,
                "client_id": dev.client_id,
                "vendedor_id": dev.vendedor_id,
                "ajudante_id": dev.ajudante_id,
                "motivo_id": dev.motivo_id,
                "responsabilidade_id": dev.responsabilidade_id,
                "data_romaneio": str(dev.data_romaneio)[:10] if dev.data_romaneio else "",
                "data_entrega": str(dev.data_entrega)[:10] if dev.data_entrega else "",
                "data_efetiva": data_efetiva,
                "valor": float(dev.valor) if dev.valor is not None else 0.0,
                "source": _normalize_devolucao_source(dev.source),
                "observacao": dev.observacao or "",
                "client_name": cname,
                "client_code": client_code,
                "client_fantasia": client_fantasia,
                "client_razao_social": client_razao_social,
                "motorista_id": dev.motorista_id,
                "motorista_name": motorista_name,
                "motorista_phone": motorista_wa_phone,
                "motorista_phone_display": motorista_phone_display,
                "vehicle_plate": plate or "—",
            }
            rows.append(
                {
                    "id": dev.id,
                    "client_id": dev.client_id,
                    "motorista_id": dev.motorista_id,
                    "data_display": data_display,
                    "client_name": cname,
                    "client_secondary": " · ".join(secondary_parts) if secondary_parts else "Sem complemento cadastrado",
                    "motorista_name": motorista_name,
                    "motivo_label": motivo_label,
                    "vehicle_plate": plate or "—",
                    "valor": float(dev.valor) if dev.valor is not None else 0.0,
                    "valor_fmt": valor_fmt,
                    "source_label": _normalize_devolucao_source(dev.source),
                    "status_key": status_meta["key"],
                    "status_label": status_meta["label"],
                    "status_tone": status_meta["tone"],
                    "status_hint": status_meta["hint"],
                    "whatsapp_url": whatsapp_url,
                    "whatsapp_enabled": bool(whatsapp_url),
                    "whatsapp_title": (
                        f"Enviar devolucao por WhatsApp para {(vendedor.name or 'o vendedor').strip()}"
                        if vendedor
                        else "Enviar devolucao por WhatsApp"
                    ),
                    "can_approve": status_meta["key"] in {"aguardando", "duplicata", "orfao"},
                    "can_delete": True,
                    "payload_json": json.dumps(row_payload, ensure_ascii=False),
                }
            )

        query_state = {
            "date_from": start_date,
            "date_to": end_date,
            "q": search_term,
            "source": source_filter,
            "status_view": status_view if status_view != "all" else None,
            "motorista_id": motorista_id or None,
            "sort": sort_key,
            "dir": sort_dir,
            "per_page": per_page_effective,
        }

        def build_href(**overrides):
            merged = dict(query_state)
            for key, value in overrides.items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = value
            return _build_devolucoes_href(merged)

        links = {
            "clear": "/devolucoes",
            "today": _build_devolucoes_href(
                {
                    "hoje": "1",
                    "q": search_term,
                    "source": source_filter,
                    "status_view": status_view if status_view != "all" else None,
                    "motorista_id": motorista_id or None,
                    "sort": sort_key,
                    "dir": sort_dir,
                    "per_page": per_page_effective,
                }
            ),
            "all": build_href(status_view=None, page=1),
            "aguardando": build_href(status_view="aguardando", page=1),
            "duplicata": build_href(status_view="duplicata", page=1),
            "orfao": build_href(status_view="orfao", page=1),
            "validado": build_href(status_view="validado", page=1),
            "mobile": build_href(source="MOBILE", page=1),
            "excel": build_href(source="EXCEL", page=1),
            "manual": build_href(source="MANUAL", page=1),
            "web": build_href(source="WEB", page=1),
        }

        sort_links = {}
        for key in ["data", "client", "motorista", "valor", "source", "status"]:
            default_dir = "desc" if key in {"data", "valor"} else "asc"
            next_dir = default_dir
            if sort_key == key:
                next_dir = "asc" if sort_dir == "desc" else "desc"
            sort_links[key] = build_href(sort=key, dir=next_dir, page=1)

        page_start = offset + 1 if filtered_total_count else 0
        page_end = offset + len(rows) if filtered_total_count else 0

        return templates.TemplateResponse(
            "devolucoes.html",
            {
                "request": request,
                "employees": employees,
                "motoristas": motoristas,
                "motivos": motivos,
                "responsabilidades": responsabilidades,
                "devolucoes": rows,
                "import_result": getattr(request.state, "devolucoes_import_result", None),
                "filters": {
                    "date_from": start_date,
                    "date_to": end_date,
                    "start_date": start_date,
                    "end_date": end_date,
                    "period_label": period_label,
                    "today_active": today_active,
                    "q": search_term,
                    "source": source_filter,
                    "status_view": status_view,
                    "motorista_id": motorista_id,
                    "sort": sort_key,
                    "dir": sort_dir,
                },
                "pagination": {
                    "page": page,
                    "per_page": per_page_effective,
                    "total_count": filtered_total_count,
                    "total_count_fmt": _fmt_int_br(filtered_total_count),
                    "total_pages": total_pages,
                    "has_prev": page > 1,
                    "has_next": page < total_pages,
                    "prev_page": page - 1 if page > 1 else 1,
                    "next_page": page + 1 if page < total_pages else total_pages,
                    "page_start": page_start,
                    "page_start_fmt": _fmt_int_br(page_start),
                    "page_end": page_end,
                    "page_end_fmt": _fmt_int_br(page_end),
                    "prev_href": build_href(page=(page - 1 if page > 1 else 1)),
                    "next_href": build_href(page=(page + 1 if page < total_pages else total_pages)),
                },
                "period_stats": {
                    "total_count": total_count,
                    "total_count_fmt": _fmt_int_br(total_count),
                    "total_valor": period_total_valor,
                    "total_valor_fmt": _fmt_moeda_br(period_total_valor),
                    "aguardando_count": period_aguardando_count,
                    "aguardando_count_fmt": _fmt_int_br(period_aguardando_count),
                    "duplicate_excel_count": period_duplicate_excel_count,
                    "duplicate_excel_count_fmt": _fmt_int_br(period_duplicate_excel_count),
                    "orphan_count": period_orphan_count,
                    "orphan_count_fmt": _fmt_int_br(period_orphan_count),
                    "validated_count": period_validated_count,
                    "validated_count_fmt": _fmt_int_br(period_validated_count),
                    "effetiva_count": period_effetiva_count,
                    "effetiva_count_fmt": _fmt_int_br(period_effetiva_count),
                    "effetiva_valor": period_effetiva_valor,
                    "effetiva_valor_fmt": _fmt_moeda_br(period_effetiva_valor),
                    "by_source": by_source,
                },
                "last_import_summary": last_import_summary,
                "links": links,
                "sort_links": sort_links,
                "page_size_options": [50, 100, 200],
                "message": request.query_params.get("message"),
                "level": request.query_params.get("level"),
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
            created_by = None
            if request.session.get("user_id"):
                u = session.get(models.User, request.session["user_id"])
                if u:
                    created_by = u.username
            created, skipped = 0, []
            if valid_rows:
                created, skipped = devolucoes_save_batch(
                    session,
                    valid_rows,
                    {"filename": filename, "batch_id": batch_id},
                    source="EXCEL",
                    created_by=created_by,
                )
            else:
                # Permite confirmar a importação mesmo sem linhas válidas:
                # inválidas já ficam registradas para revisão/download no batch.
                b = None
                try:
                    b = session.get(models.DevolucaoImportBatch, int(batch_id)) if batch_id is not None else None
                except Exception:
                    b = None
                if b:
                    b.status = "committed"
                    b.committed_at = datetime.now()
                    b.valid_count = 0
                    b.pending_count = int(b.invalid_count or 0)
                    session.add(b)
            session.commit()
            if valid_rows:
                _devolucoes_backfill_span(session, valid_rows)
            return JSONResponse(
                {
                    "ok": True,
                    "batch_id": batch_id,
                    "created": created,
                    "skipped": len(skipped),
                    "invalid_count": 0 if valid_rows else (int(getattr(b, "invalid_count", 0) or 0) if b else 0),
                    "message": (
                        "Importação confirmada com registros válidos gravados."
                        if valid_rows
                        else "Importação confirmada sem linhas válidas. As inválidas foram separadas para revisão."
                    ),
                }
            )
        except ValueError as e:
            try:
                session.rollback()
            except Exception:
                pass
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        except IntegrityError as e:
            try:
                session.rollback()
            except Exception:
                pass
            logger.exception(f"Integridade ao commitar importacao de devolucoes: {e}")
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Conflito ao gravar (possível duplicata). Recarregue o preview e tente novamente.",
                },
                status_code=409,
            )
        except Exception as e:
            try:
                session.rollback()
            except Exception:
                pass
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
        """Permite excluir qualquer devolução selecionada na tela (ação administrativa)."""
        return True

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
                {"ok": False, "error": "Não foi possível excluir este registro."},
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
                skipped.append({"id": devolucao_id, "reason": "Não foi possível excluir este registro."})
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

            operation_date = payload.data_entrega or payload.data_romaneio
            competencia = competence_date_str(operation_date) or payload.data_romaneio
            dt = datetime.strptime(competencia, "%Y-%m-%d")
            motivo = session.get(models.DevolucaoMotivo, payload.motivo_id)
            resp = session.get(models.DevolucaoResponsabilidade, payload.responsabilidade_id)
            motivo_nome = motivo.nome if motivo else "Importado"
            resp_nome = resp.nome if resp else "IMPORT"
            r_dict = {
                "data_romaneio": competencia,
                "data_entrega": payload.data_entrega,
                "client_id": payload.client_id,
                "motorista_id": payload.motorista_id,
                "valor": payload.valor,
            }
            route_id = _reconcile_devolucao_with_route(session, r_dict, motivo_nome, resp_nome)
            dev = models.Devolucao(
                route_id=route_id,
                data_romaneio=competencia,
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
                    competencia,
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
            reconnected, not_found = reconnect_orphan_devolucoes(session, start_date, end_date)
            backfill_updated = backfill_duplicate_links_period(session, start_date, end_date)
            session.commit()
            return JSONResponse({
                "ok": True,
                "reconnected": reconnected,
                "duplicates_linked": backfill_updated,
                "not_found": not_found,
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
            aj = session.get(models.Employee, d.ajudante_id) if d.ajudante_id else None
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
                    "observacao": d.observacao,
                    "client_id": d.client_id,
                    "motorista_id": d.motorista_id,
                    "vendedor_id": d.vendedor_id,
                    "ajudante_id": d.ajudante_id,
                    "motivo_id": d.motivo_id,
                    "responsabilidade_id": d.responsabilidade_id,
                    "client_name": c.name if c else "-",
                    "motorista_name": m.name if m else "-",
                    "vendedor_name": v.name if v else "-",
                    "ajudante_name": aj.name if aj else None,
                    "motivo": motivo.nome if motivo else "-",
                    "responsabilidade": resp.nome if resp else "-",
                }
            )
        return JSONResponse({"ok": True, "data": out})

    @router.put("/api/devolucoes/{devolucao_id}", response_class=JSONResponse)
    async def api_devolucoes_update(
        request: Request,
        devolucao_id: int,
        payload: DevolucaoManualPayload,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        try:
            dev = session.get(models.Devolucao, devolucao_id)
            if not dev:
                return JSONResponse({"ok": False, "error": "Devolução não encontrada"}, status_code=404)
            operation_date = payload.data_entrega or payload.data_romaneio
            competencia = competence_date_str(operation_date) or payload.data_romaneio
            dt = datetime.strptime(competencia, "%Y-%m-%d")
            dev.data_romaneio = competencia
            dev.data_entrega = payload.data_entrega
            dev.client_id = payload.client_id
            dev.vendedor_id = payload.vendedor_id
            dev.motorista_id = payload.motorista_id
            dev.ajudante_id = payload.ajudante_id
            dev.valor = payload.valor
            dev.motivo_id = payload.motivo_id
            dev.observacao = payload.observacao
            dev.responsabilidade_id = payload.responsabilidade_id
            dev.dia = compute_dia(dt)
            dev.semana = compute_semana(dt)
            dev.acima_300 = compute_acima_300(payload.valor)
            dev.cluster = compute_cluster(payload.valor)
            session.add(dev)
            session.commit()
            return JSONResponse({"ok": True, "id": dev.id})
        except Exception as e:
            logger.exception(f"Erro ao atualizar devolucao {devolucao_id}: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

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
        current_year = now.year
        current_month = now.month
        month_last_day = monthrange(current_year, current_month)[1]
        month_end_str = now.replace(day=month_last_day).strftime("%Y-%m-%d")
        avaliar_default_from = now.replace(
            day=min(AVALIAR_DEFAULT_MONTH_START_DAY, month_last_day)
        ).strftime("%Y-%m-%d")
        # Sem filtros na URL: do dia 5 (padrão) ao último dia do mês corrente.
        if not date_from and not date_to:
            date_from = avaliar_default_from
            date_to = month_end_str
        else:
            # Com uma data só, completa a outra ponta no mesmo mês informado.
            ref_raw = date_from or date_to
            try:
                ref_dt = datetime.strptime(str(ref_raw)[:10], "%Y-%m-%d")
            except Exception:
                ref_dt = now
            ref_ml = monthrange(ref_dt.year, ref_dt.month)[1]
            ref_first = ref_dt.replace(day=min(AVALIAR_DEFAULT_MONTH_START_DAY, ref_ml)).strftime("%Y-%m-%d")
            ref_last = ref_dt.replace(day=ref_ml).strftime("%Y-%m-%d")
            if not date_from:
                date_from = ref_first
            if not date_to:
                date_to = ref_last
        clients = session.exec(select(models.Client).order_by(models.Client.name)).all()
        employees = session.exec(
            select(models.Employee).where(models.Employee.status != "fired").order_by(models.Employee.name)
        ).all()
        motivos = session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.is_active == True)).all()
        responsabilidades = session.exec(
            select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.is_active == True)
        ).all()
        avaliar_employees = [
            {"id": e.id, "name": getattr(e, "name", "") or ""}
            for e in employees
            if _is_motorista_cargo(getattr(e, "role", None))
        ]
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
        status_view: Optional[str] = None,
        sort: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
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
            cards = [
                c for c in cards
                if ((c.get("ajudante_id") or 0) in ajudante_id_list)
                or any((hid in ajudante_id_list) for hid in (c.get("ajudante_ids") or []))
            ]
        if colaborador_id_list:
            cards = [
                c for c in cards
                if (c.get("motorista_id") in colaborador_id_list)
                or (c.get("ajudante_id") in colaborador_id_list)
                or any((hid in colaborador_id_list) for hid in (c.get("ajudante_ids") or []))
            ]
        for c in cards:
            pair = ajustes.get(c["id"], (True, True))
            c["responsavel_motorista"] = pair[0] if isinstance(pair, tuple) else pair
            c["responsavel_ajudante"] = pair[1] if isinstance(pair, tuple) else True
            c["edited"] = c["id"] in ajustes
        view = (status_view or "all").strip().lower()
        today_iso = datetime.now().strftime("%Y-%m-%d")
        if view == "pendentes":
            cards = [c for c in cards if not c.get("edited")]
        elif view == "concluidos":
            cards = [c for c in cards if c.get("edited")]
        elif view == "hoje":
            cards = [c for c in cards if str(c.get("data_romaneio") or "")[:10] == today_iso]
        sort_mode = (sort or "romaneio_desc").strip().lower()
        d_from = (date_from or "2020-01-01")[:10]
        d_to = (date_to or "2099-12-31")[:10]
        if sort_mode in ("escala", "operacional"):
            _sort_avaliar_cards_por_escala(session, cards, d_from, d_to)
        elif sort_mode in ("romaneio_asc", "data_asc", "asc"):
            _sort_avaliar_cards_por_romaneio(cards, ascending=True)
        else:
            # Padrão: romaneio_desc — mais recente primeiro (lançamentos do fim do período no topo).
            _sort_avaliar_cards_por_romaneio(cards, ascending=False)
        safe_per_page = max(1, min(int(per_page or 20), 100))
        safe_page = max(1, int(page or 1))
        total_count = len(cards)
        total_pages = max(1, (total_count + safe_per_page - 1) // safe_per_page)
        if safe_page > total_pages:
            safe_page = total_pages
        start = (safe_page - 1) * safe_per_page
        end = start + safe_per_page
        return JSONResponse(
            {
                "ok": True,
                "data": cards[start:end],
                "pagination": {
                    "page": safe_page,
                    "per_page": safe_per_page,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "page_start": (start + 1) if total_count else 0,
                    "page_end": min(end, total_count) if total_count else 0,
                },
            }
        )

    class DevolucaoPatchPayload(BaseModel):
        motivo_id: Optional[int] = None
        motorista_id: Optional[int] = None
        ajudante_id: Optional[int] = None
        ajudante_ids: Optional[List[int]] = None
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
            if payload.ajudante_ids is not None:
                motorista_ref = payload.motorista_id if payload.motorista_id is not None else dev.motorista_id
                clean_helper_ids: List[int] = []
                for raw in payload.ajudante_ids:
                    try:
                        hid = int(raw)
                    except Exception:
                        continue
                    if hid <= 0:
                        continue
                    if motorista_ref and hid == motorista_ref:
                        continue
                    if hid not in clean_helper_ids:
                        clean_helper_ids.append(hid)
                dev.ajudante_id = clean_helper_ids[0] if clean_helper_ids else None
                if dev.route_id:
                    route = session.get(models.Route, dev.route_id)
                    if route:
                        data = json.dumps(clean_helper_ids, ensure_ascii=False)
                        route.delivery_helpers_json = data
                        # `Route` não possui campo `helpers_json` no modelo atual.
                        # Mantemos a sincronização no campo oficial de entrega.
                        session.add(route)
            elif payload.ajudante_id is not None:
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
        payload = consolidado_avaliar_resumo(
            session,
            date_from,
            date_to,
            use_competence_window=False,
        )
        return JSONResponse(
            {"ok": True, "data": payload["data"], "data_ajudantes": payload["data_ajudantes"]}
        )

    return router
