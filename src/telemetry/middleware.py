"""
FastAPI Telemetry Middleware (TASK-FS5)
Instruments HTTP requests, measures latency, attaches trace headers, and logs metrics.
"""
from __future__ import annotations

import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.telemetry.tracer import collector, SpanRecord


class TelemetryMiddleware(BaseHTTPMiddleware):
    """
    ASGI Middleware capturing API response times and recording OpenTelemetry spans.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Ignore websocket handshakes and docs static requests in metrics if desired
        path = request.url.path
        if path.startswith("/ws"):
            return await call_next(request)

        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        span_name = f"http_request:{request.method} {path}"

        span = SpanRecord(
            name=span_name,
            trace_id=trace_id,
            attributes={
                "http.method": request.method,
                "http.path": path,
                "http.client_ip": request.client.host if request.client else "unknown",
            },
        )

        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            span.attributes["http.status_code"] = status_code
            span.finish(status="ok" if status_code < 400 else "error")

            # Attach telemetry headers
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Response-Time-Ms"] = str(duration_ms)
            return response

        except Exception as err:
            span.finish(status="error", error_message=str(err))
            raise err
        finally:
            collector.record_span(span)
