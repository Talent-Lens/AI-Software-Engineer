"""
FastAPI Server Core Application (TASK-FS1 & TASK-FS6)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import health, analyze, retrieval, eval as eval_router, agents, feedback, analytics, github, telemetry, chat, benchmark, auth
from src.api.websockets import manager, stream_pipeline_execution
from src.db.session import init_db
from src.telemetry.middleware import TelemetryMiddleware

logger = logging.getLogger("ai_engineer.api.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown lifespan handler.
    Initializes database tables on boot.
    """
    logger.info("Starting AI Software Engineer API Server...")
    try:
        init_db()
        logger.info("Database schema verified and initialized.")
    except Exception as err:
        logger.error("Database initialization warning: %s", err)

    try:
        from src.db.session import SessionLocal
        from src.benchmarks.read_service import BenchmarkReadService
        db = SessionLocal()
        try:
            BenchmarkReadService(db).recover_orphaned_jobs_on_startup()
        finally:
            db.close()
    except Exception as err:
        logger.warning("Orphaned benchmark job recovery warning: %s", err)

    yield
    logger.info("Shutting down AI Software Engineer API Server...")


app = FastAPI(
    title="AI Software Engineer Platform API",
    description="Enterprise Multi-Language AST RAG, Bug Detection, Security Audit, & Evaluation Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Middleware Setup
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "https://localhost:5173",
    "https://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TelemetryMiddleware)


@app.middleware("http")
async def benchmark_readonly_404_middleware(request, call_next):
    response = await call_next(request)
    if (
        response.status_code == 405
        and request.url.path.startswith("/api/v1/benchmarks")
        and benchmark.get_benchmark_mode() != "research"
    ):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return response

# Include REST Routers under /api/v1
app.include_router(health.router, prefix="/api/v1")
app.include_router(analyze.router, prefix="/api/v1")
app.include_router(retrieval.router, prefix="/api/v1")
app.include_router(eval_router.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(github.router, prefix="/api/v1")
app.include_router(telemetry.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(benchmark.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")

# Direct alias routes for GitHub callbacks to prevent 404 regardless of URL prefix configured in GitHub App
app.add_api_route("/github/callback", github.github_app_callback, methods=["GET"], include_in_schema=False)
app.add_api_route("/api/github/callback", github.github_app_callback, methods=["GET"], include_in_schema=False)



@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {
        "name": "AI Software Engineer Platform API",
        "status": "running",
        "docs": "/docs",
        "version": "1.0.0"
    }


@app.websocket("/ws/graph-stream")
async def websocket_graph_stream(websocket: WebSocket):
    """
    WebSocket endpoint streaming live LangGraph node execution events and logs.
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action", "")

            if action == "start_analysis":
                filepath = data.get("filepath", "graph.py")
                await stream_pipeline_execution(websocket, filepath)
            elif action == "ping":
                await manager.send_json(websocket, {"event": "pong"})
            else:
                await manager.send_json(websocket, {"event": "unknown_action", "action": action})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as err:
        logger.warning("WebSocket error: %s", err)
        manager.disconnect(websocket)
