"""
Unit tests for Independent Benchmark Router (src/api/routers/benchmark.py)
"""
import pytest
from pathlib import Path
from src.api.routers.benchmark import _normalize_rel, _extract_json_data

def test_extract_json_data_with_noisy_stdout():
    raw_output = 'Working... ---------------------------------------- 100% 0:00:08\n{\n  "results": [{"issue_text": "sample"}]\n}'
    data = _extract_json_data(raw_output)
    assert "results" in data
    assert len(data["results"]) == 1
    assert data["results"][0]["issue_text"] == "sample"

def test_extract_json_data_clean():
    data = _extract_json_data('{"status": "ok"}')
    assert data == {"status": "ok"}

def test_normalize_rel_cross_platform():
    base = Path("C:/Users/test/temp_repo")
    abs_win = "C:\\\\Users\\\\test\\\\temp_repo\\\\app\\\\server.py"
    rel_win = "app\\\\server.py"
    rel_posix = "app/server.py"
    dot_rel = "./app/server.py"

    assert _normalize_rel(abs_win, base) == "app/server.py"
    assert _normalize_rel(rel_win, base) == "app/server.py"
    assert _normalize_rel(rel_posix, base) == "app/server.py"
    assert _normalize_rel(dot_rel, base) == "app/server.py"


def test_find_cached_benchmark_corpora():
    from src.api.routers.benchmark import _find_cached_benchmark

    dsss_1 = _find_cached_benchmark("https://github.com/stamparm/DSSS/")
    assert dsss_1 is not None and "stamparm_DSSS" in dsss_1.name

    dsss_2 = _find_cached_benchmark("stamparm/DSSS")
    assert dsss_2 is not None and "stamparm_DSSS" in dsss_2.name


def test_prepare_benchmark_repo_offline_fallback(monkeypatch, tmp_path):
    import subprocess
    from src.api.routers.benchmark import _prepare_benchmark_repo, _robust_rmtree

    def mock_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            128, "git",
            output="",
            stderr="fatal: unable to access 'https://github.com/stamparm/DSSS/': Could not resolve host: github.com"
        )

    monkeypatch.setattr(subprocess, "run", mock_run)

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    # Even with git failing due to 'Could not resolve host: github.com', the cached snapshot is used
    res = _prepare_benchmark_repo("https://github.com/stamparm/DSSS/", sandbox)
    assert "Pre-cached snapshot" in res
    assert (sandbox / "dsss.py").is_file()

    _robust_rmtree(sandbox)


def test_prepare_benchmark_repo_local_dir(tmp_path):
    from src.api.routers.benchmark import _prepare_benchmark_repo, _robust_rmtree

    dummy_repo = tmp_path / "dummy_local"
    dummy_repo.mkdir()
    (dummy_repo / "main.py").write_text("print('hello')", encoding="utf-8")

    sandbox = tmp_path / "sandbox_local"
    sandbox.mkdir()

    res = _prepare_benchmark_repo(str(dummy_repo), sandbox)
    assert (sandbox / "main.py").is_file()
    assert (sandbox / "main.py").read_text(encoding="utf-8") == "print('hello')"

    _robust_rmtree(dummy_repo)
    _robust_rmtree(sandbox)


def test_research_benchmark_endpoints(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.api.server import app
    from src.db.session import SessionLocal
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkFinding, BenchmarkMetric
    from src.benchmarks_research.ground_truth_loader import GroundTruthLoader
    import json

    # Prevent background thread from actually spawning git clone during test
    monkeypatch.setattr("src.benchmarks_research.pipeline.trigger_benchmark_pipeline_async", lambda repo_id: None)

    # Use isolated temp ground-truth directory so test doesn't depend on deleted manifests
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / "sample_repo.json").write_text(json.dumps({
        "repo_name": "sample/vuln-app",
        "url": "https://github.com/sample/vuln-app",
        "pinned_vulnerable_sha": "aaa1111",
        "pinned_clean_sha": "bbb2222",
        "language": "Python",
        "loc": 100,
        "repo_type": "intentionally_vulnerable",
        "labeled_findings": [],
        "clean_negative_regions": [],
    }), encoding="utf-8")
    orig_init = GroundTruthLoader.__init__
    monkeypatch.setattr(GroundTruthLoader, "__init__", lambda self, ground_truth_dir=None: orig_init(self, ground_truth_dir=gt_dir))

    from sqlalchemy.pool import StaticPool
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.db.session import get_db, get_benchmark_read_db
    from src.db.models import Base
    import src.db.benchmark_models  # noqa: F401

    # Use isolated in-memory SQLite with StaticPool so data/ai_engineer.db is never wiped
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        test_db = TestSessionLocal()
        try:
            yield test_db
        finally:
            test_db.close()

    from fastapi import FastAPI
    from src.api.routers.benchmark import create_benchmark_router
    test_app = FastAPI()
    test_app.include_router(create_benchmark_router(mode="research"), prefix="/api/v1")
    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_benchmark_read_db] = override_get_db

    client = TestClient(test_app)

    # 1. Seed manifests
    res_seed = client.post("/api/v1/benchmarks/seed")
    assert res_seed.status_code == 200
    seed_data = res_seed.json()
    assert seed_data["status"] == "ok"
    assert "sample/vuln-app" in seed_data["repos"]

    # 2. Get overview when no repos are "done" yet (no fake numbers!)
    res_overview = client.get("/api/v1/benchmarks/overview")
    assert res_overview.status_code == 200
    data = res_overview.json()
    assert "tools" in data
    assert "codeguardian" in data["tools"]
    cg_metrics = data["tools"]["codeguardian"]
    assert cg_metrics["sample_size"] == 0
    assert cg_metrics["has_data"] is False
    assert cg_metrics["precision"] is None
    assert cg_metrics["recall"] is None
    assert data["total_repos"] == 0

    # 3. Get repos - intentionally vulnerable repo has clean_sha=None
    res_repos = client.get("/api/v1/benchmarks/repos")
    assert res_repos.status_code == 200
    repos = res_repos.json()
    assert len(repos) >= 1
    flask_repo = next(r for r in repos if r["name"] == "sample/vuln-app")
    assert flask_repo["repo_type"] == "intentionally_vulnerable"
    assert flask_repo["clean_sha"] is None
    assert flask_repo["metrics"] == {}

    # 4. Add a research repo (one-step automatic queue)
    res_add = client.post(
        "/api/v1/benchmarks/repos",
        json={"repo_url": "https://github.com/pallets/flask", "identifier": "CVE-2018-18074"}
    )
    assert res_add.status_code == 200
    queued = res_add.json()
    assert queued["status"] == "queued"
    assert "pallets/flask" in queued["repo"]["name"]
    assert queued["repo"]["pinned_sha"] is None
    assert queued["repo"]["clean_sha"] is None
    assert queued["repo"]["loc"] is None

    # 5. Issue B Regression: Duplicate submission must return 409 Conflict synchronously
    res_add_dup = client.post(
        "/api/v1/benchmarks/repos",
        json={"repo_url": "https://github.com/pallets/flask", "identifier": "CVE-2018-18074"}
    )
    assert res_add_dup.status_code == 409
    dup_detail = res_add_dup.json()["detail"]
    assert "already registered in the benchmark" in dup_detail

    # Verify duplicate did not create a second row
    res_repos_after = client.get("/api/v1/benchmarks/repos").json()
    pallets_rows = [r for r in res_repos_after if "pallets/flask" in r["name"]]
    assert len(pallets_rows) == 1

    # 6. Issue A Regression: Running repo must NOT have metrics and must NOT leak into general averages
    assert pallets_rows[0]["metrics"] == {}
    res_overview2 = client.get("/api/v1/benchmarks/overview").json()
    assert res_overview2["total_repos"] == 0
    assert res_overview2["tools"]["codeguardian"]["sample_size"] == 0

    # 7. Exclude repository with reason
    repo_id = flask_repo["id"]
    res_exclude = client.post(
        f"/api/v1/benchmarks/repos/{repo_id}/exclude",
        json={"reason": "Testing manual exclusion logic"}
    )
    assert res_exclude.status_code == 200
    assert res_exclude.json()["repo"]["is_excluded"] is True

    # 8. Unexclude repository
    res_unexclude = client.post(f"/api/v1/benchmarks/repos/{repo_id}/unexclude")
    assert res_unexclude.status_code == 200
    assert res_unexclude.json()["repo"]["is_excluded"] is False

    app.dependency_overrides.pop(get_db, None)


