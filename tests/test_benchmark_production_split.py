"""
Tests for the production-safe split of the benchmark system (Step 6):
1. Every mutating/research endpoint returns 404 in readonly mode (default).
2. Production modules never import src.benchmarks_research.
3. Snapshot export + import into an empty DB reproduces identical page numbers (and supports dry-run & rollback).
4. User scans and benchmark data stay strictly independent (separate schema & isolated transactions).
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.benchmark_models import (
    BENCHMARK_SCHEMA,
    BenchmarkDeletionAudit,
    BenchmarkFinding,
    BenchmarkLatencyPass,
    BenchmarkMetric,
    BenchmarkRun,
    BenchmarkSnapshot,
    ResearchRepo,
    SampledPrecisionAudit,
)
from src.db.models import AnalysisRun, Base, Repository


def _make_sqlite_memory_session():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=eng)
    SessionCls = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    return eng, SessionCls()


def test_readonly_mode_returns_404_for_all_mutating_endpoints(monkeypatch):
    monkeypatch.delenv("BENCHMARK_MODE", raising=False)
    from src.api.server import app

    client = TestClient(app)

    caps = client.get("/api/v1/benchmarks/capabilities")
    assert caps.status_code == 200
    caps_json = caps.json()
    assert caps_json["benchmark_mode"] == "readonly"
    assert caps_json["readonly"] is True
    assert caps_json["can_mutate"] is False

    mutating_endpoints = [
        ("POST", "/api/v1/benchmarks/repos"),
        ("GET", "/api/v1/benchmarks/repos/any-id/run-plan"),
        ("POST", "/api/v1/benchmarks/repos/any-id/run"),
        ("POST", "/api/v1/benchmarks/repos/any-id/retry"),
        ("POST", "/api/v1/benchmarks/repos/any-id/exclude"),
        ("POST", "/api/v1/benchmarks/repos/any-id/unexclude"),
        ("DELETE", "/api/v1/benchmarks/repos/any-id"),
        ("GET", "/api/v1/benchmarks/repos/any-id/blind-triage"),
        ("POST", "/api/v1/benchmarks/repos/any-id/verified-triage"),
        ("POST", "/api/v1/benchmarks/seed"),
        ("GET", "/api/v1/benchmarks/triage/sample"),
        ("POST", "/api/v1/benchmarks/triage/sample/import"),
        ("POST", "/api/v1/benchmarks/repos/any-id/recompute"),
        ("POST", "/api/v1/benchmarks/recompute-all"),
        ("POST", "/api/v1/benchmarks/latency-pass"),
    ]
    for method, path in mutating_endpoints:
        resp = client.request(method, path)
        assert resp.status_code == 404, f"Expected 404 for {method} {path} in readonly mode, got {resp.status_code}"


def test_production_build_fails_if_it_imports_research_package():
    # 1. Runtime check in a fresh Python interpreter
    code = (
        "import sys; "
        "import src.db.benchmark_models, src.benchmarks.read_service, src.benchmarks.snapshot_importer, "
        "src.api.routers.benchmark, src.api.server; "
        "leaked = [m for m in sys.modules if 'benchmarks_research' in m]; "
        "assert not leaked, f'Production imported research package: {leaked}'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr or proc.stdout

    # 2. Static AST check on production files (no top-level imports of src.benchmarks_research)
    prod_files = [
        Path("src/db/benchmark_models.py"),
        Path("src/benchmarks/read_service.py"),
        Path("src/benchmarks/snapshot_importer.py"),
        Path("src/api/server.py"),
    ]
    for pf in prod_files:
        tree = ast.parse(pf.read_text(encoding="utf-8"), filename=str(pf))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "benchmarks_research" not in alias.name, f"{pf} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "benchmarks_research" not in node.module, f"{pf} imports from {node.module}"


def test_snapshot_export_and_import_into_empty_db_reproduces_page_numbers(tmp_path):
    from src.benchmarks.read_service import BenchmarkReadService
    from src.benchmarks.snapshot_importer import import_snapshot, rollback_snapshot
    from src.benchmarks_research.service import BenchmarkService
    from src.benchmarks_research.snapshot_exporter import export_snapshot_to_file

    _, research_db = _make_sqlite_memory_session()
    _, prod_db = _make_sqlite_memory_session()

    try:
        # Populate research DB with 1 real repo + 1 synthetic fixture (which must be excluded)
        real_repo = ResearchRepo(
            id="repo-1",
            name="org/real-repo",
            url="https://github.com/org/real-repo",
            pinned_sha="a" * 40,
            clean_sha="b" * 40,
            language="python",
            loc=1000,
            status="done",
            label_quality="verified",
            is_excluded=False,
        )
        synth_repo = ResearchRepo(
            id="repo-synth",
            name="synthetic/positive-control",
            url="https://github.com/synthetic/positive-control",
            loc=50,
            status="done",
            is_excluded=False,
        )
        research_db.add_all([real_repo, synth_repo])
        research_db.flush()

        run_cg = BenchmarkRun(
            id="run-cg-1",
            repo_id=real_repo.id,
            tool="codeguardian",
            tool_version="2.1.1-research",
            duration_s=1.25,
            raw_output_path="C:/Users/secret/tmp/raw.json",
            status="completed",
            run_metadata={"vuln_duration_s": 1.25, "cache_dir": "C:/temp/cache"},
            run_version=1,
            is_superseded=False,
        )
        research_db.add(run_cg)
        research_db.flush()

        research_db.add(
            BenchmarkFinding(
                id="f-1",
                run_id=run_cg.id,
                repo_id=real_repo.id,
                tool="codeguardian",
                file_path="app/main.py",
                line_start=10,
                line_end=10,
                cwe="CWE-95",
                normalized_cwe="CWE-95",
                severity="HIGH",
                rule_id="SAST-001",
                match_result="TP",
                matched_ground_truth_id="GT-1",
            )
        )
        research_db.add(
            BenchmarkMetric(
                id="m-1",
                repo_id=real_repo.id,
                tool="codeguardian",
                tool_version="2.1.1-research",
                precision=0.5,
                recall=1.0,
                false_positive_rate=0.0,
                localization_accuracy=1.0,
                classification_accuracy=1.0,
                scan_latency=1.25,
                counts_json={
                    "tp": 1,
                    "precision_tp": 1,
                    "fp": 1,
                    "fn": 0,
                    "clean_fp": 0,
                    "total_vulnerable_findings": 2,
                },
                run_version=1,
                is_superseded=False,
            )
        )
        research_db.add(
            BenchmarkLatencyPass(
                id="lp-1",
                pass_version=1,
                is_superseded=False,
                status="completed",
                repeats=3,
                repo_ids=[real_repo.id],
                host_info={"cpu_model": "TestCPU", "cpu_cores_logical": 4, "ram_gb": 8.0, "os": "Linux"},
                scope_policy_hash="005d54e76e0a",
                tool_versions={"codeguardian": "2.1.1-research"},
                tool_rulesets={"codeguardian": "SecurityASTScanner:SAST-*"},
                results_json={
                    "per_tool_macro": {
                        "codeguardian": {
                            "median_latency_per_kloc": 1.25,
                            "spread_latency_per_kloc": 0.1,
                            "median_duration_s": 1.25,
                            "spread_duration_s": 0.1,
                            "sample_repos": 1,
                            "repeats": 3,
                        }
                    }
                },
            )
        )
        research_db.commit()

        snap_path = tmp_path / "snapshot_v1.json"
        export_summary = export_snapshot_to_file(research_db, snap_path)
        assert export_summary["repos"] == 1  # synthetic excluded

        # Dry-run on empty prod DB
        dry = import_snapshot(prod_db, snap_path, dry_run=True)
        assert dry["dry_run"] is True
        assert dry["valid_checksum"] is True
        assert dry["changes"]["repos_to_add"] == ["org/real-repo"]

        # Tampered checksum must fail
        bad_path = tmp_path / "bad.json"
        bad_data = json.loads(snap_path.read_text(encoding="utf-8"))
        bad_data["sha256"] = "0" * 64
        bad_path.write_text(json.dumps(bad_data), encoding="utf-8")
        try:
            import_snapshot(prod_db, bad_path)
            raise AssertionError("Tampered snapshot should have failed checksum validation")
        except ValueError as exc:
            assert "checksum" in str(exc).lower()

        # Real import into empty prod DB
        imp1 = import_snapshot(prod_db, snap_path, dry_run=False)
        assert imp1["status"] == "imported"

        # Exclude synthetic repo when computing research overview for comparison
        synth_repo.is_excluded = True
        research_db.commit()

        research_ov = BenchmarkService(research_db).get_overview_macro_metrics()
        prod_ov = BenchmarkReadService(prod_db).get_overview_macro_metrics()

        assert prod_ov["total_repos"] == research_ov["total_repos"] == 1
        assert prod_ov["total_loc"] == research_ov["total_loc"] == 1000
        for metric_key in (
            "precision",
            "recall",
            "f1_score",
            "false_positive_rate",
            "localization_accuracy",
            "classification_accuracy",
            "scan_latency",
        ):
            assert prod_ov["tools"]["codeguardian"][metric_key] == research_ov["tools"]["codeguardian"][metric_key]

        # Import a second snapshot and verify rollback restores v1
        real_repo.loc = 2000
        research_db.commit()
        snap2_path = tmp_path / "snapshot_v2.json"
        export_snapshot_to_file(research_db, snap2_path)
        import_snapshot(prod_db, snap2_path, dry_run=False)
        assert BenchmarkReadService(prod_db).get_overview_macro_metrics()["total_loc"] == 2000

        rb = rollback_snapshot(prod_db)
        assert rb["status"] == "rolled_back"
        assert BenchmarkReadService(prod_db).get_overview_macro_metrics()["total_loc"] == 1000
    finally:
        research_db.close()
        prod_db.close()


def test_user_scans_and_benchmark_data_stay_independent(tmp_path):
    from src.benchmarks.read_service import BenchmarkReadService
    from src.benchmarks.snapshot_importer import import_snapshot
    from src.benchmarks_research.snapshot_exporter import export_snapshot_to_file

    # Verify schema separation
    benchmark_models = [
        ResearchRepo,
        BenchmarkRun,
        BenchmarkFinding,
        BenchmarkMetric,
        BenchmarkDeletionAudit,
        SampledPrecisionAudit,
        BenchmarkLatencyPass,
        BenchmarkSnapshot,
    ]
    for bm in benchmark_models:
        assert bm.__table__.schema == BENCHMARK_SCHEMA
    for user_model in (Repository, AnalysisRun):
        assert user_model.__table__.schema is None

    _, db = _make_sqlite_memory_session()
    _, empty_research_db = _make_sqlite_memory_session()
    try:
        user_repo = Repository(id="user-repo-1", name="user/private-app", url="https://github.com/user/private-app")
        db.add(user_repo)
        db.flush()
        scan = AnalysisRun(
            id="scan-1",
            repo_id=user_repo.id,
            filepath="app/secret.py",
            status="completed",
            has_vulnerabilities=True,
            summary="Private user scan",
            security_response={"title": "Private secret"},
        )
        db.add(scan)
        db.commit()

        # Export from empty_research_db (no user data) and import into db
        snap_path = tmp_path / "empty_snap.json"
        export_snapshot_to_file(empty_research_db, snap_path)
        snap_text = snap_path.read_text(encoding="utf-8")
        assert "user/private-app" not in snap_text
        assert "Private secret" not in snap_text

        import_snapshot(db, snap_path, dry_run=False)

        # User scan tables remain completely untouched
        assert db.query(Repository).count() == 1
        assert db.query(AnalysisRun).count() == 1
        assert db.query(AnalysisRun).first().summary == "Private user scan"
        assert BenchmarkReadService(db).get_overview_macro_metrics()["total_repos"] == 0
    finally:
        db.close()
        empty_research_db.close()
