"""
Unit tests for Diff Extractor and Noise Filter (src/benchmarks/diff_extractor.py)
"""
import pytest
from src.benchmarks_research.diff_extractor import DiffExtractor


def test_noise_file_filtering():
    extractor = DiffExtractor()

    # Excluded directories
    is_noise, reason = extractor.is_noise_file("tests/test_auth.py")
    assert is_noise is True
    assert "Test file" in reason or "Excluded directory" in reason

    is_noise, _ = extractor.is_noise_file("docs/index.md")
    assert is_noise is True

    is_noise, _ = extractor.is_noise_file("package-lock.json")
    assert is_noise is True

    # Valid source file
    is_noise, _ = extractor.is_noise_file("app/auth/views.py")
    assert is_noise is False

    is_noise, _ = extractor.is_noise_file("src/controllers/userController.js")
    assert is_noise is False


def test_noise_line_filtering():
    extractor = DiffExtractor()

    # Comments and whitespace
    assert extractor.is_line_comment_or_import_or_whitespace("   # This is a comment", "python") is True
    assert extractor.is_line_comment_or_import_or_whitespace("   // JS comment", "javascript") is True
    assert extractor.is_line_comment_or_import_or_whitespace("      ", "python") is True

    # Imports
    assert extractor.is_line_comment_or_import_or_whitespace("import os, sys", "python") is True
    assert extractor.is_line_comment_or_import_or_whitespace("from flask import request", "python") is True

    # Real code
    assert extractor.is_line_comment_or_import_or_whitespace("query = f'SELECT * FROM users WHERE id={user_id}'", "python") is False
    assert extractor.is_line_comment_or_import_or_whitespace("yaml.load(payload)", "python") is False


def test_parse_diff_hunks_extraction():
    extractor = DiffExtractor()

    sample_diff = """diff --git a/app/views.py b/app/views.py
index abc1234..def5678 100644
--- a/app/views.py
+++ b/app/views.py
@@ -45,3 +45,3 @@ def login():
-    query = "SELECT * FROM users WHERE user = '" + username + "'"
-    cursor.execute(query)
+    query = "SELECT * FROM users WHERE user = %s"
+    cursor.execute(query, (username,))
diff --git a/docs/changelog.md b/docs/changelog.md
index 1111111..2222222 100644
--- a/docs/changelog.md
+++ b/docs/changelog.md
@@ -10,1 +10,1 @@
-Fixed bug in login
+Fixed security vulnerability
"""

    hunks, ignored = extractor._parse_diff_hunks(sample_diff, "python")

    # The doc file should be in ignored
    assert len(ignored) >= 1
    assert any("changelog.md" in item["file"] for item in ignored)

    # The vulnerable source hunk in app/views.py should be kept
    assert len(hunks) == 1
    assert hunks[0].file_path == "app/views.py"
    assert hunks[0].line_start == 45
    assert len(hunks[0].deleted_lines) == 2
    assert "SELECT * FROM users" in hunks[0].deleted_lines[0]
