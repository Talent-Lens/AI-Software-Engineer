---
title: AI Software Engineer Platform API
emoji: 🚀
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
---

# Enterprise AI Software Engineer Platform

Multi-Language AST Chunker, Parent-Child Windowing, Hybrid Search Engine (Vector + BM25 + Cross-Encoder Re-Ranker), SAST Security Auditor, Self-Executing Unit Test Sandbox, RAG Triad Evaluation Suite, and FastAPI Backend Server.

## 🚀 Live API Docs
- Interactive Swagger UI: `/docs`
- Interactive ReDoc UI: `/redoc`
- Health Check Endpoint: `/api/v1/health`

## 🛠️ Tech Stack
- **FastAPI** & **Uvicorn**
- **Gradio SDK** (Hugging Face Free CPU Space)
- **ChromaDB** & **SentenceTransformers**
- **Tree-sitter** Multi-Language Parser
- **LangGraph** & **LangChain** Agent Framework
- **React (Vite)** + **Tailwind CSS** + **Monaco Editor** + **Recharts**

## 💻 React Web Frontend (VS-Code & Dashboard Style)

The frontend is located in the `frontend/` directory.

### Features
1. **Live LangGraph Canvas:** Interactive node graph visualizing agent execution states live.
2. **Monaco Code Editor & Diff Viewer:** Side-by-side PR diff view of original vs proposed code fixes with AST line citations and OWASP vulnerability alerts.
3. **Recharts Evaluation Dashboard:** Real-time RAG Triad scores, Hits@K accuracy, stage-by-stage latency breakdowns, and golden benchmark runner.

### How to Run Frontend Locally
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.