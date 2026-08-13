"""
Human-in-the-Loop (HITL) Hard Negative Store (TASK-E9)

Captures user Accept/Reject feedback events, stores rejected code chunks in a
hard-negatives collection, and applies active learning penalty scoring to suppress
bad/rejected code patterns in future RAG queries.
"""

from __future__ import annotations

import enum
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from src.schema import Chunk, RetrievalResult

# ---------------------------------------------------------------------------
# Enums & Data Models
# ---------------------------------------------------------------------------

class FeedbackType(str, enum.Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass
class FeedbackEvent:
    event_id: str
    query: str
    chunk_id: str
    file_path: str
    code_snippet: str
    feedback_type: FeedbackType
    user_comment: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "query": self.query,
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "code_snippet": self.code_snippet,
            "feedback_type": self.feedback_type.value,
            "user_comment": self.user_comment,
            "timestamp": self.timestamp,
        }


@dataclass
class HardNegativeStats:
    total_events: int
    accept_count: int
    reject_count: int
    rejection_rate: float
    total_hard_negatives: int
    top_rejected_files: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_events": self.total_events,
            "accept_count": self.accept_count,
            "reject_count": self.reject_count,
            "rejection_rate": round(self.rejection_rate, 4),
            "total_hard_negatives": self.total_hard_negatives,
            "top_rejected_files": self.top_rejected_files,
        }


# ---------------------------------------------------------------------------
# Hard Negative Vector & Memory Store
# ---------------------------------------------------------------------------

class HardNegativeStore:
    """
    Active learning vector and persistent memory store for rejected hard-negative code chunks.
    """

    def __init__(self, storage_path: str = "hard_negatives_store.json"):
        self.storage_path = storage_path
        self.events: list[FeedbackEvent] = []
        self._event_counter = 1
        self._load_store()

    def _load_store(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        fb_type = FeedbackType.REJECT if item.get("feedback_type") == "REJECT" else FeedbackType.ACCEPT
                        self.events.append(
                            FeedbackEvent(
                                event_id=item["event_id"],
                                query=item["query"],
                                chunk_id=item["chunk_id"],
                                file_path=item["file_path"],
                                code_snippet=item["code_snippet"],
                                feedback_type=fb_type,
                                user_comment=item.get("user_comment"),
                                timestamp=item.get("timestamp", datetime.now().isoformat()),
                            )
                        )
                    self._event_counter = len(self.events) + 1
            except Exception:
                pass

    def _save_store(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in self.events], f, indent=2)
        except Exception:
            pass

    def record_feedback(
        self,
        query: str,
        chunk_id: str,
        file_path: str,
        code_snippet: str,
        feedback_type: str | FeedbackType,
        user_comment: str | None = None,
    ) -> FeedbackEvent:
        fb_enum = FeedbackType.REJECT if str(feedback_type).upper() == "REJECT" else FeedbackType.ACCEPT
        event_id = f"FB-{self._event_counter:04d}"
        self._event_counter += 1

        event = FeedbackEvent(
            event_id=event_id,
            query=query,
            chunk_id=chunk_id,
            file_path=file_path,
            code_snippet=code_snippet.strip(),
            feedback_type=fb_enum,
            user_comment=user_comment,
        )
        self.events.append(event)
        self._save_store()
        return event

    def get_rejected_chunks(self) -> list[FeedbackEvent]:
        return [e for e in self.events if e.feedback_type == FeedbackType.REJECT]


    def compute_similarity(self, text1: str, text2: str) -> float:
        """Computes TF-IDF / Jaccard token similarity between candidate code and rejected snippet."""
        words1 = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", text1.lower()))
        words2 = set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", text2.lower()))

        if not words1 or not words2:
            return 0.0

        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        return intersection / float(union) if union > 0 else 0.0

    def get_max_penalty_for_candidate(self, query: str, candidate_file: str, candidate_code: str) -> float:
        """
        Computes maximum similarity penalty score (0.0 to 1.0) against all stored rejected hard negatives.
        """
        rejected = self.get_rejected_chunks()
        if not rejected:
            return 0.0

        max_penalty = 0.0
        cand_text = f"{candidate_file} {candidate_code}"

        for rej in rejected:
            # File path match penalty boost
            file_boost = 1.2 if (rej.file_path and rej.file_path.lower() in candidate_file.lower()) else 1.0
            
            # Query match boost
            q_boost = 1.2 if (rej.query and self.compute_similarity(rej.query, query) > 0.3) else 1.0

            sim = self.compute_similarity(cand_text, f"{rej.file_path} {rej.code_snippet}")
            penalty = sim * file_boost * q_boost
            if penalty > max_penalty:
                max_penalty = penalty

        return min(1.0, max_penalty)

    def get_stats(self) -> HardNegativeStats:
        total = len(self.events)
        accepts = sum(1 for e in self.events if e.feedback_type == FeedbackType.ACCEPT)
        rejects = sum(1 for e in self.events if e.feedback_type == FeedbackType.REJECT)
        rate = (rejects / float(total)) if total > 0 else 0.0

        top_files: dict[str, int] = {}
        for e in self.events:
            if e.feedback_type == FeedbackType.REJECT and e.file_path:
                top_files[e.file_path] = top_files.get(e.file_path, 0) + 1

        return HardNegativeStats(
            total_events=total,
            accept_count=accepts,
            reject_count=rejects,
            rejection_rate=rate,
            total_hard_negatives=rejects,
            top_rejected_files=top_files,
        )


