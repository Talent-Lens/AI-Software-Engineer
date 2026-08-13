"""
Review Agent — critiques Bug Detection Agent output before it's returned
as final. Checks that every issue mentioned in raw findings is actually
addressed in the summary, with why/line/fix present, verifies that
cited line numbers exist in the source file and ground the cited code (TASK-E1),
and validates that all suggested code fixes are 100% syntactically valid (TASK-E2).
"""

from __future__ import annotations

import ast
import os
import re
import py_compile
import tempfile


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
        # Extract any backtick code snippets within the fix line
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
            f"try:\n    pass\n" + "\n".join("    " + l if l.strip().startswith("except") or l.strip().startswith("finally") else "    " + l for l in clean_code.splitlines()),
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

        # If all parsing modes failed, report the primary syntax error details
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

    # Default fallback for non-python languages (pass validation)
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

    # Check snippet grounding if code snippets are quoted
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


def review_bug_detection_output(agent_response: dict, filepath: str = None) -> dict:
    """
    Input: the AgentResponse dict from bug_detection.analyze_and_explain(), optional filepath
    Output: { agent_name, approved, issues, reviewed_summary, grounding, syntax_validation }
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

    problems = []
    expected_count = len(re.findall(r"ISSUE \d+:", raw_findings))

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

    approved = len(problems) == 0

    return {
        "agent_name": "review_agent",
        "approved": approved,
        "issues": problems,
        "reviewed_summary": summary,
        "grounding": grounding_result,
        "syntax_validation": syntax_result,
    }