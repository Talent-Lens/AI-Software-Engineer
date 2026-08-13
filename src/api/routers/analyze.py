"""
Analyze Pipeline Router (TASK-FS1)
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from src.api.schemas import AnalyzeRequest, AnalyzeResponse

logger = logging.getLogger("ai_engineer.api.analyze")
router = APIRouter(tags=["Analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_code(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Trigger full LangGraph analysis pipeline (Bug Detection -> Review -> Security Audit).
    """
    try:
        from graph import run_pipeline
        result = run_pipeline(request.filepath)
        return AnalyzeResponse(
            filepath=request.filepath,
            status="completed",
            agent_response=result.get("agent_response", {}),
            review=result.get("review", {}),
            security_response=result.get("security_response", {}),
            attempts=result.get("attempts", 1),
        )
    except Exception as err:
        logger.error("Error during analysis pipeline: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis pipeline failed: {err}")
