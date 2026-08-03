"""
Review Agent — critiques Bug Detection Agent output before it's returned
as final. Checks that every issue mentioned in raw findings is actually
addressed in the summary, with why/line/fix present.
"""

import re


def review_bug_detection_output(agent_response: dict) -> dict:
    """
    Input: the AgentResponse dict from bug_detection.analyze_and_explain()
    Output: { agent_name, approved, issues, reviewed_summary }
    """
    summary = agent_response.get("summary", "")
    raw_findings = agent_response.get("details", {}).get("raw_findings") or ""

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

    approved = len(problems) == 0

    return {
        "agent_name": "review_agent",
        "approved": approved,
        "issues": problems,
        "reviewed_summary": summary,
    }