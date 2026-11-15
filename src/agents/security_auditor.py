"""
SAST Security & Vulnerability Auditor Agent (TASK-E4)

Scans retrieved code chunks and source files using AST static analysis rules
and Groq LLM prompts against OWASP Top 10 security risks.
Produces an automated Security Scorecard (Pass/Fail, Severity: Low/Med/High/Critical).
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

import requests

from src.schema import AgentResponse, Chunk, RetrievalResult

# ---------------------------------------------------------------------------
# Constants & OWASP Definitions
# ---------------------------------------------------------------------------

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "qwen-2.5-coder-32b"  # or llama-3.3-70b-versatile
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_TIMEOUT = 15.0

OWASP_CATEGORIES = {
    "A01": "A01:2021-Broken Access Control",
    "A02": "A02:2021-Cryptographic Failures",
    "A03": "A03:2021-Injection",
    "A04": "A04:2021-Insecure Design",
    "A05": "A05:2021-Security Misconfiguration",
    "A06": "A06:2021-Vulnerable and Outdated Components",
    "A07": "A07:2021-Identification and Authentication Failures",
    "A08": "A08:2021-Software and Data Integrity Failures",
    "A09": "A09:2021-Security Logging and Monitoring Failures",
    "A10": "A10:2021-Server-Side Request Forgery (SSRF)",
}


# ---------------------------------------------------------------------------
# Vulnerability & Scorecard Data Models
# ---------------------------------------------------------------------------

@dataclass
class Vulnerability:
    id: str
    owasp_category: str
    title: str
    severity: str  # "Critical" | "High" | "Medium" | "Low"
    line_number: int
    code_snippet: str
    description: str
    remediation: str
    source: str = "AST"  # "AST" or "LLM"
    file_path: str = ""
    start_line: int | None = None
    end_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "owasp_category": self.owasp_category,
            "title": self.title,
            "severity": self.severity,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "description": self.description,
            "remediation": self.remediation,
            "source": self.source,
        }
        if self.file_path:
            d["file_path"] = self.file_path
        if self.start_line is not None:
            d["start_line"] = self.start_line
        if self.end_line is not None:
            d["end_line"] = self.end_line
        return d


@dataclass
class SecurityScorecard:
    status: str  # "PASS" | "FAIL"
    score: int  # 0 to 100
    summary: str
    vulnerabilities: list[Vulnerability] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)
    owasp_breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "summary": self.summary,
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "metrics": self.metrics,
            "owasp_breakdown": self.owasp_breakdown,
        }

    def to_markdown(self) -> str:
        status_icon = "[PASS]" if self.status == "PASS" else "[FAIL]"
        lines = [
            f"# SAST Security Scorecard",
            f"",
            f"**Overall Status:** {status_icon} | **Security Score:** `{self.score}/100`",
            f"",
            f"**Summary:** {self.summary}",
            f"",
            f"### Vulnerability Breakdown",
            f"- **Critical:** `{self.metrics.get('critical_count', 0)}`",
            f"- **High:** `{self.metrics.get('high_count', 0)}`",
            f"- **Medium:** `{self.metrics.get('medium_count', 0)}`",
            f"- **Low:** `{self.metrics.get('low_count', 0)}`",
            f"- **Total Scanned Findings:** `{len(self.vulnerabilities)}`",
            f"",
        ]

        if self.vulnerabilities:
            lines.append("### Detected Vulnerabilities")
            lines.append("| ID | Severity | OWASP Category | Line | Description | Source |")
            lines.append("|---|---|---|---|---|---|")
            for v in self.vulnerabilities:
                sev_badge = f"**{v.severity.upper()}**"
                lines.append(
                    f"| {v.id} | {sev_badge} | {v.owasp_category} | L{v.line_number} | {v.title} | {v.source} |"
                )
            lines.append("")

            lines.append("### Remediations & Actionable Fixes")
            for v in self.vulnerabilities:
                lines.append(f"#### [{v.id}] {v.title} (Line {v.line_number})")
                lines.append(f"- **OWASP Category:** {v.owasp_category}")
                lines.append(f"- **Description:** {v.description}")
                lines.append(f"- **Snippet:** `{v.code_snippet}`")
                lines.append(f"- **Recommended Fix:**\n```python\n{v.remediation}\n```")
                lines.append("")

        return "\n".join(lines)



# ---------------------------------------------------------------------------
# Symbol Table (Import Resolution)
# ---------------------------------------------------------------------------

class SymbolTable:
    """
    Per-file symbol table mapping local identifiers to fully qualified names (FQNs).
    Supports:
      - import x as y
      - from x import y as z
      - from x import * (best-effort resolution)
    """

    def __init__(self) -> None:
        self.symbols: dict[str, str] = {}
        self.wildcards: list[str] = []

    def register_import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name
            self.symbols[local] = alias.name

    def register_import_from(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        prefix = "." * node.level + mod if node.level else mod
        for alias in node.names:
            if alias.name == "*":
                if prefix:
                    self.wildcards.append(prefix)
            else:
                local = alias.asname or alias.name
                fqn = f"{prefix}.{alias.name}" if prefix else alias.name
                self.symbols[local] = fqn

    def resolve_name(self, name: str) -> str:
        if name in self.symbols:
            return self.symbols[name]
        for mod_name in self.wildcards:
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                if hasattr(mod, name):
                    return f"{mod_name}.{name}"
            except Exception:
                pass
        return name

    def resolve_call(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self.resolve_name(node.id)
        if isinstance(node, ast.Attribute):
            base = self.resolve_call(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""

    @classmethod
    def from_ast(cls, tree: ast.AST) -> SymbolTable:
        st = cls()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                st.register_import(n)
            elif isinstance(n, ast.ImportFrom):
                st.register_import_from(n)
        return st


# ---------------------------------------------------------------------------
# AST Rules Scanner (SecurityASTScanner)
# ---------------------------------------------------------------------------

class SecurityASTScanner(ast.NodeVisitor):
    """
    AST Visitor that scans Python AST for OWASP Top 10 vulnerabilities.
    """

    SECRET_PATTERNS = [
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID", "Critical"),
        (r"eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+", "JWT Secret Token", "High"),
        (r"-----BEGIN (?:RSA )?PRIVATE KEY-----", "RSA Private Key", "Critical"),
        (r"ghp_[A-Za-z0-9]{36}", "GitHub Personal Access Token", "Critical"),
    ]

    SENSITIVE_VAR_NAMES = {"api_key", "apikey", "secret_key", "secret", "private_key", "jwt_secret", "auth_token"}

    def __init__(
        self,
        code_text: str,
        filename: str = "<unknown>",
        codebase_graph: Any = None,
        depth_limit: int = 3,
    ):
        self.code_text = code_text
        self.code_lines = code_text.splitlines()
        self.filename = filename
        self.codebase_graph = codebase_graph
        self.depth_limit = depth_limit
        self.findings: list[Vulnerability] = []
        self._vuln_counter = 1
        self.symbol_table: SymbolTable = SymbolTable()
        self._summary_cache: dict[str, FunctionSummary] = {}

    def _add_vulnerability(
        self,
        owasp_code: str,
        title: str,
        severity: str,
        line_no: int,
        snippet: str,
        description: str,
        remediation: str,
        end_line_no: int | None = None,
    ):
        v_id = f"SAST-{self._vuln_counter:03d}"
        self._vuln_counter += 1
        owasp_cat = OWASP_CATEGORIES.get(owasp_code, owasp_code)
        self.findings.append(
            Vulnerability(
                id=v_id,
                owasp_category=owasp_cat,
                title=title,
                severity=severity,
                line_number=line_no,
                code_snippet=snippet.strip(),
                description=description,
                remediation=remediation,
                source="AST",
                file_path=self.filename,
                start_line=line_no,
                end_line=end_line_no if end_line_no is not None else line_no,
            )
        )

    def _get_line_snippet(self, line_no: int) -> str:
        if 1 <= line_no <= len(self.code_lines):
            return self.code_lines[line_no - 1]
        return ""

    def scan(self) -> list[Vulnerability]:
        self.findings.clear()
        self._vuln_counter = 1

        # First: Regex-based scan for raw string secret patterns across the full file text
        for line_idx, line in enumerate(self.code_lines, start=1):
            for pattern, name, sev in self.SECRET_PATTERNS:
                if re.search(pattern, line):
                    self._add_vulnerability(
                        owasp_code="A02",
                        title=f"Hardcoded {name} Detected",
                        severity=sev,
                        line_no=line_idx,
                        snippet=line,
                        description=f"Hardcoded sensitive secret ({name}) found directly in source code.",
                        remediation="Store secrets in environment variables or a key vault (e.g., os.getenv('SECRET_KEY')).",
                    )

        # Second: AST parsing for structural security rules
        try:
            tree = ast.parse(self.code_text, filename=self.filename)
            self.symbol_table = SymbolTable.from_ast(tree)
            self.visit(tree)
            self._scan_taint_flows(tree)
        except (SyntaxError, ValueError, RecursionError, Exception):
            # If code is a partial fragment, has syntax issues, or malformed encoding, fallback cleanly
            pass

        return self.findings

    def visit_Assign(self, node: ast.Assign):
        # A02 & A07: Hardcoded secrets in variable assignments
        for target in node.targets:
            var_name = ""
            if isinstance(target, ast.Name):
                var_name = target.id
            elif isinstance(target, ast.Attribute):
                var_name = target.attr

            if var_name.lower() in self.SENSITIVE_VAR_NAMES and isinstance(node.value, ast.Constant):
                val = str(node.value.value)
                if len(val) > 4 and not val.startswith("env:") and not val.startswith("${"):
                    self._add_vulnerability(
                        owasp_code="A02",
                        title=f"Hardcoded Sensitive Variable '{var_name}'",
                        severity="High",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description=f"Variable '{var_name}' is assigned a hardcoded plaintext secret value.",
                        remediation=f"{var_name} = os.getenv('{var_name.upper()}')",
                    )

            # A05: Security Misconfiguration - DEBUG = True
            if var_name.upper() == "DEBUG" and isinstance(node.value, ast.Constant) and node.value.value is True:
                self._add_vulnerability(
                    owasp_code="A05",
                    title="Debug Mode Enabled in Configuration",
                    severity="Medium",
                    line_no=node.lineno,
                    snippet=self._get_line_snippet(node.lineno),
                    description="DEBUG flag is set to True, which risks exposing stack traces and internal state.",
                    remediation="DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'",
                )

        # A03: SQL Injection in f-string query assignments
        if isinstance(node.value, ast.JoinedStr):
            line_str = self._get_line_snippet(node.lineno).upper()
            if any(kw in line_str for kw in ("SELECT ", "INSERT INTO ", "UPDATE ", "DELETE FROM ")):
                self._add_vulnerability(
                    owasp_code="A03",
                    title="SQL Injection Risk via Formatted F-String Query",
                    severity="Critical",
                    line_no=node.lineno,
                    snippet=self._get_line_snippet(node.lineno),
                    description="Constructing raw SQL queries via f-string formatting invites SQL injection attacks.",
                    remediation="Use parameterized query placeholders e.g. cursor.execute('SELECT * FROM tbl WHERE id = %s', (val,))",
                )

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        fqn = self.symbol_table.resolve_call(node.func)
        func_name = ""
        module_name = ""
        root_module = ""

        if "." in fqn:
            module_name, func_name = fqn.rsplit(".", 1)
            root_module = fqn.split(".", 1)[0]
        else:
            func_name = fqn
            module_name = ""
            root_module = ""

        # A03: OS Command Injection (os.system, subprocess with shell=True, eval, exec)
        if func_name in ("eval", "exec") or fqn in ("builtins.eval", "builtins.exec"):
            self._add_vulnerability(
                owasp_code="A03",
                title=f"Dynamic Code Execution via {func_name}()",
                severity="Critical",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description=f"Using {func_name}() allows arbitrary code execution if untrusted input is passed.",
                remediation="Refactor code to avoid dynamic eval/exec, or use ast.literal_eval for safe literal evaluation.",
            )

        if (module_name == "os" or fqn == "os.system") and func_name == "system":
            self._add_vulnerability(
                owasp_code="A03",
                title="OS Command Injection Risk via os.system()",
                severity="High",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description="os.system executes shell commands without parameter sanitization.",
                remediation="Use subprocess.run(['cmd', arg1, arg2], shell=False) instead of os.system().",
            )

        if (module_name == "subprocess" or root_module == "subprocess") and func_name in ("call", "Popen", "run", "check_output"):
            has_shell = any(
                keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                for keyword in node.keywords
            )
            if has_shell:
                self._add_vulnerability(
                    owasp_code="A03",
                    title="Subprocess Executed with shell=True",
                    severity="High",
                    line_no=node.lineno,
                    snippet=self._get_line_snippet(node.lineno),
                    description="Executing subprocess with shell=True enables shell injection attacks if arguments are formatted strings.",
                    remediation="Pass command arguments as a list of strings and set shell=False.",
                )
            else:
                self._add_vulnerability(
                    owasp_code="A03",
                    title="Subprocess Call - Execution Audit",
                    severity="Low",
                    line_no=node.lineno,
                    snippet=self._get_line_snippet(node.lineno),
                    description="Subprocess invocation audited for possible command execution risks.",
                    remediation="Ensure command arguments are sanitized and avoid executing untrusted input.",
                )

        # A03: SQL Injection detection (cursor.execute with f-string or % formatting)
        if func_name in ("execute", "executemany", "read_sql"):
            if node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.JoinedStr):
                    self._add_vulnerability(
                        owasp_code="A03",
                        title="SQL Injection Risk via Formatted F-String",
                        severity="Critical",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description="Database query constructed using f-string interpolation invites SQL injection.",
                        remediation="Use parameterized queries e.g. cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
                    )
                elif isinstance(first_arg, ast.BinOp) and isinstance(first_arg.op, (ast.Mod, ast.Add)):
                    self._add_vulnerability(
                        owasp_code="A03",
                        title="SQL Injection Risk via String Concatenation/Formatting",
                        severity="Critical",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description="Database query constructed using string concatenation or % formatting.",
                        remediation="Use parameterized queries e.g. cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
                    )
                elif isinstance(first_arg, ast.Call) and isinstance(first_arg.func, ast.Attribute) and first_arg.func.attr == "format":
                    self._add_vulnerability(
                        owasp_code="A03",
                        title="SQL Injection Risk via str.format()",
                        severity="Critical",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description="Database query constructed using .format() string method.",
                        remediation="Use parameterized queries e.g. cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
                    )

        # A06: Unsafe Deserialization (pickle.loads, yaml.unsafe_load, marshal.loads)
        if (module_name == "pickle" or root_module == "pickle") and func_name in ("loads", "load"):
            self._add_vulnerability(
                owasp_code="A06",
                title="Insecure Deserialization via pickle",
                severity="Critical",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description="pickle deserializes untrusted data into arbitrary Python objects, allowing remote code execution.",
                remediation="Use safer serialization formats such as json, msgpack, or protocol buffers.",
            )

        if (module_name == "yaml" or root_module == "yaml") and func_name in ("unsafe_load", "load"):
            # Check if Loader is safe
            has_safe_loader = any(
                kw.arg == "Loader" and isinstance(kw.value, ast.Attribute) and kw.value.attr == "SafeLoader"
                for kw in node.keywords
            )
            if not has_safe_loader and func_name == "unsafe_load":
                self._add_vulnerability(
                    owasp_code="A06",
                    title="Unsafe YAML Deserialization",
                    severity="High",
                    line_no=node.lineno,
                    snippet=self._get_line_snippet(node.lineno),
                    description="yaml.unsafe_load allows arbitrary code execution from untrusted YAML documents.",
                    remediation="Use yaml.safe_load(data) instead of yaml.unsafe_load(data).",
                )

        # A02: Weak Hash Algorithms (hashlib.md5, hashlib.sha1)
        if (module_name == "hashlib" or root_module == "hashlib") and func_name in ("md5", "sha1"):
            self._add_vulnerability(
                owasp_code="A02",
                title=f"Use of Weak Hash Algorithm (hashlib.{func_name})",
                severity="Medium",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description=f"{func_name.upper()} is cryptographically weak and vulnerable to collision attacks.",
                remediation=f"Use hashlib.sha256() or password hashing libraries like bcrypt or argon2.",
            )

        # A04: Insecure PRNG (random.random, random.randint, random.choice)
        if (module_name == "random" or root_module == "random") and func_name in ("random", "randint", "choice", "randrange"):
            self._add_vulnerability(
                owasp_code="A04",
                title="Use of Insecure Pseudo-Random Number Generator",
                severity="Low",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description="Standard random module PRNG is predictable and unsuitable for security/cryptographic purposes.",
                remediation="Use the cryptographically secure secrets module (e.g. secrets.token_hex()).",
            )

        # A05: SSL/TLS Verification Disabled (_create_unverified_context or verify=False)
        if func_name in ("_create_unverified_context", "_create_unverified_https_context"):
            self._add_vulnerability(
                owasp_code="A05",
                title="Creation of Unverified SSL/TLS Context",
                severity="Medium",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description="Creating an unverified SSL context bypasses certificate validation and exposes connections to MitM attacks.",
                remediation="Use ssl.create_default_context() with valid certificate verification.",
            )

        # A10: Unvalidated URL open (urllib.request.urlopen or urllib.urlopen)
        if func_name in ("urlopen", "urlretrieve") or (root_module in ("urllib", "request") and func_name in ("urlopen", "urlretrieve")):
            self._add_vulnerability(
                owasp_code="A10",
                title="Audit URL Open for Permitted Schemes",
                severity="Medium",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description="urlopen allows unexpected schemes (e.g., file://) if not restricted to http/https.",
                remediation="Validate URL scheme with urllib.parse.urlparse before opening.",
            )

        # A05: SSL/TLS Verification Disabled (verify=False in HTTP requests)
        if func_name in ("get", "post", "put", "delete", "request") and (
            module_name in ("requests", "httpx", "aiohttp") or root_module in ("requests", "httpx", "aiohttp") or func_name in ("get", "post")
        ):
            for keyword in node.keywords:
                if keyword.arg == "verify" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
                    self._add_vulnerability(
                        owasp_code="A05",
                        title="Disabled SSL/TLS Certificate Verification (verify=False)",
                        severity="High",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description="Setting verify=False disables SSL/TLS certificate validation, enabling Man-in-the-Middle (MitM) attacks.",
                        remediation="Remove verify=False or provide a trusted CA certificate bundle path.",
                    )

        # A10: Potential SSRF via unvalidated request URL
        if (module_name in ("requests", "httpx") or root_module in ("requests", "httpx")) and func_name in ("get", "post"):
            if node.args:
                url_arg = node.args[0]
                if isinstance(url_arg, ast.Name):
                    self._add_vulnerability(
                        owasp_code="A10",
                        title="Potential Server-Side Request Forgery (SSRF)",
                        severity="Low",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description=f"HTTP request targets dynamic variable '{url_arg.id}'. If user-controlled, this can allow SSRF.",
                        remediation="Validate request URLs against an allowlist of permitted domains/IPs before fetching.",
                    )
            if node.args:
                url_arg = node.args[0]
                if isinstance(url_arg, ast.Name):
                    self._add_vulnerability(
                        owasp_code="A10",
                        title="Potential Server-Side Request Forgery (SSRF)",
                        severity="Low",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description=f"HTTP request targets dynamic variable '{url_arg.id}'. If user-controlled, this can allow SSRF.",
                        remediation="Validate request URLs against an allowlist of permitted domains/IPs before fetching.",
                    )

        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        # A07: Plaintext Password Comparison (if input_password == stored_password)
        left_str = self._ast_to_str(node.left).lower()
        for comparator in node.comparators:
            comp_str = self._ast_to_str(comparator).lower()
            if ("password" in left_str or "pass" in left_str) and ("password" in comp_str or "pass" in comp_str):
                self._add_vulnerability(
                    owasp_code="A07",
                    title="Direct Password String Comparison Vulnerable to Timing Attack",
                    severity="Medium",
                    line_no=node.lineno,
                    snippet=self._get_line_snippet(node.lineno),
                    description="Comparing password strings directly using '==' exposes response timing differences.",
                    remediation="Use hmac.compare_digest(supplied_password, expected_password) for constant-time comparison.",
                )
        self.generic_visit(node)

    def _ast_to_str(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return ""

    def _scan_taint_flows(self, tree: ast.AST) -> None:
        """
        Runs intra-function taint tracking from sources to sinks.
        Sources: request.args, request.form, request.json, input(), sys.argv, os.environ.
        Sinks: cursor.execute, os.system, subprocess.*, eval, exec, open.
        Sanitizers: parameterized queries, shlex.quote, int()/float() casts, os.path.basename.
        """
        tracker = IntraFunctionTaintScanner(self)
        # Scan module-level statements
        tracker.analyze_block(tree.body)
        # Scan each function independently
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tracker.analyze_block(node.body)


# ---------------------------------------------------------------------------
# Intra-Function Taint Tracking (Data-Flow & Sanitizer Analysis)
# ---------------------------------------------------------------------------

def _extract_source(node: ast.AST, symbol_table: SymbolTable | None = None) -> tuple[str, int] | None:
    """
    Extracts taint source if node matches:
    request.args, request.form, request.json, input(), sys.argv, os.environ (or os.getenv).
    """
    if isinstance(node, ast.Call):
        fqn = symbol_table.resolve_call(node.func) if symbol_table else ""
        if fqn in ("input", "builtins.input") or (isinstance(node.func, ast.Name) and node.func.id == "input"):
            return ("input()", node.lineno)
        if fqn in ("os.getenv", "getenv") or (isinstance(node.func, ast.Attribute) and node.func.attr == "getenv"):
            return ("os.getenv()", node.lineno)
        if fqn in ("request.json", "json") or (isinstance(node.func, ast.Attribute) and node.func.attr == "json"):
            return ("request.json()", node.lineno)
        if fqn in ("request.args.get", "request.form.get", "request.json.get", "os.environ.get"):
            return (f"{fqn}()", node.lineno)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            sub_src = _extract_source(node.func.value, symbol_table)
            if sub_src:
                return (f"{sub_src[0]}.get()", node.lineno)

    if isinstance(node, ast.Subscript):
        sub_src = _extract_source(node.value, symbol_table)
        if sub_src:
            return (f"{sub_src[0]}[]", node.lineno)

    if isinstance(node, ast.Attribute):
        fqn = symbol_table.resolve_call(node) if symbol_table else ""
        if fqn in ("request.args", "request.form", "request.json"):
            return (fqn, node.lineno)
        if fqn == "sys.argv":
            return ("sys.argv", node.lineno)
        if fqn == "os.environ":
            return ("os.environ", node.lineno)
        if isinstance(node.value, ast.Name):
            obj = node.value.id
            attr = node.attr
            if obj == "request" and attr in ("args", "form", "json"):
                return (f"request.{attr}", node.lineno)
            if obj == "sys" and attr == "argv":
                return ("sys.argv", node.lineno)
            if obj == "os" and attr == "environ":
                return ("os.environ", node.lineno)

    if isinstance(node, ast.Name) and symbol_table:
        fqn = symbol_table.resolve_name(node.id)
        if fqn in ("request.args", "request.form", "request.json", "sys.argv", "os.environ"):
            return (fqn, node.lineno)

    return None


def _is_sanitizer_call(node: ast.AST, symbol_table: SymbolTable | None = None) -> bool:
    """
    Returns True if node represents a known sanitizer call:
    - int(...), float(...) casts
    - shlex.quote(...)
    - os.path.basename(...) / path.basename(...)
    """
    if not isinstance(node, ast.Call):
        return False

    fqn = symbol_table.resolve_call(node.func) if symbol_table else ""
    if fqn in ("int", "float", "builtins.int", "builtins.float") or (
        isinstance(node.func, ast.Name) and node.func.id in ("int", "float")
    ):
        return True

    if fqn in ("shlex.quote", "quote") or (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "quote"
        and getattr(node.func.value, "id", None) == "shlex"
    ):
        return True

    if fqn in ("os.path.basename", "posixpath.basename", "ntpath.basename", "path.basename", "basename") or (
        isinstance(node.func, ast.Attribute) and node.func.attr == "basename"
    ):
        return True

    return False


def _check_taint(
    node: ast.AST,
    tainted_vars: dict[str, tuple[str, int, list[str]]],
    symbol_table: SymbolTable | None = None,
    codebase_graph: Any = None,
    summary_cache: dict[str, FunctionSummary] | None = None,
) -> tuple[str, int, list[str]] | None:
    """
    Recursively inspects an expression to check if it contains tainted data.
    Returns (source_desc, source_lineno, chain) or None. Sanitizers clear taint.
    """
    if node is None:
        return None

    if _is_sanitizer_call(node, symbol_table):
        return None

    src = _extract_source(node, symbol_table)
    if src:
        src_desc, src_line = src
        return (src_desc, src_line, [src_desc])

    if isinstance(node, ast.Name):
        return tainted_vars.get(node.id)

    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                t = _check_taint(part.value, tainted_vars, symbol_table, codebase_graph, summary_cache)
                if t:
                    return t
        return None

    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return _check_taint(node.left, tainted_vars, symbol_table, codebase_graph, summary_cache) or _check_taint(
                node.right, tainted_vars, symbol_table, codebase_graph, summary_cache
            )
        elif isinstance(node.op, ast.Mod):
            return _check_taint(node.right, tainted_vars, symbol_table, codebase_graph, summary_cache) or _check_taint(
                node.left, tainted_vars, symbol_table, codebase_graph, summary_cache
            )
        return None

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            t_fmt = _check_taint(node.func.value, tainted_vars, symbol_table, codebase_graph, summary_cache)
            if t_fmt:
                return t_fmt
            for arg in node.args:
                t_arg = _check_taint(arg, tainted_vars, symbol_table, codebase_graph, summary_cache)
                if t_arg:
                    return t_arg
            for kw in node.keywords:
                t_kw = _check_taint(kw.value, tainted_vars, symbol_table, codebase_graph, summary_cache)
                if t_kw:
                    return t_kw
            return None

        # Cross-file / function summary check: does this call return tainted parameter data?
        if codebase_graph and summary_cache is not None:
            callee_name = symbol_table.resolve_call(node.func) if symbol_table else ""
            target_id = getattr(codebase_graph, "_name_to_chunk_id", {}).get(callee_name) or getattr(
                codebase_graph, "_name_to_chunk_id", {}
            ).get(callee_name.split(".")[-1])
            target_chunk = getattr(codebase_graph, "_chunk_map", {}).get(target_id)
            if target_chunk:
                cal_summary = summary_cache.get(getattr(target_chunk, "id", ""))
                if not cal_summary:
                    cal_summary = build_function_summary(
                        target_chunk, codebase_graph, summary_cache, set(), 0, 3
                    )
                if cal_summary:
                    for idx, arg in enumerate(node.args):
                        if idx < len(cal_summary.params):
                            p_name = cal_summary.params[idx]
                            if p_name in cal_summary.param_to_return:
                                t_arg = _check_taint(arg, tainted_vars, symbol_table, codebase_graph, summary_cache)
                                if t_arg:
                                    return (t_arg[0], t_arg[1], t_arg[2] + [f"{cal_summary.name}()"])

    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for elt in node.elts:
            t = _check_taint(elt, tainted_vars, symbol_table, codebase_graph, summary_cache)
            if t:
                return t
        return None

    return None


def _inspect_sink(
    node: ast.Call, symbol_table: SymbolTable | None = None
) -> tuple[str, str, str, str, ast.AST] | None:
    """
    Checks if a Call node is a known sink:
    cursor.execute, os.system, subprocess.*, eval, exec, open.
    Returns (sink_name, owasp_code, default_title, severity, vulnerable_arg_node) or None.
    """
    fqn = symbol_table.resolve_call(node.func) if symbol_table else ""
    func = node.func

    if fqn in ("eval", "exec", "builtins.eval", "builtins.exec") or (
        isinstance(func, ast.Name) and func.id in ("eval", "exec")
    ):
        if node.args:
            func_name = fqn.split(".")[-1] if fqn else func.id
            return (func_name, "A03", f"Code Injection via Tainted {func_name}()", "Critical", node.args[0])

    if fqn in ("open", "io.open", "builtins.open", "os.open") or (
        isinstance(func, ast.Name) and func.id == "open"
    ) or (
        isinstance(func, ast.Attribute) and func.attr == "open" and getattr(func.value, "id", None) in ("io", "os")
    ):
        if node.args:
            return ("open", "A01", "Path Traversal via Tainted File Path in open()", "High", node.args[0])

    if fqn.endswith((".execute", ".executemany")) or (
        isinstance(func, ast.Attribute) and func.attr in ("execute", "executemany")
    ):
        if node.args:
            return ("cursor.execute", "A03", "SQL Injection via Tainted Query", "Critical", node.args[0])

    if fqn == "os.system" or (
        isinstance(func, ast.Attribute) and func.attr == "system" and getattr(func.value, "id", None) == "os"
    ):
        if node.args:
            return ("os.system", "A03", "Command Injection via Tainted os.system()", "Critical", node.args[0])

    if fqn.startswith("subprocess.") or (
        isinstance(func, ast.Attribute)
        and func.attr in ("call", "Popen", "run", "check_output", "check_call")
        and getattr(func.value, "id", None) == "subprocess"
    ):
        if node.args:
            sub_name = fqn if fqn.startswith("subprocess.") else f"subprocess.{func.attr}"
            has_shell = any(
                kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in node.keywords
            )
            title = f"Command Injection via Tainted {sub_name}()"
            sev = "Critical" if has_shell else "High"
            return (sub_name, "A03", title, sev, node.args[0])

    return None


@dataclass
class SinkFlow:
    sink_name: str
    owasp_code: str
    title: str
    severity: str
    sink_lineno: int
    chain_suffix: list[str]


@dataclass
class FunctionSummary:
    name: str
    params: list[str]
    param_to_sinks: dict[str, list[SinkFlow]] = field(default_factory=dict)
    param_to_return: set[str] = field(default_factory=set)


def build_function_summary(
    chunk: Any,
    codebase_graph: Any,
    summary_cache: dict[str, FunctionSummary],
    call_stack: set[str],
    current_depth: int = 0,
    max_depth: int = 3,
) -> FunctionSummary:
    chunk_id = getattr(chunk, "id", getattr(chunk, "name", ""))
    if chunk_id in summary_cache:
        return summary_cache[chunk_id]
    if current_depth >= max_depth or chunk_id in call_stack:
        return FunctionSummary(name=getattr(chunk, "name", ""), params=[])

    call_stack.add(chunk_id)
    try:
        code = getattr(chunk, "code", "")
        if not code:
            call_stack.remove(chunk_id)
            return FunctionSummary(name=getattr(chunk, "name", ""), params=[])
        tree = ast.parse(code)
    except Exception:
        call_stack.remove(chunk_id)
        return FunctionSummary(name=getattr(chunk, "name", ""), params=[])

    fn_node = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_node = n
            break

    if not fn_node:
        call_stack.remove(chunk_id)
        return FunctionSummary(name=getattr(chunk, "name", ""), params=[])

    params = [a.arg for a in fn_node.args.args if a.arg not in ("self", "cls")]
    summary = FunctionSummary(name=fn_node.name, params=params)
    st = SymbolTable.from_ast(tree)

    for p in params:
        tainted_vars: dict[str, tuple[str, int, list[str]]] = {p: (f"param:{p}", fn_node.lineno, [p])}
        for stmt in fn_node.body:
            for call_n in ast.walk(stmt):
                if isinstance(call_n, ast.Call):
                    # Direct sink check
                    sink = _inspect_sink(call_n, st)
                    if sink:
                        s_name, cat, title, sev, arg = sink
                        t = _check_taint(arg, tainted_vars, st, codebase_graph, summary_cache)
                        if t and t[0] == f"param:{p}":
                            summary.param_to_sinks.setdefault(p, []).append(
                                SinkFlow(s_name, cat, title, sev, call_n.lineno, t[2])
                            )

                    # Inter-file calls via CodebaseGraph edges
                    if codebase_graph:
                        c_name = st.resolve_call(call_n.func)
                        name_map = getattr(codebase_graph, "_name_to_chunk_id", {})
                        target_id = name_map.get(c_name) or name_map.get(c_name.split(".")[-1])
                        if not target_id and hasattr(codebase_graph, "graph") and codebase_graph.graph.has_node(chunk_id):
                            for _, v, data in codebase_graph.graph.out_edges(chunk_id, data=True):
                                relations = data.get("relations", set())
                                if "CALLS" in relations or "IMPORTS" in relations:
                                    node_data = codebase_graph.graph.nodes[v]
                                    if node_data.get("name") in (c_name, c_name.split(".")[-1]):
                                        target_id = v
                                        break
                        if target_id and target_id != chunk_id:
                            target_c = getattr(codebase_graph, "_chunk_map", {}).get(target_id)
                            if target_c:
                                cal_summary = build_function_summary(
                                    target_c,
                                    codebase_graph,
                                    summary_cache,
                                    call_stack,
                                    current_depth + 1,
                                    max_depth,
                                )
                                for idx, a in enumerate(call_n.args):
                                    if idx < len(cal_summary.params):
                                        cal_p = cal_summary.params[idx]
                                        t_arg = _check_taint(a, tainted_vars, st, codebase_graph, summary_cache)
                                        if t_arg and t_arg[0] == f"param:{p}":
                                            for sf in cal_summary.param_to_sinks.get(cal_p, []):
                                                sf_tail = sf.chain_suffix[1:] if (sf.chain_suffix and sf.chain_suffix[-1] == sf.sink_name) else sf.chain_suffix[1:] + [sf.sink_name]
                                                chain = t_arg[2] + [f"{cal_summary.name}({cal_p})"] + sf_tail
                                                summary.param_to_sinks.setdefault(p, []).append(
                                                    SinkFlow(sf.sink_name, sf.owasp_code, sf.title, sf.severity, call_n.lineno, chain)
                                                )

            if isinstance(stmt, ast.Return) and stmt.value:
                t_ret = _check_taint(stmt.value, tainted_vars, st, codebase_graph, summary_cache)
                if t_ret and t_ret[0] == f"param:{p}":
                    summary.param_to_return.add(p)

    call_stack.remove(chunk_id)
    summary_cache[chunk_id] = summary
    return summary


class IntraFunctionTaintScanner:
    """
    Tracks data-flow taint from untrusted sources to sensitive sinks within functions/blocks,
    with multi-file cross-boundary propagation guided by CodebaseGraph and function summaries.
    """

    def __init__(self, scanner: SecurityASTScanner, symbol_table: SymbolTable | None = None):
        self.scanner = scanner
        self.symbol_table = symbol_table or getattr(scanner, "symbol_table", None) or SymbolTable()
        self.codebase_graph = getattr(scanner, "codebase_graph", None)
        self.summary_cache = getattr(scanner, "_summary_cache", {})
        self.depth_limit = getattr(scanner, "depth_limit", 3)

    def analyze_block(self, statements: list[ast.stmt]) -> None:
        tainted_vars: dict[str, tuple[str, int, list[str]]] = {}
        seen_sinks: set[int] = set()
        self._visit_statements(statements, tainted_vars, seen_sinks)

    def _resolve_target_chunk(self, callee_name: str) -> Any:
        if not self.codebase_graph:
            return None
        graph = self.codebase_graph
        name_map = getattr(graph, "_name_to_chunk_id", {})
        chunk_map = getattr(graph, "_chunk_map", {})
        target_id = name_map.get(callee_name) or name_map.get(callee_name.split(".")[-1])
        if target_id and target_id in chunk_map:
            return chunk_map[target_id]
        return None

    def _get_or_build_summary(self, chunk: Any) -> FunctionSummary:
        return build_function_summary(
            chunk=chunk,
            codebase_graph=self.codebase_graph,
            summary_cache=self.summary_cache,
            call_stack=set(),
            current_depth=0,
            max_depth=self.depth_limit,
        )

    def _visit_statements(
        self,
        statements: list[ast.stmt],
        tainted_vars: dict[str, tuple[str, int, list[str]]],
        seen_sinks: set[int],
    ) -> None:
        for stmt in statements:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Independent scopes handled separately
                continue

            if isinstance(stmt, ast.Assign):
                self._check_call_sinks(stmt.value, tainted_vars, seen_sinks)
                t = _check_taint(stmt.value, tainted_vars, self.symbol_table, self.codebase_graph, self.summary_cache)
                for target in stmt.targets:
                    self._assign_target(target, t, tainted_vars)

            elif isinstance(stmt, ast.AugAssign):
                self._check_call_sinks(stmt.value, tainted_vars, seen_sinks)
                val_t = _check_taint(stmt.value, tainted_vars, self.symbol_table, self.codebase_graph, self.summary_cache)
                if val_t and isinstance(stmt.target, ast.Name):
                    src_desc, src_line, chain = val_t
                    new_chain = chain + [stmt.target.id] if (not chain or chain[-1] != stmt.target.id) else chain
                    tainted_vars[stmt.target.id] = (src_desc, src_line, new_chain)

            elif isinstance(stmt, ast.AnnAssign):
                if stmt.value:
                    self._check_call_sinks(stmt.value, tainted_vars, seen_sinks)
                    t = _check_taint(stmt.value, tainted_vars, self.symbol_table, self.codebase_graph, self.summary_cache)
                    self._assign_target(stmt.target, t, tainted_vars)

            elif isinstance(stmt, ast.Expr):
                self._check_call_sinks(stmt.value, tainted_vars, seen_sinks)

            elif isinstance(stmt, ast.Return):
                if stmt.value:
                    self._check_call_sinks(stmt.value, tainted_vars, seen_sinks)

            elif isinstance(stmt, (ast.If, ast.While)):
                self._check_call_sinks(stmt.test, tainted_vars, seen_sinks)
                self._visit_statements(stmt.body, tainted_vars, seen_sinks)
                self._visit_statements(stmt.orelse, tainted_vars, seen_sinks)

            elif isinstance(stmt, ast.For):
                self._check_call_sinks(stmt.iter, tainted_vars, seen_sinks)
                iter_t = _check_taint(stmt.iter, tainted_vars, self.symbol_table, self.codebase_graph, self.summary_cache)
                self._assign_target(stmt.target, iter_t, tainted_vars)
                self._visit_statements(stmt.body, tainted_vars, seen_sinks)
                self._visit_statements(stmt.orelse, tainted_vars, seen_sinks)

            elif isinstance(stmt, ast.With):
                for item in stmt.items:
                    self._check_call_sinks(item.context_expr, tainted_vars, seen_sinks)
                    if item.optional_vars:
                        item_t = _check_taint(item.context_expr, tainted_vars, self.symbol_table, self.codebase_graph, self.summary_cache)
                        self._assign_target(item.optional_vars, item_t, tainted_vars)
                self._visit_statements(stmt.body, tainted_vars, seen_sinks)

            elif isinstance(stmt, ast.Try):
                self._visit_statements(stmt.body, tainted_vars, seen_sinks)
                for handler in stmt.handlers:
                    self._visit_statements(handler.body, tainted_vars, seen_sinks)
                self._visit_statements(stmt.orelse, tainted_vars, seen_sinks)
                self._visit_statements(stmt.finalbody, tainted_vars, seen_sinks)

    def _assign_target(
        self,
        target: ast.AST,
        taint: tuple[str, int, list[str]] | None,
        tainted_vars: dict[str, tuple[str, int, list[str]]],
    ) -> None:
        if isinstance(target, ast.Name):
            var_name = target.id
            if taint:
                src_desc, src_line, chain = taint
                new_chain = chain + [var_name] if (not chain or chain[-1] != var_name) else chain
                tainted_vars[var_name] = (src_desc, src_line, new_chain)
            else:
                tainted_vars.pop(var_name, None)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._assign_target(elt, taint, tainted_vars)

    def _check_call_sinks(
        self,
        expr: ast.AST,
        tainted_vars: dict[str, tuple[str, int, list[str]]],
        seen_sinks: set[int],
    ) -> None:
        for node in ast.walk(expr):
            if isinstance(node, ast.Call):
                # 1. Direct local sink check
                sink_info = _inspect_sink(node, self.symbol_table)
                if sink_info:
                    sink_name, owasp_code, default_title, sev, target_arg = sink_info
                    taint = _check_taint(target_arg, tainted_vars, self.symbol_table, self.codebase_graph, self.summary_cache)
                    if taint and id(node) not in seen_sinks:
                        seen_sinks.add(id(node))
                        src_desc, src_line, chain = taint
                        chain_repr = " -> ".join(chain + [sink_name])
                        desc = (
                            f"Untrusted data from '{src_desc}' (line {src_line}) "
                            f"flows to sink '{sink_name}' (line {node.lineno}) "
                            f"via chain: {chain_repr}."
                        )
                        rem = (
                            "Sanitize input before passing to sink (e.g. use parameterized queries, "
                            "shlex.quote, int() casts, or os.path.basename)."
                        )
                        self.scanner._add_vulnerability(
                            owasp_code=owasp_code,
                            title=default_title,
                            severity=sev,
                            line_no=node.lineno,
                            snippet=self.scanner._get_line_snippet(node.lineno),
                            description=desc,
                            remediation=rem,
                        )

                # 2. Cross-file / inter-procedural sink check via CodebaseGraph
                if self.codebase_graph:
                    callee_name = self.symbol_table.resolve_call(node.func)
                    target_chunk = self._resolve_target_chunk(callee_name)
                    if target_chunk:
                        callee_summary = self._get_or_build_summary(target_chunk)
                        for idx, arg_node in enumerate(node.args):
                            if idx < len(callee_summary.params):
                                param_name = callee_summary.params[idx]
                                taint = _check_taint(arg_node, tainted_vars, self.symbol_table, self.codebase_graph, self.summary_cache)
                                if taint:
                                    for sf in callee_summary.param_to_sinks.get(param_name, []):
                                        if id(node) not in seen_sinks:
                                            seen_sinks.add(id(node))
                                            src_desc, src_line, chain = taint
                                            sf_tail = sf.chain_suffix[1:] if (sf.chain_suffix and sf.chain_suffix[-1] == sf.sink_name) else sf.chain_suffix[1:] + [sf.sink_name]
                                            full_chain = " -> ".join(chain + [f"{callee_summary.name}({param_name})"] + sf_tail)
                                            desc = (
                                                f"Untrusted data from '{src_desc}' (line {src_line}) "
                                                f"flows to sink '{sf.sink_name}' via cross-file call '{callee_summary.name}' "
                                                f"at line {node.lineno} via chain: {full_chain}."
                                            )
                                            rem = (
                                                "Sanitize input before passing across function boundaries or "
                                                "use parameterized queries/shlex.quote/int() casts."
                                            )
                                            self.scanner._add_vulnerability(
                                                owasp_code=sf.owasp_code,
                                                title=sf.title,
                                                severity=sf.severity,
                                                line_no=node.lineno,
                                                snippet=self.scanner._get_line_snippet(node.lineno),
                                                description=desc,
                                                remediation=rem,
                                            )


# ---------------------------------------------------------------------------
# Groq LLM Security Auditor Engine (GroqSecurityAuditor)
# ---------------------------------------------------------------------------

class GroqSecurityAuditor:
    """
    Integrates with Groq Cloud API (qwen-2.5-coder-32b / llama-3.3-70b-versatile)
    or Ollama fallback to perform deep semantic OWASP Top 10 security audits on code.
    """

    SYSTEM_PROMPT = """You are a Principal Security Auditor specializing in Static Application Security Testing (SAST) and OWASP Top 10 security risk evaluation.
