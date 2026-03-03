# -*- coding: utf-8 -*-
"""
Rotas e lógica de inicialização do módulo Devoluções.
"""
from datetime import datetime
from typing import Optional, List, Any
from fastapi import Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from database import get_session, engine
import models
from devolucoes_service import (
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
