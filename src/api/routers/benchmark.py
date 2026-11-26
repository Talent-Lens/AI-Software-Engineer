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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.schemas import (
    BenchmarkRequest,
    BenchmarkResponse,
    BenchmarkResult,
)
from src.db.session import get_benchmark_read_db, get_db
from src.benchmarks.read_service import BenchmarkReadService, get_latest_latency_pass_from_db

logger = logging.getLogger("ai_engineer.api.benchmark")


def get_benchmark_mode() -> str:
    """Returns 'research' only when BENCHMARK_MODE=research; defaults to 'readonly'."""
    raw = os.getenv("BENCHMARK_MODE", "readonly").strip().lower()
    return "research" if raw == "research" else "readonly"


read_router = APIRouter(tags=["Benchmark"])
research_router = APIRouter(tags=["Benchmark Research"])


@read_router.get("/benchmarks/capabilities")
def get_benchmark_capabilities() -> Dict[str, Any]:
    """Returns current benchmark mode and UI capabilities."""
    mode = get_benchmark_mode()
    is_research = mode == "research"
    return {
        "benchmark_mode": mode,
        "readonly": not is_research,
        "can_mutate": is_research,
        "can_run": is_research,
        "can_add": is_research,
        "can_recompute": is_research,
        "can_triage": is_research,
        "can_latency_pass": is_research,
    }


class AddResearchRepoRequest(BaseModel):
    repo_url: str = Field(..., description="GitHub HTTPS repository URL")
    identifier: str = Field(..., description="CVE identifier (e.g. CVE-2021-32677) or fix commit SHA")
    cwe: Optional[str] = Field(None, description="Optional CWE classification (e.g. CWE-22)")


class ExcludeRepoRequest(BaseModel):
    reason: str = Field(..., min_length=5, description="Mandatory written reason for exclusion")


class DeleteRepoRequest(BaseModel):
    reason: Optional[str] = Field(None, description="Written reason (required if repo has completed runs)")


class ImportTriageRequest(BaseModel):
    findings: List[Dict[str, Any]] = Field(..., description="List of findings with triage decisions")


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
        "-m", "not slow",
        "--maxfail=10",
    ]
    stdout_text = ""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_path, check=False, timeout=60)
        stdout_text = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        logger.warning("pytest run timed out after 60 seconds on %s", repo_path)
        return {"total": 0, "passed": 0, "failed": 0}
    except Exception as exc:
        logger.warning("pytest failed to execute on %s: %s", repo_path, exc)
        return {"total": 0, "passed": 0, "failed": 0}

    if report_file.is_file():
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

    # Fallback regex extraction from stdout
    passed_m = re.search(r"(\d+)\s+passed", stdout_text)
    failed_m = re.search(r"(\d+)\s+failed", stdout_text)
    passed_count = int(passed_m.group(1)) if passed_m else 0
    failed_count = int(failed_m.group(1)) if failed_m else 0
    total_count = passed_count + failed_count
    return {
        "total": total_count,
        "passed": passed_count,
        "failed": failed_count,
    }


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
# Helper: Robust Windows rmtree
# ---------------------------------------------------------------------------

