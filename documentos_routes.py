# -*- coding: utf-8 -*-
"""Rotas do módulo Documentos Institucionais (Processos e Padronização)."""
import csv
import html
import io
import json
from datetime import datetime, date
from typing import Optional, List, Any, Callable, Dict
from urllib.parse import urlencode

from fastapi import Request, Depends, Form, Query, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, func, or_

from database import get_session
import models

DOC_TIPOS = ["POP", "IT", "FOR", "REL", "COM", "POL", "CHK"]
DOC_STATUS = ["rascunho", "em_revisao", "aprovado", "obsoleto", "arquivado"]
SETORES_PADRAO = [
    ("LOG", "Logística"),
    ("RH", "Recursos Humanos"),
    ("OP", "Operação"),
    ("DIR", "Diretoria"),
    ("ADM", "Administrativo"),
    ("EXP", "Expedição"),
    ("MAN", "Manutenção"),
    ("QLD", "Qualidade"),
    ("FIN", "Financeiro"),
    ("COM", "Comercial"),
]


def ensure_doc_setores_seed(session: Session) -> None:
    """Garante que setores padrão existam."""
    for sigla, nome in SETORES_PADRAO:
        existing = session.exec(select(models.DocSetor).where(models.DocSetor.sigla == sigla)).first()
        if not existing:
            session.add(models.DocSetor(sigla=sigla, nome=nome, ativo=True))
    session.commit()


