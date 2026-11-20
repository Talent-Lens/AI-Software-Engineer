"""
Extended AST Pattern Registry for Bug, Security, and Code Smell Detection.

Provides 20+ additional AST-based patterns that complement the
``SecurityASTScanner`` in ``src/agents/security_auditor.py``.  Every check
runs deterministically over a Python ``ast`` tree — no network calls, no
external dependencies beyond the standard library.

Usage::

    from src.analysis.pattern_registry import scan_extended_patterns

    matches = scan_extended_patterns(source_code, filename="app.py")
    for m in matches:
        print(f"[{m.pattern_id}] {m.title} @ line {m.line_number}")
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PatternMatch",
    "PatternScanner",
    "scan_extended_patterns",
]

# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class PatternMatch:
    """A single finding produced by the extended pattern scanner."""

    pattern_id: str        # e.g., "PY-BUG-001"
    category: str          # "bug", "security", "code_smell"
    title: str
    severity: str          # "Critical", "High", "Medium", "Low", "Info"
    line_number: int
    code_snippet: str
    description: str
    remediation: str
    owasp_code: str | None = None  # Only for security patterns

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "category": self.category,
            "title": self.title,
            "severity": self.severity,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "description": self.description,
            "remediation": self.remediation,
            "owasp_code": self.owasp_code,
        }


# ---------------------------------------------------------------------------
# Built-in names to detect shadowing (PY-BUG-006)
# ---------------------------------------------------------------------------

_BUILTIN_NAMES: frozenset[str] = frozenset({
    "list", "dict", "set", "tuple", "str", "int", "float", "bool",
    "type", "id", "input", "print", "len", "range", "map", "filter",
    "zip", "open", "file", "dir", "hash", "hex", "max", "min", "sum",
    "abs", "any", "all", "next", "iter", "format", "object", "super",
    "property", "staticmethod", "classmethod",
})

# Sensitive variable names for PY-SEC-004 (logging sensitive data)
_SENSITIVE_NAMES: frozenset[str] = frozenset({
    "password", "passwd", "pwd", "secret", "token", "api_key",
    "apikey", "secret_key", "private_key", "auth_token", "credential",
    "credentials", "ssn", "credit_card",
})

# IPv4 regex for PY-SEC-008 (hardcoded IP addresses)
_IPV4_RE = re.compile(
    r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
)

# Localhost / loopback addresses that are acceptable
_LOCALHOST_IPS: frozenset[str] = frozenset({
    "127.0.0.1", "0.0.0.0",  # 0.0.0.0 handled separately by PY-SEC-002
})


# ---------------------------------------------------------------------------
# AST Pattern Scanner
# ---------------------------------------------------------------------------

class PatternScanner(ast.NodeVisitor):
    """Extended AST pattern scanner covering bugs, security issues, and code smells.

    Each pattern is implemented as a private ``_check_*`` method that is
    invoked from the appropriate ``visit_*`` hook.  Matches are collected
    in ``self.matches``.
    """

    def __init__(self, code_text: str, filename: str = "<unknown>"):
        self.code_text = code_text
        self.code_lines = code_text.splitlines()
        self.filename = filename
        self.matches: list[PatternMatch] = []

        # Track context for some patterns
        self._in_finally: bool = False
        self._open_call_lines: set[int] = set()  # lines with bare open()

    # -- helpers -------------------------------------------------------------

    def _get_line(self, lineno: int) -> str:
        """Return source line text (1-indexed) or empty string."""
        if 1 <= lineno <= len(self.code_lines):
            return self.code_lines[lineno - 1]
        return ""

    def _add(
        self,
        pattern_id: str,
        category: str,
        title: str,
        severity: str,
        lineno: int,
        description: str,
        remediation: str,
        owasp_code: str | None = None,
    ) -> None:
        self.matches.append(
            PatternMatch(
                pattern_id=pattern_id,
                category=category,
                title=title,
                severity=severity,
                line_number=lineno,
                code_snippet=self._get_line(lineno).strip(),
                description=description,
                remediation=remediation,
                owasp_code=owasp_code,
            )
        )

    @staticmethod
    def _func_full_name(node: ast.Call) -> tuple[str, str]:
        """Return ``(module_name, func_name)`` for a call node."""
        func = node.func
        if isinstance(func, ast.Name):
            return ("", func.id)
        if isinstance(func, ast.Attribute):
            parts: list[str] = [func.attr]
            current: ast.expr = func.value
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            parts.reverse()
            return (".".join(parts[:-1]), parts[-1])
        return ("", "")

    @staticmethod
    def _is_constant(node: ast.expr, value: object = ...) -> bool:
        """Check if *node* is an ``ast.Constant`` optionally matching *value*."""
        if not isinstance(node, ast.Constant):
            return False
        if value is ...:
            return True
        return node.value is value or node.value == value

    # -----------------------------------------------------------------------
    # Visitor hooks
    # -----------------------------------------------------------------------

    def scan(self) -> list[PatternMatch]:
        """Parse *code_text* and run every pattern check.  Returns matches."""
        self.matches.clear()
        try:
            tree = ast.parse(self.code_text, filename=self.filename)
        except SyntaxError:
            return self.matches

        # First pass: collect bare open() call lines for PY-BUG-003
        self._collect_open_calls(tree)

        # Main visitor pass
        self.visit(tree)

        # Post-pass: check string constants for hardcoded IPs (PY-SEC-008)
        self._check_hardcoded_ips(tree)

        return self.matches

    # -- Pre-pass helpers ----------------------------------------------------

    def _collect_open_calls(self, tree: ast.Module) -> None:
        """Identify ``open()`` calls that are NOT inside a ``with`` statement."""
        with_targets: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.With):
                for item in node.items:
                    ctx_expr = item.context_expr
                    if isinstance(ctx_expr, ast.Call):
                        with_targets.add(id(ctx_expr))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                _, fname = self._func_full_name(node)
                if fname == "open" and id(node) not in with_targets:
                    self._open_call_lines.add(node.lineno)

    # -----------------------------------------------------------------------
    # Bug Patterns (PY-BUG-*)
    # -----------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._check_mutable_default(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_mutable_default(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """PY-BUG-001: Mutable default argument."""
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(
                    "PY-BUG-001", "bug",
                    "Mutable default argument",
                    "Medium",
                    default.lineno,
                    (
                        "Using a mutable object (list, dict, or set) as a default "
                        "argument causes all calls to share the same instance, "
                        "leading to unexpected data sharing between invocations."
                    ),
                    "Use None as the default and create the mutable inside the "
                    "function body: `if x is None: x = []`.",
                )

    # -- Assert for validation (PY-BUG-002) ---------------------------------

    def visit_Assert(self, node: ast.Assert) -> None:
        self._check_assert_validation(node)
        self.generic_visit(node)

    def _check_assert_validation(self, node: ast.Assert) -> None:
        """PY-BUG-002: ``assert`` used for data validation."""
        # Heuristic: assert with a comparison or call that looks like validation
        test = node.test
        is_validation = isinstance(test, (ast.Compare, ast.Call, ast.BoolOp))
        if is_validation:
            self._add(
                "PY-BUG-002", "bug",
                "Assert used for data validation",
                "Medium",
                node.lineno,
                (
                    "`assert` statements are stripped when Python runs with "
                    "the -O (optimize) flag, so using them for input/data "
                    "validation can silently skip critical checks in production."
                ),
                "Replace with an explicit `if not <cond>: raise ValueError(...)` "
                "or use a validation library.",
            )

    # -- open() without context manager (PY-BUG-003) -------------------------

    def visit_Call(self, node: ast.Call) -> None:
        self._check_open_without_with(node)
        self._check_broad_builtin_shadow_call(node)
        self._check_tempfile_mktemp(node)
        self._check_bind_all_interfaces(node)
        self._check_redos_risk(node)
        self._check_logging_sensitive(node)
        self._check_chmod_world_writable(node)
        self._check_xml_parse(node)
        self._check_jwt_decode(node)
        self._check_flask_send_file(node)
        self._check_cookie_flags(node)
        self.generic_visit(node)

    def _check_open_without_with(self, node: ast.Call) -> None:
        """PY-BUG-003: ``open()`` without context manager — resource leak."""
        if node.lineno in self._open_call_lines:
            _, fname = self._func_full_name(node)
            if fname == "open":
                self._add(
                    "PY-BUG-003", "bug",
                    "open() without context manager",
                    "Medium",
                    node.lineno,
                    (
                        "Calling `open()` without a `with` statement risks "
                        "leaving the file handle open if an exception occurs, "
                        "causing resource leaks."
                    ),
                    "Use a context manager: `with open(path) as f: ...`.",
                )

    # -- Broad exception (PY-BUG-004) / Empty except (PY-BUG-007) -----------

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._check_broad_exception(node)
        self._check_empty_except(node)
        self.generic_visit(node)

    def _check_broad_exception(self, node: ast.ExceptHandler) -> None:
        """PY-BUG-004: Catching too broad exception."""
        if node.type is None:
            # bare `except:` — even broader
            self._add(
                "PY-BUG-004", "bug",
                "Bare except clause catches all exceptions",
                "High",
                node.lineno,
                (
                    "A bare `except:` clause catches every exception including "
                    "`KeyboardInterrupt` and `SystemExit`, making it very "
                    "difficult to diagnose errors."
                ),
                "Catch specific exception types, e.g. `except ValueError:`.",
            )
            return

        name = ""
        if isinstance(node.type, ast.Name):
            name = node.type.id
        elif isinstance(node.type, ast.Attribute):
            name = node.type.attr

        if name in ("Exception", "BaseException"):
            self._add(
                "PY-BUG-004", "bug",
                f"Catching overly broad '{name}'",
                "Medium",
                node.lineno,
                (
                    f"Catching `{name}` may mask unrelated errors and make "
                    "debugging difficult.  Prefer catching specific exceptions."
                ),
                "Catch the narrowest applicable exception type(s).",
            )

    def _check_empty_except(self, node: ast.ExceptHandler) -> None:
        """PY-BUG-007: Empty ``except`` block (pass only, swallowing errors)."""
        body = node.body
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            self._add(
                "PY-BUG-007", "bug",
                "Empty except block silently swallows errors",
                "Medium",
                node.lineno,
                (
                    "An `except` block that contains only `pass` silently "
                    "swallows exceptions, hiding bugs and making failures "
                    "invisible."
                ),
                "At minimum, log the exception: `except SomeError as e: "
                "logger.exception(e)`.",
            )

    # -- Comparison with None/True/False using == (PY-BUG-005) ---------------

    def visit_Compare(self, node: ast.Compare) -> None:
        self._check_identity_comparison(node)
        self.generic_visit(node)

    def _check_identity_comparison(self, node: ast.Compare) -> None:
        """PY-BUG-005: Comparison using ``==`` with ``None``, ``True``, ``False``."""
        singletons = {None, True, False}
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)):
                if self._is_constant(comparator) and comparator.value in singletons:
                    val_repr = repr(comparator.value)
                    op_str = "==" if isinstance(op, ast.Eq) else "!="
                    is_str = "is" if isinstance(op, ast.Eq) else "is not"
                    self._add(
                        "PY-BUG-005", "bug",
                        f"Comparison to {val_repr} using '{op_str}' instead of '{is_str}'",
                        "Low",
                        node.lineno,
                        (
                            f"Comparing to `{val_repr}` with `{op_str}` checks "
                            f"equality rather than identity.  Singletons should be "
                            f"compared using `{is_str}`."
                        ),
                        f"Use `x {is_str} {val_repr}` instead of `x {op_str} {val_repr}`.",
                    )

    # -- Shadowing built-in names (PY-BUG-006) -------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_builtin_shadow_assign(node)
        self.generic_visit(node)

    def _check_builtin_shadow_assign(self, node: ast.Assign) -> None:
        """PY-BUG-006: Shadowing built-in names via assignment."""
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in _BUILTIN_NAMES:
                self._add(
                    "PY-BUG-006", "bug",
                    f"Shadowing built-in name '{target.id}'",
                    "Low",
                    node.lineno,
                    (
                        f"Assigning to `{target.id}` shadows the built-in "
                        f"`{target.id}`, which can cause subtle bugs when "
                        f"other code tries to use the original built-in."
                    ),
                    f"Choose a more descriptive variable name, e.g. "
                    f"`{target.id}_value` or `my_{target.id}`.",
                )

    def _check_broad_builtin_shadow_call(self, node: ast.Call) -> None:
        """PY-BUG-006 supplement: detect ``for`` target shadowing is already
        covered in visit_For, but we skip call-based checks here to avoid
        false positives."""
        pass  # Placeholder; assignment-based detection is the primary check.

    # -- Return in finally (PY-BUG-008) --------------------------------------

    def visit_Try(self, node: ast.Try) -> None:
        # Check finalbody for return/break/continue statements
        if node.finalbody:
            self._check_return_in_finally(node.finalbody, node)
        self.generic_visit(node)

    def _check_return_in_finally(self, stmts: list[ast.stmt], try_node: ast.Try) -> None:
        """PY-BUG-008: ``return`` in ``finally`` block swallows exceptions."""
        for stmt in ast.walk(ast.Module(body=stmts, type_ignores=[])):
            if isinstance(stmt, (ast.Return, ast.Break, ast.Continue)):
                kind = type(stmt).__name__.lower()
                self._add(
                    "PY-BUG-008", "bug",
                    f"'{kind}' inside finally block",
                    "High",
                    stmt.lineno,
                    (
                        f"A `{kind}` statement inside a `finally` block "
                        "silently swallows any active exception, making errors "
                        "disappear without a trace."
                    ),
                    f"Move the `{kind}` outside of the `finally` block, or "
                    "restructure the logic to avoid it.",
                )

    # -- Star import (PY-BUG-009) --------------------------------------------

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._check_star_import(node)
        self.generic_visit(node)

    def _check_star_import(self, node: ast.ImportFrom) -> None:
        """PY-BUG-009: ``from module import *`` namespace pollution."""
        if node.names and any(alias.name == "*" for alias in node.names):
            module = node.module or "<unknown>"
            self._add(
                "PY-BUG-009", "bug",
                f"Star import from '{module}'",
                "Low",
                node.lineno,
                (
                    f"`from {module} import *` imports every public name, "
                    "polluting the local namespace, making it unclear where "
                    "names come from, and risking accidental name collisions."
                ),
                "Import only the names you need: "
                f"`from {module} import name1, name2`.",
            )

    # -- Unreachable code (PY-BUG-010) ---------------------------------------

    def _check_unreachable_code(self, stmts: list[ast.stmt]) -> None:
        """PY-BUG-010: Unreachable code after ``return``/``raise``/``break``/``continue``."""
        terminal_types = (ast.Return, ast.Raise, ast.Break, ast.Continue)
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, terminal_types) and i < len(stmts) - 1:
                next_stmt = stmts[i + 1]
                # Skip if the next statement is a docstring-like expression or
                # another function/class def (which is reachable via name).
                if isinstance(next_stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                kind = type(stmt).__name__.lower()
                self._add(
                    "PY-BUG-010", "bug",
                    f"Unreachable code after '{kind}'",
                    "Low",
                    next_stmt.lineno,
                    (
                        f"Code after a `{kind}` statement is unreachable and "
                        "will never execute.  This is likely a bug or leftover "
                        "dead code."
                    ),
                    "Remove the unreachable code or restructure the logic.",
                )
                break  # Only report the first unreachable statement per block

    # Hook into every compound statement body that can contain sequences
    def visit_Module(self, node: ast.Module) -> None:
        self._check_unreachable_code(node.body)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._check_unreachable_code(node.body)
        self._check_unreachable_code(node.orelse)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._check_unreachable_code(node.body)
        # Check for built-in shadowing in for-loop target
        if isinstance(node.target, ast.Name) and node.target.id in _BUILTIN_NAMES:
            self._add(
                "PY-BUG-006", "bug",
                f"Shadowing built-in name '{node.target.id}'",
                "Low",
                node.lineno,
                (
                    f"Using `{node.target.id}` as a loop variable shadows the "
                    f"built-in `{node.target.id}`."
                ),
                f"Choose a different loop variable name.",
            )
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_unreachable_code(node.body)
        self.generic_visit(node)

    # -----------------------------------------------------------------------
    # Security Patterns (PY-SEC-*)
    # -----------------------------------------------------------------------

    # -- tempfile.mktemp() race condition (PY-SEC-001) -----------------------

    def _check_tempfile_mktemp(self, node: ast.Call) -> None:
        """PY-SEC-001: ``tempfile.mktemp()`` — TOCTOU race condition."""
        mod, func = self._func_full_name(node)
        if func == "mktemp" and ("tempfile" in mod or mod == ""):
            # If bare name, still flag since the pattern is dangerous
            if mod or func == "mktemp":
                self._add(
                    "PY-SEC-001", "security",
                    "Use of tempfile.mktemp() — race condition",
                    "High",
                    node.lineno,
                    (
                        "`tempfile.mktemp()` returns a filename that could be "
                        "claimed by another process before the caller opens it "
                        "(TOCTOU race).  This can be exploited for symlink "
                        "attacks."
                    ),
                    "Use `tempfile.mkstemp()` or `tempfile.NamedTemporaryFile()` "
                    "which atomically create the file.",
                    owasp_code="A05",
                )

    # -- Binding to 0.0.0.0 (PY-SEC-002) ------------------------------------

    def _check_bind_all_interfaces(self, node: ast.Call) -> None:
        """PY-SEC-002: Server binding to ``0.0.0.0``."""
        mod, func = self._func_full_name(node)
        if func in ("bind", "run", "listen"):
            for arg in node.args:
                if self._is_constant(arg) and isinstance(arg.value, str):
                    if "0.0.0.0" in arg.value:
                        self._add(
                            "PY-SEC-002", "security",
                            "Server binding to 0.0.0.0 — exposed to all interfaces",
                            "Medium",
                            node.lineno,
                            (
                                "Binding to `0.0.0.0` makes the service "
                                "accessible on every network interface, "
                                "including public ones, which may not be "
                                "intended."
                            ),
                            "Bind to `127.0.0.1` (localhost) unless external "
                            "access is explicitly required, and use firewall "
                            "rules to restrict access.",
                            owasp_code="A05",
                        )
                        return
            for kw in node.keywords:
                if kw.arg == "host" and self._is_constant(kw.value):
                    if isinstance(kw.value.value, str) and "0.0.0.0" in kw.value.value:
                        self._add(
                            "PY-SEC-002", "security",
                            "Server binding to 0.0.0.0 — exposed to all interfaces",
                            "Medium",
                            node.lineno,
                            (
                                "Binding to `0.0.0.0` makes the service "
                                "accessible on every network interface."
                            ),
                            "Bind to `127.0.0.1` unless external access is "
                            "required.",
                            owasp_code="A05",
                        )
                        return

    # -- ReDoS risk (PY-SEC-003) ---------------------------------------------

    def _check_redos_risk(self, node: ast.Call) -> None:
        """PY-SEC-003: ``re.compile()``/``re.match()`` with non-literal pattern — ReDoS."""
        mod, func = self._func_full_name(node)
        if mod in ("re", "") and func in ("compile", "match", "search", "findall", "sub", "fullmatch"):
            if node.args:
                pattern_arg = node.args[0]
                # Flag when the first arg is a variable (potential user input)
                if isinstance(pattern_arg, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
                    # Also flag f-strings or format calls
                    self._add(
                        "PY-SEC-003", "security",
                        f"Regex function re.{func}() with non-literal pattern — ReDoS risk",
                        "Medium",
                        node.lineno,
                        (
                            f"The pattern argument to `re.{func}()` comes from "
                            "a variable rather than a string literal.  If the "
                            "pattern is user-controlled, an attacker can craft "
                            "a pattern that causes catastrophic backtracking "
                            "(ReDoS)."
                        ),
                        "Use a hardcoded pattern, set `re.TIMEOUT` (Python "
                        "3.11+), or validate/sanitize the pattern before "
                        "compiling.",
                        owasp_code="A03",
                    )
                elif isinstance(pattern_arg, (ast.JoinedStr, ast.BinOp)):
                    self._add(
                        "PY-SEC-003", "security",
                        f"Regex function re.{func}() with dynamically built pattern — ReDoS risk",
                        "Medium",
                        node.lineno,
                        (
                            f"The pattern argument to `re.{func}()` is "
                            "dynamically constructed (f-string or concatenation). "
                            "If any component is user-controlled, this enables "
                            "ReDoS attacks."
                        ),
                        "Use `re.escape()` on user-supplied parts and prefer "
                        "static patterns.",
                        owasp_code="A03",
                    )

    # -- Logging sensitive data (PY-SEC-004) ---------------------------------

    def _check_logging_sensitive(self, node: ast.Call) -> None:
        """PY-SEC-004: ``logging.debug(password)`` — logging sensitive data."""
        mod, func = self._func_full_name(node)
        log_funcs = {"debug", "info", "warning", "error", "critical", "exception", "log"}
        if func in log_funcs and ("logging" in mod or "logger" in mod or "log" in mod):
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id.lower() in _SENSITIVE_NAMES:
                    self._add(
                        "PY-SEC-004", "security",
                        f"Logging potentially sensitive variable '{arg.id}'",
                        "High",
                        node.lineno,
                        (
                            f"Variable `{arg.id}` appears to contain sensitive "
                            "data and is being passed to a logging call.  Log "
                            "output may be stored in plaintext, exposed to "
                            "unauthorized users, or shipped to third-party "
                            "services."
                        ),
                        "Redact or mask sensitive data before logging, e.g. "
                        "`logger.debug('token=***')`.",
                        owasp_code="A09",
                    )
            # Also check f-string args containing sensitive names
            for arg in node.args:
                if isinstance(arg, ast.JoinedStr):
                    for val in arg.values:
                        if isinstance(val, ast.FormattedValue) and isinstance(val.value, ast.Name):
                            if val.value.id.lower() in _SENSITIVE_NAMES:
                                self._add(
                                    "PY-SEC-004", "security",
                                    f"Logging sensitive variable '{val.value.id}' in f-string",
                                    "High",
                                    node.lineno,
                                    (
                                        f"Sensitive variable `{val.value.id}` is "
                                        "interpolated into a log message via "
                                        "f-string."
                                    ),
                                    "Remove sensitive data from log messages or "
                                    "mask it before logging.",
                                    owasp_code="A09",
                                )

    # -- chmod 0o777 / world-writable (PY-SEC-005) ---------------------------

    def _check_chmod_world_writable(self, node: ast.Call) -> None:
        """PY-SEC-005: ``chmod(0o777)`` — world-writable file permissions."""
        mod, func = self._func_full_name(node)
        if func == "chmod" and ("os" in mod or mod == ""):
            if node.args and len(node.args) >= 2:
                mode_arg = node.args[1]
                if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, int):
                    mode = mode_arg.value
                    # Check if world-writable (others write bit set)
                    if mode & 0o002:
                        self._add(
                            "PY-SEC-005", "security",
                            f"World-writable file permissions (mode {oct(mode)})",
                            "High",
                            node.lineno,
                            (
                                f"Setting file permissions to `{oct(mode)}` "
                                "makes the file writable by any user on the "
                                "system, which can lead to unauthorized "
                                "modification or code injection."
                            ),
                            "Use restrictive permissions such as `0o644` "
                            "(owner read/write, group/others read-only) or "
                            "`0o600` (owner only).",
                            owasp_code="A01",
                        )

    # -- XML parsing without defusing (PY-SEC-006) ---------------------------

    def _check_xml_parse(self, node: ast.Call) -> None:
        """PY-SEC-006: ``xml.etree.ElementTree.parse`` — XXE risk."""
        mod, func = self._func_full_name(node)
        # Check for xml.etree, xml.dom, xml.sax
        unsafe_xml_modules = {
            "xml.etree.ElementTree", "xml.etree.cElementTree",
            "xml.dom.minidom", "xml.dom.pulldom", "xml.sax",
            "ElementTree", "cElementTree", "minidom",
            "ET",
        }
        parse_funcs = {"parse", "fromstring", "iterparse", "parseString", "XMLParser"}
        if func in parse_funcs:
            if mod in unsafe_xml_modules or (
                mod == "" and func in ("parse", "fromstring")
            ):
                self._add(
                    "PY-SEC-006", "security",
                    f"XML parsing with {mod}.{func}() — potential XXE vulnerability",
                    "High",
                    node.lineno,
                    (
                        "The standard library XML parsers are vulnerable to "
                        "XML External Entity (XXE) attacks, billion laughs, "
                        "and other XML-based attacks by default."
                    ),
                    "Use `defusedxml` library instead: "
                    "`import defusedxml.ElementTree as ET`.",
                    owasp_code="A03",
                )

    # -- jwt.decode with verify=False (PY-SEC-007) ---------------------------

    def _check_jwt_decode(self, node: ast.Call) -> None:
        """PY-SEC-007: ``jwt.decode()`` with ``verify=False`` or ``algorithms=["none"]``."""
        mod, func = self._func_full_name(node)
        if func == "decode" and ("jwt" in mod or mod == "jwt" or mod == ""):
            for kw in node.keywords:
                # verify=False
                if kw.arg == "verify" and self._is_constant(kw.value, False):
                    self._add(
                        "PY-SEC-007", "security",
                        "JWT decoded with verify=False — signature bypass",
                        "Critical",
                        node.lineno,
                        (
                            "Decoding a JWT with `verify=False` disables "
                            "signature verification, allowing any forged "
                            "token to be accepted."
                        ),
                        "Always verify JWT signatures: "
                        "`jwt.decode(token, key, algorithms=['HS256'])`.",
                        owasp_code="A02",
                    )
                    return
                # options={"verify_signature": False}
                if kw.arg == "options" and isinstance(kw.value, ast.Dict):
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if (self._is_constant(k) and
                                k.value == "verify_signature" and
                                self._is_constant(v, False)):
                            self._add(
                                "PY-SEC-007", "security",
                                "JWT decoded with verify_signature=False — signature bypass",
                                "Critical",
                                node.lineno,
                                (
                                    "Decoding a JWT with "
                                    "`options={'verify_signature': False}` "
                                    "disables signature verification."
                                ),
                                "Remove `verify_signature: False` from options "
                                "and provide a valid signing key.",
                                owasp_code="A02",
                            )
                            return
                # algorithms=["none"]
                if kw.arg == "algorithms" and isinstance(kw.value, ast.List):
                    for elt in kw.value.elts:
                        if self._is_constant(elt) and isinstance(elt.value, str):
                            if elt.value.lower() == "none":
                                self._add(
                                    "PY-SEC-007", "security",
                                    'JWT decoded with algorithms=["none"] — no signature',
                                    "Critical",
                                    node.lineno,
                                    (
                                        "Using the `none` algorithm means the "
                                        "JWT has no signature at all, allowing "
                                        "anyone to forge tokens."
                                    ),
                                    "Use a secure algorithm such as `HS256` or "
                                    "`RS256`.",
                                    owasp_code="A02",
                                )
                                return

    # -- Hardcoded IP addresses (PY-SEC-008) — post-pass ---------------------

    def _check_hardcoded_ips(self, tree: ast.Module) -> None:
        """PY-SEC-008: Hardcoded non-localhost IP addresses in string constants."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for match in _IPV4_RE.finditer(node.value):
                    ip = match.group(1)
                    if ip in _LOCALHOST_IPS:
                        continue
                    # Skip common version strings (e.g., "1.0.0") and
                    # documentation examples
                    octets = ip.split(".")
                    try:
                        nums = [int(o) for o in octets]
                    except ValueError:
                        continue
                    if all(0 <= n <= 255 for n in nums):
                        self._add(
                            "PY-SEC-008", "security",
                            f"Hardcoded IP address '{ip}'",
                            "Low",
                            getattr(node, "lineno", 0),
                            (
                                f"The IP address `{ip}` is hardcoded in a "
                                "string constant.  Hardcoded IPs make the "
                                "application inflexible and can leak internal "
                                "network topology."
                            ),
                            "Use configuration files, environment variables, or "
                            "DNS names instead of hardcoded IP addresses.",
                            owasp_code="A05",
                        )

    # -- flask.send_file with user path (PY-SEC-009) -------------------------

    def _check_flask_send_file(self, node: ast.Call) -> None:
        """PY-SEC-009: ``flask.send_file()`` with user-controlled path."""
        mod, func = self._func_full_name(node)
        if func == "send_file" and ("flask" in mod or mod == ""):
            if node.args:
                path_arg = node.args[0]
                # Flag if path comes from a variable (potential user input)
                if isinstance(path_arg, (ast.Name, ast.Subscript, ast.Attribute, ast.Call)):
                    self._add(
                        "PY-SEC-009", "security",
                        "flask.send_file() with potentially user-controlled path",
                        "High",
                        node.lineno,
                        (
                            "`send_file()` is called with a dynamic argument "
                            "that may be user-controlled.  An attacker could "
                            "use path traversal (e.g., `../../etc/passwd`) to "
                            "read arbitrary files from the server."
                        ),
                        "Use `flask.send_from_directory()` with a fixed base "
                        "directory, and validate/sanitize the filename with "
                        "`werkzeug.utils.secure_filename()`.",
                        owasp_code="A01",
                    )
                elif isinstance(path_arg, (ast.JoinedStr, ast.BinOp)):
                    self._add(
                        "PY-SEC-009", "security",
                        "flask.send_file() with dynamically built path",
                        "High",
                        node.lineno,
                        (
                            "`send_file()` is called with a dynamically "
                            "constructed path (f-string or concatenation), "
                            "which may allow path traversal attacks."
                        ),
                        "Use `flask.send_from_directory()` with a fixed base "
                        "directory.",
                        owasp_code="A01",
                    )

    # -- Missing httponly/secure on cookies (PY-SEC-010) ---------------------

    def _check_cookie_flags(self, node: ast.Call) -> None:
        """PY-SEC-010: Missing ``httponly``/``secure`` flags on cookie setting."""
        mod, func = self._func_full_name(node)
        if func == "set_cookie":
            kw_names = {kw.arg for kw in node.keywords if kw.arg is not None}

            missing_httponly = "httponly" not in kw_names
            missing_secure = "secure" not in kw_names

            # Also check if explicitly set to False
            for kw in node.keywords:
                if kw.arg == "httponly" and self._is_constant(kw.value, False):
                    missing_httponly = True
                if kw.arg == "secure" and self._is_constant(kw.value, False):
                    missing_secure = True

            if missing_httponly or missing_secure:
                missing: list[str] = []
                if missing_httponly:
                    missing.append("httponly")
                if missing_secure:
                    missing.append("secure")
                flags = ", ".join(missing)
                self._add(
                    "PY-SEC-010", "security",
                    f"Cookie set without {flags} flag(s)",
                    "Medium",
                    node.lineno,
                    (
                        f"The `set_cookie()` call is missing the "
                        f"`{flags}` flag(s).  Without `httponly`, the "
                        "cookie is accessible via JavaScript (XSS risk). "
                        "Without `secure`, the cookie may be sent over "
                        "unencrypted HTTP connections."
                    ),
                    "Set `httponly=True` and `secure=True` on all "
                    "sensitive cookies: "
                    "`response.set_cookie('session', value, "
                    "httponly=True, secure=True)`.",
                    owasp_code="A05",
                )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_extended_patterns(
    code_text: str, filename: str = "<unknown>"
) -> list[PatternMatch]:
    """Scan Python source code for extended bug, security, and code smell patterns.

    Parameters
    ----------
    code_text:
        The raw Python source code to analyse.
    filename:
        Optional filename used in error messages and match metadata.

    Returns
    -------
    list[PatternMatch]
        All pattern matches found.  Returns partial results (possibly empty)
        if the source has syntax errors.
    """
    scanner = PatternScanner(code_text, filename=filename)
    return scanner.scan()