def test_stuck_job_timeout():
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo
    from src.benchmarks_research.service import BenchmarkService

    from sqlalchemy.pool import StaticPool
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    db = TestSessionLocal()
    try:
        # Create a simulated stuck job with old heartbeat
        old_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=15)
        stuck_repo = ResearchRepo(
            name="test/stuck-repo (CVE-2099-0001)",
            url="https://github.com/test/stuck-repo",
            pinned_sha="",
            ground_truth_path="",
            status="running",
            job_stage="cloning",
            job_progress=0.25,
            last_heartbeat=old_heartbeat,
            added_by="test",
        )
        db.add(stuck_repo)
        db.commit()
        db.refresh(stuck_repo)
        repo_id = stuck_repo.id

        service = BenchmarkService(db)
        timed_out = service.check_and_timeout_stuck_jobs(timeout_seconds=600)

        assert any(r.id == repo_id for r in timed_out)
        db.refresh(stuck_repo)
        assert stuck_repo.status == "failed"
        assert "Job timed out after 15m at stage: cloning" in stuck_repo.job_error
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_shallow_clone_sha_validation_and_cache_isolation(tmp_path, monkeypatch):
    import pytest
    import subprocess
    from src.benchmarks_research.pipeline import _validate_sha40, compute_fetch_timeout_s, _get_bare_cache_dir

    # 1. Strict 40-char hex SHA validation
    valid_sha = "1c335944d6a8b1298baf179b7c0b3069f10c514b"
    assert _validate_sha40(valid_sha) == valid_sha
    for bad in ["1c335944", "1c335944; rm -rf /", "g" * 40, ""]:
        with pytest.raises(ValueError, match="40-character hex"):
            _validate_sha40(bad)

    # 2. Configurable LOC-scaled timeout
    assert compute_fetch_timeout_s(20000) >= 320
    monkeypatch.setenv("BENCHMARK_GIT_TIMEOUT_S", "240")
    assert compute_fetch_timeout_s(20000) == 240
    monkeypatch.delenv("BENCHMARK_GIT_TIMEOUT_S")

    # 3. Bare cache origin verification prevents cross-repo reuse
    cache_dir, origin_url, slug = _get_bare_cache_dir("https://github.com/testowner/testrepo")
    try:
        assert slug == "testowner/testrepo"
        assert cache_dir.name == "testowner__testrepo.git"
        # Tamper remote.origin.url to another repo -> _get_bare_cache_dir must recreate it
        subprocess.run(["git", "--git-dir", str(cache_dir), "remote", "set-url", "origin", "https://github.com/other/repo"], check=True)
        cache_dir2, _, _ = _get_bare_cache_dir("https://github.com/testowner/testrepo")
        proc = subprocess.run(["git", "--git-dir", str(cache_dir2), "config", "--get", "remote.origin.url"], capture_output=True, text=True, check=True)
        assert proc.stdout.strip().lower() == "https://github.com/testowner/testrepo"
    finally:
        from src.benchmarks_research.pipeline import _robust_rmtree
        _robust_rmtree(cache_dir)


