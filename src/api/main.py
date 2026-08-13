"""
Main entry point for running the uvicorn FastAPI server module.
"""
import uvicorn


def run():
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
