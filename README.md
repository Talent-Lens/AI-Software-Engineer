<div align="center">

# 🛡️ CodeGuardian
### **Autonomous Multi-Agent AI Security & Verification Engine**

```
 ⚡ 7-Node LangGraph DAG   •   🌳 Tree-Sitter AST Parsing   •   🧪 Pytest Subprocess Sandbox
```

---

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.2.0-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://reactjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.2.2-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.0.25-FF6F61?style=for-the-badge)](https://python.langchain.com/docs/langgraph)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com/)

---

</div>

> [!IMPORTANT]
> **CodeGuardian** is an enterprise AI platform built to audit codebases for **OWASP Top 10 vulnerabilities**, eliminate **LLM line citation hallucinations** using Tree-Sitter AST syntax trees, and issue **auto-verified GitHub Pull Requests**.

---

## 📌 Executive Summary Card

| Core Pillar | Technology | Value Delivered |
| :--- | :--- | :--- |
| 🤖 **Multi-Agent Flow** | **LangGraph DAG (7 Nodes)** | Autonomous step-by-step auditing, verification, and sandboxed test generation. |
| 🌳 **AST Code Grounding** | **Tree-Sitter Parser** | 100% verified line-number citations (Zero LLM hallucinations). |
| ⚡ **Hybrid Search RAG** | **Dense Embeddings + Sparse BM25** | Reciprocal Rank Fusion ($k=60$) across large codebase repositories. |
| 🧪 **Code Verification** | **Pytest Subprocess Sandbox** | Executes suggested code fixes in isolated sandboxes with exit code validation. |
| 🤖 **Automated CI/CD** | **GitHub Actions & Webhooks** | Posts inline AST security audit comments directly on real GitHub PR diffs. |

---

## 🏗️ System Architecture

```mermaid
graph LR
    A[📁 Codebase / GitHub] --> B[🌳 Tree-Sitter AST]
    B --> C[⚡ RRF Hybrid Search]
    C --> D[🤖 7-Node LangGraph DAG]
    D --> E[🟢 Verified Code Patch]
    E --> F[🐙 GitHub Pull Request]
```

---

## 🔄 3-Stage Developer Workflow

| Stage | Name | Description | Key Components |
| :---: | :--- | :--- | :--- |
| **1** | **Input Page** | Drag & drop multi-files, enter GitHub repo URL, or paste code snippet. | Multi-File Dropzone, GitHub Loader |
| **2** | **Live DAG Canvas** | Watch real-time execution across 7 agent nodes with pulsing glow lines. | Real-time SVG Canvas, Live Log Stream |
| **3** | **Results Workbench** | Inspect side-by-side code diffs, SAST audit findings, and issue GitHub PRs. | Monaco Diff Editor, File Tree, PR Modal |

---

## 🤖 7-Agent Verification Pipeline

```
  [1. Retrieval Agent]
         │
         ├───► [2. AST Bug Detector] ────► [4. Syntax Verifier] ────┐
         │                                                            ├─► [6. Pytest Sandbox] ─► [7. Doc Auditor]
         └───► [3. SAST Security Auditor] ─► [5. Line Verifier] ─────┘
```

> [!TIP]
> **Why 7 Agents?** Single-prompt LLMs make mistakes. CodeGuardian divides work into 7 specialized nodes so that security scanning, syntax linting, line grounding, and unit testing validate each fix independently.

---

## 🛠️ Complete Tech Stack

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND WORKSPACE                             │
│   React 18  •  TypeScript  •  Monaco Diff Editor  •  TailwindCSS  • Recharts  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼ REST / WebSockets API
┌─────────────────────────────────────────────────────────────────────────────┐
│                               BACKEND API ENGINE                            │
│    FastAPI  •  Uvicorn  •  Pydantic v2  •  Python 3.10  •  ChromaDB RAG     │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼ Persistence & Telemetry
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INFRASTRUCTURE & DATABASE                         │
│  Supabase PostgreSQL  •  SQLAlchemy  •  Arize Phoenix  •  GitHub Actions    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Quickstart Guide (3 Commands)

### 1️⃣ Clone & Setup Virtual Environment
```bash
git clone https://github.com/YourUsername/CodeGuardian.git
cd CodeGuardian
python -m venv venv && source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2️⃣ Start Backend Server
```bash
python -m uvicorn src.api.server:app --port 8000 --reload
```

### 3️⃣ Start Frontend UI
```bash
cd frontend && npm install && npm run dev
```
👉 Open `http://localhost:5173` in your browser.

