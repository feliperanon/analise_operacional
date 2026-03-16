# -*- coding: utf-8 -*-
"""
Rotas e lógica de inicialização do módulo Devoluções.
"""
from datetime import datetime
from calendar import monthrange
from typing import Optional, List, Any, Callable
import io
from fastapi import Request, Depends, UploadFile, File, APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlmodel import Session, select, func
from pydantic import BaseModel

from database import get_session, engine
import models
from devolucoes_service import (
    _reconcile_devolucao_with_route,
    reconcile_all_devolucoes_with_routes,
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
)
from devolucoes_service import (
    parse_excel as devolucoes_parse_excel,
    validate_rows as devolucoes_validate_rows,
    save_batch as devolucoes_save_batch,
    get_cadastro_health as devolucoes_get_cadastro_health,
    persist_import_batch as devolucoes_persist_import_batch,
)
from devolucoes_service import _load_cadastros as devolucoes_load_cadastros

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
        month: Optional[int] = None,
        year: Optional[int] = None,
        page: int = 1,
        per_page: Optional[int] = None,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        now = datetime.now()
        year = year or now.year
        month = month or now.month
        month = max(1, min(12, month))
        _, last_day = monthrange(year, month)
        start_date = f"{year:04d}-{month:02d}-01"
        end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

        clients = session.exec(select(models.Client).order_by(models.Client.name)).all()
        employees = session.exec(
            select(models.Employee).where(models.Employee.status != "fired").order_by(models.Employee.name)
        ).all()
        motivos = session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.is_active == True)).all()
        responsabilidades = session.exec(
            select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.is_active == True)
        ).all()

        count_q = (
            select(func.count(models.Devolucao.id))
            .where(models.Devolucao.data_romaneio >= start_date)
            .where(models.Devolucao.data_romaneio <= end_date)
        )
        total_count = session.exec(count_q).one()

        base_q = (
            select(models.Devolucao)
            .where(models.Devolucao.data_romaneio >= start_date)
            .where(models.Devolucao.data_romaneio <= end_date)
            .order_by(models.Devolucao.data_romaneio.desc(), models.Devolucao.created_at.desc())
        )
        per_page_effective = min(max(1, per_page or 500), 10000)
        offset = max(0, (page - 1) * per_page_effective)
        devolucoes = session.exec(base_q.offset(offset).limit(per_page_effective)).all()

        client_ids = {d.client_id for d in devolucoes}
        motorista_ids = {d.motorista_id for d in devolucoes}
        client_map = {c.id: c for c in session.exec(select(models.Client).where(models.Client.id.in_(client_ids))).all()} if client_ids else {}
        emp_map = {e.id: e for e in session.exec(select(models.Employee).where(models.Employee.id.in_(motorista_ids))).all()} if motorista_ids else {}

        rows = []
        for dev in devolucoes:
            c = client_map.get(dev.client_id)
            m = emp_map.get(dev.motorista_id)
            rows.append(
                {
                    "id": dev.id,
                    "data_romaneio": dev.data_romaneio,
                    "valor": dev.valor,
                    "cluster": dev.cluster,
                    "acima_300": dev.acima_300,
                    "source": dev.source,
                    "client_name": c.name if c else "-",
                    "motorista_name": m.name if m else "-",
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
                    "month": month,
                    "year": year,
                    "start_date": start_date,
                    "end_date": end_date,
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
            return JSONResponse(
                {
                    "ok": True,
                    "batch_id": batch_id,
                    "total": len(rows),
                    "valid_count": len(valid),
                    "invalid_count": len(invalid),
                    "invalid_details": invalid[:50],
                    "valid_rows": valid,
                    "valid_preview": valid[:10],
                }
            )
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
            return JSONResponse({"ok": True, "batch_id": batch_id, "created": created, "skipped": len(skipped)})
        except Exception as e:
            logger.exception(f"Erro ao commitar importacao de devolucoes: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

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
            dt = datetime.strptime(payload.data_romaneio, "%Y-%m-%d")
            dev.data_romaneio = payload.data_romaneio
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

    @router.get("/devolucoes/avaliar", response_class=HTMLResponse)
    async def devolucoes_avaliar_page(
        request: Request,
        month: Optional[int] = None,
        year: Optional[int] = None,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        now = datetime.now()
        current_year = year or now.year
        current_month = month or now.month
        current_month = max(1, min(12, current_month))

        clients = session.exec(select(models.Client).order_by(models.Client.name)).all()
        employees = session.exec(
            select(models.Employee).where(models.Employee.status != "fired").order_by(models.Employee.name)
        ).all()
        motivos = session.exec(select(models.DevolucaoMotivo).where(models.DevolucaoMotivo.is_active)).all()
        responsabilidades = session.exec(
            select(models.DevolucaoResponsabilidade).where(models.DevolucaoResponsabilidade.is_active)
        ).all()

        return templates.TemplateResponse(
            "devolucoes_avaliar.html",
            {
                "request": request,
                "clients": clients,
                "employees": employees,
                "motivos": motivos,
                "responsabilidades": responsabilidades,
                "current_month": current_month,
                "current_year": current_year,
            },
        )

    return router
