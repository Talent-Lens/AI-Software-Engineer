"""
Unit tests for Docstring Accuracy Verifier Agent (TASK-E5).
"""

from __future__ import annotations

import tempfile
import unittest

from src.agents.docstring_verifier import (
    ASTSignatureExtractor,
    DocstringAccuracyAuditor,
    DocstringParser,
    DocstringRefiner,
    audit_and_fix_docstring,
    verify_file_docstrings,
    verify_function_docstring,
)


class TestASTSignatureExtractor(unittest.TestCase):
    def test_extract_signature_basic(self):
        code = (
            "def calculate_total(price: float, qty: int = 1, tax_rate: float = 0.05) -> float:\n"
            '    """Calculates total cost including tax."""\n'
            "    return (price * qty) * (1 + tax_rate)\n"
        )
        sig = ASTSignatureExtractor.extract_from_code(code)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.name, "calculate_total")
        self.assertEqual(sig.return_type, "float")
        self.assertEqual(len(sig.params), 3)

        p_names = [p.name for p in sig.params]
        self.assertEqual(p_names, ["price", "qty", "tax_rate"])

        self.assertEqual(sig.params[1].default_value, "1")
        self.assertEqual(sig.params[2].default_value, "0.05")

    def test_extract_signature_varargs_kwargs(self):
        code = (
            "def process_data(target: str, *args: int, timeout: int = 30, **kwargs: str) -> bool:\n"
            "    pass\n"
        )
        sig = ASTSignatureExtractor.extract_from_code(code)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.params[1].name, "*args")
        self.assertTrue(sig.params[1].is_args)
        self.assertEqual(sig.params[3].name, "**kwargs")
        self.assertTrue(sig.params[3].is_kwargs)


class TestDocstringParser(unittest.TestCase):
    def test_parse_google_docstring(self):
        doc = (
            "Processes user input.\n\n"
            "Args:\n"
            "    user_id (int): ID of the user.\n"
            "    name (str): Name of the user. Defaults to 'Anonymous'.\n\n"
            "Returns:\n"
            "    dict: User details response.\n"
        )
        parsed = DocstringParser.parse(doc)
        self.assertEqual(parsed.summary, "Processes user input.")
        self.assertIn("user_id", parsed.params)
        self.assertEqual(parsed.params["user_id"].type_desc, "int")
        self.assertEqual(parsed.params["name"].type_desc, "str")
        self.assertEqual(parsed.returns_type, "dict")

    def test_parse_sphinx_docstring(self):
        doc = (
            "Fetches item by ID.\n"
            ":param item_id: Target item ID\n"
            ":type item_id: int\n"
            ":returns: Item object\n"
            ":rtype: dict\n"
        )
        parsed = DocstringParser.parse(doc)
        self.assertIn("item_id", parsed.params)
        self.assertEqual(parsed.params["item_id"].type_desc, "int")
        self.assertEqual(parsed.returns_type, "dict")


