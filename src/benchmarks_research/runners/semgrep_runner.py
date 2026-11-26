"""
Semgrep Runner and JSON Output Parser.
Executes Semgrep OSS via isolated Docker container (semgrep/semgrep:1.74.0)
with pinned local rules, or fallback to local semgrep CLI.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.benchmarks_research.runners.base_runner import BaseBenchmarkRunner
from src.benchmarks_research.schema import NormalizedFinding, ToolExecutionResult

logger = logging.getLogger("ai_engineer.benchmarks.runners.semgrep")

DOCKER_IMAGE = "semgrep/semgrep:1.74.0"
DEFAULT_PINNED_RULES_PATH = (
    Path(__file__).resolve().parents[1] / "rules" / "semgrep" / "python-security"
)


class SemgrepRunner(BaseBenchmarkRunner):
    """Runner for Semgrep OSS using Docker container isolation or local CLI."""

    def __init__(
        self,
        executable: Optional[str] = None,
        docker_image: str = DOCKER_IMAGE,
        rules_path: Optional[Path] = None,
    ):
        super().__init__(tool_name="semgrep")
        self.docker_image = docker_image
        self.rules_path = rules_path or DEFAULT_PINNED_RULES_PATH
        self.docker_executable = shutil.which("docker") or shutil.which("docker.exe")
        self.local_executable = executable or shutil.which("semgrep") or shutil.which("semgrep.cmd")
        self._docker_available: Optional[bool] = None

    def _has_docker(self) -> bool:
        if self._docker_available is not None:
            return self._docker_available
        if not self.docker_executable:
            self._docker_available = False
            return False
        try:
            res = subprocess.run(
                [self.docker_executable, "info"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self._docker_available = (res.returncode == 0)
            return self._docker_available
        except Exception:
            self._docker_available = False
            return False

    def is_available(self) -> bool:
        if self._has_docker():
            return True
        return self.local_executable is not None

    def get_version(self) -> str:
        if self._has_docker():
            return f"1.74.0 (Docker: {self.docker_image})"
        if self.local_executable:
            try:
                res = subprocess.run(
                    [self.local_executable, "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                return res.stdout.strip()
            except Exception:
                return "unknown"
        return "not_installed"

    def run(self, repo_path: Path) -> ToolExecutionResult:
        if not self.is_available():
            if self.docker_executable and not self._has_docker() and not self.local_executable:
                return ToolExecutionResult(
                    tool="semgrep",
                    tool_version="docker_stopped",
                    duration_s=0.0,
                    findings=[],
                    status="docker_not_running",
                    error_message="Docker daemon is not running (start Docker Desktop to run semgrep/semgrep:1.74.0).",
                )
            return ToolExecutionResult(
                tool="semgrep",
                tool_version="not_installed",
                duration_s=0.0,
                findings=[],
                status="not_installed",
                error_message="Semgrep is not installed (neither Docker CLI nor semgrep CLI found).",
            )

        use_docker = self._has_docker()
        abs_repo = repo_path.resolve()
        abs_rules = self.rules_path.resolve()

        if use_docker:
            # Mount target repo read-only to /src, and pinned rules dir read-only to /rules
            repo_posix = abs_repo.as_posix()
            rules_dir_posix = abs_rules.parent.as_posix()
            rules_filename = abs_rules.name

            cmd = [
                self.docker_executable or "docker",
                "run",
                "--rm",
                "--network", "none",
                "-v", f"{repo_posix}:/src:ro",
                "-v", f"{rules_dir_posix}:/rules:ro",
                self.docker_image,
                "semgrep",
                "scan",
                "--config", f"/rules/{rules_filename}",
                "--metrics=off",
                "--time",
                "--json",
                "--quiet",
                "/src",
            ]
        else:
            # Local CLI execution
            cmd = [
                self.local_executable or "semgrep",
                "scan",
                "--config", str(abs_rules) if abs_rules.exists() else "auto",
                "--metrics=off",
                "--time",
                "--json",
                "--quiet",
                str(abs_repo),
            ]

        wall_start = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
            wall_duration = time.perf_counter() - wall_start

            stdout = proc.stdout
            if not stdout.strip() and proc.stderr:
                logger.warning("Semgrep stderr: %s", proc.stderr[:500])

            # Extract internal scan time from Semgrep JSON time profiling to isolate
            # scan execution from container spin-up and volume mount overhead
            scan_duration = None
            try:
                parsed_data = json.loads(stdout)
                t_info = parsed_data.get("time", {})
                profiling = t_info.get("profiling_times", {})
                if "total_time" in profiling and isinstance(profiling["total_time"], (int, float)):
                    scan_duration = float(profiling["total_time"])
                elif "total_time" in t_info and isinstance(t_info["total_time"], (int, float)):
                    scan_duration = float(t_info["total_time"])
                elif "targets" in t_info and isinstance(t_info["targets"], list):
                    scan_duration = sum(float(t.get("run_time", 0.0)) for t in t_info["targets"])
            except Exception:
                pass

            duration = scan_duration if (scan_duration is not None and scan_duration > 0) else wall_duration

            findings = self.parse_json(stdout, abs_repo)
            rules_sha = None
            rules_loaded = 0
            pinned_commit = None
            if abs_rules.exists():
                import hashlib
                import yaml
                if abs_rules.is_dir():
                    h = hashlib.sha256()
                    for rf in sorted(abs_rules.rglob("*.y*ml")):
                        rb = rf.read_bytes()
                        h.update(rb)
                        try:
                            rules_loaded += len((yaml.safe_load(rb.decode("utf-8")) or {}).get("rules", []))
                        except Exception:
                            pass
                    rules_sha = h.hexdigest()[:12]
                    commit_file = abs_rules / "PINNED_COMMIT.txt"
                    if commit_file.exists():
                        pinned_commit = commit_file.read_text(encoding="utf-8").strip()
                else:
                    rules_bytes = abs_rules.read_bytes()
                    rules_sha = hashlib.sha256(rules_bytes).hexdigest()[:12]
                    try:
                        rules_loaded = len((yaml.safe_load(rules_bytes.decode("utf-8")) or {}).get("rules", []))
                    except Exception:
                        pass

            files_scanned = 0
            lines_scanned = 0
            try:
                parsed_out = json.loads(stdout) if stdout.strip() else {}
                scanned = parsed_out.get("paths", {}).get("scanned", [])
                files_scanned = len(scanned)
                for sp in scanned:
                    sp_norm = sp.replace("\\", "/")
                    if sp_norm.startswith("/src/"):
                        local_p = abs_repo / sp_norm[len("/src/"):]
                    else:
                        local_p = Path(sp)
                    if local_p.is_file():
                        lines_scanned += len(local_p.read_text(encoding="utf-8", errors="ignore").splitlines())
            except Exception:
                pass

            container_startup_s = max(0.0, wall_duration - duration) if use_docker else 0.0
            return ToolExecutionResult(
                tool="semgrep",
                tool_version=self.get_version(),
                duration_s=duration,
                findings=findings,
                status="completed",
                metadata={
                    "rule_policy": "security_only",
                    "rules_file": abs_rules.name,
                    "rules_commit": pinned_commit,
                    "rules_sha256": rules_sha,
                    "execution_mode": "docker" if use_docker else "local_cli",
                    "scan_time_s": round(duration, 4),
                    "container_startup_s": round(container_startup_s, 4),
                    "wall_duration_s": round(wall_duration, 4),
                    "files_scanned": files_scanned,
                    "lines_scanned": lines_scanned,
                    "rules_loaded": rules_loaded,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolExecutionResult(
                tool="semgrep",
                tool_version=self.get_version(),
                duration_s=180.0,
                findings=[],
                status="failed",
                error_message="Semgrep scan timed out after 180s.",
            )
        except Exception as e:
            return ToolExecutionResult(
                tool="semgrep",
                tool_version=self.get_version(),
                duration_s=0.0,
                findings=[],
                status="failed",
                error_message=str(e),
            )

    def parse_json(self, json_text: str, base_path: Optional[Path] = None) -> List[NormalizedFinding]:
        """Parses Semgrep standard JSON output and normalizes file paths and CWEs."""
        findings: List[NormalizedFinding] = []
        if not json_text.strip():
            return findings

        try:
            data = json.loads(json_text)
        except Exception as e:
            logger.error("Failed to parse Semgrep JSON: %s", e)
            return findings

        results = data.get("results", [])
        for item in results:
            raw_path = item.get("path", "").replace("\\", "/")

            # Strip Docker container path prefixes (/src/ or src/)
            if raw_path.startswith("/src/"):
                clean_path = raw_path[5:]
            elif raw_path.startswith("src/"):
                clean_path = raw_path[4:]
            elif raw_path in ("/src", "src"):
                clean_path = ""
            else:
                clean_path = raw_path

            if base_path:
                try:
                    p = Path(clean_path)
                    if p.is_absolute():
                        clean_path = p.relative_to(base_path).as_posix()
                except Exception:
                    pass

            start_line = item.get("start", {}).get("line", 1)
            end_line = item.get("end", {}).get("line", start_line)
            extra = item.get("extra", {})
            metadata = extra.get("metadata", {})

            # Extract CWE
            cwe = None
            raw_cwe = metadata.get("cwe")
            if isinstance(raw_cwe, list) and raw_cwe:
                cwe = str(raw_cwe[0]).split(":")[0].strip()
            elif isinstance(raw_cwe, str):
                cwe = raw_cwe.split(":")[0].strip()

            severity = extra.get("severity", "MEDIUM").upper()

            findings.append(
                NormalizedFinding(
                    tool="semgrep",
                    file_path=clean_path,
                    line_start=start_line,
                    line_end=end_line,
                    cwe=cwe,
                    severity=severity,
                    rule_id=item.get("check_id"),
                    title=extra.get("message", "").split("\n")[0][:150],
                    description=extra.get("message"),
                    raw_payload=item,
                )
            )
        return findings
