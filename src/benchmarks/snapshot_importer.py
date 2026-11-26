"""
Production Benchmark Snapshot Importer (CLI Only — No Web Endpoint).
Validates schema and SHA-256 checksum, supports --dry-run, applies atomically in a
single database transaction, preserves the previous snapshot for rollback, and
never touches user-scan tables.

Usage:
    python -m src.benchmarks.snapshot_importer --input snapshot.json [--dry-run]
    python -m src.benchmarks.snapshot_importer --rollback
"""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.benchmark_models import (
    BenchmarkFinding,
    BenchmarkLatencyPass,
    BenchmarkMetric,
    BenchmarkRun,
    BenchmarkSnapshot,
    ResearchRepo,
    SampledPrecisionAudit,
)
from src.db.models import Base
from src.db.session import get_benchmark_importer_session, init_db

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "snapshot_id",
    "generated_at",
    "sha256",
    "repos",
    "runs",
    "findings",
    "metrics",
}


def compute_snapshot_sha256(payload_without_checksum: Dict[str, Any]) -> str:
    canonical = json.dumps(
        payload_without_checksum,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_snapshot_payload(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_data, dict):
        raise ValueError("Snapshot root must be a JSON object.")

    missing = REQUIRED_TOP_LEVEL_KEYS - set(raw_data.keys())
    if missing:
        raise ValueError(f"Snapshot missing required keys: {sorted(missing)}")

    schema_ver = str(raw_data.get("schema_version") or "")
    if schema_ver not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported snapshot schema_version '{schema_ver}'. Expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}."
        )

    expected_sha = str(raw_data.get("sha256") or "")
    payload_copy = {k: v for k, v in raw_data.items() if k != "sha256"}
    actual_sha = compute_snapshot_sha256(payload_copy)
    if expected_sha != actual_sha:
        raise ValueError(
            f"Snapshot SHA-256 checksum mismatch: expected {expected_sha}, computed {actual_sha}."
        )

    for list_key in ("repos", "runs", "findings", "metrics"):
        if not isinstance(raw_data.get(list_key), list):
            raise ValueError(f"Snapshot '{list_key}' must be a list.")

    return raw_data


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _apply_snapshot_rows(db: Session, payload: Dict[str, Any], snapshot_row_id: str) -> Dict[str, int]:
    """Applies snapshot rows into benchmark tables inside the caller's transaction."""
    # Supersede existing active runs, metrics, and latency passes (preserve for rollback)
    db.query(BenchmarkRun).filter(BenchmarkRun.is_superseded == False).update(
        {"is_superseded": True}, synchronize_session=False
    )
    db.query(BenchmarkMetric).filter(BenchmarkMetric.is_superseded == False).update(
        {"is_superseded": True}, synchronize_session=False
    )
    db.query(BenchmarkLatencyPass).filter(BenchmarkLatencyPass.is_superseded == False).update(
        {"is_superseded": True}, synchronize_session=False
    )

    existing_repos = {r.id: r for r in db.query(ResearchRepo).all()}
    repos_added = 0
    repos_updated = 0
    for rd in payload.get("repos", []):
        rid = rd["id"]
        repo = existing_repos.get(rid)
        if repo is None:
            repo = db.query(ResearchRepo).filter(ResearchRepo.name == rd["name"]).first()
        if repo is None:
            repo = ResearchRepo(
                id=rid,
                name=rd["name"],
                url=rd["url"],
            )
            db.add(repo)
            repos_added += 1
        else:
            repos_updated += 1
        repo.url = rd["url"]
        repo.pinned_sha = rd.get("pinned_sha")
        repo.clean_sha = rd.get("clean_sha")
        repo.language = rd.get("language", "unknown")
        repo.loc = rd.get("loc")
        repo.ground_truth_path = rd.get("ground_truth_path", "")
        repo.status = rd.get("status", "done")
        repo.cve_id = rd.get("cve_id")
        repo.repo_type = rd.get("repo_type", "cve_fix")
        repo.fix_commit = rd.get("fix_commit")
        repo.parent_commit = rd.get("parent_commit")
        repo.label_quality = rd.get("label_quality", "provisional")
        repo.is_excluded = bool(rd.get("is_excluded", False))
        repo.exclusion_reason = rd.get("exclusion_reason")
        repo.job_stage = rd.get("job_stage", "done")
        repo.job_progress = float(rd.get("job_progress", 1.0) or 1.0)
        repo.job_error = rd.get("job_error")
        repo.ignored_candidates = rd.get("ignored_candidates") or []
        repo.scope_override = rd.get("scope_override")
        repo.notes = rd.get("notes")

    db.flush()

    max_run_ver = max((r.run_version or 1 for r in db.query(BenchmarkRun).all()), default=0)
    next_run_ver = max_run_ver + 1
    run_id_map: Dict[str, str] = {}
    for run_d in payload.get("runs", []):
        new_run_id = str(uuid.uuid4())
        run_id_map[run_d["id"]] = new_run_id
        meta = dict(run_d.get("metadata") or {})
        meta["imported_snapshot_id"] = snapshot_row_id
        db.add(
            BenchmarkRun(
                id=new_run_id,
                repo_id=run_d["repo_id"],
                tool=run_d["tool"],
                tool_version=run_d.get("tool_version", "unknown"),
                started_at=_parse_dt(run_d.get("started_at")) or datetime.now(timezone.utc),
                duration_s=float(run_d.get("duration_s", 0.0) or 0.0),
                raw_output_path=None,
                status=run_d.get("status", "completed"),
                error_message=run_d.get("error_message"),
                run_metadata=meta,
                run_version=next_run_ver,
                is_superseded=False,
            )
        )

    db.flush()

    findings_added = 0
    for f_d in payload.get("findings", []):
        mapped_run_id = run_id_map.get(f_d.get("run_id", ""))
        if not mapped_run_id:
            continue
        db.add(
            BenchmarkFinding(
                id=str(uuid.uuid4()),
                run_id=mapped_run_id,
                repo_id=f_d["repo_id"],
                tool=f_d["tool"],
                file_path=f_d["file_path"],
                line_start=int(f_d["line_start"]),
                line_end=int(f_d["line_end"]),
                cwe=f_d.get("cwe"),
                normalized_cwe=f_d.get("normalized_cwe"),
                severity=f_d.get("severity", "MEDIUM"),
                rule_id=f_d.get("rule_id"),
                match_result=f_d.get("match_result", "FP"),
                matched_ground_truth_id=f_d.get("matched_ground_truth_id"),
                line_distance=f_d.get("line_distance"),
                cwe_matched=bool(f_d.get("cwe_matched", False)),
                raw_finding=f_d.get("raw_finding") or {},
            )
        )
        findings_added += 1

    metrics_added = 0
    for m_d in payload.get("metrics", []):
        db.add(
            BenchmarkMetric(
                id=str(uuid.uuid4()),
                repo_id=m_d["repo_id"],
                tool=m_d["tool"],
                tool_version=m_d.get("tool_version", "unknown"),
                precision=float(m_d["precision"]) if m_d.get("precision") is not None else 0.0,
                recall=float(m_d["recall"]) if m_d.get("recall") is not None else 0.0,
                false_positive_rate=float(m_d.get("false_positive_rate") or 0.0),
                localization_accuracy=float(m_d["localization_accuracy"]) if m_d.get("localization_accuracy") is not None else 0.0,
                classification_accuracy=float(m_d["classification_accuracy"]) if m_d.get("classification_accuracy") is not None else 0.0,
                scan_latency=float(m_d.get("scan_latency") or 0.0),
                counts_json=m_d.get("counts") or {},
                run_version=next_run_ver,
                is_superseded=False,
                computed_at=_parse_dt(m_d.get("computed_at")) or datetime.now(timezone.utc),
            )
        )
        metrics_added += 1

    lp_d = payload.get("latency_pass")
    if lp_d and lp_d.get("status") == "completed":
        max_lp_ver = max((p.pass_version or 0 for p in db.query(BenchmarkLatencyPass).all()), default=0)
        db.add(
            BenchmarkLatencyPass(
                id=str(uuid.uuid4()),
                pass_version=max_lp_ver + 1,
                is_superseded=False,
                status="completed",
                repeats=int(lp_d.get("repeats", 3) or 3),
                repo_ids=lp_d.get("repo_ids") or [],
                host_info=lp_d.get("host_info") or {},
                scope_policy_hash=lp_d.get("scope_policy_hash", "snapshot"),
                tool_versions=lp_d.get("tool_versions") or {},
                tool_rulesets=lp_d.get("tool_rulesets") or {},
                results_json=lp_d.get("results") or {},
                started_at=_parse_dt(lp_d.get("started_at")) or datetime.now(timezone.utc),
                completed_at=_parse_dt(lp_d.get("completed_at")) or datetime.now(timezone.utc),
            )
        )

    audits = payload.get("sampled_precision_audits") or []
    if audits:
        max_audit_ver = max((a.audit_version or 0 for a in db.query(SampledPrecisionAudit).all()), default=0)
        next_audit_ver = max_audit_ver + 1
        for a_d in audits:
            db.add(
                SampledPrecisionAudit(
                    id=str(uuid.uuid4()),
                    audit_version=next_audit_ver,
                    sample_id=a_d["sample_id"],
                    tool=a_d["tool"],
                    repo_id=a_d["repo_id"],
                    finding_id=a_d["finding_id"],
                    file_path=a_d["file_path"],
                    line_start=int(a_d["line_start"]),
                    cwe=a_d.get("cwe"),
                    label=a_d["label"],
                    notes=a_d.get("notes"),
                    labeled_by=a_d.get("labeled_by", "snapshot"),
                )
            )

    return {
        "repos_added": repos_added,
        "repos_updated": repos_updated,
        "runs_imported": len(run_id_map),
        "findings_imported": findings_added,
        "metrics_imported": metrics_added,
        "latency_pass_imported": 1 if (lp_d and lp_d.get("status") == "completed") else 0,
        "audits_imported": len(audits),
    }


