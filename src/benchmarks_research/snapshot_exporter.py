"""
Research-Only Benchmark Snapshot Exporter CLI.
Produces a versioned, checksummed JSON snapshot of benchmark results (repos, active runs,
findings, metrics, label versions, tool versions, latency pass, methodology text, and
CodeGuardian version), strictly excluding tokens, local absolute paths, temp dirs,
the synthetic fixture, and any user-scan data.

Usage:
    python -m src.benchmarks_research.snapshot_exporter --output snapshot.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.benchmarks_research.latency_pass import get_latest_latency_pass_summary
from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner
from src.db.benchmark_models import (
    BenchmarkFinding,
    BenchmarkMetric,
    BenchmarkRun,
    ResearchRepo,
    SampledPrecisionAudit,
)
from src.db.session import SessionLocal

SCHEMA_VERSION = "1.0"

_SENSITIVE_KEYS = {
    "raw_output_path",
    "cache_dir",
    "filtered_dir",
    "tmp_dir",
    "temp_dir",
    "local_path",
    "abs_path",
    "token",
    "api_key",
    "secret",
    "password",
}

_TOKEN_RE = re.compile(
    r"(ghp_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{10,}|gsk_[A-Za-z0-9_]{10,}|Bearer\s+[A-Za-z0-9._\-]{10,})"
)
_ABS_WIN_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|]+")
_ABS_TEMP_UNIX_RE = re.compile(r"/(?:tmp|var/tmp|Users|home)/[^\s\"'<>|]+")


def sanitize_value(val: Any, key_name: Optional[str] = None) -> Any:
    """Recursively strips local absolute paths, temp dirs, and tokens."""
    if key_name and key_name.lower() in _SENSITIVE_KEYS:
        return None
    if isinstance(val, dict):
        return {
            k: sanitize_value(v, k)
            for k, v in val.items()
            if k.lower() not in _SENSITIVE_KEYS
        }
    if isinstance(val, list):
        return [sanitize_value(item) for item in val]
    if isinstance(val, str):
        cleaned = _TOKEN_RE.sub("[REDACTED_TOKEN]", val)
        cleaned = _ABS_WIN_PATH_RE.sub("[LOCAL_PATH]", cleaned)
        cleaned = _ABS_TEMP_UNIX_RE.sub("[LOCAL_PATH]", cleaned)
        return cleaned
    return val


def compute_payload_sha256(payload_without_checksum: Dict[str, Any]) -> str:
    canonical = json.dumps(
        payload_without_checksum,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _is_synthetic_repo(repo: ResearchRepo) -> bool:
    name_l = (repo.name or "").lower()
    url_l = (repo.url or "").lower()
    return (
        "synthetic/positive-control" in name_l
        or "positive-control" in name_l
        or url_l.startswith("file://")
        or not url_l.startswith("https://")
    )


def build_snapshot_payload(db: Session, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parents[2]
    cg_version = CodeGuardianRunner().get_version()

    methodology_text = ""
    for candidate in (root / "METHODOLOGY.md", root / "benchmarks" / "METHODOLOGY.md"):
        if candidate.exists():
            methodology_text = candidate.read_text(encoding="utf-8")
            break

    all_repos = db.query(ResearchRepo).order_by(ResearchRepo.created_at.asc()).all()
    repos = [r for r in all_repos if not _is_synthetic_repo(r)]
    repo_ids = [r.id for r in repos]

    runs = (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.repo_id.in_(repo_ids), BenchmarkRun.is_superseded == False)
        .order_by(BenchmarkRun.started_at.asc())
        .all()
        if repo_ids
        else []
    )
    run_ids = [run.id for run in runs]

    findings = (
        db.query(BenchmarkFinding)
        .filter(BenchmarkFinding.run_id.in_(run_ids))
        .order_by(BenchmarkFinding.created_at.asc())
        .all()
        if run_ids
        else []
    )

    metrics = (
        db.query(BenchmarkMetric)
        .filter(BenchmarkMetric.repo_id.in_(repo_ids), BenchmarkMetric.is_superseded == False)
        .order_by(BenchmarkMetric.computed_at.asc())
        .all()
        if repo_ids
        else []
    )

    label_versions: Dict[str, Any] = {}
    for r in repos:
        gt_rel = (r.ground_truth_path or "").replace("\\", "/")
        manifest_sha = None
        manifest_data = None
        if gt_rel:
            gt_file = root / gt_rel
            if gt_file.exists():
                raw_bytes = gt_file.read_bytes()
                manifest_sha = hashlib.sha256(raw_bytes).hexdigest()
                try:
                    manifest_data = json.loads(raw_bytes.decode("utf-8"))
                except Exception:
                    manifest_data = None
        label_versions[r.name] = {
            "ground_truth_path": gt_rel,
            "label_quality": r.label_quality,
            "manifest_sha256": manifest_sha,
            "manifest": sanitize_value(manifest_data),
        }

    tool_versions: Dict[str, str] = {}
    for run in runs:
        if run.status == "completed" and run.tool_version and run.tool_version != "unknown":
            tool_versions[run.tool] = run.tool_version

    latency_pass = get_latest_latency_pass_summary(db)
    if latency_pass:
        for t, ver in (latency_pass.get("tool_versions") or {}).items():
            tool_versions.setdefault(t, ver)

    latest_audit = (
        db.query(SampledPrecisionAudit)
        .order_by(SampledPrecisionAudit.audit_version.desc())
        .first()
    )
    sampled_audits: List[Dict[str, Any]] = []
    if latest_audit:
        audit_rows = (
            db.query(SampledPrecisionAudit)
            .filter(SampledPrecisionAudit.audit_version == latest_audit.audit_version)
            .all()
        )
        sampled_audits = [sanitize_value(a.to_dict()) for a in audit_rows]

    serialized_repos = []
    for r in repos:
        d = r.to_dict()
        d["ground_truth_path"] = (r.ground_truth_path or "").replace("\\", "/")
        d["scope_override"] = r.scope_override
        serialized_repos.append(sanitize_value(d))

    serialized_runs = []
    for run in runs:
        d = run.to_dict()
        d["raw_output_path"] = None
        d["metadata"] = sanitize_value(run.run_metadata or {})
        serialized_runs.append(sanitize_value(d))

    serialized_findings = []
    for f in findings:
        d = f.to_dict()
        d["raw_finding"] = sanitize_value(f.raw_finding or {})
        serialized_findings.append(sanitize_value(d))

    serialized_metrics = [sanitize_value(m.to_dict()) for m in metrics]

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "codeguardian_version": cg_version,
        "tool_versions": tool_versions,
        "label_versions": label_versions,
        "latency_pass": sanitize_value(latency_pass),
        "sampled_precision_audits": sampled_audits,
        "methodology_text": methodology_text,
        "repos": serialized_repos,
        "runs": serialized_runs,
        "findings": serialized_findings,
        "metrics": serialized_metrics,
    }

    # Safety check: verify no synthetic fixture or unredacted tokens/local paths remain
    serialized_str = json.dumps(payload, ensure_ascii=False)
    if "synthetic/positive-control" in serialized_str.lower():
        raise ValueError("Snapshot export safety check failed: synthetic fixture leaked into payload.")
    if _TOKEN_RE.search(serialized_str):
        raise ValueError("Snapshot export safety check failed: token pattern detected in payload.")

    payload["sha256"] = compute_payload_sha256(payload)
    return payload


def export_snapshot_to_file(db: Session, output_path: Path, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    payload = build_snapshot_payload(db, repo_root=repo_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "output_path": str(output_path),
        "schema_version": payload["schema_version"],
        "snapshot_id": payload["snapshot_id"],
        "sha256": payload["sha256"],
        "repos": len(payload["repos"]),
        "runs": len(payload["runs"]),
        "findings": len(payload["findings"]),
        "metrics": len(payload["metrics"]),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export versioned, checksummed benchmark snapshot (research-only).")
    parser.add_argument(
        "--output",
        "-o",
        default=f"benchmarks/snapshots/benchmark_snapshot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json",
        help="Output JSON snapshot path",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        summary = export_snapshot_to_file(db, Path(args.output))
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
