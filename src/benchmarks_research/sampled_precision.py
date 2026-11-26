"""
Blinded Sampled-Precision Export Workflow (Step 1).

Exports a deterministic (seed=42), repo-stratified random sample of up to 30
unmatched (FP) findings per tool across active repositories, deduplicates
pooled findings (same repo, same file, lines within ±3, same normalized CWE),
strips tool names and rule IDs, and writes:
  - Public blinded CSV: benchmarks/triage/sampled_precision_sample.csv
  - Private mapping JSON (import-only): benchmarks/triage/sampled_precision_map.json
"""
from __future__ import annotations

import csv
import io
import json
import math
import random
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.benchmarks_research.ground_truth_loader import GroundTruthLoader
from src.db.benchmark_models import BenchmarkFinding, BenchmarkRun, ResearchRepo, SampledPrecisionAudit

VALID_TRIAGE_LABELS = {"true_vuln", "false_alarm", "uncertain"}

DEFAULT_TRIAGE_DIR = Path("benchmarks/triage")
DEFAULT_SAMPLE_CSV = DEFAULT_TRIAGE_DIR / "sampled_precision_sample.csv"
DEFAULT_MAP_JSON = DEFAULT_TRIAGE_DIR / "sampled_precision_map.json"
ALLOWED_TOOLS = ("codeguardian", "semgrep", "codeql", "bandit")

_TOOL_NAME_RE = re.compile(r"\b(codeguardian|semgrep|codeql|bandit|sonarqube)\b", re.IGNORECASE)


def _bare_cache_dir(repo_url: str) -> Optional[Path]:
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    owner, slug = parts[-2], parts[-1].removesuffix(".git")
    candidate = Path("data/benchmark_bare_cache") / f"{owner}__{slug}.git"
    return candidate if candidate.exists() else None


