# SCHEMA.md

## Target repo (Day 0)
We're using `psf/requests` (github.com/psf/requests) as our sample repo to index/test against.
Cloned locally at: D:\test-repos\requests

## Chunk
- id: str
- file_path: str
- start_line: int
- end_line: int
- type: str        # "function" | "class" | "method"
- name: str
- code: str
- embedding: list[float] | None

## RetrievalResult
- chunk: Chunk
- score: float
- query: str

## AgentResponse
- agent_name: str
- summary: str
- details: dict
- confidence: float | None