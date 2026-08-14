"""
Unit & Integration Test Suite for Enterprise Database & Analytics Persistence (TASK-FS6)
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from src.db.models import Base, Repository, AnalysisRun, EvalExperiment, UserFeedback, AuditLog
from src.db import crud
from src.db.session import get_db
from src.api.server import app


# Test database setup (Isolated in-memory SQLite with StaticPool so all sessions share the in-memory DB)
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def test_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def test_client(test_db):
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ==========================================
# MODEL & CRUD UNIT TESTS
# ==========================================

def test_repository_crud(test_db):
    repo = crud.create_repository(
        db=test_db,
        name="AI-Software-Engineer",
        owner="Talent-Lens",
        url="https://github.com/Talent-Lens/AI-Software-Engineer",
        default_branch="dev",
        primary_language="Python",
        total_files=42,
        total_chunks=350,
        metadata={"framework": "FastAPI"},
    )

    assert repo.id is not None
    assert repo.name == "AI-Software-Engineer"
    assert repo.primary_language == "Python"

    fetched = crud.get_repository(test_db, repo.id)
    assert fetched is not None
    assert fetched.name == "AI-Software-Engineer"

    fetched_by_name = crud.get_repository_by_name(test_db, "AI-Software-Engineer")
    assert fetched_by_name is not None
    assert fetched_by_name.id == repo.id

    all_repos = crud.list_repositories(test_db)
    assert len(all_repos) == 1
    assert all_repos[0].name == "AI-Software-Engineer"


def test_analysis_run_crud(test_db):
    repo = crud.create_repository(test_db, name="test-repo")
    run = crud.create_analysis_run(
        db=test_db,
        filepath="src/auth.py",
        status="completed",
        attempts=2,
        duration_ms=145.2,
        has_vulnerabilities=True,
        has_bugs=False,
        agent_response={"triage": "passed"},
        review={"score": 85},
        security_response={"vulnerabilities": ["hardcoded_secret"]},
        patch_diff="--- old\n+++ new",
        summary="Found 1 high severity secret issue",
        repo_id=repo.id,
    )

    assert run.id is not None
    assert run.has_vulnerabilities is True
    assert run.attempts == 2

    # Check audit log was automatically generated
    audit_logs = crud.list_audit_logs(test_db)
    assert len(audit_logs) >= 1
    assert any(log.action == "analysis_completed" for log in audit_logs)

    # Filter query
    vuln_runs = crud.list_analysis_runs(test_db, has_vulnerabilities=True)
    assert len(vuln_runs) == 1

    clean_runs = crud.list_analysis_runs(test_db, has_vulnerabilities=False)
    assert len(clean_runs) == 0


def test_eval_experiment_crud(test_db):
    exp = crud.create_eval_experiment(
        db=test_db,
        experiment_name="hybrid_search_benchmark_v1",
        test_cases_file="data/synthetic_bugs.json",
        total_test_cases=10,
        mean_context_recall=0.92,
        mean_context_precision=0.88,
        mean_faithfulness=0.95,
        mean_mrr=0.85,
        hits_at_1_rate=0.80,
        hits_at_3_rate=0.90,
        hits_at_5_rate=0.95,
        hits_at_10_rate=1.0,
        results_summary=[{"query": "parse AST", "passed": True}],
    )

    assert exp.id is not None
    assert exp.mean_faithfulness == 0.95
    assert exp.total_test_cases == 10

    fetched = crud.get_eval_experiment(test_db, exp.id)
    assert fetched is not None
    assert fetched.experiment_name == "hybrid_search_benchmark_v1"

    all_experiments = crud.list_eval_experiments(test_db)
    assert len(all_experiments) == 1


def test_user_feedback_crud(test_db):
    fb = crud.create_user_feedback(
        db=test_db,
        query="graph traversal AST",
        chunk_id="chunk_ast_01",
        file_path="src/indexing/chunker.py",
        code_snippet="def visit_node(): pass",
        feedback_type="ACCEPT",
        user_comment="Exact match for AST visitor",
    )

    assert fb.id is not None
    assert fb.feedback_type == "accept"

    feedback_list = crud.list_user_feedback(test_db, feedback_type="accept")
    assert len(feedback_list) == 1
    assert feedback_list[0].chunk_id == "chunk_ast_01"


def test_analytics_overview(test_db):
    # Empty DB stats
    overview = crud.get_analytics_overview(test_db)
    assert overview["total_repositories"] == 0
    assert overview["total_analysis_runs"] == 0
    assert overview["vulnerabilities_detected"] == 0
    assert overview["feedback"]["total"] == 0
    assert overview["feedback"]["acceptance_rate_percent"] == 100.0

    # Populate data
    crud.create_repository(test_db, name="repo1")
    crud.create_analysis_run(test_db, filepath="file1.py", has_vulnerabilities=True)
    crud.create_analysis_run(test_db, filepath="file2.py", has_vulnerabilities=False)
    crud.create_user_feedback(test_db, query="q1", chunk_id="c1", file_path="f1", feedback_type="accept")
    crud.create_user_feedback(test_db, query="q2", chunk_id="c2", file_path="f2", feedback_type="reject")
    crud.create_eval_experiment(test_db, mean_faithfulness=0.98)

    updated_overview = crud.get_analytics_overview(test_db)
    assert updated_overview["total_repositories"] == 1
    assert updated_overview["total_analysis_runs"] == 2
    assert updated_overview["vulnerabilities_detected"] == 1
    assert updated_overview["feedback"]["total"] == 2
    assert updated_overview["feedback"]["accepted"] == 1
    assert updated_overview["feedback"]["rejected"] == 1
    assert updated_overview["feedback"]["acceptance_rate_percent"] == 50.0
    assert updated_overview["latest_eval_metrics"] is not None
    assert updated_overview["latest_eval_metrics"]["mean_faithfulness"] == 0.98


# ==========================================
# REST API INTEGRATION TESTS
# ==========================================

def test_api_analytics_overview(test_client, test_db):
    crud.create_repository(test_db, name="enterprise-codebase")
    response = test_client.get("/api/v1/analytics/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["total_repositories"] == 1
    assert "feedback" in data


def test_api_analytics_runs_and_by_id(test_client, test_db):
    run = crud.create_analysis_run(
        test_db,
        filepath="graph.py",
        status="completed",
        has_vulnerabilities=True,
        summary="Security scan completed",
    )

    response = test_client.get("/api/v1/analytics/analysis-runs")
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 1
    assert runs[0]["filepath"] == "graph.py"

    # Fetch by ID
    run_response = test_client.get(f"/api/v1/analytics/analysis-runs/{run.id}")
    assert run_response.status_code == 200
    run_data = run_response.json()
    assert run_data["id"] == run.id
    assert run_data["has_vulnerabilities"] is True


def test_api_analytics_eval_history(test_client, test_db):
    crud.create_eval_experiment(test_db, experiment_name="benchmark_run_1", mean_faithfulness=0.91)
    response = test_client.get("/api/v1/analytics/eval-history")
    assert response.status_code == 200
    evals = response.json()
    assert len(evals) == 1
    assert evals[0]["experiment_name"] == "benchmark_run_1"


def test_api_analytics_audit_logs(test_client, test_db):
    crud.create_audit_log(test_db, action="admin_login", actor="user_admin")
    response = test_client.get("/api/v1/analytics/audit-logs")
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["action"] == "admin_login"


def test_api_feedback_persistence_integration(test_client, test_db):
    payload = {
        "query": "vector similarity search",
        "chunk_id": "chunk_vec_99",
        "file_path": "src/indexing/vector_store.py",
        "code_snippet": "def search(): pass",
        "feedback_type": "ACCEPT",
        "user_comment": "Relevant chunk",
    }
    fb_response = test_client.post("/api/v1/feedback", json=payload)
    assert fb_response.status_code == 200

    # Query analytics feedback endpoint to verify persistence in DB
    analytics_fb = test_client.get("/api/v1/analytics/feedback")
    assert analytics_fb.status_code == 200
    feedbacks = analytics_fb.json()
    assert len(feedbacks) == 1
    assert feedbacks[0]["chunk_id"] == "chunk_vec_99"
    assert feedbacks[0]["feedback_type"] == "accept"
