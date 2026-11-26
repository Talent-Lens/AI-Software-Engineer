"""
Unit tests for the Deterministic Benchmark Evaluator.
Verifies all 6 metrics using hand-calculated expected values.
"""
import pytest
from src.benchmarks_research.evaluator import BenchmarkEvaluator, file_paths_match, normalize_file_path
from src.benchmarks_research.ground_truth_loader import (
    GroundTruthFinding,
    GroundTruthLoader,
    GroundTruthRepo,
)
from src.benchmarks_research.schema import NormalizedFinding


@pytest.fixture
def sample_ground_truth():
    findings = [
        GroundTruthFinding(
            id="GT-001",
            file="app/views.py",
            line_start=50,
            line_end=50,
            cwe="CWE-89",  # SQL Injection
            severity="HIGH",
            label="vulnerable",
            source="documented-vuln",
        ),
        GroundTruthFinding(
            id="GT-002",
            file="app/views.py",
            line_start=100,
            line_end=100,
            cwe="CWE-79",  # XSS
            severity="HIGH",
            label="vulnerable",
            source="documented-vuln",
        ),
        GroundTruthFinding(
            id="GT-003",
            file="app/auth.py",
            line_start=20,
            line_end=20,
            cwe="CWE-798",  # Hardcoded secret
            severity="HIGH",
            label="vulnerable",
            source="documented-vuln",
        ),
        GroundTruthFinding(
            id="GT-004",
            file="app/utils.py",
            line_start=80,
            line_end=80,
            cwe="CWE-502",  # Unsafe Deserialization
            severity="CRITICAL",
            label="vulnerable",
            source="documented-vuln",
        ),
    ]
    return GroundTruthRepo(
        repo_name="test-org/test-repo",
        url="https://github.com/test-org/test-repo",
        pinned_vulnerable_sha="abc1234",
        pinned_clean_sha="def5678",
        language="python",
        loc=500,  # 500 lines of code
        description="Handcrafted test repo",
        labeled_findings=findings,
        clean_negative_regions=[
            {"id": "CLN-1", "file": "app/clean.py", "line_start": 1, "line_end": 50, "label": "clean"}
        ],
    )


def test_path_normalization():
    assert file_paths_match("app/views.py", "app\\views.py")
    assert file_paths_match("repo/app/views.py", "app/views.py")
    assert file_paths_match("app/views.py", "repo/app/views.py")
    assert not file_paths_match("app/views.py", "app/other.py")


def test_cwe_equivalence_mapping():
    loader = GroundTruthLoader()
    # SQLi aliases: CWE-89 and CWE-564 should be equivalent
    assert loader.is_cwe_equivalent("CWE-89", "CWE-564")
    assert loader.is_cwe_equivalent("CWE-564", "CWE-89")
    assert loader.is_cwe_equivalent("SQL_INJECTION", "CWE-89")
    # Different categories should NOT be equivalent
    assert not loader.is_cwe_equivalent("CWE-89", "CWE-79")


def test_six_metrics_exact_hand_calculation(sample_ground_truth):
    evaluator = BenchmarkEvaluator()

    # We construct tool findings on vulnerable code:
    # 1. Matching GT-001 (line 50, CWE-89) -> tool reports line 51 (dist 1 <= 3: localized), CWE-564 (CWE match)
    # 2. Matching GT-002 (line 100, CWE-79) -> tool reports line 106 (dist 6 > 3: not localized), CWE-79 (CWE match)
    # 3. Matching GT-003 (line 20, CWE-798) -> tool reports line 20 (dist 0 <= 3: localized), CWE-89 (CWE mismatch)
    # 4. FP finding on line 200 of app/views.py (matches no ground truth)
    # Note: GT-004 is NOT detected by tool -> FN = 1.
    vulnerable_findings = [
        NormalizedFinding(
            tool="test_tool",
            file_path="app/views.py",
            line_start=51,
            line_end=51,
            cwe="CWE-564",  # Equivalent to CWE-89
            severity="HIGH",
        ),
        NormalizedFinding(
            tool="test_tool",
            file_path="app/views.py",
            line_start=106,
            line_end=106,
            cwe="CWE-79",
            severity="HIGH",
        ),
        NormalizedFinding(
            tool="test_tool",
            file_path="app/auth.py",
            line_start=20,
            line_end=20,
            cwe="CWE-89",  # Mismatched CWE (GT has CWE-798)
            severity="HIGH",
        ),
        NormalizedFinding(
            tool="test_tool",
            file_path="app/views.py",
            line_start=200,
            line_end=200,
            cwe="CWE-79",
            severity="LOW",
        ),
    ]

    # Tool findings on clean code: 2 false alarms
    clean_findings = [
        NormalizedFinding(tool="test_tool", file_path="app/views.py", line_start=10, line_end=10),
        NormalizedFinding(tool="test_tool", file_path="app/clean.py", line_start=25, line_end=25),
    ]

    duration_s = 5.0  # 5 seconds scan duration

    res = evaluator.evaluate(
        ground_truth=sample_ground_truth,
        vulnerable_findings=vulnerable_findings,
        clean_findings=clean_findings,
        duration_s=duration_s,
    )

    # Hand calculations:
    # TP = 3 (GT-001, GT-002, GT-003)
    # FP = 1 (views.py:200)
    # FN = 1 (GT-004)
    # Precision = TP / (TP + FP) = 3 / 4 = 0.75
    assert res.precision == pytest.approx(0.75, abs=1e-4)

    # Recall = TP / (TP + FN) = 3 / 4 = 0.75
    assert res.recall == pytest.approx(0.75, abs=1e-4)

    # Localization: 2 out of 3 TPs are <= 3 lines (GT-001 dist 1, GT-003 dist 0; GT-002 dist 6)
    # Localization = 2 / 3 = 0.6667
    assert res.localization_accuracy == pytest.approx(2.0 / 3.0, abs=1e-4)

    # Vulnerability Classification: 2 out of 3 TPs match CWE (GT-001 CWE-564==CWE-89, GT-002 CWE-79==CWE-79)
    # Classification = 2 / 3 = 0.6667
    assert res.classification_accuracy == pytest.approx(2.0 / 3.0, abs=1e-4)

    # False Positive Rate: 2 clean FPs on 500 LOC = (2 / 500) * 1000 = 4.0 false alarms / kLOC
    assert res.false_positive_rate == pytest.approx(4.0, abs=1e-4)

    # Scan Latency: 5.0s on 500 LOC = (5.0 / 500) * 1000 = 10.0 seconds / kLOC
    assert res.scan_latency == pytest.approx(10.0, abs=1e-4)

    assert res.counts["tp"] == 3
    assert res.counts["fp"] == 1
    assert res.counts["fn"] == 1
    assert res.counts["clean_fp"] == 2
