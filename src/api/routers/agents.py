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
)
from src.agents.security_auditor import audit_file
from src.agents.test_generation import analyze_and_generate
from src.agents.documentation_agent import generate_docs

logger = logging.getLogger("ai_engineer.api.agents")
router = APIRouter(tags=["Agents & Tools"])


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
