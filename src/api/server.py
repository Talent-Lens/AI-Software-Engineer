"""
FastAPI Server Core Application (TASK-FS1)
"""
from __future__ import annotations

import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import health, analyze, retrieval, eval as eval_router, agents, feedback
from src.api.websockets import manager, stream_pipeline_execution

logger = logging.getLogger("ai_engineer.api.server")

app = FastAPI(
    title="AI Software Engineer Platform API",
    description="Enterprise Multi-Language AST RAG, Bug Detection, Security Audit, & Evaluation Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware Setup
origins = [
    "http://localhost:5173",  # Vite default React dev port
    "http://localhost:3000",  # React default port
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include REST Routers under /api/v1
app.include_router(health.router, prefix="/api/v1")
app.include_router(analyze.router, prefix="/api/v1")
app.include_router(retrieval.router, prefix="/api/v1")
app.include_router(eval_router.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")


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
