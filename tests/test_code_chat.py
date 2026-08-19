"""
Unit and Integration Tests for Code Q&A Chat Agent & FastAPI Endpoints (TASK-FS1 / Restore Chat)
"""
import pytest
from fastapi.testclient import TestClient
from src.api.server import app
from src.agents.code_chat import code_chat, _extract_line_references

client = TestClient(app)


def test_extract_line_references():
    text = "Insecure deserialization at Line 28 and another issue at [Line 45], see lines 12."
    lines = _extract_line_references(text)
    assert 28 in lines
    assert 45 in lines
    assert 12 in lines


def test_code_chat_function_with_context():
    question = "Why is this flagged as a risk?"
    file_code = "import pickle\ntfidf = pickle.load(open('model.pkl', 'rb'))"
    security_findings = [{
        "title": "OWASP A08: Insecure Deserialization via untrusted pickle payload",
        "line": 2,
        "severity": "HIGH",
        "description": "Arbitrary code execution during unpickling.",
        "remediation": "Use safe loader or context manager."
    }]

    res = code_chat(
        question=question,
        filepath="SMS-Spam-Classifier/app.py",
        file_code=file_code,
        security_findings=security_findings,
    )

    assert "answer" in res
    assert len(res["answer"]) > 10
    assert res["status"] == "completed"
    assert "line_references" in res


def test_chat_api_endpoint_post():
    payload = {
        "question": "Explain this fix",
        "filepath": "app.py",
        "file_code": "import pickle\nwith open('m.pkl', 'rb') as f: pickle.load(f)",
        "proposed_fix": "with open('m.pkl', 'rb') as f: pickle.load(f)",
        "security_findings": [],
        "history": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi! How can I help with your code?"}],
        "model": "qwen-2.5-coder-32b"
    }
    response = client.post("/api/v1/chat/code", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert data["status"] == "completed"
    assert "model_used" in data


def test_agents_chat_api_endpoint_post():
    payload = {
        "question": "What does this function do?",
        "filepath": "utils.py",
        "file_code": "def process(): return True",
    }
    response = client.post("/api/v1/chat/code", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert len(data["answer"]) > 5


def test_code_chat_general_question_natural_reply():
    """Verify general trivia / non-code questions receive a natural answer from the LLM."""
    payload = {
        "question": "What is the capital of France?",
        "filepath": "app.py",
        "file_code": "def foo(): pass",
    }
    response = client.post("/api/v1/chat/code", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "paris" in data["answer"].lower()


def test_code_chat_error_handling_on_failure(monkeypatch):
    """Confirm that when LLM providers fail, an explicit error is returned, never a fake canned success."""
    from src.agents import model_router
    def fake_execute_chain(*args, **kwargs):
        raise RuntimeError("Connection to LLM host timed out.")

    monkeypatch.setattr(model_router.ModelProviderChain, "execute_chain", fake_execute_chain)

    payload = {
        "question": "Explain this fix",
        "filepath": "app.py",
    }
    response = client.post("/api/v1/chat/code", json=payload)
    assert response.status_code == 500
    assert "Connection to LLM host timed out" in response.json()["detail"]
