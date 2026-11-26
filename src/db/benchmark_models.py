"""
Research-Grade Benchmark Database Models (Completely Isolated from Core App).
Represents independent ground truth, competitor executions, and the 6 standardized metrics.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import relationship
from src.db.models import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


BENCHMARK_SCHEMA = "benchmark"


class ResearchRepo(Base):
    """
    Independent research benchmark repositories with pinned commit SHAs.
    Only repositories stored here contribute to macro-averages.
    """
    __tablename__ = "research_repos"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True, index=True)
    url = Column(String(1024), nullable=False)
    pinned_sha = Column(String(64), nullable=True, comment="Vulnerable pre-fix or pinned baseline commit")
    clean_sha = Column(String(64), nullable=True, comment="Post-fix clean commit for False Positive Rate calculation")
    language = Column(String(50), nullable=True, default="unknown", index=True)
    loc = Column(Integer, nullable=True, default=None, comment="Lines of code (LOC)")
    ground_truth_path = Column(String(1024), nullable=True, default="", comment="Relative path to version-controlled JSON/YAML")
    added_by = Column(String(100), default="system")
    status = Column(String(50), default="pending", index=True)  # pending | running | done | failed | needs_attention
    cve_id = Column(String(50), nullable=True, index=True)
    user_cwe = Column(String(50), nullable=True)
    repo_type = Column(String(50), default="cve_fix", index=True, comment="cve_fix | intentionally_vulnerable")
    fix_commit = Column(String(64), nullable=True)
    parent_commit = Column(String(64), nullable=True)
    label_quality = Column(String(20), default="provisional", index=True)  # provisional | verified
    is_excluded = Column(Boolean, default=False, index=True)
    exclusion_reason = Column(Text, nullable=True)
    job_stage = Column(String(50), default="queued", index=True)  # queued | resolving | cloning | labeling | scanning | computing | done | needs_attention | failed
    job_progress = Column(Float, default=0.0)
    job_error = Column(Text, nullable=True)
    last_heartbeat = Column(DateTime(timezone=True), default=utc_now)
    ignored_candidates = Column(JSON, default=list)
    scope_override = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    runs = relationship("BenchmarkRun", back_populates="repo", cascade="all, delete-orphan")
    findings = relationship("BenchmarkFinding", back_populates="repo", cascade="all, delete-orphan")
    metrics = relationship("BenchmarkMetric", back_populates="repo", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "pinned_sha": self.pinned_sha if self.pinned_sha and self.pinned_sha not in ("resolving", "") else None,
            "clean_sha": self.clean_sha if self.clean_sha and self.clean_sha not in ("resolving", "") else None,
            "language": self.language,
            "loc": self.loc,
            "ground_truth_path": self.ground_truth_path,
            "added_by": self.added_by,
            "status": self.status,
            "cve_id": self.cve_id,
            "repo_type": self.repo_type or "cve_fix",
            "fix_commit": self.fix_commit,
            "parent_commit": self.parent_commit,
            "label_quality": self.label_quality or "provisional",
            "is_excluded": bool(self.is_excluded),
            "exclusion_reason": self.exclusion_reason,
            "job_stage": self.job_stage or "done",
            "job_progress": round(self.job_progress or 0.0, 2),
            "job_error": self.job_error,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "ignored_candidates": self.ignored_candidates or [],
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BenchmarkRun(Base):
    """
    Execution run record for a specific tool against a research repo at pinned SHA.
    """
    __tablename__ = "benchmark_runs"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repo_id = Column(String(36), ForeignKey(f"{BENCHMARK_SCHEMA}.research_repos.id", ondelete="CASCADE"), nullable=False, index=True)
    tool = Column(String(50), nullable=False, index=True)  # codeguardian | semgrep | codeql | sonarqube | bandit
    tool_version = Column(String(100), default="unknown")
    started_at = Column(DateTime(timezone=True), default=utc_now)
    duration_s = Column(Float, default=0.0)
    raw_output_path = Column(String(1024), nullable=True)
    status = Column(String(50), default="completed", index=True)  # completed | failed | running | timed_out | not_installed | docker_not_running | unsupported_platform
    error_message = Column(Text, nullable=True)
    run_metadata = Column(JSON, default=dict)
    run_version = Column(Integer, default=1, index=True)
    is_superseded = Column(Boolean, default=False, index=True)

    # Relationships
    repo = relationship("ResearchRepo", back_populates="runs")
    findings = relationship("BenchmarkFinding", back_populates="run", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "duration_s": round(self.duration_s, 2),
            "status": self.status,
            "error_message": self.error_message,
            "metadata": self.run_metadata or {},
            "run_version": self.run_version or 1,
            "is_superseded": bool(self.is_superseded),
        }


class BenchmarkFinding(Base):
    """
    Normalized finding from a tool execution mapped against ground-truth items.
    """
    __tablename__ = "benchmark_findings"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), ForeignKey(f"{BENCHMARK_SCHEMA}.benchmark_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    repo_id = Column(String(36), ForeignKey(f"{BENCHMARK_SCHEMA}.research_repos.id", ondelete="CASCADE"), nullable=False, index=True)
    tool = Column(String(50), nullable=False, index=True)
    file_path = Column(String(1024), nullable=False)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    cwe = Column(String(50), nullable=True, index=True)
    normalized_cwe = Column(String(50), nullable=True)
    severity = Column(String(50), default="MEDIUM")
    rule_id = Column(String(255), nullable=True)
    match_result = Column(String(20), nullable=False, index=True)  # TP | FP | FN | clean-FP
    matched_ground_truth_id = Column(String(100), nullable=True)
    line_distance = Column(Integer, nullable=True, comment="Distance in lines from ground-truth vulnerability line")
    cwe_matched = Column(Boolean, default=False)
    raw_finding = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    run = relationship("BenchmarkRun", back_populates="findings")
    repo = relationship("ResearchRepo", back_populates="findings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "repo_id": self.repo_id,
            "tool": self.tool,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "cwe": self.cwe,
            "normalized_cwe": self.normalized_cwe,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "match_result": self.match_result,
            "matched_ground_truth_id": self.matched_ground_truth_id,
            "line_distance": self.line_distance,
            "cwe_matched": self.cwe_matched,
        }


class BenchmarkMetric(Base):
    """
    Standardized 6 metrics computed deterministically per (repo, tool).
    """
    __tablename__ = "benchmark_metrics"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repo_id = Column(String(36), ForeignKey(f"{BENCHMARK_SCHEMA}.research_repos.id", ondelete="CASCADE"), nullable=False, index=True)
    tool = Column(String(50), nullable=False, index=True)
    tool_version = Column(String(100), default="unknown")

    # The 6 Standardized Metrics
    precision = Column(Float, default=0.0, comment="TP / (TP + FP) over vulnerable version")
    recall = Column(Float, default=0.0, comment="TP / (TP + FN) against labeled vulnerabilities")
    false_positive_rate = Column(Float, default=0.0, comment="Clean-FPs per 1,000 LOC on post-fix version")
    localization_accuracy = Column(Float, default=0.0, comment="% true findings within ±3 lines")
    classification_accuracy = Column(Float, default=0.0, comment="% true findings matching CWE")
    scan_latency = Column(Float, default=0.0, comment="Seconds per 1,000 LOC with tool warmed up")

    # Counts & Supporting Proof
    counts_json = Column(JSON, default=dict, comment="Detailed integer counts {tp, fp, fn, clean_fp, loc, etc.}")
    run_version = Column(Integer, default=1, index=True)
    is_superseded = Column(Boolean, default=False, index=True)
    computed_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    repo = relationship("ResearchRepo", back_populates="metrics")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "localization_accuracy": round(self.localization_accuracy, 4),
            "classification_accuracy": round(self.classification_accuracy, 4),
            "scan_latency": round(self.scan_latency, 4),
            "counts": self.counts_json or {},
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
        }


class BenchmarkDeletionAudit(Base):
    """
    Immutable audit log of deleted benchmark repositories.
    Survives repository deletion to preserve scientific accountability.
    """
    __tablename__ = "benchmark_deletion_audits"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repo_id = Column(String(36), nullable=False, index=True)
    repo_name = Column(String(255), nullable=False)
    repo_url = Column(String(1024), nullable=False)
    cve_id = Column(String(50), nullable=True)
    had_completed_run = Column(Boolean, default=False)
    was_counted_in_averages = Column(Boolean, default=False)
    completed_runs_count = Column(Integer, default=0)
    reason = Column(Text, nullable=True)
    deleted_by = Column(String(100), default="admin")
    deleted_at = Column(DateTime(timezone=True), default=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "repo_name": self.repo_name,
            "repo_url": self.repo_url,
            "cve_id": self.cve_id,
            "had_completed_run": bool(self.had_completed_run),
            "was_counted_in_averages": bool(self.was_counted_in_averages),
            "completed_runs_count": self.completed_runs_count or 0,
            "reason": self.reason,
            "deleted_by": self.deleted_by,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class SampledPrecisionAudit(Base):
    """
    Append-only audit rows for blinded sampled-precision triage.
    """
    __tablename__ = "sampled_precision_audits"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    audit_version = Column(Integer, default=1, nullable=False, index=True)
    sample_id = Column(String(50), nullable=False, index=True)
    tool = Column(String(50), nullable=False, index=True)
    repo_id = Column(String(36), nullable=False, index=True)
    finding_id = Column(String(36), nullable=False)
    file_path = Column(String(1024), nullable=False)
    line_start = Column(Integer, nullable=False)
    cwe = Column(String(50), nullable=True)
    label = Column(String(32), nullable=False)  # true_vuln | false_alarm | uncertain
    notes = Column(Text, nullable=True)
    labeled_by = Column(String(100), default="user")
    created_at = Column(DateTime(timezone=True), default=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "audit_version": self.audit_version,
            "sample_id": self.sample_id,
            "tool": self.tool,
            "repo_id": self.repo_id,
            "finding_id": self.finding_id,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "cwe": self.cwe,
            "label": self.label,
            "notes": self.notes,
            "labeled_by": self.labeled_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BenchmarkLatencyPass(Base):
    """
    Append-only isolated sequential latency measurement pass (separate from detection runs).
    Measures every installed tool on the vulnerable commit's filtered copy with N repeats.
    """
    __tablename__ = "benchmark_latency_passes"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    pass_version = Column(Integer, default=1, nullable=False, index=True)
    is_superseded = Column(Boolean, default=False, index=True)
    status = Column(String(32), default="running", nullable=False, index=True)  # running | completed | failed
    repeats = Column(Integer, default=3, nullable=False)
    repo_ids = Column(JSON, default=list)
    host_info = Column(JSON, default=dict)
    scope_policy_hash = Column(String(64), nullable=False)
    tool_versions = Column(JSON, default=dict)
    tool_rulesets = Column(JSON, default=dict)
    results_json = Column(JSON, default=dict)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pass_version": self.pass_version,
            "is_superseded": bool(self.is_superseded),
            "status": self.status,
            "repeats": self.repeats,
            "repo_ids": self.repo_ids or [],
            "host_info": self.host_info or {},
            "scope_policy_hash": self.scope_policy_hash,
            "tool_versions": self.tool_versions or {},
            "tool_rulesets": self.tool_rulesets or {},
            "results": self.results_json or {},
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class BenchmarkSnapshot(Base):
    """
    Imported benchmark snapshot metadata (and previous snapshot payload for rollback).
    """
    __tablename__ = "benchmark_snapshots"
    __table_args__ = {"schema": BENCHMARK_SCHEMA}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    snapshot_id = Column(String(64), nullable=False, index=True)
    schema_version = Column(String(20), nullable=False)
    sha256 = Column(String(64), nullable=False)
    generated_at = Column(String(64), nullable=False)
    codeguardian_version = Column(String(64), nullable=True)
    repos_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, index=True)
    previous_snapshot_id = Column(String(36), nullable=True)
    payload_json = Column(JSON, nullable=True)
    imported_at = Column(DateTime(timezone=True), default=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "generated_at": self.generated_at,
            "codeguardian_version": self.codeguardian_version,
            "repos_count": self.repos_count or 0,
            "is_active": bool(self.is_active),
            "previous_snapshot_id": self.previous_snapshot_id,
            "imported_at": self.imported_at.isoformat() if self.imported_at else None,
        }
