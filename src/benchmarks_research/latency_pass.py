"""
Isolated Sequential Latency Pass (separate from detection runs).
Runs every installed tool sequentially on the vulnerable commit's filtered source copy
with N repeats (default 3), storing median, spread, CodeQL DB-create vs analyze breakdown,
host hardware/OS metadata, and staleness keys (tool versions, rulesets, scope policy hash).
"""
from __future__ import annotations

import logging
import os
import platform
import statistics
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.benchmarks_research.ground_truth_loader import GroundTruthLoader
from src.benchmarks_research.pipeline import (
    _safe_git_clone_and_checkout,
    get_runner_ruleset_id,
)
from src.benchmarks_research.runners.bandit_runner import BanditRunner
from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner
from src.benchmarks_research.runners.codeql_runner import CodeQLRunner
from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner
from src.benchmarks_research.runners.sonarqube_runner import SonarQubeRunner
from src.benchmarks_research.scope import ScopePolicy, build_filtered_source_copy, compute_scope_policy_hash
from src.db.benchmark_models import BenchmarkLatencyPass, ResearchRepo
from src.db.session import SessionLocal

logger = logging.getLogger("ai_engineer.benchmarks.latency_pass")


def _all_runners():
    return [
        CodeGuardianRunner(),
        SemgrepRunner(),
        CodeQLRunner(),
        SonarQubeRunner(),
        BanditRunner(),
    ]


def _get_runner(tool: str):
    for r in _all_runners():
        if r.tool_name == tool:
            return r
    return None


def collect_host_info() -> Dict[str, Any]:
    """Collects CPU model, core count, RAM (GB), and OS metadata for reproducibility."""
    cpu_model = platform.processor() or "unknown"
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if val:
                cpu_model = str(val).strip()
        except Exception:
            pass

    ram_gb: Optional[float] = None
    physical_cores: Optional[int] = None
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
        physical_cores = psutil.cpu_count(logical=False)
    except Exception:
        if platform.system() == "Windows":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                mem = MEMORYSTATUSEX()
                mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                    ram_gb = round(mem.ullTotalPhys / (1024 ** 3), 2)
            except Exception:
                pass

    return {
        "cpu_model": cpu_model,
        "cpu_cores_logical": os.cpu_count(),
        "cpu_cores_physical": physical_cores,
        "ram_gb": ram_gb,
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "machine": platform.machine(),
    }


def get_current_tool_state() -> Tuple[str, Dict[str, str], Dict[str, str]]:
    """Returns (scope_policy_hash, tool_versions, tool_rulesets) for installed tools."""
    scope_hash = compute_scope_policy_hash()
    versions: Dict[str, str] = {}
    rulesets: Dict[str, str] = {}
    for runner in _all_runners():
        if runner.is_available():
            versions[runner.tool_name] = runner.get_version()
            rulesets[runner.tool_name] = get_runner_ruleset_id(runner)
    return scope_hash, versions, rulesets


def is_latency_pass_stale(pass_row: BenchmarkLatencyPass) -> Tuple[bool, List[str]]:
    """
    A latency pass is marked stale when any tool version, ruleset, or scope policy
    changes after it was recorded.
    """
    reasons: List[str] = []
    cur_scope, cur_versions, cur_rulesets = get_current_tool_state()

    if pass_row.scope_policy_hash != cur_scope:
        reasons.append(f"scope_policy changed ({pass_row.scope_policy_hash} -> {cur_scope})")

    recorded_versions = pass_row.tool_versions or {}
    recorded_rulesets = pass_row.tool_rulesets or {}

    for tool, cur_ver in cur_versions.items():
        old_ver = recorded_versions.get(tool)
        if old_ver is None:
            reasons.append(f"{tool} newly installed ({cur_ver})")
        elif old_ver != cur_ver:
            reasons.append(f"{tool} version changed ({old_ver} -> {cur_ver})")

    for tool, cur_rs in cur_rulesets.items():
        old_rs = recorded_rulesets.get(tool)
        if old_rs is not None and old_rs != cur_rs:
            reasons.append(f"{tool} ruleset changed ({old_rs} -> {cur_rs})")

    return (len(reasons) > 0), reasons


