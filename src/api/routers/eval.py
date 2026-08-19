"""
Evaluation Suite Router (TASK-FS1 & TASK-FS6)
"""
from __future__ import annotations

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas import EvalRequest, EvalResponse
from src.eval.eval_runner import RAGTriadEvalRunner
from src.db.session import get_db
from src.db import crud

logger = logging.getLogger("ai_engineer.api.eval")
router = APIRouter(tags=["Evaluation Suite"])


@router.post("/eval/run", response_model=EvalResponse)
async def run_eval_suite(
    request: EvalRequest,
    db: Session = Depends(get_db),
) -> EvalResponse:
    """
    Run RAG Triad Evaluation Suite (Context Recall, Context Precision, Faithfulness, MRR, Hits@K)
    and persist experiment results to enterprise database.
    """
    try:
        runner = RAGTriadEvalRunner()
        if request.test_cases_file:
            report = runner.run_eval(test_cases_path=request.test_cases_file)
        else:
            report = runner.run_eval()

        results_list = [r.to_dict() for r in report.results]

        # Persist experiment to database
        try:
            crud.create_eval_experiment(
                db=db,
                experiment_name="rag_triad_benchmark",
                test_cases_file=request.test_cases_file,
                total_test_cases=report.total_test_cases,
                mean_context_recall=report.mean_context_recall,
                mean_context_precision=report.mean_context_precision,
                mean_faithfulness=report.mean_faithfulness,
                mean_mrr=report.mean_mrr,
                hits_at_1_rate=report.hits_at_1_rate,
                hits_at_3_rate=report.hits_at_3_rate,
                hits_at_5_rate=report.hits_at_5_rate,
                hits_at_10_rate=report.hits_at_10_rate,
                results_summary=results_list,
            )
        except Exception as db_err:
            logger.warning("Failed to persist eval experiment to database: %s", db_err)

        return EvalResponse(
            status="completed",
            timestamp=datetime.now().isoformat(),
            total_test_cases=report.total_test_cases,
            mean_context_recall=report.mean_context_recall,
            mean_context_precision=report.mean_context_precision,
            mean_faithfulness=report.mean_faithfulness,
            mean_mrr=report.mean_mrr,
            hits_at_1_rate=report.hits_at_1_rate,
            hits_at_3_rate=report.hits_at_3_rate,
            hits_at_5_rate=report.hits_at_5_rate,
            hits_at_10_rate=report.hits_at_10_rate,
            metrics=report.to_dict()["metrics"],
            results=results_list,
        )

    except FileNotFoundError as fnf_err:
        logger.warning("Test cases file not found: %s", fnf_err)
        raise HTTPException(status_code=404, detail=str(fnf_err))
    except HTTPException:
        raise
    except Exception as err:
        logger.error("Error executing eval suite: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation runner failed: {err}")
