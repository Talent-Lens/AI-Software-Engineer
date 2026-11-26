# src/analysis/taint_tracker.py
"""Intra-file dataflow / taint analysis for Python source code.

Tracks how user-controlled inputs (sources) flow through variables and
function calls to reach dangerous operations (sinks).  Uses the ``ast``
module exclusively — no third-party parsing dependencies.

Typical usage::

    from src.analysis.taint_tracker import analyze_taint

    flows = analyze_taint(source_code, filename="app.py")
    for flow in flows:
        print(f"{flow.source.name} → {flow.sink.name} (line {flow.sink.line})")
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, field
from typing import Iterable

__all__ = [
    "TaintSource",
    "TaintSink",
    "TaintFlow",
    "TaintTracker",
    "analyze_taint",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TaintSource:
    """A user-controlled input entry point."""

    name: str       # e.g. "request.args", "input()"
    line: int
    variable: str   # The variable that holds the tainted value


@dataclass
class TaintSink:
    """A dangerous operation that should not receive tainted data."""

    name: str           # e.g. "cursor.execute", "os.system", "eval"
    line: int
    owasp_code: str     # e.g. "A03"
    severity: str       # "Critical", "High", "Medium", "Low"


@dataclass
class TaintFlow:
    """A detected flow from a *source* to a *sink*."""

    source: TaintSource
    sink: TaintSink
    path: list[str]         # Variable names in the flow chain
    description: str


# ---------------------------------------------------------------------------
# Source / sink / sanitizer catalogues
# ---------------------------------------------------------------------------

# Each source entry: (dotted_name_or_func, human_label, confidence)
# We match against attribute chains and bare function names.
_SOURCES: list[tuple[str, str, str]] = [
    # Flask / FastAPI request object
    ("request.args",     "request.args",     "high"),
    ("request.form",     "request.form",     "high"),
    ("request.json",     "request.json",     "high"),
    ("request.data",     "request.data",     "high"),
    ("request.get_json", "request.get_json()", "high"),
    ("request.values",   "request.values",   "high"),
    ("request.headers",  "request.headers",  "high"),
    ("request.cookies",  "request.cookies",  "high"),

    # Built-in / stdlib
    ("input",    "input()",    "high"),
    ("sys.argv", "sys.argv",   "high"),
    ("sys.stdin", "sys.stdin", "high"),

    # Environment (lower confidence — often admin-controlled)
    ("os.environ", "os.environ", "low"),
    ("os.getenv",  "os.getenv()", "low"),
]

# Sink catalogue -----------------------------------------------------------
# (dotted_name_or_func, human_label, owasp_code, severity)
_SINKS: list[tuple[str, str, str, str]] = [
    # SQL Injection (A03)
    ("cursor.execute",     "cursor.execute()",     "A03", "Critical"),
    ("cursor.executemany", "cursor.executemany()", "A03", "Critical"),
    ("db.execute",         "db.execute()",         "A03", "Critical"),
    (".raw",               ".raw()",               "A03", "Critical"),
    ("pd.read_sql",        "pd.read_sql()",        "A03", "High"),
    ("pd.read_sql_query",  "pd.read_sql_query()",  "A03", "High"),

    # Command Injection (A03)
    ("os.system",          "os.system()",          "A03", "Critical"),
    ("os.popen",           "os.popen()",           "A03", "Critical"),
    ("subprocess.call",    "subprocess.call()",    "A03", "Critical"),
    ("subprocess.run",     "subprocess.run()",     "A03", "Critical"),
    ("subprocess.Popen",   "subprocess.Popen()",   "A03", "Critical"),
    ("eval",               "eval()",               "A03", "Critical"),
    ("exec",               "exec()",               "A03", "Critical"),

    # Path Traversal (A01)
    ("open",               "open()",               "A01", "High"),
    ("os.path.join",       "os.path.join()",       "A01", "High"),

    # SSRF (A10)
    ("requests.get",       "requests.get()",       "A10", "High"),
    ("requests.post",      "requests.post()",      "A10", "High"),
    ("requests.put",       "requests.put()",       "A10", "High"),
    ("requests.delete",    "requests.delete()",    "A10", "High"),
    ("urllib.request.urlopen", "urllib.request.urlopen()", "A10", "High"),
    ("httpx.get",          "httpx.get()",          "A10", "High"),
    ("httpx.post",         "httpx.post()",         "A10", "High"),

    # XSS (A03)
    ("render_template_string", "render_template_string()", "A03", "High"),
    ("Markup",             "Markup()",             "A03", "High"),

    # LDAP Injection (A03)
    ("ldap.search_s",      "ldap.search_s()",     "A03", "High"),

    # Unsafe Deserialization (A08)
    ("pickle.loads",       "pickle.loads()",       "A08", "Critical"),
    ("pickle.load",        "pickle.load()",        "A08", "Critical"),
    ("yaml.load",          "yaml.load()",          "A08", "High"),
    ("marshal.loads",      "marshal.loads()",      "A08", "High"),
    ("marshal.load",       "marshal.load()",       "A08", "High"),
]

# Functions / casts that remove taint
_SANITIZERS: set[str] = {
    # Type casts
    "int", "float", "bool",
    # HTML / XSS
    "bleach.clean", "html.escape", "markupsafe.escape",
    # Shell
    "shlex.quote", "shlex.split",
    # Safe eval
    "ast.literal_eval",
}

# String methods that do NOT remove taint (result still tainted).
_PASSTHROUGH_STR_METHODS: set[str] = {
    "strip", "lstrip", "rstrip",
    "lower", "upper", "title", "capitalize", "casefold", "swapcase",
    "replace", "format", "encode", "decode",
    "split", "rsplit", "join",
    "startswith", "endswith",  # returns bool but rarely assigned back
    "center", "ljust", "rjust", "zfill",
}


# ---------------------------------------------------------------------------
# AST helper utilities
# ---------------------------------------------------------------------------

def _dotted_name(node: ast.expr) -> str | None:
    """Return the dotted name for an ``ast.Attribute`` / ``ast.Name`` chain.

    Examples::

        request.args      → "request.args"
        os.path.join      → "os.path.join"
        subprocess.run    → "subprocess.run"
        some_var          → "some_var"

    Returns ``None`` for nodes that are not simple name/attribute chains
    (e.g. subscripts, calls used as callables, etc.).
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        if parent is not None:
            return f"{parent}.{node.attr}"
    return None


