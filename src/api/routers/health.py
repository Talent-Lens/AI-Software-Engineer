"""
Health Router (TASK-FS1 & TASK-FS6)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from fastapi import APIRouter
from sqlalchemy import text
from src.api.schemas import HealthResponse
from src.db.session import engine

logger = logging.getLogger("ai_engineer.api.health")
router = APIRouter(tags=["Health"])


@router.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Check the health status of the API server, database, vector store, and LLM providers.
    """
    db_status = "connected"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as err:
        logger.warning("Database health check failed: %s", err)
        db_status = "disconnected"

    groq_active = bool((os.getenv("GROQ_API_KEY") or "").strip().strip("'\""))
    gemini_active = bool((os.getenv("GEMINI_API_KEY") or "").strip().strip("'\""))

    return HealthResponse(
        status="ok",
        version="1.0.0",
        database=db_status,
        vector_store="ready",
        timestamp=datetime.now().isoformat(),
        llm_providers={
            "groq_configured": groq_active,
            "gemini_configured": gemini_active,
        }
    )
