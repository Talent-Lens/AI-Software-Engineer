"""
Automatic Candidate-Line Extractor and Noise Filter.
Parses git diff between parent (vulnerable) and fix (clean) commits,
extracts ground-truth vulnerability candidates with strict noise filtering.
"""
from __future__ import annotations

import ast
import io
import logging
import os
import re
import subprocess
import textwrap
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.benchmarks_research.scope import (
    DEFAULT_EXCLUDED_DIR_PARTS,
    DEFAULT_EXCLUDED_EXTENSIONS,
    DEFAULT_EXCLUDED_FILE_NAMES,
    DEFAULT_SCOPE_POLICY,
    SUPPORTED_SOURCE_EXTENSIONS,
    count_in_scope_loc,
)

logger = logging.getLogger("ai_engineer.benchmarks.diff_extractor")

# Aliases preserved for backward compatibility
IGNORED_DIR_PARTS = DEFAULT_EXCLUDED_DIR_PARTS
IGNORED_FILE_EXTENSIONS = DEFAULT_EXCLUDED_EXTENSIONS
IGNORED_FILE_NAMES = DEFAULT_EXCLUDED_FILE_NAMES


@dataclass
class DiffHunkCandidate:
    file_path: str
    line_start: int
    line_end: int
    deleted_lines: List[str]
    added_lines: List[str]
    add_line_start: int = 1
    add_line_end: int = 1
    del_count: int = 0
    add_count: int = 0
    is_noise: bool = False
    noise_reason: Optional[str] = None


@dataclass
class ExtractedGroundTruth:
    repo_name: str
    vulnerable_sha: str
    clean_sha: str
    language: str
    loc: int
    labeled_findings: List[Dict[str, Any]] = field(default_factory=list)
    clean_negative_regions: List[Dict[str, Any]] = field(default_factory=list)
    ignored_candidates: List[Dict[str, Any]] = field(default_factory=list)
    needs_attention: bool = False
    attention_reason: Optional[str] = None


