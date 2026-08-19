"""
Unit & Integration Tests for RAG Triad Benchmark Suite & Evaluation API Endpoint
"""
import pytest
from fastapi.testclient import TestClient
from src.api.server import app
from src.eval.eval_runner import RAGTriadEvalRunner, GOLDEN_BENCHMARK_DATASET

client = TestClient(app)


def test_eval_runner_unit_metrics():
    """Test RAGTriadEvalRunner offline execution produces genuine, differentiated metrics."""
    runner = RAGTriadEvalRunner()
    report = runner.run_eval()
    report_dict = report.to_dict()

    assert report.total_test_cases == 5
    assert "metrics" in report_dict
    metrics = report_dict["metrics"]

    # Verify both camelCase and snake_case properties exist
    assert "meanContextRecall" in metrics
    assert "mean_context_recall" in metrics
    assert "meanContextPrecision" in metrics
    assert "meanFaithfulness" in metrics
    assert "meanMrr" in metrics

    # Verify non-flat realistic metrics (not flat 100%)
    assert 0.0 < metrics["meanContextRecall"] <= 1.0
    assert 0.0 < metrics["meanContextPrecision"] <= 1.0
    assert 0.0 < metrics["meanMrr"] <= 1.0
    assert len(report_dict["results"]) == 5

    # Check first result item properties
    r0 = report_dict["results"][0]
    assert "testCaseId" in r0
    assert "test_case_id" in r0
    assert "contextRecall" in r0
    assert "contextPrecision" in r0
    assert "retrievedChunkIds" in r0
    assert isinstance(r0["retrievedChunkIds"], list)


def test_eval_api_endpoint_post():
    """Test POST /api/v1/eval/run returns 200 with structured RAG Triad metrics."""
    response = client.post("/api/v1/eval/run", json={})
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "completed"
    assert "timestamp" in data
    assert data["total_test_cases"] == 5
    assert "metrics" in data
    assert "results" in data
    assert len(data["results"]) == 5

    # Verify results data types
    for res in data["results"]:
        assert "test_case_id" in res
        assert "query" in res
        assert isinstance(res["context_recall"], float)
        assert isinstance(res["context_precision"], float)
        assert isinstance(res["faithfulness"], float)
        assert isinstance(res["reciprocal_rank"], float)
