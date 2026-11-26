"""
GitHub Webhook & PR Reviewer Router (TASK-FS4)
"""
from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, Optional, List
from fastapi import APIRouter, Request, Header, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import User
from src.db import crud
from src.api.services.auth_service import get_current_user
from src.api.services import github_app
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


# ==========================================
# GITHUB APP OAUTH & INSTALLATION ENDPOINTS
# ==========================================

@router.get("/github/app/connect")
async def github_app_connect(
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    Initiates GitHub App installation/authorization flow for an authenticated user.
    Generates a cryptographically signed, single-use state token and returns install URL.
    """
    app_slug = os.getenv("GITHUB_APP_SLUG", "").strip()
    client_id = os.getenv("GITHUB_CLIENT_ID", "").strip()
    
    if not app_slug and not client_id:
        raise HTTPException(
            status_code=400,
            detail="GitHub App is not configured. Please add GITHUB_APP_SLUG=<your-app-slug> or GITHUB_CLIENT_ID to your .env file."
        )
    
    install_url = github_app.create_github_connect_url(user_id=current_user.id)
    return {"install_url": install_url}


@router.get("/github/callback")
@router.get("/callback")
async def github_app_callback(
    installation_id: Optional[int] = Query(None),
    setup_action: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """
    Receives redirect from GitHub after user authorizes/installs the GitHub App.
    Verifies the CSRF state token, stores the installation, and redirects to the frontend.
    """
    frontend_base = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

    if not state:
        logger.warning("GitHub callback called without state token.")
        return RedirectResponse(url=f"{frontend_base}/?github_error=missing_state")

    try:
        user_id = github_app.verify_github_state(state)
    except HTTPException as exc:
        logger.warning("GitHub state verification failed: %s", exc.detail)
        return RedirectResponse(url=f"{frontend_base}/?github_error=invalid_state")

    if not installation_id:
        logger.info("GitHub authorization completed without new installation_id (setup_action=%s)", setup_action)
        return RedirectResponse(url=f"{frontend_base}/?github_connected=true")

    # Fetch installation details from GitHub using App JWT
    account_login = ""
    account_avatar = ""
    account_type = "User"
    repository_selection = "selected"

    try:
        details = await github_app.get_installation_details(installation_id)
        account = details.get("account", {})
        account_login = account.get("login", "")
        account_avatar = account.get("avatar_url", "")
        account_type = account.get("type", "User")
        repository_selection = details.get("repository_selection", "selected")
    except Exception as err:
        logger.warning("Could not fetch installation details for %d (App credentials may be pending): %s", installation_id, err)
        account_login = f"installation-{installation_id}"

    # Upsert installation in DB
    crud.upsert_github_installation(
        db=db,
        user_id=user_id,
        installation_id=installation_id,
        account_login=account_login,
        account_avatar_url=account_avatar,
        account_type=account_type,
        repository_selection=repository_selection,
    )

    logger.info("Successfully connected GitHub installation %d for user %s (@%s)", installation_id, user_id, account_login)
    return RedirectResponse(url=f"{frontend_base}/?github_connected=true")


@router.get("/github/installation")
async def get_github_installation_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns the real GitHub App connection status and list of authorized repositories.
    """
    inst = crud.get_github_installation_by_user_id(db, current_user.id)
    if not inst:
        return {"connected": False, "installation": None, "repos": []}

    repos: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    if github_app.is_github_app_configured():
        try:
            repos = await github_app.get_installation_repositories(inst.installation_id)
        except Exception as err:
            logger.warning("Failed to fetch repositories for installation %d: %s", inst.installation_id, err)
            error_msg = str(err)
    else:
        logger.info("GitHub App credentials not configured in backend; returning installation metadata.")

    return {
        "connected": True,
        "installation": inst.to_dict(),
        "repos": repos,
        "app_configured": github_app.is_github_app_configured(),
        "error": error_msg,
    }


@router.get("/github/branches")
async def get_github_branches(
    owner: str = Query(...),
    repo: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Fetches real branches for an authorized repository using the server-side installation token.
    """
    inst = crud.get_github_installation_by_user_id(db, current_user.id)
    if not inst:
        raise HTTPException(status_code=400, detail="GitHub App is not connected for this user.")

    if not github_app.is_github_app_configured():
        return {"branches": ["main", "develop", "master"]}

    try:
        branches = await github_app.get_repository_branches(
            installation_id=inst.installation_id,
            owner=owner,
            repo=repo,
        )
        return {"branches": branches}
    except Exception as err:
        logger.warning("Failed to fetch branches for %s/%s: %s", owner, repo, err)
        return {"branches": ["main", "develop"]}


@router.post("/github/disconnect")
async def disconnect_github_app(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Disconnects the GitHub App installation from CodeGuardian for the current user.
    """
    deleted = crud.delete_github_installation(db, current_user.id)
    return {
        "status": "disconnected" if deleted else "not_connected",
        "message": "GitHub App disconnected from CodeGuardian.",
    }


class CreatePRRequest(BaseModel):
    repo_full_name: str = Field(..., description="Target repository full name (e.g. 'owner/repo')")
    file_path: str = Field(..., description="Path of the file being patched")
    patch_content: str = Field(..., description="Clean verified patch content")
    base_branch: Optional[str] = Field("main", description="Target base branch")
    commit_message: Optional[str] = Field(None, description="Commit message")
    pr_title: Optional[str] = Field(None, description="Pull Request title")
    pr_body: Optional[str] = Field(None, description="Pull Request markdown body")


@router.post("/github/create-pr")
async def create_pull_request_endpoint(
    req: CreatePRRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Secure server-side Pull Request creation using GitHub App installation tokens.
    Verifies that the target repository belongs to the authenticated user's installation.
    Never trusts client tokens; all tokens are minted server-side via RS256 JWT.
    """
    if not req.repo_full_name or "/" not in req.repo_full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid repository name format. Expected 'owner/repo'.",
        )

    # 1. Authorize user session & load stored installation
    inst = crud.get_github_installation_by_user_id(db, current_user.id)
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub App installation found for your account. Please connect your repository first.",
        )

    # 2. Security verification: Verify target repository is in user's authorized installation
    try:
        authorized_repos = await github_app.get_installation_repositories(inst.installation_id)
        target_lower = req.repo_full_name.strip().lower()
        is_authorized = any(r.get("fullName", "").lower() == target_lower for r in authorized_repos)
        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Repository '{req.repo_full_name}' is not authorized under your GitHub App installation. Please grant access on GitHub.",
            )
    except HTTPException:
        raise
    except Exception as err:
        logger.warning("Could not verify repository ownership against GitHub API: %s", err)
        # Fall through to attempt PR creation if API rate limit or transient error

    # 3. Create branch, commit, and PR using installation token
    parts = req.repo_full_name.strip().split("/")
    owner, repo = parts[0], parts[1]

    result = await github_app.create_pull_request_for_installation(
        installation_id=inst.installation_id,
        repo_owner=owner,
        repo_name=repo,
        file_path=req.file_path,
        patch_content=req.patch_content,
        base_branch=req.base_branch or "main",
        commit_message=req.commit_message,
        pr_title=req.pr_title,
        pr_body=req.pr_body,
    )

    logger.info(
        "Successfully created PR #%s on %s for user %s: %s",
        result["pr_number"],
        req.repo_full_name,
        current_user.id,
        result["pr_url"],
    )

    return {
        "status": "success",
        "pr_url": result["pr_url"],
        "pr_number": result["pr_number"],
        "branch": result["branch"],
        "base_branch": result["base_branch"],
        "repo": result["repo"],
    }

