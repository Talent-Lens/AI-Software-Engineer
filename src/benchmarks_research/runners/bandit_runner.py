"""
Bandit Security Scanner Runner (Reference Baseline Line).
Maintained strictly as an optional Python baseline line, NEVER as the benchmark judge.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.benchmarks_research.runners.base_runner import BaseBenchmarkRunner
from src.benchmarks_research.schema import NormalizedFinding, ToolExecutionResult

logger = logging.getLogger("ai_engineer.benchmarks.runners.bandit")


class BanditRunner(BaseBenchmarkRunner):
    """Bandit SAST tool runner for Python baseline comparison."""

    def __init__(self):
        super().__init__(tool_name="bandit")

    def is_available(self) -> bool:
        try:
            import bandit  # noqa: F401
            return True
        except ImportError:
            return False

    def get_version(self) -> str:
        try:
            import bandit
            return getattr(bandit, "__version__", "1.8.6")
        except Exception:
            return "unknown"

    def run(self, repo_path: Path) -> ToolExecutionResult:
        if not self.is_available():
            return ToolExecutionResult(
                tool="bandit",
                tool_version="not_installed",
                duration_s=0.0,
                findings=[],
                status="not_installed",
                error_message="Bandit is not installed in the Python environment.",
            )

        has_python_files = any(repo_path.rglob("*.py"))
        if not has_python_files:
            return ToolExecutionResult(
                tool="bandit",
                tool_version=self.get_version(),
                duration_s=0.0,
                findings=[],
                status="completed",
                error_message="No Python files found in repository.",
            )

        cmd = [
            sys.executable, "-m", "bandit",
            "-r", str(repo_path),
            "-f", "json",
            "-q",
            "-s", "B101",
            "--exclude", ".git,node_modules,venv,.venv,__pycache__",
        ]

        start_time = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=90)
            duration = time.perf_counter() - start_time
            findings = self.parse_json(proc.stdout, repo_path)
            files_scanned = 0
            lines_scanned = 0
            rules_loaded = 0
            try:
                raw_json = json.loads(proc.stdout) if proc.stdout.strip() else {}
                metrics = raw_json.get("metrics", {})
                totals = metrics.get("_totals", {})
                lines_scanned = int(totals.get("loc", 0) or 0)
                files_scanned = sum(1 for k in metrics.keys() if k != "_totals")
            except Exception:
                pass
            try:
                from bandit.core.extension_loader import MANAGER
                rules_loaded = sum(1 for p in MANAGER.plugins if getattr(p.plugin, "_test_id", "") != "B101")
            except Exception:
                pass
            return ToolExecutionResult(
                tool="bandit",
                tool_version=self.get_version(),
                duration_s=duration,
                findings=findings,
                status="completed",
                metadata={
                    "rule_policy": "security_only",
                    "skipped_rules": ["B101"],
                    "files_scanned": files_scanned,
                    "lines_scanned": lines_scanned,
                    "rules_loaded": rules_loaded,
                },
            )
        except Exception as e:
            return ToolExecutionResult(
                tool="bandit",
                tool_version=self.get_version(),
                duration_s=0.0,
                findings=[],
                status="failed",
                error_message=str(e),
            )

    def parse_json(self, json_text: str, base_path: Optional[Path] = None) -> List[NormalizedFinding]:
        findings: List[NormalizedFinding] = []
        if not json_text.strip():
            return findings

        try:
            data = json.loads(json_text)
        except Exception:
            first_brace = json_text.find("{")
            last_brace = json_text.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                try:
                    data = json.loads(json_text[first_brace:last_brace + 1])
                except Exception:
                    return findings
            else:
                return findings

        for result in data.get("results", []):
            filename = result.get("filename", "")
            if base_path:
                try:
                    p = Path(filename)
                    if p.is_absolute():
                        filename = p.relative_to(base_path).as_posix()
                except Exception:
                    pass

            cwe_info = result.get("issue_cwe", {})
            cwe_id = f"CWE-{cwe_info.get('id')}" if cwe_info.get("id") else None
            if not cwe_id or result.get("test_id") == "B101":
                continue

            findings.append(
                NormalizedFinding(
                    tool="bandit",
                    file_path=filename.replace("\\", "/"),
                    line_start=result.get("line_number", 1),
                    line_end=result.get("line_number", 1),
                    cwe=cwe_id,
                    severity=result.get("issue_severity", "MEDIUM").upper(),
                    rule_id=result.get("test_id"),
                    title=result.get("issue_text", "")[:150],
                    description=result.get("issue_text"),
                    raw_payload=result,
                )
            )
        return findings