def test_unified_scope_filtered_copy_and_fail_loud(tmp_path):
    import pytest
    from src.benchmarks_research.scope import ScopePolicy, ScopeExclusionError, build_filtered_source_copy

    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "tests").mkdir()
    (src / "docs").mkdir()
    (src / "examples").mkdir()
    (src / "vendor").mkdir()
    (src / "pkg" / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (src / "pkg" / "app_pb2.py").write_text("# generated\n", encoding="utf-8")
    (src / "pkg" / "bundle.min.js").write_text("var a=1;", encoding="utf-8")
    (src / "tests" / "test_app.py").write_text("assert True\n", encoding="utf-8")
    (src / "docs" / "conf.py").write_text("project='x'\n", encoding="utf-8")
    (src / "examples" / "demo.py").write_text("print(1)\n", encoding="utf-8")
    (src / "vendor" / "lib.py").write_text("z = 3\n", encoding="utf-8")

    dst = tmp_path / "filtered"
    info = build_filtered_source_copy(src, dst, ScopePolicy(), labeled_files=["pkg/app.py"])
    assert info["in_scope_files"] == 1
    assert info["in_scope_loc"] == 2
    assert info["excluded_files"] == 6
    assert (dst / "pkg" / "app.py").is_file()
    assert not (dst / "tests" / "test_app.py").exists()
    assert not (dst / "pkg" / "app_pb2.py").exists()
    assert not (dst / "pkg" / "bundle.min.js").exists()

    # Fail loudly if a labeled ground-truth file is excluded
    dst2 = tmp_path / "filtered2"
    with pytest.raises(ScopeExclusionError, match="Excluded directory"):
        build_filtered_source_copy(src, dst2, ScopePolicy(), labeled_files=["tests/test_app.py"])

    # Per-repo override can include a normally excluded directory
    override_policy = ScopePolicy.from_override({"include_dirs": ["examples"]})
    dst3 = tmp_path / "filtered3"
    info3 = build_filtered_source_copy(src, dst3, override_policy, labeled_files=["examples/demo.py"])
    assert info3["in_scope_files"] == 2
    assert (dst3 / "examples" / "demo.py").is_file()


def test_security_only_rule_policy(tmp_path):
    from src.benchmarks_research.runners.bandit_runner import BanditRunner
    from src.benchmarks_research.runners.sonarqube_runner import SonarQubeRunner
    from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner

    # Bandit excludes B101 (assert_used) and records rule policy metadata
    (tmp_path / "sample.py").write_text("assert True\n", encoding="utf-8")
    b_res = BanditRunner().run(tmp_path)
    assert b_res.status == "completed"
    assert len(b_res.findings) == 0
    assert b_res.metadata.get("rule_policy") == "security_only"
    assert "B101" in b_res.metadata.get("skipped_rules", [])

    # SonarQube parser excludes CODE_SMELL and keeps VULNERABILITY
    sq_json = '{"issues": [{"type": "CODE_SMELL", "component": "p:a.py", "line": 1, "rule": "python:S1", "message": "smell"}, {"type": "VULNERABILITY", "component": "p:a.py", "line": 2, "rule": "python:S2", "message": "vuln", "tags": ["cwe-89"]}]}'
    sq_findings = SonarQubeRunner().parse_issues_json(sq_json)
    assert len(sq_findings) == 1
    assert sq_findings[0].cwe == "CWE-89"

    # CodeGuardian records rule policy metadata
    cg_res = CodeGuardianRunner().run(tmp_path)
    assert cg_res.metadata.get("rule_policy") == "security_only"


def test_append_only_run_versioning_and_single_tool_rerun(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkMetric
    from src.benchmarks_research.service import BenchmarkService
    from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner

    # 1. Semgrep distinguishes docker_not_running from not_installed
    sr = SemgrepRunner()
    sr.docker_executable = "docker"
    sr.local_executable = None
    sr._docker_available = False
    res_sr = sr.run(Path("."))
    assert res_sr.status == "docker_not_running"

    # 2. run_repo_pipeline is append-only (never deletes prior runs) and supports tool=...
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    try:
        captured = {}
        monkeypatch.setattr(
            "src.benchmarks_research.pipeline.trigger_benchmark_pipeline_async",
            lambda repo_id, target_tools=None: captured.update({"repo_id": repo_id, "target_tools": target_tools}),
        )
        repo = ResearchRepo(name="test/vrepo", url="https://github.com/test/vrepo", status="partial", job_stage="partial")
        db.add(repo)
        db.commit()
        db.refresh(repo)

        old_run = BenchmarkRun(repo_id=repo.id, tool="codeguardian", status="completed", run_version=1, is_superseded=False)
        old_metric = BenchmarkMetric(repo_id=repo.id, tool="codeguardian", precision=0.5, recall=0.5, run_version=1, is_superseded=False)
        db.add_all([old_run, old_metric])
        db.commit()

        svc = BenchmarkService(db)
        svc.run_repo_pipeline(repo.id, tool="semgrep")

        # Prior run and metric are preserved!
        assert db.query(BenchmarkRun).filter(BenchmarkRun.repo_id == repo.id).count() == 1
        assert db.query(BenchmarkMetric).filter(BenchmarkMetric.repo_id == repo.id).count() == 1
        assert captured["target_tools"] == ["semgrep"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_delete_repo_and_audit():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkFinding, BenchmarkMetric, BenchmarkDeletionAudit
    from src.benchmarks_research.service import BenchmarkService

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    db = TestSessionLocal()
    try:
        # 1. Failed repo without completed runs deletes without reason
        failed_repo = ResearchRepo(
            name="test/failed-repo",
            url="https://github.com/test/failed-repo",
            status="failed",
            job_stage="cloning",
        )
        db.add(failed_repo)
        db.commit()
        db.refresh(failed_repo)

        svc = BenchmarkService(db)
        res1 = svc.delete_repo(failed_repo.id)
        assert res1["status"] == "deleted"
        assert db.query(ResearchRepo).filter(ResearchRepo.id == failed_repo.id).first() is None
        assert db.query(BenchmarkDeletionAudit).filter(BenchmarkDeletionAudit.repo_id == failed_repo.id).count() == 1

        # 2. Done repo with completed run requires written reason and logs surviving audit record
        done_repo = ResearchRepo(
            name="test/done-repo",
            url="https://github.com/test/done-repo",
            status="done",
            job_stage="done",
            is_excluded=False,
        )
        db.add(done_repo)
        db.commit()
        db.refresh(done_repo)

        run = BenchmarkRun(repo_id=done_repo.id, tool="codeguardian", status="completed", duration_s=1.0)
        db.add(run)
        db.commit()
        db.refresh(run)

        metric = BenchmarkMetric(repo_id=done_repo.id, tool="codeguardian", precision=1.0, recall=1.0)
        finding = BenchmarkFinding(run_id=run.id, repo_id=done_repo.id, tool="codeguardian", file_path="a.py", line_start=1, line_end=1, match_result="TP")
        db.add_all([metric, finding])
        db.commit()

        import pytest
        with pytest.raises(ValueError, match="written reason"):
            svc.delete_repo(done_repo.id)

        res2 = svc.delete_repo(done_repo.id, reason="Obsolete test baseline")
        assert res2["status"] == "deleted"
        assert res2["had_completed_run"] is True
        assert res2["was_counted_in_averages"] is True
        assert db.query(ResearchRepo).filter(ResearchRepo.id == done_repo.id).first() is None
        assert db.query(BenchmarkRun).filter(BenchmarkRun.repo_id == done_repo.id).count() == 0
        assert db.query(BenchmarkMetric).filter(BenchmarkMetric.repo_id == done_repo.id).count() == 0
        assert db.query(BenchmarkFinding).filter(BenchmarkFinding.repo_id == done_repo.id).count() == 0

        audit = db.query(BenchmarkDeletionAudit).filter(BenchmarkDeletionAudit.repo_id == done_repo.id).first()
        assert audit is not None
        assert audit.reason == "Obsolete test baseline"
        assert audit.was_counted_in_averages is True
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_shallow_clone_sha_validation_and_cache_isolation(tmp_path, monkeypatch):
    import pytest
    import subprocess
    from src.benchmarks_research.pipeline import _validate_sha40, compute_fetch_timeout_s, _get_bare_cache_dir

    # 1. Strict 40-char hex SHA validation
    valid_sha = "1c335944d6a8b1298baf179b7c0b3069f10c514b"
    assert _validate_sha40(valid_sha) == valid_sha
    for bad in ["1c335944", "1c335944; rm -rf /", "g" * 40, ""]:
        with pytest.raises(ValueError, match="40-character hex"):
            _validate_sha40(bad)

    # 2. Configurable LOC-scaled timeout
    assert compute_fetch_timeout_s(20000) >= 320
    monkeypatch.setenv("BENCHMARK_GIT_TIMEOUT_S", "240")
    assert compute_fetch_timeout_s(20000) == 240
    monkeypatch.delenv("BENCHMARK_GIT_TIMEOUT_S")

    # 3. Bare cache origin verification prevents cross-repo reuse
    cache_dir, origin_url, slug = _get_bare_cache_dir("https://github.com/testowner/testrepo")
    try:
        assert slug == "testowner/testrepo"
        assert cache_dir.name == "testowner__testrepo.git"
        # Tamper remote.origin.url to another repo -> _get_bare_cache_dir must recreate it
        subprocess.run(["git", "--git-dir", str(cache_dir), "remote", "set-url", "origin", "https://github.com/other/repo"], check=True)
        cache_dir2, _, _ = _get_bare_cache_dir("https://github.com/testowner/testrepo")
        proc = subprocess.run(["git", "--git-dir", str(cache_dir2), "config", "--get", "remote.origin.url"], capture_output=True, text=True, check=True)
        assert proc.stdout.strip().lower() == "https://github.com/testowner/testrepo"
    finally:
        from src.benchmarks_research.pipeline import _robust_rmtree
        _robust_rmtree(cache_dir)


def test_unified_scope_filtered_copy_and_fail_loud(tmp_path):
    import pytest
    from src.benchmarks_research.scope import ScopePolicy, ScopeExclusionError, build_filtered_source_copy

    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "tests").mkdir()
    (src / "docs").mkdir()
    (src / "examples").mkdir()
    (src / "vendor").mkdir()
    (src / "pkg" / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (src / "pkg" / "app_pb2.py").write_text("# generated\n", encoding="utf-8")
    (src / "pkg" / "bundle.min.js").write_text("var a=1;", encoding="utf-8")
    (src / "tests" / "test_app.py").write_text("assert True\n", encoding="utf-8")
    (src / "docs" / "conf.py").write_text("project='x'\n", encoding="utf-8")
    (src / "examples" / "demo.py").write_text("print(1)\n", encoding="utf-8")
    (src / "vendor" / "lib.py").write_text("z = 3\n", encoding="utf-8")

    dst = tmp_path / "filtered"
    info = build_filtered_source_copy(src, dst, ScopePolicy(), labeled_files=["pkg/app.py"])
    assert info["in_scope_files"] == 1
    assert info["in_scope_loc"] == 2
    assert info["excluded_files"] == 6
    assert (dst / "pkg" / "app.py").is_file()
    assert not (dst / "tests" / "test_app.py").exists()
    assert not (dst / "pkg" / "app_pb2.py").exists()
    assert not (dst / "pkg" / "bundle.min.js").exists()

    # Fail loudly if a labeled ground-truth file is excluded
    dst2 = tmp_path / "filtered2"
    with pytest.raises(ScopeExclusionError, match="Excluded directory"):
        build_filtered_source_copy(src, dst2, ScopePolicy(), labeled_files=["tests/test_app.py"])

    # Per-repo override can include a normally excluded directory
    override_policy = ScopePolicy.from_override({"include_dirs": ["examples"]})
    dst3 = tmp_path / "filtered3"
    info3 = build_filtered_source_copy(src, dst3, override_policy, labeled_files=["examples/demo.py"])
    assert info3["in_scope_files"] == 2
    assert (dst3 / "examples" / "demo.py").is_file()


def test_security_only_rule_policy(tmp_path):
    from src.benchmarks_research.runners.bandit_runner import BanditRunner
    from src.benchmarks_research.runners.sonarqube_runner import SonarQubeRunner
    from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner

    # Bandit excludes B101 (assert_used) and records rule policy metadata
    (tmp_path / "sample.py").write_text("assert True\n", encoding="utf-8")
    b_res = BanditRunner().run(tmp_path)
    assert b_res.status == "completed"
    assert len(b_res.findings) == 0
    assert b_res.metadata.get("rule_policy") == "security_only"
    assert "B101" in b_res.metadata.get("skipped_rules", [])

    # SonarQube parser excludes CODE_SMELL and keeps VULNERABILITY
    sq_json = '{"issues": [{"type": "CODE_SMELL", "component": "p:a.py", "line": 1, "rule": "python:S1", "message": "smell"}, {"type": "VULNERABILITY", "component": "p:a.py", "line": 2, "rule": "python:S2", "message": "vuln", "tags": ["cwe-89"]}]}'
    sq_findings = SonarQubeRunner().parse_issues_json(sq_json)
    assert len(sq_findings) == 1
    assert sq_findings[0].cwe == "CWE-89"

    # CodeGuardian records rule policy metadata
    cg_res = CodeGuardianRunner().run(tmp_path)
    assert cg_res.metadata.get("rule_policy") == "security_only"


def test_append_only_run_versioning_and_single_tool_rerun(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkMetric
    from src.benchmarks_research.service import BenchmarkService
    from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner

    # 1. Semgrep distinguishes docker_not_running from not_installed
    sr = SemgrepRunner()
    sr.docker_executable = "docker"
    sr.local_executable = None
    sr._docker_available = False
    res_sr = sr.run(Path("."))
    assert res_sr.status == "docker_not_running"

    # 2. run_repo_pipeline is append-only (never deletes prior runs) and supports tool=...
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    try:
        captured = {}
        monkeypatch.setattr(
            "src.benchmarks_research.pipeline.trigger_benchmark_pipeline_async",
            lambda repo_id, target_tools=None: captured.update({"repo_id": repo_id, "target_tools": target_tools}),
        )
        repo = ResearchRepo(name="test/vrepo", url="https://github.com/test/vrepo", status="partial", job_stage="partial")
        db.add(repo)
        db.commit()
        db.refresh(repo)

        old_run = BenchmarkRun(repo_id=repo.id, tool="codeguardian", status="completed", run_version=1, is_superseded=False)
        old_metric = BenchmarkMetric(repo_id=repo.id, tool="codeguardian", precision=0.5, recall=0.5, run_version=1, is_superseded=False)
        db.add_all([old_run, old_metric])
        db.commit()

        svc = BenchmarkService(db)
        svc.run_repo_pipeline(repo.id, tool="semgrep")

        # Prior run and metric are preserved!
        assert db.query(BenchmarkRun).filter(BenchmarkRun.repo_id == repo.id).count() == 1
        assert db.query(BenchmarkMetric).filter(BenchmarkMetric.repo_id == repo.id).count() == 1
        assert captured["target_tools"] == ["semgrep"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_recover_orphaned_jobs_and_partial_averages():
    import time
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkMetric
    from src.benchmarks_research.service import BenchmarkService
    from src.benchmarks_research.pipeline import _run_tool_with_timeout
    from src.benchmarks_research.schema import ToolExecutionResult

    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    db = TestSessionLocal()
    try:
        # 1. Startup recovery marks running jobs as interrupted by restart
        orphaned = ResearchRepo(
            name="test/orphaned-repo",
            url="https://github.com/test/orphaned-repo",
            status="running",
            job_stage="scanning_clean",
            job_progress=0.75,
        )
        db.add(orphaned)
        db.commit()

        svc = BenchmarkService(db)
        recovered = svc.recover_orphaned_jobs_on_startup()
        assert len(recovered) == 1
        db.refresh(orphaned)
        assert orphaned.status == "failed"
        assert "Interrupted by server restart at stage: scanning_clean" in orphaned.job_error

        # 2. Per-tool timeout isolates slow runner
        class SlowRunner:
            tool_name = "slow_tool"
            def get_version(self):
                return "1.0"
            def run(self, repo_path):
                time.sleep(2.0)
                return ToolExecutionResult(tool="slow_tool", tool_version="1.0", duration_s=2.0)

        res = _run_tool_with_timeout(SlowRunner(), repo_path=None, timeout_s=0.1)
        assert res.status == "timed_out"
        assert "timed out" in res.error_message

        # 3. Partial repo counts completed tool in averages and excludes timed-out tool
        partial_repo = ResearchRepo(
            name="test/partial-repo",
            url="https://github.com/test/partial-repo",
            status="partial",
            job_stage="partial",
            loc=1000,
            is_excluded=False,
        )
        db.add(partial_repo)
        db.commit()
        db.refresh(partial_repo)

        db.add(BenchmarkRun(repo_id=partial_repo.id, tool="codeguardian", status="completed", duration_s=0.5))
        db.add(BenchmarkRun(repo_id=partial_repo.id, tool="codeql", status="timed_out", duration_s=300.0))
        db.add(BenchmarkMetric(repo_id=partial_repo.id, tool="codeguardian", precision=0.8, recall=0.5))
        db.commit()

        overview = svc.get_overview_macro_metrics()
        assert overview["total_repos"] == 1
        assert overview["tools"]["codeguardian"]["has_data"] is True
        assert overview["tools"]["codeguardian"]["precision"] == 0.8
        assert overview["tools"]["codeql"]["has_data"] is False
        assert overview["tools"]["codeql"]["sample_size"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_shallow_clone_sha_validation_and_cache_isolation(tmp_path, monkeypatch):
    import pytest
    import subprocess
    from src.benchmarks_research.pipeline import _validate_sha40, compute_fetch_timeout_s, _get_bare_cache_dir

    # 1. Strict 40-char hex SHA validation
    valid_sha = "1c335944d6a8b1298baf179b7c0b3069f10c514b"
    assert _validate_sha40(valid_sha) == valid_sha
    for bad in ["1c335944", "1c335944; rm -rf /", "g" * 40, ""]:
        with pytest.raises(ValueError, match="40-character hex"):
            _validate_sha40(bad)

    # 2. Configurable LOC-scaled timeout
    assert compute_fetch_timeout_s(20000) >= 320
    monkeypatch.setenv("BENCHMARK_GIT_TIMEOUT_S", "240")
    assert compute_fetch_timeout_s(20000) == 240
    monkeypatch.delenv("BENCHMARK_GIT_TIMEOUT_S")

    # 3. Bare cache origin verification prevents cross-repo reuse
    cache_dir, origin_url, slug = _get_bare_cache_dir("https://github.com/testowner/testrepo")
    try:
        assert slug == "testowner/testrepo"
        assert cache_dir.name == "testowner__testrepo.git"
        # Tamper remote.origin.url to another repo -> _get_bare_cache_dir must recreate it
        subprocess.run(["git", "--git-dir", str(cache_dir), "remote", "set-url", "origin", "https://github.com/other/repo"], check=True)
        cache_dir2, _, _ = _get_bare_cache_dir("https://github.com/testowner/testrepo")
        proc = subprocess.run(["git", "--git-dir", str(cache_dir2), "config", "--get", "remote.origin.url"], capture_output=True, text=True, check=True)
        assert proc.stdout.strip().lower() == "https://github.com/testowner/testrepo"
    finally:
        from src.benchmarks_research.pipeline import _robust_rmtree
        _robust_rmtree(cache_dir)


def test_unified_scope_filtered_copy_and_fail_loud(tmp_path):
    import pytest
    from src.benchmarks_research.scope import ScopePolicy, ScopeExclusionError, build_filtered_source_copy

    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "tests").mkdir()
    (src / "docs").mkdir()
    (src / "examples").mkdir()
    (src / "vendor").mkdir()
    (src / "pkg" / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (src / "pkg" / "app_pb2.py").write_text("# generated\n", encoding="utf-8")
    (src / "pkg" / "bundle.min.js").write_text("var a=1;", encoding="utf-8")
    (src / "tests" / "test_app.py").write_text("assert True\n", encoding="utf-8")
    (src / "docs" / "conf.py").write_text("project='x'\n", encoding="utf-8")
    (src / "examples" / "demo.py").write_text("print(1)\n", encoding="utf-8")
    (src / "vendor" / "lib.py").write_text("z = 3\n", encoding="utf-8")

    dst = tmp_path / "filtered"
    info = build_filtered_source_copy(src, dst, ScopePolicy(), labeled_files=["pkg/app.py"])
    assert info["in_scope_files"] == 1
    assert info["in_scope_loc"] == 2
    assert info["excluded_files"] == 6
    assert (dst / "pkg" / "app.py").is_file()
    assert not (dst / "tests" / "test_app.py").exists()
    assert not (dst / "pkg" / "app_pb2.py").exists()
    assert not (dst / "pkg" / "bundle.min.js").exists()

    # Fail loudly if a labeled ground-truth file is excluded
    dst2 = tmp_path / "filtered2"
    with pytest.raises(ScopeExclusionError, match="Excluded directory"):
        build_filtered_source_copy(src, dst2, ScopePolicy(), labeled_files=["tests/test_app.py"])

    # Per-repo override can include a normally excluded directory
    override_policy = ScopePolicy.from_override({"include_dirs": ["examples"]})
    dst3 = tmp_path / "filtered3"
    info3 = build_filtered_source_copy(src, dst3, override_policy, labeled_files=["examples/demo.py"])
    assert info3["in_scope_files"] == 2
    assert (dst3 / "examples" / "demo.py").is_file()


def test_security_only_rule_policy(tmp_path):
    from src.benchmarks_research.runners.bandit_runner import BanditRunner
    from src.benchmarks_research.runners.sonarqube_runner import SonarQubeRunner
    from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner

    # Bandit excludes B101 (assert_used) and records rule policy metadata
    (tmp_path / "sample.py").write_text("assert True\n", encoding="utf-8")
    b_res = BanditRunner().run(tmp_path)
    assert b_res.status == "completed"
    assert len(b_res.findings) == 0
    assert b_res.metadata.get("rule_policy") == "security_only"
    assert "B101" in b_res.metadata.get("skipped_rules", [])

    # SonarQube parser excludes CODE_SMELL and keeps VULNERABILITY
    sq_json = '{"issues": [{"type": "CODE_SMELL", "component": "p:a.py", "line": 1, "rule": "python:S1", "message": "smell"}, {"type": "VULNERABILITY", "component": "p:a.py", "line": 2, "rule": "python:S2", "message": "vuln", "tags": ["cwe-89"]}]}'
    sq_findings = SonarQubeRunner().parse_issues_json(sq_json)
    assert len(sq_findings) == 1
    assert sq_findings[0].cwe == "CWE-89"

    # CodeGuardian records rule policy metadata
    cg_res = CodeGuardianRunner().run(tmp_path)
    assert cg_res.metadata.get("rule_policy") == "security_only"


def test_append_only_run_versioning_and_single_tool_rerun(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkMetric
    from src.benchmarks_research.service import BenchmarkService
    from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner

    # 1. Semgrep distinguishes docker_not_running from not_installed
    sr = SemgrepRunner()
    sr.docker_executable = "docker"
    sr.local_executable = None
    sr._docker_available = False
    res_sr = sr.run(Path("."))
    assert res_sr.status == "docker_not_running"

    # 2. run_repo_pipeline is append-only (never deletes prior runs) and supports tool=...
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    try:
        captured = {}
        monkeypatch.setattr(
            "src.benchmarks_research.pipeline.trigger_benchmark_pipeline_async",
            lambda repo_id, target_tools=None: captured.update({"repo_id": repo_id, "target_tools": target_tools}),
        )
        repo = ResearchRepo(name="test/vrepo", url="https://github.com/test/vrepo", status="partial", job_stage="partial")
        db.add(repo)
        db.commit()
        db.refresh(repo)

        old_run = BenchmarkRun(repo_id=repo.id, tool="codeguardian", status="completed", run_version=1, is_superseded=False)
        old_metric = BenchmarkMetric(repo_id=repo.id, tool="codeguardian", precision=0.5, recall=0.5, run_version=1, is_superseded=False)
        db.add_all([old_run, old_metric])
        db.commit()

        svc = BenchmarkService(db)
        svc.run_repo_pipeline(repo.id, tool="semgrep")

        # Prior run and metric are preserved!
        assert db.query(BenchmarkRun).filter(BenchmarkRun.repo_id == repo.id).count() == 1
        assert db.query(BenchmarkMetric).filter(BenchmarkMetric.repo_id == repo.id).count() == 1
        assert captured["target_tools"] == ["semgrep"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_zero_metric_na_definitions_and_macro_average_skipping():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkMetric
    from src.benchmarks_research.evaluator import BenchmarkEvaluator
    from src.benchmarks_research.ground_truth_loader import GroundTruthFinding, GroundTruthRepo
    from src.benchmarks_research.service import BenchmarkService

    gt = GroundTruthRepo(
        repo_name="test/zero-repo",
        url="https://github.com/test/zero-repo",
        pinned_vulnerable_sha="aaa",
        pinned_clean_sha="bbb",
        language="Python",
        loc=1000,
        description="Zero findings test",
        labeled_findings=[
            GroundTruthFinding(id="GT-1", file="a.py", line_start=10, line_end=10, cwe="CWE-89", severity="HIGH", label="vulnerable", source="synthetic")
        ],
    )
    evaluator = BenchmarkEvaluator()
    # 0 findings reported -> precision is None ('n/a'), recall is 0.0, localization & classification are None ('n/a')
    summary = evaluator.evaluate(ground_truth=gt, vulnerable_findings=[], clean_findings=[], duration_s=1.0)
    assert summary.precision is None
    assert summary.recall == 0.0
    assert summary.localization_accuracy is None
    assert summary.classification_accuracy is None

    # Macro-average skips n/a (None) rather than treating it as 0
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    try:
        r1 = ResearchRepo(name="test/r1", url="https://github.com/test/r1", status="done", loc=1000, is_excluded=False)
        r2 = ResearchRepo(name="test/r2", url="https://github.com/test/r2", status="done", loc=1000, is_excluded=False)
        db.add_all([r1, r2])
        db.commit()
        db.refresh(r1)
        db.refresh(r2)

        db.add(BenchmarkRun(repo_id=r1.id, tool="codeguardian", status="completed", duration_s=1.0))
        db.add(BenchmarkRun(repo_id=r2.id, tool="codeguardian", status="completed", duration_s=1.0))
        # r1 had 0 findings (tp=0, fp=0, fn=1) -> precision/loc/cls must become None (n/a)
        db.add(BenchmarkMetric(repo_id=r1.id, tool="codeguardian", precision=0.0, recall=0.0, localization_accuracy=0.0, classification_accuracy=0.0, counts_json={"tp": 0, "fp": 0, "fn": 1}))
        # r2 had 1 TP out of 1 finding -> precision=1.0, loc=1.0, cls=1.0
        db.add(BenchmarkMetric(repo_id=r2.id, tool="codeguardian", precision=1.0, recall=1.0, localization_accuracy=1.0, classification_accuracy=1.0, counts_json={"tp": 1, "fp": 0, "fn": 0}))
        db.commit()

        ov = BenchmarkService(db).get_overview_macro_metrics()
        cg = ov["tools"]["codeguardian"]
        assert cg["precision"] == 1.0  # skipped r1's n/a instead of averaging (0+1)/2 = 0.5
        assert cg["recall"] == 0.5     # averaged (0.0 + 1.0)/2 = 0.5
        assert cg["localization_accuracy"] == 1.0
        assert cg["classification_accuracy"] == 1.0
        assert cg["sample_counts"]["precision"] == 1
        assert cg["sample_counts"]["recall"] == 2
        assert cg["sample_counts"]["localization_accuracy"] == 1
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


def test_shallow_clone_sha_validation_and_cache_isolation(tmp_path, monkeypatch):
    import pytest
    import subprocess
    from src.benchmarks_research.pipeline import _validate_sha40, compute_fetch_timeout_s, _get_bare_cache_dir

    # 1. Strict 40-char hex SHA validation
    valid_sha = "1c335944d6a8b1298baf179b7c0b3069f10c514b"
    assert _validate_sha40(valid_sha) == valid_sha
    for bad in ["1c335944", "1c335944; rm -rf /", "g" * 40, ""]:
        with pytest.raises(ValueError, match="40-character hex"):
            _validate_sha40(bad)

    # 2. Configurable LOC-scaled timeout
    assert compute_fetch_timeout_s(20000) >= 320
    monkeypatch.setenv("BENCHMARK_GIT_TIMEOUT_S", "240")
    assert compute_fetch_timeout_s(20000) == 240
    monkeypatch.delenv("BENCHMARK_GIT_TIMEOUT_S")

    # 3. Bare cache origin verification prevents cross-repo reuse
    cache_dir, origin_url, slug = _get_bare_cache_dir("https://github.com/testowner/testrepo")
    try:
        assert slug == "testowner/testrepo"
        assert cache_dir.name == "testowner__testrepo.git"
        # Tamper remote.origin.url to another repo -> _get_bare_cache_dir must recreate it
        subprocess.run(["git", "--git-dir", str(cache_dir), "remote", "set-url", "origin", "https://github.com/other/repo"], check=True)
        cache_dir2, _, _ = _get_bare_cache_dir("https://github.com/testowner/testrepo")
        proc = subprocess.run(["git", "--git-dir", str(cache_dir2), "config", "--get", "remote.origin.url"], capture_output=True, text=True, check=True)
        assert proc.stdout.strip().lower() == "https://github.com/testowner/testrepo"
    finally:
        from src.benchmarks_research.pipeline import _robust_rmtree
        _robust_rmtree(cache_dir)


def test_unified_scope_filtered_copy_and_fail_loud(tmp_path):
    import pytest
    from src.benchmarks_research.scope import ScopePolicy, ScopeExclusionError, build_filtered_source_copy

    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "tests").mkdir()
    (src / "docs").mkdir()
    (src / "examples").mkdir()
    (src / "vendor").mkdir()
    (src / "pkg" / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (src / "pkg" / "app_pb2.py").write_text("# generated\n", encoding="utf-8")
    (src / "pkg" / "bundle.min.js").write_text("var a=1;", encoding="utf-8")
    (src / "tests" / "test_app.py").write_text("assert True\n", encoding="utf-8")
    (src / "docs" / "conf.py").write_text("project='x'\n", encoding="utf-8")
    (src / "examples" / "demo.py").write_text("print(1)\n", encoding="utf-8")
    (src / "vendor" / "lib.py").write_text("z = 3\n", encoding="utf-8")

    dst = tmp_path / "filtered"
    info = build_filtered_source_copy(src, dst, ScopePolicy(), labeled_files=["pkg/app.py"])
    assert info["in_scope_files"] == 1
    assert info["in_scope_loc"] == 2
    assert info["excluded_files"] == 6
    assert (dst / "pkg" / "app.py").is_file()
    assert not (dst / "tests" / "test_app.py").exists()
    assert not (dst / "pkg" / "app_pb2.py").exists()
    assert not (dst / "pkg" / "bundle.min.js").exists()

    # Fail loudly if a labeled ground-truth file is excluded
    dst2 = tmp_path / "filtered2"
    with pytest.raises(ScopeExclusionError, match="Excluded directory"):
        build_filtered_source_copy(src, dst2, ScopePolicy(), labeled_files=["tests/test_app.py"])

    # Per-repo override can include a normally excluded directory
    override_policy = ScopePolicy.from_override({"include_dirs": ["examples"]})
    dst3 = tmp_path / "filtered3"
    info3 = build_filtered_source_copy(src, dst3, override_policy, labeled_files=["examples/demo.py"])
    assert info3["in_scope_files"] == 2
    assert (dst3 / "examples" / "demo.py").is_file()


def test_security_only_rule_policy(tmp_path):
    from src.benchmarks_research.runners.bandit_runner import BanditRunner
    from src.benchmarks_research.runners.sonarqube_runner import SonarQubeRunner
    from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner

    # Bandit excludes B101 (assert_used) and records rule policy metadata
    (tmp_path / "sample.py").write_text("assert True\n", encoding="utf-8")
    b_res = BanditRunner().run(tmp_path)
    assert b_res.status == "completed"
    assert len(b_res.findings) == 0
    assert b_res.metadata.get("rule_policy") == "security_only"
    assert "B101" in b_res.metadata.get("skipped_rules", [])

    # SonarQube parser excludes CODE_SMELL and keeps VULNERABILITY
    sq_json = '{"issues": [{"type": "CODE_SMELL", "component": "p:a.py", "line": 1, "rule": "python:S1", "message": "smell"}, {"type": "VULNERABILITY", "component": "p:a.py", "line": 2, "rule": "python:S2", "message": "vuln", "tags": ["cwe-89"]}]}'
    sq_findings = SonarQubeRunner().parse_issues_json(sq_json)
    assert len(sq_findings) == 1
    assert sq_findings[0].cwe == "CWE-89"

    # CodeGuardian records rule policy metadata
    cg_res = CodeGuardianRunner().run(tmp_path)
    assert cg_res.metadata.get("rule_policy") == "security_only"


def test_append_only_run_versioning_and_single_tool_rerun(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.db.models import Base
    from src.db.benchmark_models import ResearchRepo, BenchmarkRun, BenchmarkMetric
    from src.benchmarks_research.service import BenchmarkService
    from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner

    # 1. Semgrep distinguishes docker_not_running from not_installed
    sr = SemgrepRunner()
    sr.docker_executable = "docker"
    sr.local_executable = None
    sr._docker_available = False
    res_sr = sr.run(Path("."))
    assert res_sr.status == "docker_not_running"

    # 2. run_repo_pipeline is append-only (never deletes prior runs) and supports tool=...
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, execution_options={"schema_translate_map": {"benchmark": None}},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    try:
        captured = {}
        monkeypatch.setattr(
            "src.benchmarks_research.pipeline.trigger_benchmark_pipeline_async",
            lambda repo_id, target_tools=None: captured.update({"repo_id": repo_id, "target_tools": target_tools}),
        )
        repo = ResearchRepo(name="test/vrepo", url="https://github.com/test/vrepo", status="partial", job_stage="partial")
        db.add(repo)
        db.commit()
        db.refresh(repo)

        old_run = BenchmarkRun(repo_id=repo.id, tool="codeguardian", status="completed", run_version=1, is_superseded=False)
        old_metric = BenchmarkMetric(repo_id=repo.id, tool="codeguardian", precision=0.5, recall=0.5, run_version=1, is_superseded=False)
        db.add_all([old_run, old_metric])
        db.commit()

        svc = BenchmarkService(db)
        svc.run_repo_pipeline(repo.id, tool="semgrep")

        # Prior run and metric are preserved!
        assert db.query(BenchmarkRun).filter(BenchmarkRun.repo_id == repo.id).count() == 1
        assert db.query(BenchmarkMetric).filter(BenchmarkMetric.repo_id == repo.id).count() == 1
        assert captured["target_tools"] == ["semgrep"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)



