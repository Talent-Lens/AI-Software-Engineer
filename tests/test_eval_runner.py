"""
Unit tests for RAG Triad Evaluation Suite & Benchmark Runner (TASK-E6 & TASK-FS6).
Verifies strict computation of Recall, Precision, Faithfulness, F1 Score, and IR ranking.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.eval.eval_runner import (
    BenchmarkTestCase,
    ContextPrecisionEvaluator,
    ContextRecallEvaluator,
    FaithfulnessEvaluator,
    GOLDEN_BENCHMARK_DATASET,
    RAGTriadEvalRunner,
    RetrievalMetricsEvaluator,
)
from src.schema import Chunk


class TestContextRecallEvaluator(unittest.TestCase):
    def test_recall_perfect(self):
        tc = BenchmarkTestCase(
            id="TC-1",
            query="find bare except",
            ground_truth_file="src/agents/bug_detection.py",
            ground_truth_chunk_id="src/agents/bug_detection.py::find_bare_excepts::39",
            ground_truth_keywords=["bare_except", "find_bare_excepts"],
            ground_truth_answer="Explanation",
        )
        c = Chunk(
            id="src/agents/bug_detection.py::find_bare_excepts::39",
            file_path="src/agents/bug_detection.py",
            start_line=39,
            end_line=50,
            type="function",
            name="find_bare_excepts",
            code="def find_bare_excepts(): pass # bare_except",
        )
        score = ContextRecallEvaluator.evaluate(tc, [c])
        self.assertEqual(score, 1.0)

    def test_recall_partial(self):
        """Target chunk matches file but only 1 of 2 essential keywords is in retrieved context."""
        tc = BenchmarkTestCase(
            id="TC-1B",
            query="find bare except",
            ground_truth_file="src/agents/bug_detection.py",
            ground_truth_chunk_id="src/agents/bug_detection.py::find_bare_excepts::39",
            ground_truth_keywords=["bare_except", "suppress_exception"],
            ground_truth_answer="Explanation",
        )
        c = Chunk(
            id="src/agents/bug_detection.py::find_bare_excepts::39",
            file_path="src/agents/bug_detection.py",
            start_line=39,
            end_line=50,
            type="function",
            name="find_bare_excepts",
            code="def find_bare_excepts(): pass # bare_except only",
        )
        score = ContextRecallEvaluator.evaluate(tc, [c])
        # 0.6 * 1.0 (target retrieved) + 0.4 * 0.5 (1/2 keywords) = 0.8
        self.assertEqual(score, 0.8)

    def test_recall_zero(self):
        tc = BenchmarkTestCase(
            id="TC-2",
            query="sql injection",
            ground_truth_file="src/agents/security_auditor.py",
            ground_truth_chunk_id="src/agents/security_auditor.py::sqli",
            ground_truth_keywords=["SQLi", "execute"],
            ground_truth_answer="Answer",
        )
        c = Chunk(
            id="other.py::func::1",
            file_path="other.py",
            start_line=1,
            end_line=5,
            type="function",
            name="func",
            code="def func(): print('hello')",
        )
        score = ContextRecallEvaluator.evaluate(tc, [c])
        self.assertEqual(score, 0.0)


class TestContextPrecisionEvaluator(unittest.TestCase):
    def test_precision_clean_top_rank(self):
        tc = BenchmarkTestCase(
            id="TC-1",
            query="ast chunker",
            ground_truth_file="src/indexing/chunker.py",
            ground_truth_chunk_id="src/indexing/chunker.py::chunk_file",
            ground_truth_keywords=["chunk_file", "ast"],
            ground_truth_answer="",
        )
        c1 = Chunk(
            id="src/indexing/chunker.py::chunk_file",
            file_path="src/indexing/chunker.py",
            start_line=1,
            end_line=10,
            type="function",
            name="chunk_file",
            code="def chunk_file(): pass # ast",
        )
        score = ContextPrecisionEvaluator.evaluate(tc, [c1])
        self.assertEqual(score, 1.0)

    def test_precision_distractor_penalty(self):
        """Relevant chunk placed at rank 3 after two completely irrelevant distractors."""
        tc = BenchmarkTestCase(
            id="TC-1B",
            query="ast chunker",
            ground_truth_file="src/indexing/chunker.py",
            ground_truth_chunk_id="src/indexing/chunker.py::chunk_file",
            ground_truth_keywords=["chunk_file", "ast"],
            ground_truth_answer="",
        )
        d1 = Chunk(id="misc.py::1", file_path="misc.py", start_line=1, end_line=5, type="f", name="d1", code="foo")
        d2 = Chunk(id="noisy.py::2", file_path="noisy.py", start_line=1, end_line=5, type="f", name="d2", code="bar")
        rel = Chunk(
            id="src/indexing/chunker.py::chunk_file",
            file_path="src/indexing/chunker.py",
            start_line=1,
            end_line=10,
            type="function",
            name="chunk_file",
            code="def chunk_file(): pass # ast",
        )
        score = ContextPrecisionEvaluator.evaluate(tc, [d1, d2, rel])
        # Relevant item at rank 3 -> precision = (1/3) / 1 = 0.3333...
        self.assertAlmostEqual(score, 1.0 / 3.0, places=3)

    def test_precision_empty(self):
        tc = BenchmarkTestCase(
            id="TC-2",
            query="test",
            ground_truth_file="test.py",
            ground_truth_chunk_id="test.py::1",
            ground_truth_keywords=["test"],
            ground_truth_answer="",
        )
        score = ContextPrecisionEvaluator.evaluate(tc, [])
        self.assertEqual(score, 0.0)


class TestFaithfulnessEvaluator(unittest.TestCase):
    def test_faithfulness_grounded(self):
        answer = "The function chunk_file parses python code using ast and extracts function chunks."
        c = Chunk(
            id="chunker.py::chunk_file",
            file_path="src/indexing/chunker.py",
            start_line=1,
            end_line=10,
            type="function",
            name="chunk_file",
            code="def chunk_file(filepath): ast parse python code function chunks",
        )
        score = FaithfulnessEvaluator.evaluate(answer, [c])
        self.assertGreaterEqual(score, 0.8)

    def test_faithfulness_hallucinated(self):
        """Answer claims a fabricated class and library that do not exist anywhere in retrieved context."""
        hallucinated_answer = "We use the QuantumBlockchainEncrypter module with HyperLedgerProtocol to secure private tokens."
        c = Chunk(
            id="auth.py::1",
            file_path="src/auth.py",
            start_line=1,
            end_line=10,
            type="function",
            name="auth_user",
            code="def auth_user(username, password): return verify_password(password)",
        )
        score = FaithfulnessEvaluator.evaluate(hallucinated_answer, [c])
        # Must fail grounding check and score low (<= 0.4)
        self.assertLessEqual(score, 0.4)

    def test_faithfulness_empty_context(self):
        score = FaithfulnessEvaluator.evaluate("Some generated answer", [])
        self.assertEqual(score, 0.0)


class TestRetrievalMetricsEvaluator(unittest.TestCase):
    def test_ir_metrics_hit_at_rank_1(self):
        tc = BenchmarkTestCase(
            id="TC-1",
            query="target",
            ground_truth_file="target.py",
            ground_truth_chunk_id="target.py::1",
            ground_truth_keywords=["target_kw"],
            ground_truth_answer="",
        )
        c1 = Chunk(
            id="target.py::1",
            file_path="target.py",
            start_line=1,
            end_line=5,
            type="function",
            name="target",
            code="target_kw",
        )
        res = RetrievalMetricsEvaluator.evaluate(tc, [c1])
        self.assertEqual(res["reciprocal_rank"], 1.0)
        self.assertEqual(res["hits_at_1"], 1)
        self.assertEqual(res["hits_at_3"], 1)

    def test_ir_metrics_hit_at_rank_2(self):
        tc = BenchmarkTestCase(
            id="TC-2",
            query="target",
            ground_truth_file="target.py",
            ground_truth_chunk_id="target.py::1",
            ground_truth_keywords=["target_kw"],
            ground_truth_answer="",
        )
        c1 = Chunk(id="noisy.py::1", file_path="noisy.py", start_line=1, end_line=5, type="f", name="n", code="nothing")
        c2 = Chunk(id="target.py::1", file_path="target.py", start_line=1, end_line=5, type="f", name="t", code="target_kw")
        res = RetrievalMetricsEvaluator.evaluate(tc, [c1, c2])
        self.assertEqual(res["reciprocal_rank"], 0.5)
        self.assertEqual(res["hits_at_1"], 0)
        self.assertEqual(res["hits_at_3"], 1)


class TestRAGTriadEvalRunner(unittest.TestCase):
    def test_golden_benchmark_dataset_size(self):
        """Ensures the Golden Benchmark suite contains >= 25 realistic test cases (no stub n=5)."""
        self.assertGreaterEqual(len(GOLDEN_BENCHMARK_DATASET), 25)

    def test_run_eval_full_suite(self):
        runner = RAGTriadEvalRunner()
        report = runner.run_eval()

        self.assertEqual(report.total_test_cases, 25)
        self.assertGreaterEqual(report.mean_context_recall, 0.85)
        self.assertGreaterEqual(report.mean_context_precision, 0.75)
        self.assertGreaterEqual(report.mean_f1_score, 0.80)
        self.assertGreaterEqual(report.mean_faithfulness, 0.85)
        self.assertGreaterEqual(report.mean_mrr, 0.70)

        with tempfile.TemporaryDirectory() as tmpdir:
            json_p = os.path.join(tmpdir, "eval_report.json")
            csv_p = os.path.join(tmpdir, "eval_report.csv")

            runner.export_json(report, json_p)
            runner.export_csv(report, csv_p)

            self.assertTrue(os.path.exists(json_p))
            self.assertTrue(os.path.exists(csv_p))


if __name__ == "__main__":
    unittest.main()
