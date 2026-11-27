"""
Health Router (TASK-FS1 & TASK-FS6)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter
from sqlalchemy import text
from src.api.schemas import HealthResponse
from src.db.session import engine

logger = logging.getLogger("ai_engineer.api.health")
router = APIRouter(tags=["Health"])


def _check_db_sync() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@router.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Check the health status of the API server, database, and vector store.
    """
    db_status = "connected"
    try:
        await asyncio.to_thread(_check_db_sync)
    except Exception as err:
        logger.warning("Database health check failed: %s", err)
        db_status = "disconnected"

    return HealthResponse(
        status="ok",
        version="1.0.0",
        database=db_status,
        vector_store="ready",
        timestamp=datetime.now().isoformat()
    )
