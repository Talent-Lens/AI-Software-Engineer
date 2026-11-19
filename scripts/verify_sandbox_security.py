"""
Verification Script for Docker Sandbox Isolation (Issue 1)
Tests all security boundaries:
 1. Normal Test Execution (PASSED / FAILED)
 2. Host Secret Leakage Prevention (Environment Isolation)
 3. Network Isolation (Zero Internet Access)
 4. Filesystem Boundary (No Host File Traversal)
 5. Timeout & Infinite Loop Protection
"""

import os
import sys
import tempfile

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sandbox.runner import execute_tests_in_sandbox


def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_1_normal_execution():
    print_header("Test 1: Functional Test Execution (Pass & Fail)")

    # 1a. Passing test
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def calculate(x, y):\n    return x * y + 10\n")
        f.flush()
        test_code = "def test_calculate():\n    assert calculate(5, 2) == 20\n"
        res = execute_tests_in_sandbox(f.name, test_code)

    assert res["status"] == "PASSED", f"Expected PASSED, got {res['status']}"
    assert res["passed_count"] == 1
    print("  [PASS] Passing test executed cleanly inside Docker (Status: PASSED)")

    # 1b. Failing test
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def calculate(x, y):\n    return x * y + 10\n")
        f.flush()
        test_code = "def test_calculate():\n    assert calculate(5, 2) == 999\n"
        res = execute_tests_in_sandbox(f.name, test_code)

    assert res["status"] == "FAILED", f"Expected FAILED, got {res['status']}"
    assert res["failed_count"] == 1
    assert res["error_traceback"] is not None
    print("  [PASS] Failing test correctly caught with traceback (Status: FAILED)")


def test_2_secret_isolation():
    print_header("Test 2: Host Secret / Environment Isolation")

    # Set mock host secrets
    os.environ["OPENAI_API_KEY"] = "sk-mock-secret-host-key-12345"
    os.environ["DATABASE_URL"] = "postgresql://user:password@internal-db:5432/prod"

    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def is_safe():\n    return True\n")
            f.flush()

            test_code = """
import os

def test_no_host_secrets():
    assert 'OPENAI_API_KEY' not in os.environ, 'CRITICAL: Host OPENAI_API_KEY leaked!'
    assert 'DATABASE_URL' not in os.environ, 'CRITICAL: Host DATABASE_URL leaked!'
"""
            res = execute_tests_in_sandbox(f.name, test_code)

        assert res["status"] == "PASSED", f"Host secret test failed: {res}"
        print("  [PASS] Host API keys and Database URLs are 100% invisible inside Docker!")
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("DATABASE_URL", None)


def test_3_network_isolation():
    print_header("Test 3: Network Isolation (--network none)")

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def ping():\n    return 'pong'\n")
        f.flush()

        test_code = """
import urllib.request
import socket
import pytest

def test_outbound_http_blocked():
    with pytest.raises(Exception):
        urllib.request.urlopen('http://1.1.1.1', timeout=2)

def test_raw_socket_blocked():
    with pytest.raises(Exception):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(('8.8.8.8', 53))
"""
        res = execute_tests_in_sandbox(f.name, test_code)

    assert res["status"] == "PASSED", f"Network isolation failed: {res}"
    print("  [PASS] All outbound HTTP and socket traffic is blocked by Docker (--network none)")


def test_4_filesystem_jail():
    print_header("Test 4: Filesystem Jail & Read-Only Root")

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def check_fs():\n    return True\n")
        f.flush()

        test_code = """
import os
import pytest

def test_host_filesystem_invisible():
    # Attempt to locate host paths outside /sandbox
    assert not os.path.exists('D:\\\\AI-Software-Engineer')
    assert not os.path.exists('C:\\\\Users')

def test_root_filesystem_read_only():
    # Attempting to write into container root (/etc, /usr, /root) must fail
    with pytest.raises(OSError):
        with open('/usr/malicious_payload.sh', 'w') as f:
            f.write('echo hacked')
"""
        res = execute_tests_in_sandbox(f.name, test_code)

    assert res["status"] == "PASSED", f"Filesystem jail test failed: {res}"
    print("  [PASS] Host files are invisible; container root is strictly read-only!")


def test_5_timeout_infinite_loop():
    print_header("Test 5: Timeout & Infinite Loop Protection")

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def loop():\n    while True:\n        pass\n")
        f.flush()

        test_code = "def test_loop():\n    loop()\n"
        # Run with short 3-second timeout
        res = execute_tests_in_sandbox(f.name, test_code, timeout_seconds=3)

    assert res["status"] == "TIMEOUT", f"Expected TIMEOUT, got {res['status']}"
    print(f"  [PASS] Infinite loop killed by Docker sandbox after {res['duration']}s (Status: TIMEOUT)")


if __name__ == "__main__":
    print("\nStarting In-Depth Sandbox Security Verification...")
    test_1_normal_execution()
    test_2_secret_isolation()
    test_3_network_isolation()
    test_4_filesystem_jail()
    test_5_timeout_infinite_loop()

    print("\n" + "=" * 60)
    print("  ALL 5 DEEP SECURITY TESTS PASSED SUCCESSFULLY! ")
    print("=" * 60 + "\n")