---

## 📡 REST API Reference Table

| Method | Endpoint | Purpose |
| :---: | :--- | :--- |
| `GET` | `/api/v1/health` | Backend status & AST engine health check. |
| `POST` | `/api/v1/analyze` | Executes 7-node LangGraph analysis on target code. |
| `POST` | `/api/v1/github/webhook` | Receives GitHub PR webhooks with HMAC SHA-256 validation. |
| `POST` | `/api/v1/github/review-pr` | Triggers automated AI PR review comments on GitHub. |
| `GET` | `/api/v1/eval/report` | Returns RAG Triad benchmark metrics & telemetry latency spans. |
| `POST` | `/api/v1/feedback/submit` | Logs developer RLHF feedback (`Accept` / `Reject`). |

---

## 🔌 Model Context Protocol (MCP) Server

CodeGuardian includes a production **Model Context Protocol (MCP)** server (`mcp>=1.0.0`) that exposes its multi-language AST chunker, persistent ChromaDB vector store, BM25 hybrid search, and neural Cross-Encoder re-ranking directly to AI developer tools such as **Claude Desktop**, **Claude Code**, **Cursor**, and **Windsurf**.

### 🛠️ Exposed MCP Tools

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `index_repository` | `path: str`, `reset: bool = False`, `incremental: bool = True`, `collection_name: str = "repo_index"`, `persist_path: str = "./chroma_db"` | Indexes a codebase into ChromaDB + BM25 with multi-language AST parsing (Python, TS, JS, Java, Go) and fast Git-diff incremental updates. |
| `search_codebase` | `query: str`, `top_k: int = 5`, `rerank: bool = True`, `collection_name: str = "repo_index"`, `persist_path: str = "./chroma_db"`, `use_graph: bool = False` | Executes hybrid search (Dense Vector + BM25 + RRF + Cross-Encoder re-ranking) and returns code chunks with full file and line metadata. |
| `get_function_context` | `path: str`, `function_name: str`, `collection_name: str = "repo_index"`, `persist_path: str = "./chroma_db"` | Retrieves complete AST context for a function/class including imports, parent class/struct hierarchy, start/end lines, and compilable context. |

### 🚀 Running the MCP Server

```bash
# Direct module execution (stdio transport for MCP clients)
python -m src.mcp.server --transport stdio

# Or using the script runner
python scripts/run_mcp_server.py --transport stdio
```

### ⚙️ Client Configurations

#### 1. Claude Desktop (`claude_desktop_config.json`)
Location:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "codeguardian": {
      "command": "python",
      "args": [
        "-m",
        "src.mcp.server",
        "--transport",
        "stdio"
      ],
      "cwd": "C:\\path\\to\\CodeGuardian"
    }
  }
}
```

#### 2. Claude Code CLI (`~/.claude.json` or project settings)
```json
{
  "mcpServers": {
    "codeguardian": {
      "command": "python",
      "args": [
        "-m",
        "src.mcp.server"
      ],
      "cwd": "C:\\path\\to\\CodeGuardian"
    }
  }
}
```

#### 3. Cursor / Windsurf IDE
Add a new MCP server in IDE Settings:
- **Type:** `command` (stdio)
- **Command:** `python -m src.mcp.server --transport stdio`
- **Working Directory:** `/path/to/CodeGuardian`

---

## 👥 Engineering Team & Ownership

Built as a high-impact engineering project by a 2-person team:

| Team Member | Domain | Key Accomplishments |
| :--- | :--- | :--- |
| **Teammate 1 (You)** | **AI Systems & Full-Stack Lead** | • Built 7-Node LangGraph DAG & Tree-Sitter AST Grounding Parser.<br>• Designed 3-Stage React Workspace, SVG Canvas & Monaco Diff Viewer.<br>• Built GitHub Webhook Bot (`/api/v1/github/webhook`) & PR Creation API. |
| **Teammate 2 (Partner)** | **Infrastructure & Database Lead** | • Built RAG Triad Benchmark Suite & Arize Phoenix Telemetry Tracing.<br>• Designed Supabase PostgreSQL schema (`SQLAlchemy`) for audit persistence.<br>• Implemented Pytest Subprocess Sandboxing. |

---

<div align="center">

**CodeGuardian** • *Autonomous Multi-Agent AI Security Engine*

</div>