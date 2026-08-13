"""
Human-in-the-Loop Feedback Router (TASK-FS1)
"""
from __future__ import annotations

import uuid
import logging
from fastapi import APIRouter, HTTPException
from src.api.schemas import FeedbackRequest, FeedbackResponse
from src.retrieval.hard_negative_store import (
    HardNegativeStore,
    FeedbackEvent,
    FeedbackType,
)

logger = logging.getLogger("ai_engineer.api.feedback")
router = APIRouter(tags=["Feedback & HITL"])


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Log user Accept/Reject feedback on retrieved code chunks into ChromaDB hard-negatives store.
    """
    try:
        store = HardNegativeStore()
        event = store.record_feedback(
            query=request.query,
            chunk_id=request.chunk_id,
            file_path=request.file_path,
            code_snippet=request.code_snippet,
            feedback_type=request.feedback_type,
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