def import_snapshot(
    db: Session,
    snapshot_path: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    raw_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload = validate_snapshot_payload(raw_data)

    existing_repos = {r.id for r in db.query(ResearchRepo).all()}
    incoming_repos = payload.get("repos", [])
    repos_to_add = [r["name"] for r in incoming_repos if r["id"] not in existing_repos]
    repos_to_update = [r["name"] for r in incoming_repos if r["id"] in existing_repos]
    prev_active = (
        db.query(BenchmarkSnapshot)
        .filter(BenchmarkSnapshot.is_active == True)
        .order_by(BenchmarkSnapshot.imported_at.desc())
        .first()
    )

    if dry_run:
        return {
            "dry_run": True,
            "valid_checksum": True,
            "snapshot_id": payload["snapshot_id"],
            "schema_version": payload["schema_version"],
            "generated_at": payload["generated_at"],
            "sha256": payload["sha256"],
            "previous_snapshot_id": prev_active.snapshot_id if prev_active else None,
            "changes": {
                "repos_to_add": repos_to_add,
                "repos_to_update": repos_to_update,
                "runs_to_import": len(payload.get("runs", [])),
                "findings_to_import": len(payload.get("findings", [])),
                "metrics_to_import": len(payload.get("metrics", [])),
                "latency_pass_present": bool(payload.get("latency_pass")),
                "sampled_audits_to_import": len(payload.get("sampled_precision_audits", [])),
            },
        }

    try:
        if prev_active:
            prev_active.is_active = False

        snap_row = BenchmarkSnapshot(
            id=str(uuid.uuid4()),
            snapshot_id=payload["snapshot_id"],
            schema_version=payload["schema_version"],
            sha256=payload["sha256"],
            generated_at=payload["generated_at"],
            codeguardian_version=payload.get("codeguardian_version"),
            repos_count=len(incoming_repos),
            is_active=True,
            previous_snapshot_id=prev_active.id if prev_active else None,
            payload_json=payload,
        )
        db.add(snap_row)
        db.flush()

        counts = _apply_snapshot_rows(db, payload, snap_row.id)
        db.commit()
        return {
            "dry_run": False,
            "status": "imported",
            "snapshot_id": snap_row.snapshot_id,
            "previous_snapshot_id": prev_active.snapshot_id if prev_active else None,
            "sha256": snap_row.sha256,
            "counts": counts,
        }
    except Exception:
        db.rollback()
        raise


def rollback_snapshot(db: Session) -> Dict[str, Any]:
    """Rolls back atomically to the previous imported snapshot."""
    current = (
        db.query(BenchmarkSnapshot)
        .filter(BenchmarkSnapshot.is_active == True)
        .order_by(BenchmarkSnapshot.imported_at.desc())
        .first()
    )
    if not current or not current.previous_snapshot_id:
        raise ValueError("No previous snapshot available for rollback.")

    prev = (
        db.query(BenchmarkSnapshot)
        .filter(BenchmarkSnapshot.id == current.previous_snapshot_id)
        .first()
    )
    if not prev or not prev.payload_json:
        raise ValueError("Previous snapshot payload is missing; cannot roll back.")

    try:
        current.is_active = False
        prev.is_active = True
        counts = _apply_snapshot_rows(db, prev.payload_json, prev.id)
        db.commit()
        return {
            "status": "rolled_back",
            "rolled_back_from": current.snapshot_id,
            "restored_snapshot_id": prev.snapshot_id,
            "counts": counts,
        }
    except Exception:
        db.rollback()
        raise


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import benchmark snapshot into production DB (CLI-only).")
    parser.add_argument("--input", "-i", help="Path to snapshot JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview changes without writing to DB")
    parser.add_argument("--rollback", action="store_true", help="Roll back to the previous imported snapshot")
    args = parser.parse_args(argv)

    imp_engine, db = get_benchmark_importer_session()
    init_db(imp_engine)
    try:
        if args.rollback:
            res = rollback_snapshot(db)
        elif args.input:
            res = import_snapshot(db, Path(args.input), dry_run=args.dry_run)
        else:
            parser.error("Provide --input <path> or --rollback.")
            return 2
        print(json.dumps(res, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