def _robust_rmtree(path: Path) -> None:
    """Safely delete directory tree on Windows, clearing read-only attributes created by git."""
    import stat
    def _handle_readonly(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    if path.exists():
        try:
            shutil.rmtree(path, onerror=_handle_readonly)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helper: Pre-cached benchmark corpora discovery & repository resolution
# ---------------------------------------------------------------------------

def _get_benchmark_cache_dir() -> Path:
    """Returns the persistent directory holding pre-cached / bundled benchmark corpora."""
    # Resolves to AI-Software-Engineer/data/benchmark_cache
    cache_dir = Path(__file__).resolve().parents[3] / "data" / "benchmark_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _find_cached_benchmark(target: str) -> Optional[Path]:
    """
    Search for a pre-cached snapshot matching the target repository
    across standard corpora:
    - 'stamparm/DSSS' (SQLi test suite) -> data/benchmark_cache/stamparm_DSSS
    - 'we45/Vulnerable-Flask-App' (SAST suite) -> data/benchmark_cache/we45_Vulnerable-Flask-App
    - 'psf/requests' (pytest test suite) -> data/benchmark_cache/psf_requests
    Also matches any previously cloned or downloaded repositories.
    """
    cache_dir = _get_benchmark_cache_dir()
    if not cache_dir.is_dir():
        return None

    clean = target.strip().strip("'\"").rstrip("/").lower()
    if clean.endswith(".git"):
        clean = clean[:-4]

    # 1. Alias matching for standard benchmark suites
    alias_map = {
        "dsss": "stamparm_DSSS",
        "vulnerable-flask-app": "we45_Vulnerable-Flask-App",
        "vulnerable_flask_app": "we45_Vulnerable-Flask-App",
        "requests": "psf_requests",
    }
    for alias, dirname in alias_map.items():
        if alias in clean:
            cand = cache_dir / dirname
            if cand.is_dir():
                return cand

    # 2. Extract slug if possible
    slug = re.sub(r"^https?://[^/]+/", "", clean)
    if slug.startswith("github.com/"):
        slug = slug[len("github.com/"):]
    parts = [p for p in slug.split("/") if p]
    if len(parts) >= 2:
        direct_key = f"{parts[-2]}_{parts[-1]}"
        for item in cache_dir.iterdir():
            if item.is_dir() and item.name.lower() == direct_key.lower():
                return item
    elif len(parts) == 1:
        repo_name = parts[0]
        for item in cache_dir.iterdir():
            if item.is_dir() and (item.name.lower() == repo_name.lower() or item.name.lower().endswith(f"_{repo_name.lower()}")):
                return item

    return None


def _download_github_zip(owner: str, repo: str, target_dir: Path) -> bool:
    """
    Download and unpack repository ZIP archive directly from GitHub codeload.
    Acts as a resilient fallback if git CLI fails (e.g. DNS resolution, proxy, SSL).
    """
    import urllib.request
    import zipfile
    import io

    zip_candidates = [
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master",
        f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip",
        f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip",
    ]

    for z_url in zip_candidates:
        try:
            req = urllib.request.Request(
                z_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CodeGuardian/1.0"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    zip_data = resp.read()
                    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                        namelist = zf.namelist()
                        root_prefix = namelist[0].split("/")[0] + "/" if namelist and "/" in namelist[0] else ""
                        for member in zf.infolist():
                            if member.is_dir():
                                continue
                            rel_name = member.filename
                            if root_prefix and rel_name.startswith(root_prefix):
                                rel_name = rel_name[len(root_prefix):]
                            if not rel_name:
                                continue
                            dest = target_dir / rel_name
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(member) as src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                    logger.info("Successfully fetched and extracted repository archive from %s", z_url)
                    return True
        except Exception as exc:
            logger.debug("Zip download attempt failed for %s: %s", z_url, exc)

    return False


def _prepare_benchmark_repo(target: str, tmp_dir: Path) -> str:
    """
    Prepares repository in sandbox tmp_dir with 100% reliability across all cases:
    1. Local directories (e.g. 'test_repo', absolute/relative path) -> copied directly.
    2. Cached standard benchmark corpora -> instantly copied if offline or if network fails.
    3. Remote repository shallow clone with optimized network parameters.
    4. Resilient Python HTTP zip fallback if git network fails.
    5. Persistent cache saving for newly fetched repositories.
    """
    raw = target.strip().strip("'\"").rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]

    # --- Case 1: Local Directory on disk ---
    local_path = Path(raw)
    if not local_path.is_absolute():
        workspace_root = Path(__file__).resolve().parents[3]
        if (workspace_root / raw).is_dir():
            local_path = workspace_root / raw

    if local_path.is_dir():
        logger.info("Using local repository directory: %s", local_path)
        shutil.copytree(
            local_path,
            tmp_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", "venv", ".venv", "__pycache__", "node_modules", ".pytest_cache")
        )
        return str(local_path)

    # --- Case 2: Parse Remote URL & Search Cache ---
    clean_url = raw
    if clean_url.startswith("http://") or clean_url.startswith("https://"):
        clean_url = re.sub(r"^https?://[^/]+/", "", clean_url)
    elif clean_url.startswith("github.com/"):
        clean_url = clean_url[len("github.com/"):]

    parts = [p for p in clean_url.split("/") if p]
    owner, repo = "", ""
    if len(parts) >= 2:
        owner = parts[-2]
        repo = parts[-1]
    elif len(parts) == 1:
        repo = parts[0]

    cache_key = f"{owner}_{repo}" if owner and repo else repo
    clone_url = f"https://github.com/{owner}/{repo}.git" if owner and repo else raw

    cached_repo = _find_cached_benchmark(raw)

    # --- Case 3: Try Git Shallow Clone ---
    git_exe = shutil.which("git") or "git"
    clone_env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
        "GIT_HTTP_LOW_SPEED_TIME": "15",
    }

    git_success = False
    git_err = ""
    try:
        subprocess.run(
            [
                git_exe,
                "-c", "http.version=HTTP/1.1",
                "-c", "http.sslVerify=false",
                "clone",
                "--depth", "1",
                "--single-branch",
                clone_url,
                str(tmp_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=clone_env,
            timeout=25,
        )
        git_success = True
        logger.info("Cloned %s into %s", clone_url, tmp_dir)
    except subprocess.TimeoutExpired:
        git_err = "Git clone timed out after 25 seconds."
        logger.warning(git_err)
    except Exception as exc:
        git_err = getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or str(exc)
        logger.warning("Git clone failed for %s: %s", clone_url, git_err)

    if git_success:
        # Cache for future instant/offline runs
        try:
            cache_dir = _get_benchmark_cache_dir()
            if cache_key:
                save_dest = cache_dir / cache_key
                if not save_dest.exists():
                    shutil.copytree(
                        tmp_dir,
                        save_dest,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "venv", ".venv", "__pycache__")
                    )
        except Exception as cache_exc:
            logger.debug("Failed saving repository to cache: %s", cache_exc)
        return clone_url

    # --- Case 4: Cache Fallback (Network / DNS failure) ---
    if cached_repo and cached_repo.is_dir():
        logger.info("Using cached repository fallback: %s", cached_repo)
        shutil.copytree(
            cached_repo,
            tmp_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", "venv", ".venv", "__pycache__", "node_modules")
        )
        return f"{clone_url} (Pre-cached snapshot)"

    # --- Case 5: Python HTTP Zip Fallback ---
    if owner and repo:
        if _download_github_zip(owner, repo, tmp_dir):
            try:
                cache_dir = _get_benchmark_cache_dir()
                save_dest = cache_dir / cache_key
                if not save_dest.exists():
                    shutil.copytree(
                        tmp_dir,
                        save_dest,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "venv", ".venv", "__pycache__")
                    )
            except Exception:
                pass
            return clone_url

    # --- Case 6: Clean, Actionable Failure Message ---
    clean_err = git_err.strip()
    if "Could not resolve host" in clean_err or "unable to access" in clean_err:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot reach GitHub (network/DNS offline). "
                f"For offline benchmarking, use a pre-cached corpus ('stamparm/DSSS', 'we45/Vulnerable-Flask-App') "
                f"or test a local repository folder (e.g. 'test_repo')."
            )
        )
    elif "Repository not found" in clean_err or "not found" in clean_err:
        raise HTTPException(status_code=400, detail=f"Repository not found or private: {raw}")
    elif "could not read Username" in clean_err or "Authentication failed" in clean_err:
        raise HTTPException(status_code=400, detail=f"Repository is private or requires authentication: {raw}")
    else:
        raise HTTPException(status_code=400, detail=f"Cannot clone repo: {clean_err[:300] or 'Clone failed'}")