Analyze the provided source code or code chunk for OWASP Top 10 vulnerabilities.

Respond ONLY with valid JSON structured as follows:
{
  "vulnerabilities": [
    {
      "owasp_code": "A03",
      "title": "Short descriptive title of vulnerability",
      "severity": "Critical", // "Critical" | "High" | "Medium" | "Low"
      "line_number": 12,
      "code_snippet": "problematic line of code",
      "description": "Clear explanation of attack vector and security impact.",
      "remediation": "Exact corrected Python code fix."
    }
  ]
}
If no vulnerabilities are found, return {"vulnerabilities": []}."""

    def __init__(
        self,
        groq_api_key: str | None = None,
        model: str = DEFAULT_GROQ_MODEL,
        ollama_timeout: float | None = None,
    ):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        env_timeout = os.getenv("OLLAMA_TIMEOUT")
        self.ollama_timeout = (
            ollama_timeout
            if ollama_timeout is not None
            else float(env_timeout) if env_timeout else DEFAULT_OLLAMA_TIMEOUT
        )

    def audit_code(
        self,
        code_text: str,
        filename: str = "<unknown>",
        timeout: float | None = None,
    ) -> list[Vulnerability]:
        if not code_text.strip():
            return []

        prompt = f"Filename: {filename}\nSource Code:\n```python\n{code_text}\n```"

        # Attempt 1: Call Groq API if API Key is available
        if self.groq_api_key:
            llm_res = self._call_groq_api(prompt)
            if llm_res:
                return self._parse_llm_json(llm_res, code_text, filename=filename)

        # Attempt 2: Fallback to local Ollama API with configurable timeout and graceful degradation
        ollama_res = self._call_ollama_api(prompt, timeout=timeout)
        if ollama_res:
            return self._parse_llm_json(ollama_res, code_text, filename=filename)

        # Attempt 3: No LLM available or timeout occurred, gracefully return empty list (AST rules serve as baseline)
        return []

    async def audit_code_async(
        self,
        code_text: str,
        filename: str = "<unknown>",
        timeout: float | None = None,
    ) -> list[Vulnerability]:
        """Asynchronous code audit using non-blocking calls and configurable timeout."""
        if not code_text.strip():
            return []

        prompt = f"Filename: {filename}\nSource Code:\n```python\n{code_text}\n```"

        if self.groq_api_key:
            llm_res = await asyncio.to_thread(self._call_groq_api, prompt)
            if llm_res:
                return self._parse_llm_json(llm_res, code_text, filename=filename)

        ollama_res = await self._call_ollama_api_async(prompt, timeout=timeout)
        if ollama_res:
            return self._parse_llm_json(ollama_res, code_text, filename=filename)

        return []

    def _call_groq_api(self, user_prompt: str) -> str | None:
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        try:
            resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass
        return None

    def _call_ollama_api_sync(self, user_prompt: str) -> str | None:
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=0.5)
            if r.status_code != 200:
                return None
        except Exception:
            return None

        try:
            import ollama

            response = ollama.chat(
                model=DEFAULT_OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                format="json",
            )
            if isinstance(response, dict):
                return response.get("message", {}).get("content", "")
            return getattr(getattr(response, "message", None), "content", None)
        except Exception:
            return None

    def _call_ollama_api(self, user_prompt: str, timeout: float | None = None) -> str | None:
        eff_timeout = timeout if timeout is not None else self.ollama_timeout
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._call_ollama_api_sync, user_prompt)
                return future.result(timeout=eff_timeout)
        except (concurrent.futures.TimeoutError, TimeoutError):
            # Graceful degradation to AST-only on timeout
            return None
        except Exception:
            return None

    async def _call_ollama_api_async(self, user_prompt: str, timeout: float | None = None) -> str | None:
        eff_timeout = timeout if timeout is not None else self.ollama_timeout
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_ollama_api_sync, user_prompt),
                timeout=eff_timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            # Graceful degradation to AST-only on timeout
            return None
        except Exception:
            return None

    def _parse_llm_json(self, json_str: str, code_text: str, filename: str = "<unknown>") -> list[Vulnerability]:
        results: list[Vulnerability] = []
        try:
            data = json.loads(json_str)
            raw_vulns = data.get("vulnerabilities", [])
            lines = code_text.splitlines()

            for i, raw in enumerate(raw_vulns, start=1):
                owasp_code = raw.get("owasp_code", "A03")
                owasp_cat = OWASP_CATEGORIES.get(owasp_code, f"{owasp_code}:2021-Security Issue")
                line_no = int(raw.get("line_number", 1))
                snippet = raw.get("code_snippet") or (lines[line_no - 1] if 1 <= line_no <= len(lines) else "")
                start_l = int(raw.get("start_line", line_no))
                end_l = int(raw.get("end_line", line_no))

                results.append(
                    Vulnerability(
                        id=f"LLM-{i:03d}",
                        owasp_category=owasp_cat,
                        title=raw.get("title", "Security Vulnerability Detected"),
                        severity=raw.get("severity", "Medium"),
                        line_number=line_no,
                        code_snippet=snippet.strip(),
                        description=raw.get("description", "Vulnerability detected by Groq Security LLM."),
                        remediation=raw.get("remediation", "# Consult security team for fix."),
                        source="Groq-LLM",
                        file_path=filename,
                        start_line=start_l,
                        end_line=end_l,
                    )
                )
        except Exception:
            pass
        return results


# ---------------------------------------------------------------------------
# Scorecard Generator & Core Auditor Logic
# ---------------------------------------------------------------------------

def normalize_vulnerability_category(cat: str) -> str:
    """
    Normalizes OWASP category strings to canonical standard keys (e.g. 'A01' - 'A10').
    Handles 'A03:2021-Injection', 'A3', 'Injection', 'SQL Injection', 'Command Injection', etc.
    """
    if not cat:
        return "UNKNOWN"
    cat_upper = cat.upper().strip()
    match = re.search(r"\bA0?([1-9]|10)\b", cat_upper)
    if match:
        num = int(match.group(1))
        return f"A{num:02d}"

    cat_lower = cat.lower()
    if any(k in cat_lower for k in ("access", "traversal", "idor", "authz")):
        return "A01"
    elif any(k in cat_lower for k in ("crypto", "cipher", "md5", "sha1", "prng")):
        return "A02"
    elif any(k in cat_lower for k in ("inject", "sql", "command", "os.system", "eval", "exec", "xss")):
        return "A03"
    elif any(k in cat_lower for k in ("design", "rate limit")):
        return "A04"
    elif any(k in cat_lower for k in ("config", "debug", "ssl", "tls", "cors", "default")):
        return "A05"
    elif any(k in cat_lower for k in ("component", "outdated", "vulnerable dependency")):
        return "A06"
    elif any(k in cat_lower for k in ("auth", "password", "session", "credential", "jwt")):
        return "A07"
    elif any(k in cat_lower for k in ("integrity", "deserial", "pickle", "yaml", "untrusted")):
        return "A08"
    elif any(k in cat_lower for k in ("log", "monitor", "alert")):
        return "A09"
    elif any(k in cat_lower for k in ("ssrf", "request forgery", "url open")):
        return "A10"
    return cat_upper


def _get_line_range(v: Vulnerability) -> tuple[int, int]:
    s = getattr(v, "start_line", None)
    if s is None or s <= 0:
        s = v.line_number
    e = getattr(v, "end_line", None)
    if e is None or e <= 0:
        e = v.line_number
    return (min(s, e), max(s, e))


def _line_ranges_overlap(r1: tuple[int, int], r2: tuple[int, int], tolerance: int = 2) -> bool:
    """Check if two line ranges intersect or are within +/- tolerance lines of each other."""
    return not (r1[1] + tolerance < r2[0] or r2[1] + tolerance < r1[0])


def calculate_security_scorecard(
    ast_vulns: list[Vulnerability],
    llm_vulns: list[Vulnerability],
    filepath: str = "<unknown>",
) -> SecurityScorecard:
    """
    Combines AST and LLM vulnerabilities, deduplicates findings by:
      (file, line range, normalized vulnerability category)
    instead of exact title match.
    Computes numerical score (0-100), determines Pass/Fail status, and maps findings to OWASP categories.
    """
    all_vulns: list[Vulnerability] = []

    def _is_duplicate(v: Vulnerability, existing_list: list[Vulnerability], default_file: str) -> bool:
        v_cat = normalize_vulnerability_category(v.owasp_category)
        v_file = os.path.normpath(getattr(v, "file_path", "") or default_file).lower()
        v_range = _get_line_range(v)

        for existing in existing_list:
            ex_cat = normalize_vulnerability_category(existing.owasp_category)
            if v_cat != ex_cat:
                continue
            ex_file = os.path.normpath(getattr(existing, "file_path", "") or default_file).lower()
            if v_file and ex_file and v_file != "<unknown>" and ex_file != "<unknown>" and v_file != ex_file:
                continue
            ex_range = _get_line_range(existing)
            if _line_ranges_overlap(v_range, ex_range, tolerance=2):
                return True
        return False

    # Add AST findings first
    for v in ast_vulns:
        if not _is_duplicate(v, all_vulns, filepath):
            all_vulns.append(v)

    # Add non-duplicate LLM findings (deduped against existing findings)
    for v in llm_vulns:
        if not _is_duplicate(v, all_vulns, filepath):
            all_vulns.append(v)

    # Count by severity
    crit_count = sum(1 for v in all_vulns if v.severity.capitalize() == "Critical")
    high_count = sum(1 for v in all_vulns if v.severity.capitalize() == "High")
    med_count = sum(1 for v in all_vulns if v.severity.capitalize() == "Medium")
    low_count = sum(1 for v in all_vulns if v.severity.capitalize() == "Low")

    # Score calculation: 100 base score minus penalties
    penalties = (crit_count * 25) + (high_count * 15) + (med_count * 8) + (low_count * 3)
    final_score = max(0, min(100, 100 - penalties))

    # Pass/Fail determination
    status = "FAIL" if (final_score < 70 or crit_count > 0 or high_count > 0) else "PASS"

    # OWASP breakdown
    owasp_breakdown: dict[str, int] = {}
    for v in all_vulns:
        cat = v.owasp_category
        owasp_breakdown[cat] = owasp_breakdown.get(cat, 0) + 1

    summary = (
        f"Audited '{os.path.basename(filepath)}': {len(all_vulns)} total security finding(s) detected. "
        f"Security Score: {final_score}/100 ({status})."
    )

    metrics = {
        "critical_count": crit_count,
        "high_count": high_count,
        "medium_count": med_count,
        "low_count": low_count,
        "total_vulnerabilities": len(all_vulns),
        "ast_findings_count": len(ast_vulns),
        "llm_findings_count": len(llm_vulns),
    }

    return SecurityScorecard(
        status=status,
        score=final_score,
        summary=summary,
        vulnerabilities=all_vulns,
        metrics=metrics,
        owasp_breakdown=owasp_breakdown,
    )


# ---------------------------------------------------------------------------
# Public Entry Points
# ---------------------------------------------------------------------------

def audit_code_string(
    code_text: str,
    filename: str = "<unknown>",
    groq_api_key: str | None = None,
    codebase_graph: Any = None,
    depth_limit: int = 3,
    ollama_timeout: float | None = None,
) -> dict[str, Any]:
    """
    Audits a raw string of Python code using both AST rules and Groq LLM auditor.
    Returns AgentResponse-shaped dict.
    """
    scanner = SecurityASTScanner(
        code_text,
        filename=filename,
        codebase_graph=codebase_graph,
        depth_limit=depth_limit,
    )
    ast_vulns = scanner.scan()

    llm_auditor = GroqSecurityAuditor(groq_api_key=groq_api_key, ollama_timeout=ollama_timeout)
    llm_vulns = llm_auditor.audit_code(code_text, filename=filename)

    scorecard = calculate_security_scorecard(ast_vulns, llm_vulns, filepath=filename)

    return {
        "agent_name": "security_auditor",
        "summary": scorecard.summary,
        "details": {
            "scorecard": scorecard.to_dict(),
            "markdown_scorecard": scorecard.to_markdown(),
            "filepath": filename,
        },
        "confidence": 1.0 if scorecard.status == "PASS" else round(scorecard.score / 100.0, 2),
    }


async def audit_code_string_async(
    code_text: str,
    filename: str = "<unknown>",
    groq_api_key: str | None = None,
    codebase_graph: Any = None,
    depth_limit: int = 3,
    ollama_timeout: float | None = None,
) -> dict[str, Any]:
    """
    Asynchronously audits a raw string of Python code with non-blocking LLM calls
    and graceful degradation to AST-only findings on timeout.
    """
    scanner = SecurityASTScanner(
        code_text,
        filename=filename,
        codebase_graph=codebase_graph,
        depth_limit=depth_limit,
    )
    ast_vulns = scanner.scan()

    llm_auditor = GroqSecurityAuditor(groq_api_key=groq_api_key, ollama_timeout=ollama_timeout)
    llm_vulns = await llm_auditor.audit_code_async(code_text, filename=filename)

    scorecard = calculate_security_scorecard(ast_vulns, llm_vulns, filepath=filename)

    return {
        "agent_name": "security_auditor",
        "summary": scorecard.summary,
        "details": {
            "scorecard": scorecard.to_dict(),
            "markdown_scorecard": scorecard.to_markdown(),
            "filepath": filename,
        },
        "confidence": 1.0 if scorecard.status == "PASS" else round(scorecard.score / 100.0, 2),
    }


def audit_file(
    filepath: str,
    groq_api_key: str | None = None,
    codebase_graph: Any = None,
    depth_limit: int = 3,
    ollama_timeout: float | None = None,
) -> dict[str, Any]:
    """
    Audits a Python source file path for OWASP Top 10 vulnerabilities.
    Returns AgentResponse-shaped dict with complete Security Scorecard.
    """
    if not os.path.exists(filepath):
        return {
            "agent_name": "security_auditor",
            "summary": f"File does not exist: {filepath}",
            "details": {"error": "File not found", "filepath": filepath},
            "confidence": None,
        }

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            code_text = f.read()
    except Exception as e:
        return {
            "agent_name": "security_auditor",
            "summary": f"Error reading file {filepath}: {e}",
            "details": {"error": str(e), "filepath": filepath},
            "confidence": None,
        }

    return audit_code_string(
        code_text,
        filename=filepath,
        groq_api_key=groq_api_key,
        codebase_graph=codebase_graph,
        depth_limit=depth_limit,
        ollama_timeout=ollama_timeout,
    )


def audit_retrieved_chunks(
    chunks: Sequence[Chunk | RetrievalResult | dict[str, Any]],
    groq_api_key: str | None = None,
    codebase_graph: Any = None,
    depth_limit: int = 3,
    ollama_timeout: float | None = None,
) -> dict[str, Any]:
    """
    Audits a list of retrieved RAG code chunks for security vulnerabilities,
    wiring CodebaseGraph for cross-file taint analysis.
    """
    if codebase_graph is None:
        chunk_objs = [
            c if isinstance(c, Chunk) else c.chunk if isinstance(c, RetrievalResult) else None
            for c in chunks
        ]
        valid_chunks = [c for c in chunk_objs if c is not None]
        if len(valid_chunks) > 1:
            try:
                from src.retrieval.graph_rag import CodebaseGraph
                codebase_graph = CodebaseGraph()
                codebase_graph.build_from_chunks(valid_chunks)
            except Exception:
                codebase_graph = None

    all_ast_vulns: list[Vulnerability] = []
    all_llm_vulns: list[Vulnerability] = []
    shared_summary_cache: dict[str, FunctionSummary] = {}

    llm_auditor = GroqSecurityAuditor(groq_api_key=groq_api_key, ollama_timeout=ollama_timeout)

    for item in chunks:
        code_text = ""
        file_path = "<retrieved_chunk>"
        start_line = 1

        if isinstance(item, Chunk):
            code_text = item.code
            file_path = item.file_path
            start_line = item.start_line
        elif isinstance(item, RetrievalResult):
            code_text = item.chunk.code
            file_path = item.chunk.file_path
            start_line = item.chunk.start_line
        elif isinstance(item, dict):
            code_text = item.get("code", "")
            file_path = item.get("file_path", "<retrieved_chunk>")
            start_line = item.get("start_line", 1)

        if not code_text.strip():
            continue

        scanner = SecurityASTScanner(
            code_text,
            filename=file_path,
            codebase_graph=codebase_graph,
            depth_limit=depth_limit,
        )
        scanner._summary_cache = shared_summary_cache
        ast_findings = scanner.scan()
        # Adjust line numbers relative to original file if start_line > 1
        for v in ast_findings:
            v.line_number = start_line + (v.line_number - 1)
        all_ast_vulns.extend(ast_findings)

        llm_findings = llm_auditor.audit_code(code_text, filename=file_path)
        for v in llm_findings:
            v.line_number = start_line + (v.line_number - 1)
        all_llm_vulns.extend(llm_findings)

    scorecard = calculate_security_scorecard(all_ast_vulns, all_llm_vulns, filepath="Retrieved RAG Chunks")

    return {
        "agent_name": "security_auditor",
        "summary": scorecard.summary,
        "details": {
            "scorecard": scorecard.to_dict(),
            "markdown_scorecard": scorecard.to_markdown(),
            "retrieved_chunk_count": len(chunks),
        },
        "confidence": 1.0 if scorecard.status == "PASS" else round(scorecard.score / 100.0, 2),
    }


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else __file__
    res = audit_file(target)
    print(res["details"]["markdown_scorecard"])
