"""
Database CRUD & Analytics Service Layer (TASK-FS6)
Provides typed querying, persisting, and aggregation helper functions.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from src.db.models import (
    Repository,
    AnalysisRun,
    EvalExperiment,
    UserFeedback,
    AuditLog,
)

logger = logging.getLogger("ai_engineer.db.crud")


# ==========================================
# REPOSITORY CRUD
# ==========================================

def create_repository(
    db: Session,
    name: str,
    owner: Optional[str] = None,
    url: Optional[str] = None,
    default_branch: str = "main",
    primary_language: Optional[str] = None,
    total_files: int = 0,
    total_chunks: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
) -> Repository:
    repo = Repository(
        name=name,
        owner=owner,
        url=url,
        default_branch=default_branch,
        primary_language=primary_language,
        total_files=total_files,
        total_chunks=total_chunks,
        metadata_json=metadata or {},
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def get_repository(db: Session, repo_id: str) -> Optional[Repository]:
    return db.query(Repository).filter(Repository.id == repo_id).first()


def get_repository_by_name(db: Session, name: str) -> Optional[Repository]:
    return db.query(Repository).filter(Repository.name == name).first()


def list_repositories(db: Session, skip: int = 0, limit: int = 100) -> List[Repository]:
    return db.query(Repository).order_by(desc(Repository.created_at)).offset(skip).limit(limit).all()


# ==========================================
# ANALYSIS RUN CRUD
# ==========================================

def create_analysis_run(
    db: Session,
    filepath: str,
    status: str = "completed",
    attempts: int = 1,
    duration_ms: float = 0.0,
    has_vulnerabilities: bool = False,
    has_bugs: bool = False,
    agent_response: Optional[Dict[str, Any]] = None,
    review: Optional[Dict[str, Any]] = None,
    security_response: Optional[Dict[str, Any]] = None,
    patch_diff: Optional[str] = None,
    summary: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> AnalysisRun:
    run = AnalysisRun(
        repo_id=repo_id,
        filepath=filepath,
        status=status,
        attempts=attempts,
        duration_ms=duration_ms,
        has_vulnerabilities=has_vulnerabilities,
        has_bugs=has_bugs,
        agent_response=agent_response or {},
        review=review or {},
        security_response=security_response or {},
        patch_diff=patch_diff,
        summary=summary,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Log audit event
    create_audit_log(
        db,
        action="analysis_completed",
        entity_type="analysis_run",
        entity_id=run.id,
        details={"filepath": filepath, "status": status, "has_vulnerabilities": has_vulnerabilities},
    )

    return run


def get_analysis_run(db: Session, run_id: str) -> Optional[AnalysisRun]:
    return db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()


def list_analysis_runs(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    has_vulnerabilities: Optional[bool] = None,
) -> List[AnalysisRun]:
    query = db.query(AnalysisRun)
    if status:
        query = query.filter(AnalysisRun.status == status)
    if has_vulnerabilities is not None:
        query = query.filter(AnalysisRun.has_vulnerabilities == has_vulnerabilities)
    return query.order_by(desc(AnalysisRun.created_at)).offset(skip).limit(limit).all()


# ==========================================
# EVALUATION EXPERIMENT CRUD
# ==========================================

def create_eval_experiment(
    db: Session,
    experiment_name: str = "rag_triad_benchmark",
    test_cases_file: Optional[str] = None,
    total_test_cases: int = 0,
    mean_context_recall: float = 0.0,
    mean_context_precision: float = 0.0,
    mean_faithfulness: float = 0.0,
    mean_mrr: float = 0.0,
    hits_at_1_rate: float = 0.0,
    hits_at_3_rate: float = 0.0,
    hits_at_5_rate: float = 0.0,
    hits_at_10_rate: float = 0.0,
    results_summary: Optional[List[Dict[str, Any]]] = None,
) -> EvalExperiment:
    experiment = EvalExperiment(
        experiment_name=experiment_name,
        test_cases_file=test_cases_file,
        total_test_cases=total_test_cases,
        mean_context_recall=mean_context_recall,
        mean_context_precision=mean_context_precision,
        mean_faithfulness=mean_faithfulness,
        mean_mrr=mean_mrr,
        hits_at_1_rate=hits_at_1_rate,
        hits_at_3_rate=hits_at_3_rate,
        hits_at_5_rate=hits_at_5_rate,
        hits_at_10_rate=hits_at_10_rate,
        results_summary=results_summary or [],
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)

    create_audit_log(
        db,
        action="eval_experiment_recorded",
        entity_type="eval_experiment",
        entity_id=experiment.id,
        details={
            "experiment_name": experiment_name,
            "total_test_cases": total_test_cases,
            "mean_faithfulness": mean_faithfulness,
        },
    )

    return experiment


def get_eval_experiment(db: Session, experiment_id: str) -> Optional[EvalExperiment]:
    return db.query(EvalExperiment).filter(EvalExperiment.id == experiment_id).first()


def list_eval_experiments(db: Session, skip: int = 0, limit: int = 50) -> List[EvalExperiment]:
    return db.query(EvalExperiment).order_by(desc(EvalExperiment.created_at)).offset(skip).limit(limit).all()


# ==========================================
# USER FEEDBACK CRUD
# ==========================================

def create_user_feedback(
    db: Session,
    query: str,
    chunk_id: str,
    file_path: str,
    feedback_type: str,
    code_snippet: Optional[str] = None,
    user_comment: Optional[str] = None,
) -> UserFeedback:
    feedback = UserFeedback(
        query=query,
        chunk_id=chunk_id,
        file_path=file_path,
        code_snippet=code_snippet,
        feedback_type=feedback_type.lower(),
        user_comment=user_comment,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    create_audit_log(
        db,
        action="feedback_submitted",
        entity_type="user_feedback",
        entity_id=feedback.id,
        details={"chunk_id": chunk_id, "feedback_type": feedback_type},
    )

    return feedback


def list_user_feedback(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    feedback_type: Optional[str] = None,
) -> List[UserFeedback]:
    query = db.query(UserFeedback)
    if feedback_type:
        query = query.filter(UserFeedback.feedback_type == feedback_type.lower())
    return query.order_by(desc(UserFeedback.created_at)).offset(skip).limit(limit).all()


# ==========================================
# AUDIT LOG CRUD
# ==========================================

def create_audit_log(
    db: Session,
    action: str,
    actor: str = "system",
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    log = AuditLog(
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_audit_logs(db: Session, skip: int = 0, limit: int = 100) -> List[AuditLog]:
    return db.query(AuditLog).order_by(desc(AuditLog.created_at)).offset(skip).limit(limit).all()


# ==========================================
# AGGREGATE DASHBOARD METRICS
# ==========================================

def get_analytics_overview(db: Session) -> Dict[str, Any]:
    """
    Compute aggregate platform statistics across all models.
    """
    total_repos = db.query(func.count(Repository.id)).scalar() or 0
    total_analysis_runs = db.query(func.count(AnalysisRun.id)).scalar() or 0
    total_vulnerabilities_detected = (
        db.query(func.count(AnalysisRun.id))
        .filter(AnalysisRun.has_vulnerabilities == True)
        .scalar()
        or 0
    )
    
    total_feedback = db.query(func.count(UserFeedback.id)).scalar() or 0
    total_accepts = (
        db.query(func.count(UserFeedback.id))
        .filter(UserFeedback.feedback_type == "accept")
        .scalar()
        or 0
    )
    acceptance_rate = (total_accepts / total_feedback * 100.0) if total_feedback > 0 else 100.0

    # Latest eval metrics
    latest_eval = db.query(EvalExperiment).order_by(desc(EvalExperiment.created_at)).first()

    return {
        "total_repositories": total_repos,
        "total_analysis_runs": total_analysis_runs,
        "vulnerabilities_detected": total_vulnerabilities_detected,
        "feedback": {
            "total": total_feedback,
            "accepted": total_accepts,
            "rejected": total_feedback - total_accepts,
            "acceptance_rate_percent": round(acceptance_rate, 2),
        },
        "latest_eval_metrics": latest_eval.to_dict() if latest_eval else None,
    }