def _is_parameterized_query(node: ast.Call) -> bool:
    """Detect ``cursor.execute(query, (param,))`` style parameterized queries.

    When the call has ≥ 2 positional arguments (or a ``params`` / ``args``
    keyword), we treat the first argument as safely parameterized even if
    it is tainted — the DB driver will handle escaping.
    """
    if len(node.args) >= 2:
        return True
    for kw in node.keywords:
        if kw.arg in ("params", "args", "parameters"):
            return True
    return False


def _extract_names_from_node(node: ast.expr) -> set[str]:
    """Collect every ``ast.Name.id`` reachable from *node*.

    Used to determine whether a sub-expression references a tainted
    variable.
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
    return names


# ---------------------------------------------------------------------------
# Scope-level taint map
# ---------------------------------------------------------------------------

@dataclass
class _TaintInfo:
    """Metadata attached to a tainted variable name."""

    source: TaintSource
    path: list[str] = field(default_factory=list)

    def extended(self, var: str) -> _TaintInfo:
        """Return a copy with *var* appended to the flow path."""
        return _TaintInfo(
            source=self.source,
            path=self.path + [var],
        )


class _ScopeMap:
    """Variable-level taint map for a single function / module scope.

    Maps ``variable_name → _TaintInfo``.  Provides helpers to taint,
    untaint, query, and propagate taint through assignments.
    """

    def __init__(self) -> None:
        self._map: dict[str, _TaintInfo] = {}

    # -- mutators ----------------------------------------------------------

    def taint(self, var: str, info: _TaintInfo) -> None:
        self._map[var] = info

    def untaint(self, var: str) -> None:
        self._map.pop(var, None)

    # -- queries -----------------------------------------------------------

    def is_tainted(self, var: str) -> bool:
        return var in self._map

    def get(self, var: str) -> _TaintInfo | None:
        return self._map.get(var)

    def tainted_names_in(self, names: Iterable[str]) -> list[str]:
        """Return the subset of *names* that are currently tainted."""
        return [n for n in names if n in self._map]

    def copy(self) -> _ScopeMap:
        """Shallow copy — used when entering a nested scope."""
        new = _ScopeMap()
        new._map = dict(self._map)
        return new


# ---------------------------------------------------------------------------
# Core taint tracker (AST visitor)
# ---------------------------------------------------------------------------

class TaintTracker(ast.NodeVisitor):
    """Intra-file taint analysis using AST.

    1. Identifies **sources** (user-controlled input entry points).
    2. Tracks **propagation** through variable assignments, string
       operations, container literals, and simple function returns.
    3. Detects when tainted data reaches **sinks** (dangerous operations).

    The tracker works at function-scope granularity.  Module-level code
    is analysed in its own implicit scope.  No inter-procedural analysis
    is performed.
    """

    def __init__(self, filename: str = "<unknown>", *, track_params: bool = False) -> None:
        self.filename = filename
        self.track_params = track_params

        # Results
        self.flows: list[TaintFlow] = []

        # Per-scope taint state (stack to handle nested functions)
        self._scope_stack: list[_ScopeMap] = [_ScopeMap()]

    # -- scope helpers -----------------------------------------------------

    @property
    def _scope(self) -> _ScopeMap:
        return self._scope_stack[-1]

    def _push_scope(self, inherit: bool = False) -> None:
        if inherit:
            self._scope_stack.append(self._scope.copy())
        else:
            self._scope_stack.append(_ScopeMap())

    def _pop_scope(self) -> _ScopeMap:
        return self._scope_stack.pop()

    # -- source detection --------------------------------------------------

    def _check_source(self, node: ast.expr) -> TaintSource | None:
        """If *node* represents a known source expression, return a
        ``TaintSource``; otherwise return ``None``."""

        dotted = _dotted_name(node)

        # Direct attribute / name match  (e.g. ``request.args``)
        if dotted:
            for src_name, label, _confidence in _SOURCES:
                if dotted == src_name or dotted.endswith(f".{src_name}"):
                    return TaintSource(
                        name=label,
                        line=getattr(node, "lineno", 0),
                        variable="",
                    )

        # Subscript on a source  (e.g. ``request.args["id"]``)
        if isinstance(node, ast.Subscript):
            return self._check_source(node.value)

        # Call to a source function  (e.g. ``input()``, ``request.get_json()``)
        if isinstance(node, ast.Call):
            return self._check_source(node.func)

        return None

    # -- propagation (expression tainting) ---------------------------------

    def _expr_is_tainted(self, node: ast.expr) -> _TaintInfo | None:
        """Return ``_TaintInfo`` if *node* evaluates to a tainted value.

        Handles:
        - Name references
        - Attribute access on tainted objects (``tainted.strip()``)
        - f-strings (``JoinedStr``)
        - Binary ``+`` / ``%`` (string concat / formatting)
        - Container literals ``[]``, ``{}``, ``()``
        - Calls to passthrough / non-sanitizer functions
        - Subscript on tainted containers
        """
        # --- Name ---
        if isinstance(node, ast.Name):
            return self._scope.get(node.id)

        # --- Attribute on tainted value (e.g. tainted.strip()) ---
        if isinstance(node, ast.Attribute):
            parent_info = self._expr_is_tainted(node.value)
            if parent_info is not None:
                return parent_info

        # --- Subscript on tainted container ---
        if isinstance(node, ast.Subscript):
            # First check if the whole subscript is a source
            src = self._check_source(node)
            if src:
                return _TaintInfo(source=src, path=[])
            return self._expr_is_tainted(node.value)

        # --- f-string (JoinedStr) ---
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    info = self._expr_is_tainted(value.value)
                    if info is not None:
                        return info

        # --- BinOp (string concat ``+``, modulo ``%``) ---
        if isinstance(node, ast.BinOp):
            left_info = self._expr_is_tainted(node.left)
            if left_info is not None:
                return left_info
            right_info = self._expr_is_tainted(node.right)
            if right_info is not None:
                return right_info

        # --- Container literals: list, tuple, set, dict ---
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.elts:
                info = self._expr_is_tainted(elt)
                if info is not None:
                    return info
        if isinstance(node, ast.Dict):
            for v in node.values:
                if v is not None:
                    info = self._expr_is_tainted(v)
                    if info is not None:
                        return info

        # --- Call ---
        if isinstance(node, ast.Call):
            return self._call_taint(node)

        # --- Starred (e.g. *tainted in a list) ---
        if isinstance(node, ast.Starred):
            return self._expr_is_tainted(node.value)

        # --- IfExp (ternary: a if cond else b) ---
        if isinstance(node, ast.IfExp):
            body_info = self._expr_is_tainted(node.body)
            if body_info is not None:
                return body_info
            return self._expr_is_tainted(node.orelse)

        return None

    def _call_taint(self, node: ast.Call) -> _TaintInfo | None:
        """Determine if the *return value* of a call is tainted.

        Rules:
        - Sanitizer call → not tainted (returns ``None``).
        - String method on tainted object → still tainted.
        - Source call (``input()``, etc.) → newly tainted.
        - Any other call whose arguments include a tainted value →
          tainted (simple heuristic).
        """
        func_name = _dotted_name(node.func)

        # 1. Sanitizers remove taint
        if func_name and func_name in _SANITIZERS:
            return None

        # 2. Source call
        src = self._check_source(node)
        if src:
            return _TaintInfo(source=src, path=[])

        # 3. String method on a tainted value (e.g. tainted.strip())
        if isinstance(node.func, ast.Attribute):
            obj_info = self._expr_is_tainted(node.func.value)
            if obj_info is not None and node.func.attr in _PASSTHROUGH_STR_METHODS:
                return obj_info

        # 4. Generic propagation: if any positional arg is tainted, result
        #    is tainted (simple heuristic — works well for wrappers).
        for arg in node.args:
            info = self._expr_is_tainted(arg)
            if info is not None:
                # But NOT if the callee is a sanitizer (already handled above)
                return info

        return None

    # -- sink detection & flow recording -----------------------------------

    def _check_sink_call(self, node: ast.Call) -> None:
        """Check if *node* is a call to a known sink with tainted args."""
        func_name = _dotted_name(node.func)
        if func_name is None:
            # Try suffix matching for method calls like obj.execute()
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            else:
                return

        for sink_pattern, label, owasp, severity in _SINKS:
            if not self._matches_sink(func_name, sink_pattern, node):
                continue

            # For SQL-style sinks, parameterized queries are safe
            if sink_pattern in (
                "cursor.execute", "cursor.executemany",
                "db.execute", "pd.read_sql", "pd.read_sql_query",
            ) and _is_parameterized_query(node):
                continue

            # Check each positional argument for taint
            for arg in node.args:
                info = self._expr_is_tainted(arg)
                if info is not None:
                    self._record_flow(info, label, node, owasp, severity)
                    break  # one flow per call site is enough

            # Also check keyword arguments (e.g. data=tainted)
            for kw in node.keywords:
                if kw.arg in ("params", "args", "parameters"):
                    continue  # these are the safe parameter slots
                info = self._expr_is_tainted(kw.value)
                if info is not None:
                    self._record_flow(info, label, node, owasp, severity)
                    break

    def _matches_sink(
        self, func_name: str, pattern: str, node: ast.Call
    ) -> bool:
        """Return ``True`` if *func_name* matches the sink *pattern*.

        Supports exact match, suffix match (``cursor.execute`` matches
        ``db_cursor.execute``), and bare-name match for builtins
        (``eval``, ``exec``, ``open``).
        """
        if func_name == pattern:
            return True
        # Suffix match: "my_cursor.execute" matches pattern "cursor.execute"
        if "." in pattern and func_name.endswith("." + pattern.split(".")[-1]):
            # Ensure the object part also loosely matches
            obj_part = pattern.split(".")[0]
            actual_obj = func_name.rsplit(".", 1)[0] if "." in func_name else ""
            if obj_part in actual_obj or actual_obj.endswith(obj_part):
                return True
        # For patterns that start with "." (like ".raw"), match any suffix
        if pattern.startswith(".") and func_name.endswith(pattern.lstrip(".")):
            return True
        # Bare-name sinks (eval, exec, open) — match Name nodes
        if "." not in pattern and func_name == pattern:
            return True
        # Attribute match for dotted sinks: func_name ends with the pattern
        if func_name.endswith(pattern):
            return True
        return False

    def _record_flow(
        self,
        info: _TaintInfo,
        sink_label: str,
        node: ast.Call,
        owasp: str,
        severity: str,
    ) -> None:
        """Create a ``TaintFlow`` and append to ``self.flows``."""
        sink = TaintSink(
            name=sink_label,
            line=getattr(node, "lineno", 0),
            owasp_code=owasp,
            severity=severity,
        )

        path = list(info.path)
        if info.source.variable and info.source.variable not in path:
            path.insert(0, info.source.variable)

        self.flows.append(TaintFlow(
            source=info.source,
            sink=sink,
            path=path,
            description=(
                f"Tainted data from {info.source.name} (line {info.source.line}) "
                f"flows to {sink_label} (line {sink.line}) "
                f"via [{' → '.join(path) if path else 'direct'}]"
            ),
        ))

    # -- AST visitors ------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track taint through assignments like ``x = tainted_value``."""
        # Check if the RHS is a known source
        source = self._check_source(node.value)

        if source is not None:
            # New taint from a source
            for target in node.targets:
                names = self._assign_target_names(target)
                for name in names:
                    source_copy = TaintSource(
                        name=source.name,
                        line=source.line,
                        variable=name,
                    )
                    self._scope.taint(name, _TaintInfo(
                        source=source_copy,
                        path=[name],
                    ))
        else:
            # Check propagation from existing tainted vars
            info = self._expr_is_tainted(node.value)
            if info is not None:
                for target in node.targets:
                    names = self._assign_target_names(target)
                    for name in names:
                        self._scope.taint(name, info.extended(name))
            else:
                # RHS is clean — untaint the target if it was tainted
                for target in node.targets:
                    names = self._assign_target_names(target)
                    for name in names:
                        self._scope.untaint(name)

        # If the value is a Call, it might also be a sink
        if isinstance(node.value, ast.Call):
            self._check_sink_call(node.value)

        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Handle ``x += tainted`` — the result is tainted."""
        info = self._expr_is_tainted(node.value)
        if info is not None:
            names = self._assign_target_names(node.target)
            for name in names:
                self._scope.taint(name, info.extended(name))
        else:
            # Check if the target itself is tainted (x += "safe" keeps taint)
            target_info = self._expr_is_tainted(node.target)
            # Keep existing taint on the target — do nothing extra

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Handle annotated assignments: ``x: str = tainted``."""
        if node.value is not None and node.target is not None:
            source = self._check_source(node.value)
            names = self._assign_target_names(node.target)

            if source is not None:
                for name in names:
                    source_copy = TaintSource(
                        name=source.name, line=source.line, variable=name,
                    )
                    self._scope.taint(name, _TaintInfo(
                        source=source_copy, path=[name],
                    ))
            else:
                info = self._expr_is_tainted(node.value)
                if info is not None:
                    for name in names:
                        self._scope.taint(name, info.extended(name))
                else:
                    for name in names:
                        self._scope.untaint(name)

            if isinstance(node.value, ast.Call):
                self._check_sink_call(node.value)

        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        """Visit bare expression statements — mainly for standalone calls."""
        if isinstance(node.value, ast.Call):
            self._check_sink_call(node.value)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        """Check return values for sink calls."""
        if node.value is not None and isinstance(node.value, ast.Call):
            self._check_sink_call(node.value)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Enter a new scope for function bodies."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Enter a new scope for async function bodies."""
        self._visit_function(node)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Shared logic for sync / async function definitions."""
        self._push_scope()

        # Optionally taint function parameters
        if self.track_params:
            for arg in node.args.args:
                arg_name = arg.arg
                if arg_name == "self":
                    continue
                src = TaintSource(
                    name=f"parameter:{arg_name}",
                    line=node.lineno,
                    variable=arg_name,
                )
                self._scope.taint(arg_name, _TaintInfo(
                    source=src, path=[arg_name],
                ))

        # Visit the body
        for child in node.body:
            self.visit(child)

        self._pop_scope()

    def visit_For(self, node: ast.For) -> None:
        """Track taint through for-loop targets.

        ``for x in tainted_list:`` → ``x`` is tainted.
        """
        info = self._expr_is_tainted(node.iter)
        if info is not None:
            names = self._assign_target_names(node.target)
            for name in names:
                self._scope.taint(name, info.extended(name))
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        """Track taint through context managers.

        ``with open(tainted) as f:`` — check the call for sinks.
        """
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                self._check_sink_call(item.context_expr)

            # Propagate taint to the ``as`` variable
            if item.optional_vars is not None:
                info = self._expr_is_tainted(item.context_expr)
                if info is not None:
                    names = self._assign_target_names(item.optional_vars)
                    for name in names:
                        self._scope.taint(name, info.extended(name))

        self.generic_visit(node)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _assign_target_names(target: ast.expr) -> list[str]:
        """Extract plain variable names from an assignment target.

        Handles ``x``, ``(x, y)``, ``[x, y]``, and starred targets.
        Ignores attribute stores (``self.x = ...``) and subscript stores.
        """
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names: list[str] = []
            for elt in target.elts:
                names.extend(TaintTracker._assign_target_names(elt))
            return names
        if isinstance(target, ast.Starred):
            return TaintTracker._assign_target_names(target.value)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_taint(
    code_text: str,
    filename: str = "<unknown>",
    *,
    track_params: bool = False,
) -> list[TaintFlow]:
    """Analyse *code_text* for taint flows from sources to sinks.

    Parameters
    ----------
    code_text:
        Python source code to analyse.
    filename:
        File path shown in diagnostics.
    track_params:
        When ``True``, function parameters (except ``self``) are treated
        as tainted sources.  Off by default to reduce false positives.

    Returns
    -------
    list[TaintFlow]
        Every detected flow from a user-controlled source to a
        dangerous sink, including the propagation path.
    """
    try:
        tree = ast.parse(code_text, filename=filename)
    except SyntaxError:
        return []

    tracker = TaintTracker(filename=filename, track_params=track_params)
    tracker.visit(tree)
    return tracker.flows