def _median_and_spread(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    med = round(statistics.median(values), 4)
    spread = round(max(values) - min(values), 4) if len(values) > 1 else 0.0
    return med, spread


def run_latency_pass(
    db: Session,
    repo_ids: Optional[List[str]] = None,
    repeats: int = 3,
) -> BenchmarkLatencyPass:
    """
    Executes an isolated sequential latency pass over the selected repositories.
    Refuses to start if any detection pipeline or latency pass is currently running.
    """
    running_repo = db.query(ResearchRepo).filter(ResearchRepo.status == "running").first()
    if running_repo:
        raise ValueError(
            f"Cannot start latency pass while '{running_repo.name}' is running ({running_repo.job_stage})."
        )
    running_pass = db.query(BenchmarkLatencyPass).filter(BenchmarkLatencyPass.status == "running").first()
    if running_pass:
        raise ValueError(f"Latency pass v{running_pass.pass_version} is already running.")

    if repo_ids:
        repos = db.query(ResearchRepo).filter(ResearchRepo.id.in_(repo_ids)).all()
    else:
        repos = (
            db.query(ResearchRepo)
            .filter(ResearchRepo.is_excluded == False, ResearchRepo.status.in_(["done", "partial"]))
            .all()
        )
    if not repos:
        raise ValueError("No eligible repositories selected for latency pass.")

    max_ver = db.query(func.max(BenchmarkLatencyPass.pass_version)).scalar() or 0
    scope_hash, tool_versions, tool_rulesets = get_current_tool_state()
    host_info = collect_host_info()

    pass_row = BenchmarkLatencyPass(
        pass_version=int(max_ver) + 1,
        is_superseded=False,
        status="running",
        repeats=repeats,
        repo_ids=[r.id for r in repos],
        host_info=host_info,
        scope_policy_hash=scope_hash,
        tool_versions=tool_versions,
        tool_rulesets=tool_rulesets,
        results_json={},
    )
    db.add(pass_row)
    db.commit()
    db.refresh(pass_row)

    installed_tools = list(tool_versions.keys())
    per_repo_results: Dict[str, Any] = {}
    macro_per_tool: Dict[str, List[Dict[str, Any]]] = {t: [] for t in installed_tools}

    try:
        for repo in repos:
            vuln_sha = repo.pinned_sha or repo.parent_commit
            if not vuln_sha:
                raise ValueError(f"Repository '{repo.name}' has no pinned vulnerable commit SHA.")

            labeled_files: List[str] = []
            if repo.ground_truth_path:
                try:
                    gt = GroundTruthLoader().load_file(Path(repo.ground_truth_path))
                    labeled_files = [
                        v.file_path for v in (gt.labeled_findings or []) if getattr(v, "file_path", None)
                    ]
                except Exception:
                    labeled_files = []

            with tempfile.TemporaryDirectory() as tmp_root:
                raw_dir = Path(tmp_root) / "raw"
                filtered_dir = Path(tmp_root) / "filtered_vuln"

                _safe_git_clone_and_checkout(
                    repo.url,
                    raw_dir,
                    vuln_sha,
                    loc=repo.loc,
                )
                scope_stats = build_filtered_source_copy(
                    raw_dir,
                    filtered_dir,
                    policy=ScopePolicy.from_override(repo.scope_override),
                    labeled_files=labeled_files,
                )
                in_scope_loc = max(int(scope_stats.get("in_scope_loc", 0) or 0), 1)
                kloc = in_scope_loc / 1000.0

                repo_tool_results: Dict[str, Any] = {}
                for tool in installed_tools:
                    runner = _get_runner(tool)
                    if not runner:
                        continue
                    durations_s: List[float] = []
                    latencies_kloc: List[float] = []
                    db_create_s: List[float] = []
                    analyze_s: List[float] = []

                    for _ in range(repeats):
                        res = runner.run(filtered_dir)
                        if res.status != "completed":
                            raise RuntimeError(
                                f"Tool '{tool}' failed during latency pass on '{repo.name}': "
                                f"{res.status} ({res.error_message})"
                            )
                        dur = round(float(res.duration_s), 4)
                        durations_s.append(dur)
                        latencies_kloc.append(round(dur / kloc, 4))
                        if tool == "codeql":
                            meta = res.metadata or {}
                            db_val = meta.get("db_build_time_s") if meta.get("db_build_time_s") is not None else meta.get("db_build_s")
                            an_val = meta.get("analysis_time_s") if meta.get("analysis_time_s") is not None else meta.get("analysis_s")
                            if db_val is not None:
                                db_create_s.append(round(float(db_val), 4))
                            if an_val is not None:
                                analyze_s.append(round(float(an_val), 4))

                    med_dur, spr_dur = _median_and_spread(durations_s)
                    med_lat, spr_lat = _median_and_spread(latencies_kloc)
                    entry: Dict[str, Any] = {
                        "runs_s": durations_s,
                        "median_s": med_dur,
                        "spread_s": spr_dur,
                        "min_s": min(durations_s),
                        "max_s": max(durations_s),
                        "median_latency_per_kloc": med_lat,
                        "spread_latency_per_kloc": spr_lat,
                    }
                    if tool == "codeql":
                        db_med, db_spr = _median_and_spread(db_create_s)
                        an_med, an_spr = _median_and_spread(analyze_s)
                        entry.update({
                            "db_create_runs_s": db_create_s,
                            "db_create_median_s": db_med,
                            "db_create_spread_s": db_spr,
                            "analyze_runs_s": analyze_s,
                            "analyze_median_s": an_med,
                            "analyze_spread_s": an_spr,
                        })
                    repo_tool_results[tool] = entry
                    macro_per_tool[tool].append(entry)

                per_repo_results[repo.id] = {
                    "repo_name": repo.name,
                    "vuln_sha": vuln_sha,
                    "in_scope_loc": in_scope_loc,
                    "tools": repo_tool_results,
                }

        per_tool_macro: Dict[str, Any] = {}
        for tool, entries in macro_per_tool.items():
            if not entries:
                continue
            lat_vals = [e["median_latency_per_kloc"] for e in entries if e["median_latency_per_kloc"] is not None]
            dur_vals = [e["median_s"] for e in entries if e["median_s"] is not None]
            spr_lat_vals = [e["spread_latency_per_kloc"] for e in entries if e["spread_latency_per_kloc"] is not None]
            macro_entry: Dict[str, Any] = {
                "median_latency_per_kloc": round(sum(lat_vals) / len(lat_vals), 4) if lat_vals else None,
                "spread_latency_per_kloc": round(max(spr_lat_vals), 4) if spr_lat_vals else None,
                "median_duration_s": round(sum(dur_vals) / len(dur_vals), 4) if dur_vals else None,
                "spread_duration_s": round(max(e["spread_s"] for e in entries if e["spread_s"] is not None), 4),
                "sample_repos": len(entries),
                "repeats": repeats,
            }
            if tool == "codeql":
                db_meds = [e["db_create_median_s"] for e in entries if e.get("db_create_median_s") is not None]
                an_meds = [e["analyze_median_s"] for e in entries if e.get("analyze_median_s") is not None]
                macro_entry["db_create_median_s"] = round(sum(db_meds) / len(db_meds), 4) if db_meds else None
                macro_entry["analyze_median_s"] = round(sum(an_meds) / len(an_meds), 4) if an_meds else None
            per_tool_macro[tool] = macro_entry

        # Mark older completed passes superseded (append-only: never delete)
        db.query(BenchmarkLatencyPass).filter(
            BenchmarkLatencyPass.id != pass_row.id,
            BenchmarkLatencyPass.is_superseded == False,
        ).update({"is_superseded": True}, synchronize_session=False)

        pass_row.results_json = {
            "per_repo": per_repo_results,
            "per_tool_macro": per_tool_macro,
        }
        pass_row.status = "completed"
        pass_row.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(pass_row)
        return pass_row

    except Exception as exc:
        logger.exception("Latency pass failed: %s", exc)
        pass_row.status = "failed"
        pass_row.error_message = str(exc)
        pass_row.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(pass_row)
        raise


def get_latest_latency_pass_summary(db: Session) -> Optional[Dict[str, Any]]:
    """Returns the latest completed latency pass with staleness info, or None."""
    latest = (
        db.query(BenchmarkLatencyPass)
        .filter(BenchmarkLatencyPass.status == "completed")
        .order_by(BenchmarkLatencyPass.pass_version.desc())
        .first()
    )
    if not latest:
        return None
    stale, stale_reasons = is_latency_pass_stale(latest)
    data = latest.to_dict()
    data["stale"] = stale
    data["stale_reasons"] = stale_reasons
    return data


def trigger_latency_pass_async(repo_ids: Optional[List[str]] = None, repeats: int = 3) -> None:
    """Starts an isolated latency pass in a background thread."""
    def _worker() -> None:
        db = SessionLocal()
        try:
            run_latency_pass(db, repo_ids=repo_ids, repeats=repeats)
        except Exception as exc:
            logger.error("Async latency pass failed: %s", exc)
        finally:
            db.close()

    t = threading.Thread(target=_worker, daemon=True, name="benchmark-latency-pass")
    t.start()