def _extract_code_context(
    cache_map: Dict[Tuple[str, str], List[str]],
    repo_url: str,
    sha: str,
    rel_file: str,
    line_no: int,
    radius: int = 7,
) -> str:
    """Extracts ~15 lines of code centered on `line_no` from the bare git cache."""
    key = (sha, rel_file)
    if key not in cache_map:
        bare = _bare_cache_dir(repo_url)
        lines: List[str] = []
        if bare and sha:
            try:
                out = subprocess.check_output(
                    ["git", "-C", str(bare), "show", f"{sha}:{rel_file}"],
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
                lines = out.splitlines()
            except Exception:
                lines = []
        cache_map[key] = lines

    lines = cache_map[key]
    if not lines:
        return "(source unavailable in local bare cache)"
    start = max(1, line_no - radius)
    end = min(len(lines), line_no + radius)
    formatted = []
    for ln in range(start, end + 1):
        marker = ">>>" if ln == line_no else "   "
        formatted.append(f"{marker} {ln:4d}: {lines[ln - 1]}")
    return "\n".join(formatted)


def _extract_message(raw_finding: Optional[Dict[str, Any]]) -> str:
    if not raw_finding:
        return ""
    msg = (
        raw_finding.get("message")
        or raw_finding.get("description")
        or raw_finding.get("title")
        or raw_finding.get("issue_text")
        or ""
    )
    if isinstance(msg, dict):
        msg = msg.get("text", "")
    # Blind any accidental tool name mentions
    return _TOOL_NAME_RE.sub("[TOOL]", str(msg)).strip()


def _stratified_sample_indices(
    by_repo: Dict[str, List[Any]],
    k: int,
    rng: random.Random,
) -> List[Any]:
    """Deterministically samples up to k items across repos proportionally (min 1 when available)."""
    total = sum(len(v) for v in by_repo.values())
    if total <= k:
        pool = [item for items in by_repo.values() for item in items]
        rng.shuffle(pool)
        return pool

    repo_keys = sorted(by_repo.keys())
    shuffled_by_repo: Dict[str, List[Any]] = {}
    for rk in repo_keys:
        items = list(by_repo[rk])
        items.sort(key=lambda x: (x.file_path, x.line_start, x.id))
        rng.shuffle(items)
        shuffled_by_repo[rk] = items

    # Proportional allocation with floor 1 per non-empty stratum
    alloc: Dict[str, int] = {rk: 1 for rk in repo_keys if shuffled_by_repo[rk]}
    remaining = k - len(alloc)
    if remaining < 0:
        # More repos than k: sample 1 from k randomly chosen repos
        chosen = rng.sample(list(alloc.keys()), k)
        return [shuffled_by_repo[rk][0] for rk in chosen]

    capacities = {rk: len(shuffled_by_repo[rk]) - alloc[rk] for rk in alloc}
    total_cap = sum(capacities.values())
    if total_cap > 0 and remaining > 0:
        for rk in repo_keys:
            if rk in capacities and capacities[rk] > 0:
                extra = min(capacities[rk], int(remaining * capacities[rk] / total_cap))
                alloc[rk] += extra
        # Distribute any rounding remainder
        leftover = k - sum(alloc.values())
        for rk in sorted(repo_keys, key=lambda x: capacities.get(x, 0), reverse=True):
            if leftover <= 0:
                break
            room = len(shuffled_by_repo[rk]) - alloc.get(rk, 0)
            if room > 0:
                take = min(room, leftover)
                alloc[rk] = alloc.get(rk, 0) + take
                leftover -= take

    sampled: List[Any] = []
    for rk in repo_keys:
        sampled.extend(shuffled_by_repo[rk][: alloc.get(rk, 0)])
    return sampled


def export_sampled_precision_csv(
    db: Session,
    per_tool: int = 30,
    seed: int = 42,
    csv_path: Path = DEFAULT_SAMPLE_CSV,
    map_path: Path = DEFAULT_MAP_JSON,
) -> Dict[str, Any]:
    """
    Exports a blinded, deduplicated, repo-stratified sample of unmatched findings
    for human precision triage, writing the CSV and separate tool mapping file.
    """
    rng = random.Random(seed)
    loader = GroundTruthLoader()

    repos = {
        r.id: r
        for r in db.query(ResearchRepo).filter(ResearchRepo.is_excluded == False).order_by(ResearchRepo.created_at).all()
    }
    if not repos:
        raise ValueError("No active research repositories found.")

    active_runs = (
        db.query(BenchmarkRun)
        .filter(
            BenchmarkRun.repo_id.in_(list(repos.keys())),
            BenchmarkRun.is_superseded == False,
            BenchmarkRun.status == "completed",
            BenchmarkRun.tool.in_(ALLOWED_TOOLS),
        )
        .all()
    )
    active_run_ids = [r.id for r in active_runs]
    if not active_run_ids:
        raise ValueError("No completed benchmark runs found.")

    fp_findings = (
        db.query(BenchmarkFinding)
        .filter(
            BenchmarkFinding.run_id.in_(active_run_ids),
            BenchmarkFinding.match_result == "FP",
        )
        .all()
    )

    # Group unmatched findings by (tool -> repo_id -> list)
    grouped: Dict[str, Dict[str, List[BenchmarkFinding]]] = {t: {} for t in ALLOWED_TOOLS}
    for f in fp_findings:
        if f.tool in grouped and f.repo_id in repos:
            grouped[f.tool].setdefault(f.repo_id, []).append(f)

    sampled_per_tool: Dict[str, int] = {}
    pooled: List[BenchmarkFinding] = []
    for tool in ALLOWED_TOOLS:
        by_repo = grouped[tool]
        if not by_repo:
            sampled_per_tool[tool] = 0
            continue
        chosen = _stratified_sample_indices(by_repo, per_tool, rng)
        sampled_per_tool[tool] = len(chosen)
        pooled.extend(chosen)

    # Deduplicate pooled findings: same repo, same file, lines within ±3, same normalized CWE
    pooled.sort(key=lambda f: (f.repo_id, f.file_path, f.line_start, f.tool, f.id))
    clusters: List[Dict[str, Any]] = []
    for f in pooled:
        norm_cwe = loader.normalize_cwe(f.cwe) or (f.cwe or "unknown").upper()
        norm_file = f.file_path.replace("\\", "/")
        matched_cluster = None
        for cl in clusters:
            if (
                cl["repo_id"] == f.repo_id
                and cl["file_path"] == norm_file
                and cl["norm_cwe"] == norm_cwe
                and abs(cl["line_start"] - f.line_start) <= 3
            ):
                matched_cluster = cl
                break
        if matched_cluster is None:
            clusters.append({
                "repo_id": f.repo_id,
                "repo_name": repos[f.repo_id].name,
                "pinned_sha": repos[f.repo_id].pinned_sha,
                "repo_url": repos[f.repo_id].url,
                "file_path": norm_file,
                "line_start": f.line_start,
                "cwe": f.cwe or norm_cwe,
                "norm_cwe": norm_cwe,
                "message": _extract_message(f.raw_finding),
                "occurrences": [
                    {
                        "tool": f.tool,
                        "finding_id": f.id,
                        "rule_id": f.rule_id,
                        "line_start": f.line_start,
                        "cwe": f.cwe,
                    }
                ],
            })
        else:
            if not matched_cluster["message"]:
                matched_cluster["message"] = _extract_message(f.raw_finding)
            matched_cluster["occurrences"].append({
                "tool": f.tool,
                "finding_id": f.id,
                "rule_id": f.rule_id,
                "line_start": f.line_start,
                "cwe": f.cwe,
            })

    # Deterministically shuffle clusters so order does not leak tool identity
    rng.shuffle(clusters)

    code_cache: Dict[Tuple[str, str], List[str]] = {}
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["sample_id", "repo", "file", "line", "cwe", "message", "code_context", "label", "notes"])

    mapping_records: Dict[str, Any] = {}
    for idx, cl in enumerate(clusters, start=1):
        sample_id = f"SP-{idx:03d}"
        ctx = _extract_code_context(
            code_cache,
            cl["repo_url"],
            cl["pinned_sha"],
            cl["file_path"],
            cl["line_start"],
            radius=7,
        )
        writer.writerow([
            sample_id,
            cl["repo_name"],
            cl["file_path"],
            cl["line_start"],
            cl["cwe"],
            cl["message"],
            ctx,
            "",
            "",
        ])
        mapping_records[sample_id] = {
            "repo_id": cl["repo_id"],
            "repo_name": cl["repo_name"],
            "file_path": cl["file_path"],
            "line_start": cl["line_start"],
            "cwe": cl["cwe"],
            "norm_cwe": cl["norm_cwe"],
            "occurrences": cl["occurrences"],
        }

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(csv_buf.getvalue(), encoding="utf-8")

    map_payload = {
        "seed": seed,
        "per_tool": per_tool,
        "sampled_per_tool": sampled_per_tool,
        "deduplicated_items": len(clusters),
        "samples": mapping_records,
    }
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps(map_payload, indent=2), encoding="utf-8")

    return {
        "seed": seed,
        "per_tool": per_tool,
        "sampled_per_tool": sampled_per_tool,
        "pooled_before_dedup": len(pooled),
        "deduplicated_items": len(clusters),
        "csv_path": str(csv_path),
        "map_path": str(map_path),
    }


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    """Computes 95% Wilson score confidence interval for k successes in n trials."""
    if n <= 0:
        return None, None
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)) / denom
    return round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)


