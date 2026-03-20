# -*- coding: utf-8 -*-
"""Rotas do módulo Documentos Institucionais (Processos e Padronização)."""
import html
import json
from datetime import datetime
from typing import Optional, List, Any, Callable
from fastapi import Request, Depends, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    """Converte corpo do relatório em HTML formatado: seções numeradas, listas, parágrafos."""
    if not corpo or not corpo.strip():
        return ""
    import re
    lines = corpo.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<p class='doc-p-space'></p>")
            continue
        # Seção numerada: "1. TÍTULO" ou "1. Título"
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m and len(m.group(2)) < 100:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3 class='doc-section-title'>{html.escape(stripped)}</h3>")
            continue
        # Item de lista: "- item"
        if stripped.startswith("- "):
            if not in_list:
                out.append("<ul class='doc-list'>")
                in_list = True
            out.append(f"<li>{html.escape(stripped[2:])}</li>")
            continue
        # Parágrafo normal
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p class='doc-p'>{html.escape(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


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

    @router.get("/documentos", response_class=HTMLResponse)
    async def documentos_page(
        request: Request,
        tipo: Optional[str] = Query(None),
        setor: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        acao: Optional[str] = Query(None),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        setores = list(session.exec(select(models.DocSetor).where(models.DocSetor.ativo == True)).all())
        stmt = select(models.DocInstitucional).order_by(models.DocInstitucional.updated_at.desc())
        if tipo:
            stmt = stmt.where(models.DocInstitucional.tipo_documento == tipo.upper())
        if setor:
            stmt = stmt.where(models.DocInstitucional.area_responsavel == setor.upper())
        if status:
            stmt = stmt.where(models.DocInstitucional.status == status)
        if q and q.strip():
            qs = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    models.DocInstitucional.titulo.ilike(qs),
                    models.DocInstitucional.codigo.ilike(qs),
                )
            )
        documentos = list(session.exec(stmt.limit(200)).all())
        return templates.TemplateResponse(
            "documentos_institucionais.html",
            {
                "request": request,
                "documentos": documentos,
                "setores": setores,
                "filtros": {"tipo": tipo, "setor": setor, "status": status, "q": q or "", "acao": acao},
                "doc_tipos": DOC_TIPOS,
                "doc_status": DOC_STATUS,
            },
        )

    @router.get("/documentos/novo", response_class=HTMLResponse)
    async def documento_novo_page(
        request: Request,
        tipo: Optional[str] = Query(None),
        session: Session = Depends(get_session),
    ):
        require_login(request)
        setores = list(session.exec(select(models.DocSetor).where(models.DocSetor.ativo == True)).all())
        return templates.TemplateResponse(
            "documento_form.html",
            {
                "request": request,
                "documento": None,
                "setores": setores,
                "doc_tipos": DOC_TIPOS,
                "tipo_predefinido": (tipo or "").upper() if tipo else None,
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

    return router
