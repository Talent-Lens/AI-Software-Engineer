"""
Subprocess Execution Sandbox — runs generated unit test suites inside an
isolated, ephemeral Docker container sandbox with strict resource limits,
network isolation, read-only root filesystem, and zero host secret leakage.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

SANDBOX_IMAGE = "codesandbox-runner:latest"
DOCKERFILE_NAME = "sandbox.Dockerfile"


def _resolve_docker_binary() -> str:
    """
    Locates the Docker CLI executable, searching system PATH and standard
    installation paths on Windows, Linux, and macOS.
    """
    path = shutil.which("docker")
    if path:
        return path

    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe"),
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        "/usr/local/bin/docker",
        "/usr/bin/docker",
    ]
    for c in candidates:
        if os.path.isfile(c):
            # Ensure Docker directory is in process PATH for credential helpers
            d = os.path.dirname(c)
            if d not in os.environ.get("PATH", ""):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            return c

    raise RuntimeError(
        "Docker CLI not found. Docker must be installed and running to securely execute tests in isolation."
    )


def check_docker_available(docker_bin: str | None = None) -> None:
    """
    Verifies that the Docker daemon is active and responsive.
    Raises RuntimeError if Docker is not available.
    """
    if docker_bin is None:
        docker_bin = _resolve_docker_binary()

    try:
        res = subprocess.run(
            [docker_bin, "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            err = res.stderr.strip() or "Docker daemon is not running or accessible."
            raise RuntimeError(f"Docker daemon is not accessible: {err}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker daemon check timed out after 10 seconds.")
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Failed to communicate with Docker daemon: {e}")


def ensure_sandbox_image(
    docker_bin: str | None = None,
    image_name: str = SANDBOX_IMAGE,
) -> None:
    """
    Checks if the sandbox Docker image exists locally.
    If not, builds it automatically from sandbox.Dockerfile.
    """
    if docker_bin is None:
        docker_bin = _resolve_docker_binary()

    inspect_res = subprocess.run(
        [docker_bin, "image", "inspect", image_name],
        capture_output=True,
        text=True,
    )
    if inspect_res.returncode == 0:
        return

    # Find sandbox.Dockerfile in repository root
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    dockerfile_path = os.path.join(repo_root, DOCKERFILE_NAME)
    if not os.path.exists(dockerfile_path):
        dockerfile_path = os.path.abspath(DOCKERFILE_NAME)
        if not os.path.exists(dockerfile_path):
            raise RuntimeError(
                f"Cannot build sandbox image: {DOCKERFILE_NAME} not found at {dockerfile_path}"
            )
        repo_root = os.path.dirname(dockerfile_path)

    build_res = subprocess.run(
        [docker_bin, "build", "-f", dockerfile_path, "-t", image_name, repo_root],
        capture_output=True,
        text=True,
    )
    if build_res.returncode != 0:
        raise RuntimeError(
            f"Failed to build sandbox image {image_name}: {build_res.stderr.strip()}"
        )


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
    Executes `test_code` against `source_filepath` inside an isolated,
    ephemeral Docker container sandbox.

    Enforces:
      - Disposable container (--rm)
      - Zero network access (--network none)
      - Memory cap (--memory 256m)
      - CPU cap (--cpus 0.5)
      - Process limit (--pids-limit 64)
      - Non-root user (--user 1000:1000)
      - Read-only root filesystem (--read-only)
      - Dedicated in-memory /tmp (--tmpfs /tmp:rw,noexec,nosuid,size=64m)
      - Isolated volume mount (-v host_dir:/sandbox:rw)
      - Clean environment (no host secrets/environment variables)

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
    # 1. Config flag check
    enable_sandbox_env = os.environ.get("ENABLE_SANDBOX", "true").strip().lower()
    if enable_sandbox_env in ("false", "0", "no"):
        return {
            "status": "ERROR",
            "exit_code": -1,
            "passed_count": 0,
            "failed_count": 0,
            "duration": 0.0,
            "stdout": "",
            "stderr": "Sandbox execution is disabled",
            "error_traceback": "Sandbox execution is disabled",
        }

    # 2. Source file check
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

    # 3. Docker availability check & image assurance
    docker_bin = _resolve_docker_binary()
    check_docker_available(docker_bin)
    ensure_sandbox_image(docker_bin, SANDBOX_IMAGE)

    # 4. Prepare isolated temporary directory with source and test files
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
        header = "import sys\nimport os\nsys.path.insert(0, '/sandbox')\n"
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
        container_name = f"sandbox_{uuid.uuid4().hex[:12]}"
        mount_path = os.path.abspath(tmpdir)

        # 5. Build secure docker run command
        cmd = [
            docker_bin, "run",
            "--name", container_name,
            "--rm",
            "--network", "none",
            "--memory", "256m",
            "--cpus", "0.5",
            "--pids-limit", "64",
            "--user", "1000:1000",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-v", f"{mount_path}:/sandbox:rw",
            "-w", "/sandbox",
            SANDBOX_IMAGE,
            "pytest", test_filename, "-v", "--tb=short", "-o", "cache_dir=/tmp/.pytest_cache",
        ]

        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode

        except subprocess.TimeoutExpired:
            # Force stop and remove container on timeout
            subprocess.run([docker_bin, "kill", container_name], capture_output=True)
            subprocess.run([docker_bin, "rm", "-f", container_name], capture_output=True)
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
