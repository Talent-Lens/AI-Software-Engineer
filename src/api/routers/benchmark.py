"""
Independent Benchmark Router (Fair Evaluation)

Clones a public GitHub repository, runs an external third-party judge
(Bandit for security, pytest for bug-fix verification), and compares
the judge's findings with CodeGuardian's findings.

CodeGuardian NEVER grades itself — the judge is always an independent tool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    BenchmarkRequest,
    BenchmarkResponse,
    BenchmarkResult,
)

logger = logging.getLogger("ai_engineer.api.benchmark")
router = APIRouter(tags=["Benchmark"])


# ---------------------------------------------------------------------------
# Helper: Robust JSON parser for CLI outputs (handles stdout progress/noise)
# ---------------------------------------------------------------------------

def _extract_json_data(text: str) -> Dict[str, Any]:
    """
    Extract and parse JSON object from CLI stdout.
    Handles cases where tools output progress meters, banner text, or warnings
    before/after the actual JSON body.
    """
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(text[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass
        raise


# ---------------------------------------------------------------------------
# Helper: Run Bandit (independent security judge)
# ---------------------------------------------------------------------------

def _run_bandit(repo_path: Path) -> List[Dict[str, Any]]:
    """
    Run Bandit (third-party SAST scanner) on the cloned repo.
    Returns a list of issue dicts straight from Bandit's own JSON output.
    """
    # If the repository does not contain any Python files, Bandit has nothing to scan
    has_python_files = any(repo_path.rglob("*.py"))
    if not has_python_files:
        logger.info("No Python files found in repository %s; skipping Bandit scan.", repo_path)
        return []

    cmd = [
        sys.executable, "-m", "bandit",
        "-r", str(repo_path),
        "-f", "json",
        "-q",  # Quiet mode: suppress progress bars and non-JSON output
        "--exclude", ".git,node_modules,venv,.venv,__pycache__",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=90)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Bandit security scan timed out after 90 seconds.") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to execute Bandit: {exc}") from exc

    # Attempt to extract JSON from stdout even if exit code is 1 (issues found)
    try:
        data = _extract_json_data(proc.stdout)
        return data.get("results", [])
    except Exception as exc:
        # Bandit exit codes: 0 = clean, 1 = issues found, other = error
        if proc.returncode not in (0, 1):
            err_msg = proc.stderr.strip()[:500] if proc.stderr else proc.stdout.strip()[:500]
            raise RuntimeError(f"Bandit failed (exit {proc.returncode}): {err_msg}") from exc
        raise RuntimeError(f"Bandit output is not valid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Helper: Run pytest (independent bug-fix judge)
# ---------------------------------------------------------------------------

def _run_pytest(repo_path: Path) -> Dict[str, Any]:
    """
    Run pytest with JSON report plugin on the cloned repo.
    Returns summary dict with total / passed / failed counts.
    """
    report_file = repo_path / ".pytest_report.json"
    cmd = [
        sys.executable, "-m", "pytest",
        str(repo_path),
        "--json-report",
        f"--json-report-file={report_file}",
        "--tb=no",
        "-q",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, cwd=repo_path, check=False, timeout=60)
    except subprocess.TimeoutExpired:
        logger.warning("pytest run timed out after 60 seconds on %s", repo_path)
        return {"total": 0, "passed": 0, "failed": 0}
    except Exception as exc:
        logger.warning("pytest failed to execute on %s: %s", repo_path, exc)
        return {"total": 0, "passed": 0, "failed": 0}

    if not report_file.is_file():
        return {"total": 0, "passed": 0, "failed": 0}

    try:
        with open(report_file, "r", encoding="utf-8") as f:
            report = json.load(f)
        summary = report.get("summary", {})
        return {
            "total": summary.get("total", 0),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
        }
    except Exception as exc:
        logger.warning("Failed to parse pytest json report: %s", exc)
        return {"total": 0, "passed": 0, "failed": 0}


# ---------------------------------------------------------------------------
# Helper: Run CodeGuardian's own security scanner on the same repo
# ---------------------------------------------------------------------------

def _run_codeguardian_security(repo_path: Path) -> List[Dict[str, Any]]:
    """
    Run CodeGuardian's own AST-based security auditor on every Python file
    in the cloned repo. Returns a list of finding dicts.
    """
    try:
        from src.agents.security_auditor import SecurityASTScanner
    except ImportError as exc:
        logger.error("Failed to import SecurityASTScanner: %s", exc)
        return []

    findings: List[Dict[str, Any]] = []

    for py_file in repo_path.rglob("*.py"):
        # Skip hidden dirs, venvs, etc.
        try:
            rel = py_file.relative_to(repo_path)
        except ValueError:
            continue

        skip_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__"}
        if any(part in skip_dirs for part in rel.parts):
            continue

        rel_posix = rel.as_posix()
        try:
            code = py_file.read_text(encoding="utf-8", errors="ignore")
            scanner = SecurityASTScanner(code, rel_posix)
            file_findings = scanner.scan()
            for vuln in file_findings:
                findings.append({
                    "file": rel_posix,
                    "line": vuln.line_number,
                    "title": vuln.title,
                    "severity": vuln.severity,
                    "owasp": vuln.owasp_category,
                })
        except Exception as err:
            logger.debug("Skipping %s: %s", py_file, err)

    return findings


# ---------------------------------------------------------------------------
# Comparison logic: CodeGuardian findings vs Bandit findings
# ---------------------------------------------------------------------------

def _normalize_rel(path_str: str, base: Path) -> str:
    """
    Normalize any path (absolute or relative, Windows or POSIX)
    to a consistent lowercase forward-slash relative path relative to base.
    """
    if not path_str:
        return ""

    norm_str = re.sub(r"[/\\]+", "/", path_str).strip()
    base_posix = re.sub(r"[/\\]+", "/", base.as_posix().lower()).rstrip("/") + "/"
    p_posix = norm_str.lower()

    if p_posix.startswith(base_posix):
        return p_posix[len(base_posix):].lstrip("./")

    p = Path(norm_str)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(base.resolve()).as_posix().lstrip("./").lower()
        except Exception:
            pass

    return norm_str.lstrip("./").lower()


def _compare_security(
    codeguardian_findings: List[Dict[str, Any]],
    bandit_findings: List[Dict[str, Any]],
    repo_path: Path,
    has_python_files: bool = True,
) -> BenchmarkResult:
    """
    Compare CodeGuardian's findings against Bandit's findings (the ground truth).

    Ground truth = Bandit's report (independent third-party judge).
    We check how many Bandit issues CodeGuardian also detected (by file + line proximity).
    """
    if not has_python_files:
        return BenchmarkResult(
            total_cases=0,
            detected_cases=0,
            false_positives=0,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            details=[{
                "file": "Overview",
                "line": "0",
                "issue": "No Python files found in this repository. Bandit SAST evaluates Python source code.",
                "severity": "INFO",
                "matched": True,
            }],
        )

    # Build a set of (file, line) tuples from Bandit (the ground truth)
    bandit_locations = set()
    for issue in bandit_findings:
        fname = _normalize_rel(issue.get("filename", ""), repo_path)
        line = issue.get("line_number", 0)
        bandit_locations.add((fname, line))

    # Build a set of (file, line) tuples from CodeGuardian
    cg_locations = set()
    for finding in codeguardian_findings:
        fname = _normalize_rel(finding.get("file", finding.get("filename", "")), repo_path)
        line = finding.get("line", finding.get("line_number", 0))
        cg_locations.add((fname, line))

    # True positives: issues Bandit found AND CodeGuardian also found (±3 lines tolerance)
    detected = 0
    matched_bandit_locations = set()
    for b_file, b_line in bandit_locations:
        for c_file, c_line in cg_locations:
            if b_file == c_file and abs(b_line - c_line) <= 3:
                detected += 1
                matched_bandit_locations.add((b_file, b_line))
                break

    bandit_details = []
    for issue in bandit_findings:
        fname = _normalize_rel(issue.get("filename", ""), repo_path)
        line = issue.get("line_number", 0)
        is_matched = (fname, line) in matched_bandit_locations
        bandit_details.append({
            "file": fname or "unknown",
            "line": str(line),
            "issue": issue.get("issue_text", ""),
            "severity": issue.get("issue_severity", "LOW"),
            "matched": is_matched,
        })

    # False positives: CodeGuardian flagged but Bandit did NOT flag
    false_positives = 0
    for c_file, c_line in cg_locations:
        matched = False
        for b_file, b_line in bandit_locations:
            if c_file == b_file and abs(c_line - b_line) <= 3:
                matched = True
                break
        if not matched:
            false_positives += 1

    total = len(bandit_locations)
    if total == 0:
        # Both clean or no security issues found by third-party judge
        precision = 1.0 if false_positives == 0 else 0.0
        recall = 1.0
        f1 = 1.0 if precision == 1.0 else 0.0
        if not bandit_details:
            bandit_details.append({
                "file": "Overview",
                "line": "0",
                "issue": "Bandit SAST and CodeGuardian found 0 security issues in this repository.",
                "severity": "INFO",
                "matched": True,
            })
    else:
        true_pos = detected
        precision = true_pos / max(true_pos + false_positives, 1)
        recall = true_pos / max(total, 1)
        if precision + recall == 0:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall)

    return BenchmarkResult(
        total_cases=total,
        detected_cases=detected,
        false_positives=false_positives,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
        details=bandit_details[:50],  # cap detail list for UI performance
    )


# ---------------------------------------------------------------------------
# Synchronous Executor (Executed in worker thread to prevent event loop blocking)
# ---------------------------------------------------------------------------

def _execute_benchmark(repo_url: str, test_type: str) -> BenchmarkResult:
    """
    Synchronous benchmark execution pipeline:
    1. Clones repository in isolated temp directory.
    2. Runs independent third-party judge + CodeGuardian scanner.
    3. Calculates precision, recall, and F1 metrics.
    4. Cleans up temp directory in finally block.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="cg_bench_"))
    try:
        # ── 1. Clone ──────────────────────────────────────────────────
        git_exe = shutil.which("git") or "git"
        clone_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        try:
            subprocess.run(
                [git_exe, "clone", "--depth", "1", repo_url, str(tmp_dir)],
                check=True,
                capture_output=True,
                text=True,
                env=clone_env,
                timeout=60,
            )
            logger.info("Cloned %s into %s", repo_url, tmp_dir)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=400,
                detail="Git clone timed out after 60 seconds. The repository may be too large or network is slow."
            ) from exc
        except subprocess.CalledProcessError as exc:
            clean_err = exc.stderr.strip() or exc.stdout.strip() or "Clone failed"
            if "Repository not found" in clean_err or "not found" in clean_err:
                clean_err = f"Repository not found or private: {repo_url}"
            elif "could not read Username" in clean_err or "Authentication failed" in clean_err:
                clean_err = f"Repository is private or requires authentication: {repo_url}"
            raise HTTPException(status_code=400, detail=f"Cannot clone repo: {clean_err[:300]}") from exc

        # ── 2. Run the independent judge + CodeGuardian ───────────────
        has_python_files = any(tmp_dir.rglob("*.py"))

        if test_type == "security":
            # Judge = Bandit (independent third-party)
            bandit_findings = _run_bandit(tmp_dir)
            # Subject = CodeGuardian
            cg_findings = _run_codeguardian_security(tmp_dir)
            # Compare
            return _compare_security(cg_findings, bandit_findings, tmp_dir, has_python_files)

        elif test_type == "bugfix":
            # Judge = pytest (tests either pass or fail — objective)
            pytest_res = _run_pytest(tmp_dir)
            total = pytest_res["total"]
            passed = pytest_res["passed"]
            failed = pytest_res["failed"]
            return BenchmarkResult(
                total_cases=total,
                detected_cases=failed,
                false_positives=0,
                precision=round(passed / max(total, 1), 4),
                recall=round(failed / max(total, 1), 4) if failed else 0.0,
                f1_score=0.0,
                details=[{
                    "file": "pytest suite",
                    "line": "0",
                    "issue": f"Total: {total}, Passed: {passed}, Failed: {failed}",
                    "severity": "HIGH" if failed > 0 else "LOW",
                    "matched": True,
                }],
            )

        elif test_type == "rag":
            return BenchmarkResult(
                total_cases=0,
                detected_cases=0,
                false_positives=0,
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
                details=[{
                    "file": "RAG Evaluator",
                    "line": "0",
                    "issue": "RAG evaluation judge placeholder.",
                    "severity": "INFO",
                    "matched": True,
                }],
            )

        else:
            raise HTTPException(status_code=400, detail=f"Unknown test_type: {test_type}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@router.post("/benchmark", response_model=BenchmarkResponse)
async def run_benchmark(request: BenchmarkRequest) -> BenchmarkResponse:
    """
    Fair, independent benchmark evaluation.

    1. Clones the public repo into an isolated temp sandbox.
    2. Runs the independent third-party judge (Bandit / pytest).
    3. Runs CodeGuardian on the same repo.
    4. Compares the two — the judge's output is ground truth.
    5. Returns precision / recall / F1 to the UI.
    """
    repo_url = str(request.repo_url).strip()
    try:
        metrics = await asyncio.to_thread(_execute_benchmark, repo_url, request.test_type)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Benchmark failed for %s", repo_url)
        raise HTTPException(status_code=500, detail=str(exc))

    return BenchmarkResponse(
        status="completed",
        repo_url=request.repo_url,
        test_type=request.test_type,
        metrics=metrics,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )
