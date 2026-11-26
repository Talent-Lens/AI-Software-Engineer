"""
Unified Source-Scope Policy for CodeGuardian Benchmarks.

Defines ONE canonical source-scope configuration used identically across:
1. Ground-truth diff extraction & LOC counting
2. Filtered source copy construction for ALL SAST/AI runners
   (CodeGuardian, Semgrep, CodeQL, SonarQube, Bandit)
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

DEFAULT_EXCLUDED_DIR_PARTS: Set[str] = {
    "test", "tests", "testing", "spec", "specs",
    "doc", "docs", "documentation",
    "example", "examples", "sample", "samples",
    "tools", "tool",
    "vendor", "_vendor", "third_party", "externals", "external", "node_modules",
    "benchmarks", "benchmark",
    ".github", ".git",
    "build", "dist", "migrations", "fixtures",
    "venv", ".venv", "__pycache__",
}

DEFAULT_EXCLUDED_DIR_SUBSTRINGS: Tuple[str, ...] = (
    "_vendor",
    "vendor",
    "externals",
    "benchmarks",
    "tests",
    "docs",
    "examples",
)

DEFAULT_EXCLUDED_FILE_GLOBS: Tuple[str, ...] = (
    "test_*.py",
    "*_test.py",
    "*.min.js",
    "*.min.css",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.generated.*",
    "*.g.cs",
    "*.pb.go",
)

DEFAULT_EXCLUDED_EXTENSIONS: Set[str] = {
    ".md", ".rst", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".lock", ".svg", ".png", ".jpg", ".gif", ".ico",
    ".html", ".css", ".scss", ".less",
    ".sh", ".bat", ".ps1", ".cmd",
}

DEFAULT_EXCLUDED_FILE_NAMES: Set[str] = {
    "license", "license.txt", "licence", "readme", "readme.md",
    "changelog", "changelog.md", "changes", "contributing",
    "package-lock.json", "yarn.lock", "cargo.lock", "poetry.lock", "pipfile.lock",
}

SUPPORTED_SOURCE_EXTENSIONS: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".c": "c",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
}


DEFAULT_REQUIRED_TOOLS: Tuple[str, ...] = (
    "codeguardian",
    "semgrep",
    "codeql",
    "bandit",
)


def get_required_tools(override: Optional[Iterable[str]] = None) -> Tuple[str, ...]:
    """
    Returns the configurable set of required benchmark tools.
    SonarQube is excluded from the default required set for now (code kept intact).
    Configurable via BENCHMARK_REQUIRED_TOOLS env var (comma-separated).
    """
    if override is not None:
        return tuple(str(t).strip().lower() for t in override if str(t).strip())
    env_val = os.getenv("BENCHMARK_REQUIRED_TOOLS", "").strip()
    if env_val:
        parsed = tuple(t.strip().lower() for t in env_val.split(",") if t.strip())
        if parsed:
            return parsed
    return DEFAULT_REQUIRED_TOOLS


_CWE_STRICT_RE = re.compile(r"^(?:CWE-)?(\d+)$", re.IGNORECASE)


def validate_and_normalize_cwe(raw_cwe: Optional[str], *, strict: bool = True) -> Optional[str]:
    """
    Strictly validates and normalizes a CWE identifier to 'CWE-<digits>'.
    Never stores raw URLs or arbitrary strings as a CWE.
    If strict=True, raises ValueError on malformed non-empty input.
    If strict=False, returns None on malformed input (caller falls back to 'unknown').
    """
    if raw_cwe is None:
        return None
    cleaned = str(raw_cwe).strip()
    if not cleaned:
        return None
    m = _CWE_STRICT_RE.fullmatch(cleaned)
    if not m:
        if strict:
            raise ValueError(f"Malformed CWE '{raw_cwe}': must match CWE-<digits> (e.g. CWE-94).")
        return None
    return f"CWE-{int(m.group(1))}"


class ScopeExclusionError(ValueError):
    """Raised loudly when a labeled ground-truth file is excluded by the active scope policy."""
    pass


@dataclass
class ScopePolicy:
    """Configurable source-scope policy with per-repo overrides."""
    excluded_dir_parts: Set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDED_DIR_PARTS))
    excluded_file_globs: Tuple[str, ...] = DEFAULT_EXCLUDED_FILE_GLOBS
    excluded_extensions: Set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDED_EXTENSIONS))
    excluded_file_names: Set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDED_FILE_NAMES))
    include_dirs: Set[str] = field(default_factory=set)
    include_paths: Set[str] = field(default_factory=set)

    @classmethod
    def from_override(cls, override: Optional[Dict[str, Any]] = None) -> "ScopePolicy":
        policy = cls()
        if not override:
            return policy
        for d in override.get("extra_exclude_dirs", []) or []:
            policy.excluded_dir_parts.add(str(d).strip().lower())
        for d in override.get("include_dirs", []) or []:
            d_norm = str(d).strip().lower()
            policy.include_dirs.add(d_norm)
            policy.excluded_dir_parts.discard(d_norm)
        for p in override.get("include_paths", []) or []:
            policy.include_paths.add(str(p).replace("\\", "/").strip().lstrip("./").lower())
        extra_globs = [str(g).strip().lower() for g in (override.get("extra_exclude_globs", []) or []) if g]
        if extra_globs:
            policy.excluded_file_globs = tuple(list(policy.excluded_file_globs) + extra_globs)
        return policy

    def is_in_scope(self, rel_path: str) -> Tuple[bool, Optional[str]]:
        """Returns (True, None) if file is in scope, else (False, exclusion_reason)."""
        norm = rel_path.replace("\\", "/").strip().lstrip("./")
        norm_lower = norm.lower()
        parts = norm_lower.split("/")
        filename = parts[-1]
        base_name, ext = os.path.splitext(filename)

        # Explicit per-repo path override wins
        if norm_lower in self.include_paths:
            if ext in SUPPORTED_SOURCE_EXTENSIONS:
                return True, None

        for part in parts[:-1]:
            if part in self.include_dirs:
                continue
            if part in self.excluded_dir_parts or any(sub in part for sub in DEFAULT_EXCLUDED_DIR_SUBSTRINGS):
                return False, f"Excluded directory '{part}': {norm}"

        if filename in self.excluded_file_names or base_name in self.excluded_file_names:
            return False, f"Excluded file name: {filename}"

        for pat in self.excluded_file_globs:
            if fnmatch.fnmatch(filename, pat):
                return False, f"Excluded file pattern '{pat}': {filename}"

        if ext in self.excluded_extensions:
            return False, f"Non-source extension: {ext}"

        if ext not in SUPPORTED_SOURCE_EXTENSIONS:
            return False, f"Unsupported language extension: {ext}"

        return True, None


DEFAULT_SCOPE_POLICY = ScopePolicy()


def compute_scope_policy_hash(policy: Optional[ScopePolicy] = None) -> str:
    """Returns a deterministic 12-char SHA-256 hash of the active ScopePolicy."""
    p = policy or DEFAULT_SCOPE_POLICY
    payload = {
        "excluded_dir_parts": sorted(p.excluded_dir_parts),
        "excluded_file_globs": sorted(p.excluded_file_globs),
        "excluded_extensions": sorted(p.excluded_extensions),
        "excluded_file_names": sorted(p.excluded_file_names),
        "include_dirs": sorted(p.include_dirs),
        "include_paths": sorted(p.include_paths),
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def validate_ground_truth_in_scope(
    labeled_files: Iterable[str],
    policy: ScopePolicy = DEFAULT_SCOPE_POLICY,
) -> None:
    """
    Fails loudly if any labeled ground-truth file would be excluded by the active scope policy.
    Prevents silent 0% recall from scope mismatches.
    """
    excluded: List[str] = []
    for fpath in labeled_files:
        in_scope, reason = policy.is_in_scope(fpath)
        if not in_scope:
            excluded.append(f"{fpath} ({reason})")
    if excluded:
        raise ScopeExclusionError(
            "Labeled ground-truth file(s) excluded by source-scope policy: "
            + "; ".join(excluded)
            + ". Add a per-repo scope_override or adjust the ground-truth manifest."
        )


def count_in_scope_loc(root_dir: Path, policy: ScopePolicy = DEFAULT_SCOPE_POLICY) -> Tuple[int, int]:
    """Counts (in_scope_loc, in_scope_file_count) inside root_dir according to policy."""
    loc = 0
    file_count = 0
    for p in root_dir.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root_dir).as_posix()
        except ValueError:
            continue
        in_scope, _ = policy.is_in_scope(rel)
        if not in_scope:
            continue
        file_count += 1
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as fh:
                loc += sum(1 for _ in fh)
        except OSError:
            pass
    return loc, file_count


def build_filtered_source_copy(
    src_dir: Path,
    dst_dir: Path,
    policy: ScopePolicy = DEFAULT_SCOPE_POLICY,
    labeled_files: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """
    Builds a clean, filtered source-only copy of src_dir in dst_dir containing ONLY in-scope
    source files (preserving exact relative paths).
    All benchmark tools run against dst_dir so every tool sees the exact same file set.
    """
    if labeled_files:
        validate_ground_truth_in_scope(labeled_files, policy)

    dst_dir.mkdir(parents=True, exist_ok=True)
    in_scope_files = 0
    in_scope_loc = 0
    excluded_files = 0

    for p in src_dir.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(src_dir).as_posix()
        except ValueError:
            continue
        in_scope, _ = policy.is_in_scope(rel)
        if not in_scope:
            excluded_files += 1
            continue

        dest_file = dst_dir / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest_file)
        in_scope_files += 1
        try:
            with dest_file.open("r", encoding="utf-8", errors="ignore") as fh:
                in_scope_loc += sum(1 for _ in fh)
        except OSError:
            pass

    return {
        "in_scope_files": in_scope_files,
        "in_scope_loc": in_scope_loc,
        "excluded_files": excluded_files,
        "filtered_dir": str(dst_dir),
    }
