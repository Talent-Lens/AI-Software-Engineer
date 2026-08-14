"""
Human-in-the-Loop Feedback Router (TASK-FS1 & TASK-FS6)
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import FeedbackRequest, FeedbackResponse
from src.retrieval.hard_negative_store import HardNegativeStore
from src.db.session import get_db
from src.db import crud

logger = logging.getLogger("ai_engineer.api.feedback")
router = APIRouter(tags=["Feedback & HITL"])


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    """
    Log user Accept/Reject feedback on retrieved code chunks into ChromaDB and Enterprise Relational DB.
    """
    try:
        # 1. Record into vector hard-negatives store
        store = HardNegativeStore()
        event = store.record_feedback(
            query=request.query,
            chunk_id=request.chunk_id,
            file_path=request.file_path,
            code_snippet=request.code_snippet,
            feedback_type=request.feedback_type,
            user_comment=request.user_comment,
        )

        # 2. Persist into Relational Database (PostgreSQL / SQLite)
        crud.create_user_feedback(
            db=db,
            query=request.query,
            chunk_id=request.chunk_id,
            file_path=request.file_path,
            code_snippet=request.code_snippet,
            feedback_type=event.feedback_type.value,
            user_comment=request.user_comment,
        )

        return FeedbackResponse(
            status="success",
            event_id=event.event_id,
            feedback_type=event.feedback_type.value,
            message=f"Recorded {event.feedback_type.value} feedback for chunk '{request.chunk_id}'.",
        )

    except Exception as err:
        logger.error("Failed to record feedback: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Feedback logging failed: {err}")
