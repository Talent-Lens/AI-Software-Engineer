"""
CodeGuardian Security Scanner Runner.
Executes CodeGuardian's AST + OWASP security auditor without modifying core scanning logic.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List

from src.agents.security_auditor import SecurityASTScanner
from src.benchmarks_research.runners.base_runner import BaseBenchmarkRunner
from src.benchmarks_research.schema import NormalizedFinding, ToolExecutionResult

logger = logging.getLogger("ai_engineer.benchmarks.runners.codeguardian")


class CodeGuardianRunner(BaseBenchmarkRunner):
    """Runner for CodeGuardian's native security engine."""

    def __init__(self):
        super().__init__(tool_name="codeguardian")

    def is_available(self) -> bool:
        return True

    def get_version(self) -> str:
        return "2.1.1-research"

    def run(self, repo_path: Path) -> ToolExecutionResult:
        start_time = time.perf_counter()
        findings: List[NormalizedFinding] = []
        files_scanned = 0
        lines_scanned = 0

        skip_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}

        for py_file in repo_path.rglob("*.py"):
            try:
                rel = py_file.relative_to(repo_path)
            except ValueError:
                continue

            if any(part in skip_dirs for part in rel.parts):
                continue

            rel_posix = rel.as_posix()
            try:
                code = py_file.read_text(encoding="utf-8", errors="ignore")
                files_scanned += 1
                lines_scanned += len(code.splitlines())
                scanner = SecurityASTScanner(code, rel_posix)
                file_vulns = scanner.scan()

                for v in file_vulns:
                    # Map OWASP category to standard CWE where possible
                    cwe_mapped = self._map_owasp_to_cwe(v.owasp_category, v.title)
                    findings.append(
                        NormalizedFinding(
                            tool="codeguardian",
                            file_path=rel_posix,
                            line_start=v.line_number,
                            line_end=v.line_number,
                            cwe=cwe_mapped,
                            severity=v.severity.upper(),
                            rule_id=v.id,
                            title=v.title,
                            description=v.description,
                            raw_payload=v.to_dict(),
                        )
                    )
            except Exception as err:
                logger.debug("CodeGuardian error analyzing %s: %s", py_file, err)

        duration = time.perf_counter() - start_time
        return ToolExecutionResult(
            tool="codeguardian",
            tool_version=self.get_version(),
            duration_s=duration,
            findings=findings,
            status="completed",
            metadata={
                "rule_policy": "security_only",
                "ruleset": "SecurityASTScanner (SAST-*)",
                "llm_calls": 0,
                "files_scanned": files_scanned,
                "lines_scanned": lines_scanned,
                "rules_loaded": 5,
            },
        )

    @staticmethod
    def _map_owasp_to_cwe(owasp: str, title: str) -> str:
        title_lower = title.lower()
        if "sql" in title_lower:
            return "CWE-89"
        if "yaml" in title_lower or "deserial" in title_lower or "pickle" in title_lower:
            return "CWE-502"
        if "md5" in title_lower or "sha1" in title_lower or "random" in title_lower or "crypto" in title_lower:
            return "CWE-327"
        if "password" in title_lower or "secret" in title_lower or "key" in title_lower:
            return "CWE-798"
        if "verify" in title_lower or "ssl" in title_lower:
            return "CWE-295"
        if "dynamic code execution" in title_lower or "eval()" in title_lower or "exec()" in title_lower:
            return "CWE-95"
        if "command" in title_lower or "exec" in title_lower:
            return "CWE-78"
        if "xss" in title_lower or "script" in title_lower:
            return "CWE-79"
        if "traversal" in title_lower or "path" in title_lower:
            return "CWE-22"
        return "CWE-89" if "injection" in owasp.lower() else "CWE-699"
