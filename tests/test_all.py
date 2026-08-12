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
from src.agents.review_agent import (
    review_bug_detection_output,
    extract_line_citations,
    verify_line_grounding,
    extract_code_blocks,
    validate_code_syntax,
    verify_syntax_and_lint,
)
from src.agents.test_generation import get_function_chunks, analyze_and_generate
from src.sandbox.runner import execute_tests_in_sandbox
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

    def test_extract_line_citations(self):
        text = "WHICH LINE(S): 4-5 and line 99 and L10-12"
        citations = extract_line_citations(text)
        self.assertIn((4, 5), citations)
        self.assertIn((99, 99), citations)
        self.assertIn((10, 12), citations)

    def test_verify_line_grounding_valid(self):
        sample_code = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(sample_code)
            f.flush()
            res = verify_line_grounding(f.name, "WHICH LINE(S): 2-4")

        self.assertTrue(res["valid"])
        self.assertEqual(res["total_lines"], 5)
        self.assertEqual(len(res["errors"]), 0)

    def test_verify_line_grounding_hallucinated(self):
        sample_code = "def foo():\n    pass\n"  # 2 lines total
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(sample_code)
            f.flush()
            res = verify_line_grounding(f.name, "The bug is on line 99.")

        self.assertFalse(res["valid"])
        self.assertTrue(any("Hallucinated line number" in err for err in res["errors"]))

    def test_verify_line_grounding_code_mismatch(self):
        sample_code = "def hello():\n    print('world')\n"  # line 2 has print('world')
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(sample_code)
            f.flush()
            # Citing line 1 for snippet 'print('world')' which is actually on line 2
            res = verify_line_grounding(f.name, "Issue on line 1: `print('world')`")

        self.assertFalse(res["valid"])
        self.assertTrue(any("Code grounding mismatch" in err for err in res["errors"]))

    def test_review_rejected_hallucinated_lines(self):
        sample_code = "try:\n    pass\nexcept:\n    pass\n"  # 4 lines total
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(sample_code)
            f.flush()

            mock_response = {
                "summary": "Issue 1: foo\nWHY it matters: bad\nWHICH LINE(S): 99\nPOSSIBLE FIX: fix it",
                "details": {
                    "raw_findings": "ISSUE 1:\n  type: bare_except\n  location: foo\n  lines: 99\n",
                    "filepath": f.name
                },
            }
            res = review_bug_detection_output(mock_response, filepath=f.name)
            self.assertFalse(res["approved"])
            self.assertTrue(any("Hallucinated line number" in issue for issue in res["issues"]))

    def test_validate_code_syntax_valid(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        res = validate_code_syntax(code, "python")
        self.assertTrue(res["valid"])
        self.assertIsNone(res["error"])

    def test_validate_code_syntax_invalid(self):
        invalid_code = "def broken_func(:\n    pass"
        res = validate_code_syntax(invalid_code, "python")
        self.assertFalse(res["valid"])
        self.assertIsNotNone(res["error"])
        self.assertIn("SyntaxError", res["error"])

    def test_extract_code_blocks(self):
        text = (
            "Here is the fix:\n"
            "```python\n"
            "try:\n"
            "    x = 1 / 0\n"
            "except ZeroDivisionError:\n"
            "    pass\n"
            "```\n"
        )
        blocks = extract_code_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["language"], "python")
        self.assertIn("ZeroDivisionError", blocks[0]["code"])

    def test_review_rejected_syntax_error(self):
        mock_response = {
            "summary": (
                "Issue 1: foo\n"
                "WHY it matters: invalid syntax\n"
                "WHICH LINE(S): 1-2\n"
                "POSSIBLE FIX: Use this code:\n"
                "```python\n"
                "def bad_syntax(a, b:\n"
                "    return a + b\n"
                "```\n"
            ),
            "details": {"raw_findings": "ISSUE 1:\n  type: syntax_error\n  location: foo\n  lines: 1-2\n"},
        }
        res = review_bug_detection_output(mock_response)
        self.assertFalse(res["approved"])
        self.assertTrue(any("Syntax error in code fix" in issue for issue in res["issues"]))


