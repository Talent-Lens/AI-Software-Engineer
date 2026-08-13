"""
CLI Runner Script for launching the FastAPI backend server (TASK-FS1)
"""
import argparse
import sys
import os

# Add project root to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="AI Software Engineer FastAPI Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    print(f"Starting AI Software Engineer FastAPI Server on http://{args.host}:{args.port}")
    uvicorn.run("src.api.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
