"""
Unit & Integration Test Suite for CodeGuardian MCP Server (Task: MCP Hybrid Retrieval Tools).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from src.mcp.server import create_mcp_server
from src.mcp.tools import (
    get_function_context_tool,
    index_repository_tool,
    search_codebase_tool,
)
from src.schema import Chunk


@pytest.fixture
def temp_sample_repo(tmp_path: Path):
    """Creates a temporary multi-language codebase for indexing and retrieval verification."""
    repo_dir = tmp_path / "sample_codebase"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # 1. Python file
    py_file = repo_dir / "auth_service.py"
    py_file.write_text(
        '"""Authentication service module."""\n'
        "import hmac\n"
        "import hashlib\n"
        "from typing import Optional\n\n"
        "class SecurityManager:\n"
        "    def __init__(self, secret_key: str):\n"
        "        self.secret_key = secret_key\n\n"
        "    def generate_auth_signature(self, payload: str) -> str:\n"
        '        """Generate HMAC-SHA256 signature for payload verification."""\n'
        "        return hmac.new(self.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()\n\n"
        "def verify_token_payload(token: str, expected_sig: str) -> bool:\n"
        '    """Verifies token integrity using constant-time comparison."""\n'
        "    return hmac.compare_digest(token, expected_sig)\n",
        encoding="utf-8",
    )

    # 2. TypeScript file
    ts_file = repo_dir / "payment_gateway.ts"
    ts_file.write_text(
        'import { AxiosInstance } from "axios";\n'
        'import { PaymentResult, ChargeOptions } from "./types";\n\n'
        "export class StripePaymentGateway {\n"
        "    private apiKey: string;\n\n"
        "    constructor(apiKey: string) {\n"
        "        this.apiKey = apiKey;\n"
        "    }\n\n"
        "    async processCreditCardCharge(amount: number, currency: string): Promise<PaymentResult> {\n"
        '        console.log(`Charging ${amount} ${currency}`);\n'
        '        return { success: true, transactionId: "tx_123456" };\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    # 3. Go file
    go_file = repo_dir / "server.go"
    go_file.write_text(
        "package main\n\n"
        'import (\n\t"fmt"\n\t"net/http"\n)\n\n'
        "type HttpServer struct {\n\tPort int\n}\n\n"
        "func (s *HttpServer) StartServer() error {\n"
        '\tfmt.Printf("Starting on port %d\\n", s.Port)\n'
        "\treturn nil\n"
        "}\n",
        encoding="utf-8",
    )

    chroma_dir = tmp_path / "test_chroma_db"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    return {
        "repo_dir": str(repo_dir),
        "chroma_dir": str(chroma_dir),
        "py_file": str(py_file),
        "ts_file": str(ts_file),
        "go_file": str(go_file),
    }


def test_mcp_server_tool_registration():
    """Verify that all MCP tools are registered with correct schemas on MCPServer."""
    from src.mcp.server import HAS_MCP, create_mcp_server
    if not HAS_MCP:
        pytest.skip("mcp SDK not installed in this Python environment (requires Python >= 3.10).")

    server = create_mcp_server()
    tools = asyncio.run(server.list_tools())
    tool_names = [t.name for t in tools]

    assert "index_repository" in tool_names
    assert "search_codebase" in tool_names
    assert "get_function_context" in tool_names

    # Check tool schemas
    index_tool = next(t for t in tools if t.name == "index_repository")
    assert "path" in index_tool.input_schema["properties"]
    assert "incremental" in index_tool.input_schema["properties"]

    search_tool = next(t for t in tools if t.name == "search_codebase")
    assert "query" in search_tool.input_schema["properties"]
    assert "top_k" in search_tool.input_schema["properties"]

    func_tool = next(t for t in tools if t.name == "get_function_context")
    assert "path" in func_tool.input_schema["properties"]
    assert "function_name" in func_tool.input_schema["properties"]


def test_index_repository_tool_full(temp_sample_repo):
    """Test full repository indexing tool across Python, TypeScript, and Go."""
    repo_path = temp_sample_repo["repo_dir"]
    persist_path = temp_sample_repo["chroma_dir"]

    result = index_repository_tool(
        path=repo_path,
        reset=True,
        incremental=False,
        collection_name="test_mcp_repo",
        persist_path=persist_path,
    )

    assert result["status"] == "success"
    assert result["mode"] == "full"
    assert result["total_files"] == 3
    assert result["total_chunks"] >= 4
    assert result["latency_ms"] > 0


def test_index_repository_invalid_path():
    """Test handling of non-existent directory paths."""
    result = index_repository_tool(
        path="/non/existent/path/for/sure_12345",
        collection_name="test_invalid",
    )
    assert result["status"] == "error"
    assert "does not exist" in result["message"]


def test_search_codebase_tool_hybrid_and_rerank(temp_sample_repo):
    """Test search_codebase_tool with hybrid retrieval and cross-encoder reranking."""
    repo_path = temp_sample_repo["repo_dir"]
    persist_path = temp_sample_repo["chroma_dir"]

    # Index first
    index_repository_tool(
        path=repo_path,
        reset=True,
        incremental=False,
        collection_name="test_search_repo",
        persist_path=persist_path,
    )

    # 1. Search for HMAC signature logic
    results = search_codebase_tool(
        query="generate HMAC SHA256 security signature",
        top_k=3,
        rerank=True,
        collection_name="test_search_repo",
        persist_path=persist_path,
    )

    assert len(results) >= 1
    top_result = results[0]
    assert "auth_service.py" in top_result["file_path"]
    assert "generate_auth_signature" in top_result["name"] or "SecurityManager" in top_result["name"]
    assert "formatted_context" in top_result
    assert "Imports / Package Statements:" in top_result["formatted_context"]

    # 2. Search for credit card processing in TypeScript
    ts_results = search_codebase_tool(
        query="credit card payment charge transaction",
        top_k=2,
        rerank=False,
        collection_name="test_search_repo",
        persist_path=persist_path,
    )
    assert len(ts_results) >= 1
    assert any("payment_gateway.ts" in r["file_path"] for r in ts_results)


def test_get_function_context_tool_multilanguage(temp_sample_repo):
    """Test get_function_context_tool for Python, TS, and Go with parent scope and imports."""
    py_path = temp_sample_repo["py_file"]
    ts_path = temp_sample_repo["ts_file"]
    go_path = temp_sample_repo["go_file"]

    # 1. Python method inside class
    res_py = get_function_context_tool(
        path=py_path,
        function_name="generate_auth_signature",
    )
    assert res_py["found"] is True
    assert res_py["name"] == "generate_auth_signature"
    assert res_py["parent_name"] == "SecurityManager"
    assert res_py["type"] == "method"
    assert any("import hmac" in imp for imp in res_py["imports"])
    assert "Enclosing Scope: method 'generate_auth_signature' in 'SecurityManager'" in res_py["formatted_context"]

    # 2. TypeScript method inside class
    res_ts = get_function_context_tool(
        path=ts_path,
        function_name="processCreditCardCharge",
    )
    assert res_ts["found"] is True
    assert res_ts["name"] == "processCreditCardCharge"
    assert res_ts["parent_name"] == "StripePaymentGateway"
    assert any("AxiosInstance" in imp for imp in res_ts["imports"])

    # 3. Go method with struct receiver
    res_go = get_function_context_tool(
        path=go_path,
        function_name="StartServer",
    )
    assert res_go["found"] is True
    assert res_go["name"] == "StartServer"
    assert res_go["parent_name"] == "HttpServer"

    # 4. Non-existent function
    res_missing = get_function_context_tool(
        path=py_path,
        function_name="non_existent_function_xyz",
    )
    assert res_missing["found"] is False


def test_index_persistence_across_sessions(temp_sample_repo):
    """Test that indexed data persists in ChromaDB without needing re-indexing."""
    repo_path = temp_sample_repo["repo_dir"]
    persist_path = temp_sample_repo["chroma_dir"]

    # Step 1: Index repository
    index_repository_tool(
        path=repo_path,
        reset=True,
        collection_name="persistence_test_repo",
        persist_path=persist_path,
    )

    # Step 2: Search in a brand new tool invocation without calling index_repository
    results = search_codebase_tool(
        query="verify token payload digest",
        top_k=2,
        collection_name="persistence_test_repo",
        persist_path=persist_path,
    )

    assert len(results) >= 1
    assert any("verify_token_payload" in r["name"] for r in results)
