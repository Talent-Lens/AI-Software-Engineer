import json
import requests
from src.schema import Chunk, RetrievalResult
from src.indexing.chunker import format_chunk_with_context
from src.retrieval.retriever import HybridRetriever


def retrieve_context(collection, query, n_results=3, hybrid=True, rerank=False):
    if hybrid:
        retriever = HybridRetriever(collection=collection)
        return retriever.retrieve(query=query, top_k=n_results, rerank=rerank)

    results = collection.query(query_texts=[query], n_results=n_results)

    retrieval_results = []
    if not results or not results.get("documents") or not results["documents"][0]:
        return retrieval_results

    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        raw_imports = meta.get("imports", "[]")
        try:
            parsed_imports = json.loads(raw_imports) if raw_imports else []
        except Exception:
            parsed_imports = []

        chunk = Chunk(
            id=f"{meta['file_path']}::{meta['name']}::{meta['start_line']}",
            file_path=meta["file_path"],
            start_line=meta["start_line"],
            end_line=meta["end_line"],
            type=meta["type"],
            name=meta["name"],
            code=doc,
            parent_name=meta.get("parent_name") or None,
            imports=parsed_imports,
        )
        retrieval_results.append(RetrievalResult(chunk=chunk, score=dist, query=query))

    return retrieval_results


def build_prompt(question, retrieval_results):
    context = "\n\n---\n\n".join(
        format_chunk_with_context(r.chunk) for r in retrieval_results
    )
    return f"""You are a code assistant. Use the following code context to answer the question.

Context:
{context}

Question: {question}

Answer:"""


def ask_ollama(prompt, model="llama3.2:1b", timeout=60):
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("response", "No response content returned from Ollama.")
    except Exception as e:
        return f"Error querying Ollama ({model}): {e}"


def rag_query(collection, question):
    retrieval_results = retrieve_context(collection, question)
    prompt = build_prompt(question, retrieval_results)
    return ask_ollama(prompt)
