"""
Analyze Pipeline Router (TASK-FS1 & TASK-FS6)
"""
from __future__ import annotations

import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import AnalyzeRequest, AnalyzeResponse
from src.db.session import get_db
from src.db import crud

logger = logging.getLogger("ai_engineer.api.analyze")
router = APIRouter(tags=["Analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_code(
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
) -> AnalyzeResponse:
    """
    Trigger full LangGraph analysis pipeline (Bug Detection -> Review -> Security Audit)
    and persist results to enterprise database.
    """
    start_time = time.perf_counter()
    try:
        from graph import run_pipeline
        result = run_pipeline(request.filepath)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        agent_response = result.get("agent_response", {})
        review = result.get("review", {})
        security_response = result.get("security_response", {})
        attempts = result.get("attempts", 1)

        # Check vulnerability indicators
        has_vulnerabilities = bool(
            security_response.get("vulnerabilities")
            or "vulnerab" in str(security_response).lower()
        )
        has_bugs = bool(agent_response.get("bug_detected") or "bug" in str(agent_response).lower())
        patch_diff = agent_response.get("proposed_fix") or agent_response.get("diff")

        # Persist run to database
        try:
            crud.create_analysis_run(
                db=db,
                filepath=request.filepath,
                status="completed",
                attempts=attempts,
                duration_ms=duration_ms,
                has_vulnerabilities=has_vulnerabilities,
                has_bugs=has_bugs,
                agent_response=agent_response,
                review=review,
                security_response=security_response,
                patch_diff=str(patch_diff) if patch_diff else None,
                summary=agent_response.get("summary") or review.get("summary"),
            )
        except Exception as db_err:
            logger.warning("Failed to persist analysis run to database: %s", db_err)

        return AnalyzeResponse(
            filepath=request.filepath,
            status="completed",
            agent_response=agent_response,
            review=review,
            security_response=security_response,
            attempts=attempts,
        )
    except Exception as err:
        logger.error("Error during analysis pipeline: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis pipeline failed: {err}")
