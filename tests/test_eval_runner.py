"""
Unit tests for RAG Triad Evaluation Suite & Benchmark Runner (TASK-E6).
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
    def test_precision_clean(self):
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

    def test_faithfulness_empty_answer(self):
        score = FaithfulnessEvaluator.evaluate("", [])
        self.assertEqual(score, 1.0)


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
    def test_run_eval_and_exports(self):
        runner = RAGTriadEvalRunner()
        report = runner.run_eval()

        self.assertGreater(report.total_test_cases, 0)
        self.assertGreaterEqual(report.mean_context_recall, 0.0)
        self.assertGreaterEqual(report.mean_mrr, 0.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            json_p = os.path.join(tmpdir, "eval_report.json")
            csv_p = os.path.join(tmpdir, "eval_report.csv")

            runner.export_json(report, json_p)
            runner.export_csv(report, csv_p)

            self.assertTrue(os.path.exists(json_p))
            self.assertTrue(os.path.exists(csv_p))


if __name__ == "__main__":
    unittest.main()
