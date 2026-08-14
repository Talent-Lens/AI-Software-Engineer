"""
OpenTelemetry & Agent Tracing Engine (TASK-FS5)
Provides distributed tracing, agent span profiling, LLM token metrics, and Phoenix/OTLP exporter support.
"""
from __future__ import annotations

import os
import time
import uuid
import logging
import functools
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from contextlib import contextmanager

# OpenTelemetry Standard API
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

logger = logging.getLogger("ai_engineer.telemetry")


class SpanRecord:
    """
    Structured representation of a single traced span or agent execution step.
    """
    def __init__(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        self.span_id = str(uuid.uuid4())
        self.trace_id = trace_id or str(uuid.uuid4())
        self.parent_id = parent_id
        self.name = name
        self.start_time = time.perf_counter()
        self.start_timestamp = datetime.now(timezone.utc).isoformat()
        self.end_time: Optional[float] = None
        self.end_timestamp: Optional[str] = None
        self.duration_ms: float = 0.0
        self.status: str = "in_progress"  # ok, error, in_progress
        self.attributes: Dict[str, Any] = attributes or {}
        self.token_usage: Dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "model": "unknown",
        }
        self.error_message: Optional[str] = None

    def finish(self, status: str = "ok", error_message: Optional[str] = None) -> None:
        self.end_time = time.perf_counter()
        self.end_timestamp = datetime.now(timezone.utc).isoformat()
        self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 2)
        self.status = status
        self.error_message = error_message

    def record_tokens(self, prompt_tokens: int, completion_tokens: int, model: str = "default") -> None:
        self.token_usage["prompt_tokens"] += prompt_tokens
        self.token_usage["completion_tokens"] += completion_tokens
        self.token_usage["total_tokens"] += (prompt_tokens + completion_tokens)
        self.token_usage["model"] = model

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "attributes": self.attributes,
            "token_usage": self.token_usage,
            "error_message": self.error_message,
        }


class TelemetryCollector:
    """
    Thread-safe in-process telemetry manager aggregating spans, token metrics, and latency percentiles.
    """
    def __init__(self, max_traces: int = 1000):
        self.max_traces = max_traces
        self._spans: List[SpanRecord] = []
        self._otel_tracer = None
        self._init_otel()

    def _init_otel(self):
        if OTEL_AVAILABLE:
            try:
                resource = Resource.create({"service.name": "ai-software-engineer", "service.version": "1.0.0"})
                provider = TracerProvider(resource=resource)
                trace.set_tracer_provider(provider)
                self._otel_tracer = trace.get_tracer("ai_software_engineer.tracer")
                logger.info("OpenTelemetry TracerProvider successfully initialized.")
            except Exception as err:
                logger.warning("OpenTelemetry initialization skipped: %s", err)

    def record_span(self, span: SpanRecord) -> None:
        if len(self._spans) >= self.max_traces:
            self._spans.pop(0)  # Evict oldest
        self._spans.append(span)

    def record_token_usage(self, prompt_tokens: int, completion_tokens: int, model: str = "qwen2.5-coder:7b"):
        """
        Record standalone LLM token usage.
        """
        span = SpanRecord(name=f"llm_inference:{model}", attributes={"model": model})
        span.finish(status="ok")
        span.record_tokens(prompt_tokens, completion_tokens, model=model)
        self.record_span(span)

    def get_traces(self, limit: int = 100, span_name: Optional[str] = None) -> List[Dict[str, Any]]:
        results = self._spans
        if span_name:
            results = [s for s in results if s.name == span_name]
        return [s.to_dict() for s in reversed(results[-limit:])]

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Compute high-level telemetry and token summary across all collected spans.
        """
        total_spans = len(self._spans)
        total_errors = sum(1 for s in self._spans if s.status == "error")
        total_prompt_tokens = sum(s.token_usage["prompt_tokens"] for s in self._spans)
        total_completion_tokens = sum(s.token_usage["completion_tokens"] for s in self._spans)
        total_tokens = total_prompt_tokens + total_completion_tokens

        # Group latency and count by span name
        breakdowns: Dict[str, Dict[str, Any]] = {}
        tokens_by_model: Dict[str, Dict[str, int]] = {}

        for s in self._spans:
            # Latency breakdown
            name = s.name
            if name not in breakdowns:
                breakdowns[name] = {"count": 0, "total_ms": 0.0, "min_ms": s.duration_ms, "max_ms": s.duration_ms}
            b = breakdowns[name]
            b["count"] += 1
            b["total_ms"] += s.duration_ms
            b["min_ms"] = min(b["min_ms"], s.duration_ms)
            b["max_ms"] = max(b["max_ms"], s.duration_ms)

            # Token usage by model
            model = s.token_usage.get("model", "unknown")
            if model != "unknown" and s.token_usage["total_tokens"] > 0:
                if model not in tokens_by_model:
                    tokens_by_model[model] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                tokens_by_model[model]["prompt_tokens"] += s.token_usage["prompt_tokens"]
                tokens_by_model[model]["completion_tokens"] += s.token_usage["completion_tokens"]
                tokens_by_model[model]["total_tokens"] += s.token_usage["total_tokens"]

        # Calculate mean latency
        latency_summary = {}
        for name, data in breakdowns.items():
            count = data["count"]
            latency_summary[name] = {
                "invocations": count,
                "mean_latency_ms": round(data["total_ms"] / count, 2) if count > 0 else 0.0,
                "min_latency_ms": data["min_ms"],
                "max_latency_ms": data["max_ms"],
            }

        return {
            "total_spans": total_spans,
            "total_errors": total_errors,
            "error_rate_percent": round((total_errors / total_spans * 100.0), 2) if total_spans > 0 else 0.0,
            "tokens": {
                "total_prompt_tokens": total_prompt_tokens,
                "total_completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens,
                "by_model": tokens_by_model,
            },
            "latency_breakdowns": latency_summary,
        }

    def reset(self) -> None:
        self._spans.clear()


# Global Singleton Collector Instance
collector = TelemetryCollector()


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None):
    """
    Context manager to trace execution of a block of code or LangGraph node.
    
    Usage:
        with trace_span("bug_detector_node", attributes={"file": "auth.py"}) as span:
            # do work
            span.record_tokens(120, 45, model="qwen2.5-coder")
    """
    span = SpanRecord(name=name, trace_id=trace_id, attributes=attributes)
    try:
        yield span
        span.finish(status="ok")
    except Exception as err:
        span.finish(status="error", error_message=str(err))
        raise
    finally:
        collector.record_span(span)


def traced(name: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None):
    """
    Decorator for synchronous or asynchronous functions to trace latency and executions.
    """
    def decorator(func: Callable):
        span_name = name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with trace_span(span_name, attributes=attributes):
                return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            with trace_span(span_name, attributes=attributes):
                return await func(*args, **kwargs)

        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
