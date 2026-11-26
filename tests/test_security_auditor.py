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

    def test_intra_function_taint_tracking(self):
        code = (
            "def handle():\n"
            "    raw_cmd = request.args.get('cmd')\n"
            "    step1 = raw_cmd\n"
            "    final_cmd = f'exec {step1}'\n"
            "    os.system(final_cmd)\n"
            "    user_path = input('Path: ')\n"
            "    f = open(user_path)\n"
            "    query = 'SELECT * FROM users WHERE name = %s' % os.environ['USER']\n"
            "    cursor.execute(query)\n"
        )
        scanner = SecurityASTScanner(code, filename="taint_test.py")
        vulns = scanner.scan()

        taint_vulns = [v for v in vulns if "Untrusted data from" in v.description]
        self.assertEqual(len(taint_vulns), 3)

        # Verify command injection finding with chain and source/sink lines
        cmd_v = [v for v in taint_vulns if "os.system" in v.title][0]
        self.assertEqual(cmd_v.line_number, 5)
        self.assertIn("line 2", cmd_v.description)
        self.assertIn("line 5", cmd_v.description)
        self.assertIn("request.args.get() -> raw_cmd -> step1 -> final_cmd -> os.system", cmd_v.description)

        # Verify open() path traversal finding
        open_v = [v for v in taint_vulns if "open()" in v.title][0]
        self.assertEqual(open_v.line_number, 7)
        self.assertIn("input() -> user_path -> open", open_v.description)

        # Verify SQL injection via os.environ % formatting
        sql_v = [v for v in taint_vulns if "cursor.execute" in cmd_v.description or "SQL Injection" in v.title][0]
        self.assertEqual(sql_v.line_number, 9)
        self.assertIn("os.environ[] -> query -> cursor.execute", sql_v.description)

    def test_sanitizers_clear_taint(self):
        code = (
            "import os, shlex\n"
            "def handle_safe():\n"
            "    user_input = request.args.get('id')\n"
            "    clean_id = int(user_input)\n"
            "    query = f'SELECT * FROM tbl WHERE id = {clean_id}'\n"
            "    cursor.execute(query)\n"
            "    raw_file = request.form['file']\n"
            "    safe_file = os.path.basename(raw_file)\n"
            "    f = open(safe_file)\n"
            "    cmd = shlex.quote(request.json.get('cmd'))\n"
            "    os.system(f'echo {cmd}')\n"
            "    # Parameterized query safety\n"
            "    param = request.args.get('param')\n"
            "    cursor.execute('SELECT * FROM tbl WHERE p = %s', (param,))\n"
        )
        scanner = SecurityASTScanner(code, filename="safe_test.py")
        vulns = scanner.scan()

        taint_vulns = [v for v in vulns if "Untrusted data from" in v.description]
        self.assertEqual(len(taint_vulns), 0)

    def test_import_resolution_symbol_table(self):
        code = (
            "from pickle import loads\n"
            "import pickle as pk\n"
            "from subprocess import call\n"
            "import subprocess as sp\n"
            "from os import system as sys_exec\n"
            "from shlex import quote as q\n"
            "from sys import argv as cli_args\n"
            "\n"
            "def run_all(payload, user_cmd):\n"
            "    obj1 = loads(payload)\n"
            "    obj2 = pk.loads(payload)\n"
            "    call(user_cmd, shell=True)\n"
            "    sp.call(user_cmd, shell=True)\n"
            "    arg = cli_args[1]\n"
            "    sys_exec(arg)\n"
            "    sys_exec(q(arg))\n"
        )
        scanner = SecurityASTScanner(code, filename="imports_test.py")
        vulns = scanner.scan()

        # Check loads and pk.loads both resolve to pickle deserialization
        pickle_vulns = [v for v in vulns if "pickle" in v.title.lower()]
        self.assertEqual(len(pickle_vulns), 2)

        # Check call and sp.call both resolve to subprocess shell=True
        shell_vulns = [v for v in vulns if "shell=True" in v.title]
        self.assertEqual(len(shell_vulns), 2)

        # Check aliased source (cli_args[1]) flows to aliased sink (sys_exec)
        taint_vulns = [v for v in vulns if "Untrusted data from" in v.description]
        self.assertEqual(len(taint_vulns), 1)
        self.assertIn("sys.argv", taint_vulns[0].description)
        self.assertIn("os.system", taint_vulns[0].description)

    def test_wildcard_import_resolution(self):
        code = (
            "from pickle import *\n"
            "def load_wildcard(data):\n"
            "    return loads(data)\n"
        )
        scanner = SecurityASTScanner(code, filename="wildcard_test.py")
        vulns = scanner.scan()

        pickle_vulns = [v for v in vulns if "pickle" in v.title.lower()]
        self.assertEqual(len(pickle_vulns), 1)

    def test_cross_file_taint_graph_rag(self):
        from src.retrieval.graph_rag import CodebaseGraph

        code_util = (
            "import os\n"
            "def execute_cmd(command):\n"
            "    os.system(command)\n"
        )
        code_app = (
            "from utils import execute_cmd\n"
            "def handle_web():\n"
            "    val = request.args.get('cmd')\n"
            "    execute_cmd(val)\n"
        )

        c_util = Chunk(
            id="c_util",
            name="execute_cmd",
            type="function",
            file_path="utils.py",
            start_line=1,
            end_line=4,
            code=code_util,
            imports=["import os"],
        )
        c_app = Chunk(
            id="c_app",
            name="handle_web",
            type="function",
            file_path="app.py",
            start_line=1,
            end_line=5,
            code=code_app,
            imports=["from utils import execute_cmd"],
        )

        graph = CodebaseGraph()
        graph.build_from_chunks([c_util, c_app])

        scanner = SecurityASTScanner(code_app, filename="app.py", codebase_graph=graph)
        vulns = scanner.scan()

        cross_vulns = [v for v in vulns if "cross-file" in v.description]
        self.assertEqual(len(cross_vulns), 1)
        self.assertIn("execute_cmd", cross_vulns[0].description)
        self.assertIn("os.system", cross_vulns[0].description)
        self.assertIn("request.args.get() -> val -> execute_cmd(command) -> os.system", cross_vulns[0].description)

    def test_cycle_handling_and_depth_limit(self):
        from src.retrieval.graph_rag import CodebaseGraph

        code_a = "def fn_a(x):\n    return fn_b(x)\n"
        code_b = "def fn_b(y):\n    return fn_a(y)\n"

        ca = Chunk(id="ca", name="fn_a", type="function", file_path="a.py", start_line=1, end_line=3, code=code_a)
        cb = Chunk(id="cb", name="fn_b", type="function", file_path="b.py", start_line=1, end_line=3, code=code_b)

        graph = CodebaseGraph()
        graph.build_from_chunks([ca, cb])

        # Analyzing cyclical function should terminate cleanly without RecursionError
        caller_code = "def caller():\n    v = request.args.get('x')\n    fn_a(v)\n"
        scanner = SecurityASTScanner(caller_code, filename="caller.py", codebase_graph=graph, depth_limit=3)
        vulns = scanner.scan()
        self.assertIsInstance(vulns, list)


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

    def test_ollama_configurable_timeout(self):
        auditor = GroqSecurityAuditor(groq_api_key=None)
        self.assertEqual(auditor.ollama_timeout, 15.0)

        custom_auditor = GroqSecurityAuditor(groq_api_key=None, ollama_timeout=25.0)
        self.assertEqual(custom_auditor.ollama_timeout, 25.0)

    @patch("src.agents.security_auditor.requests.get")
    def test_ollama_timeout_graceful_degradation(self, mock_get):
        mock_get.return_value.status_code = 200
        auditor = GroqSecurityAuditor(groq_api_key=None, ollama_timeout=0.01)
        with patch.object(auditor, "_call_ollama_api_sync", side_effect=lambda prompt: __import__("time").sleep(0.2)):
            vulns = auditor.audit_code("a = 1", filename="test.py")
            self.assertEqual(vulns, [])

    def test_ollama_timeout_async_graceful_degradation(self):
        import asyncio
        auditor = GroqSecurityAuditor(groq_api_key=None, ollama_timeout=0.01)

        async def _run():
            with patch.object(auditor, "_call_ollama_api_sync", side_effect=lambda prompt: __import__("time").sleep(0.2)):
                return await auditor.audit_code_async("a = 1", filename="test.py")

        loop = asyncio.new_event_loop()
        try:
            vulns = loop.run_until_complete(_run())
            self.assertEqual(vulns, [])
        finally:
            loop.close()


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

    def test_deduplication_by_file_line_range_normalized_category(self):
        ast_vuln = Vulnerability(
            id="SAST-001",
            owasp_category="A03:2021-Injection",
            title="Direct SQL String Concatenation / Formatting (SQL Injection)",
            severity="Critical",
            line_number=10,
            code_snippet="cursor.execute(f'SELECT {x}')",
            description="SQLi via f-string",
            remediation="Use params",
            source="AST",
            file_path="app.py",
        )
        llm_vuln = Vulnerability(
            id="LLM-001",
            owasp_category="A03",
            title="SQL Injection Vulnerability",
            severity="Critical",
            line_number=11,
            code_snippet="cursor.execute(...)",
            description="LLM detected SQL Injection",
            remediation="Use parameterized queries",
            source="Groq-LLM",
            file_path="app.py",
        )
        llm_distinct = Vulnerability(
            id="LLM-002",
            owasp_category="A07",
            title="Hardcoded JWT Secret",
            severity="High",
            line_number=50,
            code_snippet="secret = '12345'",
            description="Hardcoded secret key",
            remediation="Use env vars",
            source="Groq-LLM",
            file_path="app.py",
        )
        scorecard = calculate_security_scorecard([ast_vuln], [llm_vuln, llm_distinct], filepath="app.py")
        self.assertEqual(len(scorecard.vulnerabilities), 2)
        self.assertEqual(scorecard.vulnerabilities[0].id, "SAST-001")
        self.assertEqual(scorecard.vulnerabilities[1].id, "LLM-002")


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