def formatar_corpo_relatorio(corpo: str) -> str:
    """Converte corpo do relatório em HTML formatado: seções numeradas, listas, parágrafos.
    Emite blocos .doc-section com hierarquia: doc-section-intro (primeira), doc-section-conclusion
    (conclusão), doc-section-final (última seção) para fechamento visual forte."""
    if not corpo or not corpo.strip():
        return ""
    import re
    import unicodedata
    corpo = unicodedata.normalize("NFC", str(corpo))
    lines = corpo.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    in_list = False
    in_section = False
    is_first_section = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<p class='doc-p-space'></p>")
            continue
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m and len(m.group(2)) < 100:
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_section:
                out.append("</div>")
            title_lower = m.group(2).lower()
            is_conclusion = "conclusão" in title_lower or "conclusao" in title_lower
            section_cls = ["doc-section"]
            if is_first_section:
                section_cls.append("doc-section-intro")
                is_first_section = False
            if is_conclusion:
                section_cls.append("doc-section-conclusion")
            cls_str = " ".join(section_cls)
            out.append(f"<div class='{cls_str}'>")
            in_section = True
            out.append(f"<h3 class='doc-section-title'>{html.escape(stripped)}</h3>")
            continue
        if stripped.startswith("- "):
            if not in_section:
                out.append("<div class='doc-section doc-section-intro'>")
                in_section = True
                is_first_section = False
            if not in_list:
                out.append("<ul class='doc-list'>")
                in_list = True
            out.append(f"<li>{html.escape(stripped[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if not in_section:
            out.append("<div class='doc-section doc-section-intro'>")
            in_section = True
            is_first_section = False
        out.append(f"<p class='doc-p'>{html.escape(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    if in_section:
        out.append("</div>")
    html_output = "\n".join(out)
    last_div = html_output.rfind("<div class='")
    if last_div != -1:
        end_quote = html_output.find("'>", last_div)
        if end_quote != -1:
            insert_at = end_quote
            if "doc-section-final" not in html_output[last_div:end_quote]:
                html_output = (
                    html_output[:insert_at] + " doc-section-final" + html_output[insert_at:]
                )
    return html_output


def _build_documentos_href(params: Dict[str, Any]) -> str:
    clean: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        clean[key] = value
    qs = urlencode(clean, doseq=True)
    return "/documentos" + (f"?{qs}" if qs else "")


def _normalize_csv_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "_")


def gerar_proximo_codigo(session: Session, tipo: str, setor_sigla: str) -> str:
    """Gera próximo código no padrão TIPO-SETOR-NNN."""
    tipo = (tipo or "").strip().upper()[:3]
    setor = (setor_sigla or "").strip().upper()[:10]
    if not tipo or not setor:
        return f"{tipo or 'DOC'}-{setor or 'GER'}-001"
    prefix = f"{tipo}-{setor}-"
    stmt = (
        select(func.max(models.DocInstitucional.codigo))
        .where(models.DocInstitucional.codigo.like(f"{prefix}%"))
    )
    last = session.exec(stmt).first()
    if not last or not str(last).startswith(prefix):
        return f"{prefix}001"
    try:
        num = int(str(last)[len(prefix):])
        return f"{prefix}{num + 1:03d}"
    except ValueError:
        return f"{prefix}001"


def init_documentos_router(
    *,
    templates,
    require_login: Callable[[Request], Any],
) -> Any:
    """Cria router do módulo Documentos Institucionais."""
    from fastapi import APIRouter
    router = APIRouter()

    def _apply_doc_base_filters(
        stmt,
        *,
        tipo: Optional[str],
        setor: Optional[str],
        q: Optional[str],
    ):
        if tipo and str(tipo).strip():
            stmt = stmt.where(models.DocInstitucional.tipo_documento == str(tipo).strip().upper()[:3])
        if setor and str(setor).strip():
            stmt = stmt.where(models.DocInstitucional.area_responsavel == str(setor).strip().upper())
        if q and str(q).strip():
            qs = f"%{str(q).strip()}%"
            stmt = stmt.where(
                or_(
                    models.DocInstitucional.titulo.ilike(qs),
                    models.DocInstitucional.codigo.ilike(qs),
                )
            )
        return stmt

    def _apply_doc_visao(
        stmt,
        *,
        visao: str,
        status_legacy: Optional[str],
    ):
        if status_legacy and str(status_legacy).strip() in DOC_STATUS:
            return stmt.where(models.DocInstitucional.status == str(status_legacy).strip())
        v = (visao or "todos").strip().lower()
        if v == "pendentes":
            return stmt.where(
                or_(
                    models.DocInstitucional.status == "rascunho",
                    models.DocInstitucional.status == "em_revisao",
                )
            )
        if v == "aprovados":
            return stmt.where(models.DocInstitucional.status == "aprovado")
        if v == "criticos":
            return stmt.where(models.DocInstitucional.status == "em_revisao")
        if v == "obsoletos":
            return stmt.where(
                or_(
                    models.DocInstitucional.status == "obsoleto",
                    models.DocInstitucional.status == "arquivado",
                )
            )
        if v == "hoje":
            today = date.today()
            start = datetime.combine(today, datetime.min.time())
            end = datetime.combine(today, datetime.max.time())
            return stmt.where(
                models.DocInstitucional.updated_at >= start,
                models.DocInstitucional.updated_at <= end,
            )
        return stmt

    @router.get("/documentos", response_class=HTMLResponse)
    async def documentos_page(
        request: Request,
        tipo: Optional[str] = Query(None),
        setor: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        visao: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        acao: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=100),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        ensure_doc_setores_seed(session)
        setores = list(session.exec(select(models.DocSetor).where(models.DocSetor.ativo == True)).all())
        search_term = (q or "").strip()
        visao_key = (visao or "").strip().lower() or "todos"
        if visao_key not in {"todos", "pendentes", "aprovados", "criticos", "obsoletos", "hoje"}:
            visao_key = "todos"
        status_legacy = (status or "").strip() if status else None
        if status_legacy and status_legacy not in DOC_STATUS:
            status_legacy = None

        # KPIs (mesmos filtros base tipo/setor/busca — sem visão/status)
        stats_stmt = select(models.DocInstitucional.status, func.count(models.DocInstitucional.id)).group_by(
            models.DocInstitucional.status
        )
        stats_stmt = _apply_doc_base_filters(stats_stmt, tipo=tipo, setor=setor, q=search_term or None)
        status_counts: Dict[str, int] = {}
        for row in session.exec(stats_stmt).all():
            st = row[0] if row else None
            if st:
                status_counts[str(st)] = int(row[1] or 0)
        total_cat = sum(status_counts.values())
        kpi_rascunho = status_counts.get("rascunho", 0)
        kpi_revisao = status_counts.get("em_revisao", 0)
        kpi_aprovado = status_counts.get("aprovado", 0)
        kpi_obsoleto_arq = status_counts.get("obsoleto", 0) + status_counts.get("arquivado", 0)

        # Listagem paginada
        count_stmt = select(func.count(models.DocInstitucional.id))
        count_stmt = _apply_doc_base_filters(count_stmt, tipo=tipo, setor=setor, q=search_term or None)
        count_stmt = _apply_doc_visao(count_stmt, visao=visao_key, status_legacy=status_legacy)
        filtered_total = int(session.exec(count_stmt).one() or 0)

        per_page_eff = min(max(int(per_page or 50), 10), 100)
        total_pages = max(1, (filtered_total + per_page_eff - 1) // per_page_eff) if filtered_total else 1
        page_eff = min(max(1, int(page)), total_pages)
        offset = (page_eff - 1) * per_page_eff

        list_stmt = select(models.DocInstitucional).order_by(models.DocInstitucional.updated_at.desc())
        list_stmt = _apply_doc_base_filters(list_stmt, tipo=tipo, setor=setor, q=search_term or None)
        list_stmt = _apply_doc_visao(list_stmt, visao=visao_key, status_legacy=status_legacy)
        documentos = list(session.exec(list_stmt.offset(offset).limit(per_page_eff)).all())

        query_state: Dict[str, Any] = {
            "tipo": (tipo or "").strip() or None,
            "setor": (setor or "").strip() or None,
            "status": status_legacy,
            "visao": visao_key if visao_key != "todos" else None,
            "q": search_term or None,
            "per_page": per_page_eff,
        }

        def build_href(**overrides: Any) -> str:
            merged = {k: v for k, v in query_state.items() if v is not None}
            for k, v in overrides.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            return _build_documentos_href(merged)

        links = {
            "todos": build_href(visao=None, status=None, page=1),
            "pendentes": build_href(visao="pendentes", status=None, page=1),
            "aprovados": build_href(visao="aprovados", status=None, page=1),
            "criticos": build_href(visao="criticos", status=None, page=1),
            "obsoletos": build_href(visao="obsoletos", status=None, page=1),
            "hoje": build_href(visao="hoje", status=None, page=1),
            "clear": "/documentos",
        }
        page_start = offset + 1 if filtered_total else 0
        page_end = offset + len(documentos) if filtered_total else 0
        prev_href = build_href(page=page_eff - 1 if page_eff > 1 else 1)
        next_href = build_href(page=page_eff + 1 if page_eff < total_pages else total_pages)

        return templates.TemplateResponse(
            "documentos_institucionais.html",
            {
                "request": request,
                "documentos": documentos,
                "setores": setores,
                "filtros": {
                    "tipo": tipo,
                    "setor": setor,
                    "status": status_legacy,
                    "visao": visao_key,
                    "q": search_term,
                    "acao": acao,
                },
                "doc_tipos": DOC_TIPOS,
                "doc_status": DOC_STATUS,
                "kpi": {
                    "total": total_cat,
                    "rascunho": kpi_rascunho,
                    "em_revisao": kpi_revisao,
                    "aprovado": kpi_aprovado,
                    "obsoleto_arquivado": kpi_obsoleto_arq,
                    "pendentes": kpi_rascunho + kpi_revisao,
                },
                "pagination": {
                    "page": page_eff,
                    "per_page": per_page_eff,
                    "total_count": filtered_total,
                    "total_pages": total_pages,
                    "has_prev": page_eff > 1,
                    "has_next": page_eff < total_pages,
                    "prev_href": prev_href,
                    "next_href": next_href,
                    "page_start": page_start,
                    "page_end": page_end,
                },
                "links": links,
                "message": request.query_params.get("message"),
                "level": request.query_params.get("level"),
            },
        )

    @router.get("/documentos/novo", response_class=HTMLResponse)
    async def documento_novo_page(
        request: Request,
        tipo: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=10, le=30),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        setores = list(session.exec(select(models.DocSetor).where(models.DocSetor.ativo == True)).all())
        status_filter = (status or "").strip() or None
        if status_filter and status_filter not in DOC_STATUS:
            status_filter = None
        search_term = (q or "").strip()

        stats_stmt = select(models.DocInstitucional.status, func.count(models.DocInstitucional.id)).group_by(
            models.DocInstitucional.status
        )
        status_counts: Dict[str, int] = {}
        for row in session.exec(stats_stmt).all():
            if row and row[0]:
                status_counts[str(row[0])] = int(row[1] or 0)
        kpi_rascunho = status_counts.get("rascunho", 0)
        kpi_revisao = status_counts.get("em_revisao", 0)
        kpi_aprovado = status_counts.get("aprovado", 0)

        base_count = select(func.count(models.DocInstitucional.id))
        base_list = select(models.DocInstitucional).order_by(models.DocInstitucional.updated_at.desc())
        if status_filter:
            base_count = base_count.where(models.DocInstitucional.status == status_filter)
            base_list = base_list.where(models.DocInstitucional.status == status_filter)
        if search_term:
            like_q = f"%{search_term}%"
            cond = or_(
                models.DocInstitucional.titulo.ilike(like_q),
                models.DocInstitucional.codigo.ilike(like_q),
            )
            base_count = base_count.where(cond)
            base_list = base_list.where(cond)

        total = int(session.exec(base_count).one() or 0)
        total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
        page_eff = min(max(1, int(page)), total_pages)
        offset = (page_eff - 1) * per_page
        recentes = list(session.exec(base_list.offset(offset).limit(per_page)).all())
        return templates.TemplateResponse(
            "documento_form.html",
            {
                "request": request,
                "documento": None,
                "setores": setores,
                "doc_tipos": DOC_TIPOS,
                "doc_status": DOC_STATUS,
                "tipo_predefinido": (tipo or "").upper() if tipo else None,
                "kpi": {
                    "total": sum(status_counts.values()),
                    "pendentes": kpi_rascunho + kpi_revisao,
                    "aprovado": kpi_aprovado,
                    "setores": len(setores),
                },
                "recentes": recentes,
                "filtros": {
                    "q": search_term,
                    "status": status_filter,
                },
                "pagination": {
                    "page": page_eff,
                    "per_page": per_page,
                    "total_count": total,
                    "total_pages": total_pages,
                    "page_start": (offset + 1) if total else 0,
                    "page_end": (offset + len(recentes)) if total else 0,
                },
            },
        )

    @router.post("/documentos", response_class=RedirectResponse)
    async def documento_create(
        request: Request,
        tipo_documento: str = Form(...),
        titulo: str = Form(...),
        area_responsavel: str = Form(...),
        elaborado_por: str = Form(...),
        classificacao: str = Form("Interno"),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        codigo = gerar_proximo_codigo(session, tipo_documento, area_responsavel)
        hoje = datetime.now().strftime("%Y-%m-%d")
        doc = models.DocInstitucional(
            tipo_documento=tipo_documento.upper()[:3],
            codigo=codigo,
            titulo=(titulo or "").strip(),
            area_responsavel=(area_responsavel or "").strip().upper(),
            elaborado_por=(elaborado_por or "").strip(),
            classificacao=(classificacao or "Interno").strip(),
            status="rascunho",
            data_emissao=hoje,
            versao=1,
            conteudo={},
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return RedirectResponse(url=f"/documentos/{doc.id}", status_code=303)

    @router.get("/documentos/{doc_id}", response_class=HTMLResponse)
    async def documento_detail(
        request: Request,
        doc_id: int,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        doc = session.get(models.DocInstitucional, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        setores = list(session.exec(select(models.DocSetor).where(models.DocSetor.ativo == True)).all())
        c = doc.conteudo or {}
        corpo_html = ""
        if doc.tipo_documento == "REL" and c.get("corpo"):
            corpo_html = formatar_corpo_relatorio(c.get("corpo", ""))
        return templates.TemplateResponse(
            "documento_detalhe.html",
            {
                "request": request,
                "documento": doc,
                "setores": setores,
                "doc_tipos": DOC_TIPOS,
                "doc_status": DOC_STATUS,
                "corpo_html": corpo_html,
            },
        )

    @router.get("/documentos/{doc_id}/print", response_class=HTMLResponse)
    async def documento_print_page(
        request: Request,
        doc_id: int,
        session: Session = Depends(get_session),
    ):
        """Página de impressão limpa (sem layout base, sem scroll, fluxo natural multi-página)."""
        require_login(request)
        doc = session.get(models.DocInstitucional, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        c = doc.conteudo or {}
        corpo_html = ""
        if doc.tipo_documento == "REL" and c.get("corpo"):
            corpo_html = formatar_corpo_relatorio(c.get("corpo", ""))
        resp = templates.TemplateResponse(
            "documento_print.html",
            {
                "request": request,
                "documento": doc,
                "corpo_html": corpo_html,
            },
        )
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    @router.get("/documentos/{doc_id}/editar", response_class=HTMLResponse)
    async def documento_editar_page(
        request: Request,
        doc_id: int,
        session: Session = Depends(get_session),
    ):
        require_login(request)
        doc = session.get(models.DocInstitucional, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        if doc.status != "rascunho":
            raise HTTPException(status_code=403, detail="Somente documentos em rascunho podem ser editados.")
        setores = list(session.exec(select(models.DocSetor).where(models.DocSetor.ativo == True)).all())
        conteudo_json = json.dumps(doc.conteudo or {}, ensure_ascii=False, indent=2)
        return templates.TemplateResponse(
            "documento_editar.html",
            {
                "request": request,
                "documento": doc,
                "setores": setores,
                "doc_tipos": DOC_TIPOS,
                "conteudo_json": conteudo_json,
            },
        )

    @router.post("/documentos/{doc_id}", response_class=RedirectResponse)
    async def documento_update(
        request: Request,
        doc_id: int,
        titulo: str = Form(...),
        elaborado_por: str = Form(...),
        revisado_por: str = Form(""),
        aprovado_por: str = Form(""),
        classificacao: str = Form("Interno"),
        conteudo_json: str = Form("{}"),
        objetivo: str = Form(""),
        contexto: str = Form(""),
        descricao: str = Form(""),
        evidencias_fatos: str = Form(""),
        analise: str = Form(""),
        conclusao: str = Form(""),
        observacoes: str = Form(""),
        para: str = Form(""),
        de: str = Form(""),
        data_relatorio: str = Form(""),
        assunto: str = Form(""),
        corpo: str = Form(""),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        doc = session.get(models.DocInstitucional, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        if doc.status != "rascunho":
            raise HTTPException(status_code=403, detail="Somente documentos em rascunho podem ser editados.")
        doc.titulo = (titulo or "").strip()
        doc.elaborado_por = (elaborado_por or "").strip()
        doc.revisado_por = (revisado_por or "").strip() or None
        doc.aprovado_por = (aprovado_por or "").strip() or None
        doc.classificacao = (classificacao or "Interno").strip()
        doc.updated_at = datetime.now()
        conteudo = dict(doc.conteudo or {})
        conteudo["objetivo"] = objetivo.strip() or None
        conteudo["contexto"] = contexto.strip() or None
        conteudo["descricao"] = descricao.strip() or None
        conteudo["evidencias_fatos"] = evidencias_fatos.strip() or None
        conteudo["analise"] = analise.strip() or None
        conteudo["conclusao"] = conclusao.strip() or None
        conteudo["observacoes"] = observacoes.strip() or None
        conteudo["para"] = para.strip() or None
        conteudo["de"] = de.strip() or None
        conteudo["data_relatorio"] = data_relatorio.strip() or None
        conteudo["assunto"] = assunto.strip() or None
        conteudo["corpo"] = corpo.strip() or None
        conteudo = {k: v for k, v in conteudo.items() if v is not None}
        if not conteudo and conteudo_json.strip():
            try:
                conteudo = json.loads(conteudo_json)
            except json.JSONDecodeError:
                conteudo = {}
        doc.conteudo = conteudo
        session.add(doc)
        session.commit()
        return RedirectResponse(url=f"/documentos/{doc.id}?saved=1", status_code=303)

    @router.get("/api/documentos/gerar-codigo", response_class=JSONResponse)
    async def api_gerar_codigo(
        request: Request,
        tipo: str = Query(...),
        setor: str = Query(...),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        codigo = gerar_proximo_codigo(session, tipo, setor)
        return JSONResponse({"codigo": codigo})

    @router.get("/documentos/export.csv")
    async def documentos_export_csv(
        request: Request,
        tipo: Optional[str] = Query(None),
        setor: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        visao: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        search_term = (q or "").strip()
        visao_key = (visao or "").strip().lower() or "todos"
        if visao_key not in {"todos", "pendentes", "aprovados", "criticos", "obsoletos", "hoje"}:
            visao_key = "todos"
        status_legacy = (status or "").strip() if status else None
        if status_legacy and status_legacy not in DOC_STATUS:
            status_legacy = None
        stmt = select(models.DocInstitucional).order_by(models.DocInstitucional.updated_at.desc())
        stmt = _apply_doc_base_filters(stmt, tipo=tipo, setor=setor, q=search_term or None)
        stmt = _apply_doc_visao(stmt, visao=visao_key, status_legacy=status_legacy)
        rows = list(session.exec(stmt.limit(5000)).all())
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["codigo", "tipo_documento", "titulo", "area_responsavel", "status", "versao", "elaborado_por", "updated_at"])
        for d in rows:
            w.writerow(
                [
                    d.codigo,
                    d.tipo_documento,
                    d.titulo,
                    d.area_responsavel,
                    d.status,
                    d.versao,
                    d.elaborado_por,
                    d.updated_at.isoformat(timespec="seconds") if d.updated_at else "",
                ]
            )
        return Response(
            content=buf.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="documentos_export.csv"'},
        )

    @router.get("/documentos/import-template.csv")
    async def documentos_import_template(request: Request):
        require_login(request)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["tipo_documento", "titulo", "area_responsavel", "elaborado_por", "classificacao"])
        w.writerow(["POP", "Exemplo de procedimento", "LOG", "Nome do responsavel", "Interno"])
        return Response(
            content=buf.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="documentos_import_modelo.csv"'},
        )

    @router.post("/api/documentos/import", response_class=JSONResponse)
    async def api_documentos_import(
        request: Request,
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        ensure_doc_setores_seed(session)
        raw = await file.read()
        if not raw or len(raw) > 2_000_000:
            return JSONResponse({"ok": False, "error": "Arquivo vazio ou muito grande (máx. ~2 MB)."}, status_code=400)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return JSONResponse({"ok": False, "error": "Use CSV em UTF-8."}, status_code=400)
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return JSONResponse({"ok": False, "error": "Cabeçalho ausente."}, status_code=400)
        colmap = {_normalize_csv_header(h): h for h in reader.fieldnames if h}
        required = ["tipo_documento", "titulo", "area_responsavel", "elaborado_por"]
        missing = [c for c in required if c not in colmap]
        if missing:
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"Colunas obrigatórias ausentes: {', '.join(missing)}. Use o modelo em /documentos/import-template.csv",
                },
                status_code=400,
            )
        setor_siglas = {str(s.sigla).strip().upper() for s in session.exec(select(models.DocSetor)).all()}
        created = 0
        errors: List[Dict[str, Any]] = []
        hoje = datetime.now().strftime("%Y-%m-%d")
        for idx, row in enumerate(reader, start=2):
            if not row or not any((v or "").strip() for v in row.values()):
                continue
            tipo = (row.get(colmap["tipo_documento"]) or "").strip().upper()[:3]
            titulo = (row.get(colmap["titulo"]) or "").strip()
            area = (row.get(colmap["area_responsavel"]) or "").strip().upper()
            elab = (row.get(colmap["elaborado_por"]) or "").strip()
            classif = "Interno"
            if "classificacao" in colmap:
                classif = (row.get(colmap["classificacao"]) or "Interno").strip() or "Interno"
            if tipo not in DOC_TIPOS:
                errors.append({"line": idx, "reason": f"Tipo inválido: {tipo!r} (use {', '.join(DOC_TIPOS)})"})
                continue
            if not titulo:
                errors.append({"line": idx, "reason": "Título vazio."})
                continue
            if not area or area not in setor_siglas:
                errors.append({"line": idx, "reason": f"Setor inválido ou desconhecido: {area!r}"})
                continue
            if not elab:
                errors.append({"line": idx, "reason": "Elaborado por vazio."})
                continue
            codigo = gerar_proximo_codigo(session, tipo, area)
            doc = models.DocInstitucional(
                tipo_documento=tipo,
                codigo=codigo,
                titulo=titulo[:255],
                area_responsavel=area,
                elaborado_por=elab[:100],
                classificacao=classif[:50],
                status="rascunho",
                data_emissao=hoje,
                versao=1,
                conteudo={},
            )
            session.add(doc)
            try:
                session.commit()
                session.refresh(doc)
                created += 1
            except IntegrityError:
                session.rollback()
                errors.append({"line": idx, "reason": "Conflito ao gravar (código duplicado?)."})
            except Exception as e:
                session.rollback()
                errors.append({"line": idx, "reason": str(e)[:200]})
        return JSONResponse(
            {
                "ok": True,
                "created": created,
                "errors": errors[:50],
                "error_count": len(errors),
                "message": f"{created} documento(s) criado(s) em rascunho." + (f" {len(errors)} linha(s) com erro." if errors else ""),
            }
        )

    return router
