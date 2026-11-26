"""
One-time timing profiler for psf/requests (CVE-2018-18074, fix c45d7c49).
Measures per-stage and per-tool, per-commit timings without modifying scanning logic.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.benchmarks.cve_resolver import resolve_commit_parent, resolve_cve_or_advisory
from src.benchmarks.diff_extractor import DiffExtractor
from src.benchmarks.pipeline import _safe_git_clone_and_checkout, _robust_rmtree, compute_tool_timeout_s, _run_tool_with_timeout
from src.benchmarks.runners.bandit_runner import BanditRunner
from src.benchmarks.runners.codeguardian_runner import CodeGuardianRunner
from src.benchmarks.runners.codeql_runner import CodeQLRunner
from src.benchmarks.runners.semgrep_runner import SemgrepRunner
from src.benchmarks.runners.sonarqube_runner import SonarQubeRunner


def count_py_files(root: Path) -> dict:
    skip = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
    total = 0
    in_tests = 0
    in_docs = 0
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        if any(part in skip for part in rel.parts):
            continue
        total += 1
        parts_lower = [part.lower() for part in rel.parts]
        if any(x in parts_lower for x in ("tests", "test")):
            in_tests += 1
        if any(x in parts_lower for x in ("docs", "doc", "examples")):
            in_docs += 1
    return {"total_py": total, "in_tests": in_tests, "in_docs": in_docs, "non_test_non_doc": total - in_tests - in_docs}


def main():
    repo_url = "https://github.com/psf/requests"
    identifier = "CVE-2018-18074"
    profile = {"stages": {}, "commits": {}}

    # 1. Resolve
    t0 = time.perf_counter()
    fix_commit = "c45d7c49"
    parent_commit = resolve_commit_parent("psf", "requests", fix_commit)
    cwe = "CWE-522"
    profile["stages"]["resolve_s"] = round(time.perf_counter() - t0, 3)
    print(f"Resolved: parent={parent_commit[:8]}, fix={fix_commit[:8]}, cwe={cwe} in {profile['stages']['resolve_s']}s", flush=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="cg_profile_req_"))
    try:
        # 2. Clone
        t1 = time.perf_counter()
        _safe_git_clone_and_checkout(repo_url, tmp_dir, parent_commit)
        profile["stages"]["clone_s"] = round(time.perf_counter() - t1, 3)
        print(f"Cloned in {profile['stages']['clone_s']}s", flush=True)

        # 3. Labeling
        t2 = time.perf_counter()
        extractor = DiffExtractor()
        extracted = extractor.extract_from_git_repo(
            repo_dir=tmp_dir,
            parent_sha=parent_commit,
            fix_sha=fix_commit,
            cve_id=identifier,
            cwe=cwe,
        )
        profile["stages"]["labeling_s"] = round(time.perf_counter() - t2, 3)
        profile["loc"] = extracted.loc
        print(f"Labeled (LOC={extracted.loc}) in {profile['stages']['labeling_s']}s", flush=True)

        runners = [
            CodeGuardianRunner(),
            SemgrepRunner(),
            CodeQLRunner(),
            SonarQubeRunner(),
            BanditRunner(),
        ]

        # 4. Scan Vulnerable Commit
        vuln_counts = count_py_files(tmp_dir)
        profile["commits"]["vulnerable"] = {"sha": parent_commit, "file_counts": vuln_counts, "tools": {}}
        for runner in runners:
            tname = runner.tool_name
            timeout_s = compute_tool_timeout_s(tname, extracted.loc)
            wt0 = time.perf_counter()
            tres = _run_tool_with_timeout(runner, tmp_dir, timeout_s)
            wall_s = time.perf_counter() - wt0
            entry = {
                "status": tres.status,
                "version": tres.tool_version,
                "scan_duration_s": round(tres.duration_s, 3),
                "wall_s": round(wall_s, 3),
                "overhead_or_startup_s": round(max(0.0, wall_s - tres.duration_s), 3),
                "findings_count": len(tres.findings),
                "metadata": tres.metadata,
                "error": tres.error_message,
            }
            profile["commits"]["vulnerable"]["tools"][tname] = entry
            print(f"[vuln] {tname}: status={tres.status}, scan={entry['scan_duration_s']}s, wall={entry['wall_s']}s, findings={len(tres.findings)}", flush=True)

        # 5. Checkout Clean Commit & Scan
        t3 = time.perf_counter()
        subprocess.run(["git", "checkout", fix_commit], cwd=str(tmp_dir), capture_output=True, text=True, check=True)
        profile["stages"]["checkout_clean_s"] = round(time.perf_counter() - t3, 3)

        clean_counts = count_py_files(tmp_dir)
        profile["commits"]["clean"] = {"sha": fix_commit, "file_counts": clean_counts, "tools": {}}
        for runner in runners:
            tname = runner.tool_name
            timeout_s = compute_tool_timeout_s(tname, extracted.loc)
            wt0 = time.perf_counter()
            tres = _run_tool_with_timeout(runner, tmp_dir, timeout_s)
            wall_s = time.perf_counter() - wt0
            entry = {
                "status": tres.status,
                "version": tres.tool_version,
                "scan_duration_s": round(tres.duration_s, 3),
                "wall_s": round(wall_s, 3),
                "overhead_or_startup_s": round(max(0.0, wall_s - tres.duration_s), 3),
                "findings_count": len(tres.findings),
                "metadata": tres.metadata,
                "error": tres.error_message,
            }
            profile["commits"]["clean"]["tools"][tname] = entry
            print(f"[clean] {tname}: status={tres.status}, scan={entry['scan_duration_s']}s, wall={entry['wall_s']}s, findings={len(tres.findings)}", flush=True)

        out_path = Path("scratch/requests_profile.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        print("Saved profile to", out_path, flush=True)
    finally:
        _robust_rmtree(tmp_dir)


if __name__ == "__main__":
    main()
