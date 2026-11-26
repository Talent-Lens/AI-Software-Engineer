"""
CodeQL Runner and SARIF Output Parser.
Executes GitHub CodeQL CLI (native on Windows) or parses SARIF 2.1.0 reports into NormalizedFindings.
Measures database creation time and query analysis time separately, summing them for total latency.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.benchmarks_research.runners.base_runner import BaseBenchmarkRunner
from src.benchmarks_research.schema import NormalizedFinding, ToolExecutionResult

logger = logging.getLogger("ai_engineer.benchmarks.runners.codeql")

DEFAULT_QUERY_SUITE = "codeql/python-queries:codeql-suites/python-security-extended.qls"


class CodeQLRunner(BaseBenchmarkRunner):
    """Runner for GitHub CodeQL CLI (native Windows execution, SARIF v2.1.0 output)."""

    def __init__(self, executable: Optional[str] = None, query_suite: str = DEFAULT_QUERY_SUITE):
        super().__init__(tool_name="codeql")
        local_cmd = Path(__file__).resolve().parents[3] / "tools" / "codeql" / "codeql.cmd"
        local_exe = Path(__file__).resolve().parents[3] / "tools" / "codeql" / "codeql.exe"
        discovered = (
            executable
            or shutil.which("codeql")
            or shutil.which("codeql.cmd")
            or shutil.which("codeql.exe")
        )
        if not discovered:
            if local_cmd.exists():
                discovered = str(local_cmd)
            elif local_exe.exists():
                discovered = str(local_exe)
        self.executable = discovered
        self.query_suite = query_suite

    def is_available(self) -> bool:
        return self.executable is not None

    def get_version(self) -> str:
        if not self.is_available():
            return "not_installed"
        try:
            res = subprocess.run(
                [self.executable, "version", "--format=json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            data = json.loads(res.stdout)
            return data.get("version", "unknown")
        except Exception:
            return "unknown"

    def run(self, repo_path: Path) -> ToolExecutionResult:
        if not self.is_available():
            return ToolExecutionResult(
                tool="codeql",
                tool_version="not_installed",
                duration_s=0.0,
                findings=[],
                status="not_installed",
                error_message="CodeQL CLI not found in system PATH. Download CodeQL bundle and add 'codeql' to PATH.",
            )

        abs_repo = repo_path.resolve()

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "codeql_db"
            sarif_path = Path(tmp_dir) / "results.sarif"

            # 1. Database Creation (Pure static AST extraction - never executes repo code)
            create_cmd = [
                self.executable,
                "database", "create",
                str(db_path),
                "--language=python",
                f"--source-root={str(abs_repo)}",
                "--overwrite",
                "--threads=0",
            ]

            t0 = time.perf_counter()
            try:
                proc_create = subprocess.run(
                    create_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300,
                )
                db_build_time = time.perf_counter() - t0
            except subprocess.TimeoutExpired:
                return ToolExecutionResult(
                    tool="codeql",
                    tool_version=self.get_version(),
                    duration_s=300.0,
                    findings=[],
                    status="failed",
                    error_message="CodeQL database create timed out after 300s.",
                )

            if proc_create.returncode != 0:
                logger.error("CodeQL database create failed: %s", proc_create.stderr[:500])
                return ToolExecutionResult(
                    tool="codeql",
                    tool_version=self.get_version(),
                    duration_s=db_build_time,
                    findings=[],
                    status="failed",
                    error_message=f"CodeQL database create failed: {proc_create.stderr[:300]}",
                )

            # 2. Database Analysis (Query pack execution producing SARIF)
            analyze_cmd = [
                self.executable,
                "database", "analyze",
                str(db_path),
                self.query_suite,
                "--threads=0",
                "--format=sarif-latest",
                f"--output={str(sarif_path)}",
            ]

            t1 = time.perf_counter()
            try:
                proc_analyze = subprocess.run(
                    analyze_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=600,
                )
                analysis_time = time.perf_counter() - t1
            except subprocess.TimeoutExpired:
                return ToolExecutionResult(
                    tool="codeql",
                    tool_version=self.get_version(),
                    duration_s=db_build_time + 600.0,
                    findings=[],
                    status="failed",
                    error_message="CodeQL database analyze timed out after 600s.",
                )

            total_duration = db_build_time + analysis_time

            if not sarif_path.exists():
                return ToolExecutionResult(
                    tool="codeql",
                    tool_version=self.get_version(),
                    duration_s=total_duration,
                    findings=[],
                    status="failed",
                    error_message=f"CodeQL analysis failed to produce SARIF: {proc_analyze.stderr[:300]}",
                )

            sarif_text = sarif_path.read_text(encoding="utf-8", errors="ignore")
            findings = self.parse_sarif(sarif_text, abs_repo)

            rules_loaded = 0
            try:
                sarif_data = json.loads(sarif_text)
                runs = sarif_data.get("runs", [])
                if runs:
                    rules_loaded = len(runs[0].get("tool", {}).get("driver", {}).get("rules", []))
            except Exception:
                pass

            py_files = [p for p in abs_repo.rglob("*.py") if p.is_file()]
            files_scanned = len(py_files)
            lines_scanned = sum(len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) for p in py_files)
            db_python_files, db_functions = self._query_db_stats(db_path, Path(tmp_dir))

            return ToolExecutionResult(
                tool="codeql",
                tool_version=self.get_version(),
                duration_s=total_duration,
                findings=findings,
                status="completed",
                metadata={
                    "rule_policy": "security_only",
                    "query_pack": "codeql/python-queries@0.9.8",
                    "query_suite": self.query_suite,
                    "db_build_time_s": round(db_build_time, 3),
                    "analysis_time_s": round(analysis_time, 3),
                    "files_scanned": files_scanned,
                    "lines_scanned": lines_scanned,
                    "rules_loaded": rules_loaded,
                    "db_python_files": db_python_files,
                    "db_functions": db_functions,
                },
            )

    def _query_db_stats(self, db_path: Path, tmp_dir: Path) -> tuple[Optional[int], Optional[int]]:
        """Query the created CodeQL database for extracted Python file and function counts."""
        stats_ql = Path(__file__).resolve().parents[1] / "rules" / "codeql" / "db_stats" / "stats.ql"
        if not stats_ql.exists() or not self.executable:
            return None, None
        bqrs_path = tmp_dir / "db_stats.bqrs"
        try:
            q_res = subprocess.run(
                [self.executable, "query", "run", f"--database={db_path}", f"--output={bqrs_path}", str(stats_ql)],
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            if q_res.returncode != 0 or not bqrs_path.exists():
                return None, None
            dec = subprocess.run(
                [self.executable, "bqrs", "decode", "--format=json", str(bqrs_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if dec.returncode != 0:
                return None, None
            data = json.loads(dec.stdout)
            tuples = data.get("#select", {}).get("tuples", [])
            if tuples and len(tuples[0]) >= 2:
                return int(tuples[0][0]), int(tuples[0][1])
        except Exception:
            pass
        return None, None

    def parse_sarif(self, sarif_text: str, base_path: Optional[Path] = None) -> List[NormalizedFinding]:
        """Parses standard SARIF v2.1.0 output produced by CodeQL."""
        findings: List[NormalizedFinding] = []
        if not sarif_text.strip():
            return findings

        try:
            data = json.loads(sarif_text)
        except Exception as e:
            logger.error("Failed to parse SARIF: %s", e)
            return findings

        runs = data.get("runs", [])
        for run in runs:
            # Map rules for CWE lookup
            rules = {r.get("id"): r for r in run.get("tool", {}).get("driver", {}).get("rules", [])}

            for result in run.get("results", []):
                rule_id = result.get("ruleId")
                rule = rules.get(rule_id, {})
                rule_tags = rule.get("properties", {}).get("tags", [])

                # Extract CWE from tags (e.g. "external/cwe/cwe-89")
                cwe = None
                for tag in rule_tags:
                    if "cwe/cwe-" in tag.lower():
                        parts = tag.lower().split("cwe/cwe-")
                        if len(parts) > 1:
                            cwe = f"CWE-{parts[1].split('/')[0].strip().upper()}"
                            break

                level = result.get("level", "warning").lower()
                severity_map = {"error": "HIGH", "warning": "MEDIUM", "note": "LOW", "none": "INFO"}
                severity = severity_map.get(level, "MEDIUM")

                locations = result.get("locations", [])
                for loc in locations:
                    phys = loc.get("physicalLocation", {})
                    artifact = phys.get("artifactLocation", {})
                    uri = artifact.get("uri", "").replace("\\", "/")

                    # Strip file:// URI prefix if present
                    if uri.startswith("file://"):
                        uri = uri[7:]
                        if uri.startswith("/") and len(uri) > 2 and uri[2] == ":":
                            uri = uri[1:]

                    if base_path:
                        try:
                            p = Path(uri)
                            if p.is_absolute():
                                uri = p.relative_to(base_path).as_posix()
                        except Exception:
                            pass

                    region = phys.get("region", {})
                    start_line = region.get("startLine", 1)
                    end_line = region.get("endLine", start_line)

                    findings.append(
                        NormalizedFinding(
                            tool="codeql",
                            file_path=uri.replace("\\", "/"),
                            line_start=start_line,
                            line_end=end_line,
                            cwe=cwe,
                            severity=severity,
                            rule_id=rule_id,
                            title=result.get("message", {}).get("text", "")[:150],
                            description=result.get("message", {}).get("text"),
                            raw_payload=result,
                        )
                    )
        return findings
