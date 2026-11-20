"""
Bug Detection Agent — analyzes a Python file for real issues (currently:
bare except clauses) and produces an LLM-generated explanation for each,
following the why / which line / possible fix structure.
"""

import ast
import os
import re
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import ollama
import requests

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

MODEL_NAME = "qwen2.5:7b"



# ---------------------------------------------------------------------------
# Detection logic (Tree-sitter based)
# TODO: consider moving into src/indexing/chunker.py once confirmed with
# partner — this duplicates their parser setup for now, kept separate to
# avoid touching their file without agreement.
# ---------------------------------------------------------------------------

def _find_enclosing_name(node, filepath):
    names = []
    current = node.parent
    while current:
        if current.type in ("function_definition", "class_definition"):
            name_node = current.child_by_field_name("name")
            if name_node:
                names.insert(0, name_node.text.decode())
        current = current.parent
    if names:
        return ".".join(names)
    import os
    return os.path.splitext(os.path.basename(filepath))[0]


def find_bare_excepts(filepath: str) -> list[dict]:
    with open(filepath, "rb") as f:
        code = f.read()
    tree = parser.parse(code)

    query = PY_LANGUAGE.query("(except_clause) @except.block")
    captures = query.captures(tree.root_node)

    results = []
    for node in captures.get("except.block", []):
        has_type = any(
            child.type != ":" and child.is_named
            for child in node.children if child.type != "block"
        )
        if not has_type:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            enclosing = _find_enclosing_name(node, filepath)
            qualified_name = f"{enclosing}[bare_except]"
            results.append({
                "id": f"{filepath}::{qualified_name}::{start_line}",
                "type": "bare_except",
                "name": qualified_name,
                "start_line": start_line,
                "end_line": end_line,
            })
    return results


# ---------------------------------------------------------------------------
# AST Bug and Security Pattern Checkers
# ---------------------------------------------------------------------------

def check_mutable_default_args(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag functions using mutable default arguments (list, dict, set)."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_defs = list(node.args.defaults) + [d for d in node.args.kw_defaults if d]
            for d in all_defs:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    issues.append({
                        "id": f"{filepath}::{node.name}[mutable_default_args]::{d.lineno}",
                        "type": "mutable_default_args",
                        "name": f"{node.name}[mutable_default_args]",
                        "start_line": d.lineno,
                        "end_line": getattr(d, "end_lineno", d.lineno),
                        "description": f"Function '{node.name}' uses a mutable default argument ({type(d).__name__.lower()}).",
                    })
    return issues


def check_assert_validation(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag assert statements used for data validation (stripped in optimized Python -O)."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            issues.append({
                "id": f"{filepath}::assert[assert_validation]::{node.lineno}",
                "type": "assert_validation",
                "name": "assert[assert_validation]",
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "description": "Assert used for validation; assertions are removed when Python runs with optimization (-O).",
            })
    return issues


