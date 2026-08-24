"""
MCP Tools Implementation — CodeGuardian Security & Retrieval Engine.

Wraps existing AST chunker, ChromaDB vector store, BM25 indexer,
and Cross-Encoder reranker into standard tool callables.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from src.indexing.chunker import chunk_file, format_chunk_with_context
from src.indexing.git_indexer import GitIncrementalIndexer
from src.indexing.indexer import get_repository_files, index_repository as core_index_repository
from src.indexing.vector_store import get_collection
from src.retrieval.graph_rag import GraphRetriever
from src.retrieval.retriever import HybridRetriever
from src.schema import Chunk

logger = logging.getLogger("codeguardian.mcp.tools")


def index_repository_tool(
    path: str,
    reset: bool = False,
    incremental: bool = True,
    collection_name: str = "repo_index",
    persist_path: str = "./chroma_db",
) -> dict[str, Any]:
    """
    Indexes or re-indexes a codebase directory into the hybrid search pipeline.

    Args:
        path: Absolute or relative directory path of the codebase to index.
        reset: If True, purges existing index and builds from scratch.
        incremental: If True and the directory is a Git repo, uses Git diffs for fast incremental updates.
        collection_name: ChromaDB collection identifier (default: 'repo_index').
        persist_path: Directory where ChromaDB index files are persisted.

    Returns:
        Summary dict containing status, mode, files/chunks indexed, and execution latency.
    """
    start_time = time.perf_counter()
    target_path = Path(path).resolve()

    if not target_path.exists() or not target_path.is_dir():
        return {
            "status": "error",
            "message": f"Provided path '{path}' does not exist or is not a directory.",
            "path": str(target_path),
        }

    collection = get_collection(name=collection_name, persist_path=persist_path, reset=reset)

    # 1. Incremental Git indexing if applicable
    is_git_repo = (target_path / ".git").exists()
    if incremental and is_git_repo and not reset:
        try:
            indexer = GitIncrementalIndexer(
                repo_path=str(target_path),
                collection=collection,
                collection_name=collection_name,
            )
            retriever = HybridRetriever(collection=collection)
            result = indexer.index_incremental(retriever=retriever)
            result["mode"] = "incremental"
            result["path"] = str(target_path)
            result["collection_name"] = collection_name
            return result
        except Exception as err:
            logger.warning("Incremental indexing failed (%s), falling back to full indexing.", err)

    # 2. Full repository indexing
    try:
        repo_files = get_repository_files(str(target_path))
        all_chunks: list[Chunk] = []

        for fpath in repo_files:
            try:
                chunks = chunk_file(fpath)
                rel_path = os.path.relpath(fpath, str(target_path)).replace("\\", "/")
                for c in chunks:
                    c.file_path = rel_path
                all_chunks.extend(chunks)
            except Exception as err:
                logger.warning("Failed chunking file '%s': %s", fpath, err)

        if all_chunks:
            # If reset was not requested, clear existing IDs for re-indexed files to avoid duplicates
            if not reset:
                existing = collection.get()
                if existing and existing.get("ids"):
                    collection.delete(ids=existing["ids"])

            collection.add(
                documents=[c.code for c in all_chunks],
                ids=[c.id for c in all_chunks],
                metadatas=[
                    {
                        "file_path": c.file_path,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "type": c.type,
                        "name": c.name,
                        "parent_name": c.parent_name or "",
                        "imports": json.dumps(c.imports),
                    }
                    for c in all_chunks
                ],
            )

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return {
            "status": "success",
            "mode": "full",
            "path": str(target_path),
            "collection_name": collection_name,
            "total_files": len(repo_files),
            "total_chunks": len(all_chunks),
            "latency_ms": latency_ms,
        }
    except Exception as err:
        logger.error("Failed to index repository at '%s': %s", path, err)
        return {
            "status": "error",
            "message": str(err),
            "path": str(target_path),
        }


def search_codebase_tool(
    query: str,
    top_k: int = 5,
    rerank: bool = True,
    collection_name: str = "repo_index",
    persist_path: str = "./chroma_db",
    use_graph: bool = False,
    max_hops: int = 1,
) -> list[dict[str, Any]]:
    """
    Performs hybrid code search (Vector + BM25 + Reciprocal Rank Fusion + Cross-Encoder Reranking).

    Args:
        query: Natural language search query, security query, or code identifier.
        top_k: Maximum number of relevant code chunks to return (default: 5).
        rerank: Whether to apply Cross-Encoder neural re-ranking (default: True).
        collection_name: ChromaDB collection to search (default: 'repo_index').
        persist_path: Directory where ChromaDB index files are stored.
        use_graph: Whether to expand context with Codebase GraphRAG (default: False).
        max_hops: Graph exploration depth when use_graph is True.

    Returns:
        List of structured result dictionaries with relevance scores and formatted AST context.
    """
    collection = get_collection(name=collection_name, persist_path=persist_path, reset=False)
    hybrid_retriever = HybridRetriever(collection=collection)

    if use_graph:
        graph_retriever = GraphRetriever(hybrid_retriever=hybrid_retriever)
        results = graph_retriever.retrieve(
            query=query,
            top_k=top_k,
            enable_graph_expansion=True,
            max_hops=max_hops,
            rerank=rerank,
        )
    else:
        results = hybrid_retriever.retrieve(
            query=query,
            top_k=top_k,
            rerank=rerank,
        )

    formatted_results: list[dict[str, Any]] = []
    for r in results:
        chunk = r.chunk
        formatted_context = format_chunk_with_context(chunk)
        formatted_results.append(
            {
                "id": chunk.id,
                "file_path": chunk.file_path,
                "name": chunk.name,
                "type": chunk.type,
                "parent_name": chunk.parent_name,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "score": round(float(r.score), 4),
                "imports": chunk.imports,
                "code": chunk.code,
                "formatted_context": formatted_context,
            }
        )

    return formatted_results


def get_function_context_tool(
    path: str,
    function_name: str,
    collection_name: str = "repo_index",
    persist_path: str = "./chroma_db",
) -> dict[str, Any]:
    """
    Retrieves full AST context for a specific function, method, or class within a file.
    Includes enclosing parent class/struct hierarchy, top-level imports, and line bounds.

    Args:
        path: Path to the source code file (relative or absolute).
        function_name: Name of the function, method, or class to inspect.
        collection_name: ChromaDB collection fallback if file is not on local path.
        persist_path: ChromaDB persistence directory.

    Returns:
        Dictionary containing the formatted context string, AST metadata, imports, and source code.
    """
    target_file = Path(path).resolve()
    matched_chunk: Chunk | None = None

    # 1. Parse directly from file on disk if available
    if target_file.exists() and target_file.is_file():
        try:
            chunks = chunk_file(str(target_file))
            # Exact match first
            for c in chunks:
                if c.name == function_name:
                    matched_chunk = c
                    break
            # Case-insensitive or suffix/prefix fallback
            if matched_chunk is None:
                for c in chunks:
                    if function_name.lower() in c.name.lower() or c.name.lower() in function_name.lower():
                        matched_chunk = c
                        break
        except Exception as err:
            logger.warning("Error parsing file '%s': %s", target_file, err)

    # 2. Fallback: Search ChromaDB collection
    if matched_chunk is None:
        try:
            collection = get_collection(name=collection_name, persist_path=persist_path, reset=False)
            norm_rel_path = path.replace("\\", "/")
            
            # Query by metadata filter
            records = collection.get(
                where={"$and": [{"name": function_name}, {"file_path": norm_rel_path}]}
            )
            if not records or not records.get("documents"):
                # Query by name alone
                records = collection.get(where={"name": function_name})

            if records and records.get("documents"):
                doc = records["documents"][0]
                meta = records["metadatas"][0]
                doc_id = records["ids"][0]
                raw_imports = meta.get("imports", "[]")
                try:
                    parsed_imports = json.loads(raw_imports) if raw_imports else []
                except Exception:
                    parsed_imports = []

                matched_chunk = Chunk(
                    id=doc_id,
                    file_path=meta.get("file_path", norm_rel_path),
                    start_line=int(meta.get("start_line", 1)),
                    end_line=int(meta.get("end_line", 1)),
                    type=meta.get("type", "function"),
                    name=meta.get("name", function_name),
                    code=doc,
                    parent_name=meta.get("parent_name") or None,
                    imports=parsed_imports,
                )
        except Exception as err:
            logger.warning("ChromaDB lookup for function '%s' failed: %s", function_name, err)

    if matched_chunk is None:
        return {
            "found": False,
            "message": f"Function '{function_name}' was not found in '{path}'.",
            "path": path,
            "function_name": function_name,
        }

    return {
        "found": True,
        "id": matched_chunk.id,
        "file_path": matched_chunk.file_path,
        "name": matched_chunk.name,
        "type": matched_chunk.type,
        "parent_name": matched_chunk.parent_name,
        "start_line": matched_chunk.start_line,
        "end_line": matched_chunk.end_line,
        "imports": matched_chunk.imports,
        "code": matched_chunk.code,
        "formatted_context": format_chunk_with_context(matched_chunk),
    }


__all__ = [
    "index_repository_tool",
    "search_codebase_tool",
    "get_function_context_tool",
]
