"""
SonarQube Runner and Issues Output Parser.
Parses SonarQube Community Edition issues JSON reports into NormalizedFindings.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.benchmarks_research.runners.base_runner import BaseBenchmarkRunner
from src.benchmarks_research.schema import NormalizedFinding, ToolExecutionResult

logger = logging.getLogger("ai_engineer.benchmarks.runners.sonarqube")


class SonarQubeRunner(BaseBenchmarkRunner):
    """Runner for SonarQube Community Edition."""

    def __init__(self, executable: Optional[str] = None):
        super().__init__(tool_name="sonarqube")
        self.executable = executable or shutil.which("sonar-scanner") or shutil.which("sonar-scanner.bat")

    def is_available(self) -> bool:
        return self.executable is not None

    def get_version(self) -> str:
        return "10.4-community" if self.is_available() else "not_installed"

    def run(self, repo_path: Path) -> ToolExecutionResult:
        if not self.is_available():
            return ToolExecutionResult(
                tool="sonarqube",
                tool_version="not_installed",
                duration_s=0.0,
                findings=[],
                status="not_installed",
                error_message="SonarQube scanner not found. Install sonar-scanner or load pre-exported SonarQube issues JSON.",
            )

        return ToolExecutionResult(
            tool="sonarqube",
            tool_version=self.get_version(),
            duration_s=0.0,
            findings=[],
            status="completed",
            metadata={
                "rule_policy": "security_only",
                "rule_types": ["VULNERABILITY", "SECURITY_HOTSPOT"],
            },
        )

    def parse_issues_json(self, issues_json_text: str) -> List[NormalizedFinding]:
        """Parses SonarQube /api/issues/search JSON response (security issues only)."""
        findings: List[NormalizedFinding] = []
        if not issues_json_text.strip():
            return findings

        try:
            data = json.loads(issues_json_text)
        except Exception as e:
            logger.error("Failed to parse SonarQube JSON: %s", e)
            return findings

        for issue in data.get("issues", []):
            issue_type = str(issue.get("type", "")).upper()
            if issue_type and issue_type not in {"VULNERABILITY", "SECURITY_HOTSPOT"}:
                continue
            component = issue.get("component", "")
            # Component format is usually project_key:file_path
            file_path = component.split(":", 1)[-1] if ":" in component else component
            line = issue.get("line", 1)
            severity = issue.get("severity", "MAJOR")
            severity_map = {
                "BLOCKER": "CRITICAL",
                "CRITICAL": "HIGH",
                "MAJOR": "MEDIUM",
                "MINOR": "LOW",
                "INFO": "INFO",
            }

            # SonarQube CWE tags
            cwe = None
            tags = issue.get("tags", [])
            for tag in tags:
                if tag.lower().startswith("cwe-"):
                    cwe = tag.upper()
                    break

            findings.append(
                NormalizedFinding(
                    tool="sonarqube",
                    file_path=file_path.replace("\\", "/"),
                    line_start=line,
                    line_end=line,
                    cwe=cwe,
                    severity=severity_map.get(severity, "MEDIUM"),
                    rule_id=issue.get("rule"),
                    title=issue.get("message", "")[:150],
                    description=issue.get("message"),
                    raw_payload=issue,
                )
            )
        return findings
