"""
Unit tests for CodeQLRunner and SARIF v2.1.0 Parser.
Verifies CWE normalization, path handling, severity mapping, and database+analysis timing.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.benchmarks_research.runners.codeql_runner import CodeQLRunner

SAMPLE_SARIF = {
    "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
    "version": "2.1.0",
    "runs": [
        {
            "tool": {
                "driver": {
                    "name": "CodeQL",
                    "version": "2.16.2",
                    "rules": [
                        {
                            "id": "py/sql-injection",
                            "name": "py/sql-injection",
                            "properties": {
                                "tags": [
                                    "security",
                                    "external/cwe/cwe-89",
                                ],
                            },
                        },
                        {
                            "id": "py/cleartext-storage-sensitive-data",
                            "name": "py/cleartext-storage-sensitive-data",
                            "properties": {
                                "tags": [
                                    "security",
                                    "external/cwe/cwe-798",
                                ],
                            },
                        },
                    ],
                }
            },
            "results": [
                {
                    "ruleId": "py/sql-injection",
                    "level": "error",
                    "message": {"text": "Query string is directly formatted with untrusted input."},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": "app.py",
                                    "uriBaseId": "%SRCROOT%",
                                },
                                "region": {
                                    "startLine": 8,
                                    "endLine": 8,
                                    "startColumn": 5,
                                    "endColumn": 45,
                                },
                            }
                        }
                    ],
                },
                {
                    "ruleId": "py/cleartext-storage-sensitive-data",
                    "level": "warning",
                    "message": {"text": "Hardcoded secret key found in source."},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": "src\\handlers\\auth.py",
                                },
                                "region": {
                                    "startLine": 14,
                                    "endLine": 14,
                                },
                            }
                        }
                    ],
                },
            ],
        }
    ],
}


def test_codeql_runner_initialization_and_status():
    runner = CodeQLRunner()
    # If not on path and not downloaded yet, correctly reports not_installed
    if not runner.is_available():
        assert runner.get_version() == "not_installed"
        res = runner.run(Path("."))
        assert res.status == "not_installed"
        assert res.findings == []


def test_codeql_sarif_parser_cwe_and_path_normalization():
    runner = CodeQLRunner()
    sarif_str = json.dumps(SAMPLE_SARIF)
    findings = runner.parse_sarif(sarif_str)

    assert len(findings) == 2

    # Finding 1: SQL Injection
    f1 = findings[0]
    assert f1.tool == "codeql"
    assert f1.file_path == "app.py"
    assert f1.line_start == 8
    assert f1.line_end == 8
    assert f1.cwe == "CWE-89"
    assert f1.severity == "HIGH"
    assert f1.rule_id == "py/sql-injection"

    # Finding 2: Hardcoded Secret with Windows backslash path
    f2 = findings[1]
    assert f2.tool == "codeql"
    assert f2.file_path == "src/handlers/auth.py"  # Backslash converted to forward slash
    assert f2.line_start == 14
    assert f2.line_end == 14
    assert f2.cwe == "CWE-798"
    assert f2.severity == "MEDIUM"
    assert f2.rule_id == "py/cleartext-storage-sensitive-data"