class TestDocstringAccuracyAuditor(unittest.TestCase):
    def test_detect_hallucinated_param(self):
        code = (
            "def greet(name: str) -> str:\n"
            '    """\n'
            "    Greets a person.\n\n"
            "    Args:\n"
            "        name (str): The name.\n"
            "        age (int): The age of person.\n"
            '    """\n'
            "    return f'Hello {name}'\n"
        )
        sig = ASTSignatureExtractor.extract_from_code(code)
        parsed_doc = DocstringParser.parse(sig.docstring)
        report = DocstringAccuracyAuditor.audit(sig, parsed_doc)

        self.assertEqual(report.status, "FAIL")
        hallucinations = [d for d in report.discrepancies if d.discrepancy_type == "HALLUCINATED_PARAM"]
        self.assertEqual(len(hallucinations), 1)
        self.assertEqual(hallucinations[0].param_name, "age")

    def test_detect_missing_param(self):
        code = (
            "def compute(a: int, b: int) -> int:\n"
            '    """\n'
            "    Computes sum.\n\n"
            "    Args:\n"
            "        a (int): First value.\n"
            '    """\n'
            "    return a + b\n"
        )
        sig = ASTSignatureExtractor.extract_from_code(code)
        parsed_doc = DocstringParser.parse(sig.docstring)
        report = DocstringAccuracyAuditor.audit(sig, parsed_doc)

        missing = [d for d in report.discrepancies if d.discrepancy_type == "MISSING_PARAM"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].param_name, "b")

    def test_detect_type_mismatch(self):
        code = (
            "def parse_count(raw: int) -> int:\n"
            '    """\n'
            "    Parses raw count.\n\n"
            "    Args:\n"
            "        raw (str): Raw string count.\n"
            '    """\n'
            "    return raw\n"
        )
        sig = ASTSignatureExtractor.extract_from_code(code)
        parsed_doc = DocstringParser.parse(sig.docstring)
        report = DocstringAccuracyAuditor.audit(sig, parsed_doc)

        type_mismatches = [d for d in report.discrepancies if d.discrepancy_type == "TYPE_MISMATCH"]
        self.assertEqual(len(type_mismatches), 1)
        self.assertEqual(type_mismatches[0].param_name, "raw")
        self.assertEqual(type_mismatches[0].expected, "int")
        self.assertEqual(type_mismatches[0].actual, "str")

    def test_detect_default_value_mismatch(self):
        code = (
            "def fetch(limit: int = 10) -> list:\n"
            '    """\n'
            "    Fetches items.\n\n"
            "    Args:\n"
            "        limit (int): Max items. Defaults to 50.\n"
            '    """\n'
            "    return []\n"
        )
        sig = ASTSignatureExtractor.extract_from_code(code)
        parsed_doc = DocstringParser.parse(sig.docstring)
        report = DocstringAccuracyAuditor.audit(sig, parsed_doc)

        def_mismatches = [d for d in report.discrepancies if d.discrepancy_type == "DEFAULT_VALUE_MISMATCH"]
        self.assertEqual(len(def_mismatches), 1)
        self.assertEqual(def_mismatches[0].expected, "10")
        self.assertEqual(def_mismatches[0].actual, "50")

    def test_detect_return_type_mismatch(self):
        code = (
            "def is_valid(code: str) -> bool:\n"
            '    """\n'
            "    Validates code.\n\n"
            "    Returns:\n"
            "        dict: Result details dictionary.\n"
            '    """\n'
            "    return True\n"
        )
        sig = ASTSignatureExtractor.extract_from_code(code)
        parsed_doc = DocstringParser.parse(sig.docstring)
        report = DocstringAccuracyAuditor.audit(sig, parsed_doc)

        ret_mismatches = [d for d in report.discrepancies if d.discrepancy_type == "RETURN_TYPE_MISMATCH"]
        self.assertEqual(len(ret_mismatches), 1)
        self.assertEqual(ret_mismatches[0].expected, "bool")
        self.assertEqual(ret_mismatches[0].actual, "dict")


class TestDocstringRefinerAndPublicAPI(unittest.TestCase):
    def test_docstring_refiner_generation(self):
        code = "def create_user(user_id: int, role: str = 'member') -> dict:\n    pass\n"
        sig = ASTSignatureExtractor.extract_from_code(code)
        gt_doc = DocstringRefiner.generate_ground_truth_docstring(sig)

        self.assertIn("create_user", gt_doc)
        self.assertIn("user_id (int)", gt_doc)
        self.assertIn("role (str)", gt_doc)
        self.assertIn("Defaults to 'member'", gt_doc)
        self.assertIn("dict", gt_doc)

    def test_audit_and_fix_docstring(self):
        hallucinated_code = (
            "def multiply(a: int, b: int = 2) -> int:\n"
            '    """\n'
            "    Multiplies numbers.\n\n"
            "    Args:\n"
            "        a (int): First num.\n"
            "        fake_arg (float): Non-existent arg.\n"
            '    """\n'
            "    return a * b\n"
        )
        res = audit_and_fix_docstring(hallucinated_code)
        rep = res["details"]["report"]
        self.assertEqual(rep["status"], "FAIL")

        corrected = res["details"].get("corrected_docstring")
        self.assertIsNotNone(corrected)
        self.assertIn("a (int)", corrected)
        self.assertIn("b (int)", corrected)
        self.assertNotIn("fake_arg", corrected)

    def test_verify_file_docstrings(self):
        code = (
            "def func1(x: int) -> int:\n"
            '    """\n'
            "    Func 1.\n\n"
            "    Args:\n"
            "        x (int): Value.\n"
            '    """\n'
            "    return x\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            f.flush()
            res = verify_file_docstrings(f.name)

        self.assertEqual(res["agent_name"], "docstring_verifier")
        self.assertEqual(res["details"]["overall_status"], "PASS")
        self.assertEqual(res["details"]["average_score"], 100)


if __name__ == "__main__":
    unittest.main()