def check_tempfile_mktemp(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag tempfile.mktemp() usage which is insecure and prone to race conditions."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if call_str.endswith("mktemp") or (isinstance(node.func, ast.Attribute) and node.func.attr == "mktemp"):
                issues.append({
                    "id": f"{filepath}::mktemp[tempfile_mktemp]::{node.lineno}",
                    "type": "tempfile_mktemp",
                    "name": "mktemp[tempfile_mktemp]",
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "description": "tempfile.mktemp() is insecure and vulnerable to symlink race conditions; use NamedTemporaryFile or mkstemp.",
                })
    return issues


def check_open_without_encoding(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag open() calls in text mode missing explicit encoding."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if call_name == "open":
                has_enc = any(kw.arg == "encoding" for kw in node.keywords)
                is_binary = False
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    if "b" in node.args[1].value:
                        is_binary = True
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        if "b" in kw.value.value:
                            is_binary = True
                if not is_binary and not has_enc:
                    issues.append({
                        "id": f"{filepath}::open[open_without_encoding]::{node.lineno}",
                        "type": "open_without_encoding",
                        "name": "open[open_without_encoding]",
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "description": "open() called in text mode without explicit encoding parameter.",
                    })
    return issues


def check_yaml_load_unsafe(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag yaml.load() calls missing Loader=SafeLoader."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if call_str.endswith("yaml.load") or (isinstance(node.func, ast.Attribute) and node.func.attr == "load" and getattr(node.func.value, "id", None) == "yaml"):
                has_safe = any(kw.arg == "Loader" and "SafeLoader" in (ast.unparse(kw.value) if hasattr(ast, "unparse") else "") for kw in node.keywords)
                if not has_safe:
                    issues.append({
                        "id": f"{filepath}::yaml.load[yaml_load_unsafe]::{node.lineno}",
                        "type": "yaml_load_unsafe",
                        "name": "yaml.load[yaml_load_unsafe]",
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "description": "yaml.load() called without Loader=SafeLoader can allow arbitrary code execution.",
                    })
    return issues


def check_redos_patterns(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag regular expressions with nested quantifiers vulnerable to ReDoS."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if (call_str.startswith("re.") or "compile" in call_str) and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    if re.search(r"\([^\)]*[\+\*]\)[\+\*]", arg0.value):
                        issues.append({
                            "id": f"{filepath}::re[redos_pattern]::{node.lineno}",
                            "type": "redos_pattern",
                            "name": "re[redos_pattern]",
                            "start_line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                            "description": "Regular expression contains nested quantifiers vulnerable to catastrophic backtracking (ReDoS).",
                        })
    return issues


def check_comparison_to_none(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag comparisons to None using '==' or '!=' instead of 'is'/'is not'."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    if (isinstance(node.left, ast.Constant) and node.left.value is None) or (isinstance(comp, ast.Constant) and comp.value is None):
                        issues.append({
                            "id": f"{filepath}::None[comparison_to_none]::{node.lineno}",
                            "type": "comparison_to_none",
                            "name": "None[comparison_to_none]",
                            "start_line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                            "description": "Comparison to None using equality operator; use 'is None' or 'is not None'.",
                        })
    return issues


def check_is_with_literal(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag identity checks ('is' / 'is not') against literal values."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Is, ast.IsNot)):
                    for side in (node.left, comp):
                        if isinstance(side, ast.Constant) and isinstance(side.value, (int, str, float, bytes)):
                            issues.append({
                                "id": f"{filepath}::is_literal[is_with_literal]::{node.lineno}",
                                "type": "is_with_literal",
                                "name": "is_literal[is_with_literal]",
                                "start_line": node.lineno,
                                "end_line": getattr(node, "end_lineno", node.lineno),
                                "description": "Identity comparison ('is'/'is not') used with a literal value; use '==' or '!='.",
                            })
                            break
    return issues


def check_open_without_context_manager(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag open() calls not wrapped in a 'with' context manager."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call_s = ast.unparse(node.value.func) if hasattr(ast, "unparse") else ""
            if call_s == "open":
                issues.append({
                    "id": f"{filepath}::open[open_without_context_manager]::{node.lineno}",
                    "type": "open_without_context_manager",
                    "name": "open[open_without_context_manager]",
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "description": "open() called as standalone expression without context manager; risk of file descriptor leak.",
                })
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call_s = ast.unparse(node.value.func) if hasattr(ast, "unparse") else ""
            if call_s == "open":
                issues.append({
                    "id": f"{filepath}::open[open_without_context_manager]::{node.lineno}",
                    "type": "open_without_context_manager",
                    "name": "open[open_without_context_manager]",
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "description": "open() assigned directly without a context manager ('with' statement); risk of resource leak.",
                })
    return issues


def check_unreachable_code(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag unreachable statements after return, raise, break, or continue."""
    issues = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for idx, stmt in enumerate(body[:-1]):
                if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                    unreach = body[idx + 1]
                    issues.append({
                        "id": f"{filepath}::unreachable[unreachable_code]::{unreach.lineno}",
                        "type": "unreachable_code",
                        "name": "unreachable[unreachable_code]",
                        "start_line": unreach.lineno,
                        "end_line": getattr(unreach, "end_lineno", unreach.lineno),
                        "description": "Unreachable code statement found after return, raise, break, or continue.",
                    })
    return issues


def check_unused_variables(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag local variables assigned in a function but never read."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assigned = set()
            loaded = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    if isinstance(child.ctx, ast.Store) and not child.id.startswith("_"):
                        assigned.add((child.id, child.lineno))
                    elif isinstance(child.ctx, ast.Load):
                        loaded.add(child.id)
            param_names = (
                {a.arg for a in node.args.args}
                | {a.arg for a in getattr(node.args, "posonlyargs", [])}
                | {a.arg for a in node.args.kwonlyargs}
            )
            for var, lno in assigned:
                if var not in loaded and var not in param_names:
                    issues.append({
                        "id": f"{filepath}::{var}[unused_variable]::{lno}",
                        "type": "unused_variable",
                        "name": f"{var}[unused_variable]",
                        "start_line": lno,
                        "end_line": lno,
                        "description": f"Local variable '{var}' is assigned but never used.",
                    })
    return issues


def check_silent_except_pass(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag except blocks that specify an exception type but silently suppress it with 'pass'."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            # If node.type is None, it is a bare except (already detected by find_bare_excepts)
            if node.type is not None and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                issues.append({
                    "id": f"{filepath}::except[silent_except_pass]::{node.lineno}",
                    "type": "silent_except_pass",
                    "name": "except[silent_except_pass]",
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "description": "Silent exception suppression: except block contains only 'pass' without logging or handling.",
                })
    return issues


def check_duplicate_dict_keys(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag literal dictionaries with duplicate keys."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            seen_keys = set()
            for k in node.keys:
                if isinstance(k, ast.Constant):
                    if k.value in seen_keys:
                        issues.append({
                            "id": f"{filepath}::dict_key[duplicate_dict_key]::{k.lineno}",
                            "type": "duplicate_dict_key",
                            "name": f"key:{k.value}[duplicate_dict_key]",
                            "start_line": k.lineno,
                            "end_line": getattr(k, "end_lineno", k.lineno),
                            "description": f"Duplicate dictionary key '{k.value}' overwrites previous entry.",
                        })
                    else:
                        seen_keys.add(k.value)
    return issues


def check_finally_return_raise(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag return or raise statements inside a 'finally' block."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.finalbody:
            for stmt in node.finalbody:
                if isinstance(stmt, (ast.Return, ast.Raise)):
                    issues.append({
                        "id": f"{filepath}::finally[finally_return_raise]::{stmt.lineno}",
                        "type": "finally_return_raise",
                        "name": "finally[finally_return_raise]",
                        "start_line": stmt.lineno,
                        "end_line": getattr(stmt, "end_lineno", stmt.lineno),
                        "description": "return or raise inside 'finally' block swallows pending exceptions or overrides try/except control flow.",
                    })
    return issues


def check_shelve_open(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag shelve.open() calls (pickle-based deserialization vulnerability)."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            if call_str.endswith("shelve.open") or (isinstance(node.func, ast.Attribute) and node.func.attr == "open" and getattr(node.func.value, "id", None) == "shelve"):
                issues.append({
                    "id": f"{filepath}::shelve[shelve_open]::{node.lineno}",
                    "type": "shelve_open",
                    "name": "shelve[shelve_open]",
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "description": "shelve.open() relies on pickle internally and is vulnerable to arbitrary object deserialization.",
                })
    return issues


def check_path_traversal_open(tree: ast.AST, filepath: str = "<unknown>") -> list[dict]:
    """Flag open() calls constructed with unvalidated dynamic path inputs."""
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if call_name == "open" and node.args:
                arg0 = node.args[0]
                is_traversal_risk = False
                if isinstance(arg0, (ast.JoinedStr, ast.BinOp)):
                    is_traversal_risk = True
                elif isinstance(arg0, ast.Name) and any(hint in arg0.id.lower() for hint in ("user", "param", "req", "input", "upload")):
                    is_traversal_risk = True
                elif isinstance(arg0, ast.Call):
                    call_s = ast.unparse(arg0) if hasattr(ast, "unparse") else ""
                    if any(hint in call_s.lower() for hint in ("user", "request", "input")) and "basename" not in call_s:
                        is_traversal_risk = True
                if is_traversal_risk:
                    issues.append({
                        "id": f"{filepath}::open[path_traversal_open]::{node.lineno}",
                        "type": "path_traversal_open",
                        "name": "open[path_traversal_open]",
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "description": "File path in open() constructed from unvalidated input without os.path.basename; risk of path traversal.",
                    })
    return issues


CHECKERS = [
    check_mutable_default_args,
    check_assert_validation,
    check_tempfile_mktemp,
    check_open_without_encoding,
    check_yaml_load_unsafe,
    check_redos_patterns,
    check_comparison_to_none,
    check_is_with_literal,
    check_open_without_context_manager,
    check_unreachable_code,
    check_unused_variables,
    check_silent_except_pass,
    check_duplicate_dict_keys,
    check_finally_return_raise,
    check_shelve_open,
    check_path_traversal_open,
]


def find_ast_bugs(filepath: str, code: str = None) -> list[dict]:
    """Run all independent AST bug checkers against a Python file or source code string."""
    if code is None:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()
        except Exception:
            return []
    try:
        tree = ast.parse(code, filename=filepath)
    except Exception:
        return []

    issues = []
    for checker in CHECKERS:
        try:
            issues.extend(checker(tree, filepath))
        except Exception:
            pass
    return issues


# ---------------------------------------------------------------------------
# Tool: wraps detection logic for the LLM to call
# ---------------------------------------------------------------------------

def run_bug_scan(filepath: str) -> str:
    try:
        issues = find_bare_excepts(filepath) + find_ast_bugs(filepath)
    except Exception as e:
        return f"Error analyzing file: {e}"

    if not issues:
        return f"No real issues found in {filepath}."

    lines = [f"Found {len(issues)} issue(s) in {filepath}:\n"]
    for i, issue in enumerate(issues, 1):
        desc = issue.get("description")
        if not desc and issue.get("type") == "bare_except":
            desc = (
                "a bare 'except:' with no exception type — "
                "silently catches everything, including KeyboardInterrupt and SystemExit"
            )
        desc_str = f" ({desc})" if desc else ""
        lines.append(
            f"ISSUE {i}:\n"
            f"  type: {issue['type']}{desc_str}\n"
            f"  location: {issue['name']}\n"
            f"  lines: {issue['start_line']}-{issue['end_line']}\n"
        )
    return "\n".join(lines)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_bug_scan",
            "description": "Runs static analysis on a Python file and returns real issues found (currently: bare except clauses). Use this whenever the user asks to check, review, or find bugs in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Full path to the Python file to analyze"
                    }
                },
                "required": ["filepath"]
            }
        }
    }
]

TOOL_IMPLEMENTATIONS = {
    "run_bug_scan": lambda args: run_bug_scan(args["filepath"]),
}

SYSTEM_PROMPT = """You are a code review assistant. The run_bug_scan tool returns a list of numbered ISSUEs.
For EACH issue separately, write its own explanation block using exactly this structure:

Issue N: <location>
- WHY it matters: <specific to this issue's type, not generic>
- WHICH LINE(S): <the line range given>
- POSSIBLE FIX: <a concrete, specific suggestion>

Do not combine multiple issues into one paragraph. Do not repeat the same generic sentence for every issue.
If the tool reports no real issues, just say the file looks clean."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

import os


def analyze_and_explain(filepath: str) -> dict:
    """
    Runs the bug detection agent on a file, returns an AgentResponse-shaped dict:
      { agent_name, summary, details, confidence }
    """
    if not os.path.exists(filepath):
        return {
            "agent_name": "bug_detection",
            "summary": f"File does not exist: {filepath}",
            "details": {"error": "File not found"},
            "confidence": None,
        }

    # First, run zero-latency AST bug scan
    raw_findings = run_bug_scan(filepath)

    # Fast connectivity check: skip Ollama wait if daemon is offline
    ollama_online = False
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=0.5)
        ollama_online = (r.status_code == 200)
    except Exception:
        ollama_online = False

    if not ollama_online:
        return {
            "agent_name": "bug_detection",
            "summary": f"Bug scan completed via static AST analyzer.\n\n{raw_findings}",
            "details": {"raw_findings": raw_findings, "filepath": filepath},
            "confidence": 1.0,
        }

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Please check {filepath} for bugs."},
    ]

    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(ollama.chat, model=MODEL_NAME, messages=messages, tools=TOOLS)
            response = future.result(timeout=1.0)

    except Exception:
        return {
            "agent_name": "bug_detection",
            "summary": f"Bug scan completed via static AST analyzer.\n\n{raw_findings}",
            "details": {"raw_findings": raw_findings, "filepath": filepath},
            "confidence": 1.0,
        }




    message = response["message"] if isinstance(response, dict) else getattr(response, "message", {})
    tool_calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)

    if not tool_calls:
        content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
        return {
            "agent_name": "bug_detection",
            "summary": content,
            "details": {"raw_findings": None, "filepath": filepath},
            "confidence": None,
        }

    call = tool_calls[0]
    func_info = call.get("function", {}) if isinstance(call, dict) else getattr(call, "function", {})
    func_name = func_info.get("name") if isinstance(func_info, dict) else getattr(func_info, "name", None)
    func_args = func_info.get("arguments") if isinstance(func_info, dict) else getattr(func_info, "arguments", {})

    if func_name in TOOL_IMPLEMENTATIONS:
        raw_result = TOOL_IMPLEMENTATIONS[func_name](func_args)
    else:
        raw_result = run_bug_scan(filepath)

    messages.append(message)
    messages.append({"role": "tool", "content": raw_result})

    try:
        final_response = ollama.chat(model=MODEL_NAME, messages=messages, tools=TOOLS)
        final_msg = final_response["message"] if isinstance(final_response, dict) else getattr(final_response, "message", {})
        final_content = final_msg.get("content", "") if isinstance(final_msg, dict) else getattr(final_msg, "content", "")
    except Exception:
        final_content = f"Scan complete. Raw findings:\n{raw_result}"

    return {
        "agent_name": "bug_detection",
        "summary": final_content,
        "details": {"raw_findings": raw_result, "filepath": filepath},
        "confidence": None,
    }


if __name__ == "__main__":
    # quick manual test using current file
    result = analyze_and_explain(__file__)
    print(result["summary"])