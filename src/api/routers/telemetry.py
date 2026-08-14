"""
OpenTelemetry & Agent Tracing API Router (TASK-FS5)
"""
from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query

from src.telemetry.tracer import collector, OTEL_AVAILABLE

logger = logging.getLogger("ai_engineer.api.telemetry")
router = APIRouter(tags=["Observability & Tracing"])


@router.get("/telemetry/metrics")
async def get_telemetry_metrics() -> Dict[str, Any]:
    """
    Get aggregated telemetry metrics: token consumption, latency breakdowns, and error rates.
    """
    return collector.get_metrics_summary()


@router.get("/telemetry/traces")
async def get_telemetry_traces(
    limit: int = Query(50, ge=1, le=500),
    span_name: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    """
    Query recent execution spans and traces with waterfall timestamps.
    """
    return collector.get_traces(limit=limit, span_name=span_name)


@router.get("/telemetry/status")
async def get_telemetry_status() -> Dict[str, Any]:
    """
    Check the status of OpenTelemetry and Arize Phoenix tracing integration.
    """
    phoenix_endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    
    return {
        "status": "active",
        "opentelemetry_installed": OTEL_AVAILABLE,
        "arize_phoenix_endpoint": phoenix_endpoint or "in_process_collector",
        "buffered_spans_count": len(collector._spans),
        "supported_tracers": ["agent_nodes", "http_requests", "llm_inferences", "rag_retrievals"],
    }


@router.post("/telemetry/reset")
async def reset_telemetry_buffer() -> Dict[str, Any]:
    """
    Reset in-memory telemetry spans and counters.
    """
    collector.reset()
    return {"status": "success", "message": "Telemetry buffer cleared."}
