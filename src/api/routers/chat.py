"""
Chat Router — Context-Aware Code Q&A with LLM (TASK-FS1 / Restore Chat)
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from src.api.schemas import CodeChatRequest, CodeChatResponse
from src.agents.code_chat import code_chat

logger = logging.getLogger("ai_engineer.api.chat")
router = APIRouter(prefix="/chat", tags=["Code Chat & Q&A"])


@router.post("", response_model=CodeChatResponse)
@router.post("/code", response_model=CodeChatResponse)
async def ask_code_question(request: CodeChatRequest) -> CodeChatResponse:
    """
    Ask natural language questions about active source code, diffs, and security findings.
    Powered by Qwen-2.5 Coder 32B with automatic AST grounding & line reference extraction.
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
        logger.error("Chat endpoint error: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {err}")
