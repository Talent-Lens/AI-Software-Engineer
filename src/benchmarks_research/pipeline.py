"""
Automatic Benchmark Pipeline Worker.
Runs end-to-end background ingestion of research repositories:
1. Resolve fix and parent commits (via GitHub or commit SHA)
2. Safe isolated clone
3. Noise-filtered diff extraction and ground-truth generation
4. Dual-commit static scanning across all 4 tools
5. Deterministic 6-metrics computation and isolated DB storage
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.benchmarks_research.cve_resolver import (
    parse_and_validate_github_url,
    resolve_commit_parent,
    resolve_cve_or_advisory,
    ResolverError,
)
from src.benchmarks_research.diff_extractor import DiffExtractor, ExtractedGroundTruth
from src.benchmarks_research.evaluator import BenchmarkEvaluator
from src.benchmarks_research.ground_truth_loader import GroundTruthFinding, GroundTruthLoader, GroundTruthRepo
from src.benchmarks_research.runners.bandit_runner import BanditRunner
from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner
from src.benchmarks_research.runners.codeql_runner import CodeQLRunner
from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner
from src.benchmarks_research.runners.sonarqube_runner import SonarQubeRunner
from src.benchmarks_research.schema import NormalizedFinding, ToolExecutionResult
from src.benchmarks_research.scope import ScopePolicy, build_filtered_source_copy
from src.db.benchmark_models import BenchmarkFinding, BenchmarkMetric, BenchmarkRun, ResearchRepo
from src.db.session import SessionLocal

logger = logging.getLogger("ai_engineer.benchmarks.pipeline")

# Known tuning / training repositories to warn against data leakage
TUNING_REPOS = {
    "stamparm/dsss",
    "we45/vulnerable-flask-app",
}

# Configurable per-tool base timeout (seconds) + LOC scaling (seconds per 1,000 LOC)
TOOL_TIMEOUT_BASE_S: Dict[str, int] = {
    "codeguardian": 120,
    "semgrep": 120,
    "bandit": 120,
    "codeql": 300,
    "sonarqube": 180,
}
TOOL_TIMEOUT_PER_KLOC_S: Dict[str, int] = {
    "codeguardian": 10,
    "semgrep": 15,
    "bandit": 10,
    "codeql": 30,
    "sonarqube": 20,
}


def compute_tool_timeout_s(tool_name: str, loc: Optional[int] = None) -> int:
    """Computes configurable per-tool timeout scaled by repository LOC."""
    env_override = os.environ.get("BENCHMARK_TOOL_TIMEOUT_S")
    if env_override and env_override.isdigit():
        return max(30, int(env_override))
    base = TOOL_TIMEOUT_BASE_S.get(tool_name, 180)
    per_kloc = TOOL_TIMEOUT_PER_KLOC_S.get(tool_name, 15)
    kloc = max(1.0, (loc or 1000) / 1000.0)
    return min(1800, int(base + per_kloc * kloc))


def _run_tool_with_timeout(runner: Any, repo_path: Path, timeout_s: int) -> ToolExecutionResult:
    """Executes a single benchmark runner with an isolated per-tool timeout."""
    tool_name = runner.tool_name
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(runner.run, repo_path)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        logger.warning("Tool %s timed out after %ds on %s", tool_name, timeout_s, repo_path)
        return ToolExecutionResult(
            tool=tool_name,
            tool_version=runner.get_version(),
            duration_s=float(timeout_s),
            findings=[],
            status="timed_out",
            error_message=f"{tool_name} timed out after {timeout_s}s",
        )
    except Exception as err:
        logger.error("Runner %s failed on %s: %s", tool_name, repo_path, err)
        return ToolExecutionResult(
            tool=tool_name,
            tool_version=runner.get_version(),
            duration_s=0.0,
            findings=[],
            status="failed",
            error_message=str(err),
        )
    finally:
        executor.shutdown(wait=False)


_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SAFE_GIT_CONFIG_FLAGS: List[str] = [
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "filter.lfs.smudge=",
    "-c", "filter.lfs.process=",
    "-c", "submodule.recurse=false",
]


def _validate_sha40(sha: str, label: str = "commit") -> str:
    """Validates that a commit SHA is a strict 40-character hexadecimal string."""
    s = (sha or "").strip()
    if not _SHA40_RE.match(s):
        raise ValueError(f"Invalid {label} SHA '{sha}': must be a 40-character hex commit hash.")
    return s.lower()


def _safe_git_env() -> Dict[str, str]:
    """Returns subprocess environment with git interactive prompts and LFS smudge disabled."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    return env


def compute_fetch_timeout_s(loc: Optional[int] = None) -> int:
    """Configurable git fetch timeout scaled by repository LOC."""
    env_override = os.environ.get("BENCHMARK_GIT_TIMEOUT_S")
    if env_override and env_override.isdigit():
        return max(30, int(env_override))
    kloc = max(1.0, (loc or 5000) / 1000.0)
    return min(900, max(120, int(120 + 10 * kloc)))


