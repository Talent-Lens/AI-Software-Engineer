#!/usr/bin/env python3
"""
CLI Runner for CodeGuardian MCP Server.

Usage:
  python scripts/run_mcp_server.py
  python scripts/run_mcp_server.py --transport stdio
  python scripts/run_mcp_server.py --transport sse
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add workspace root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.mcp.server import main

if __name__ == "__main__":
    main()
