"""
CodeGuardian Model Context Protocol (MCP) Server.

Exposes CodeGuardian's AST chunker, ChromaDB vector store, BM25 hybrid search,
and neural Cross-Encoder re-ranker as standardized MCP tools.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from src.mcp.tools import (
    get_function_context_tool,
    index_repository_tool,
    search_codebase_tool,
)

logger = logging.getLogger("codeguardian.mcp.server")

# ---------------------------------------------------------------------------
# MCP Server Instantiation
# ---------------------------------------------------------------------------
try:
    from mcp.server import MCPServer
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    MCPServer = Any  # type: ignore


def create_mcp_server() -> Any:
    """
    Creates and configures the CodeGuardian MCPServer instance with registered tools.
    """
    if not HAS_MCP:
        raise ImportError(
            "The 'mcp' SDK is required to run the MCP server. "
            "Please install it via 'pip install mcp>=1.0.0' with Python >= 3.10."
        )

    server = MCPServer(
        name="codeguardian-search",
        version="1.0.0",
        description=(
            "CodeGuardian Autonomous Multi-Agent Code Security & Retrieval Engine. "
            "Exposes hybrid AST retrieval, ChromaDB vector search, and Cross-Encoder re-ranking."
        ),
    )

    @server.tool(
        name="index_repository",
        description=(
            "Index or re-index a codebase repository into the hybrid search pipeline (ChromaDB + BM25). "
            "Supports fast incremental Git diff indexing for modified files and multi-language AST chunking "
            "(Python, JavaScript, TypeScript, Java, Go)."
        ),
    )
    def index_repository(
        path: str,
        reset: bool = False,
        incremental: bool = True,
        collection_name: str = "repo_index",
        persist_path: str = "./chroma_db",
    ) -> dict[str, Any]:
        """
        Index a local repository folder.

        :param path: Absolute or relative directory path of the codebase.
        :param reset: Set to True to wipe the existing index and re-index from scratch.
        :param incremental: Set to True to use fast Git-diff incremental indexing when available.
        :param collection_name: ChromaDB collection identifier (default: 'repo_index').
        :param persist_path: Directory path for ChromaDB persistent index storage.
        """
        return index_repository_tool(
            path=path,
            reset=reset,
            incremental=incremental,
            collection_name=collection_name,
            persist_path=persist_path,
        )

    @server.tool(
        name="search_codebase",
        description=(
            "Execute hybrid code search across the indexed repository using dense vector search "
            "(ChromaDB + BAAI/bge-m3), sparse BM25 keyword matching, Reciprocal Rank Fusion (RRF), "
            "and Cross-Encoder neural re-ranking (cross-encoder/ms-marco-MiniLM-L-6-v2)."
        ),
    )
    def search_codebase(
        query: str,
        top_k: int = 5,
        rerank: bool = True,
        collection_name: str = "repo_index",
        persist_path: str = "./chroma_db",
        use_graph: bool = False,
        max_hops: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Search indexed codebase for relevant functions, classes, and logic.

        :param query: Natural language search query, bug description, or symbol identifier.
        :param top_k: Maximum number of relevant code chunks to return.
        :param rerank: If True, applies Cross-Encoder neural re-ranking to candidate chunks.
        :param collection_name: ChromaDB collection to search against.
        :param persist_path: Directory path for ChromaDB storage.
        :param use_graph: If True, uses GraphRAG expansion across call and inheritance graphs.
        :param max_hops: Maximum graph traversal hops when use_graph is True.
        """
        return search_codebase_tool(
            query=query,
            top_k=top_k,
            rerank=rerank,
            collection_name=collection_name,
            persist_path=persist_path,
            use_graph=use_graph,
            max_hops=max_hops,
        )

    @server.tool(
        name="get_function_context",
        description=(
            "Fetch the complete AST context for a function, method, or class within a file. "
            "Returns top-of-file imports, enclosing parent class/struct hierarchy, start/end lines, "
            "and clean compilable context."
        ),
    )
    def get_function_context(
        path: str,
        function_name: str,
        collection_name: str = "repo_index",
        persist_path: str = "./chroma_db",
    ) -> dict[str, Any]:
        """
        Retrieve AST context for a specific function or class.

        :param path: Source code file path.
        :param function_name: Function, method, or class name to look up.
        :param collection_name: Fallback collection for metadata lookup.
        :param persist_path: Directory path for ChromaDB storage.
        """
        return get_function_context_tool(
            path=path,
            function_name=function_name,
            collection_name=collection_name,
            persist_path=persist_path,
        )

    return server


# ---------------------------------------------------------------------------
# CLI Entrypoint & Transport Runner
# ---------------------------------------------------------------------------
def main() -> None:
    """Run the MCP server over stdio or SSE transport."""
    parser = argparse.ArgumentParser(description="CodeGuardian MCP Retrieval Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use (default: stdio)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # IMPORTANT: stdio transport uses stdout for JSON-RPC
    )

    server = create_mcp_server()
    logger.info("Starting CodeGuardian MCP server with '%s' transport...", args.transport)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