class TestTestGeneration(unittest.TestCase):
    def test_get_function_chunks(self):
        code = "def add(a, b):\n    return a + b\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            f.flush()
            funcs = get_function_chunks(f.name)

        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0].name, "add")

    def test_sandbox_passing_tests(self):
        source_code = "def add(a, b):\n    return a + b\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(source_code)
            f.flush()
            test_code = "def test_add():\n    assert add(2, 3) == 5\n"
            res = execute_tests_in_sandbox(f.name, test_code)

        self.assertEqual(res["status"], "PASSED")
        self.assertEqual(res["exit_code"], 0)
        self.assertGreaterEqual(res["passed_count"], 1)

    def test_sandbox_failing_tests(self):
        source_code = "def multiply(a, b):\n    return a * b\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(source_code)
            f.flush()
            test_code = "def test_multiply():\n    assert multiply(2, 3) == 999\n"
            res = execute_tests_in_sandbox(f.name, test_code)

        self.assertEqual(res["status"], "FAILED")
        self.assertNotEqual(res["exit_code"], 0)
        self.assertIsNotNone(res["error_traceback"])

    @patch("src.agents.test_generation.refine_failing_tests")
    @patch("src.agents.test_generation.generate_tests_for_function")
    def test_sandbox_self_correction_loop(self, mock_gen, mock_refine):
        # First attempt generates failing test, refinement generates passing test
        mock_gen.return_value = "def test_add():\n    assert add(1, 1) == 99\n"
        mock_refine.return_value = "def test_add():\n    assert add(1, 1) == 2\n"

        source_code = "def add(a, b):\n    return a + b\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(source_code)
            f.flush()

            res = analyze_and_generate(f.name, max_attempts=3)

        self.assertEqual(res["confidence"], 1.0)
        self.assertIn("Verified pytest suite", res["summary"])
        mock_refine.assert_called_once()


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


from src.agents.security_auditor import audit_file, audit_code_string, SecurityASTScanner


class TestSecurityAuditor(unittest.TestCase):
    def test_security_ast_scanner_rules(self):
        vuln_code = (
            "import os, pickle, hashlib\n"
            'API_KEY = "sk_live_1234567890abcdef"\n'
            "def handle(user_id, data):\n"
            "    h = hashlib.md5(b'test').hexdigest()\n"
            "    cursor.execute(f'SELECT * FROM users WHERE id = {user_id}')\n"
            "    obj = pickle.loads(data)\n"
            "    os.system('echo ' + user_id)\n"
        )
        scanner = SecurityASTScanner(vuln_code, filename="test_vuln.py")
        vulns = scanner.scan()
        self.assertGreaterEqual(len(vulns), 4)

    def test_audit_file(self):
        clean_code = "def greet(name: str) -> str:\n    return f'Hello, {name}'\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(clean_code)
            f.flush()
            res = audit_file(f.name)

        self.assertEqual(res["agent_name"], "security_auditor")
        scorecard = res["details"]["scorecard"]
        self.assertEqual(scorecard["status"], "PASS")
        self.assertEqual(scorecard["score"], 100)


from src.agents.docstring_verifier import verify_function_docstring, audit_and_fix_docstring


class TestDocstringVerifier(unittest.TestCase):
    def test_verify_function_docstring_hallucination(self):
        code = (
            "def add(a: int, b: int) -> int:\n"
            '    """Adds two numbers.\n\n'
            "    Args:\n"
            "        a (int): First.\n"
            "        c (float): Hallucinated.\n"
            '    """\n'
            "    return a + b\n"
        )
        res = verify_function_docstring(code)
        rep = res["details"]["report"]
        self.assertEqual(rep["status"], "FAIL")

    def test_audit_and_fix_docstring(self):
        code = "def sub(x: int, y: int = 1) -> int:\n    pass\n"
        res = audit_and_fix_docstring(code)
        self.assertIn("corrected_docstring", res["details"])


from src.eval.eval_runner import RAGTriadEvalRunner


class TestEvalRunner(unittest.TestCase):
    def test_rag_triad_runner_benchmark(self):
        runner = RAGTriadEvalRunner()
        report = runner.run_eval()
        self.assertGreater(report.total_test_cases, 0)
        self.assertGreaterEqual(report.mean_context_recall, 0.0)


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
        self.assertIn("security_response", res)


if __name__ == "__main__":
    unittest.main()



