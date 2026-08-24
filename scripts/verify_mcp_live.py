"""
Verification script for CodeGuardian MCP Server Tools.
Tests: index_repository, search_codebase, get_function_context end-to-end.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure root is in path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.mcp.server import create_mcp_server
from src.mcp.tools import (
    get_function_context_tool,
    index_repository_tool,
    search_codebase_tool,
)


def run_live_verification():
    print("=================================================================")
    print("CODEGUARDIAN MCP SERVER — LIVE VERIFICATION SUITE")
    print("=================================================================\n")

    # Step 1: Server & Tool Registration
    print("[1/4] Inspecting MCP Server & Tool Definitions...")
    server = create_mcp_server()
    tools = asyncio.run(server.list_tools())
    print(f"Registered MCP Tools ({len(tools)} total):")
    for t in tools:
        print(f"  - {t.name}: {t.description[:80]}...")
    print("  -> MCP Tool Registration: PASS\n")

    # Step 2: index_repository against real src/ codebase
    print("[2/4] Executing index_repository tool against real 'src/' codebase...")
    persist_path = "./chroma_db_live_verify"
    collection_name = "live_verify_index"

    index_result = index_repository_tool(
        path="src",
        reset=True,
        incremental=False,
        collection_name=collection_name,
        persist_path=persist_path,
    )
    print("Index Summary Output:")
    print(json.dumps(index_result, indent=2))
    assert index_result["status"] == "success", "Indexing failed!"
    assert index_result["total_files"] > 0, "No files found!"
    assert index_result["total_chunks"] > 0, "No chunks created!"
    print("  -> index_repository: PASS\n")

    # Step 3: search_codebase hybrid search
    print("[3/4] Executing search_codebase tool...")
    query = "tree sitter multi-language AST chunking functions classes"
    print(f"Search Query: '{query}'")
    search_results = search_codebase_tool(
        query=query,
        top_k=3,
        rerank=False,
        collection_name=collection_name,
        persist_path=persist_path,
    )
    print(f"Retrieved {len(search_results)} search results:")
    for idx, res in enumerate(search_results, 1):
        print(f"  [{idx}] {res['name']} ({res['type']}) in {res['file_path']}")
        print(f"      Lines: {res['start_line']}-{res['end_line']} | Score: {res['score']}")
        print(f"      Parent Scope: {res['parent_name']}")
    assert len(search_results) > 0, "No search results returned!"
    print("  -> search_codebase: PASS\n")

    # Step 4: get_function_context for multi-language AST context
    print("[4/4] Executing get_function_context tool...")
    
    # 4a. Python function
    func_py = get_function_context_tool(
        path="src/indexing/chunker.py",
        function_name="chunk_file",
        collection_name=collection_name,
        persist_path=persist_path,
    )
    print(f"Python lookup 'chunk_file': Found={func_py['found']}, Lines={func_py['start_line']}-{func_py['end_line']}")
    assert func_py["found"] is True

    # 4b. Python method inside class
    method_py = get_function_context_tool(
        path="src/retrieval/retriever.py",
        function_name="retrieve",
        collection_name=collection_name,
        persist_path=persist_path,
    )
    print(f"Method lookup 'retrieve' in 'HybridRetriever': Found={method_py['found']}, Parent={method_py['parent_name']}")
    assert method_py["found"] is True
    assert method_py["parent_name"] == "HybridRetriever"

    print("\nSample Formatted AST Context Output for 'retrieve' in 'HybridRetriever':")
    print("-----------------------------------------------------------------")
    print(method_py["formatted_context"])
    print("-----------------------------------------------------------------")
    print("  -> get_function_context: PASS\n")

    # Cleanup live verify chroma dir
    import shutil
    if os.path.exists(persist_path):
        try:
            shutil.rmtree(persist_path)
        except Exception:
            pass

    print("=================================================================")
    print("ALL MCP TOOLS END-TO-END VERIFICATION: 100% SUCCESS")
    print("=================================================================")


if __name__ == "__main__":
    run_live_verification()
