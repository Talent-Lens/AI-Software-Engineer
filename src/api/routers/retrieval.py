"""
Retrieval & Indexing Router (TASK-FS1)
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from src.api.schemas import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    ChunkSchema,
    IndexRequest,
    IndexResponse,
)
from src.indexing.vector_store import get_collection
from src.retrieval.retriever import HybridRetriever
from src.indexing.indexer import index_repository, index_repository_incremental

logger = logging.getLogger("ai_engineer.api.retrieval")
router = APIRouter(tags=["Retrieval & Indexing"])


@router.post("/retrieval/search", response_model=SearchResponse)
async def search_retrieval(request: SearchRequest) -> SearchResponse:
    """
    Hybrid dense vector + BM25 keyword search with Cross-Encoder re-ranking.
    """
    try:
        collection = get_collection(name="repo_index")
        retriever = HybridRetriever(collection=collection)

        results = retriever.retrieve(
            query=request.query,
            top_k=request.top_k,
            rerank=request.rerank,
        )

        items = []
        for r in results:
            chunk_data = ChunkSchema(
                id=r.chunk.id,
                file_path=r.chunk.file_path,
                start_line=r.chunk.start_line,
                end_line=r.chunk.end_line,
                type=r.chunk.type,
                name=r.chunk.name,
                code=r.chunk.code,
                parent_name=r.chunk.parent_name,
                imports=r.chunk.imports or [],
            )
            items.append(SearchResultItem(chunk=chunk_data, score=float(r.score), query=r.query))

        return SearchResponse(query=request.query, total=len(items), results=items)

    except Exception as err:
        logger.error("Retrieval search error: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {err}")


@router.post("/indexing/index", response_model=IndexResponse)
async def trigger_indexing(request: IndexRequest) -> IndexResponse:
    """
    Trigger full or incremental Git repository indexing into ChromaDB vector store.
    """
    try:
        if request.force_reindex:
            col = index_repository(folder_path=request.repo_path, reset=True, collection_name="repo_index")
            count = col.count() if hasattr(col, "count") else 0
            return IndexResponse(
                status="completed",
                indexed_files=-1,
                total_chunks=count,
                message=f"Full re-indexing completed for {request.repo_path}. Total chunks: {count}"
            )
        else:
            stats = index_repository_incremental(folder_path=request.repo_path, collection_name="repo_index")
            return IndexResponse(
                status="completed",
                indexed_files=stats.get("added_files_count", 0) + stats.get("modified_files_count", 0),
                total_chunks=stats.get("new_chunks_count", 0),
                message=f"Incremental indexing completed. {stats.get('new_chunks_count', 0)} chunks updated."
            )
    except Exception as err:
        logger.error("Indexing failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Indexing failed: {err}")
