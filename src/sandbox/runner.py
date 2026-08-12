"""
Subprocess Execution Sandbox — runs generated unit test suites in an isolated
temporary directory sandbox, capturing execution status, stdout/stderr,
and failure tracebacks.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


def _parse_test_output(stdout: str, stderr: str, exit_code: int) -> tuple[int, int, str | None]:
    """
    Parses pytest or unittest stdout/stderr to extract passed count, failed count,
    and failure traceback snippet.
    """
    combined = stdout + "\n" + stderr

    passed = 0
    failed = 0

    # Match pytest summary line e.g., '2 passed, 1 failed in 0.12s' or '3 passed in 0.05s'
    pytest_passed = re.search(r"(\d+)\s+passed", combined)
    pytest_failed = re.search(r"(\d+)\s+(?:failed|error|errors)", combined)

    if pytest_passed:
        passed = int(pytest_passed.group(1))
    if pytest_failed:
        failed = int(pytest_failed.group(1))

    # Match unittest summary line e.g., 'Ran 3 tests in 0.002s ... OK' or 'FAILED (failures=1, errors=1)'
    if not pytest_passed and not pytest_failed:
        unittest_ran = re.search(r"Ran (\d+) test", combined)
        if unittest_ran:
            total_ran = int(unittest_ran.group(1))
            failures_match = re.search(r"failures=(\d+)", combined)
            errors_match = re.search(r"errors=(\d+)", combined)
            failures = int(failures_match.group(1)) if failures_match else 0
            errors = int(errors_match.group(1)) if errors_match else 0

            failed = failures + errors
            passed = max(0, total_ran - failed)

    # Extract traceback if exit_code != 0
    traceback = None
    if exit_code != 0:
        tb_lines = []
        capture = False
        for line in combined.splitlines():
            if any(k in line for k in ("FAIL", "ERROR", "Traceback", "AssertionError", "E   ", "File ")):
                capture = True
            if capture:
                tb_lines.append(line)
                if len(tb_lines) >= 30:
                    break
        traceback = "\n".join(tb_lines) if tb_lines else combined.strip()

    return passed, failed, traceback


def execute_tests_in_sandbox(
    source_filepath: str,
    test_code: str,
    timeout_seconds: int = 30,
) -> dict:
    """
    Executes `test_code` against `source_filepath` inside an isolated temporary directory.

    Returns dict:
      {
        "status": "PASSED" | "FAILED" | "ERROR" | "TIMEOUT",
        "exit_code": int,
        "passed_count": int,
        "failed_count": int,
        "duration": float,
        "stdout": str,
        "stderr": str,
        "error_traceback": str | None
      }
    """
    if not os.path.exists(source_filepath):
        return {
            "status": "ERROR",
            "exit_code": -1,
            "passed_count": 0,
            "failed_count": 0,
            "duration": 0.0,
            "stdout": "",
            "stderr": f"Source file does not exist: {source_filepath}",
            "error_traceback": f"Source file does not exist: {source_filepath}",
        }

    with tempfile.TemporaryDirectory(prefix="test_sandbox_") as tmpdir:
        source_filename = os.path.basename(source_filepath)
        sandbox_source_path = os.path.join(tmpdir, source_filename)
        shutil.copy2(source_filepath, sandbox_source_path)

        # Create __init__.py in sandbox so python imports resolve
        with open(os.path.join(tmpdir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("# Sandbox package\n")

        module_name = os.path.splitext(source_filename)[0]
        test_filename = f"test_{module_name}.py"
        sandbox_test_path = os.path.join(tmpdir, test_filename)

        # Prepend import statement if not already present in generated code
        header = f"import sys\nimport os\nsys.path.insert(0, r'{tmpdir}')\n"
        if f"import {module_name}" not in test_code and f"from {module_name}" not in test_code:
            header += f"from {module_name} import *\n"

        # Universal entry point footer so tests can run via pytest or direct python unittest execution
        footer = (
            "\n\nif __name__ == '__main__':\n"
            "    import unittest, types, sys\n"
            "    suite = unittest.TestSuite()\n"
            "    for name, obj in list(globals().items()):\n"
            "        if name.startswith('test_') and isinstance(obj, types.FunctionType):\n"
            "            suite.addTest(unittest.FunctionTestCase(obj))\n"
            "        elif isinstance(obj, type) and issubclass(obj, unittest.TestCase):\n"
            "            suite.addTest(unittest.makeSuite(obj))\n"
            "    runner = unittest.TextTestRunner(verbosity=2)\n"
            "    result = runner.run(suite)\n"
            "    sys.exit(0 if result.wasSuccessful() else 1)\n"
        )

        full_test_code = header + "\n" + test_code + footer

        with open(sandbox_test_path, "w", encoding="utf-8") as f:
            f.write(full_test_code)

        start_time = time.time()
        env = os.environ.copy()
        env["PYTHONPATH"] = tmpdir + os.pathsep + env.get("PYTHONPATH", "")

        # Try pytest first, fallback to direct python runner
        cmd = [sys.executable, "-m", "pytest", test_filename, "-v", "--tb=short"]

        try:
            process = subprocess.run(
                cmd,
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode

            # Fallback to direct Python runner if pytest is not installed
            if exit_code in (4, 127) or "No module named pytest" in stderr or "No module named pytest" in stdout:
                cmd_direct = [sys.executable, test_filename]
                process = subprocess.run(
                    cmd_direct,
                    cwd=tmpdir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode

        except subprocess.TimeoutExpired:
            duration = round(time.time() - start_time, 3)
            return {
                "status": "TIMEOUT",
                "exit_code": -1,
                "passed_count": 0,
                "failed_count": 0,
                "duration": duration,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout_seconds} seconds.",
                "error_traceback": f"Test sandbox execution timed out after {timeout_seconds} seconds.",
            }
        except Exception as e:
            duration = round(time.time() - start_time, 3)
            return {
                "status": "ERROR",
                "exit_code": -1,
                "passed_count": 0,
                "failed_count": 0,
                "duration": duration,
                "stdout": "",
                "stderr": str(e),
                "error_traceback": str(e),
            }

        duration = round(time.time() - start_time, 3)
        passed_count, failed_count, traceback = _parse_test_output(stdout, stderr, exit_code)
        status = "PASSED" if exit_code == 0 else ("FAILED" if failed_count > 0 or exit_code == 1 else "ERROR")

        return {
            "status": status,
            "exit_code": exit_code,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "duration": duration,
            "stdout": stdout,
            "stderr": stderr,
            "error_traceback": traceback,
        }
