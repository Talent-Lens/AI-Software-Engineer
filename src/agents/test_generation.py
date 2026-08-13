"""
Test Generation Agent — given a Python file, extracts functions, generates
pytest test cases, executes them in an isolated subprocess sandbox, and
self-corrects test cases if stack trace errors occur until tests pass cleanly (TASK-E3).
"""

import os
import re
import ollama
from src.indexing.chunker import chunk_file
from src.schema import Chunk
from src.sandbox.runner import execute_tests_in_sandbox

MODEL_NAME = "qwen2.5:7b"


def get_function_chunks(filepath: str) -> list[Chunk]:
    """Reuse chunker to get function/method chunks with real source code."""
    chunks = chunk_file(filepath)
    return [c for c in chunks if c.type in ("function", "method")]


def _clean_code_output(text: str) -> str:
    """Extracts raw python code from markdown fenced code blocks if present."""
    match = re.search(r"```(?:python|py)?\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Strip backticks if single block
    lines = text.strip().splitlines()
    filtered = [l for l in lines if not l.strip().startswith("```")]
    return "\n".join(filtered).strip()


def generate_tests_for_function(func_code: str, func_name: str) -> str:
    """Tool: sends one function's code to the LLM, asks for pytest test cases."""
    prompt = f"""Write pytest test cases for this Python function. Cover:
1. A normal/expected input case
2. At least one edge case
3. At least one case that should raise an error, if applicable

Function:
```python
{func_code}
```

Return only valid Python test code using pytest conventions (test_ prefixed functions), no explanation text."""

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
        )
        if isinstance(response, dict):
            raw = response.get("message", {}).get("content", "")
        else:
            raw = getattr(getattr(response, "message", None), "content", str(response))
        return _clean_code_output(raw)
    except Exception as e:
        return f"# Test generation failed: {e}"


def refine_failing_tests(
    func_code: str, func_name: str, failing_test_code: str, error_traceback: str
) -> str:
    """Sends failing test code + stack trace back to LLM to self-correct until tests pass."""
    prompt = f"""The generated pytest code for function `{func_name}` failed during subprocess sandbox execution.

Function Source:
```python
{func_code}
```

Failing Test Code:
```python
{failing_test_code}
```

Sandbox Error Traceback:
```text
{error_traceback}
```

Please fix the test code so that all pytest assertions pass cleanly without errors.
Return ONLY valid Python test code, no explanation text."""

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
        )
        if isinstance(response, dict):
            raw = response.get("message", {}).get("content", "")
        else:
            raw = getattr(getattr(response, "message", None), "content", str(response))
        return _clean_code_output(raw)
    except Exception as e:
        return failing_test_code


def analyze_and_generate(filepath: str, max_attempts: int = 3) -> dict:
    """
    Public entry point. Extracts functions from file, generates pytest tests,
    executes them live in isolated subprocess sandbox, and self-corrects on failure.
    """
    if not os.path.exists(filepath):
        return {
            "agent_name": "test_generation",
            "summary": f"File non-existent: {filepath}",
            "details": {"filepath": filepath},
            "confidence": 0.0,
        }

    try:
        functions = get_function_chunks(filepath)
    except Exception as e:
        return {
            "agent_name": "test_generation",
            "summary": f"Failed to extract functions: {e}",
            "details": {"filepath": filepath},
            "confidence": 0.0,
        }

    if not functions:
        return {
            "agent_name": "test_generation",
            "summary": f"No functions found in {filepath}.",
            "details": {"filepath": filepath},
            "confidence": 1.0,
        }

    all_verified_tests = []
    per_function_results = {}
    sandbox_results = {}
    passed_funcs = 0

    for func in functions:
        attempt = 1
        current_tests = generate_tests_for_function(func.code, func.name)
        sandbox_res = execute_tests_in_sandbox(filepath, current_tests)

        # Self-correction loop: retry up to max_attempts if tests fail
        while sandbox_res["status"] != "PASSED" and attempt < max_attempts:
            attempt += 1
            traceback_info = sandbox_res.get("error_traceback") or sandbox_res.get("stderr") or "Test failure"
            current_tests = refine_failing_tests(
                func_code=func.code,
                func_name=func.name,
                failing_test_code=current_tests,
                error_traceback=traceback_info,
            )
            sandbox_res = execute_tests_in_sandbox(filepath, current_tests)

        sandbox_res["attempts"] = attempt
        sandbox_results[func.name] = sandbox_res
        per_function_results[func.name] = current_tests

        if sandbox_res["status"] == "PASSED":
            passed_funcs += 1
            all_verified_tests.append(f"# Verified pytest suite for {func.name}\n{current_tests}")
        else:
            all_verified_tests.append(f"# Unverified test suite for {func.name} (Status: {sandbox_res['status']})\n{current_tests}")

    summary = "\n\n".join(all_verified_tests) if all_verified_tests else "No tests generated."
    confidence = round(passed_funcs / len(functions), 2) if functions else 0.0

    return {
        "agent_name": "test_generation",
        "summary": summary,
        "details": {
            "per_function": per_function_results,
            "sandbox_results": sandbox_results,
            "function_count": len(functions),
            "passed_functions": passed_funcs,
            "filepath": filepath,
        },
        "confidence": confidence,
    }


if __name__ == "__main__":
    sample_file = __file__
    result = analyze_and_generate(sample_file)
    print(result["summary"])