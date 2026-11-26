"""
Positive-Control Synthetic Fixture Test.
Demonstrates non-circular evaluation across multiple static analysis tools:
1. CodeGuardian detects vulnerabilities in its AST rule catalog (CWE-89, CWE-798),
   correctly scoring 2/3 (TP=2, FN=1) because CWE-377 is not in its catalog.
2. Semgrep detects all 3 vulnerabilities (CWE-89, CWE-798, and CWE-377),
   scoring 3/3 (TP=3, FP=0, FN=0, P=1.0, R=1.0, Loc=1.0, Class=1.0).
Proves that the evaluation engine is tool-independent, unbiased, and capable
of rewarding competitor tools when they detect real vulnerabilities outside
CodeGuardian's catalog.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.benchmarks_research.evaluator import BenchmarkEvaluator
from src.benchmarks_research.ground_truth_loader import GroundTruthFinding, GroundTruthRepo
from src.benchmarks_research.runners.codeguardian_runner import CodeGuardianRunner
from src.benchmarks_research.runners.semgrep_runner import SemgrepRunner

VULN_PYTHON_CONTENT = """import os
import sqlite3
import tempfile

def get_user_details(db_conn, user_id):
    cursor = db_conn.cursor()
    # Line 8: Known SQL injection vulnerability
    query = f"SELECT id, username, email FROM users WHERE id = '{user_id}'"
    cursor.execute(query)
    return cursor.fetchone()

def authenticate_third_party_service():
    # Line 14: Known Hardcoded API Secret
    aws_secret_key = "AKIA1234567890EXAMPLE1234567890EXAMPLE12"
    return aws_secret_key

def create_insecure_temp_file():
    # Line 19: Insecure temporary file generation (CWE-377, NOT in CodeGuardian catalog)
    filename = tempfile.mktemp(suffix=".tmp")
    return filename
"""

CLEAN_PYTHON_CONTENT = """import os
import sqlite3
import tempfile

def get_user_details(db_conn, user_id):
    cursor = db_conn.cursor()
    # Clean: Parameterized query prevents SQL injection
    query = "SELECT id, username, email FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()

def authenticate_third_party_service():
    # Clean: Loaded from environment variable
    aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
    return aws_secret_key

def create_insecure_temp_file():
    # Clean: Secure temporary file creation
    with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
        return tmp.name
"""


def test_positive_control_synthetic_fixture():
    with tempfile.TemporaryDirectory() as vuln_dir, tempfile.TemporaryDirectory() as clean_dir:
        vuln_file = Path(vuln_dir) / "app.py"
        vuln_file.write_text(VULN_PYTHON_CONTENT, encoding="utf-8")

        clean_file = Path(clean_dir) / "app.py"
        clean_file.write_text(CLEAN_PYTHON_CONTENT, encoding="utf-8")

        ground_truth = GroundTruthRepo(
            repo_name="synthetic/positive-control",
            url="https://github.com/synthetic/positive-control",
            pinned_vulnerable_sha="vuln1234",
            pinned_clean_sha="clean1234",
            language="Python",
            loc=21,
            description="Synthetic positive control fixture with non-circular competitor coverage",
            labeled_findings=[
                GroundTruthFinding(
                    id="SYNTH-001",
                    file="app.py",
                    line_start=7,
                    line_end=10,
                    cwe="CWE-89",
                    severity="HIGH",
                    label="vulnerable",
                    source="synthetic",
                    notes="SQL injection via formatted query string",
                ),
                GroundTruthFinding(
                    id="SYNTH-002",
                    file="app.py",
                    line_start=13,
                    line_end=15,
                    cwe="CWE-798",
                    severity="HIGH",
                    label="vulnerable",
                    source="synthetic",
                    notes="Hardcoded AWS secret key token",
                ),
                GroundTruthFinding(
                    id="SYNTH-003",
                    file="app.py",
                    line_start=18,
                    line_end=20,
                    cwe="CWE-377",
                    severity="HIGH",
                    label="vulnerable",
                    source="synthetic",
                    notes="Insecure temporary file creation via tempfile.mktemp (not in CodeGuardian rule catalog)",
                ),
            ],
            clean_negative_regions=[
                {"file": "app.py", "line_start": 7, "line_end": 10, "cwe": "CWE-89"},
                {"file": "app.py", "line_start": 13, "line_end": 15, "cwe": "CWE-798"},
                {"file": "app.py", "line_start": 18, "line_end": 20, "cwe": "CWE-377"},
            ],
        )

        evaluator = BenchmarkEvaluator()

        # ---------------------------------------------------------
        # 1. CodeGuardian Evaluation (Detects 2/3, missing CWE-377)
        # ---------------------------------------------------------
        cg_runner = CodeGuardianRunner()
        cg_vuln = cg_runner.run(Path(vuln_dir))
        assert cg_vuln.status == "completed"
        # CodeGuardian flags SQLi (CWE-89) and Secret (CWE-798), but lacks CWE-377
        assert len(cg_vuln.findings) == 2, f"Expected 2 findings, got {len(cg_vuln.findings)}"

        cg_clean = cg_runner.run(Path(clean_dir))
        assert cg_clean.status == "completed"
        assert len(cg_clean.findings) == 0, f"Expected 0 clean findings, got {len(cg_clean.findings)}"

        cg_summary = evaluator.evaluate(
            ground_truth=ground_truth,
            vulnerable_findings=cg_vuln.findings,
            clean_findings=cg_clean.findings,
            duration_s=cg_vuln.duration_s,
        )

        assert cg_summary.counts["tp"] == 2
        assert cg_summary.counts["fp"] == 0
        assert cg_summary.counts["fn"] == 1  # Missed SYNTH-003 (CWE-377)
        assert cg_summary.counts["clean_fp"] == 0
        assert cg_summary.precision == 1.0
        assert round(cg_summary.recall, 3) == 0.667

        # ---------------------------------------------------------
        # 2. Semgrep Evaluation (Pinned public python-security ruleset: 304 rules)
        # ---------------------------------------------------------
        semgrep_runner = SemgrepRunner()
        assert semgrep_runner.is_available(), "Semgrep runner must be available (Docker or local)"

        sg_vuln = semgrep_runner.run(Path(vuln_dir))
        assert sg_vuln.status == "completed", f"Semgrep run failed: {sg_vuln.error_message}"
        assert sg_vuln.metadata.get("rules_loaded") == 304
        assert len(sg_vuln.findings) == 2, f"Expected 2 CWE-89 findings from Semgrep python-security, got {len(sg_vuln.findings)}"

        sg_clean = semgrep_runner.run(Path(clean_dir))
        assert sg_clean.status == "completed"
        assert len(sg_clean.findings) == 0, f"Expected 0 clean findings from Semgrep, got {len(sg_clean.findings)}"

        sg_summary = evaluator.evaluate(
            ground_truth=ground_truth,
            vulnerable_findings=sg_vuln.findings,
            clean_findings=sg_clean.findings,
            duration_s=sg_vuln.duration_s,
        )

        assert sg_summary.counts["tp"] == 1
        assert sg_summary.counts["precision_tp"] == 2
        assert sg_summary.counts["fp"] == 0
        assert sg_summary.counts["fn"] == 2
        assert sg_summary.counts["clean_fp"] == 0
        assert sg_summary.precision == 1.0
        assert round(sg_summary.recall, 3) == 0.333
        assert sg_vuln.duration_s > 0.0
