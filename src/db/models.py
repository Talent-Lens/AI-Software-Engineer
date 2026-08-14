"""
SQLAlchemy Database Models (TASK-FS6)
Enterprise Persistence for Repositories, Analysis Runs, Eval Experiments, Feedback, and Audit Logs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    DateTime,
    JSON,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Repository(Base):
    """
    Codebase repository metadata and indexing state.
    """
    __tablename__ = "repositories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, index=True)
    owner = Column(String(255), nullable=True)
    url = Column(String(1024), nullable=True)
    default_branch = Column(String(100), default="main")
    primary_language = Column(String(50), nullable=True)
    total_files = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    analysis_runs = relationship("AnalysisRun", back_populates="repository", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "url": self.url,
            "default_branch": self.default_branch,
            "primary_language": self.primary_language,
            "total_files": self.total_files,
            "total_chunks": self.total_chunks,
            "last_indexed_at": self.last_indexed_at.isoformat() if self.last_indexed_at else None,
            "metadata": self.metadata_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AnalysisRun(Base):
    """
    Historical record of LangGraph analysis & multi-agent pipeline executions.
    """
    __tablename__ = "analysis_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repo_id = Column(String(36), ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True)
    filepath = Column(String(1024), nullable=False, index=True)
    status = Column(String(50), default="completed", index=True)  # completed, failed, in_progress
    attempts = Column(Integer, default=1)
    duration_ms = Column(Float, default=0.0)
    has_vulnerabilities = Column(Boolean, default=False, index=True)
    has_bugs = Column(Boolean, default=False)
    
    agent_response = Column(JSON, default=dict)
    review = Column(JSON, default=dict)
    security_response = Column(JSON, default=dict)
    patch_diff = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    # Relationships
    repository = relationship("Repository", back_populates="analysis_runs")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "filepath": self.filepath,
            "status": self.status,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
            "has_vulnerabilities": self.has_vulnerabilities,
            "has_bugs": self.has_bugs,
            "agent_response": self.agent_response or {},
            "review": self.review or {},
            "security_response": self.security_response or {},
            "patch_diff": self.patch_diff,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalExperiment(Base):
    """
    RAG Triad & Benchmark evaluation runs for regression tracking.
    """
    __tablename__ = "eval_experiments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    experiment_name = Column(String(255), default="rag_triad_benchmark", index=True)
    test_cases_file = Column(String(1024), nullable=True)
    total_test_cases = Column(Integer, default=0)
    
    mean_context_recall = Column(Float, default=0.0)
    mean_context_precision = Column(Float, default=0.0)
    mean_faithfulness = Column(Float, default=0.0)
    mean_mrr = Column(Float, default=0.0)
    hits_at_1_rate = Column(Float, default=0.0)
    hits_at_3_rate = Column(Float, default=0.0)
    hits_at_5_rate = Column(Float, default=0.0)
    hits_at_10_rate = Column(Float, default=0.0)
    
    results_summary = Column(JSON, default=list)  # Detailed list of test case outputs
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "experiment_name": self.experiment_name,
            "test_cases_file": self.test_cases_file,
            "total_test_cases": self.total_test_cases,
            "mean_context_recall": self.mean_context_recall,
            "mean_context_precision": self.mean_context_precision,
            "mean_faithfulness": self.mean_faithfulness,
            "mean_mrr": self.mean_mrr,
            "hits_at_1_rate": self.hits_at_1_rate,
            "hits_at_3_rate": self.hits_at_3_rate,
            "hits_at_5_rate": self.hits_at_5_rate,
            "hits_at_10_rate": self.hits_at_10_rate,
            "results_summary": self.results_summary or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserFeedback(Base):
    """
    Human-in-the-loop feedback (Accept/Reject) on code chunk retrieval and AI generated fixes.
    """
    __tablename__ = "user_feedback"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    query = Column(Text, nullable=False)
    chunk_id = Column(String(255), nullable=False, index=True)
    file_path = Column(String(1024), nullable=False)
    code_snippet = Column(Text, nullable=True)
    feedback_type = Column(String(20), nullable=False, index=True)  # accept, reject
    user_comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "code_snippet": self.code_snippet,
            "feedback_type": self.feedback_type,
            "user_comment": self.user_comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    """
    Enterprise audit logs for compliance, security scans, and agent modifications.
    """
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    action = Column(String(100), nullable=False, index=True)  # e.g., "analyze_code", "eval_run", "user_feedback"
    actor = Column(String(100), default="system")
    entity_type = Column(String(50), nullable=True)  # e.g., "analysis_run", "eval_experiment"
    entity_id = Column(String(36), nullable=True, index=True)
    details = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "actor": self.actor,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": self.details or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
