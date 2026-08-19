"""
Unit Tests for Pre-Launch Security Checklist (TASK-SEC-LAUNCH).

Tests 20 production readiness checks across:
- Vulnerable codebase (PyGoat style - fails multiple checks)
- Clean, well-secured reference codebase (passes security checks)
- Runtime/Infrastructure checks (ensuring Manual Review categorization)
- Live FastAPI endpoint integration
"""

from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from src.agents.launch_checklist import (
    ChecklistItem,
    LaunchChecklistReport,
    PreLaunchSecurityAuditor,
)
from src.api.server import app


class TestPreLaunchSecurityAuditor(unittest.TestCase):
    def setUp(self):
        self.auditor = PreLaunchSecurityAuditor()

    def test_vulnerable_codebase_fails_expected_checks(self):
        """
        Vulnerable repo containing hardcoded AWS key, raw SQL injection,
        weak MD5 hashing, unescaped XSS, and insecure cookie flags.
        """
        vulnerable_files = {
            "app.py": """
import hashlib
from fastapi import FastAPI, Response

app = FastAPI()
AWS_KEY = "AKIA1234567890ABCDEF"  # Hardcoded secret

@app.get("/login")
def login(username, password, resp: Response):
    # Weak MD5 hash
    hashed = hashlib.md5(password.encode()).hexdigest()
    # Insecure cookie
    resp.set_cookie("session", "xyz", httponly=False, secure=False)
    return {"status": "ok"}

@app.get("/users")
def get_users(user_id, db):
    # Raw SQL injection
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return db.execute(query)
""",
            "frontend/App.tsx": """
import React from 'react';

export const UserBio = ({ bioHtml }: { bioHtml: string }) => {
    // Dangerous XSS injection
    return <div dangerouslySetInnerHTML={{ __html: bioHtml }} />;
};
""",
            "requirements.txt": "requests==2.28.0\nurllib3==1.25.11\n",
            ".gitignore": "# Missing .env",
        }

        report = self.auditor.audit(file_contents=vulnerable_files)

        self.assertEqual(report.total_checks, 20)
        self.assertGreater(report.failed_count, 0)
        self.assertEqual(report.launch_status, "BLOCK_DEPLOYMENT")
        self.assertIn(report.grade, ("D", "F"))

        failed_check_ids = {item.id for item in report.items if item.status == "FAIL"}
        
        # Verify specific security failures were flagged
        self.assertIn("SEC-01", failed_check_ids)  # Hide API keys
        self.assertIn("SEC-02", failed_check_ids)  # Purge git secrets (.env in gitignore)
        self.assertIn("SEC-10", failed_check_ids)  # Secure session cookies
        self.assertIn("SEC-11", failed_check_ids)  # Hash passwords (MD5)
        self.assertIn("SEC-13", failed_check_ids)  # Parameterize queries (SQLi)
        self.assertIn("SEC-16", failed_check_ids)  # Escape user content (XSS)

    def test_clean_secured_codebase_passes_checks(self):
        """
        Well-secured reference repo with env vars, bcrypt, parameterized queries,
        and Pydantic input schemas.
        """
        clean_files = {
            "main.py": """
import os
from passlib.context import CryptContext
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(..., max_length=50)
    password: str = Field(..., min_length=8)

def hash_pw(pw: str) -> str:
    return pwd_context.hash(pw)

def get_user_by_id(db: Session, user_id: int):
    # Parameterized ORM query
    return db.query(User).filter(User.id == user_id).first()
""",
            "frontend/App.tsx": """
import React from 'react';

export const UserCard = ({ name }: { name: string }) => {
    // Safe React auto-escaping
    return <div className="user">{name}</div>;
};
""",
            "requirements.txt": "fastapi==0.115.0\npydantic==2.8.0\npasslib==1.7.4\nbcrypt==4.2.0\n",
            ".gitignore": ".env\n.env.local\n*.pem\n*.key\n__pycache__/\nnode_modules/\n",
        }

        report = self.auditor.audit(file_contents=clean_files)

        self.assertEqual(report.total_checks, 20)
        self.assertEqual(report.failed_count, 0)
        self.assertGreaterEqual(report.readiness_percentage, 50.0)

        passed_check_ids = {item.id for item in report.items if item.status == "PASS"}
        self.assertIn("SEC-01", passed_check_ids)  # No hardcoded API keys
        self.assertIn("SEC-02", passed_check_ids)  # .env in .gitignore
        self.assertIn("SEC-03", passed_check_ids)  # No admin DB key client side
        self.assertIn("SEC-11", passed_check_ids)  # Hash passwords (bcrypt)
        self.assertIn("SEC-13", passed_check_ids)  # Parameterize queries
        self.assertIn("SEC-14", passed_check_ids)  # Validate all input (Pydantic)
        self.assertIn("SEC-15", passed_check_ids)  # Block field tampering (extra='forbid')
        self.assertIn("SEC-16", passed_check_ids)  # Escape user content (React)
        self.assertIn("SEC-20", passed_check_ids)  # Dependency manifest

    def test_infrastructure_and_runtime_checks_marked_manual_review(self):
        """
        Confirms checks requiring live database or edge context (e.g., RLS, HTTPS redirect,
        response trimming) are categorized as MANUAL_REVIEW rather than false passes or false fails.
        """
        minimal_files = {
            "app.py": "print('hello')",
            ".gitignore": ".env\n",
        }

        report = self.auditor.audit(file_contents=minimal_files)
        items_by_id = {item.id: item for item in report.items}

        # SEC-04 (Enable row-level security)
        self.assertEqual(items_by_id["SEC-04"].status, "MANUAL_REVIEW")
        self.assertIsNotNone(items_by_id["SEC-04"].manual_review_reason)

        # SEC-19 (Force HTTPS)
        self.assertEqual(items_by_id["SEC-19"].status, "MANUAL_REVIEW")
        self.assertIsNotNone(items_by_id["SEC-19"].manual_review_reason)

    def test_live_repository_audit_execution(self):
        """Audits the actual CodeGuardian repository without mocking."""
        report = self.auditor.audit()

        self.assertEqual(report.total_checks, 20)
        self.assertGreaterEqual(report.readiness_percentage, 0.0)
        self.assertGreaterEqual(report.passed_count, 10)
        self.assertIn(report.launch_status, ("LAUNCH_READY", "NEEDS_REVIEW", "BLOCK_DEPLOYMENT"))
        self.assertIn(report.grade, ("A+", "A", "B", "C", "D", "F"))

        # Verify all 6 categories are represented in category summary
        self.assertEqual(len(report.category_summary), 6)
        self.assertIn("Secrets & Credentials", report.category_summary)
        self.assertIn("Access Control", report.category_summary)
        self.assertIn("Data Protection", report.category_summary)
        self.assertIn("Input Validation", report.category_summary)
        self.assertIn("Infrastructure & Headers", report.category_summary)
        self.assertIn("Dependencies", report.category_summary)


class TestLaunchChecklistAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_launch_checklist_endpoint_get_and_post(self):
        # Test GET
        res_get = self.client.get("/api/v1/security/launch-checklist")
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()
        self.assertEqual(data_get["total_checks"], 20)
        self.assertEqual(len(data_get["items"]), 20)

        # Test POST
        res_post = self.client.post("/api/v1/security/launch-checklist", json={})
        self.assertEqual(res_post.status_code, 200)
        data_post = res_post.json()
        self.assertEqual(data_post["total_checks"], 20)
        self.assertIn("grade", data_post)
        self.assertIn("readiness_percentage", data_post)


if __name__ == "__main__":
    unittest.main()
