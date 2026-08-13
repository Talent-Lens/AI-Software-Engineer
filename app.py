"""
Hugging Face Space Entry Point (TASK-FS3 Deployment)
Mounts the FastAPI server onto Gradio SDK for 100% Free Cloud Deployment (16GB RAM + 50GB Disk).
"""
import gradio as gr
from src.api.server import app

def api_status(query: str):
    return (
        "🚀 AI Software Engineer Platform API Backend is LIVE!\n\n"
        "• Interactive Swagger UI: /docs\n"
        "• Interactive ReDoc: /redoc\n"
        "• Health Endpoint: /api/v1/health\n\n"
        f"Query status check: '{query or 'Ready'}'"
    )

demo = gr.Interface(
    fn=api_status,
    inputs=gr.Textbox(lines=2, placeholder="Type a test query or visit /docs endpoint..."),
    outputs="text",
    title="🤖 AI Software Engineer Platform API",
    description="Enterprise Multi-Language AST RAG, Bug Detection, SAST Security Audit, & Evaluation Backend.",
)

# Mount FastAPI REST & WebSockets app onto Gradio root
app_ui = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app_ui, host="0.0.0.0", port=7860)
