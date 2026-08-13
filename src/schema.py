# src/schema.py
from __future__ import annotations

from dataclasses import dataclass, field
from pydantic import BaseModel
from typing import Optional, Any


@dataclass
class Chunk:
    id: str
    file_path: str
    start_line: int
    end_line: int
    type: str  # "function" | "class" | "method" | "code_block"
    name: str
    code: str
    parent_name: str | None = None
    imports: list[str] = field(default_factory=list)
    embedding: list[float] | None = None


@dataclass
class RetrievalResult:
    chunk: Chunk
    score: float
    query: str


class AgentResponse(BaseModel):
    agent_name: str
    summary: str
    details: dict[str, Any]
    confidence: Optional[float] = None
