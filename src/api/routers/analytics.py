"""
Enterprise Analytics & Persistence Router (TASK-FS6)
Provides REST endpoints for querying dashboard metrics, analysis histories, eval trends, and audit trails.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db import crud

logger = logging.getLogger("ai_engineer.api.analytics")
router = APIRouter(tags=["Analytics & Persistence"])


@router.get("/analytics/overview")
async def get_dashboard_overview(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get aggregated analytics metrics (total repos, analysis runs, vulnerabilities, feedback acceptance rate).
    """
    try:
        return crud.get_analytics_overview(db)
    except Exception as err:
        logger.error("Failed to fetch analytics overview: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/analytics/analysis-runs")
async def get_analysis_runs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    has_vulnerabilities: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Query historical agent analysis pipeline runs.
    """
    try:
        runs = crud.list_analysis_runs(
            db, skip=skip, limit=limit, status=status, has_vulnerabilities=has_vulnerabilities
        )
        return [r.to_dict() for r in runs]
    except Exception as err:
        logger.error("Failed to query analysis runs: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/analytics/analysis-runs/{run_id}")
async def get_analysis_run_by_id(run_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Fetch a single analysis run by ID.
    """
    run = crud.get_analysis_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Analysis run '{run_id}' not found")
    return run.to_dict()


@router.get("/analytics/eval-history")
async def get_evaluation_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Query historical RAG Triad benchmark evaluation experiments.
    """
    try:
        experiments = crud.list_eval_experiments(db, skip=skip, limit=limit)
        return [e.to_dict() for e in experiments]
    except Exception as err:
        logger.error("Failed to query eval history: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/analytics/feedback")
async def get_feedback_records(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    feedback_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Query human-in-the-loop feedback entries.
    """
    try:
        records = crud.list_user_feedback(db, skip=skip, limit=limit, feedback_type=feedback_type)
        return [r.to_dict() for r in records]
    except Exception as err:
        logger.error("Failed to query feedback: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/analytics/audit-logs")
async def get_audit_trail(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Query system audit log trail.
    """
    try:
        logs = crud.list_audit_logs(db, skip=skip, limit=limit)
        return [log.to_dict() for log in logs]
    except Exception as err:
        logger.error("Failed to query audit logs: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/analytics/repositories")
async def get_repositories_list(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Query indexed repositories metadata.
    """
    try:
        repos = crud.list_repositories(db, skip=skip, limit=limit)
        return [repo.to_dict() for repo in repos]
    except Exception as err:
        logger.error("Failed to list repositories: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))
