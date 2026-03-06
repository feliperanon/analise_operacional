# -*- coding: utf-8 -*-
"""Rotas de administração para geocodificação de clientes."""

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

import models
from database import get_session, engine
from services.geocoding_service import geocoding_service
from datetime import datetime

logger = logging.getLogger(__name__)


def _geocode_and_update(client: models.Client, session: Session) -> dict:
    """Geocodifica um cliente e atualiza o banco. Retorna dict com resultado."""
    result = geocoding_service.geocode_cliente(client)
    now = datetime.now()

    if result.success:
        client.latitude = result.latitude
        client.longitude = result.longitude
        client.geocoding_status = "success"
        client.geocoded_at = now
        client.geocoding_source = result.source
        client.geocoding_error = None
        if result.display_name:
            client.address_normalized = result.display_name[:500]
    else:
        client.geocoding_status = "failed"
        client.geocoded_at = now
        client.geocoding_error = (result.error or "Erro desconhecido")[:500]

    session.add(client)
    session.commit()
    return {"client_id": client.id, "success": result.success, "error": result.error}


def _run_geocode_batch(client_ids: list, limit: int) -> dict:
    """Executa geocodificação em lote em background (sem session compartilhada)."""
    processed = 0
    success = 0
    failed = 0
    errors = []

    with Session(engine) as session:
        for cid in client_ids[:limit]:
            client = session.get(models.Client, cid)
            if not client:
                continue
            try:
                res = _geocode_and_update(client, session)
                processed += 1
                if res["success"]:
                    success += 1
                else:
                    failed += 1
                    if res["error"]:
                        errors.append(f"ID {cid}: {res['error']}")
            except Exception as e:
                failed += 1
                errors.append(f"ID {cid}: {str(e)}")
                logger.error("Erro geocodificando cliente %s: %s", cid, e)

    logger.info(
        "Geocodificação em lote concluída: %d processados, %d sucesso, %d falhas",
        processed, success, failed,
    )
    return {"processed": processed, "success": success, "failed": failed, "errors": errors[:10]}


def init_admin_geocoding_router(
    *,
    require_leader: Callable[[Request], Any],
) -> APIRouter:
    """Cria o router de geocodificação administrativa."""
    router = APIRouter(prefix="/admin/geocoding", tags=["admin-geocoding"])

    @router.post("/processar-pendentes", response_class=JSONResponse)
    async def processar_pendentes(
        background_tasks: BackgroundTasks,
        limit: int = 50,
        session: Session = Depends(get_session),
        _user=Depends(require_leader),
    ):
        """Processa geocodificação de clientes com status 'pending' em background."""
        pendentes = session.exec(
            select(models.Client)
            .where(
                (models.Client.geocoding_status == "pending")
                | models.Client.geocoding_status.is_(None)
            )
            .limit(limit)
        ).all()

        client_ids = [c.id for c in pendentes if c.id is not None]
        if not client_ids:
            return JSONResponse({"message": "Nenhum cliente pendente encontrado", "queued": 0})

        background_tasks.add_task(_run_geocode_batch, client_ids, limit)
        return JSONResponse(
            {"message": f"{len(client_ids)} cliente(s) enviado(s) para geocodificação", "queued": len(client_ids)}
        )

    @router.post("/reprocessar-falhas", response_class=JSONResponse)
    async def reprocessar_falhas(
        background_tasks: BackgroundTasks,
        limit: int = 50,
        session: Session = Depends(get_session),
        _user=Depends(require_leader),
    ):
        """Reprocessa clientes com geocodificação com falha."""
        falhas = session.exec(
            select(models.Client)
            .where(models.Client.geocoding_status == "failed")
            .limit(limit)
        ).all()

        client_ids = [c.id for c in falhas if c.id is not None]
        if not client_ids:
            return JSONResponse({"message": "Nenhum cliente com falha encontrado", "queued": 0})

        # Marca como pending antes de reprocessar
        for c in falhas:
            c.geocoding_status = "pending"
            session.add(c)
        session.commit()

        background_tasks.add_task(_run_geocode_batch, client_ids, limit)
        return JSONResponse(
            {"message": f"{len(client_ids)} cliente(s) marcado(s) para reprocessamento", "queued": len(client_ids)}
        )

    @router.get("/status", response_class=JSONResponse)
    async def geocoding_status(
        session: Session = Depends(get_session),
        _user=Depends(require_leader),
    ):
        """Retorna estatísticas de geocodificação dos clientes."""
        all_clients = session.exec(select(models.Client)).all()
        total = len(all_clients)
        status_counts: dict = {}
        for c in all_clients:
            st = c.geocoding_status or "pending"
            status_counts[st] = status_counts.get(st, 0) + 1

        com_coords = sum(1 for c in all_clients if c.has_valid_coordinates())
        return JSONResponse(
            {
                "total": total,
                "com_coordenadas": com_coords,
                "sem_coordenadas": total - com_coords,
                "por_status": status_counts,
            }
        )

    return router
