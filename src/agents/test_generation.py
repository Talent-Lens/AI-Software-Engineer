"""
Test Generation Agent — given a Python file, extracts functions and
generates pytest test cases for each, covering normal/edge/error cases.
"""

import os
import ollama
from src.indexing.chunker import chunk_file
from src.schema import Chunk

MODEL_NAME = "qwen2.5:7b"


def get_function_chunks(filepath: str) -> list[Chunk]:
    """Reuse partner's chunker to get function/method chunks with real source code."""
    chunks = chunk_file(filepath)
    return [c for c in chunks if c.type in ("function", "method")]


def generate_tests_for_function(func_code: str, func_name: str) -> str:
    """Tool: sends one function's code to the LLM, asks for pytest tests."""
    prompt = f"""Write pytest test cases for this Python function. Cover:
1. A normal/expected input case
2. At least one edge case
3. At least one case that should raise an error, if applicable

Function:
```python
{func_code}
```

Return only valid Python test code using pytest conventions (test_ prefixed functions), no explanation text."""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
    )
    if isinstance(response, dict):
        return response.get("message", {}).get("content", "")
    return getattr(getattr(response, "message", None), "content", str(response))


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_tests_for_function",
            "description": "Generates pytest test cases for a given function's source code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "func_code": {"type": "string", "description": "The function's source code"},
                    "func_name": {"type": "string", "description": "The function's name"},
                },
                "required": ["func_code", "func_name"]
            }
        }
    }
]


def analyze_and_generate(filepath: str) -> dict:
    """
    Public entry point. Extracts all functions/methods from a file,
    generates tests for each, returns AgentResponse-shaped dict.
    """
    if not os.path.exists(filepath):
        return {
            "agent_name": "test_generation",
            "summary": f"File non-existent: {filepath}",
            "details": {},
            "confidence": None,
        }

    try:
        functions = get_function_chunks(filepath)
    except Exception as e:
        return {
            "agent_name": "test_generation",
            "summary": f"Failed to extract functions: {e}",
            "details": {},
            "confidence": None,
        }

    if not functions:
        return {
            "agent_name": "test_generation",
            "summary": f"No functions found in {filepath}.",
            "details": {},
            "confidence": None,
        }

    all_tests = []
    per_function_results = {}

    for func in functions:
        try:
            tests = generate_tests_for_function(func.code, func.name)
            per_function_results[func.name] = tests
            if tests:
                all_tests.append(f"# Tests for {func.name}\n{tests}")
            else:
                per_function_results[func.name] = "No test output generated."
        except Exception as e:
            per_function_results[func.name] = f"Error: {e}"

    summary = "\n\n".join(all_tests) if all_tests else "No tests generated."

    return {
        "agent_name": "test_generation",
        "summary": summary,
        "details": {"per_function": per_function_results, "function_count": len(functions)},
        "confidence": None,
    }


if __name__ == "__main__":
    sample_file = __file__
    result = analyze_and_generate(sample_file)
    print(result["summary"])