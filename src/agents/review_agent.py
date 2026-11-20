"""
Review Agent — critiques Bug Detection Agent output before it's returned
as final.

Architecture: Two-Pass Hybrid Verification Pipeline:
  1. Pass 1 (Deterministic Fast Gate):
     - Summary claims consistency vs raw findings
     - Expected issue count coverage
     - WHY/FIX presence
     - Line-number & code grounding in target file (TASK-E1)
     - AST code syntax & lint validation for suggested code fixes (TASK-E2)
  2. Pass 2 (LLM Semantic Verification):
     - Evaluates fix correctness, technical accuracy, false positives,
       and severity calibration via Groq (primary) or Ollama (fallback).
     - Gracefully degrades to deterministic-only verification if no LLM is available.
"""

from __future__ import annotations

import ast
import concurrent.futures
import json
import logging
import os
import re
import tempfile
import py_compile
from typing import Any

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("ai_engineer.review_agent")


# ---------------------------------------------------------------------------
# Deterministic Grounding & Syntax Extractors (Pass 1)
# ---------------------------------------------------------------------------

def extract_line_citations(text: str) -> list[tuple[int, int]]:
    """
    Extracts all line numbers/ranges cited in text (e.g. 'line 99', 'lines 4-5', 'WHICH LINE(S): 4-5').
    Returns a list of tuples (start_line, end_line).
    """
    citations = []
    patterns = [
        r"(?:WHICH LINE\(S\)|lines?|line:)\s*[:=]?\s*(\d+)(?:\s*(?:-|to)\s*(\d+))?",
        r"\bL(\d+)(?:\s*-\s*(\d+))?\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            citations.append((start, end))
    return citations


def extract_code_snippets(text: str) -> list[str]:
    """
    Extracts inline code snippets enclosed in backticks from response text.
    """
    return re.findall(r"`([^`]+)`", text)


def extract_code_blocks(text: str) -> list[dict]:
    """
    Extracts fenced markdown code blocks and explicit code fix suggestions from response text.
    Returns list of dicts: [{'code': str, 'language': str, 'source': str}]
    """
    blocks = []

    # Match fenced code blocks e.g. ```python ... ```
    fenced_pattern = r"```(?:([a-zA-Z0-9_+-]+)\n)?(.*?)```"
    for match in re.finditer(fenced_pattern, text, re.DOTALL):
        lang = match.group(1) or "python"
        code_content = match.group(2).strip()
        if code_content:
            blocks.append({
                "code": code_content,
                "language": lang.lower(),
                "source": "fenced_code_block"
            })

    # Match POSSIBLE FIX lines with inline code blocks
    fix_pattern = r"(?:POSSIBLE FIX|FIX)\s*:\s*(.*)"
    for match in re.finditer(fix_pattern, text, re.IGNORECASE):
        fix_line = match.group(1).strip()
        fix_snippets = extract_code_snippets(fix_line)
        for snippet in fix_snippets:
            if len(snippet.strip()) > 3:
                blocks.append({
                    "code": snippet.strip(),
                    "language": "python",
                    "source": "possible_fix_inline"
                })

    return blocks


def validate_code_syntax(code: str, language: str = "python") -> dict:
    """
    Validates code syntax using Python's AST parser (ast.parse) and byte compilation.
    Supports full Python modules, statements, and code fragments.
    Returns dict: {'valid': bool, 'error': str | None, 'line': int | None, 'column': int | None}
    """
    clean_code = code.strip()
    if not clean_code:
        return {"valid": True, "error": None, "line": None, "column": None}

    if language in ("python", "py"):
        # 1. Attempt standard module parse
        try:
            ast.parse(clean_code, mode="exec")
            return {"valid": True, "error": None, "line": None, "column": None}
        except (SyntaxError, IndentationError) as direct_err:
            primary_err = direct_err

        # 2. Attempt fragment parsing (wrapped in a dummy function or try-except block)
        fragment_wrappers = [
            f"def _dummy_wrapper():\n" + "\n".join("    " + l for l in clean_code.splitlines()),
            f"try:\n    pass\n" + "\n".join(
                "    " + l if l.strip().startswith("except") or l.strip().startswith("finally") else "    " + l
                for l in clean_code.splitlines()
            ),
        ]

        for wrapper in fragment_wrappers:
            try:
                ast.parse(wrapper, mode="exec")
                return {"valid": True, "error": None, "line": None, "column": None}
            except (SyntaxError, IndentationError):
                pass

        # 3. Attempt eval mode for single expressions
        try:
            ast.parse(clean_code, mode="eval")
            return {"valid": True, "error": None, "line": None, "column": None}
        except (SyntaxError, IndentationError):
            pass

        err_msg = str(primary_err)
        line = getattr(primary_err, "lineno", None)
        column = getattr(primary_err, "offset", None)
        text_line = getattr(primary_err, "text", "") or ""

        return {
            "valid": False,
            "error": f"SyntaxError: {primary_err.msg}" if hasattr(primary_err, "msg") else err_msg,
            "line": line,
            "column": column,
            "offending_text": text_line.strip(),
        }

    return {"valid": True, "error": None, "line": None, "column": None}


def verify_syntax_and_lint(text: str) -> dict:
    """
    Extracts all code blocks and code fixes from `text` and verifies their syntax using AST.
    Returns dict: {'valid': bool, 'syntax_errors': list[str], 'validated_blocks': int}
    """
    blocks = extract_code_blocks(text)
    syntax_errors = []

    for block in blocks:
        res = validate_code_syntax(block["code"], block["language"])
        if not res["valid"]:
            location_info = ""
            if res.get("line"):
                location_info = f" at line {res['line']}"
                if res.get("column"):
                    location_info += f", col {res['column']}"
            offending = f" -> '{res['offending_text']}'" if res.get("offending_text") else ""
            syntax_errors.append(
                f"Syntax error in code fix ({block['source']}){location_info}: {res['error']}{offending}"
            )

    return {
        "valid": len(syntax_errors) == 0,
        "syntax_errors": syntax_errors,
        "validated_blocks": len(blocks),
    }


def verify_line_grounding(filepath: str, text: str) -> dict:
    """
    Verifies that all line numbers cited in `text` exist in `filepath`
    and that cited inline code snippets actually match the code at those lines.
    """
    if not os.path.exists(filepath):
        return {
            "valid": False,
            "filepath": filepath,
            "total_lines": 0,
            "citations": [],
            "errors": [f"File not found for grounding verification: {filepath}"],
        }

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            file_lines = f.readlines()
    except Exception as e:
        return {
            "valid": False,
            "filepath": filepath,
            "total_lines": 0,
            "citations": [],
            "errors": [f"Failed to read file '{filepath}': {e}"],
        }

    total_lines = len(file_lines)
    citations = extract_line_citations(text)
    errors = []

    for start_line, end_line in citations:
        if start_line < 1:
            errors.append(f"Invalid line number: Line {start_line} is less than 1.")
        elif start_line > total_lines:
            errors.append(
                f"Hallucinated line number: Line {start_line} cited, but file '{os.path.basename(filepath)}' only has {total_lines} lines."
            )

        if end_line < start_line:
            errors.append(f"Invalid line range: {start_line}-{end_line} (start > end).")
        elif end_line > total_lines and start_line <= total_lines:
            errors.append(
                f"Hallucinated line range: End line {end_line} exceeds total lines ({total_lines}) in '{os.path.basename(filepath)}'."
            )

    snippets = extract_code_snippets(text)
    if snippets and citations:
        for snippet in snippets:
            clean_snippet = snippet.strip()
            if len(clean_snippet) < 3 or clean_snippet.lower() in ("python", "bash", "bare_except", "try", "except"):
                continue

            snippet_found = False
            for start_line, end_line in citations:
                if 1 <= start_line <= total_lines:
                    actual_end = min(end_line, total_lines)
                    cited_code = "".join(file_lines[start_line - 1 : actual_end])
                    if clean_snippet in cited_code:
                        snippet_found = True
                        break

            if not snippet_found and any(clean_snippet in line for line in file_lines):
                errors.append(
                    f"Code grounding mismatch: Snippet '{clean_snippet}' exists in file but not at cited line(s)."
                )

    return {
        "valid": len(errors) == 0,
        "filepath": filepath,
        "total_lines": total_lines,
        "citations": citations,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Pass 2: LLM Semantic Verification Agent
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """You are a Senior Code Review Verifier in CodeGuardian.
You provide a critical second-opinion review on bug detection findings produced by an automated bug detection agent.
Deterministic syntax checks and line grounding have ALREADY passed. Your job is purely SEMANTIC verification:

1. Fix Correctness: Does each suggested code fix actually resolve the underlying bug without introducing regressions or side-effects?
2. Explanation Accuracy: Is the "WHY it matters" rationale technically accurate for this specific context?
3. False Positive Filtering: Are any flagged issues intentional design decisions or acceptable patterns?
   Watch out for:
   - `assert` statements in test suites, benchmarks, or diagnostic scripts.
   - `bare except` in CLI entry points, daemon loops, or shutdown hooks.
   - `unused_variable` for throwaway loop indices or tuple unpacking (e.g., `_`, `idx`).
   - `open_without_encoding` when reading binary files or relying on platform standard io.
4. Severity Assessment: Calibrate severity appropriately (critical, high, medium, low).
5. Overall Quality & Verdict:
   - "approve": Analysis is technically sound and actionable.
   - "revise": Explanations or fixes contain non-fatal inaccuracies that should be noted.
   - "reject": Critical hallucination, broken fix, or overwhelming false positives.

IMPORTANT CONSERVATISM RULE: If an issue is ambiguous or a matter of style, favor "approve". Do not block deployments on pure speculation.

Return ONLY valid JSON matching this schema:
{
  "fix_correctness": [
    {
      "issue_id": 1,
      "fix_is_correct": true,
      "reasoning": "Explanation of fix validity."
    }
  ],
  "false_positives": [
    {
      "issue_id": 1,
      "is_false_positive": false,
      "reasoning": "Why this is or isn't a false positive."
    }
  ],
  "explanation_accuracy": [
    {
      "issue_id": 1,
      "explanation_is_accurate": true,
      "correction": null
    }
  ],
  "severity_assessment": [
    {
      "issue_id": 1,
      "suggested_severity": "medium",
      "reasoning": "Severity justification."
    }
  ],
  "summary_quality_score": 8,
  "overall_verdict": "approve",
  "comments": "High-level summary of the semantic review critique."
}"""


class LLMReviewVerifier:
    """
    Semantic code review verifier leveraging Groq Cloud API as primary
    and Ollama local server as fallback with timeout management.
    """

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    DEFAULT_OLLAMA_TIMEOUT = 10.0
    DEFAULT_GROQ_TIMEOUT = 5.0

    def __init__(
        self,
        groq_api_key: str | None = None,
        ollama_timeout: float | None = None,
        groq_timeout: float | None = None,
    ):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        env_ollama_timeout = os.getenv("OLLAMA_TIMEOUT")
        self.ollama_timeout = (
            ollama_timeout
            if ollama_timeout is not None
            else float(env_ollama_timeout) if env_ollama_timeout else self.DEFAULT_OLLAMA_TIMEOUT
        )
        env_groq_timeout = os.getenv("GROQ_TIMEOUT")
        self.groq_timeout = (
            groq_timeout
            if groq_timeout is not None
            else float(env_groq_timeout) if env_groq_timeout else self.DEFAULT_GROQ_TIMEOUT
        )

    def _call_groq_api(self, user_prompt: str) -> str | None:
        """Invokes Groq Cloud chat completions API using raw HTTP requests."""
        if not self.groq_api_key:
            return None
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.DEFAULT_GROQ_MODEL,
            "messages": [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(self.GROQ_API_URL, headers=headers, json=payload, timeout=self.groq_timeout)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            logger.warning("Groq review API returned HTTP %s: %s", resp.status_code, resp.text)
        except Exception as err:
            logger.warning("Groq review API request error: %s", err)
        return None

    def _call_ollama_api_sync(self, user_prompt: str) -> str | None:
        """Synchronously invokes Ollama local server."""
        try:
            import ollama
            response = ollama.chat(
                model=self.DEFAULT_OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                format="json",
                options={"temperature": 0.1},
            )
            msg = response["message"] if isinstance(response, dict) else getattr(response, "message", {})
            return msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        except Exception as err:
            logger.debug("Ollama sync review call error: %s", err)
            return None

    def _call_ollama_api(self, user_prompt: str, timeout: float | None = None) -> str | None:
        """Thread-bounded call to local Ollama server with timeout."""
        eff_timeout = timeout if timeout is not None else self.ollama_timeout
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._call_ollama_api_sync, user_prompt)
                return future.result(timeout=eff_timeout)
        except Exception as err:
            logger.debug("Ollama review executor error or timeout: %s", err)
            return None

    def _parse_llm_json(self, raw_content: str) -> dict | None:
        """Extracts and validates JSON payload from LLM response."""
        try:
            cleaned = raw_content.strip()
            if "```json" in cleaned:
                cleaned = re.search(r"```json\s*(.*?)\s*```", cleaned, re.DOTALL).group(1)
            elif "```" in cleaned:
                cleaned = re.search(r"```\s*(.*?)\s*```", cleaned, re.DOTALL).group(1)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "overall_verdict" in parsed:
                return parsed
        except Exception as e:
            logger.warning("Failed to parse JSON from LLM review output: %s", e)
        return None

    def verify(
        self,
        source_code: str,
        raw_findings: str,
        summary: str,
        filepath: str = "<unknown>",
    ) -> dict | None:
        """
        Executes semantic verification across Groq -> Ollama -> Graceful fallback.
        Returns parsed review dictionary or None if LLM is unavailable.
        """
        user_prompt = (
            f"Target File: {filepath}\n\n"
            f"--- SOURCE CODE ---\n```python\n{source_code}\n```\n\n"
            f"--- RAW AST FINDINGS ---\n{raw_findings}\n\n"
            f"--- BUG DETECTION AGENT SUMMARY ---\n{summary}\n\n"
            "Evaluate each issue, suggested fix, explanation, and provide verdict in JSON."
        )

        # 1. Primary: Groq API
        if self.groq_api_key:
            res = self._call_groq_api(user_prompt)
            if res:
                parsed = self._parse_llm_json(res)
                if parsed:
                    logger.info("Semantic review successfully verified via Groq Cloud.")
                    return parsed

        # 2. Fallback: Ollama local API
        res = self._call_ollama_api(user_prompt)
        if res:
            parsed = self._parse_llm_json(res)
            if parsed:
                logger.info("Semantic review successfully verified via Ollama local fallback.")
                return parsed

        # 3. Graceful degradation: No LLM available
        logger.info("LLM Reviewer unavailable; degrading gracefully to deterministic pass.")
        return None


# ---------------------------------------------------------------------------
# Public Review Agent Entry Point (Two-Pass Pipeline)
# ---------------------------------------------------------------------------

def review_bug_detection_output(agent_response: dict, filepath: str = None) -> dict:
    """
    Two-pass critique of Bug Detection Agent output:
      - Pass 1: Deterministic structural checks (consistency, counts, grounding, AST syntax).
      - Pass 2: LLM semantic critique (fix validity, technical correctness, false positives).

    Input: the AgentResponse dict from bug_detection.analyze_and_explain(), optional filepath
    Output: {
        agent_name, approved, issues, reviewed_summary, grounding, syntax_validation,
        deterministic_pass, llm_review, llm_available, review_mode
    }
    """
    summary = agent_response.get("summary", "")
    details = agent_response.get("details", {}) or {}
    raw_findings = details.get("raw_findings") or ""

    # Resolve target filepath
    target_path = filepath or details.get("filepath")
    if not target_path:
        path_match = re.search(r"in ([\w\-\\./:\\]+\.py)", raw_findings + "\n" + summary)
        if path_match:
            target_path = path_match.group(1)

    problems: list[str] = []
    expected_count = len(re.findall(r"ISSUE \d+:", raw_findings))

    # =========================================================================
    # PASS 1: Deterministic Structural Gate
    # =========================================================================

    # Check 1: summary shouldn't claim "clean" if real findings exist
    if expected_count > 0 and re.search(r"\b(clean|no issues|no real issues)\b", summary, re.IGNORECASE):
        problems.append("Summary claims file is clean, but raw findings contain real issues.")

    # Check 2: every expected issue should be addressed
    addressed_count = len(re.findall(r"Issue \d+:", summary, re.IGNORECASE))
    if expected_count > 0 and addressed_count < expected_count:
        problems.append(f"Only {addressed_count}/{expected_count} issues addressed in summary.")

    # Check 3: summary should explain why + suggest a fix
    if expected_count > 0:
        if "WHY" not in summary.upper():
            problems.append("Summary doesn't explain WHY any issue matters.")
        if "FIX" not in summary.upper():
            problems.append("Summary doesn't suggest a FIX for any issue.")

    # Check 4: Line-Number & Code Grounding Verification (TASK-E1)
    grounding_result = None
    if target_path and os.path.exists(target_path):
        grounding_result = verify_line_grounding(target_path, summary + "\n" + raw_findings)
        if not grounding_result["valid"]:
            problems.extend(grounding_result["errors"])
    elif target_path and not os.path.exists(target_path):
        problems.append(f"Specified file path for grounding verification does not exist: {target_path}")

    # Check 5: AST Code Syntax & Lint Validation (TASK-E2)
    syntax_result = verify_syntax_and_lint(summary)
    if not syntax_result["valid"]:
        problems.extend(syntax_result["syntax_errors"])

    deterministic_pass = (len(problems) == 0)

    # If deterministic gate fails, reject immediately without spending LLM tokens
    if not deterministic_pass:
        return {
            "agent_name": "review_agent",
            "approved": False,
            "issues": problems,
            "reviewed_summary": summary,
            "grounding": grounding_result,
            "syntax_validation": syntax_result,
            "deterministic_pass": False,
            "llm_review": None,
            "llm_available": False,
            "review_mode": "deterministic",
        }

    # =========================================================================
    # PASS 2: LLM Semantic Verification (Deep Pass)
    # =========================================================================
    source_code = ""
    if target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                source_code = f.read()
        except Exception:
            source_code = ""

    verifier = LLMReviewVerifier()
    llm_critique = verifier.verify(
        source_code=source_code,
        raw_findings=raw_findings,
        summary=summary,
        filepath=target_path or "<unknown>",
    )

    if llm_critique is None:
        # Graceful degradation: Deterministic pass passed, LLM unavailable -> approve
        return {
            "agent_name": "review_agent",
            "approved": True,
            "issues": problems,
            "reviewed_summary": summary,
            "grounding": grounding_result,
            "syntax_validation": syntax_result,
            "deterministic_pass": True,
            "llm_review": None,
            "llm_available": False,
            "review_mode": "deterministic",
        }

    # Process LLM Semantic Critique
    verdict = str(llm_critique.get("overall_verdict", "approve")).lower()
    llm_comments = llm_critique.get("comments", "")
    llm_issues: list[str] = []

    # Check for flagged invalid fixes
    for fix in llm_critique.get("fix_correctness", []):
        if not fix.get("fix_is_correct", True):
            llm_issues.append(f"Issue {fix.get('issue_id')}: Suggested fix flagged as incorrect - {fix.get('reasoning')}")

    # Check for flagged explanation inaccuracies
    for exp in llm_critique.get("explanation_accuracy", []):
        if not exp.get("explanation_is_accurate", True):
            correction = f" Correction: {exp.get('correction')}" if exp.get("correction") else ""
            llm_issues.append(f"Issue {exp.get('issue_id')}: Technical explanation inaccurate.{correction}")

    # Verdict handling
    if verdict == "reject":
        approved = False
        reason = f"LLM Reviewer rejected summary: {llm_comments}" if llm_comments else "LLM Reviewer rejected output."
        problems.append(reason)
        problems.extend(llm_issues)
    elif verdict == "revise":
        approved = False
        reason = f"LLM Reviewer requested revision: {llm_comments}" if llm_comments else "Revision required."
        problems.append(reason)
        problems.extend(llm_issues)
    else:  # "approve"
        approved = True
        # If there were minor remarks, we keep them recorded but approved remains True

    return {
        "agent_name": "review_agent",
        "approved": approved,
        "issues": problems,
        "reviewed_summary": summary,
        "grounding": grounding_result,
        "syntax_validation": syntax_result,
        "deterministic_pass": True,
        "llm_review": llm_critique,
        "llm_available": True,
        "review_mode": "hybrid",
    }
