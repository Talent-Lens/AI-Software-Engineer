# src/schema.py
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel
from typing import Optional

@dataclass
class Chunk:
    id: str
    file_path: str
    start_line: int
    end_line: int
    type: str
    name: str
    code: str
    embedding: list[float] | None = None
    
from dataclasses import dataclass, field

@dataclass
class Chunk:
    id: str
    file_path: str
    start_line: int
    end_line: int
    type: str        # "function" | "class" | "method"
    name: str
    code: str
    embedding: list[float] | None = None

@dataclass
class RetrievalResult:
    chunk: Chunk
    score: float
    query: str

class AgentResponse(BaseModel):
    agent_name: str
    summary: str
    details: dict
    confidence: Optional[float] = None