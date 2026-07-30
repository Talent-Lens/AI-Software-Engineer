"""
Bug Detection Agent — analyzes a Python file for real issues (currently:
bare except clauses) and produces an LLM-generated explanation for each,
following the why / which line / possible fix structure.
"""

from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import ollama

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
# Tool: wraps detection logic for the LLM to call
# ---------------------------------------------------------------------------

def run_bug_scan(filepath: str) -> str:
    try:
        issues = find_bare_excepts(filepath)
    except Exception as e:
        return f"Error analyzing file: {e}"

    if not issues:
        return f"No real issues found in {filepath}."

    lines = [f"Found {len(issues)} issue(s) in {filepath}:\n"]
    for i, issue in enumerate(issues, 1):
        lines.append(
            f"ISSUE {i}:\n"
            f"  type: bare_except (a bare 'except:' with no exception type — "
            f"silently catches everything, including KeyboardInterrupt and SystemExit)\n"
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

def analyze_and_explain(filepath: str) -> dict:
    """
    Runs the bug detection agent on a file, returns an AgentResponse-shaped dict:
      { agent_name, summary, details, confidence }
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Please check {filepath} for bugs."},
    ]

    try:
        response = ollama.chat(model=MODEL_NAME, messages=messages, tools=TOOLS)
    except Exception as e:
        return {
            "agent_name": "bug_detection",
            "summary": "Agent failed to run — is Ollama running?",
            "details": {"error": str(e)},
            "confidence": None,
        }

    tool_calls = response["message"].get("tool_calls")

    if not tool_calls:
        return {
            "agent_name": "bug_detection",
            "summary": response["message"]["content"],
            "details": {"raw_findings": None},
            "confidence": None,
        }

    call = tool_calls[0]
    raw_result = TOOL_IMPLEMENTATIONS[call["function"]["name"]](call["function"]["arguments"])

    messages.append(response["message"])
    messages.append({"role": "tool", "content": raw_result})

    final_response = ollama.chat(model=MODEL_NAME, messages=messages, tools=TOOLS)

    return {
        "agent_name": "bug_detection",
        "summary": final_response["message"]["content"],
        "details": {"raw_findings": raw_result},
        "confidence": None,
    }


if __name__ == "__main__":
    # quick manual test
    result = analyze_and_explain(r"D:\test-repos\test_bare_except_file.py")
    print(result["summary"])