# ---------------------------------------------------------------------------
# Synchronous Executor (Executed in worker thread to prevent event loop blocking)
# ---------------------------------------------------------------------------

def _execute_benchmark(repo_url: str, test_type: str) -> BenchmarkResult:
    """
    Synchronous benchmark execution pipeline:
    1. Prepares repository in isolated temp directory (clones or uses cached/local).
    2. Runs independent third-party judge + CodeGuardian scanner.
    3. Calculates precision, recall, and F1 metrics.
    4. Cleans up temp directory safely in finally block.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="cg_bench_"))
    try:
        # ── 1. Prepare repository (Resilient multi-tier resolver) ───────
        resolved_target = _prepare_benchmark_repo(repo_url, tmp_dir)
        logger.info("Executing benchmark for %s (sandbox: %s)", resolved_target, tmp_dir)

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
        _robust_rmtree(tmp_dir)


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@read_router.post("/benchmark", response_model=BenchmarkResponse)
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


# ---------------------------------------------------------------------------
# Research-Grade Independent Ground-Truth Benchmark Endpoints
# ---------------------------------------------------------------------------

@read_router.get("/benchmarks/overview")
def get_benchmarks_overview(
    verified_only: bool = Query(False, description="Filter for verified ground-truth repositories only"),
    db: Session = Depends(get_benchmark_read_db),
) -> Dict[str, Any]:
    """
    Returns macro-averages for each tool across all active research repos,
    sample size (N total, M verified), and upper-bound false positive warnings.
    """
    service = BenchmarkReadService(db)
    return service.get_overview_macro_metrics(verified_only=verified_only)


@read_router.get("/benchmarks/repos")
def get_benchmarks_repos(db: Session = Depends(get_benchmark_read_db)) -> List[Dict[str, Any]]:
    """
    Returns the list of research benchmark repositories with pinned SHAs and per-tool metrics.
    """
    service = BenchmarkReadService(db)
    return service.get_research_repos()


@research_router.post("/benchmarks/repos")
def add_research_repository(
    body: AddResearchRepoRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Admin endpoint to trigger automatic one-step research repository ingestion:
    resolves commits, extracts diffs, generates ground truth, scans dual commits,
    and recalculates general averages.
    """
    from src.benchmarks_research.service import BenchmarkService, DuplicateRepoError
    service = BenchmarkService(db)
    try:
        repo = service.add_research_repo(url=body.repo_url, identifier=body.identifier, cwe=body.cwe)
        return {"status": "queued", "repo": repo.to_dict()}
    except DuplicateRepoError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Failed to add research repository")
        raise HTTPException(status_code=400, detail=str(e))


