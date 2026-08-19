"""
GitHub Webhook & PR Reviewer Router (TASK-FS4)
"""
from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, Header, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.api.services.github_service import (
    verify_github_signature,
    process_pull_request_event,
    format_ai_pr_review,
    post_github_pr_comment,
    fetch_pr_files,
)

logger = logging.getLogger("ai_engineer.api.github_router")
router = APIRouter(tags=["GitHub CI/CD & Webhooks"])


class ManualPRReviewRequest(BaseModel):
    owner: str = Field(..., description="Repository owner or org name (e.g., 'Talent-Lens')")
    repo: str = Field(..., description="Repository name (e.g., 'AI-Software-Engineer')")
    pull_number: int = Field(..., description="Pull Request number")
    token: Optional[str] = Field(None, description="Optional GitHub token override")


@router.get("/github/status")
async def github_integration_status() -> Dict[str, Any]:
    """
    Check the status and configuration of the GitHub Webhook and Token integration.
    """
    has_token = bool(os.getenv("GITHUB_TOKEN"))
    has_webhook_secret = bool(os.getenv("GITHUB_WEBHOOK_SECRET"))
    
    return {
        "status": "ready",
        "github_token_configured": has_token,
        "webhook_secret_configured": has_webhook_secret,
        "supported_events": ["pull_request", "ping"],
    }


@router.post("/github/webhook")
async def github_webhook_listener(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Receive and process incoming GitHub Webhook events.
    Verifies HMAC SHA-256 signature and triggers AI PR review for pull_request events.
    """
    body_bytes = await request.body()

    # 1. Verify HMAC Signature
    if not verify_github_signature(body_bytes, x_hub_signature_256):
        logger.warning("Invalid GitHub webhook HMAC signature received.")
        raise HTTPException(status_code=401, detail="Invalid HMAC signature (X-Hub-Signature-256)")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {err}")

    # 2. Handle Ping event
    if x_github_event == "ping":
        zen = payload.get("zen", "GitHub ping received")
        return {"status": "success", "event": "ping", "message": zen}

    # 3. Handle Pull Request events
    if x_github_event == "pull_request":
        action = payload.get("action", "")
        if action in ("opened", "synchronize", "reopened"):
            # Process synchronously or queue
            result = await process_pull_request_event(payload, db=db)
            return result
        else:
            return {"status": "ignored", "action": action, "message": f"Action '{action}' does not require AI review."}

    return {"status": "ignored", "event": x_github_event, "message": "Event ignored."}


@router.post("/github/review-pr")
async def manual_pr_review(
    request: ManualPRReviewRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Manually trigger AI Review on any GitHub Pull Request.
    """
    try:
        mock_payload = {
            "action": "manual_review",
            "pull_request": {"number": request.pull_number},
            "repository": {
                "name": request.repo,
                "full_name": f"{request.owner}/{request.repo}",
                "owner": {"login": request.owner},
            },
        }
        result = await process_pull_request_event(mock_payload, db=db, github_token=request.token)
        return result
    except Exception as err:
        logger.error("Failed to manually review PR: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


class AnalyzeRepoRequest(BaseModel):
    repo_url: str = Field(..., description="GitHub repository URL (e.g. https://github.com/owner/repository)")
    token: Optional[str] = Field(None, description="Optional GitHub Personal Access Token")
    max_files: Optional[int] = Field(10, description="Max files to analyze")


@router.post("/github/analyze-repo")
async def analyze_github_repository_endpoint(
    request: AnalyzeRepoRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Clones/fetches and analyzes a public or private GitHub repository,
    performing AST bug detection and SAST security auditing on all code files.
    """
    from src.api.services.github_service import fetch_and_analyze_repository
    
    if not request.repo_url or not request.repo_url.strip():
        raise HTTPException(status_code=400, detail="Repository URL is required.")

    try:
        result = await fetch_and_analyze_repository(
            repo_url=request.repo_url.strip(),
            token=request.token,
            max_files=request.max_files or 10,
            db=db,
        )
        return result
    except ValueError as err:
        error_msg = str(err)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        elif "rate limit" in error_msg.lower() or "access denied" in error_msg.lower():
            raise HTTPException(status_code=403, detail=error_msg)
        elif "no supported source code files" in error_msg.lower():
            raise HTTPException(status_code=422, detail=error_msg)
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as err:
        logger.error("Unexpected error in analyze_github_repository: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to analyze repository: {err}")

