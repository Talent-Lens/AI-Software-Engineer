import requests
import json
from indexing.chunker import chunk_file
from schema import AgentResponse


def generate_docs(file_path: str, model="qwen2.5:3b") -> AgentResponse:
    chunks = chunk_file(file_path)
    functions = [c for c in chunks if c.type in ("function", "method")]

    code_summary = "\n\n".join(f"{c.name}:\n{c.code}" for c in functions[:5])  # cap for prompt size

    prompt = f"""You are a documentation assistant. Write clear docstring-style explanations for these functions.

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
            timeout=60,
        )
        response.raise_for_status()
        parsed = json.loads(response.json()["message"]["content"])
        return AgentResponse(**parsed)
    except Exception as e:
        return AgentResponse(
            agent_name="documentation_agent",
            summary=f"Agent failed to run — is Ollama running? Error: {e}",
            details={"error": str(e)},
            confidence=None,
        )