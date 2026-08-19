"""
Pydantic Request & Response Schemas for FastAPI API (TASK-FS1)
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    database: str = "connected"
    vector_store: str = "ready"
    timestamp: str


class AnalyzeRequest(BaseModel):
    filepath: str = Field(..., description="Path to the file to analyze relative to repo or absolute")
    query: Optional[str] = Field(None, description="Optional custom query or instructions for analysis")


class AnalyzeResponse(BaseModel):
    filepath: str
    status: str
    agent_response: dict[str, Any]
    review: dict[str, Any]
    security_response: dict[str, Any]
    attempts: int


class ChunkSchema(BaseModel):
    id: str
    file_path: str
    start_line: int
    end_line: int
    type: str
    name: str
    code: str
    parent_name: Optional[str] = None
    imports: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(..., description="Semantic or keyword query")
    top_k: int = Field(5, ge=1, le=50)
    use_hybrid: bool = Field(True, description="Enable dense + BM25 hybrid search")
    rerank: bool = Field(True, description="Enable Cross-Encoder re-ranking")


class SearchResultItem(BaseModel):
    chunk: ChunkSchema
    score: float
    query: str


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]


class IndexRequest(BaseModel):
    repo_path: str = Field(..., description="Repository directory path to index")
    force_reindex: bool = Field(False, description="Re-index all files ignoring git diff cache")


class IndexResponse(BaseModel):
    status: str
    indexed_files: int
    total_chunks: int
    message: str


class EvalRequest(BaseModel):
    test_cases_file: Optional[str] = Field(None, description="Path to benchmark test cases JSON file")


class EvalResponse(BaseModel):
    status: str
    timestamp: str
    total_test_cases: int
    mean_context_recall: float
    mean_context_precision: float
    mean_faithfulness: float
    mean_mrr: float
    hits_at_1_rate: float
    hits_at_3_rate: float
    hits_at_5_rate: float
    hits_at_10_rate: float
    metrics: Optional[dict[str, Any]] = None
    results: list[dict[str, Any]]


class SecurityAuditRequest(BaseModel):
    filepath: str = Field(..., description="Path to source code file for SAST security audit")


class SecurityAuditResponse(BaseModel):
    filepath: str
    status: str
    scorecard: dict[str, Any]
    raw_response: dict[str, Any]


class TestGenRequest(BaseModel):
    filepath: str = Field(..., description="Path to code file requiring unit test generation")
    target_function: Optional[str] = Field(None, description="Optional target function name")


class TestGenResponse(BaseModel):
    filepath: str
    status: str
    generated_test_code: str
    execution_result: dict[str, Any]


class DocGenRequest(BaseModel):
    filepath: str = Field(..., description="Path to code file needing docstrings")


class DocGenResponse(BaseModel):
    filepath: str
    status: str
    updated_code: str
    verifier_report: dict[str, Any]


class FeedbackRequest(BaseModel):
    query: str
    chunk_id: str
    file_path: str
    code_snippet: str
    feedback_type: str = Field(..., description="ACCEPT or REJECT")
    user_comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    status: str
    event_id: str
    feedback_type: str
    message: str


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user' | 'assistant' | 'system'")
    content: str = Field(..., description="Message content")


class CodeChatRequest(BaseModel):
    question: str = Field(..., description="User question about code, diff, or security findings")
    filepath: Optional[str] = Field(None, description="Path or name of active file")
    file_code: Optional[str] = Field(None, description="Original source code of active file")
    proposed_fix: Optional[str] = Field(None, description="Proposed verified fix / diff")
    security_findings: Optional[list[dict[str, Any]]] = Field(default_factory=list, description="Security findings / OWASP issues")
    history: Optional[list[ChatMessage]] = Field(default_factory=list, description="Previous messages in the conversation")
    model: Optional[str] = Field("qwen-2.5-coder-32b", description="Target LLM model identifier")


class CodeChatResponse(BaseModel):
    answer: str = Field(..., description="LLM generated answer")
    model_used: str = Field(..., description="Model used to generate response")
    provider_used: str = Field(..., description="Provider used (groq, gemini, ollama, rule-engine)")
    line_references: list[int] = Field(default_factory=list, description="Line numbers referenced in the answer")
    files_referenced: list[str] = Field(default_factory=list, description="Files referenced in the answer")
    status: str = "completed"