def _dir_size_bytes(path: Path) -> int:
    """Computes total size on disk (bytes) of a directory tree."""
    total = 0
    for root, _, files in os.walk(str(path)):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _get_bare_cache_dir(repo_url: str) -> Tuple[Path, str, str]:
    """
    Returns (bare_cache_dir, canonical_origin_url, repo_display_slug) keyed strictly by owner/repo.
    Verifies any existing cache's remote.origin.url matches canonical_origin_url so caches
    can never be reused across different repositories.
    """
    owner, repo_slug = parse_and_validate_github_url(repo_url)
    canonical_url = f"https://github.com/{owner}/{repo_slug}"
    base_dir = Path(__file__).resolve().parents[2]
    cache_root = base_dir / "data" / "benchmark_bare_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_dir = cache_root / f"{owner.lower()}__{repo_slug.lower()}.git"

    env = _safe_git_env()
    if cache_dir.exists():
        proc = subprocess.run(
            ["git", "--git-dir", str(cache_dir), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=15,
        )
        existing_origin = (proc.stdout or "").strip().rstrip("/").removesuffix(".git").lower()
        if proc.returncode != 0 or existing_origin != canonical_url.lower():
            logger.warning(
                "Bare cache origin mismatch at %s (found '%s', expected '%s'); recreating.",
                cache_dir, existing_origin, canonical_url,
            )
            _robust_rmtree(cache_dir)

    if not cache_dir.exists():
        subprocess.run(
            ["git", *_SAFE_GIT_CONFIG_FLAGS, "init", "--bare", str(cache_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=30,
        )
        subprocess.run(
            ["git", "--git-dir", str(cache_dir), "remote", "add", "origin", canonical_url],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=15,
        )

    return cache_dir, canonical_url, f"{owner}/{repo_slug}"


def _commit_in_repo(git_dir_args: List[str], sha: str, env: Dict[str, str]) -> bool:
    proc = subprocess.run(
        ["git", *git_dir_args, "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=15,
    )
    return proc.returncode == 0


def _fetch_sha_into_bare_cache(
    cache_dir: Path,
    repo_display: str,
    sha: str,
    timeout_s: int,
    max_retries: int = 3,
    fallback_fix_sha: Optional[str] = None,
) -> Tuple[float, str]:
    """
    Fetches a single 40-char SHA into the bare cache with:
      1) --depth=1 origin <sha>
      2) --depth=2 origin <fallback_fix_sha> (if fetching parent failed)
      3) --filter=blob:none origin <sha>
    Retries up to max_retries with exponential backoff; raises clear timeout message on failure.
    Returns (elapsed_s, strategy_used).
    """
    env = _safe_git_env()
    if _commit_in_repo(["--git-dir", str(cache_dir)], sha, env):
        return 0.0, "bare-cache-hit"

    strategies: List[Tuple[str, List[str]]] = [
        ("depth-1-sha", ["fetch", "--depth=1", "--no-tags", "origin", sha]),
    ]
    if fallback_fix_sha and fallback_fix_sha != sha:
        strategies.append(
            ("depth-2-from-fix", ["fetch", "--depth=2", "--no-tags", "origin", fallback_fix_sha])
        )
    strategies.append(
        ("blobless-partial", ["fetch", "--filter=blob:none", "--no-tags", "origin", sha])
    )

    t_start = time.perf_counter()
    last_err = ""
    for strat_name, fetch_args in strategies:
        for attempt in range(1, max_retries + 1):
            try:
                proc = subprocess.run(
                    ["git", *_SAFE_GIT_CONFIG_FLAGS, "--git-dir", str(cache_dir), *fetch_args],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                    timeout=timeout_s,
                )
                if proc.returncode == 0 and _commit_in_repo(["--git-dir", str(cache_dir)], sha, env):
                    return round(time.perf_counter() - t_start, 3), strat_name
                last_err = (proc.stderr or proc.stdout or "").strip()
                # If server rejected unadvertised SHA / shallow object, move to next strategy immediately
                if "not our ref" in last_err.lower() or "couldn't find remote ref" in last_err.lower() or "server does not allow request" in last_err.lower():
                    break
            except subprocess.TimeoutExpired:
                last_err = f"Network timeout while downloading {repo_display} (attempt {attempt} of {max_retries})"
                logger.warning("%s [strategy=%s]", last_err, strat_name)
                if attempt == max_retries and strat_name == strategies[-1][0]:
                    raise RuntimeError(last_err)
            if attempt < max_retries:
                time.sleep(2 * attempt)

    if "Network timeout while downloading" in last_err:
        raise RuntimeError(last_err)
    raise RuntimeError(f"Git fetch for {repo_display} ({sha[:8]}) failed after {max_retries} attempts: {last_err[:300]}")


def _safe_git_clone_and_checkout(
    repo_url: str,
    target_dir: Path,
    commit_sha: str,
    max_retries: int = 3,
    fix_sha: Optional[str] = None,
    loc: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Safely fetches ONLY the needed commit(s) into a per-repo bare cache, initializes an
    empty repo in target_dir, fetches locally from the bare cache, and checks out commit_sha
    with hooks, LFS smudge, and submodules disabled.
    Returns timing and disk-size telemetry.
    """
    parent_sha = _validate_sha40(commit_sha, "parent")
    clean_fix_sha = _validate_sha40(fix_sha, "fix") if fix_sha else None
    timeout_s = compute_fetch_timeout_s(loc)
    env = _safe_git_env()

    cache_dir, _, repo_display = _get_bare_cache_dir(repo_url)

    # Fetch needed commits into persistent bare cache (network)
    parent_fetch_s, parent_strategy = _fetch_sha_into_bare_cache(
        cache_dir, repo_display, parent_sha, timeout_s=timeout_s, max_retries=max_retries, fallback_fix_sha=clean_fix_sha
    )
    fix_fetch_s = 0.0
    fix_strategy = "skipped"
    if clean_fix_sha:
        fix_fetch_s, fix_strategy = _fetch_sha_into_bare_cache(
            cache_dir, repo_display, clean_fix_sha, timeout_s=timeout_s, max_retries=max_retries
        )

    # Initialize isolated empty repo in target_dir and pull only the two SHAs from local bare cache
    target_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", *_SAFE_GIT_CONFIG_FLAGS, "init", str(target_dir)],
        capture_output=True, text=True, env=env, check=True, timeout=30,
    )
    subprocess.run(
        ["git", "-C", str(target_dir), "remote", "add", "origin", str(cache_dir)],
        capture_output=True, text=True, env=env, check=True, timeout=15,
    )

    local_shas = [parent_sha] + ([clean_fix_sha] if clean_fix_sha and clean_fix_sha != parent_sha else [])
    for l_sha in local_shas:
        proc = subprocess.run(
            ["git", *_SAFE_GIT_CONFIG_FLAGS, "-c", "protocol.file.allow=always", "-C", str(target_dir), "fetch", "--depth=1", "--no-tags", "origin", l_sha],
            capture_output=True, text=True, env=env, check=False, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Local cache fetch failed for {l_sha[:8]}: {proc.stderr or proc.stdout}")

    t_co = time.perf_counter()
    co_proc = subprocess.run(
        ["git", *_SAFE_GIT_CONFIG_FLAGS, "-C", str(target_dir), "checkout", "--force", parent_sha],
        capture_output=True, text=True, env=env, check=False, timeout=60,
    )
    if co_proc.returncode != 0:
        raise RuntimeError(f"Git checkout {parent_sha} failed: {co_proc.stderr or co_proc.stdout}")
    parent_checkout_s = round(time.perf_counter() - t_co, 3)
    parent_checkout_bytes = _dir_size_bytes(target_dir)

    return {
        "cache_dir": str(cache_dir),
        "timeout_s": timeout_s,
        "parent_sha": parent_sha,
        "parent_fetch_s": parent_fetch_s,
        "parent_strategy": parent_strategy,
        "parent_checkout_s": parent_checkout_s,
        "parent_checkout_bytes": parent_checkout_bytes,
        "fix_sha": clean_fix_sha,
        "fix_fetch_s": fix_fetch_s,
        "fix_strategy": fix_strategy,
    }


def _robust_rmtree(path: Path) -> None:
    """Safely cleans up directories on Windows (clearing read-only bits)."""
    import stat
    if not path.exists():
        return
    for root, dirs, files in os.walk(str(path)):
        for f in files:
            p = os.path.join(root, f)
            try:
                os.chmod(p, stat.S_IWRITE)
            except Exception:
                pass
    try:
        shutil.rmtree(str(path), ignore_errors=True)
    except Exception as e:
        logger.debug("Sandbox cleanup warning: %s", e)


def get_runner_ruleset_id(runner: BaseBenchmarkRunner) -> str:
    """Returns a deterministic ruleset/query-suite identifier for cache keying."""
    name = runner.tool_name
    if name == "codeguardian":
        return "SecurityASTScanner:SAST-*"
    if name == "semgrep":
        rules_path = getattr(runner, "rules_path", None)
        if rules_path and Path(rules_path).exists():
            commit_file = Path(rules_path) / "PINNED_COMMIT.txt"
            if commit_file.exists():
                return f"semgrep-rules:{commit_file.read_text(encoding='utf-8').strip()[:12]}"
        return f"semgrep:{getattr(runner, 'docker_image', 'default')}"
    if name == "codeql":
        return f"{getattr(runner, 'query_suite', 'default')}"
    if name == "bandit":
        return "bandit:security_only:-s B101"
    if name == "sonarqube":
        return "sonarqube:VULNERABILITY,SECURITY_HOTSPOT"
    return name


def build_run_plan(
    db: Session,
    repo: ResearchRepo,
    target_tools: Optional[List[str]] = None,
    force_rescan: bool = False,
) -> Dict[str, Any]:
    """
    Computes which tools can reuse a cached result keyed by
    (repo, commit SHA, tool, tool version, scope-policy hash, ruleset)
    and which tools will re-scan.
    """
    from src.benchmarks_research.scope import compute_scope_policy_hash

    scope_policy = ScopePolicy.from_override(getattr(repo, "scope_override", None))
    scope_hash = compute_scope_policy_hash(scope_policy)
    vuln_sha = repo.pinned_sha or repo.parent_commit or ""
    clean_sha = repo.clean_sha or repo.fix_commit or ""

    all_runners = [
        CodeGuardianRunner(),
        SemgrepRunner(),
        CodeQLRunner(),
        SonarQubeRunner(),
        BanditRunner(),
    ]
    selected = [r for r in all_runners if r.tool_name in target_tools] if target_tools else all_runners

    prior_runs = (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.repo_id == repo.id, BenchmarkRun.status == "completed")
        .order_by(BenchmarkRun.run_version.desc())
        .all()
    )

    plan_tools: List[Dict[str, Any]] = []
    reuse_list: List[str] = []
    rescan_list: List[str] = []

    for runner in selected:
        t_name = runner.tool_name
        t_ver = runner.get_version()
        ruleset_id = get_runner_ruleset_id(runner)

        matched_run: Optional[BenchmarkRun] = None
        if not force_rescan and vuln_sha:
            for pr in prior_runs:
                if pr.tool != t_name or pr.tool_version != t_ver:
                    continue
                meta = pr.run_metadata or {}
                if (
                    meta.get("commit_sha") == vuln_sha
                    and meta.get("clean_sha", "") == clean_sha
                    and meta.get("scope_policy_hash") == scope_hash
                    and meta.get("ruleset_id") == ruleset_id
                ):
                    matched_run = pr
                    break

        if matched_run is not None:
            meta = matched_run.run_metadata or {}
            orig_ts = meta.get("original_timestamp") or (
                matched_run.started_at.isoformat() if matched_run.started_at else None
            )
            orig_dur = meta.get("original_duration_s")
            if orig_dur is None:
                orig_dur = round(matched_run.duration_s or 0.0, 4)
            reuse_list.append(t_name)
            plan_tools.append({
                "tool": t_name,
                "action": "reuse",
                "reason": f"cached (v{t_ver}, same commit/scope/ruleset)",
                "cached_run_id": matched_run.id,
                "original_timestamp": orig_ts,
                "original_duration_s": orig_dur,
                "tool_version": t_ver,
                "scope_policy_hash": scope_hash,
                "ruleset_id": ruleset_id,
            })
        else:
            reason = "force full re-scan" if force_rescan else "no matching cached run (commit/version/scope/ruleset)"
            rescan_list.append(t_name)
            plan_tools.append({
                "tool": t_name,
                "action": "rescan",
                "reason": reason,
                "cached_run_id": None,
                "tool_version": t_ver,
                "scope_policy_hash": scope_hash,
                "ruleset_id": ruleset_id,
            })

    return {
        "repo_id": repo.id,
        "repo_name": repo.name,
        "force_rescan": force_rescan,
        "scope_policy_hash": scope_hash,
        "reuse": reuse_list,
        "rescan": rescan_list,
        "tools": plan_tools,
    }


class BenchmarkPipelineJob:
    """Executes the one-step automatic research repo pipeline in the background."""

    def __init__(self, repo_id: str, target_tools: Optional[List[str]] = None, force_rescan: bool = False):
        self.repo_id = repo_id
        self.target_tools = [t.lower() for t in target_tools] if target_tools else None
        self.force_rescan = force_rescan
        self.loader = GroundTruthLoader()
        self.evaluator = BenchmarkEvaluator(loader=self.loader)
        self.diff_extractor = DiffExtractor()

    def update_stage(
        self,
        db: Session,
        repo: ResearchRepo,
        stage: str,
        progress: float,
        error: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Atomically updates repository job stage and progress in database."""
        repo.job_stage = stage
        repo.job_progress = progress
        repo.last_heartbeat = datetime.now(timezone.utc)
        if error:
            repo.job_error = error
            repo.status = "failed"
        if notes:
            repo.notes = notes
        db.commit()

    def run_sync(self) -> None:
        """Main synchronous entry point intended for background threads."""
        db = SessionLocal()
        try:
            repo = db.query(ResearchRepo).filter(ResearchRepo.id == self.repo_id).first()
            if not repo:
                logger.error("Repository %s not found in DB.", self.repo_id)
                return

            self._execute_pipeline(db, repo)
        except Exception as e:
            logger.exception("Benchmark pipeline failed for %s", self.repo_id)
            try:
                repo = db.query(ResearchRepo).filter(ResearchRepo.id == self.repo_id).first()
                if repo:
                    from src.benchmarks_research.scope import get_required_tools
                    req = set(get_required_tools())
                    has_completed = any(
                        r.tool in req and r.status == "completed"
                        for r in db.query(BenchmarkRun).filter(
                            BenchmarkRun.repo_id == repo.id, BenchmarkRun.is_superseded == False
                        ).all()
                    )
                    if has_completed:
                        repo.status = "partial"
                        repo.job_stage = "partial"
                        repo.job_error = str(e)
                        repo.last_heartbeat = datetime.now(timezone.utc)
                        db.commit()
                    else:
                        self.update_stage(db, repo, stage="failed", progress=0.0, error=str(e))
            except Exception:
                pass
        finally:
            db.close()

    def _execute_pipeline(self, db: Session, repo: ResearchRepo) -> None:
        owner, repo_slug = parse_and_validate_github_url(repo.url)
        full_slug = f"{owner}/{repo_slug}".lower()

        # Check tuning repo warning
        is_tuning_repo = full_slug in TUNING_REPOS
        if is_tuning_repo:
            warning_msg = f"WARNING: {full_slug} is in tuning_repos. Results may exhibit overfitting/leakage."
            repo.notes = f"{repo.notes or ''}\n{warning_msg}".strip()

        # ── STAGE 1: RESOLVING ───────────────────────────────────────────────
        self.update_stage(db, repo, stage="resolving", progress=0.1)

        from src.benchmarks_research.scope import validate_and_normalize_cwe
        is_intentionally_vuln = (repo.repo_type == "intentionally_vulnerable" and bool(repo.ground_truth_path))
        if is_intentionally_vuln:
            parent_commit = repo.pinned_sha or repo.parent_commit
            fix_commit = None
            cwe = None
        else:
            fix_commit = repo.fix_commit or repo.clean_sha
            parent_commit = repo.parent_commit or repo.pinned_sha
            cwe = validate_and_normalize_cwe(getattr(repo, "user_cwe", None), strict=False)

            if not fix_commit or not parent_commit:
                if fix_commit and not parent_commit:
                    parent_commit = resolve_commit_parent(owner, repo_slug, fix_commit)
                    if repo.cve_id and not cwe:
                        try:
                            res = resolve_cve_or_advisory(owner, repo_slug, repo.cve_id)
                            cwe = res.get("cwe")
                        except Exception:
                            pass
                else:
                    identifier = repo.cve_id or fix_commit or parent_commit
                    if not identifier:
                        raise ResolverError("No CVE ID or fix commit SHA specified.")
                    res = resolve_cve_or_advisory(owner, repo_slug, identifier)
                    fix_commit = res["fix_commit"]
                    parent_commit = res["parent_commit"]
                    cwe = cwe or res["cwe"]
                    repo.cve_id = res.get("cve_id") or repo.cve_id

            repo.fix_commit = fix_commit
            repo.clean_sha = fix_commit
            repo.parent_commit = parent_commit
            repo.pinned_sha = parent_commit
            db.commit()

            # Check for duplicates in DB (same repo + parent + fix pair)
            dup = (
                db.query(ResearchRepo)
                .filter(
                    ResearchRepo.id != repo.id,
                    ResearchRepo.url == repo.url,
                    ResearchRepo.pinned_sha == parent_commit,
                    ResearchRepo.clean_sha == fix_commit,
                )
                .first()
            )
            if dup:
                raise ResolverError(
                    f"Duplicate benchmark repository detected: {repo.name} at {parent_commit[:8]}..{fix_commit[:8]} "
                    f"already exists in research_repos (ID: {dup.id})."
                )

        # ── STAGE 2: CLONING & LABELING ──────────────────────────────────────
        self.update_stage(db, repo, stage="cloning", progress=0.25)
        tmp_dir = Path(tempfile.mkdtemp(prefix="cg_bench_pipe_"))

        try:
            # Shallow-fetch only the parent & fix commits via persistent bare cache, checkout parent
            t_clone0 = time.perf_counter()
            clone_info = _safe_git_clone_and_checkout(
                repo.url,
                tmp_dir,
                parent_commit,
                fix_sha=fix_commit,
                loc=repo.loc,
            )
            clone_or_fetch_s = round(time.perf_counter() - t_clone0, 4)

            self.update_stage(db, repo, stage="labeling", progress=0.4)
            if is_intentionally_vuln:
                gt_repo = self.loader.load_manifest(Path(repo.ground_truth_path))
                repo.loc = gt_repo.loc
                repo.language = gt_repo.language
                db.commit()
            else:
                extracted = self.diff_extractor.extract_from_git_repo(
                    repo_dir=tmp_dir,
                    parent_sha=parent_commit,
                    fix_sha=fix_commit,
                    cve_id=repo.cve_id,
                    cwe=cwe,
                )

                repo.loc = extracted.loc
                repo.language = extracted.language
                repo.ignored_candidates = extracted.ignored_candidates

                if extracted.needs_attention:
                    repo.status = "needs_attention"
                    repo.job_stage = "needs_attention"
                    repo.job_error = extracted.attention_reason
                    repo.is_excluded = True
                    repo.exclusion_reason = f"Automatic labeling needs attention: {extracted.attention_reason}"
                    db.commit()
                    logger.warning("Repo %s marked needs_attention: %s", repo.name, extracted.attention_reason)
                    return

                # Never overwrite existing ground-truth manifests; reuse versioned manifest if already set
                existing_gt = Path(repo.ground_truth_path) if repo.ground_truth_path else None
                if existing_gt and existing_gt.exists() and ".v" in existing_gt.name:
                    gt_repo = self.loader.load_manifest(existing_gt)
                else:
                    manifest_filename = f"{owner}_{repo_slug}_{fix_commit[:8]}.json"
                    manifest_path = Path("benchmarks/ground_truth") / manifest_filename
                    if manifest_path.exists():
                        ver = 2
                        while (Path("benchmarks/ground_truth") / f"{owner}_{repo_slug}_{fix_commit[:8]}.v{ver}.json").exists():
                            ver += 1
                        manifest_filename = f"{owner}_{repo_slug}_{fix_commit[:8]}.v{ver}.json"
                        manifest_path = Path("benchmarks/ground_truth") / manifest_filename
                    manifest_path.parent.mkdir(parents=True, exist_ok=True)

                    gt_manifest_data = {
                        "repo_name": repo.name,
                        "url": repo.url,
                        "pinned_vulnerable_sha": parent_commit,
                        "pinned_clean_sha": fix_commit,
                        "language": extracted.language,
                        "loc": extracted.loc,
                        "description": f"Auto-extracted benchmark for {repo.cve_id or fix_commit[:8]}",
                        "label_quality": repo.label_quality or "provisional",
                        "labeled_findings": extracted.labeled_findings,
                        "clean_negative_regions": extracted.clean_negative_regions,
                    }
                    with open(manifest_path, "w", encoding="utf-8") as f:
                        json.dump(gt_manifest_data, f, indent=2)

                    repo.ground_truth_path = f"benchmarks/ground_truth/{manifest_filename}"
                    db.commit()

                    gt_repo = self.loader.load_manifest(manifest_path)

            # ── STAGE 3: UNIFIED FILTERED SOURCE COPY & SCANNING ─────────────
            self.update_stage(db, repo, stage="scanning", progress=0.55)
            from src.benchmarks_research.scope import compute_scope_policy_hash
            scope_policy = ScopePolicy.from_override(getattr(repo, "scope_override", None))
            scope_hash = compute_scope_policy_hash(scope_policy)
            labeled_files = [gt.file for gt in gt_repo.labeled_findings]

            run_plan = build_run_plan(db, repo, target_tools=self.target_tools, force_rescan=self.force_rescan)
            plan_by_tool = {item["tool"]: item for item in run_plan["tools"]}
            all_runners = [
                CodeGuardianRunner(),
                SemgrepRunner(),
                CodeQLRunner(),
                SonarQubeRunner(),
                BanditRunner(),
            ]
            runners = (
                [r for r in all_runners if r.tool_name in self.target_tools]
                if self.target_tools
                else all_runners
            )

            from sqlalchemy import func
            max_ver = (
                db.query(func.max(BenchmarkRun.run_version))
                .filter(BenchmarkRun.repo_id == repo.id)
                .scalar()
                or 0
            )
            next_version = int(max_ver) + 1
            is_dual_commit = bool(repo.repo_type != "intentionally_vulnerable" and fix_commit)

            stage_timings: Dict[str, Any] = {
                "clone_or_fetch_s": clone_or_fetch_s,
                "parent_fetch_s": clone_info.get("parent_fetch_s"),
                "fix_fetch_s": clone_info.get("fix_fetch_s"),
                "parent_strategy": clone_info.get("parent_strategy"),
                "filtered_copy_vuln_s": 0.0,
                "filtered_copy_clean_s": None,
                "tools": {},
                "evaluator_s": 0.0,
            }

            filtered_vuln_dir = Path(tempfile.mkdtemp(prefix="cg_bench_scope_vuln_"))
            filtered_clean_dir: Optional[Path] = None
            try:
                t_fc_v = time.perf_counter()
                vuln_scope_info = build_filtered_source_copy(
                    tmp_dir, filtered_vuln_dir, scope_policy, labeled_files=labeled_files
                )
                stage_timings["filtered_copy_vuln_s"] = round(time.perf_counter() - t_fc_v, 4)
                in_scope_loc = max(vuln_scope_info["in_scope_loc"], 1)
                repo.loc = in_scope_loc
                gt_repo.loc = in_scope_loc
                db.commit()
                logger.info(
                    "Unified scope (%s vuln): %d in-scope files (%d LOC), %d excluded files",
                    repo.name, vuln_scope_info["in_scope_files"], in_scope_loc, vuln_scope_info["excluded_files"],
                )

                tool_vuln_results: Dict[str, ToolExecutionResult] = {}
                tool_clean_results: Dict[str, ToolExecutionResult] = {}
                persisted_runs: Dict[str, BenchmarkRun] = {}
                cached_tools: set[str] = set()

                # 0. Reuse cached results when key matches & force_rescan is False
                for runner in runners:
                    t_name = runner.tool_name
                    p_item = plan_by_tool.get(t_name, {})
                    if p_item.get("action") == "reuse" and p_item.get("cached_run_id"):
                        cached_run = db.query(BenchmarkRun).filter(BenchmarkRun.id == p_item["cached_run_id"]).first()
                        if cached_run is not None:
                            cached_tools.add(t_name)
                            db.query(BenchmarkRun).filter(
                                BenchmarkRun.repo_id == repo.id,
                                BenchmarkRun.tool == t_name,
                                BenchmarkRun.is_superseded == False,
                            ).update({"is_superseded": True})
                            db.query(BenchmarkMetric).filter(
                                BenchmarkMetric.repo_id == repo.id,
                                BenchmarkMetric.tool == t_name,
                                BenchmarkMetric.is_superseded == False,
                            ).update({"is_superseded": True})
                            db.flush()

                            c_meta = dict(cached_run.run_metadata or {})
                            c_meta["cached"] = True
                            c_meta["cached_from_run_id"] = cached_run.id
                            c_meta["original_timestamp"] = p_item.get("original_timestamp")
                            c_meta["original_duration_s"] = p_item.get("original_duration_s")
                            c_meta["latency_measurement_mode"] = c_meta.get("latency_measurement_mode", "isolated_sequential")
                            new_run = BenchmarkRun(
                                repo_id=repo.id,
                                tool=t_name,
                                tool_version=cached_run.tool_version,
                                duration_s=cached_run.duration_s,
                                raw_output_path=cached_run.raw_output_path,
                                status=cached_run.status,
                                error_message=cached_run.error_message,
                                run_metadata=c_meta,
                                run_version=next_version,
                                is_superseded=False,
                            )
                            db.add(new_run)
                            db.flush()
                            persisted_runs[t_name] = new_run

                            old_findings = db.query(BenchmarkFinding).filter(BenchmarkFinding.run_id == cached_run.id).all()
                            reused_nfs: List[NormalizedFinding] = []
                            for of in old_findings:
                                nf = NormalizedFinding(
                                    tool=of.tool,
                                    file_path=of.file_path,
                                    line_start=of.line_start,
                                    line_end=of.line_end,
                                    cwe=of.cwe,
                                    severity=of.severity or "MEDIUM",
                                    rule_id=of.rule_id or "",
                                    raw_payload=of.raw_finding,
                                )
                                reused_nfs.append(nf)
                                db.add(
                                    BenchmarkFinding(
                                        run_id=new_run.id,
                                        repo_id=repo.id,
                                        tool=t_name,
                                        file_path=of.file_path,
                                        line_start=of.line_start,
                                        line_end=of.line_end,
                                        cwe=of.cwe,
                                        normalized_cwe=of.normalized_cwe,
                                        severity=of.severity,
                                        rule_id=of.rule_id,
                                        match_result=of.match_result,
                                        matched_ground_truth_id=of.matched_ground_truth_id,
                                        raw_finding=of.raw_finding,
                                    )
                                )

                            old_metric = (
                                db.query(BenchmarkMetric)
                                .filter(
                                    BenchmarkMetric.repo_id == repo.id,
                                    BenchmarkMetric.tool == t_name,
                                    BenchmarkMetric.run_version == cached_run.run_version,
                                )
                                .first()
                            )
                            if old_metric is not None:
                                clean_fp = int((old_metric.counts_json or {}).get("clean_fp", 0))
                                t_ev0 = time.perf_counter()
                                summary = self.evaluator.evaluate(
                                    ground_truth=gt_repo,
                                    vulnerable_findings=reused_nfs,
                                    clean_findings=[NormalizedFinding(tool=t_name, file_path="c.py", line_start=1, line_end=1, cwe="", severity="LOW", rule_id="C")] * clean_fp if is_dual_commit else None,
                                    duration_s=cached_run.duration_s or 0.0,
                                )
                                stage_timings["evaluator_s"] = round(stage_timings["evaluator_s"] + (time.perf_counter() - t_ev0), 4)
                                db.add(
                                    BenchmarkMetric(
                                        repo_id=repo.id,
                                        tool=t_name,
                                        tool_version=cached_run.tool_version,
                                        precision=summary.precision,
                                        recall=summary.recall,
                                        false_positive_rate=summary.false_positive_rate,
                                        localization_accuracy=summary.localization_accuracy,
                                        classification_accuracy=summary.classification_accuracy,
                                        scan_latency=summary.scan_latency,
                                        counts_json=summary.counts,
                                        run_version=next_version,
                                        is_superseded=False,
                                    )
                                )
                            db.commit()

                uncached_runners = [r for r in runners if r.tool_name not in cached_tools]

                # 1. Scan Vulnerable Commit sequentially (isolated) & persist each tool immediately
                for idx, runner in enumerate(uncached_runners):
                    tool_name = runner.tool_name
                    tool_timeout_s = compute_tool_timeout_s(tool_name, repo.loc)
                    logger.info("Scanning %s (vulnerable commit, scoped) with %s (timeout=%ds)", repo.name, tool_name, tool_timeout_s)
                    v_res = _run_tool_with_timeout(runner, filtered_vuln_dir, tool_timeout_s)
                    tool_vuln_results[tool_name] = v_res

                    # Supersede prior active runs/metrics for ONLY this (repo_id, tool)
                    db.query(BenchmarkRun).filter(
                        BenchmarkRun.repo_id == repo.id,
                        BenchmarkRun.tool == tool_name,
                        BenchmarkRun.is_superseded == False,
                    ).update({"is_superseded": True})
                    db.query(BenchmarkMetric).filter(
                        BenchmarkMetric.repo_id == repo.id,
                        BenchmarkMetric.tool == tool_name,
                        BenchmarkMetric.is_superseded == False,
                    ).update({"is_superseded": True})
                    db.flush()

                    merged_meta = dict(v_res.metadata or {})
                    merged_meta["commit_sha"] = parent_commit
                    merged_meta["clean_sha"] = fix_commit or ""
                    merged_meta["scope_policy_hash"] = scope_hash
                    merged_meta["ruleset_id"] = get_runner_ruleset_id(runner)
                    merged_meta["cached"] = False
                    merged_meta["original_timestamp"] = datetime.now(timezone.utc).isoformat()
                    merged_meta["original_duration_s"] = round(v_res.duration_s, 4)
                    merged_meta["latency_measurement_mode"] = "isolated_sequential"
                    merged_meta["vuln_duration_s"] = round(v_res.duration_s, 4)
                    merged_meta["clean_duration_s"] = None
                    merged_meta["total_duration_s"] = round(v_res.duration_s, 4)
                    merged_meta["latency_basis"] = "vulnerable_commit_only"

                    t_stage_entry: Dict[str, Any] = {"vuln_duration_s": round(v_res.duration_s, 4)}
                    if tool_name == "codeql":
                        t_stage_entry["vuln_db_build_s"] = merged_meta.get("db_build_time_s")
                        t_stage_entry["vuln_analysis_s"] = merged_meta.get("analysis_time_s")
                    elif tool_name == "semgrep":
                        t_stage_entry["vuln_container_startup_s"] = merged_meta.get("container_startup_s")
                        t_stage_entry["vuln_scan_s"] = merged_meta.get("scan_time_s")
                    stage_timings["tools"][tool_name] = t_stage_entry

                    run_record = BenchmarkRun(
                        repo_id=repo.id,
                        tool=tool_name,
                        tool_version=v_res.tool_version,
                        duration_s=v_res.duration_s,
                        status=v_res.status,
                        error_message=v_res.error_message,
                        run_metadata=merged_meta,
                        run_version=next_version,
                        is_superseded=False,
                    )
                    db.add(run_record)
                    db.flush()
                    persisted_runs[tool_name] = run_record

                    finding_matches, _, _ = self.evaluator.match_findings(gt_repo, v_res.findings)
                    for f_idx, f in enumerate(v_res.findings):
                        cwe_norm = self.loader.normalize_cwe(f.cwe)
                        m_info = finding_matches.get(f_idx)
                        match_res = m_info[0] if m_info else "FP"
                        matched_id = m_info[1] if m_info else None
                        line_dist = m_info[2] if m_info else None
                        cwe_matched = m_info[3] if m_info else False
                        db.add(
                            BenchmarkFinding(
                                run_id=run_record.id,
                                repo_id=repo.id,
                                tool=tool_name,
                                file_path=f.file_path,
                                line_start=f.line_start,
                                line_end=f.line_end,
                                cwe=f.cwe,
                                normalized_cwe=cwe_norm,
                                severity=f.severity,
                                rule_id=f.rule_id,
                                match_result=match_res,
                                matched_ground_truth_id=matched_id,
                                line_distance=line_dist,
                                cwe_matched=cwe_matched,
                                raw_finding=f.raw_payload,
                            )
                        )

                    if not is_dual_commit and v_res.status == "completed":
                        t_ev0 = time.perf_counter()
                        metrics_summary = self.evaluator.evaluate(
                            ground_truth=gt_repo,
                            vulnerable_findings=v_res.findings,
                            clean_findings=None,
                            duration_s=v_res.duration_s,
                        )
                        stage_timings["evaluator_s"] = round(stage_timings["evaluator_s"] + (time.perf_counter() - t_ev0), 4)
                        db.add(
                            BenchmarkMetric(
                                repo_id=repo.id,
                                tool=tool_name,
                                tool_version=v_res.tool_version,
                                precision=metrics_summary.precision,
                                recall=metrics_summary.recall,
                                false_positive_rate=metrics_summary.false_positive_rate,
                                localization_accuracy=metrics_summary.localization_accuracy,
                                classification_accuracy=metrics_summary.classification_accuracy,
                                scan_latency=metrics_summary.scan_latency,
                                counts_json=metrics_summary.counts,
                                run_version=next_version,
                                is_superseded=False,
                            )
                        )
                    db.commit()
                    self.update_stage(db, repo, stage="scanning", progress=0.55 + 0.15 * ((idx + 1) / max(len(uncached_runners), 1)))

                # 2. Checkout and Scan Clean Commit sequentially (isolated) & finalize each tool immediately
                if is_dual_commit and uncached_runners:
                    self.update_stage(db, repo, stage="scanning_clean", progress=0.75)
                    checkout_clean = subprocess.run(
                        ["git", *_SAFE_GIT_CONFIG_FLAGS, "checkout", "--force", fix_commit],
                        cwd=str(tmp_dir),
                        env=_safe_git_env(),
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )
                    if checkout_clean.returncode == 0:
                        filtered_clean_dir = Path(tempfile.mkdtemp(prefix="cg_bench_scope_clean_"))
                        t_fc_c = time.perf_counter()
                        clean_scope_info = build_filtered_source_copy(
                            tmp_dir, filtered_clean_dir, scope_policy
                        )
                        stage_timings["filtered_copy_clean_s"] = round(time.perf_counter() - t_fc_c, 4)
                        logger.info(
                            "Unified scope (%s clean): %d in-scope files (%d LOC), %d excluded files",
                            repo.name, clean_scope_info["in_scope_files"], clean_scope_info["in_scope_loc"], clean_scope_info["excluded_files"],
                        )
                        for idx, runner in enumerate(uncached_runners):
                            tool_name = runner.tool_name
                            tool_timeout_s = compute_tool_timeout_s(tool_name, repo.loc)
                            logger.info("Scanning %s (clean commit, scoped) with %s (timeout=%ds)", repo.name, tool_name, tool_timeout_s)
                            c_res = _run_tool_with_timeout(runner, filtered_clean_dir, tool_timeout_s)
                            tool_clean_results[tool_name] = c_res

                            v_res = tool_vuln_results[tool_name]
                            run_record = persisted_runs[tool_name]
                            effective_status = v_res.status
                            effective_error = v_res.error_message
                            if v_res.status == "completed" and c_res.status in ("timed_out", "failed"):
                                effective_status = c_res.status
                                effective_error = f"Clean commit {c_res.status}: {c_res.error_message or ''}".strip()

                            meta = dict(run_record.run_metadata or {})
                            meta["clean_duration_s"] = round(c_res.duration_s, 4)
                            meta["total_duration_s"] = round(v_res.duration_s + c_res.duration_s, 4)
                            if c_res.metadata:
                                meta["clean_scan_proof"] = {
                                    k: c_res.metadata.get(k)
                                    for k in ("files_scanned", "lines_scanned", "rules_loaded", "db_python_files", "db_functions")
                                    if k in c_res.metadata
                                }
                                if tool_name == "codeql":
                                    meta["clean_db_build_time_s"] = c_res.metadata.get("db_build_time_s")
                                    meta["clean_analysis_time_s"] = c_res.metadata.get("analysis_time_s")
                                elif tool_name == "semgrep":
                                    meta["clean_container_startup_s"] = c_res.metadata.get("container_startup_s")
                                    meta["clean_scan_time_s"] = c_res.metadata.get("scan_time_s")

                            t_stage_entry = stage_timings["tools"].setdefault(tool_name, {})
                            t_stage_entry["clean_duration_s"] = round(c_res.duration_s, 4)
                            t_stage_entry["total_duration_s"] = round(v_res.duration_s + c_res.duration_s, 4)
                            if tool_name == "codeql" and c_res.metadata:
                                t_stage_entry["clean_db_build_s"] = c_res.metadata.get("db_build_time_s")
                                t_stage_entry["clean_analysis_s"] = c_res.metadata.get("analysis_time_s")
                            elif tool_name == "semgrep" and c_res.metadata:
                                t_stage_entry["clean_container_startup_s"] = c_res.metadata.get("container_startup_s")
                                t_stage_entry["clean_scan_s"] = c_res.metadata.get("scan_time_s")

                            run_record.status = effective_status
                            run_record.error_message = effective_error
                            run_record.run_metadata = meta

                            if effective_status == "completed" and c_res.status == "completed":
                                t_ev0 = time.perf_counter()
                                metrics_summary = self.evaluator.evaluate(
                                    ground_truth=gt_repo,
                                    vulnerable_findings=v_res.findings,
                                    clean_findings=c_res.findings,
                                    duration_s=v_res.duration_s,
                                )
                                stage_timings["evaluator_s"] = round(stage_timings["evaluator_s"] + (time.perf_counter() - t_ev0), 4)
                                db.add(
                                    BenchmarkMetric(
                                        repo_id=repo.id,
                                        tool=tool_name,
                                        tool_version=v_res.tool_version,
                                        precision=metrics_summary.precision,
                                        recall=metrics_summary.recall,
                                        false_positive_rate=metrics_summary.false_positive_rate,
                                        localization_accuracy=metrics_summary.localization_accuracy,
                                        classification_accuracy=metrics_summary.classification_accuracy,
                                        scan_latency=metrics_summary.scan_latency,
                                        counts_json=metrics_summary.counts,
                                        run_version=next_version,
                                        is_superseded=False,
                                    )
                                )
                            db.commit()
                            self.update_stage(db, repo, stage="scanning_clean", progress=0.75 + 0.12 * ((idx + 1) / max(len(uncached_runners), 1)))
                    else:
                        logger.warning("Could not checkout clean commit %s: %s", fix_commit, checkout_clean.stderr)
                else:
                    logger.info("Skipping clean commit scan for %s", repo.name)

                for r_rec in persisted_runs.values():
                    m = dict(r_rec.run_metadata or {})
                    m["stage_timings"] = stage_timings
                    r_rec.run_metadata = m
                db.commit()
            finally:
                _robust_rmtree(filtered_vuln_dir)
                if filtered_clean_dir is not None:
                    _robust_rmtree(filtered_clean_dir)

            # ── STAGE 4: FINALIZING ───────────────────────────────────────────
            self.update_stage(db, repo, stage="computing", progress=0.9)

            # ── STAGE 5: COMPLETE (done | partial | failed) across configurable required tools ──
            from src.benchmarks_research.scope import get_required_tools

            required_tools = set(get_required_tools())
            active_runs = (
                db.query(BenchmarkRun)
                .filter(BenchmarkRun.repo_id == repo.id, BenchmarkRun.is_superseded == False)
                .all()
            )
            active_by_tool = {r.tool: r for r in active_runs}
            completed_required = [
                t for t in sorted(required_tools)
                if t in active_by_tool and active_by_tool[t].status == "completed"
            ]
            incomplete_required = []
            for t in sorted(required_tools):
                r = active_by_tool.get(t)
                if r is None:
                    incomplete_required.append(f"{t} (missing)")
                elif r.status != "completed":
                    incomplete_required.append(f"{t} ({r.status.replace('_', ' ')})")

            if completed_required and incomplete_required:
                repo.status = "partial"
                repo.job_stage = "partial"
                repo.job_progress = 1.0
                repo.job_error = "; ".join(incomplete_required)
            elif not completed_required and incomplete_required:
                repo.status = "failed"
                repo.job_stage = "failed"
                repo.job_progress = 1.0
                repo.job_error = "; ".join(incomplete_required)
            else:
                repo.status = "done"
                repo.job_stage = "done"
                repo.job_progress = 1.0
                repo.job_error = None
            repo.last_heartbeat = datetime.now(timezone.utc)
            db.commit()
            logger.info("Benchmark pipeline finished (%s) for %s (version=%d)", repo.status, repo.name, next_version)

        finally:
            _robust_rmtree(tmp_dir)


def trigger_benchmark_pipeline_async(
    repo_id: str,
    target_tools: Optional[List[str]] = None,
    force_rescan: bool = False,
) -> None:
    """Spawns background thread for the repository benchmark pipeline."""
    import threading
    job = BenchmarkPipelineJob(repo_id, target_tools=target_tools, force_rescan=force_rescan)
    thread = threading.Thread(target=job.run_sync, daemon=True, name=f"bench-job-{repo_id[:8]}")
    thread.start()
