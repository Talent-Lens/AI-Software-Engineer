"""
Unit Test Suite for AI Software Engineer Platform
Verifies schema, AST chunker, bug detection, review agent, test generation, RAG prompt building, and LangGraph pipeline.
"""

import tempfile
import unittest
from unittest.mock import patch

from src.schema import Chunk, RetrievalResult, AgentResponse
from src.indexing.chunker import chunk_file
from src.agents.bug_detection import find_bare_excepts, analyze_and_explain, run_bug_scan
from src.agents.review_agent import review_bug_detection_output
from src.agents.test_generation import get_function_chunks, analyze_and_generate
from src.retrieval.rag import build_prompt, retrieve_context
from graph import run_pipeline


class TestSchema(unittest.TestCase):
    def test_chunk_creation(self):
        c = Chunk(
            id="test::1",
            file_path="test.py",
            start_line=1,
            end_line=5,
            type="function",
            name="foo",
            code="def foo(): pass",
        )
        self.assertEqual(c.name, "foo")
        self.assertEqual(c.type, "function")

    def test_agent_response(self):
        resp = AgentResponse(
            agent_name="bug_detection",
            summary="All clean",
            details={},
            confidence=0.95,
        )
        self.assertEqual(resp.agent_name, "bug_detection")
        self.assertEqual(resp.confidence, 0.95)


class TestASTChunker(unittest.TestCase):
    def test_chunk_file(self):
        sample_code = (
            "class MyClass:\n"
            "    def my_method(self):\n"
            "        pass\n\n"
            "def top_function():\n"
            "    pass\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(sample_code)
            f.flush()
            chunks = chunk_file(f.name)

        types = [c.type for c in chunks]
        names = [c.name for c in chunks]

        self.assertIn("class", types)
        self.assertIn("method", types)
        self.assertIn("function", types)
        self.assertIn("MyClass", names)
        self.assertIn("my_method", names)
        self.assertIn("top_function", names)


class TestBugDetection(unittest.TestCase):
    def test_find_bare_excepts(self):
        buggy_code = (
            "def calculate():\n"
            "    try:\n"
            "        x = 1 / 0\n"
            "    except:\n"
            "        pass\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(buggy_code)
            f.flush()
            issues = find_bare_excepts(f.name)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "bare_except")
        self.assertEqual(issues[0]["start_line"], 4)

    def test_run_bug_scan(self):
        buggy_code = "try:\n    pass\nexcept:\n    pass\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(buggy_code)
            f.flush()
            output = run_bug_scan(f.name)

        self.assertIn("Found 1 issue", output)
        self.assertIn("bare_except", output)


class TestReviewAgent(unittest.TestCase):
    def test_review_approved(self):
        mock_response = {
            "summary": "Issue 1: foo[bare_except]\nWHY it matters: bad\nWHICH LINE(S): 4-5\nPOSSIBLE FIX: specify Exception",
            "details": {"raw_findings": "ISSUE 1:\n  type: bare_except\n  location: foo\n  lines: 4-5\n"},
        }
        res = review_bug_detection_output(mock_response)
        self.assertTrue(res["approved"])
        self.assertEqual(len(res["issues"]), 0)

    def test_review_rejected_clean_claim(self):
        mock_response = {
            "summary": "The file is clean.",
            "details": {"raw_findings": "ISSUE 1:\n  type: bare_except\n  location: foo\n  lines: 4-5\n"},
        }
        res = review_bug_detection_output(mock_response)
        self.assertFalse(res["approved"])
        self.assertIn("Summary claims file is clean", res["issues"][0])


class TestTestGeneration(unittest.TestCase):
    def test_get_function_chunks(self):
        code = "def add(a, b):\n    return a + b\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            f.flush()
            funcs = get_function_chunks(f.name)

        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0].name, "add")


class TestRAG(unittest.TestCase):
    def test_build_prompt(self):
        chunk = Chunk(
            id="test::1",
            file_path="main.py",
            start_line=1,
            end_line=3,
            type="function",
            name="main",
            code="def main(): pass",
        )
        res = RetrievalResult(chunk=chunk, score=0.1, query="main")
        prompt = build_prompt("What does main do?", [res])

        self.assertIn("File: main.py", prompt)
        self.assertIn("def main(): pass", prompt)
        self.assertIn("What does main do?", prompt)


class TestGraphPipeline(unittest.TestCase):
    @patch("src.agents.bug_detection.ollama.chat")
    def test_run_pipeline(self, mock_chat):
        mock_chat.return_value = {
            "message": {
                "content": "No real issues found.",
                "tool_calls": []
            }
        }
        code = "def ok(): pass\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            f.flush()
            res = run_pipeline(f.name)

        self.assertIn("agent_response", res)
        self.assertIn("review", res)


if __name__ == "__main__":
    unittest.main()
