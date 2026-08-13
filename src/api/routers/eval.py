"""
Evaluation Suite Router (TASK-FS1)
"""
from __future__ import annotations

import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException
from src.api.schemas import EvalRequest, EvalResponse
from src.eval.eval_runner import RAGTriadEvalRunner

logger = logging.getLogger("ai_engineer.api.eval")
router = APIRouter(tags=["Evaluation Suite"])


@router.post("/eval/run", response_model=EvalResponse)
async def run_eval_suite(request: EvalRequest) -> EvalResponse:
    """
    Run RAG Triad Evaluation Suite (Context Recall, Context Precision, Faithfulness, MRR, Hits@K).
    """
    try:
        runner = RAGTriadEvalRunner()
        if request.test_cases_file:
            report = runner.run_eval(test_cases_path=request.test_cases_file)
        else:
            report = runner.run_eval()

        results_list = [r.to_dict() for r in report.results]

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
            results=results_list,
        )

    except Exception as err:
        logger.error("Error executing eval suite: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation runner failed: {err}")
