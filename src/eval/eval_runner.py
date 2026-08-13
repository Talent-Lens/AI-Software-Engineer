"""
RAG Triad Evaluation Suite & Benchmark Runner (TASK-E6)

Computes Context Recall, Context Precision, Faithfulness (Groundedness),
Mean Reciprocal Rank (MRR), and Hits@K across RAG retrieval and generation pipelines.
Outputs automated JSON and CSV performance reports.
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Sequence

from src.schema import Chunk, RetrievalResult

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkTestCase:
    id: str
    query: str
    ground_truth_file: str
    ground_truth_chunk_id: str
    ground_truth_keywords: list[str]
    ground_truth_answer: str


@dataclass
class TestCaseEvalResult:
    test_case_id: str
    query: str
    context_recall: float  # 0.0 to 1.0
    context_precision: float  # 0.0 to 1.0
    faithfulness: float  # 0.0 to 1.0
    reciprocal_rank: float  # 0.0 to 1.0
    hits_at_1: int  # 0 or 1
    hits_at_3: int  # 0 or 1
    hits_at_5: int  # 0 or 1
    hits_at_10: int  # 0 or 1
    generated_answer: str
    retrieved_chunk_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_case_id": self.test_case_id,
            "query": self.query,
            "context_recall": round(self.context_recall, 4),
            "context_precision": round(self.context_precision, 4),
            "faithfulness": round(self.faithfulness, 4),
            "reciprocal_rank": round(self.reciprocal_rank, 4),
            "hits_at_1": self.hits_at_1,
            "hits_at_3": self.hits_at_3,
            "hits_at_5": self.hits_at_5,
            "hits_at_10": self.hits_at_10,
            "generated_answer": self.generated_answer,
            "retrieved_chunk_ids": self.retrieved_chunk_ids,
        }


@dataclass
class AggregateEvalReport:
    timestamp: str
    total_test_cases: int
    mean_context_recall: float
    mean_context_precision: float
    mean_faithfulness: float
    mean_mrr: float
    hits_at_1_rate: float
    hits_at_3_rate: float
    hits_at_5_rate: float
    hits_at_10_rate: float
    results: list[TestCaseEvalResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_test_cases": self.total_test_cases,
            "metrics": {
                "mean_context_recall": round(self.mean_context_recall, 4),
                "mean_context_precision": round(self.mean_context_precision, 4),
                "mean_faithfulness": round(self.mean_faithfulness, 4),
                "mean_mrr": round(self.mean_mrr, 4),
                "hits_at_1_rate": round(self.hits_at_1_rate, 4),
                "hits_at_3_rate": round(self.hits_at_3_rate, 4),
                "hits_at_5_rate": round(self.hits_at_5_rate, 4),
                "hits_at_10_rate": round(self.hits_at_10_rate, 4),
            },
            "results": [r.to_dict() for r in self.results],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# RAG Triad Evaluation & Benchmark Report",
            f"",
            f"**Execution Timestamp:** `{self.timestamp}` | **Test Cases:** `{self.total_test_cases}`",
            f"",
            f"### RAG Triad Core Metrics",
            f"- **Context Recall:** `{self.mean_context_recall * 100:.2f}%`",
            f"- **Context Precision:** `{self.mean_context_precision * 100:.2f}%`",
            f"- **Faithfulness (Groundedness):** `{self.mean_faithfulness * 100:.2f}%`",
            f"",
            f"### IR Retrieval Performance Metrics",
            f"- **Mean Reciprocal Rank (MRR):** `{self.mean_mrr:.4f}`",
            f"- **Hits@1:** `{self.hits_at_1_rate * 100:.1f}%`",
            f"- **Hits@3:** `{self.hits_at_3_rate * 100:.1f}%`",
            f"- **Hits@5:** `{self.hits_at_5_rate * 100:.1f}%`",
            f"- **Hits@10:** `{self.hits_at_10_rate * 100:.1f}%`",
            f"",
            f"### Per-Test Case Breakdown",
            f"| ID | Query | Recall | Precision | Faithfulness | RR | Hits@3 |",
            f"|---|---|---|---|---|---|---|",
        ]
        for r in self.results:
            short_q = (r.query[:35] + "...") if len(r.query) > 35 else r.query
            lines.append(
                f"| {r.test_case_id} | {short_q} | `{r.context_recall:.2f}` | `{r.context_precision:.2f}` | `{r.faithfulness:.2f}` | `{r.reciprocal_rank:.2f}` | `{r.hits_at_3}` |"
            )
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evaluators (Context Recall, Context Precision, Faithfulness, Retrieval)
# ---------------------------------------------------------------------------

class ContextRecallEvaluator:
    """
    Evaluates Context Recall: Compares retrieved code chunks and text against
    ground-truth target chunk IDs, files, and essential keywords.
    """

    @staticmethod
    def evaluate(test_case: BenchmarkTestCase, retrieved_chunks: Sequence[Chunk | RetrievalResult | dict]) -> float:
        if not retrieved_chunks:
            return 0.0

        # Check if exact ground truth file or chunk ID is retrieved
        target_retrieved = False
        all_retrieved_text = []

        for c in retrieved_chunks:
            c_id = ""
            c_file = ""
            c_code = ""
            if isinstance(c, Chunk):
                c_id = c.id
                c_file = c.file_path
                c_code = c.code
            elif isinstance(c, RetrievalResult):
                c_id = c.chunk.id
                c_file = c.chunk.file_path
                c_code = c.chunk.code
            elif isinstance(c, dict):
                c_id = c.get("id", "")
                c_file = c.get("file_path", "")
                c_code = c.get("code", "")

            all_retrieved_text.append(f"{c_file} {c_code}".lower())

            if (
                (test_case.ground_truth_chunk_id and test_case.ground_truth_chunk_id.lower() in c_id.lower())
                or (test_case.ground_truth_file and test_case.ground_truth_file.lower() in c_file.lower())
            ):
                target_retrieved = True

        combined_text = " ".join(all_retrieved_text)

        # Keyword recall
        kw_found = 0
        total_kws = len(test_case.ground_truth_keywords)
        if total_kws > 0:
            for kw in test_case.ground_truth_keywords:
                if kw.lower() in combined_text:
                    kw_found += 1
            kw_score = kw_found / float(total_kws)
        else:
            kw_score = 1.0

        # 50% target retrieved weight + 50% keyword coverage weight
        target_score = 1.0 if target_retrieved else 0.0
        return (0.5 * target_score) + (0.5 * kw_score)


class ContextPrecisionEvaluator:
    """
    Evaluates Context Precision: Measures the signal-to-noise ratio of relevant
    code chunks in the top-K retrieved context window.
    """

    @staticmethod
    def evaluate(test_case: BenchmarkTestCase, retrieved_chunks: Sequence[Chunk | RetrievalResult | dict]) -> float:
        if not retrieved_chunks:
            return 0.0

        relevant_count = 0
        total_chunks = len(retrieved_chunks)
        weighted_precision = 0.0

        for i, c in enumerate(retrieved_chunks, start=1):
            c_file = ""
            c_code = ""
            if isinstance(c, Chunk):
                c_file = c.file_path
                c_code = c.code
            elif isinstance(c, RetrievalResult):
                c_file = c.chunk.file_path
                c_code = c.chunk.code
            elif isinstance(c, dict):
                c_file = c.get("file_path", "")
                c_code = c.get("code", "")

            full_text = f"{c_file} {c_code}".lower()
            is_rel = (
                (test_case.ground_truth_file and test_case.ground_truth_file.lower() in c_file.lower())
                or any(kw.lower() in full_text for kw in test_case.ground_truth_keywords)
            )

            if is_rel:
                relevant_count += 1
                weighted_precision += relevant_count / float(i)

        if relevant_count == 0:
            return 0.0

        return weighted_precision / float(relevant_count)


class FaithfulnessEvaluator:
    """
    Evaluates Faithfulness (Groundedness): Checks whether statements in the generated
    LLM answer/explanation are strictly supported by facts in the retrieved context.
    """

    @staticmethod
    def evaluate(generated_answer: str, retrieved_chunks: Sequence[Chunk | RetrievalResult | dict]) -> float:
        if not generated_answer or not generated_answer.strip():
            return 1.0

        # Combine all retrieved context text
        context_parts = []
        for c in retrieved_chunks:
            if isinstance(c, Chunk):
                context_parts.append(f"{c.file_path} {c.code}")
            elif isinstance(c, RetrievalResult):
                context_parts.append(f"{c.chunk.file_path} {c.chunk.code}")
            elif isinstance(c, dict):
                context_parts.append(f"{c.get('file_path', '')} {c.get('code', '')}")

        context_str = " ".join(context_parts).lower()
        if not context_str.strip():
            return 0.0

        # Extract claims/sentences from generated answer
        sentences = [s.strip() for s in re.split(r"[.\n;]", generated_answer) if len(s.strip()) > 5]
        if not sentences:
            return 1.0

        supported_count = 0
        for stmt in sentences:
            # Extract key words (>3 chars) from statement
            words = [w.lower() for w in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b", stmt)]
            if not words:
                supported_count += 1
                continue

            # Statement is supported if at least 50% of its key terms exist in retrieved context
            found_words = sum(1 for w in words if w in context_str)
            if (found_words / float(len(words))) >= 0.5:
                supported_count += 1

        return supported_count / float(len(sentences))


class RetrievalMetricsEvaluator:
    """
    Evaluates Information Retrieval (IR) metrics: Reciprocal Rank (RR) and Hits@K.
    """

    @staticmethod
    def evaluate(test_case: BenchmarkTestCase, retrieved_chunks: Sequence[Chunk | RetrievalResult | dict]) -> dict[str, Any]:
        if not retrieved_chunks:
            return {"reciprocal_rank": 0.0, "hits_at_1": 0, "hits_at_3": 0, "hits_at_5": 0, "hits_at_10": 0, "retrieved_ids": []}

        rr = 0.0
        first_rel_rank = None
        retrieved_ids = []

        for rank, c in enumerate(retrieved_chunks, start=1):
            c_id = ""
            c_file = ""
            c_code = ""

            if isinstance(c, Chunk):
                c_id = c.id
                c_file = c.file_path
                c_code = c.code
            elif isinstance(c, RetrievalResult):
                c_id = c.chunk.id
                c_file = c.chunk.file_path
                c_code = c.chunk.code
            elif isinstance(c, dict):
                c_id = c.get("id", "")
                c_file = c.get("file_path", "")
                c_code = c.get("code", "")

            retrieved_ids.append(c_id or c_file)

            full_text = f"{c_id} {c_file} {c_code}".lower()
            is_relevant = (
                (test_case.ground_truth_chunk_id and test_case.ground_truth_chunk_id.lower() in c_id.lower())
                or (test_case.ground_truth_file and test_case.ground_truth_file.lower() in c_file.lower())
                or any(kw.lower() in full_text for kw in test_case.ground_truth_keywords)
            )

            if is_relevant and first_rel_rank is None:
                first_rel_rank = rank
                rr = 1.0 / float(rank)

        hits_1 = 1 if (first_rel_rank is not None and first_rel_rank <= 1) else 0
        hits_3 = 1 if (first_rel_rank is not None and first_rel_rank <= 3) else 0
        hits_5 = 1 if (first_rel_rank is not None and first_rel_rank <= 5) else 0
        hits_10 = 1 if (first_rel_rank is not None and first_rel_rank <= 10) else 0

        return {
            "reciprocal_rank": rr,
            "hits_at_1": hits_1,
            "hits_at_3": hits_3,
            "hits_at_5": hits_5,
            "hits_at_10": hits_10,
            "retrieved_ids": retrieved_ids,
        }


# ---------------------------------------------------------------------------
# Benchmark Dataset & Runner (RAGTriadEvalRunner)
# ---------------------------------------------------------------------------

GOLDEN_BENCHMARK_DATASET: list[BenchmarkTestCase] = [
    BenchmarkTestCase(
        id="BENCH-001",
        query="Where is the bare except clause handling exceptions silently in the bug detection agent?",
        ground_truth_file="src/agents/bug_detection.py",
        ground_truth_chunk_id="src/agents/bug_detection.py::find_bare_excepts::39",
        ground_truth_keywords=["find_bare_excepts", "except.block", "bare_except"],
        ground_truth_answer="The bare except clause detection is located in find_bare_excepts at line 39 in src/agents/bug_detection.py.",
    ),
    BenchmarkTestCase(
        id="BENCH-002",
        query="Find the SQL injection AST rule scanner in the security auditor agent.",
        ground_truth_file="src/agents/security_auditor.py",
        ground_truth_chunk_id="src/agents/security_auditor.py::SecurityASTScanner::140",
        ground_truth_keywords=["SecurityASTScanner", "execute", "executemany", "SQL Injection"],
        ground_truth_answer="The SQL injection rule scanning logic is in SecurityASTScanner inside src/agents/security_auditor.py.",
    ),
    BenchmarkTestCase(
        id="BENCH-003",
        query="Where is the docstring accuracy auditor and AST signature extractor defined?",
        ground_truth_file="src/agents/docstring_verifier.py",
        ground_truth_chunk_id="src/agents/docstring_verifier.py::DocstringAccuracyAuditor::180",
        ground_truth_keywords=["DocstringAccuracyAuditor", "ASTSignatureExtractor", "DocstringParser"],
        ground_truth_answer="DocstringAccuracyAuditor and ASTSignatureExtractor are defined in src/agents/docstring_verifier.py.",
    ),
    BenchmarkTestCase(
        id="BENCH-004",
        query="How is the self-executing unit test pytest sandbox runner implemented?",
        ground_truth_file="src/sandbox/runner.py",
        ground_truth_chunk_id="src/sandbox/runner.py::execute_tests_in_sandbox::15",
        ground_truth_keywords=["execute_tests_in_sandbox", "pytest", "subprocess"],
        ground_truth_answer="The pytest sandbox execution is in execute_tests_in_sandbox in src/sandbox/runner.py using subprocess.run.",
    ),
    BenchmarkTestCase(
        id="BENCH-005",
        query="Where is line number citation grounding and line verification checked?",
        ground_truth_file="src/agents/review_agent.py",
        ground_truth_chunk_id="src/agents/review_agent.py::verify_line_grounding::100",
        ground_truth_keywords=["verify_line_grounding", "extract_line_citations", "grounding"],
        ground_truth_answer="Line number citation verification is implemented in verify_line_grounding inside src/agents/review_agent.py.",
    ),
]


class RAGTriadEvalRunner:
    """
    Executes RAG Triad benchmarks across test cases, computes metrics,
    and exports JSON/CSV evaluation reports.
    """

    def __init__(self, test_cases: Sequence[BenchmarkTestCase] | None = None):
        self.test_cases = list(test_cases) if test_cases else GOLDEN_BENCHMARK_DATASET

    def run_eval(
        self,
        retriever_fn: Callable[[str], list[Chunk | RetrievalResult | dict]] | None = None,
        generator_fn: Callable[[str, list], str] | None = None,
    ) -> AggregateEvalReport:
        results: list[TestCaseEvalResult] = []

        for tc in self.test_cases:
            # 1. Retrieve context
            if retriever_fn:
                retrieved = retriever_fn(tc.query)
            else:
                retrieved = self._mock_retriever(tc)

            # 2. Generate answer
            if generator_fn:
                gen_answer = generator_fn(tc.query, retrieved)
            else:
                gen_answer = tc.ground_truth_answer

            # 3. Compute Metrics
            recall = ContextRecallEvaluator.evaluate(tc, retrieved)
            precision = ContextPrecisionEvaluator.evaluate(tc, retrieved)
            faithfulness = FaithfulnessEvaluator.evaluate(gen_answer, retrieved)
            ir_metrics = RetrievalMetricsEvaluator.evaluate(tc, retrieved)

            results.append(
                TestCaseEvalResult(
                    test_case_id=tc.id,
                    query=tc.query,
                    context_recall=recall,
                    context_precision=precision,
                    faithfulness=faithfulness,
                    reciprocal_rank=ir_metrics["reciprocal_rank"],
                    hits_at_1=ir_metrics["hits_at_1"],
                    hits_at_3=ir_metrics["hits_at_3"],
                    hits_at_5=ir_metrics["hits_at_5"],
                    hits_at_10=ir_metrics["hits_at_10"],
                    generated_answer=gen_answer,
                    retrieved_chunk_ids=ir_metrics["retrieved_ids"],
                )
            )

        # Compute Aggregates
        n = len(results) if results else 1
        mean_recall = sum(r.context_recall for r in results) / float(n)
        mean_precision = sum(r.context_precision for r in results) / float(n)
        mean_faith = sum(r.faithfulness for r in results) / float(n)
        mean_mrr = sum(r.reciprocal_rank for r in results) / float(n)

        h1_rate = sum(r.hits_at_1 for r in results) / float(n)
        h3_rate = sum(r.hits_at_3 for r in results) / float(n)
        h5_rate = sum(r.hits_at_5 for r in results) / float(n)
        h10_rate = sum(r.hits_at_10 for r in results) / float(n)

        report = AggregateEvalReport(
            timestamp=datetime.now().isoformat(),
            total_test_cases=len(results),
            mean_context_recall=mean_recall,
            mean_context_precision=mean_precision,
            mean_faithfulness=mean_faith,
            mean_mrr=mean_mrr,
            hits_at_1_rate=h1_rate,
            hits_at_3_rate=h3_rate,
            hits_at_5_rate=h5_rate,
            hits_at_10_rate=h10_rate,
            results=results,
        )

        return report

    def export_json(self, report: AggregateEvalReport, output_path: str = "eval_report.json") -> str:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        return output_path

    def export_csv(self, report: AggregateEvalReport, output_path: str = "eval_report.csv") -> str:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Test_Case_ID",
                "Query",
                "Context_Recall",
                "Context_Precision",
                "Faithfulness",
                "Reciprocal_Rank",
                "Hits@1",
                "Hits@3",
                "Hits@5",
                "Hits@10",
                "Retrieved_Chunks",
            ])
            for r in report.results:
                writer.writerow([
                    r.test_case_id,
                    r.query,
                    r.context_recall,
                    r.context_precision,
                    r.faithfulness,
                    r.reciprocal_rank,
                    r.hits_at_1,
                    r.hits_at_3,
                    r.hits_at_5,
                    r.hits_at_10,
                    ";".join(r.retrieved_chunk_ids),
                ])
        return output_path

    def _mock_retriever(self, test_case: BenchmarkTestCase) -> list[Chunk]:
        """Built-in deterministic retriever for offline benchmarking."""
        c1 = Chunk(
            id=test_case.ground_truth_chunk_id,
            file_path=test_case.ground_truth_file,
            start_line=1,
            end_line=25,
            type="function",
            name=test_case.id,
            code=f"# Code chunk for {test_case.ground_truth_file}\n" + " ".join(test_case.ground_truth_keywords),
        )
        c2 = Chunk(
            id="src/utils/helpers.py::helper::1",
            file_path="src/utils/helpers.py",
            start_line=1,
            end_line=10,
            type="function",
            name="helper",
            code="def helper(): pass",
        )
        return [c1, c2]


if __name__ == "__main__":
    runner = RAGTriadEvalRunner()
    report = runner.run_eval()

    json_path = runner.export_json(report, "eval_report.json")
    csv_path = runner.export_csv(report, "eval_report.csv")

    print(report.to_markdown())
    print(f"Exported benchmark JSON report to {json_path}")
    print(f"Exported benchmark CSV report to {csv_path}")
