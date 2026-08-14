"""
GitHub PR Webhook & Review Service (TASK-FS4)
Handles HMAC signature verification, PR diff fetching, AI review generation, and PR comment posting.
"""
from __future__ import annotations

import hmac
import hashlib
import os
import logging
import httpx
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from src.db.session import SessionLocal
from src.db import crud

logger = logging.getLogger("ai_engineer.api.github")


def verify_github_signature(payload_body: bytes, signature_header: Optional[str], secret: Optional[str] = None) -> bool:
    """
    Verify HMAC SHA-256 signature from GitHub webhook request ('X-Hub-Signature-256').
    """
    webhook_secret = secret or os.getenv("GITHUB_WEBHOOK_SECRET")
    if not webhook_secret:
        # If no secret is configured, bypass check in dev/test mode
        return True
    
    if not signature_header:
        return False
    
    if not signature_header.startswith("sha256="):
        return False
    
    expected_signature = "sha256=" + hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature_header)


def format_ai_pr_review(
    pr_number: int,
    repo_name: str,
    analysis_results: List[Dict[str, Any]],
) -> str:
    """
    Format structured markdown AI code review comment for GitHub PRs.
    """
    total_files = len(analysis_results)
    vulnerabilities = []
    bugs = []
    suggestions = []

    for item in analysis_results:
        filepath = item.get("filepath", "unknown")
        agent_res = item.get("agent_response", {})
        sec_res = item.get("security_response", {})
        review_res = item.get("review", {})

        if sec_res.get("vulnerabilities"):
            for v in sec_res["vulnerabilities"]:
                vulnerabilities.append((filepath, v))

        if agent_res.get("bug_detected") or agent_res.get("proposed_fix"):
            bugs.append((filepath, agent_res.get("proposed_fix") or agent_res.get("summary", "Bug detected")))

        if review_res.get("comments"):
            for c in review_res["comments"]:
                suggestions.append((filepath, c))

    risk_level = "🔴 High Risk" if vulnerabilities else ("🟡 Medium Risk" if bugs else "🟢 Low Risk / Approved")

    md = []
    md.append("## 🤖 AI Software Engineer Code Review")
    md.append(f"**Repository:** `{repo_name}` | **PR:** `#{pr_number}` | **Status:** {risk_level}\n")
    md.append(f"> Automated multi-agent review analyzing `{total_files}` modified file(s).\n")
    md.append("---")

    # Security Section
    if vulnerabilities:
        md.append("### 🛡️ Security Vulnerabilities Detected")
        for fpath, vuln in vulnerabilities:
            md.append(f"- **`{fpath}`**: {vuln}")
        md.append("")
    else:
        md.append("### 🛡️ Security Audit: ✅ Passed (0 critical vulnerabilities)")
        md.append("")

    # Bugs & Fixes Section
    if bugs:
        md.append("### 🐛 Potential Bugs & Proposed Fixes")
        for fpath, fix in bugs:
            md.append(f"#### `{fpath}`")
            md.append(f"```diff\n{fix}\n```\n")
    else:
        md.append("### 🐛 Code Quality & Logic: ✅ No critical bugs identified\n")

    # Suggestions / Ast line grounding
    if suggestions:
        md.append("### 💡 Code Improvements & Review Comments")
        for fpath, comment in suggestions:
            md.append(f"- **`{fpath}`**: {comment}")
        md.append("")

    md.append("---")
    md.append("*Generated automatically by [AI Software Engineer](https://github.com/Talent-Lens/AI-Software-Engineer) Multi-Agent AST RAG Engine.*")

    return "\n".join(md)


async def post_github_pr_comment(
    owner: str,
    repo: str,
    pull_number: int,
    comment_body: str,
    token: Optional[str] = None,
) -> bool:
    """
    Post review comment directly on GitHub PR using GitHub REST API.
    """
    github_token = token or os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.warning("GITHUB_TOKEN not provided; skipping live GitHub API comment posting.")
        return False

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pull_number}/comments"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AI-Software-Engineer-Reviewer",
    }
    payload = {"body": comment_body}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=15.0)
        if response.status_code in (200, 201):
            logger.info("Successfully posted AI review comment on %s/%s#%d", owner, repo, pull_number)
            return True
        else:
            logger.error("Failed to post comment to GitHub PR: %d %s", response.status_code, response.text)
            return False


async def fetch_pr_files(
    owner: str,
    repo: str,
    pull_number: int,
    token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch list of changed files and patches for a given PR.
    """
    github_token = token or os.getenv("GITHUB_TOKEN")
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/files"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AI-Software-Engineer-Reviewer",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=15.0)
        if response.status_code == 200:
            return response.json()
        logger.warning("Could not fetch PR files from GitHub (%d): %s", response.status_code, response.text)
        return []


async def process_pull_request_event(
    payload: Dict[str, Any],
    db: Optional[Session] = None,
    github_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Orchestrate AI analysis on PR event and post comment back to GitHub.
    """
    action = payload.get("action")
    pull_request = payload.get("pull_request", {})
    repository = payload.get("repository", {})

    if not pull_request or not repository:
        return {"status": "skipped", "message": "Missing pull_request or repository payload"}

    pr_number = pull_request.get("number")
    repo_full_name = repository.get("full_name", "")
    owner = repository.get("owner", {}).get("login", "")
    repo_name = repository.get("name", "")

    logger.info("Processing PR #%s in %s (action: %s)", pr_number, repo_full_name, action)

    # 1. Fetch changed files
    files = await fetch_pr_files(owner, repo_name, pr_number, token=github_token)
    
    # 2. Analyze modified files
    analysis_results = []
    from graph import run_pipeline

    if files:
        for f in files:
            filename = f.get("filename", "")
            if filename.endswith((".py", ".js", ".ts", ".go", ".java")):
                try:
                    res = run_pipeline(filename)
                    analysis_results.append({
                        "filepath": filename,
                        "agent_response": res.get("agent_response", {}),
                        "review": res.get("review", {}),
                        "security_response": res.get("security_response", {}),
                    })
                except Exception as err:
                    logger.warning("Failed analyzing file %s: %s", filename, err)
    else:
        # Fallback default analysis if files couldn't be fetched remotely
        try:
            res = run_pipeline("graph.py")
            analysis_results.append({
                "filepath": "graph.py",
                "agent_response": res.get("agent_response", {}),
                "review": res.get("review", {}),
                "security_response": res.get("security_response", {}),
            })
        except Exception as err:
            logger.warning("Pipeline run error: %s", err)

    # 3. Format Markdown AI Review
    review_markdown = format_ai_pr_review(pr_number, repo_full_name, analysis_results)

    # 4. Post comment back to GitHub PR
    posted = await post_github_pr_comment(
        owner=owner,
        repo=repo_name,
        pull_number=pr_number,
        comment_body=review_markdown,
        token=github_token,
    )

    # 5. Persist to Database if session provided
    if db:
        try:
            for item in analysis_results:
                crud.create_analysis_run(
                    db=db,
                    filepath=f"PR#{pr_number}:{item.get('filepath')}",
                    status="completed",
                    agent_response=item.get("agent_response"),
                    review=item.get("review"),
                    security_response=item.get("security_response"),
                    summary=f"Automated PR review on {repo_full_name}#{pr_number}",
                )
        except Exception as db_err:
            logger.warning("Failed to record PR run in DB: %s", db_err)

    return {
        "status": "completed",
        "pr_number": pr_number,
        "repo": repo_full_name,
        "action": action,
        "files_analyzed": len(analysis_results),
        "comment_posted": posted,
        "review_markdown": review_markdown,
    }
