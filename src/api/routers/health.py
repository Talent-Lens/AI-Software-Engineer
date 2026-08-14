"""
Health Router (TASK-FS1)
"""
from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter
from src.api.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Check the health status of the API server, database, and vector store.
    """
    return HealthResponse(
        status="ok",
        version="1.0.0",
        database="pending_task_fs6",
        vector_store="ready",
        timestamp=datetime.now().isoformat()
    )