class DiffExtractor:
    """Extracts vulnerable candidate lines from a commit diff with noise filtering."""

    @staticmethod
    def is_noise_file(file_path: str) -> Tuple[bool, Optional[str]]:
        """Determines if a file is non-source or ignored under the unified source-scope policy."""
        in_scope, reason = DEFAULT_SCOPE_POLICY.is_in_scope(file_path)
        return (not in_scope), reason

    @staticmethod
    def is_line_comment_or_import_or_whitespace(line: str, language: str) -> bool:
        """Determines if a line is a comment, import statement, or blank/whitespace."""
        s = line.strip()
        if not s:
            return True

        # Comments
        if s.startswith("#") or s.startswith("//") or s.startswith("/*") or s.startswith("*"):
            return True

        # Python imports
        if language == "python":
            if s.startswith("import ") or s.startswith("from "):
                return True

        # JS/TS imports
        if language in ("javascript", "typescript"):
            if s.startswith("import ") or s.startswith("export ") or s.startswith("const ") and "require(" in s:
                return True

        return False

    @staticmethod
    def _python_non_executable_lines(source: str) -> Set[int]:
        """
        Uses Python's AST and tokenize modules (not regexes) to identify all
        line numbers in `source` that belong strictly to comments, docstrings/
        standalone string expressions, imports, blank lines, or whitespace.
        """
        lines = source.splitlines()
        non_exec: Set[int] = {idx for idx, ln in enumerate(lines, start=1) if not ln.strip()}

        # 1. AST: docstrings / standalone string expressions and import statements
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                is_docstring_expr = (
                    isinstance(node, ast.Expr)
                    and isinstance(getattr(node, "value", None), ast.Constant)
                    and isinstance(node.value.value, str)
                )
                is_import = isinstance(node, (ast.Import, ast.ImportFrom))
                if is_docstring_expr or is_import:
                    start_ln = getattr(node, "lineno", None)
                    end_ln = getattr(node, "end_lineno", start_ln)
                    if start_ln is not None and end_ln is not None:
                        non_exec.update(range(start_ln, end_ln + 1))
        except SyntaxError:
            pass

        # 2. Tokenize: lines containing only non-code tokens (comments/NL/whitespace)
        code_tokens_by_line: Dict[int, Set[int]] = {}
        non_code_toks = {
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENCODING,
            tokenize.ENDMARKER,
        }
        try:
            for tok in tokenize.generate_tokens(io.StringIO(source).readline):
                s_line = tok.start[0]
                e_line = tok.end[0]
                if tok.type not in non_code_toks:
                    for ln in range(s_line, e_line + 1):
                        code_tokens_by_line.setdefault(ln, set()).add(tok.type)
        except tokenize.TokenError:
            pass

        for idx in range(1, len(lines) + 1):
            if idx not in code_tokens_by_line:
                non_exec.add(idx)

        return non_exec

    @classmethod
    def _is_python_snippet_non_executable(cls, lines: List[str]) -> bool:
        """Fallback AST/tokenize check on a hunk snippet when full file text is unavailable."""
        if not lines:
            return True
        snippet = textwrap.dedent("\n".join(lines))
        if not snippet.strip():
            return True
        non_exec = cls._python_non_executable_lines(snippet)
        return all(idx in non_exec for idx in range(1, len(lines) + 1))

    @staticmethod
    def _git_show_file(repo_dir: Path, sha: str, rel_path: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", "show", f"{sha}:{rel_path}"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=15,
            )
            if proc.returncode == 0:
                return proc.stdout
        except Exception:
            pass
        return None

    def extract_from_git_repo(
        self,
        repo_dir: Path,
        parent_sha: str,
        fix_sha: str,
        cve_id: Optional[str] = None,
        cwe: Optional[str] = None,
    ) -> ExtractedGroundTruth:
        """
        Executes git diff between parent and fix commits, parses hunks,
        and generates automatic ground-truth candidates.
        """
        # Count LOC in parent commit
        loc = self._count_loc(repo_dir, parent_sha)

        # Detect primary language
        primary_lang = self._detect_language(repo_dir)

        # Run git diff -U0 parent fix
        cmd = ["git", "diff", "-U0", f"{parent_sha}", f"{fix_sha}"]
        try:
            proc = subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, check=False)
            diff_text = proc.stdout
        except Exception as e:
            logger.error("Failed to execute git diff: %s", e)
            return ExtractedGroundTruth(
                repo_name=repo_dir.name,
                vulnerable_sha=parent_sha,
                clean_sha=fix_sha,
                language=primary_lang,
                loc=loc,
                needs_attention=True,
                attention_reason=f"Failed to generate git diff: {e}",
            )

        # Load parent & fix Python sources for AST/tokenize hunk filtering
        parent_sources: Dict[str, str] = {}
        fix_sources: Dict[str, str] = {}
        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                rel_f = line[6:].strip().replace("\\", "/")
                if rel_f.endswith(".py") and rel_f not in fix_sources:
                    p_src = self._git_show_file(repo_dir, parent_sha, rel_f)
                    f_src = self._git_show_file(repo_dir, fix_sha, rel_f)
                    if p_src is not None:
                        parent_sources[rel_f] = p_src
                    if f_src is not None:
                        fix_sources[rel_f] = f_src

        hunk_candidates, ignored = self._parse_diff_hunks(
            diff_text, primary_lang, parent_sources=parent_sources, fix_sources=fix_sources
        )

        from src.benchmarks_research.scope import validate_and_normalize_cwe
        safe_cwe = validate_and_normalize_cwe(cwe, strict=False) or "unknown"

        labeled_findings: List[Dict[str, Any]] = []
        for idx, cand in enumerate(hunk_candidates):
            finding_id = f"GT-{cve_id or 'AUTO'}-{idx + 1:03d}"
            notes = (
                f"Auto-extracted from fix commit {fix_sha[:8]}. "
                f"Changed {len(cand.deleted_lines)} line(s) in {cand.file_path}."
            )
            labeled_findings.append({
                "id": finding_id,
                "file": cand.file_path,
                "line_start": cand.line_start,
                "line_end": cand.line_end,
                "cwe": safe_cwe,
                "severity": "HIGH",
                "label": "vulnerable",
                "source": "cve-fix-auto",
                "notes": notes,
                "deleted_lines": cand.deleted_lines,
                "added_lines": cand.added_lines,
            })

        # Needs attention validation: minimum candidate lines check
        needs_attention = False
        attention_reason = None
        if len(labeled_findings) < 1:
            needs_attention = True
            attention_reason = (
                f"Fix commit {fix_sha[:8]} yielded 0 candidate source lines after noise filtering "
                f"({len(ignored)} changes filtered as non-code/comments/tests)."
            )

        return ExtractedGroundTruth(
            repo_name=repo_dir.name,
            vulnerable_sha=parent_sha,
            clean_sha=fix_sha,
            language=primary_lang,
            loc=loc,
            labeled_findings=labeled_findings,
            ignored_candidates=ignored,
            needs_attention=needs_attention,
            attention_reason=attention_reason,
        )

    def _parse_diff_hunks(
        self,
        diff_text: str,
        language: str,
        parent_sources: Optional[Dict[str, str]] = None,
        fix_sources: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[DiffHunkCandidate], List[Dict[str, Any]]]:
        """Parses unified diff output into candidate vulnerable line spans and ignored items."""
        hunks: List[DiffHunkCandidate] = []
        ignored: List[Dict[str, Any]] = []

        current_file: Optional[str] = None
        current_hunk: Optional[DiffHunkCandidate] = None

        hunk_header_re = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")

        lines = diff_text.splitlines()
        for line in lines:
            if line.startswith("diff --git "):
                current_file = None
                current_hunk = None
                continue

            if line.startswith("--- a/"):
                current_file = line[6:].strip()
                continue

            if line.startswith("+++ b/"):
                if not current_file:
                    current_file = line[6:].strip()
                continue

            if line.startswith("@@ "):
                m = hunk_header_re.match(line)
                if m and current_file:
                    del_start = int(m.group(1))
                    del_count = int(m.group(2)) if m.group(2) is not None else 1
                    add_start = int(m.group(3))
                    add_count = int(m.group(4)) if m.group(4) is not None else 1

                    # Vulnerable line span is the deleted range in parent commit
                    # If del_count == 0 (pure insertion), use del_start as anchor
                    line_start = del_start if del_count > 0 else max(del_start, 1)
                    line_end = (del_start + del_count - 1) if del_count > 0 else line_start
                    a_start = add_start if add_count > 0 else max(add_start, 1)
                    a_end = (add_start + add_count - 1) if add_count > 0 else a_start

                    current_hunk = DiffHunkCandidate(
                        file_path=current_file.replace("\\", "/"),
                        line_start=line_start,
                        line_end=line_end,
                        deleted_lines=[],
                        added_lines=[],
                        add_line_start=a_start,
                        add_line_end=a_end,
                        del_count=del_count,
                        add_count=add_count,
                    )
                    hunks.append(current_hunk)
                continue

            if current_hunk:
                if line.startswith("-") and not line.startswith("---"):
                    current_hunk.deleted_lines.append(line[1:])
                elif line.startswith("+") and not line.startswith("+++"):
                    current_hunk.added_lines.append(line[1:])

        # Apply Noise Filtering
        parent_non_exec_cache: Dict[str, Set[int]] = {}
        fix_non_exec_cache: Dict[str, Set[int]] = {}
        valid_candidates: List[DiffHunkCandidate] = []
        for h in hunks:
            is_noise, reason = self.is_noise_file(h.file_path)
            if is_noise:
                ignored.append({
                    "file": h.file_path,
                    "line_start": h.line_start,
                    "reason": reason,
                })
                continue

            if h.file_path.endswith(".py") or language == "python":
                p_src = (parent_sources or {}).get(h.file_path)
                f_src = (fix_sources or {}).get(h.file_path)
                if p_src is not None:
                    p_non = parent_non_exec_cache.setdefault(h.file_path, self._python_non_executable_lines(p_src))
                    del_trivial = (h.del_count == 0) or all(
                        ln in p_non for ln in range(h.line_start, h.line_end + 1)
                    )
                else:
                    del_trivial = self._is_python_snippet_non_executable(h.deleted_lines)

                if f_src is not None:
                    f_non = fix_non_exec_cache.setdefault(h.file_path, self._python_non_executable_lines(f_src))
                    add_trivial = (h.add_count == 0) or all(
                        ln in f_non for ln in range(h.add_line_start, h.add_line_end + 1)
                    )
                else:
                    add_trivial = self._is_python_snippet_non_executable(h.added_lines)

                if del_trivial and add_trivial:
                    ignored.append({
                        "file": h.file_path,
                        "line_start": h.line_start,
                        "reason": "AST/tokenize noise filter: comments, docstrings, imports, or whitespace only",
                    })
                    continue
            else:
                all_deleted_trivial = all(
                    self.is_line_comment_or_import_or_whitespace(l, language) for l in h.deleted_lines
                )
                all_added_trivial = all(
                    self.is_line_comment_or_import_or_whitespace(l, language) for l in h.added_lines
                )
                if all_deleted_trivial and all_added_trivial:
                    ignored.append({
                        "file": h.file_path,
                        "line_start": h.line_start,
                        "reason": "Whitespace/comment/import-only change",
                    })
                    continue

            valid_candidates.append(h)

        return valid_candidates, ignored

    @staticmethod
    def _count_loc(repo_dir: Path, commit_sha: str) -> int:
        """Counts in-scope source lines of code in the repo at the given commit."""
        loc, _ = count_in_scope_loc(repo_dir, DEFAULT_SCOPE_POLICY)
        return max(loc, 1)

    @staticmethod
    def _detect_language(repo_dir: Path) -> str:
        """Detects the primary programming language of the repository."""
        counts: Dict[str, int] = {}
        for p in repo_dir.rglob("*"):
            if p.is_file() and p.suffix in SUPPORTED_SOURCE_EXTENSIONS:
                lang = SUPPORTED_SOURCE_EXTENSIONS[p.suffix]
                counts[lang] = counts.get(lang, 0) + 1
        if not counts:
            return "python"
        return max(counts, key=counts.get)
