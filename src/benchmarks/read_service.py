"""
Production Benchmark Read Service (Read-Only APIs).
Strictly isolated from `src.benchmarks_research` (zero imports of runners, pipeline,
diff_extractor, ground_truth_loader, triage, or rule files).
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.db.benchmark_models import (
    BenchmarkLatencyPass,
    BenchmarkMetric,
    BenchmarkRun,
    BenchmarkSnapshot,
    ResearchRepo,
    SampledPrecisionAudit,
)

logger = logging.getLogger("ai_engineer.benchmarks.read_service")

STAGE_TIMEOUT_SECONDS: Dict[str, int] = {
    "queued": 120,
    "resolving": 180,
    "cloning": 300,
    "labeling": 120,
    "scanning": 600,
    "scanning_clean": 600,
    "computing": 120,
}
DEFAULT_STAGE_TIMEOUT = 300
DEFAULT_REQUIRED_TOOLS: Tuple[str, ...] = ("codeguardian", "semgrep", "codeql", "bandit")


def get_required_tools_prod() -> Tuple[str, ...]:
    env_val = os.getenv("BENCHMARK_REQUIRED_TOOLS", "").strip()
    if env_val:
        parsed = tuple(t.strip().lower() for t in env_val.split(",") if t.strip())
        if parsed:
            return parsed
    return DEFAULT_REQUIRED_TOOLS


def _wilson_ci_95(k: int, n: int) -> Tuple[Optional[float], Optional[float]]:
    if n <= 0:
        return None, None
    z = 1.959963984540054
    p = k / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * n)) / n)) / denom
    return round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)


def get_latest_sampled_precision_from_db(db: Session) -> Optional[Dict[str, Any]]:
    """Pure DB read of the latest SampledPrecisionAudit version with 95% Wilson CI."""
    latest_row = (
        db.query(SampledPrecisionAudit)
        .order_by(SampledPrecisionAudit.audit_version.desc())
        .first()
    )
    if not latest_row:
        return None

    ver = latest_row.audit_version
    rows = (
        db.query(SampledPrecisionAudit)
        .filter(SampledPrecisionAudit.audit_version == ver)
        .all()
    )
    by_tool: Dict[str, List[SampledPrecisionAudit]] = {}
    for r in rows:
        by_tool.setdefault(r.tool, []).append(r)

    per_tool: Dict[str, Any] = {}
    for tool, t_rows in sorted(by_tool.items()):
        tv = sum(1 for r in t_rows if r.label == "true_vuln")
        fa = sum(1 for r in t_rows if r.label == "false_alarm")
        unc = sum(1 for r in t_rows if r.label == "uncertain")
        n_decided = tv + fa
        sp = round(tv / n_decided, 4) if n_decided > 0 else None
        ci_low, ci_high = _wilson_ci_95(tv, n_decided)
        per_tool[tool] = {
            "sampled_precision": sp,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "true_vuln": tv,
            "false_alarm": fa,
            "uncertain": unc,
            "n_decided": n_decided,
            "n_total": len(t_rows),
        }

    return {
        "audit_version": ver,
        "per_tool": per_tool,
        "created_at": latest_row.created_at.isoformat() if latest_row.created_at else None,
    }


def get_latest_latency_pass_from_db(db: Session) -> Optional[Dict[str, Any]]:
    """
    Pure DB read of the latest completed BenchmarkLatencyPass.
    In production (no research package), reads stored staleness if present or defaults to False.
    """
    latest = (
        db.query(BenchmarkLatencyPass)
        .filter(BenchmarkLatencyPass.status == "completed")
        .order_by(BenchmarkLatencyPass.pass_version.desc())
        .first()
    )
    if not latest:
        return None
    data = latest.to_dict()
    data.setdefault("stale", False)
    data.setdefault("stale_reasons", [])
    return data


class BenchmarkReadService:
    """Production read-only service for benchmark overview, repos, and repo detail."""

    def __init__(self, db: Session):
        self.db = db

    def check_and_timeout_stuck_jobs(self, timeout_seconds: Optional[int] = None) -> List[ResearchRepo]:
        now = datetime.now(timezone.utc)
        timed_out: List[ResearchRepo] = []
        running_repos = self.db.query(ResearchRepo).filter(ResearchRepo.status == "running").all()
        for r in running_repos:
            ref_time = r.last_heartbeat or r.updated_at or r.created_at
            if ref_time:
                if ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                diff = (now - ref_time).total_seconds()
                stage_limit = (
                    timeout_seconds
                    if timeout_seconds is not None
                    else STAGE_TIMEOUT_SECONDS.get(r.job_stage, DEFAULT_STAGE_TIMEOUT)
                )
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

    @staticmethod
    def _effective_metric_dict(m: BenchmarkMetric) -> Dict[str, Any]:
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

    def _get_latency_pass_summary(self) -> Optional[Dict[str, Any]]:
        """Hook overridden in research mode to also compute live staleness."""
        return get_latest_latency_pass_from_db(self.db)

    def get_overview_macro_metrics(self, verified_only: bool = False) -> Dict[str, Any]:
        if os.getenv("BENCHMARK_MODE", "readonly").strip().lower() == "research":
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
        verified_repos_count = len(
            [r for r in all_repos if not r.is_excluded and r.status in ("done", "partial") and r.label_quality == "verified"]
        )
        provisional_repos_count = total_repos_count - verified_repos_count
        total_loc = sum(r.loc for r in active_repos if r.loc)

        completed_runs = (
            self.db.query(BenchmarkRun.repo_id, BenchmarkRun.tool)
            .filter(
                BenchmarkRun.repo_id.in_(active_repo_ids),
                BenchmarkRun.status == "completed",
                BenchmarkRun.is_superseded == False,
            )
            .all()
            if active_repo_ids
            else []
        )
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

        sampled_latest = get_latest_sampled_precision_from_db(self.db)
        sampled_per_tool = (sampled_latest or {}).get("per_tool", {})

        latency_pass = self._get_latency_pass_summary()
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
                cls_fam_vals = [
                    e["classification_family_accuracy"]
                    for e in eff_list
                    if e.get("classification_family_accuracy") is not None
                ]

                clean_metrics = [
                    m for m in m_list
                    if m.repo and m.repo.repo_type != "intentionally_vulnerable" and m.repo.clean_sha
                ]
                fpr_avg = (
                    round(sum(m.false_positive_rate for m in clean_metrics) / len(clean_metrics), 4)
                    if clean_metrics
                    else 0.0
                )
                total_vuln_findings = sum(
                    int((m.counts_json or {}).get("total_vulnerable_findings", 0)) for m in m_list
                )
                total_clean_fp = sum(int((m.counts_json or {}).get("clean_fp", 0)) for m in clean_metrics)
                zero_findings_only = total_vuln_findings == 0 and total_clean_fp == 0

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
                    "classification_family_accuracy": (
                        round(sum(cls_fam_vals) / len(cls_fam_vals), 4) if cls_fam_vals else None
                    ),
                    "scan_latency": lp_latency,
                    "latency_spread": lp_spread,
                    "latency_measured": lp_measured,
                    "ast_latency": lp_latency if (tool_name == "codeguardian" and lp_measured) else None,
                    "codeql_db_create_median_s": (
                        lp_tool.get("db_create_median_s") if (tool_name == "codeql" and lp_tool) else None
                    ),
                    "codeql_analyze_median_s": (
                        lp_tool.get("analyze_median_s") if (tool_name == "codeql" and lp_tool) else None
                    ),
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
                    t_status = "not_installed"
                    t_detail = f"{tool_name} not available"

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

        if tools_macro.get("codeguardian", {}).get("has_data") and tools_macro.get("semgrep", {}).get("has_data"):
            cg_p = tools_macro.get("codeguardian", {}).get("precision")
            sem_p = tools_macro.get("semgrep", {}).get("precision")
            if cg_p is not None and sem_p is not None and abs(cg_p - sem_p) > 0.40:
                sanity_warnings.append(
                    "Extreme margin alert: CodeGuardian and Semgrep precision differ by >40%. Verify rule coverage."
                )

        active_snapshot = (
            self.db.query(BenchmarkSnapshot)
            .filter(BenchmarkSnapshot.is_active == True)
            .order_by(BenchmarkSnapshot.imported_at.desc())
            .first()
        )

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
            "snapshot": active_snapshot.to_dict() if active_snapshot else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_research_repos(self) -> List[Dict[str, Any]]:
        if os.getenv("BENCHMARK_MODE", "readonly").strip().lower() == "research":
            self.check_and_timeout_stuck_jobs()
        repos = self.db.query(ResearchRepo).order_by(ResearchRepo.created_at.desc()).all()
        req_tools = list(get_required_tools_prod())
        res = []
        for r in repos:
            repo_dict = r.to_dict()
            active_metrics = [m for m in r.metrics if not getattr(m, "is_superseded", False)]
            active_runs = [run for run in r.runs if not getattr(run, "is_superseded", False)]
            metrics = {m.tool: self._effective_metric_dict(m) for m in active_metrics}
            completed_runs_count = sum(1 for run in r.runs if run.status == "completed")
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
        repo = self.db.query(ResearchRepo).filter(ResearchRepo.id == repo_id).first()
        if not repo:
            repo = self.db.query(ResearchRepo).filter(ResearchRepo.name.ilike(f"%{repo_id}%")).first()
        if not repo:
            return None

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
