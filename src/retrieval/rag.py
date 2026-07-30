import requests
from schema import Chunk, RetrievalResult


def retrieve_context(collection, query, n_results=3):
    results = collection.query(query_texts=[query], n_results=n_results)

    retrieval_results = []
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        chunk = Chunk(
            id=f"{meta['file_path']}::{meta['name']}::{meta['start_line']}",
            file_path=meta["file_path"],
            start_line=meta["start_line"],
            end_line=meta["end_line"],
            type=meta["type"],
            name=meta["name"],
            code=doc,
        )
        retrieval_results.append(RetrievalResult(chunk=chunk, score=dist, query=query))

    return retrieval_results


def build_prompt(question, retrieval_results):
    context = "\n\n---\n\n".join(
        f"File: {r.chunk.file_path}\n{r.chunk.code}" for r in retrieval_results
    )
    return f"""You are a code assistant. Use the following code context to answer the question.

Context:
{context}

Question: {question}

Answer:"""


def ask_ollama(prompt, model="llama3.2:1b"):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
    )
    return response.json()["response"]


def rag_query(collection, question):
    retrieval_results = retrieve_context(collection, question)
    prompt = build_prompt(question, retrieval_results)
    return ask_ollama(prompt)