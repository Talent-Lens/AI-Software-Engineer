# SCHEMA.md

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