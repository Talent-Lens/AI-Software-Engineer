"""
Comprehensive Unit & Integration Test Suite for FastAPI Backend & WebSockets (TASK-FS1)
"""
import pytest
from fastapi.testclient import TestClient
from src.api.server import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "version" in data


def test_health_check_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert data["vector_store"] == "ready"


def test_retrieval_search_endpoint():
    payload = {
        "query": "function to parse AST python chunks",
        "top_k": 3,
        "use_hybrid": True,
        "rerank": False
    }
    response = client.post("/api/v1/retrieval/search", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "results" in data
    assert isinstance(data["results"], list)


def test_security_audit_endpoint():
    payload = {"filepath": "graph.py"}
    response = client.post("/api/v1/security/audit", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "scorecard" in data


def test_feedback_endpoint():
    payload = {
        "query": "how to search ChromaDB",
        "chunk_id": "chunk_123",
        "file_path": "src/retrieval/retriever.py",
        "code_snippet": "def retrieve(): pass",
        "feedback_type": "REJECT",
        "user_comment": "Irrelevant chunk retrieved for query"
    }
    response = client.post("/api/v1/feedback", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["feedback_type"] == "REJECT"
    assert "event_id" in data


def test_eval_run_endpoint():
    payload = {}
    response = client.post("/api/v1/eval/run", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "mean_context_recall" in data
    assert "mean_context_precision" in data


def test_analyze_endpoint():
    payload = {"filepath": "graph.py"}
    response = client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "agent_response" in data
    assert "review" in data
    assert "security_response" in data


def test_websocket_ping_pong():
    with client.websocket_connect("/ws/graph-stream") as websocket:
        # First message is connection_established
        conn_msg = websocket.receive_json()
        assert conn_msg["event"] == "connection_established"

        # Send ping
        websocket.send_json({"action": "ping"})
        response = websocket.receive_json()
        assert response["event"] == "pong"


def test_websocket_stream_analysis():
    with client.websocket_connect("/ws/graph-stream") as websocket:
        # First message: connection_established
        conn_msg = websocket.receive_json()
        assert conn_msg["event"] == "connection_established"

        # Send start_analysis
        websocket.send_json({"action": "start_analysis", "filepath": "graph.py"})

        events = []
        while True:
            msg = websocket.receive_json()
            events.append(msg["event"])
            if msg["event"] in ("pipeline_complete", "pipeline_error"):
                break

        assert "pipeline_start" in events
        assert "pipeline_complete" in events