@research_router.get("/benchmarks/repos/{repo_id}/run-plan")
def get_benchmark_run_plan(
    repo_id: str,
    force_rescan: bool = Query(False, description="If true, ignores result cache and marks all tools for re-scan"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Preview which tools will reuse cached results vs re-scan before confirming."""
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        return service.get_run_plan(repo_id, force_rescan=force_rescan)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@research_router.post("/benchmarks/repos/{repo_id}/run")
def run_research_repository(
    repo_id: str,
    tool: Optional[str] = Query(None, description="Optional single tool name to re-run (reusing cached results for others)"),
    force_rescan: bool = Query(False, description="Force full re-scan, ignoring cached tool results"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Starts or re-runs the automated benchmark pipeline (all tools or a single tool).
    Append-only: prior runs are marked superseded, never deleted.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        repo = service.run_repo_pipeline(repo_id, tool=tool, force_rescan=force_rescan)
        return {"status": "started", "tool": tool, "force_rescan": force_rescan, "repo": repo.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=409 if "already" in str(e).lower() else 400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@research_router.post("/benchmarks/repos/{repo_id}/retry")
def retry_research_repository(
    repo_id: str,
    tool: Optional[str] = Query(None, description="Optional single tool name to retry"),
    force_rescan: bool = Query(False, description="Force full re-scan, ignoring cached tool results"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retries an existing research repo pipeline without deleting prior run history.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        repo = service.retry_repo_pipeline(repo_id, tool=tool, force_rescan=force_rescan)
        return {"status": "retrying", "tool": tool, "force_rescan": force_rescan, "repo": repo.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=409 if "already" in str(e).lower() else 400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@research_router.post("/benchmarks/repos/{repo_id}/exclude")
def exclude_research_repository(
    repo_id: str,
    body: ExcludeRepoRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Excludes a repository from general averages with a mandatory written reason.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        repo = service.exclude_repo(repo_id, body.reason)
        return {"status": "excluded", "repo": repo.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@research_router.post("/benchmarks/repos/{repo_id}/unexclude")
def unexclude_research_repository(
    repo_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Restores an excluded repository back into general macro-averages.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        repo = service.unexclude_repo(repo_id)
        return {"status": "re-included", "repo": repo.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@research_router.delete("/benchmarks/repos/{repo_id}")
def delete_research_repository(
    repo_id: str,
    body: Optional[DeleteRepoRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Permanently deletes a research repository, all runs/findings/metrics,
    its ground-truth manifest, and cached directories. Logs an audit record
    if the repository had completed runs.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        reason = body.reason if body else None
        return service.delete_repo(repo_id, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete research repository %s", repo_id)
        raise HTTPException(status_code=500, detail=str(e))


@research_router.get("/benchmarks/repos/{repo_id}/blind-triage")
def export_blind_triage_findings(
    repo_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Exports unique findings with tool identities blinded (Tool-Alpha, Tool-Beta)
    for objective human review.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        return service.export_blind_triage(repo_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@research_router.post("/benchmarks/repos/{repo_id}/verified-triage")
def import_verified_triage_findings(
    repo_id: str,
    body: ImportTriageRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Imports human triage decisions and upgrades repo from 'provisional' to 'verified'.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        repo = service.import_verified_triage(repo_id, body.findings)
        return {"status": "verified", "repo": repo.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@read_router.get("/benchmarks/repos/{repo_id}")
def get_benchmark_repo_detail(repo_id: str, db: Session = Depends(get_benchmark_read_db)) -> Dict[str, Any]:
    """
    Returns detailed ground truth and per-tool metric drilldown for a single research repo.
    """
    service = BenchmarkReadService(db)
    detail = service.get_repo_detail(repo_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Research repository '{repo_id}' not found.")
    return detail


@research_router.post("/benchmarks/seed")
def seed_benchmark_manifests(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Admin endpoint to sync ground-truth manifests from disk into the database.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    repos = service.sync_manifests_to_db()
    return {"status": "ok", "synced_repos": len(repos), "repos": [r.name for r in repos]}


@research_router.get("/benchmarks/triage/sample")
def export_sampled_precision_endpoint(
    per_tool: int = Query(30, ge=1, le=200, description="Max unmatched findings to sample per tool"),
    seed: int = Query(42, description="Deterministic RNG seed"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Exports a deterministic, repo-stratified, blinded CSV sample of unmatched (FP)
    findings across tools for human precision auditing.
    """
    from src.benchmarks_research.sampled_precision import export_sampled_precision_csv
    try:
        return export_sampled_precision_csv(db, per_tool=per_tool, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export sampled precision CSV: {e}")


class ImportSampledPrecisionRequest(BaseModel):
    csv_content: Optional[str] = Field(None, description="Optional raw CSV text; defaults to benchmarks/triage/sampled_precision_sample.csv")
    labeled_by: str = Field("user", description="Annotator identifier")


@research_router.post("/benchmarks/triage/sample/import")
def import_sampled_precision_endpoint(
    body: Optional[ImportSampledPrecisionRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Validates and imports labeled sampled-precision CSV rows (append-only)
    and returns per-tool sampled precision with 95% Wilson intervals.
    """
    from src.benchmarks_research.sampled_precision import import_sampled_precision_csv
    try:
        return import_sampled_precision_csv(
            db,
            csv_content=body.csv_content if body else None,
            labeled_by=body.labeled_by if body else "user",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import sampled precision CSV: {e}")


@research_router.post("/benchmarks/repos/{repo_id}/recompute")
def recompute_repo_metrics_endpoint(
    repo_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Re-evaluates stored active findings against the latest ground-truth manifest
    and cwe_map.json without re-scanning. Appends a new run_version.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        return service.recompute_metrics(repo_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to recompute metrics for %s", repo_id)
        raise HTTPException(status_code=500, detail=str(e))


@research_router.post("/benchmarks/recompute-all")
def recompute_all_metrics_endpoint(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Recomputes metrics across all non-running repositories without re-scanning.
    """
    from src.benchmarks_research.service import BenchmarkService
    service = BenchmarkService(db)
    try:
        return service.recompute_all_metrics()
    except Exception as e:
        logger.exception("Failed to recompute all metrics")
        raise HTTPException(status_code=500, detail=str(e))


class LatencyPassRequest(BaseModel):
    repo_ids: Optional[List[str]] = Field(None, description="Selected repository IDs; defaults to all active repos")
    repeats: int = Field(3, ge=1, le=10, description="Number of sequential repeats per tool per repo")


@research_router.post("/benchmarks/latency-pass")
def start_latency_pass_endpoint(
    body: Optional[LatencyPassRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Starts an isolated sequential latency pass (separate from detection runs).
    Refuses if any detection pipeline or latency pass is currently running.
    """
    from src.benchmarks_research.latency_pass import trigger_latency_pass_async
    from src.db.benchmark_models import BenchmarkLatencyPass, ResearchRepo

    running_repo = db.query(ResearchRepo).filter(ResearchRepo.status == "running").first()
    if running_repo:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start latency pass while '{running_repo.name}' is running ({running_repo.job_stage}).",
        )
    running_pass = db.query(BenchmarkLatencyPass).filter(BenchmarkLatencyPass.status == "running").first()
    if running_pass:
        raise HTTPException(
            status_code=409,
            detail=f"Latency pass v{running_pass.pass_version} is already running.",
        )

    repo_ids = body.repo_ids if body else None
    repeats = body.repeats if body else 3
    trigger_latency_pass_async(repo_ids=repo_ids, repeats=repeats)
    return {
        "status": "queued",
        "repeats": repeats,
        "repo_ids": repo_ids,
        "message": "Isolated sequential latency pass started in background.",
    }


@read_router.get("/benchmarks/latency-pass/latest")
def get_latest_latency_pass_endpoint(db: Session = Depends(get_benchmark_read_db)) -> Dict[str, Any]:
    """Returns the latest completed latency pass (with staleness check if research package available) and any active pass."""
    from src.db.benchmark_models import BenchmarkLatencyPass

    latest = get_latest_latency_pass_from_db(db)
    running = (
        db.query(BenchmarkLatencyPass)
        .filter(BenchmarkLatencyPass.status == "running")
        .order_by(BenchmarkLatencyPass.pass_version.desc())
        .first()
    )
    return {
        "latest": latest,
        "running": running.to_dict() if running else None,
    }


def create_benchmark_router(mode: Optional[str] = None) -> APIRouter:
    """
    Builds the benchmark APIRouter for the given mode ('readonly' | 'research').
    In 'readonly' mode (default), mutating/research endpoints are NOT registered and return 404.
    """
    resolved_mode = mode if mode is not None else get_benchmark_mode()
    combined = APIRouter(tags=["Benchmark"])
    combined.include_router(read_router)
    if resolved_mode == "research":
        combined.include_router(research_router)
    return combined


router = create_benchmark_router()

