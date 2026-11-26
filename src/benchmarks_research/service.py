"""
Benchmark Orchestration and Persistence Service.
Bridges research ground truth, tool runners, evaluation, and isolated database models.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.benchmarks.read_service import BenchmarkReadService, DEFAULT_STAGE_TIMEOUT, STAGE_TIMEOUT_SECONDS
from src.benchmarks_research.cve_resolver import (
    parse_and_validate_github_url,
    extract_commit_from_github_url,
    extract_cve_or_advisory_or_commit,
)
from src.benchmarks_research.evaluator import BenchmarkEvaluator
from src.benchmarks_research.ground_truth_loader import GroundTruthLoader, GroundTruthRepo
from src.benchmarks_research.runners.bandit_runner import BanditRunner
from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner
from src.benchmarks_research.runners.codeql_runner import CodeQLRunner
from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner
from src.benchmarks_research.runners.sonarqube_runner import SonarQubeRunner
from src.benchmarks_research.schema import MetricSummary, NormalizedFinding, ToolExecutionResult
from src.db.benchmark_models import (
    BenchmarkDeletionAudit,
    BenchmarkFinding,
    BenchmarkMetric,
    BenchmarkRun,
    ResearchRepo,
)

logger = logging.getLogger("ai_engineer.benchmarks.service")


class DuplicateRepoError(ValueError):
    """Raised when an added repository and CVE/commit already exist in benchmarks."""
    pass


STAGE_TIMEOUT_SECONDS: Dict[str, int] = {
    "queued": 120,          # 2 minutes to leave queue and begin execution
    "resolving": 180,       # 3 minutes for GitHub commit/parent resolution
    "cloning": 300,         # 5 minutes for git clone
    "labeling": 120,        # 2 minutes for diff extraction & ground truth generation
    "scanning": 600,        # 10 minutes for SAST runners on vulnerable snapshot
    "scanning_clean": 600,  # 10 minutes for SAST runners on clean snapshot
    "computing": 120,       # 2 minutes for metrics evaluation
}
DEFAULT_STAGE_TIMEOUT = 300  # 5 minutes fallback


class BenchmarkService(BenchmarkReadService):
    """Manages research benchmark repositories, runs, and metric calculations."""

    def __init__(self, db: Session, loader: Optional[GroundTruthLoader] = None):
        super().__init__(db)
        self.loader = loader or GroundTruthLoader()
        self.evaluator = BenchmarkEvaluator(loader=self.loader)

    def _get_latency_pass_summary(self) -> Optional[Dict[str, Any]]:
        from src.benchmarks_research.latency_pass import get_latest_latency_pass_summary
        return get_latest_latency_pass_summary(self.db)

    def check_and_timeout_stuck_jobs(self, timeout_seconds: Optional[int] = None) -> List[ResearchRepo]:
        """
        Scans running jobs. If last_heartbeat exceeds the per-stage limit (or explicit timeout_seconds),
        marks the job as failed with 'Job timed out at stage: <stage>'.
        """
        now = datetime.now(timezone.utc)
        timed_out: List[ResearchRepo] = []
        running_repos = self.db.query(ResearchRepo).filter(ResearchRepo.status == "running").all()
        for r in running_repos:
            ref_time = r.last_heartbeat or r.updated_at or r.created_at
            if ref_time:
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                diff = (now - ref_time).total_seconds()
                stage_limit = timeout_seconds if timeout_seconds is not None else STAGE_TIMEOUT_SECONDS.get(r.job_stage, DEFAULT_STAGE_TIMEOUT)
                if diff > stage_limit:
                    r.status = "failed"
                    r.job_error = f"Job timed out after {int(diff // 60)}m at stage: {r.job_stage}"
                    r.last_heartbeat = now
                    timed_out.append(r)
        if timed_out:
            self.db.commit()
            for r in timed_out:
                self.db.refresh(r)
        return timed_out

    def recover_orphaned_jobs_on_startup(self) -> List[ResearchRepo]:
        """
        Called once on server boot. Any repository still marked 'running' belonged to a
        previous server process whose background threads no longer exist; mark them failed
        with 'Interrupted by server restart at stage: <stage>'.
        """
        now = datetime.now(timezone.utc)
        recovered: List[ResearchRepo] = []
        running_repos = self.db.query(ResearchRepo).filter(ResearchRepo.status == "running").all()
        for r in running_repos:
            r.status = "failed"
            r.job_error = f"Interrupted by server restart at stage: {r.job_stage or 'unknown'}"
            r.last_heartbeat = now
            recovered.append(r)
        if recovered:
            self.db.commit()
            for r in recovered:
                self.db.refresh(r)
            logger.warning("Recovered %d orphaned benchmark job(s) on startup.", len(recovered))
        return recovered

    def sync_manifests_to_db(self) -> List[ResearchRepo]:
        """
        Scans benchmarks/ground_truth/ and ensures all research repos are registered in DB.
        """
        manifests = self.loader.load_all_manifests()
        repos: List[ResearchRepo] = []

        for m in manifests:
            existing = self.db.query(ResearchRepo).filter(ResearchRepo.name == m.repo_name).first()
            repo_type = getattr(m, "repo_type", "cve_fix")
            clean_sha = None if repo_type == "intentionally_vulnerable" else m.pinned_clean_sha

            if not existing:
                repo_record = ResearchRepo(
                    name=m.repo_name,
                    url=m.url,
                    pinned_sha=m.pinned_vulnerable_sha,
                    clean_sha=clean_sha,
                    language=m.language,
                    loc=m.loc,
                    ground_truth_path=m.manifest_path or f"benchmarks/ground_truth/{Path(m.url).stem}.json",
                    added_by="ground_truth_manifest",
                    status="ready",
                    job_stage="ready",
                    job_progress=1.0,
                    repo_type=repo_type,
                    label_quality="verified" if "we45" in m.repo_name.lower() else "provisional",
                    last_heartbeat=datetime.now(timezone.utc),
                    notes=m.description,
                )
                self.db.add(repo_record)
                self.db.commit()
                self.db.refresh(repo_record)
                repos.append(repo_record)
            else:
                updated = False
                if m.manifest_path and existing.ground_truth_path != m.manifest_path:
                    existing.ground_truth_path = m.manifest_path
                    updated = True
                if existing.repo_type != repo_type:
                    existing.repo_type = repo_type
                    updated = True
                if repo_type == "intentionally_vulnerable" and existing.clean_sha is not None:
                    existing.clean_sha = None
                    updated = True
                if updated:
                    self.db.commit()
                repos.append(existing)

        return repos

    def add_research_repo(
        self,
        url: str,
        identifier: str,
        added_by: str = "admin",
        cwe: Optional[str] = None,
    ) -> ResearchRepo:
        """
        One-step automated entry point: validates URL, checks duplicates synchronously,
        creates record in queued state, and triggers asynchronous background pipeline.
        """
        from src.benchmarks_research.pipeline import trigger_benchmark_pipeline_async

        owner, repo_slug = parse_and_validate_github_url(url)
        commit_in_url = extract_commit_from_github_url(url)
        clean_id = extract_cve_or_advisory_or_commit(identifier)

        fix_commit = commit_in_url or (clean_id if clean_id and not (clean_id.upper().startswith("CVE-") or clean_id.upper().startswith("GHSA-")) else None)
        cve_id = clean_id if (clean_id and (clean_id.upper().startswith("CVE-") or clean_id.upper().startswith("GHSA-"))) else None

        display_tag = cve_id or (fix_commit[:8] if fix_commit else clean_id)
        full_name = f"{owner}/{repo_slug} ({display_tag})" if display_tag else f"{owner}/{repo_slug}"
        norm_url = f"https://github.com/{owner}/{repo_slug}".lower()

        # Synchronous duplicate detection BEFORE inserting any row
        existing_query = self.db.query(ResearchRepo).filter(
            func.lower(ResearchRepo.url) == norm_url
        )
        if cve_id:
            existing = existing_query.filter(ResearchRepo.cve_id.ilike(cve_id)).first()
        elif fix_commit:
            existing = existing_query.filter(
                or_(
                    ResearchRepo.fix_commit.ilike(fix_commit),
                    ResearchRepo.pinned_sha.ilike(fix_commit),
                    ResearchRepo.name.ilike(full_name),
                )
            ).first()
        else:
            existing = existing_query.filter(ResearchRepo.name.ilike(full_name)).first()

        if existing:
            raise DuplicateRepoError(
                f"Repository '{existing.name}' is already registered in the benchmark "
                f"(Status: {existing.status}, ID: {existing.id})."
            )

        from src.benchmarks_research.scope import validate_and_normalize_cwe
        norm_cwe = validate_and_normalize_cwe(cwe, strict=True)

        repo_record = ResearchRepo(
            name=full_name,
            url=f"https://github.com/{owner}/{repo_slug}",
            pinned_sha="",
            clean_sha=None,
            language="detecting",
            loc=None,
            ground_truth_path="",
            added_by=added_by,
            status="running",
            job_stage="queued",
            job_progress=0.05,
            label_quality="provisional",
            repo_type="cve_fix",
            cve_id=cve_id,
            user_cwe=norm_cwe,
            fix_commit=fix_commit,
            last_heartbeat=datetime.now(timezone.utc),
            notes=f"Automatic research repository queued with {display_tag or 'fix'}",
        )
        self.db.add(repo_record)
        self.db.commit()
        self.db.refresh(repo_record)

        # Trigger background pipeline
        trigger_benchmark_pipeline_async(repo_record.id)
        return repo_record

    def run_repo_pipeline(
        self,
        repo_id: str,
        tool: Optional[str] = None,
        force_rescan: bool = False,
    ) -> ResearchRepo:
        """
        Starts or re-runs the benchmark pipeline for a repository (all tools or a single tool).
        Append-only: never deletes prior runs, findings, or metrics; older runs are marked superseded.
        Idempotent: rejects duplicate concurrent executions while an active job is running.
        """
        from src.benchmarks_research.pipeline import trigger_benchmark_pipeline_async

        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        valid_tools = {"codeguardian", "semgrep", "codeql", "sonarqube", "bandit"}
        target_tools: Optional[List[str]] = None
        if tool:
            t_norm = tool.strip().lower()
            if t_norm not in valid_tools:
                raise ValueError(f"Unknown tool '{tool}'. Expected one of: {sorted(valid_tools)}")
            target_tools = [t_norm]

        # Idempotence check: prevent double-clicks if actively running
        if repo.status == "running":
            now = datetime.now(timezone.utc)
            ref_time = repo.last_heartbeat or repo.updated_at or repo.created_at
            if ref_time:
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                diff = (now - ref_time).total_seconds()
                stage_limit = STAGE_TIMEOUT_SECONDS.get(repo.job_stage, DEFAULT_STAGE_TIMEOUT)
                if diff <= stage_limit:
                    raise ValueError(f"Benchmark pipeline for '{repo.name}' is already actively running at stage '{repo.job_stage}'.")

        repo.status = "running"
        repo.job_stage = "queued"
        repo.job_progress = 0.05
        repo.job_error = None
        repo.is_excluded = False
        repo.last_heartbeat = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(repo)

        if force_rescan:
            trigger_benchmark_pipeline_async(repo.id, target_tools=target_tools, force_rescan=True)
        else:
            trigger_benchmark_pipeline_async(repo.id, target_tools=target_tools)
        return repo

    def retry_repo_pipeline(
        self,
        repo_id: str,
        tool: Optional[str] = None,
        force_rescan: bool = False,
    ) -> ResearchRepo:
        """Alias for run_repo_pipeline for retrying failed or stalled pipelines."""
        return self.run_repo_pipeline(repo_id, tool=tool, force_rescan=force_rescan)

    def get_run_plan(self, repo_id: str, force_rescan: bool = False) -> Dict[str, Any]:
        """Returns which tools will reuse cached results vs re-scan before running."""
        from src.benchmarks_research.pipeline import build_run_plan
        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")
        return build_run_plan(self.db, repo, force_rescan=force_rescan)

    def exclude_repo(self, repo_id: str, reason: str) -> ResearchRepo:
        """Excludes a research repo from general macro-averages with mandatory reason."""
        if not reason or len(reason.strip()) < 5:
            raise ValueError("A specific written reason (at least 5 characters) is required to exclude a repository.")

        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        repo.is_excluded = True
        repo.exclusion_reason = reason.strip()
        self.db.commit()
        self.db.refresh(repo)
        return repo

    def unexclude_repo(self, repo_id: str) -> ResearchRepo:
        """Re-includes a previously excluded research repository."""
        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        repo.is_excluded = False
        repo.exclusion_reason = None
        self.db.commit()
        self.db.refresh(repo)
        return repo

    def delete_repo(
        self,
        repo_id: str,
        reason: Optional[str] = None,
        deleted_by: str = "admin",
    ) -> Dict[str, Any]:
        """
        Permanently deletes a research repo and all related DB rows (runs, findings, metrics),
        its ground-truth manifest on disk, and its cached clone directory.
        If the repo has completed runs, requires a written reason and logs an audit record
        that survives deletion.
        """
        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        if repo.status == "running":
            now = datetime.now(timezone.utc)
            ref_time = repo.last_heartbeat or repo.updated_at or repo.created_at
            if ref_time:
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                diff = (now - ref_time).total_seconds()
                stage_limit = STAGE_TIMEOUT_SECONDS.get(repo.job_stage, DEFAULT_STAGE_TIMEOUT)
                if diff <= stage_limit:
                    raise ValueError(f"Cannot delete '{repo.name}' while pipeline is actively running.")

        completed_runs_count = (
            self.db.query(BenchmarkRun)
            .filter(BenchmarkRun.repo_id == repo.id, BenchmarkRun.status == "completed")
            .count()
        )
        had_completed_run = completed_runs_count > 0
        was_counted_in_averages = had_completed_run and repo.status == "done" and not bool(repo.is_excluded)

        clean_reason = reason.strip() if reason else None
        if had_completed_run and (not clean_reason or len(clean_reason) < 5):
            raise ValueError(
                "A specific written reason (at least 5 characters) is required to delete a repository with completed runs."
            )

        # Record immutable audit entry before removing the repo
        audit = BenchmarkDeletionAudit(
            repo_id=repo.id,
            repo_name=repo.name,
            repo_url=repo.url,
            cve_id=repo.cve_id,
            had_completed_run=had_completed_run,
            was_counted_in_averages=was_counted_in_averages,
            completed_runs_count=completed_runs_count,
            reason=clean_reason,
            deleted_by=deleted_by,
        )
        self.db.add(audit)

        # Remove disk artifacts: ground-truth manifest and cached clone dir
        base_dir = Path(__file__).resolve().parents[2]
        removed_manifest = None
        if repo.ground_truth_path:
            manifest_file = base_dir / repo.ground_truth_path
            if manifest_file.exists() and manifest_file.is_file():
                manifest_file.unlink()
                removed_manifest = str(repo.ground_truth_path)

        removed_cache = None
        try:
            owner, repo_slug = parse_and_validate_github_url(repo.url)
            cache_dir = base_dir / "data" / "benchmark_cache" / f"{owner}_{repo_slug}"
            if cache_dir.exists() and cache_dir.is_dir():
                shutil.rmtree(cache_dir, ignore_errors=True)
                removed_cache = str(cache_dir.relative_to(base_dir))
        except Exception as exc:
            logger.warning("Failed to inspect/remove cache dir for %s: %s", repo.url, exc)

        repo_name = repo.name
        # Explicitly delete child rows then the repo row
        self.db.query(BenchmarkFinding).filter(BenchmarkFinding.repo_id == repo.id).delete()
        self.db.query(BenchmarkMetric).filter(BenchmarkMetric.repo_id == repo.id).delete()
        self.db.query(BenchmarkRun).filter(BenchmarkRun.repo_id == repo.id).delete()
        self.db.delete(repo)
        self.db.commit()

        return {
            "status": "deleted",
            "repo_id": repo_id,
            "repo_name": repo_name,
            "had_completed_run": had_completed_run,
            "was_counted_in_averages": was_counted_in_averages,
            "audit_id": audit.id,
            "removed_manifest": removed_manifest,
            "removed_cache": removed_cache,
        }

    @staticmethod
    def _effective_metric_dict(m: BenchmarkMetric) -> Dict[str, Any]:
        """
        Normalizes a stored BenchmarkMetric row without mutating DB:
        - Precision is None ('n/a') when tp + fp == 0
        - Localization & Classification are None ('n/a') when tp == 0
        - Recall is None ('n/a') only when tp + fn == 0
        - Computes F1 when precision and recall are defined
        """
        d = m.to_dict()
        counts = m.counts_json or {}
        tp = counts.get("tp")
        fp = counts.get("fp")
        fn = counts.get("fn")

        p = d.get("precision")
        r = d.get("recall")
        loc = d.get("localization_accuracy")
        cls = d.get("classification_accuracy")
        cls_fam = counts.get("classification_family_accuracy")

        if tp is not None and fp is not None and (tp + fp) == 0:
            p = None
        if tp is not None and fn is not None and (tp + fn) == 0:
            r = None
        if tp is not None and tp == 0:
            loc = None
            cls = None
            cls_fam = None

        f1 = None
        if p is not None and r is not None:
            f1 = round((2 * p * r / (p + r)), 4) if (p + r) > 0 else 0.0

        d["precision"] = round(p, 4) if p is not None else None
        d["recall"] = round(r, 4) if r is not None else None
        d["localization_accuracy"] = round(loc, 4) if loc is not None else None
        d["classification_accuracy"] = round(cls, 4) if cls is not None else None
        d["classification_family_accuracy"] = round(cls_fam, 4) if cls_fam is not None else None
        d["f1_score"] = f1
        return d

    def get_overview_macro_metrics(self, verified_only: bool = False) -> Dict[str, Any]:
        """
        Computes macro-averages across all active research repositories.
        Supports filtering by verified_only, calculates sample size,
        flags provisional FPR upper-bounds, and compiles sanity warnings.
        Does NOT inject synthetic fallbacks or leak unverified data.
        """
        self.check_and_timeout_stuck_jobs()

        query = self.db.query(ResearchRepo).filter(
            ResearchRepo.is_excluded == False,
            ResearchRepo.status.in_(["done", "partial"]),
        )
        if verified_only:
            query = query.filter(ResearchRepo.label_quality == "verified")

        active_repos = query.all()
        active_repo_ids = {r.id for r in active_repos}

        all_repos = self.db.query(ResearchRepo).all()
        total_repos_count = len([r for r in all_repos if not r.is_excluded and r.status in ("done", "partial")])
        verified_repos_count = len([r for r in all_repos if not r.is_excluded and r.status in ("done", "partial") and r.label_quality == "verified"])
        provisional_repos_count = total_repos_count - verified_repos_count

        total_loc = sum(r.loc for r in active_repos if r.loc)

        # Get metrics for active repos only, strictly filtered to latest non-superseded completed tool runs
        completed_runs = self.db.query(BenchmarkRun.repo_id, BenchmarkRun.tool).filter(
            BenchmarkRun.repo_id.in_(active_repo_ids),
            BenchmarkRun.status == "completed",
            BenchmarkRun.is_superseded == False,
        ).all()
        completed_pairs = set(completed_runs)

        raw_metrics = (
            self.db.query(BenchmarkMetric)
            .filter(BenchmarkMetric.repo_id.in_(active_repo_ids), BenchmarkMetric.is_superseded == False)
            .all()
            if active_repo_ids
            else []
        )
        metrics = [m for m in raw_metrics if (m.repo_id, m.tool) in completed_pairs]

        tool_metrics: Dict[str, List[BenchmarkMetric]] = {}
        for m in metrics:
            tool_metrics.setdefault(m.tool, []).append(m)

        tools_macro: Dict[str, Any] = {}
        tool_order = ["codeguardian", "semgrep", "codeql", "sonarqube", "bandit"]
        runner_map = {
            "codeguardian": CodeGuardianRunner,
            "semgrep": SemgrepRunner,
            "codeql": CodeQLRunner,
            "sonarqube": SonarQubeRunner,
            "bandit": BanditRunner,
        }

        # Latest non-completed run status per tool across active repos (for accurate UI diagnostics)
        latest_run_by_tool: Dict[str, BenchmarkRun] = {}
        if active_repo_ids:
            all_active_runs = (
                self.db.query(BenchmarkRun)
                .filter(BenchmarkRun.repo_id.in_(active_repo_ids), BenchmarkRun.is_superseded == False)
                .order_by(BenchmarkRun.started_at.desc())
                .all()
            )
            for run in all_active_runs:
                if run.tool not in latest_run_by_tool:
                    latest_run_by_tool[run.tool] = run

        from src.benchmarks_research.sampled_precision import get_latest_sampled_precision
        from src.benchmarks_research.latency_pass import get_latest_latency_pass_summary
        from src.db.benchmark_models import BenchmarkLatencyPass

        sampled_latest = get_latest_sampled_precision(self.db)
        sampled_per_tool = (sampled_latest or {}).get("per_tool", {})

        latency_pass = get_latest_latency_pass_summary(self.db)
        latency_macro = ((latency_pass or {}).get("results") or {}).get("per_tool_macro") or {}
        active_latency_pass = (
            self.db.query(BenchmarkLatencyPass)
            .filter(BenchmarkLatencyPass.status == "running")
            .order_by(BenchmarkLatencyPass.pass_version.desc())
            .first()
        )

        for tool_name in tool_order:
            m_list = tool_metrics.get(tool_name, [])
            lp_tool = latency_macro.get(tool_name)
            lp_measured = bool(lp_tool and lp_tool.get("median_latency_per_kloc") is not None)
            lp_latency = lp_tool.get("median_latency_per_kloc") if lp_measured else None
            lp_spread = lp_tool.get("spread_latency_per_kloc") if lp_measured else None
            if m_list:
                n = len(m_list)
                eff_list = [self._effective_metric_dict(m) for m in m_list]

                p_vals = [e["precision"] for e in eff_list if e["precision"] is not None]
                r_vals = [e["recall"] for e in eff_list if e["recall"] is not None]
                f1_vals = [e["f1_score"] for e in eff_list if e["f1_score"] is not None]
                loc_vals = [e["localization_accuracy"] for e in eff_list if e["localization_accuracy"] is not None]
                cls_vals = [e["classification_accuracy"] for e in eff_list if e["classification_accuracy"] is not None]
                cls_fam_vals = [e["classification_family_accuracy"] for e in eff_list if e.get("classification_family_accuracy") is not None]

                clean_metrics = [
                    m for m in m_list
                    if m.repo and m.repo.repo_type != "intentionally_vulnerable" and m.repo.clean_sha
                ]
                fpr_avg = round(sum(m.false_positive_rate for m in clean_metrics) / len(clean_metrics), 4) if clean_metrics else 0.0
                total_vuln_findings = sum(int((m.counts_json or {}).get("total_vulnerable_findings", 0)) for m in m_list)
                total_clean_fp = sum(int((m.counts_json or {}).get("clean_fp", 0)) for m in clean_metrics)
                zero_findings_only = (total_vuln_findings == 0 and total_clean_fp == 0)

                latency_scope = (
                    "AST stage only (0 LLM calls in benchmark runner)"
                    if tool_name == "codeguardian"
                    else "DB create + QL analysis"
                    if tool_name == "codeql"
                    else "Scan-only (excl. container startup)"
                    if tool_name == "semgrep"
                    else "Scan-only"
                )

                tools_macro[tool_name] = {
                    "precision": round(sum(p_vals) / len(p_vals), 4) if p_vals else None,
                    "sampled_precision": sampled_per_tool.get(tool_name),
                    "recall": round(sum(r_vals) / len(r_vals), 4) if r_vals else None,
                    "f1_score": round(sum(f1_vals) / len(f1_vals), 4) if f1_vals else None,
                    "false_positive_rate": fpr_avg,
                    "zero_findings_only": zero_findings_only,
                    "localization_accuracy": round(sum(loc_vals) / len(loc_vals), 4) if loc_vals else None,
                    "classification_accuracy": round(sum(cls_vals) / len(cls_vals), 4) if cls_vals else None,
                    "classification_family_accuracy": round(sum(cls_fam_vals) / len(cls_fam_vals), 4) if cls_fam_vals else None,
                    "scan_latency": lp_latency,
                    "latency_spread": lp_spread,
                    "latency_measured": lp_measured,
                    "ast_latency": lp_latency if (tool_name == "codeguardian" and lp_measured) else None,
                    "codeql_db_create_median_s": lp_tool.get("db_create_median_s") if (tool_name == "codeql" and lp_tool) else None,
                    "codeql_analyze_median_s": lp_tool.get("analyze_median_s") if (tool_name == "codeql" and lp_tool) else None,
                    "end_to_end_latency": None,
                    "latency_scope": latency_scope,
                    "latency_measurement_mode": "isolated_sequential_pass" if lp_measured else "not_measured",
                    "tool_version": m_list[0].tool_version,
                    "sample_size": n,
                    "sample_counts": {
                        "precision": len(p_vals),
                        "recall": len(r_vals),
                        "f1_score": len(f1_vals),
                        "false_positive_rate": len(clean_metrics),
                        "localization_accuracy": len(loc_vals),
                        "classification_accuracy": len(cls_vals),
                        "classification_family_accuracy": len(cls_fam_vals),
                        "scan_latency": lp_tool.get("sample_repos", 0) if lp_measured else 0,
                    },
                    "has_data": True,
                    "status": "completed",
                    "status_detail": None,
                }
            else:
                latest_run = latest_run_by_tool.get(tool_name)
                if latest_run:
                    t_status = latest_run.status
                    t_detail = latest_run.error_message
                else:
                    runner_cls = runner_map.get(tool_name)
                    available = runner_cls().is_available() if runner_cls else False
                    t_status = "ready" if available else "not_installed"
                    t_detail = None if available else f"{tool_name} not available"

                tools_macro[tool_name] = {
                    "precision": None,
                    "recall": None,
                    "f1_score": None,
                    "false_positive_rate": 0.0,
                    "localization_accuracy": None,
                    "classification_accuracy": None,
                    "scan_latency": lp_latency,
                    "latency_spread": lp_spread,
                    "latency_measured": lp_measured,
                    "ast_latency": lp_latency if (tool_name == "codeguardian" and lp_measured) else None,
                    "end_to_end_latency": None,
                    "latency_scope": None,
                    "tool_version": "unknown",
                    "sample_size": 0,
                    "sample_counts": {
                        "precision": 0,
                        "recall": 0,
                        "f1_score": 0,
                        "false_positive_rate": 0,
                        "localization_accuracy": 0,
                        "classification_accuracy": 0,
                        "scan_latency": lp_tool.get("sample_repos", 0) if lp_measured else 0,
                    },
                    "has_data": False,
                    "status": t_status,
                    "status_detail": t_detail,
                }

        # Compile Sanity Warnings
        sanity_warnings: List[str] = []
        n_active = len(active_repos)
        if n_active < 5:
            sanity_warnings.append(
                f"Small sample size ({n_active} research repos in averages). "
                "At least 5 diverse repositories are recommended for research-grade statistical significance."
            )

        for tool_name, t_metrics in tools_macro.items():
            if t_metrics.get("has_data") and t_metrics["recall"] == 0.0 and n_active > 0:
                sanity_warnings.append(f"Tool Dropout: '{tool_name}' detected zero labeled vulnerabilities.")

        # Check extreme margin win/loss only when real data exists and both precisions are defined
        if tools_macro.get("codeguardian", {}).get("has_data") and tools_macro.get("semgrep", {}).get("has_data"):
            cg_p = tools_macro.get("codeguardian", {}).get("precision")
            sem_p = tools_macro.get("semgrep", {}).get("precision")
            if cg_p is not None and sem_p is not None and abs(cg_p - sem_p) > 0.40:
                sanity_warnings.append("Extreme margin alert: CodeGuardian and Semgrep precision differ by >40%. Verify rule coverage.")

        return {
            "total_repos": n_active,
            "verified_repos": verified_repos_count,
            "provisional_repos": provisional_repos_count,
            "verified_only": verified_only,
            "has_provisional": provisional_repos_count > 0 and not verified_only,
            "fpr_is_upper_bound": provisional_repos_count > 0 and not verified_only,
            "total_loc": total_loc,
            "sanity_warnings": sanity_warnings,
            "tools": tools_macro,
            "latency_pass": latency_pass,
            "active_latency_pass": active_latency_pass.to_dict() if active_latency_pass else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_research_repos(self) -> List[Dict[str, Any]]:
        """Returns list of research repositories with metrics."""
        self.check_and_timeout_stuck_jobs()
        repos = self.db.query(ResearchRepo).order_by(ResearchRepo.created_at.desc()).all()
        res = []
        for r in repos:
            repo_dict = r.to_dict()
            active_metrics = [m for m in r.metrics if not getattr(m, "is_superseded", False)]
            active_runs = [run for run in r.runs if not getattr(run, "is_superseded", False)]
            metrics = {m.tool: self._effective_metric_dict(m) for m in active_metrics}
            completed_runs_count = sum(1 for run in r.runs if run.status == "completed")
            from src.benchmarks_research.scope import get_required_tools
            req_tools = list(get_required_tools())
            repo_dict["metrics"] = metrics
            repo_dict["required_tools"] = req_tools
            repo_dict["tools_ran"] = [run.tool for run in active_runs if run.status == "completed"]
            repo_dict["tool_statuses"] = {
                run.tool: {
                    "status": run.status,
                    "tool_version": run.tool_version,
                    "duration_s": round(run.duration_s or 0.0, 2),
                    "error_message": run.error_message,
                    "run_version": getattr(run, "run_version", 1) or 1,
                    "required": run.tool in req_tools,
                    "cached": bool((run.run_metadata or {}).get("cached", False)),
                    "original_timestamp": (run.run_metadata or {}).get("original_timestamp"),
                    "original_duration_s": (run.run_metadata or {}).get("original_duration_s"),
                }
                for run in active_runs
            }
            repo_dict["completed_runs_count"] = completed_runs_count
            repo_dict["has_completed_run"] = completed_runs_count > 0
            res.append(repo_dict)
        return res

    def get_repo_detail(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Returns detailed ground truth and metric comparison for a single repo."""
        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            repo = self.db.query(ResearchRepo).filter(ResearchRepo.name.ilike(f"%{repo_id}%")).first()
        if not repo:
            return None

        # Load ground truth manifest
        base_dir = Path(__file__).resolve().parents[2]
        manifest_file = base_dir / repo.ground_truth_path if repo.ground_truth_path else None
        ground_truth_data = {}
        if manifest_file and manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    ground_truth_data = json.load(f)
            except Exception as e:
                logger.error("Failed to read manifest: %s", e)

        active_metrics = [m for m in repo.metrics if not getattr(m, "is_superseded", False)]
        metrics = {m.tool: self._effective_metric_dict(m) for m in active_metrics}
        active_runs = [run for run in repo.runs if not getattr(run, "is_superseded", False)]
        active_run_ids = {run.id for run in active_runs}
        runs = [run.to_dict() for run in active_runs]
        findings = [f.to_dict() for f in repo.findings if f.run_id in active_run_ids]
        stage_timings = None
        for r in active_runs:
            st = (r.run_metadata or {}).get("stage_timings")
            if st:
                stage_timings = st
                break

        return {
            "repo": repo.to_dict(),
            "ground_truth": ground_truth_data,
            "metrics": metrics,
            "runs": runs,
            "findings": findings,
            "stage_timings": stage_timings,
        }

    def export_blind_triage(self, repo_id: str) -> Dict[str, Any]:
        """
        Exports unique findings across all tools with tool names blinded (e.g. 'Tool-A', 'Tool-B')
        for objective human review and label upgrading.
        """
        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        # Map tools to anonymized letters
        tool_anonymizer = {
            "codeguardian": "Tool-Alpha",
            "semgrep": "Tool-Beta",
            "codeql": "Tool-Gamma",
            "sonarqube": "Tool-Delta",
            "bandit": "Tool-Epsilon",
        }

        blind_findings = []
        for f in repo.findings:
            blind_findings.append({
                "finding_id": f.id,
                "anonymized_tool": tool_anonymizer.get(f.tool, "Tool-Anonymous"),
                "file": f.file_path,
                "line": f.line_start,
                "cwe": f.cwe,
                "severity": f.severity,
                "rule_id": f.rule_id,
                "triage_decision": "unreviewed",  # Human reviewer marks: "true_positive" | "false_positive"
            })

        return {
            "repo_id": repo.id,
            "repo_name": repo.name,
            "pinned_sha": repo.pinned_sha,
            "instruction": "Mark 'triage_decision' as 'true_positive' or 'false_positive' for each finding, then re-import.",
            "findings": blind_findings,
        }

    def import_verified_triage(self, repo_id: str, reviewed_findings: List[Dict[str, Any]]) -> ResearchRepo:
        """
        Imports human-verified triage decisions and upgrades repo from 'provisional' to 'verified'.
        """
        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        # Update findings match_result based on human triage
        triage_map = {item.get("finding_id"): item.get("triage_decision") for item in reviewed_findings if item.get("finding_id")}
        for f in repo.findings:
            decision = triage_map.get(f.id)
            if decision == "true_positive":
                f.match_result = "TP"
            elif decision == "false_positive":
                f.match_result = "FP"

        repo.label_quality = "verified"
        repo.status = "done"
        self.db.commit()
        self.db.refresh(repo)
        return repo

    def recompute_metrics(self, repo_id: str) -> Dict[str, Any]:
        """
        Re-evaluates stored active findings against the latest ground-truth manifest
        and cwe_map.json without re-scanning. Appends a new run_version and marks
        prior BenchmarkRun / BenchmarkMetric rows superseded.
        """
        import uuid
        from src.benchmarks_research.evaluator import BenchmarkEvaluator
        from src.benchmarks_research.ground_truth_loader import GroundTruthLoader
        from src.benchmarks_research.schema import NormalizedFinding

        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            repo = self.db.query(ResearchRepo).filter(ResearchRepo.name.ilike(f"%{repo_id}%")).first()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")
        if repo.status == "running":
            raise ValueError(f"Repository '{repo.name}' is currently running; cannot recompute while active.")

        loader = GroundTruthLoader()
        evaluator = BenchmarkEvaluator(loader=loader)

        manifests = loader.load_all_manifests()
        gt_repo = next((m for m in manifests if m.repo_name == repo.name), None)
        if gt_repo and getattr(gt_repo, "manifest_path", None):
            repo.ground_truth_path = gt_repo.manifest_path
        elif repo.ground_truth_path and Path(repo.ground_truth_path).exists():
            gt_repo = loader.load_manifest(Path(repo.ground_truth_path))
        elif gt_repo is None:
            raise ValueError(f"No ground-truth manifest found for '{repo.name}'.")

        active_runs = (
            self.db.query(BenchmarkRun)
            .filter(BenchmarkRun.repo_id == repo.id, BenchmarkRun.is_superseded == False)
            .all()
        )
        if not active_runs:
            raise ValueError(f"No active benchmark runs found for '{repo.name}'.")

        active_metrics = {
            m.tool: m
            for m in self.db.query(BenchmarkMetric)
            .filter(BenchmarkMetric.repo_id == repo.id, BenchmarkMetric.is_superseded == False)
            .all()
        }
        next_ver = max((r.run_version or 1 for r in active_runs), default=1) + 1
        tools_recomputed: List[str] = []

        for old_run in active_runs:
            old_run.is_superseded = True
            old_metric = active_metrics.get(old_run.tool)
            if old_metric:
                old_metric.is_superseded = True

            old_findings = (
                self.db.query(BenchmarkFinding)
                .filter(BenchmarkFinding.run_id == old_run.id)
                .all()
            )
            new_meta = dict(old_run.run_metadata or {})
            new_meta["recomputed_from_version"] = old_run.run_version or 1
            new_meta["recomputed_without_rescan"] = True

            new_run = BenchmarkRun(
                id=str(uuid.uuid4()),
                repo_id=repo.id,
                tool=old_run.tool,
                tool_version=old_run.tool_version,
                started_at=old_run.started_at,
                duration_s=old_run.duration_s,
                raw_output_path=old_run.raw_output_path,
                status=old_run.status,
                error_message=old_run.error_message,
                run_metadata=new_meta,
                run_version=next_ver,
                is_superseded=False,
            )
            self.db.add(new_run)
            self.db.flush()

            from src.benchmarks_research.scope import ScopePolicy
            scope_policy = ScopePolicy.from_override(getattr(repo, "scope_override", None))

            vuln_findings: List[NormalizedFinding] = []
            for f in old_findings:
                in_scope, _ = scope_policy.is_in_scope(f.file_path)
                if not in_scope:
                    continue
                nf = NormalizedFinding(
                    tool=f.tool,
                    file_path=f.file_path,
                    line_start=f.line_start,
                    line_end=f.line_end,
                    cwe=f.cwe,
                    severity=f.severity or "MEDIUM",
                    rule_id=f.rule_id or "",
                    title=(f.raw_finding or {}).get("title", ""),
                    description=(f.raw_finding or {}).get("description", ""),
                    raw_payload=f.raw_finding,
                )
                vuln_findings.append(nf)

            finding_matches, _, _ = evaluator.match_findings(gt_repo, vuln_findings)
            for f_idx, nf in enumerate(vuln_findings):
                m_info = finding_matches.get(f_idx)
                match_res = m_info[0] if m_info else "FP"
                matched_id = m_info[1] if m_info else None
                line_dist = m_info[2] if m_info else None
                cwe_matched = m_info[3] if m_info else False

                self.db.add(
                    BenchmarkFinding(
                        id=str(uuid.uuid4()),
                        run_id=new_run.id,
                        repo_id=repo.id,
                        tool=old_run.tool,
                        file_path=nf.file_path,
                        line_start=nf.line_start,
                        line_end=nf.line_end,
                        cwe=nf.cwe,
                        normalized_cwe=loader.normalize_cwe(nf.cwe),
                        severity=nf.severity,
                        rule_id=nf.rule_id,
                        match_result=match_res,
                        matched_ground_truth_id=matched_id,
                        line_distance=line_dist,
                        cwe_matched=cwe_matched,
                        raw_finding=nf.raw_payload,
                    )
                )

            if old_run.status == "completed":
                clean_fp = (
                    int((old_metric.counts_json or {}).get("clean_fp", 0))
                    if old_metric is not None
                    else int((old_run.run_metadata or {}).get("clean_fp", 0))
                )
                clean_dummy = [
                    NormalizedFinding(
                        tool=old_run.tool,
                        file_path="clean.py",
                        line_start=1,
                        line_end=1,
                        cwe="",
                        severity="LOW",
                        rule_id="CLEAN",
                    )
                ] * clean_fp
                summary = evaluator.evaluate(
                    ground_truth=gt_repo,
                    vulnerable_findings=vuln_findings,
                    clean_findings=clean_dummy,
                    duration_s=old_run.duration_s or 0.0,
                )
                self.db.add(
                    BenchmarkMetric(
                        id=str(uuid.uuid4()),
                        repo_id=repo.id,
                        tool=old_run.tool,
                        tool_version=old_run.tool_version,
                        precision=summary.precision,
                        recall=summary.recall,
                        false_positive_rate=summary.false_positive_rate,
                        localization_accuracy=summary.localization_accuracy,
                        classification_accuracy=summary.classification_accuracy,
                        scan_latency=summary.scan_latency,
                        counts_json=summary.counts,
                        run_version=next_ver,
                        is_superseded=False,
                    )
                )
                tools_recomputed.append(old_run.tool)

        from src.benchmarks_research.scope import get_required_tools
        req_tools = set(get_required_tools())
        if repo.status in ("failed", "partial") and req_tools.issubset(set(tools_recomputed)):
            repo.status = "done"
            repo.job_stage = "done"
            repo.job_progress = 1.0
            repo.job_error = None

        self.db.commit()
        return {
            "repo_id": repo.id,
            "repo_name": repo.name,
            "run_version": next_ver,
            "ground_truth_path": repo.ground_truth_path,
            "tools_recomputed": tools_recomputed,
        }

    def recompute_all_metrics(self) -> Dict[str, Any]:
        """Recomputes metrics across all non-running, non-excluded repos without scanning."""
        repos = self.db.query(ResearchRepo).filter(ResearchRepo.is_excluded == False).all()
        recomputed: List[Dict[str, Any]] = []
        skipped: List[Dict[str, str]] = []
        for r in repos:
            if r.status == "running":
                skipped.append({"repo_id": r.id, "repo_name": r.name, "reason": "currently running"})
                continue
            try:
                recomputed.append(self.recompute_metrics(r.id))
            except ValueError as e:
                skipped.append({"repo_id": r.id, "repo_name": r.name, "reason": str(e)})
        return {"recomputed": recomputed, "skipped": skipped}
