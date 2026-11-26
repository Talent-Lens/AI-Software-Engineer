"""
Base benchmark runner interface.
Every competitor tool runner implements this contract.
"""
from __future__ import annotations

import abc
import shutil
import time
from pathlib import Path
from typing import Optional

from src.benchmarks_research.schema import ToolExecutionResult


class BaseBenchmarkRunner(abc.ABC):
    """Abstract interface for executing a static analysis tool against a target repository."""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check if tool CLI or dependencies are installed on the local system."""
        pass

    @abc.abstractmethod
    def get_version(self) -> str:
        """Get the installed version of the tool."""
        pass

    @abc.abstractmethod
    def run(self, repo_path: Path) -> ToolExecutionResult:
        """
        Execute the tool on the target repository directory and return normalized findings.
        """
        pass
