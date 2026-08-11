# src/schema.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chunk:
    id: str
    file_path: str
    start_line: int
    end_line: int
    type: str  # "function" | "class" | "method"
    name: str
    code: str
    embedding: list[float] | None = None


@dataclass
class RetrievalResult:
    chunk: Chunk
    score: float
    query: str


@dataclass
class AgentResponse:
    agent_name: str
    summary: str
    details: dict
    confidence: float | None = None