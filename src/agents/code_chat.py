import requests
import json
from indexing.vector_store import get_collection
from retrieval.rag import retrieve_context
from schema import AgentResponse

collection = get_collection(name="repo_index")


def code_chat(question: str, model="qwen2.5:3b") -> AgentResponse:
    results = retrieve_context(collection, question)
    context = "\n\n---\n\n".join(
        f"File: {r.chunk.file_path} ({r.chunk.type} {r.chunk.name})\n{r.chunk.code}"
        for r in results
    )

    prompt = f"""You are a code assistant answering questions about a codebase.

Context:
{context}

Question: {question}

Respond ONLY with JSON matching this structure:
{{"agent_name": "code_chat", "summary": "your answer here", "details": {{"files_referenced": ["list", "of", "file", "paths"]}}, "confidence": 0.0}}
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
            agent_name="code_chat",
            summary=f"Agent failed to run — is Ollama running? Error: {e}",
            details={"error": str(e)},
            confidence=None,
        )