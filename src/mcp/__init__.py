"""
CodeGuardian MCP Package.

Exposes Model Context Protocol (MCP) server and tooling for code search and AST retrieval.
"""
from __future__ import annotations

from src.mcp.server import create_mcp_server
from src.mcp.tools import (
    get_function_context_tool,
    index_repository_tool,
    search_codebase_tool,
)

__all__ = [
    "create_mcp_server",
    "index_repository_tool",
    "search_codebase_tool",
    "get_function_context_tool",
]
