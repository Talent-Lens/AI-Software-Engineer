"""
Unit & Integration Tests for GitHub Webhook & AI PR Reviewer (TASK-FS4)
"""
import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.api.services.github_service import (
    verify_github_signature,
    format_ai_pr_review,
    process_pull_request_event,
)

client = TestClient(app)


# ==========================================
# HMAC SIGNATURE TESTS
# ==========================================

def test_verify_github_signature_valid():
    secret = "my_super_secret_key"
    payload = b'{"action": "opened", "number": 1}'
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    assert verify_github_signature(payload, valid_sig, secret=secret) is True


def test_verify_github_signature_invalid():
    secret = "my_super_secret_key"
    payload = b'{"action": "opened", "number": 1}'
    tampered_payload = b'{"action": "tampered", "number": 1}'
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    # Signature computed on original payload should fail on tampered payload
    assert verify_github_signature(tampered_payload, valid_sig, secret=secret) is False
    assert verify_github_signature(payload, "sha256=invalid_hash", secret=secret) is False
    assert verify_github_signature(payload, None, secret=secret) is False


def test_verify_github_signature_no_secret_bypasses():
    payload = b'{"test": true}'
    # When no secret is configured, returns True in dev
    assert verify_github_signature(payload, None, secret="") is True


# ==========================================
# MARKDOWN REVIEW FORMATTER TESTS
# ==========================================

def test_format_ai_pr_review_with_vulnerabilities():
    analysis_results = [
        {
            "filepath": "src/auth.py",
            "agent_response": {"bug_detected": True, "proposed_fix": "- old\n+ new"},
            "security_response": {"vulnerabilities": ["Hardcoded API secret found on line 12"]},
            "review": {"comments": ["Use os.getenv for credentials"]},
        }
    ]
    md = format_ai_pr_review(pr_number=42, repo_name="Talent-Lens/AI-Software-Engineer", analysis_results=analysis_results)

    assert "PR:** `#42`" in md
    assert "High Risk" in md
    assert "Hardcoded API secret found on line 12" in md
    assert "```diff" in md
    assert "Use os.getenv for credentials" in md


def test_format_ai_pr_review_clean():
    analysis_results = [
        {
            "filepath": "src/utils.py",
            "agent_response": {"bug_detected": False},
            "security_response": {"vulnerabilities": []},
            "review": {"comments": []},
        }
    ]
    md = format_ai_pr_review(pr_number=10, repo_name="Talent-Lens/AI-Software-Engineer", analysis_results=analysis_results)

    assert "PR:** `#10`" in md
    assert "Low Risk / Approved" in md
    assert "0 critical vulnerabilities" in md
    assert "No critical bugs identified" in md


# ==========================================
# REST API ENDPOINT TESTS
# ==========================================

def test_github_status_endpoint():
    response = client.get("/api/v1/github/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "github_token_configured" in data
    assert "webhook_secret_configured" in data


def test_github_webhook_ping_event():
    headers = {
        "X-GitHub-Event": "ping",
        "Content-Type": "application/json",
    }
    payload = {"zen": "Keep it logically awesome."}
    response = client.post("/api/v1/github/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["event"] == "ping"


def test_github_webhook_pr_opened_event():
    headers = {
        "X-GitHub-Event": "pull_request",
        "Content-Type": "application/json",
    }
    payload = {
        "action": "opened",
        "pull_request": {"number": 7},
        "repository": {
            "name": "AI-Software-Engineer",
            "full_name": "Talent-Lens/AI-Software-Engineer",
            "owner": {"login": "Talent-Lens"},
        },
    }
    response = client.post("/api/v1/github/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["pr_number"] == 7
    assert "review_markdown" in data


def test_github_webhook_invalid_signature():
    secret = "secret123"
    import os
    os.environ["GITHUB_WEBHOOK_SECRET"] = secret

    try:
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=invalid_hash",
            "Content-Type": "application/json",
        }
        payload = {"action": "opened"}
        response = client.post("/api/v1/github/webhook", json=payload, headers=headers)
        assert response.status_code == 401
    finally:
        del os.environ["GITHUB_WEBHOOK_SECRET"]


def test_manual_pr_review_endpoint():
    payload = {
        "owner": "Talent-Lens",
        "repo": "AI-Software-Engineer",
        "pull_number": 5,
    }
    response = client.post("/api/v1/github/review-pr", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["pr_number"] == 5
    assert "review_markdown" in data