def _compute_tool_stats(rows: List[SampledPrecisionAudit]) -> Dict[str, Any]:
    by_tool: Dict[str, Dict[str, int]] = {}
    for r in rows:
        counts = by_tool.setdefault(r.tool, {"true_vuln": 0, "false_alarm": 0, "uncertain": 0})
        if r.label in counts:
            counts[r.label] += 1

    result: Dict[str, Any] = {}
    for tool, counts in sorted(by_tool.items()):
        tv = counts["true_vuln"]
        fa = counts["false_alarm"]
        unc = counts["uncertain"]
        n_decided = tv + fa
        prec = round(tv / n_decided, 4) if n_decided > 0 else None
        ci_low, ci_high = wilson_interval(tv, n_decided)
        result[tool] = {
            "sampled_precision": prec,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "true_vuln": tv,
            "false_alarm": fa,
            "uncertain": unc,
            "n_decided": n_decided,
            "n_total": n_decided + unc,
        }
    return result


def import_sampled_precision_csv(
    db: Session,
    csv_content: Optional[str] = None,
    csv_path: Path = DEFAULT_SAMPLE_CSV,
    map_path: Path = DEFAULT_MAP_JSON,
    labeled_by: str = "user",
) -> Dict[str, Any]:
    """
    Validates a labeled sampled-precision CSV against the private mapping file,
    rejects unknown labels or missing/unknown sample_ids, stores append-only
    SampledPrecisionAudit rows, and returns per-tool sampled precision with
    95% Wilson intervals.
    """
    if not map_path.exists():
        raise ValueError(f"Mapping file not found at {map_path}. Export a sample first.")
    map_data = json.loads(map_path.read_text(encoding="utf-8"))
    expected_samples: Dict[str, Any] = map_data.get("samples", {})
    if not expected_samples:
        raise ValueError("Mapping file contains no sample records.")

    if csv_content is None:
        if not csv_path.exists():
            raise ValueError(f"Labeled CSV not found at {csv_path}.")
        csv_content = csv_path.read_text(encoding="utf-8")

    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames or "sample_id" not in reader.fieldnames or "label" not in reader.fieldnames:
        raise ValueError("CSV must include 'sample_id' and 'label' columns.")

    parsed_rows: Dict[str, Tuple[str, str]] = {}
    for row_num, row in enumerate(reader, start=2):
        sid = (row.get("sample_id") or "").strip()
        lbl = (row.get("label") or "").strip().lower()
        notes = (row.get("notes") or "").strip()
        if not sid:
            raise ValueError(f"Row {row_num}: missing sample_id.")
        if sid not in expected_samples:
            raise ValueError(f"Row {row_num}: unknown sample_id '{sid}'.")
        if sid in parsed_rows:
            raise ValueError(f"Row {row_num}: duplicate sample_id '{sid}'.")
        if lbl not in VALID_TRIAGE_LABELS:
            raise ValueError(
                f"Row {row_num} ({sid}): invalid label '{lbl}'. "
                f"Must be one of {sorted(VALID_TRIAGE_LABELS)}."
            )
        parsed_rows[sid] = (lbl, notes)

    missing_ids = sorted(set(expected_samples.keys()) - set(parsed_rows.keys()))
    if missing_ids:
        raise ValueError(f"Missing sample_ids in CSV: {missing_ids[:10]} (total missing: {len(missing_ids)}).")

    max_ver = db.query(func.max(SampledPrecisionAudit.audit_version)).scalar() or 0
    next_ver = int(max_ver) + 1

    new_audit_rows: List[SampledPrecisionAudit] = []
    for sid in sorted(expected_samples.keys()):
        meta = expected_samples[sid]
        lbl, notes = parsed_rows[sid]
        for occ in meta.get("occurrences", []):
            audit_row = SampledPrecisionAudit(
                audit_version=next_ver,
                sample_id=sid,
                tool=occ["tool"],
                repo_id=meta["repo_id"],
                finding_id=occ["finding_id"],
                file_path=meta["file_path"],
                line_start=int(occ.get("line_start", meta["line_start"])),
                cwe=occ.get("cwe") or meta.get("cwe"),
                label=lbl,
                notes=notes or None,
                labeled_by=labeled_by,
            )
            db.add(audit_row)
            new_audit_rows.append(audit_row)

    db.commit()
    return {
        "audit_version": next_ver,
        "imported_sample_ids": len(parsed_rows),
        "stored_audit_rows": len(new_audit_rows),
        "per_tool": _compute_tool_stats(new_audit_rows),
    }


def get_latest_sampled_precision(db: Session) -> Optional[Dict[str, Any]]:
    """Returns per-tool sampled precision for the latest audit_version, or None if no import exists."""
    max_ver = db.query(func.max(SampledPrecisionAudit.audit_version)).scalar()
    if not max_ver:
        return None
    rows = (
        db.query(SampledPrecisionAudit)
        .filter(SampledPrecisionAudit.audit_version == int(max_ver))
        .all()
    )
    if not rows:
        return None
    return {
        "audit_version": int(max_ver),
        "per_tool": _compute_tool_stats(rows),
    }
