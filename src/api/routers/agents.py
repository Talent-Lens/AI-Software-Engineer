"""
Agents Router — SAST Security, Test Generation, & Docstring Generation (TASK-FS1)
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from src.api.schemas import (
    SecurityAuditRequest,
    SecurityAuditResponse,
    TestGenRequest,
    TestGenResponse,
    DocGenRequest,
    DocGenResponse,
    CodeChatRequest,
    CodeChatResponse,
)
from src.agents.security_auditor import audit_file
from src.agents.test_generation import analyze_and_generate
from src.agents.documentation_agent import generate_docs
from src.agents.code_chat import code_chat

logger = logging.getLogger("ai_engineer.api.agents")
router = APIRouter(tags=["Agents & Tools"])


@router.post("/chat/code", response_model=CodeChatResponse)
async def chat_with_code(request: CodeChatRequest) -> CodeChatResponse:
    """
    Interactive Q&A agent for code, security findings, and diffs using Qwen-2.5 Coder 32B.
    """
    try:
        history_dicts = [m.model_dump() for m in request.history] if request.history else []
        res = code_chat(
            question=request.question,
            filepath=request.filepath or "",
            file_code=request.file_code or "",
            proposed_fix=request.proposed_fix or "",
            security_findings=request.security_findings or [],
            history=history_dicts,
            model=request.model or "qwen-2.5-coder-32b",
        )
        return CodeChatResponse(
            answer=res.get("answer", ""),
            model_used=res.get("model_used", "qwen-2.5-coder-32b"),
            provider_used=res.get("provider_used", "codeguardian-engine"),
            line_references=res.get("line_references", []),
            files_referenced=res.get("files_referenced", []),
            status="completed",
        )
    except Exception as err:
        logger.error("Code chat failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Code chat failed: {err}")



@router.post("/security/audit", response_model=SecurityAuditResponse)
async def audit_security(request: SecurityAuditRequest) -> SecurityAuditResponse:
    """
    Run SAST Security & Vulnerability Auditor on a file against OWASP Top 10 risks.
    """
    try:
        res = audit_file(request.filepath)
        scorecard = res.get("details", {}).get("scorecard", {})
        return SecurityAuditResponse(
            filepath=request.filepath,
            status="completed",
            scorecard=scorecard,
            raw_response=res,
        )
    except Exception as err:
        logger.error("Security audit failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Security audit failed: {err}")


@router.post("/tests/generate", response_model=TestGenResponse)
async def generate_tests(request: TestGenRequest) -> TestGenResponse:
    """
    Generate pytest test cases for functions and run them in isolated subprocess sandbox.
    """
    try:
        res = analyze_and_generate(request.filepath)
        summary = res.get("summary", "")
        details = res.get("details", {})
        return TestGenResponse(
            filepath=request.filepath,
            status="completed",
            generated_test_code=summary,
            execution_result=details,
        )
    except Exception as err:
        logger.error("Test generation failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Test generation failed: {err}")


@router.post("/docstrings/generate", response_model=DocGenResponse)
async def generate_docstrings(request: DocGenRequest) -> DocGenResponse:
    """
    Generate Google-style/JSDoc docstrings for undocumented functions in a file.
    """
    try:
        res = generate_docs(request.filepath)
        summary = res.summary
        details = res.details
        return DocGenResponse(
            filepath=request.filepath,
            status="completed",
            updated_code=summary,
            verifier_report=details,
        )
    except Exception as err:
        logger.error("Docstring generation failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Docstring generation failed: {err}")


from typing import Any, Dict, Optional

@router.api_route("/security/launch-checklist", methods=["GET", "POST"])
async def run_launch_security_checklist(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Audit repository or code files against the 20 Essential Pre-Launch Production Readiness Checks.
    """
    try:
        from src.agents.launch_checklist import LAUNCH_SECURITY_AUDITOR, PreLaunchSecurityAuditor

        req_payload = payload or {}
        repo_path = req_payload.get("repo_path")
        files_dict = req_payload.get("files")

        auditor = PreLaunchSecurityAuditor(repo_path=repo_path) if repo_path else LAUNCH_SECURITY_AUDITOR
        report = auditor.audit(file_contents=files_dict)
        return report.to_dict()
    except Exception as err:
        logger.error("Launch security checklist failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Launch security checklist failed: {err}")
