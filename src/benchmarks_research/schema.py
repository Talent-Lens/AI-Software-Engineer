"""
Normalized finding and benchmark schemas.
Standardizes findings across CodeGuardian, Semgrep, CodeQL, SonarQube, and Bandit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NormalizedFinding:
    """
    Unified representation of a security finding from any SAST/AI tool.
    """
    tool: str
    file_path: str
    line_start: int
    line_end: int
    cwe: Optional[str] = None
    severity: str = "MEDIUM"  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    rule_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "cwe": self.cwe,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "title": self.title,
            "description": self.description,
        }


@dataclass
class ToolExecutionResult:
    """
    Result of executing an analysis tool against a repository snapshot.
    """
    tool: str
    tool_version: str
    duration_s: float
    findings: List[NormalizedFinding] = field(default_factory=list)
    status: str = "completed"  # completed | failed | not_installed | unsupported_platform
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricSummary:
    """
    The 6 Standardized Benchmark Metrics.
    Undefined metrics (e.g. Precision when TP+FP=0, Localization/Classification when TP=0) are None ('n/a').
    """
    precision: Optional[float]
    recall: Optional[float]
    false_positive_rate: float  # False alarms per 1,000 LOC on clean code
    localization_accuracy: Optional[float]  # % of true findings within ±3 lines
    classification_accuracy: Optional[float]  # % of true findings matching exact/parent-child CWE
    scan_latency: float  # Wall-clock seconds per 1,000 LOC
    classification_family_accuracy: Optional[float] = None  # % of TPs sharing top-level MITRE CWE family
    counts: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "precision": round(self.precision, 4) if self.precision is not None else None,
            "recall": round(self.recall, 4) if self.recall is not None else None,
            "false_positive_rate": round(self.false_positive_rate, 4),
            "localization_accuracy": round(self.localization_accuracy, 4) if self.localization_accuracy is not None else None,
            "classification_accuracy": round(self.classification_accuracy, 4) if self.classification_accuracy is not None else None,
            "classification_family_accuracy": round(self.classification_family_accuracy, 4) if self.classification_family_accuracy is not None else None,
            "scan_latency": round(self.scan_latency, 4),
            "counts": self.counts,
        }
