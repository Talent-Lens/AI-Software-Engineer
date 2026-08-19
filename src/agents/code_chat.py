"""
Code Chat Agent — Interactive Context-Aware Q&A Agent for Code, Security Findings, and Diffs.
Supports multi-turn conversations, line referencing, and dynamic multi-model routing (Qwen-2.5 Coder 32B / Groq / Gemini / Ollama).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from src.schema import AgentResponse
from src.agents.model_router import route_and_execute

logger = logging.getLogger("ai_engineer.agents.code_chat")


def _extract_line_references(text: str) -> list[int]:
    """Extract unique line numbers referenced in markdown text (e.g., 'Line 28', 'line 12', '[Line 28]')."""
    lines_found = set()
    patterns = [
        r"(?:line|lines|Line|Lines|#)\s*(\d+)",
        r"\[(?:line\s+|Line\s+)?(\d+)\]",
        r"`(?:line\s+|Line\s+)?(\d+)`",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            try:
                line_num = int(match.group(1))
                if 1 <= line_num <= 10000:
                    lines_found.add(line_num)
            except ValueError:
                continue
    return sorted(list(lines_found))


def code_chat(
    question: str,
    filepath: str = "",
    file_code: str = "",
    proposed_fix: str = "",
    security_findings: list[dict[str, Any]] | None = None,
    history: list[dict[str, str]] | None = None,
    model: str = "qwen-2.5-coder-32b",
) -> dict[str, Any]:
    """
    Context-aware Code Chat handler.
    Passes genuine developer questions and full file/security context directly to the LLM.
    No hardcoded or templated fallbacks under any circumstance.
    """
    findings = security_findings or []
    hist = history or []

    # Format numbered code lines for context
    numbered_code = ""
    if file_code:
        lines = file_code.split("\n")
        numbered_code = "\n".join(f"{i+1:3d} | {line}" for i, line in enumerate(lines[:1000]))

    # Format findings summary
    findings_str = "None detected."
    if findings:
        findings_str = "\n".join(
            f"- [Line {f.get('line', '?')}] {f.get('title', f.get('rule', 'Issue'))} (Severity: {f.get('severity', 'UNKNOWN')})\n  Description: {f.get('description', '')}\n  Remediation: {f.get('remediation', '')}"
            for f in findings
        )

    # Format recent conversation history (excluding the current question if it was appended)
    history_str = ""
    if hist:
        # Exclude current question from prior history if present as last item
        clean_hist = [m for m in hist if not (m.get("role") == "user" and m.get("content") == question)]
        recent = clean_hist[-8:]  # Retain last 8 exchanges for multi-turn continuity
        if recent:
            history_str = "\n".join(f"{m.get('role', 'user').upper()}: {m.get('content', '')}" for m in recent)

    # Construct context payload
    context_parts = []
    if filepath:
        context_parts.append(f"CURRENT ACTIVE FILE: {filepath}")
    if numbered_code:
        context_parts.append(f"ORIGINAL FILE SOURCE CODE (WITH LINE NUMBERS):\n```\n{numbered_code}\n```")
    if proposed_fix:
        context_parts.append(f"PROPOSED VERIFIED PATCH / DIFF:\n```\n{proposed_fix[:4000]}\n```")
    if findings_str != "None detected.":
        context_parts.append(f"AST SECURITY & VULNERABILITY FINDINGS:\n{findings_str}")
    if history_str:
        context_parts.append(f"PRIOR CONVERSATION HISTORY:\n{history_str}")

    full_context = "\n\n".join(context_parts)

    system_prompt = (
        "You are CodeGuardian AI Expert Assistant, a senior software engineer and security auditor.\n"
        "You provide direct, precise, intelligent, and context-aware answers to the developer.\n"
        "Guidelines:\n"
        "1. For questions regarding the active file, diff, or AST security findings, provide deep technical analysis and cite line numbers in brackets (e.g. '[Line 28]') so the user can navigate to the exact line.\n"
        "2. If the user asks a general-purpose question (e.g. general programming concepts, algorithms, facts, trivia, or non-code questions), answer naturally and directly without forcing irrelevant file context.\n"
        "3. Maintain conversational continuity across multi-turn exchanges based on prior conversation history.\n"
        "4. NEVER output boilerplate, generic, or templated responses. Always generate a real, tailored answer directly addressing the user's specific prompt."
    )

    # Execute LLM call via model router
    router_res = route_and_execute(
        query=question,
        context=full_context,
        system_prompt=system_prompt,
        preferred_model=model,
    )

    answer_text = router_res.get("answer", "")
    if not answer_text or not answer_text.strip():
        raise RuntimeError("Empty response received from LLM.")

    model_used = router_res.get("model_used", model)
    provider_used = router_res.get("provider_used", "ollama")

    line_refs = _extract_line_references(answer_text)
    files_ref = [filepath] if filepath else []

    return {
        "answer": answer_text,
        "model_used": model_used,
        "provider_used": provider_used,
        "line_references": line_refs,
        "files_referenced": files_ref,
        "status": "completed",
    }


def code_chat_agent_node(state: dict[str, Any]) -> AgentResponse:
    """LangGraph node compatibility wrapper."""
    question = state.get("question", "")
    res = code_chat(question)
    return AgentResponse(
        agent_name="code_chat",
        summary=res.get("answer", ""),
        details={"line_references": res.get("line_references", []), "model": res.get("model_used", "")},
        confidence=0.95,
    )

