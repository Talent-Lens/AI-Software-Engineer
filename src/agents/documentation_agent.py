import json
import requests
from src.indexing.chunker import chunk_file
from src.schema import AgentResponse
from src.agents.docstring_verifier import verify_file_docstrings, audit_and_fix_docstring


def generate_docs(file_path: str, model="qwen2.5:3b") -> AgentResponse:
    # First, run Docstring Accuracy Verifier on existing file functions
    verifier_res = verify_file_docstrings(file_path)

    chunks = chunk_file(file_path)
    functions = [c for c in chunks if c.type in ("function", "method")]

    if not functions:
        return AgentResponse(
            agent_name="documentation_agent",
            summary=f"No functions found in {file_path}.",
            details={"filepath": file_path, "verifier": verifier_res.get("details", {})},
            confidence=1.0,
        )

    code_summary = "\n\n".join(f"{c.name}:\n{c.code}" for c in functions[:5])  # cap for prompt size

    prompt = f"""You are a documentation assistant. Write clear Google-style docstring explanations for these functions.

Code:
{code_summary}

Respond ONLY with JSON matching this structure:
{{"agent_name": "documentation_agent", "summary": "one-line overview of the file", "details": {{"function_docs": {{"function_name": "explanation"}}}}, "confidence": 0.0}}
"""

    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
            },
            timeout=10,
        )
        response.raise_for_status()
        parsed = json.loads(response.json()["message"]["content"])
        parsed["details"]["accuracy_verification"] = verifier_res.get("details", {})
        return AgentResponse(**parsed)
    except Exception as e:
        # Fallback to local AST signature docstring verification and ground-truth generation
        fixed_docs = {}
        for func in functions[:5]:
            fixed = audit_and_fix_docstring(func.code)
            corrected = fixed.get("details", {}).get("corrected_docstring")
            if corrected:
                fixed_docs[func.name] = corrected

        return AgentResponse(
            agent_name="documentation_agent",
            summary=f"Docstrings generated and verified via AST signature auditor for {len(functions)} functions.",
            details={
                "error": str(e),
                "accuracy_verification": verifier_res.get("details", {}),
                "function_docs": fixed_docs,
            },
            confidence=verifier_res.get("confidence", 0.9),
        )