"""
SAST Security & Vulnerability Auditor Agent (TASK-E4)

Scans retrieved code chunks and source files using AST static analysis rules
and Groq LLM prompts against OWASP Top 10 security risks.
Produces an automated Security Scorecard (Pass/Fail, Severity: Low/Med/High/Critical).
"""

from __future__ import annotations

import ast
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

    def to_dict(self) -> dict[str, Any]:
        return {
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

    def __init__(self, code_text: str, filename: str = "<unknown>"):
        self.code_text = code_text
        self.code_lines = code_text.splitlines()
        self.filename = filename
        self.findings: list[Vulnerability] = []
        self._vuln_counter = 1

    def _add_vulnerability(
        self,
        owasp_code: str,
        title: str,
        severity: str,
        line_no: int,
        snippet: str,
        description: str,
        remediation: str,
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
            self.visit(tree)
        except SyntaxError:
            # If code is a partial fragment or has syntax issues, fallback cleanly
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

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        func_name = ""
        module_name = ""

        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
            if isinstance(node.func.value, ast.Name):
                module_name = node.func.value.id

        # A03: OS Command Injection (os.system, subprocess with shell=True, eval, exec)
        if func_name == "eval" or func_name == "exec":
            self._add_vulnerability(
                owasp_code="A03",
                title=f"Dynamic Code Execution via {func_name}()",
                severity="Critical",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description=f"Using {func_name}() allows arbitrary code execution if untrusted input is passed.",
                remediation="Refactor code to avoid dynamic eval/exec, or use ast.literal_eval for safe literal evaluation.",
            )

        if module_name == "os" and func_name == "system":
            self._add_vulnerability(
                owasp_code="A03",
                title="OS Command Injection Risk via os.system()",
                severity="High",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description="os.system executes shell commands without parameter sanitization.",
                remediation="Use subprocess.run(['cmd', arg1, arg2], shell=False) instead of os.system().",
            )

        if module_name == "subprocess" and func_name in ("call", "Popen", "run", "check_output"):
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    self._add_vulnerability(
                        owasp_code="A03",
                        title="Subprocess Executed with shell=True",
                        severity="High",
                        line_no=node.lineno,
                        snippet=self._get_line_snippet(node.lineno),
                        description="Executing subprocess with shell=True enables shell injection attacks if arguments are formatted strings.",
                        remediation="Pass command arguments as a list of strings and set shell=False.",
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
        if module_name == "pickle" and func_name in ("loads", "load"):
            self._add_vulnerability(
                owasp_code="A06",
                title="Insecure Deserialization via pickle",
                severity="Critical",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description="pickle deserializes untrusted data into arbitrary Python objects, allowing remote code execution.",
                remediation="Use safer serialization formats such as json, msgpack, or protocol buffers.",
            )

        if module_name == "yaml" and func_name in ("unsafe_load", "load"):
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
        if module_name == "hashlib" and func_name in ("md5", "sha1"):
            self._add_vulnerability(
                owasp_code="A02",
                title=f"Use of Weak Hash Algorithm (hashlib.{func_name})",
                severity="Medium",
                line_no=node.lineno,
                snippet=self._get_line_snippet(node.lineno),
                description=f"{func_name.upper()} is cryptographically weak and vulnerable to collision attacks.",
                remediation=f"Use hashlib.sha256() or password hashing libraries like bcrypt or argon2.",
            )

        # A04: Insecure PRNG for Security Contexts (random.random, random.randint)
        if module_name == "random" and func_name in ("random", "randint", "choice", "randrange"):
            # Check if context looks like token generation
            line_str = self._get_line_snippet(node.lineno).lower()
            if any(term in line_str for term in ("token", "key", "secret", "password", "auth", "session")):
                self._add_vulnerability(
                    owasp_code="A04",
                    title="Insecure Pseudo-Random Number Generator for Security Token",
                    severity="Medium",
                    line_no=node.lineno,
                    snippet=self._get_line_snippet(node.lineno),
                    description="Standard random module PRNG is predictable and unsuitable for security credentials.",
                    remediation="Use the cryptographically secure secrets module (e.g. secrets.token_hex()).",
                )

        # A05: SSL/TLS Verification Disabled (verify=False in HTTP requests)
        if func_name in ("get", "post", "put", "delete", "request") and (
            module_name in ("requests", "httpx", "aiohttp") or func_name in ("get", "post")
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
        if module_name in ("requests", "httpx") and func_name in ("get", "post"):
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

    def __init__(self, groq_api_key: str | None = None, model: str = DEFAULT_GROQ_MODEL):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.model = model

    def audit_code(self, code_text: str, filename: str = "<unknown>") -> list[Vulnerability]:
        if not code_text.strip():
            return []

        prompt = f"Filename: {filename}\nSource Code:\n```python\n{code_text}\n```"

        # Attempt 1: Call Groq API if API Key is available
        if self.groq_api_key:
            llm_res = self._call_groq_api(prompt)
            if llm_res:
                return self._parse_llm_json(llm_res, code_text)

        # Attempt 2: Fallback to local Ollama API
        ollama_res = self._call_ollama_api(prompt)
        if ollama_res:
            return self._parse_llm_json(ollama_res, code_text)

        # Attempt 3: No LLM available, return empty list (AST rules serve as baseline)
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

    def _call_ollama_api(self, user_prompt: str) -> str | None:
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

    def _parse_llm_json(self, json_str: str, code_text: str) -> list[Vulnerability]:
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
                    )
                )
        except Exception:
            pass
        return results


# ---------------------------------------------------------------------------
# Scorecard Generator & Core Auditor Logic
# ---------------------------------------------------------------------------

def calculate_security_scorecard(
    ast_vulns: list[Vulnerability],
    llm_vulns: list[Vulnerability],
    filepath: str = "<unknown>",
) -> SecurityScorecard:
    """
    Combines AST and LLM vulnerabilities, deduplicates findings, computes numerical score (0-100),
    determines Pass/Fail status, and maps findings to OWASP categories.
    """
    all_vulns: list[Vulnerability] = []
    seen_keys = set()

    # Add AST findings first
    for v in ast_vulns:
        key = (v.line_number, v.owasp_category, v.title)
        if key not in seen_keys:
            seen_keys.add(key)
            all_vulns.append(v)

    # Add non-duplicate LLM findings
    for v in llm_vulns:
        key = (v.line_number, v.owasp_category, v.title)
        if key not in seen_keys:
            seen_keys.add(key)
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
    code_text: str, filename: str = "<unknown>", groq_api_key: str | None = None
) -> dict[str, Any]:
    """
    Audits a raw string of Python code using both AST rules and Groq LLM auditor.
    Returns AgentResponse-shaped dict.
    """
    scanner = SecurityASTScanner(code_text, filename=filename)
    ast_vulns = scanner.scan()

    llm_auditor = GroqSecurityAuditor(groq_api_key=groq_api_key)
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


def audit_file(filepath: str, groq_api_key: str | None = None) -> dict[str, Any]:
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

    return audit_code_string(code_text, filename=filepath, groq_api_key=groq_api_key)


def audit_retrieved_chunks(
    chunks: Sequence[Chunk | RetrievalResult | dict[str, Any]], groq_api_key: str | None = None
) -> dict[str, Any]:
    """
    Audits a list of retrieved RAG code chunks for security vulnerabilities.
    """
    all_ast_vulns: list[Vulnerability] = []
    all_llm_vulns: list[Vulnerability] = []

    llm_auditor = GroqSecurityAuditor(groq_api_key=groq_api_key)

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

        scanner = SecurityASTScanner(code_text, filename=file_path)
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
