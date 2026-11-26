"""
Verify CodeQL against the synthetic positive-control fixture.
Tests vulnerable and clean snapshots, measures db build vs analysis time,
and evaluates matching against ground-truth entries.
"""
import tempfile
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.benchmarks.runners.codeql_runner import CodeQLRunner
from src.benchmarks.evaluator import BenchmarkEvaluator
from src.benchmarks.ground_truth_loader import GroundTruthRepo, GroundTruthFinding

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
    # Line 19: Insecure temporary file generation (CWE-377)
    filename = tempfile.mktemp(suffix=".tmp")
    return filename
"""

CLEAN_PYTHON_CONTENT = """import os
import sqlite3
import tempfile

def get_user_details(db_conn, user_id):
    cursor = db_conn.cursor()
    query = "SELECT id, username, email FROM users WHERE id = ?"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()

def authenticate_third_party_service():
    aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
    return aws_secret_key

def create_insecure_temp_file():
    with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
        return tmp.name
"""


def main():
    ground_truth = GroundTruthRepo(
        repo_name="synthetic/positive-control",
        url="https://github.com/synthetic/positive-control",
        pinned_vulnerable_sha="vuln1234",
        pinned_clean_sha="clean1234",
        language="Python",
        loc=21,
        description="Synthetic positive control fixture",
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
                notes="Insecure tempfile creation via tempfile.mktemp",
            ),
        ],
        clean_negative_regions=[
            {"file": "app.py", "line_start": 7, "line_end": 10, "cwe": "CWE-89"},
            {"file": "app.py", "line_start": 13, "line_end": 15, "cwe": "CWE-798"},
            {"file": "app.py", "line_start": 18, "line_end": 20, "cwe": "CWE-377"},
        ],
    )

    runner = CodeQLRunner()
    print("CodeQL Runner available:", runner.is_available())
    print("CodeQL Executable:", runner.executable)
    print("CodeQL Version:", runner.get_version())
    print("Query Suite:", runner.query_suite)

    with tempfile.TemporaryDirectory() as vuln_dir, tempfile.TemporaryDirectory() as clean_dir:
        vuln_file = Path(vuln_dir) / "app.py"
        vuln_file.write_text(VULN_PYTHON_CONTENT, encoding="utf-8")

        clean_file = Path(clean_dir) / "app.py"
        clean_file.write_text(CLEAN_PYTHON_CONTENT, encoding="utf-8")

        print("\n--- 1. Running CodeQL on Vulnerable Snapshot ---")
        vuln_res = runner.run(Path(vuln_dir))
        print("Vulnerable Run Status:", vuln_res.status)
        print("Duration:", f"{vuln_res.duration_s:.2f}s")
        print("Metadata:", json.dumps(vuln_res.metadata, indent=2))
        print(f"Total Findings Found: {len(vuln_res.findings)}")
        for i, f in enumerate(vuln_res.findings, 1):
            print(f"  Finding #{i}:")
            print(f"    File: {f.file_path}")
            print(f"    Lines: {f.line_start}-{f.line_end}")
            print(f"    CWE: {f.cwe}")
            print(f"    Severity: {f.severity}")
            print(f"    Rule ID: {f.rule_id}")
            print(f"    Title: {f.title}")

        print("\n--- 2. Running CodeQL on Clean Snapshot ---")
        clean_res = runner.run(Path(clean_dir))
        print("Clean Run Status:", clean_res.status)
        print("Duration:", f"{clean_res.duration_s:.2f}s")
        print("Metadata:", json.dumps(clean_res.metadata, indent=2))
        print(f"Total Clean Findings Found: {len(clean_res.findings)}")
        for i, f in enumerate(clean_res.findings, 1):
            print(f"  Clean Finding #{i}: {f.file_path}:{f.line_start} [{f.cwe}] {f.rule_id}")

        print("\n--- 3. Evaluating Benchmark Matching Engine ---")
        evaluator = BenchmarkEvaluator()
        summary = evaluator.evaluate(
            ground_truth=ground_truth,
            vulnerable_findings=vuln_res.findings,
            clean_findings=clean_res.findings,
            duration_s=vuln_res.duration_s,
        )

        print("Benchmark Evaluation Summary:")
        print(f"  Precision: {summary.precision * 100:.1f}%")
        print(f"  Recall: {summary.recall * 100:.1f}%")
        print(f"  Localization Accuracy: {summary.localization_accuracy * 100:.1f}%")
        print(f"  Classification Accuracy: {summary.classification_accuracy * 100:.1f}%")
        print(f"  Counts: TP={summary.counts['tp']}, FP={summary.counts['fp']}, FN={summary.counts['fn']}, Clean_FP={summary.counts['clean_fp']}")
        print(f"  TP Match Details ({len(summary.counts.get('tp_details', []))}):")
        for detail in summary.counts.get("tp_details", []):
            f = detail["finding"]
            print(f"    GT: {detail['gt_id']} -> Finding: {f.file_path}:{f.line_start} [{f.cwe}] Rule: {f.rule_id} (Dist: {detail['distance']}, Localized: {detail['is_localized']}, CWE Match: {detail['cwe_match']})")


if __name__ == "__main__":
    main()