# Global Store Instance
GLOBAL_HARD_NEGATIVE_STORE = HardNegativeStore()


# ---------------------------------------------------------------------------
# Active Learning Reranker
# ---------------------------------------------------------------------------

class HardNegativeReranker:
    """
    Applies hard-negative similarity penalty deductions to retrieved search candidates,
    re-ranking bad/rejected candidate code patterns downward.
    """

    @classmethod
    def rerank(
        cls,
        query: str,
        candidates: Sequence[Chunk | RetrievalResult | dict[str, Any]],
        penalty_weight: float = 0.35,
        store: HardNegativeStore | None = None,
    ) -> list[dict[str, Any]]:
        target_store = store or GLOBAL_HARD_NEGATIVE_STORE
        penalized_results: list[dict[str, Any]] = []

        for rank, c in enumerate(candidates, start=1):
            chunk_obj = None
            c_file = ""
            c_code = ""
            c_id = ""
            base_score = 1.0 / float(rank)  # Default base rank score if un-scored

            if isinstance(c, Chunk):
                chunk_obj = c
                c_id = c.id
                c_file = c.file_path
                c_code = c.code
            elif isinstance(c, RetrievalResult):
                chunk_obj = c.chunk
                c_id = c.chunk.id
                c_file = c.chunk.file_path
                c_code = c.chunk.code
                base_score = c.score
            elif isinstance(c, dict):
                c_id = c.get("id", "")
                c_file = c.get("file_path", "")
                c_code = c.get("code", "")
                base_score = c.get("score", base_score)

            penalty_sim = target_store.get_max_penalty_for_candidate(query, c_file, c_code)
            penalty_deduction = penalty_sim * penalty_weight
            adjusted_score = max(0.0, base_score - penalty_deduction)

            penalized_results.append(
                {
                    "chunk": chunk_obj or {"id": c_id, "file_path": c_file, "code": c_code},
                    "original_score": round(base_score, 4),
                    "penalty_deduction": round(penalty_deduction, 4),
                    "adjusted_score": round(adjusted_score, 4),
                    "hard_negative_penalty_applied": penalty_deduction > 0.05,
                }
            )

        # Re-sort candidates descending by adjusted_score
        penalized_results.sort(key=lambda x: x["adjusted_score"], reverse=True)
        return penalized_results


# ---------------------------------------------------------------------------
# Public Entry Points
# ---------------------------------------------------------------------------

def record_user_feedback(
    query: str,
    chunk: Chunk | RetrievalResult | dict | str,
    feedback_type: str,
    user_comment: str | None = None,
    store: HardNegativeStore | None = None,
) -> dict[str, Any]:
    """
    Captures UI Accept/Reject feedback event via /api/v1/feedback endpoint logic.
    Stores rejected code chunks as hard-negatives for active learning.
    """
    target_store = store or GLOBAL_HARD_NEGATIVE_STORE

    c_id = "chunk_001"
    c_file = "unknown.py"
    c_code = ""

    if isinstance(chunk, Chunk):
        c_id = chunk.id
        c_file = chunk.file_path
        c_code = chunk.code
    elif isinstance(chunk, RetrievalResult):
        c_id = chunk.chunk.id
        c_file = chunk.chunk.file_path
        c_code = chunk.chunk.code
    elif isinstance(chunk, dict):
        c_id = chunk.get("id", "chunk_001")
        c_file = chunk.get("file_path", "unknown.py")
        c_code = chunk.get("code", str(chunk))
    elif isinstance(chunk, str):
        c_code = chunk

    event = target_store.record_feedback(
        query=query,
        chunk_id=c_id,
        file_path=c_file,
        code_snippet=c_code,
        feedback_type=feedback_type,
        user_comment=user_comment,
    )

    stats = target_store.get_stats()
    return {
        "status": "SUCCESS",
        "feedback_event": event.to_dict(),
        "stats": stats.to_dict(),
    }


def apply_hard_negative_penalties(
    query: str,
    candidates: Sequence[Chunk | RetrievalResult | dict[str, Any]],
    penalty_weight: float = 0.35,
    store: HardNegativeStore | None = None,
) -> list[dict[str, Any]]:
    """
    Applies active learning penalty scoring to retrieved candidates, re-ranking
    rejected code patterns downward.
    """
    return HardNegativeReranker.rerank(
        query=query, candidates=candidates, penalty_weight=penalty_weight, store=store
    )


def get_hard_negative_stats(store: HardNegativeStore | None = None) -> dict[str, Any]:
    """Returns active learning hard-negative telemetry stats."""
    target_store = store or GLOBAL_HARD_NEGATIVE_STORE
    return target_store.get_stats().to_dict()


if __name__ == "__main__":
    # Quick demo execution
    sample_query = "fix bare except in database handler"
    bad_chunk = Chunk(
        id="db.py::bad::1",
        file_path="src/db.py",
        start_line=1,
        end_line=10,
        type="function",
        name="bad",
        code="try:\n    pass\nexcept:\n    pass\n",
    )

    res = record_user_feedback(sample_query, bad_chunk, "REJECT", "Bare except is terrible!")
    print("[Feedback Recorded]:", res["feedback_event"])

    reranked = apply_hard_negative_penalties(sample_query, [bad_chunk])
    print("[Penalty Reranked Candidate]:", reranked[0])
