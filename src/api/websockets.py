"""
WebSocket Connection Manager and Stream Engine for LangGraph Execution Logs (TASK-FS1)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("ai_engineer.api.websockets")


class ConnectionManager:
    """
    Manages active WebSocket connections for live LangGraph execution streaming.
    """

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket client connected. Total active: %d", len(self.active_connections))
        await self.send_json(websocket, {
            "event": "connection_established",
            "message": "Connected to AI Software Engineer WebSockets Stream Engine",
            "timestamp": datetime.now().isoformat()
        })

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket client disconnected. Total active: %d", len(self.active_connections))

    async def send_json(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning("Failed to send WebSocket message: %s", e)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("Error broadcasting to connection, removing: %s", e)
                self.disconnect(connection)


manager = ConnectionManager()


async def stream_pipeline_execution(websocket: WebSocket, filepath: str) -> dict[str, Any]:
    """
    Executes the LangGraph pipeline while streaming real-time node events to the WebSocket client.
    """
    from graph import app as pipeline_app

    async def emit(event_type: str, node: str | None = None, data: Any = None, message: str | None = None) -> None:
        payload = {
            "event": event_type,
            "node": node,
            "data": data,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        await manager.send_json(websocket, payload)

    await emit("pipeline_start", data={"filepath": filepath}, message=f"Starting analysis for {filepath}")

    initial_state = {
        "filepath": filepath,
        "agent_response": {},
        "review": {},
        "security_response": {},
        "attempts": 0,
    }

    try:
        # Step 1: Detect node
        await emit("node_start", node="detect", message="Running Bug Detection Agent")
        state_after_detect = pipeline_app.invoke(initial_state)
        await emit("node_complete", node="detect", data=state_after_detect.get("agent_response", {}))

        # Step 2: Review node
        await emit("node_start", node="review", message="Running Line-Number & AST Grounding Review Agent")
        review_data = state_after_detect.get("review", {})
        await emit("node_complete", node="review", data=review_data)

        # Step 3: Security node
        await emit("node_start", node="security", message="Running SAST Security Audit Agent")
        security_data = state_after_detect.get("security_response", {})
        await emit("node_complete", node="security", data=security_data)

        # Pipeline complete
        await emit("pipeline_complete", data=state_after_detect, message="Analysis complete")
        return state_after_detect

    except Exception as err:
        await emit("pipeline_error", message=f"Error executing pipeline: {err}")
        raise err
