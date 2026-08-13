"""
Unit tests for SAST Security & Vulnerability Auditor Agent (TASK-E4).
"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.agents.security_auditor import (
    GroqSecurityAuditor,
    SecurityASTScanner,
    SecurityScorecard,
    Vulnerability,
    audit_code_string,
    audit_file,
    audit_retrieved_chunks,
    calculate_security_scorecard,
)
from src.schema import Chunk, RetrievalResult


class TestSecurityASTScanner(unittest.TestCase):
    def test_hardcoded_secrets(self):
        code = (
            'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
            'API_SECRET = "sk_live_1234567890abcdef"\n'
            'api_key = "super_secret_key_1234"\n'
        )
        scanner = SecurityASTScanner(code, filename="secrets_test.py")
        vulns = scanner.scan()

        self.assertTrue(any("AWS" in v.title for v in vulns))
        self.assertTrue(any("api_key" in v.code_snippet for v in vulns))

    def test_sql_injection(self):
        code = (
            "def get_user(user_id):\n"
            '    query = f"SELECT * FROM users WHERE id = {user_id}"\n'
            "    cursor.execute(query)\n"
            "    cursor.execute('SELECT * FROM accounts WHERE name = %s' % (name,))\n"
            "    cursor.execute('SELECT * FROM logs WHERE id = {}'.format(log_id))\n"
        )
        scanner = SecurityASTScanner(code, filename="sqli_test.py")
        vulns = scanner.scan()

        sqli_vulns = [v for v in vulns if "A03" in v.owasp_category]
        self.assertGreaterEqual(len(sqli_vulns), 2)
        self.assertTrue(any(v.severity == "Critical" for v in sqli_vulns))

    def test_command_injection(self):
        code = (
            "import os, subprocess\n"
            "def run_cmd(user_input):\n"
            "    eval(user_input)\n"
            "    exec(user_input)\n"
            "    os.system('rm ' + user_input)\n"
            "    subprocess.Popen(user_input, shell=True)\n"
        )
        scanner = SecurityASTScanner(code, filename="cmd_test.py")
        vulns = scanner.scan()

        titles = [v.title for v in vulns]
        self.assertTrue(any("eval()" in t for t in titles))
        self.assertTrue(any("os.system()" in t for t in titles))
        self.assertTrue(any("shell=True" in t for t in titles))

    def test_unsafe_deserialization(self):
        code = (
            "import pickle, yaml\n"
            "def load_data(payload):\n"
            "    obj = pickle.loads(payload)\n"
            "    cfg = yaml.unsafe_load(payload)\n"
        )
        scanner = SecurityASTScanner(code, filename="pickle_test.py")
        vulns = scanner.scan()

        deserial_vulns = [v for v in vulns if "A06" in v.owasp_category]
        self.assertEqual(len(deserial_vulns), 2)

    def test_weak_crypto_and_insecure_prng(self):
        code = (
            "import hashlib, random\n"
            "def generate_token():\n"
            "    h = hashlib.md5(b'test').hexdigest()\n"
            "    token = str(random.randint(1000, 9999))\n"
            "    return h, token\n"
        )
        scanner = SecurityASTScanner(code, filename="crypto_test.py")
        vulns = scanner.scan()

        self.assertTrue(any("md5" in v.title for v in vulns))
        self.assertTrue(any("Pseudo-Random" in v.title for v in vulns))

    def test_security_misconfig(self):
        code = (
            "import requests\n"
            "DEBUG = True\n"
            "def fetch(url):\n"
            "    return requests.get(url, verify=False)\n"
        )
        scanner = SecurityASTScanner(code, filename="misconfig_test.py")
        vulns = scanner.scan()

        self.assertTrue(any("Debug Mode" in v.title for v in vulns))
        self.assertTrue(any("verify=False" in v.title for v in vulns))


class TestGroqLLMAuditor(unittest.TestCase):
    @patch("requests.post")
    def test_groq_api_call(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"vulnerabilities": [{"owasp_code": "A03", "title": "LLM Found SQLi", "severity": "High", "line_number": 3, "code_snippet": "query = ...", "description": "SQL injection vulnerability", "remediation": "Use params"}]}'
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        auditor = GroqSecurityAuditor(groq_api_key="gsk_test12345")
        vulns = auditor.audit_code("query = 'SELECT * FROM users'", filename="test.py")

        self.assertEqual(len(vulns), 1)
        self.assertEqual(vulns[0].title, "LLM Found SQLi")
        self.assertEqual(vulns[0].source, "Groq-LLM")

    @patch("src.agents.security_auditor.GroqSecurityAuditor._call_ollama_api", return_value=None)
    def test_fallback_without_key(self, mock_ollama):
        auditor = GroqSecurityAuditor(groq_api_key=None)
        # Should cleanly return empty list or fallback without crashing
        vulns = auditor.audit_code("print('hello')", filename="test.py")
        self.assertIsInstance(vulns, list)


class TestSecurityScorecard(unittest.TestCase):
    def test_scorecard_calculation_pass(self):
        ast_vulns = []
        llm_vulns = []
        scorecard = calculate_security_scorecard(ast_vulns, llm_vulns, filepath="clean.py")

        self.assertEqual(scorecard.status, "PASS")
        self.assertEqual(scorecard.score, 100)
        self.assertEqual(scorecard.metrics["total_vulnerabilities"], 0)

    def test_scorecard_calculation_fail(self):
        ast_vulns = [
            Vulnerability(
                id="SAST-001",
                owasp_category="A03:2021-Injection",
                title="SQL Injection",
                severity="Critical",
                line_number=5,
                code_snippet="cursor.execute(f'SELECT {x}')",
                description="SQLi via f-string",
                remediation="Use params",
                source="AST",
            )
        ]
        llm_vulns = []
        scorecard = calculate_security_scorecard(ast_vulns, llm_vulns, filepath="vulnerable.py")

        self.assertEqual(scorecard.status, "FAIL")
        self.assertEqual(scorecard.score, 75)
        self.assertEqual(scorecard.metrics["critical_count"], 1)

    def test_to_markdown(self):
        scorecard = SecurityScorecard(
            status="PASS",
            score=100,
            summary="Clean file",
            vulnerabilities=[],
            metrics={"critical_count": 0, "high_count": 0, "medium_count": 0, "low_count": 0},
            owasp_breakdown={},
        )
        md = scorecard.to_markdown()
        self.assertIn("SAST Security Scorecard", md)
        self.assertIn("100/100", md)
        self.assertIn("PASS", md)


@patch("src.agents.security_auditor.GroqSecurityAuditor._call_ollama_api", return_value=None)
class TestAuditPublicAPI(unittest.TestCase):
    def test_audit_clean_file(self, mock_ollama):
        clean_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(clean_code)
            f.flush()
            res = audit_file(f.name)

        self.assertEqual(res["agent_name"], "security_auditor")
        scorecard = res["details"]["scorecard"]
        self.assertEqual(scorecard["status"], "PASS")
        self.assertEqual(scorecard["score"], 100)

    def test_audit_vulnerable_file(self, mock_ollama):
        vuln_code = (
            "import os, pickle\n"
            'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
            "def run(data, user_input):\n"
            "    obj = pickle.loads(data)\n"
            "    os.system('echo ' + user_input)\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(vuln_code)
            f.flush()
            res = audit_file(f.name)

        self.assertEqual(res["agent_name"], "security_auditor")
        scorecard = res["details"]["scorecard"]
        self.assertEqual(scorecard["status"], "FAIL")
        self.assertLess(scorecard["score"], 70)

    def test_audit_retrieved_chunks(self, mock_ollama):
        c1 = Chunk(
            id="c1",
            file_path="app.py",
            start_line=10,
            end_line=15,
            type="function",
            name="unsafe_exec",
            code="def unsafe_exec(cmd):\n    eval(cmd)\n",
        )
        res = audit_retrieved_chunks([c1])
        scorecard = res["details"]["scorecard"]
        self.assertEqual(scorecard["status"], "FAIL")
        self.assertTrue(len(scorecard["vulnerabilities"]) > 0)


if __name__ == "__main__":
    unittest.main()

