"""
Unit & Integration Test Suite for OpenTelemetry & Agent Tracing (TASK-FS5)
"""
import time
import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.telemetry.tracer import (
    collector,
    trace_span,
    traced,
    SpanRecord,
    TelemetryCollector,
)
from graph import run_pipeline

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_telemetry():
    collector.reset()
    yield
    collector.reset()


# ==========================================
# SPAN & COLLECTOR UNIT TESTS
# ==========================================

def test_span_record_lifecycle():
    span = SpanRecord(name="test_span", attributes={"env": "test"})
    assert span.status == "in_progress"
    assert span.span_id is not None
    assert span.trace_id is not None

    time.sleep(0.01)
    span.record_tokens(prompt_tokens=100, completion_tokens=50, model="qwen2.5-coder")
    span.finish(status="ok")

    assert span.status == "ok"
    assert span.duration_ms > 0
    assert span.token_usage["prompt_tokens"] == 100
    assert span.token_usage["completion_tokens"] == 50
    assert span.token_usage["total_tokens"] == 150
    assert span.token_usage["model"] == "qwen2.5-coder"


def test_trace_span_context_manager():
    with trace_span("database_query", attributes={"table": "repositories"}) as span:
        span.record_tokens(10, 5, model="small_embedder")

    traces = collector.get_traces(limit=10)
    assert len(traces) == 1
    assert traces[0]["name"] == "database_query"
    assert traces[0]["status"] == "ok"
    assert traces[0]["attributes"]["table"] == "repositories"


def test_trace_span_captures_exceptions():
    with pytest.raises(ValueError, match="Synthetic failure"):
        with trace_span("failing_node") as span:
            raise ValueError("Synthetic failure")

    traces = collector.get_traces(limit=10)
    assert len(traces) == 1
    assert traces[0]["name"] == "failing_node"
    assert traces[0]["status"] == "error"
    assert "Synthetic failure" in traces[0]["error_message"]


def test_traced_decorator_sync():
    @traced(name="custom_sync_func", attributes={"version": 1})
    def dummy_func(a, b):
        return a + b

    result = dummy_func(2, 3)
    assert result == 5

    traces = collector.get_traces(limit=10)
    assert len(traces) == 1
    assert traces[0]["name"] == "custom_sync_func"
    assert traces[0]["attributes"]["version"] == 1


@pytest.mark.anyio
async def test_traced_decorator_async():
    @traced(name="custom_async_func")
    async def dummy_async():
        return "ok"

    res = await dummy_async()
    assert res == "ok"

    traces = collector.get_traces(limit=10)
    assert len(traces) == 1
    assert traces[0]["name"] == "custom_async_func"


def test_metrics_summary_aggregation():
    # Record multiple spans with tokens
    with trace_span("agent_a") as s1:
        s1.record_tokens(100, 50, model="model_1")
    with trace_span("agent_a") as s2:
        s2.record_tokens(100, 50, model="model_1")
    with trace_span("agent_b") as s3:
        s3.record_tokens(200, 100, model="model_2")

    metrics = collector.get_metrics_summary()
    assert metrics["total_spans"] == 3
    assert metrics["total_errors"] == 0
    assert metrics["tokens"]["total_prompt_tokens"] == 400
    assert metrics["tokens"]["total_completion_tokens"] == 200
    assert metrics["tokens"]["total_tokens"] == 600
    assert "model_1" in metrics["tokens"]["by_model"]
    assert "agent_a" in metrics["latency_breakdowns"]
    assert metrics["latency_breakdowns"]["agent_a"]["invocations"] == 2


# ==========================================
# FASTAPI MIDDLEWARE & REST API TESTS
# ==========================================

def test_telemetry_middleware_headers():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "X-Trace-ID" in response.headers
    assert "X-Response-Time-Ms" in response.headers
    assert float(response.headers["X-Response-Time-Ms"]) >= 0


def test_api_telemetry_metrics_endpoint():
    # Make a couple requests to populate telemetry
    client.get("/api/v1/health")
    client.get("/api/v1/github/status")

    response = client.get("/api/v1/telemetry/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "total_spans" in data
    assert "tokens" in data
    assert "latency_breakdowns" in data
    assert data["total_spans"] >= 2


def test_api_telemetry_traces_endpoint():
    client.get("/api/v1/health")
    response = client.get("/api/v1/telemetry/traces?limit=10")
    assert response.status_code == 200
    traces = response.json()
    assert len(traces) >= 1
    assert any("http_request" in t["name"] for t in traces)


def test_api_telemetry_status_endpoint():
    response = client.get("/api/v1/telemetry/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert "supported_tracers" in data


def test_api_telemetry_reset_endpoint():
    client.get("/api/v1/health")
    client.get("/api/v1/github/status")
    assert len(collector._spans) >= 2

    reset_res = client.post("/api/v1/telemetry/reset")
    assert reset_res.status_code == 200
    data = reset_res.json()
    assert data["status"] == "success"
    # Only the POST /reset request itself was recorded by middleware
    assert len(collector._spans) == 1
    assert "reset" in collector._spans[0].name


# ==========================================
# LANGGRAPH PIPELINE INSTRUMENTATION TEST
# ==========================================

def test_langgraph_pipeline_tracing():
    collector.reset()
    res = run_pipeline("graph.py")
    assert res is not None

    traces = collector.get_traces(limit=20)
    trace_names = [t["name"] for t in traces]

    # Verify that LangGraph nodes were individually traced
    assert any("bug_detection" in name for name in trace_names)
    assert any("code_reviewer" in name for name in trace_names)
    assert any("security_auditor" in name for name in trace_names)
    assert any("langgraph_pipeline" in name for name in trace_names)

    # Verify tokens were recorded
    metrics = collector.get_metrics_summary()
    assert metrics["tokens"]["total_tokens"] > 0
