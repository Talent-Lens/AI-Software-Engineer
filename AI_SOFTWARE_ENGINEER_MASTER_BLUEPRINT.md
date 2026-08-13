# 🚀 AI Software Engineer Platform: Master Project Blueprint & Task Execution Roadmap

**Project Name:** Enterprise AI Software Engineer Platform  
**Target Roles:** 
- **Friend:** LLM Retrieval Engineer & Indexing Infrastructure Lead  
- **You:** Review, Evaluation, Execution & Safety/Guardrails Lead  

---

## 🎯 Executive Overview & Tech Stack

This project builds an **Enterprise-Grade AI Software Engineer System** that indexes multi-language repositories, performs hybrid search, detects bugs, auto-generates unit tests, executes tests in a safe sandbox, audits security vulnerabilities, verifies zero hallucinations, runs automated GitHub PR reviews, persists analytics in PostgreSQL/Supabase, and serves everything via a live React + FastAPI Web UI.

### 🆓 100% Free Stack (Zero Dollars Spent):
- **Database:** Supabase PostgreSQL / Local SQLite (via SQLAlchemy ORM & `pgvector`).
- **LLM APIs:** Groq Cloud API (`qwen-2.5-coder-32b`, `llama-3.3-70b-versatile`), Google Gemini API (`gemini-2.5-flash`), Local Ollama (`deepseek-r1:7b`).
- **Vector DB:** ChromaDB / FAISS / Supabase `pgvector` (Local & Cloud).
- **Embeddings & Reranker:** Hugging Face Open-Source (`BAAI/bge-m3`, `cross-encoder/ms-marco-MiniLM-L-6-v2`).
- **Observability:** Arize Phoenix / OpenTelemetry (Free Open-Source).
- **Frontend & Backend:** React (Vite) + FastAPI + Docker.

---

## 📊 Master Task Split & Assignment Matrix

| Task ID | Feature Name | Owner | Core Responsibility |
|---|---|---|---|
| **TASK-R1** | Multi-Language AST Chunker | **Friend** | Multi-language parsing (Python, JS/TS, Java, Go) using `tree-sitter`. |
| **TASK-R2** | Parent-Child Context Windowing | **Friend** | Enclose functions with class headers and top-of-file imports. |
| **TASK-R3** | Hybrid Search Engine | **Friend** | Dense Embeddings + BM25 Keyword Search fused via RRF. |
| **TASK-R4** | Cross-Encoder Re-Ranker | **Friend** | Re-score top 20 retrieved candidates down to top 3-5 high precision. |
| **TASK-R5** | Incremental Git Indexing | **Friend** | Read `.git` diffs to re-index only modified/added files. |
| **TASK-R6** | Docstring Generator Agent | **Friend** | Generate Google-style/JSDoc/OpenAPI docstrings for code chunks. |
| **TASK-R7** | Codebase GraphRAG (`NetworkX`) | **Friend** | Connect file imports & call hierarchies for Graph-guided retrieval. |
| **TASK-E1** | Line-Number Grounding Verifier | **You** | Verify line citations against raw files to eliminate hallucinations. |
| **TASK-E2** | AST Code Syntax & Lint Validator | **You** | Parse generated fixes with `ast.parse` and `ruff` to guarantee syntax. |
| **TASK-E3** | Self-Executing Unit Test Sandbox | **You** | Generate unit tests, execute them in `pytest`/`jest` subprocesses live. |
| **TASK-E4** | SAST Security Auditor Agent | **You** | Scan code for OWASP Top 10 risks (SQL injection, hardcoded secrets). |
| **TASK-E5** | Docstring Accuracy Verifier | **You** | Audit generated docs against function signatures for precision. |
| **TASK-E6** | RAG Triad Evaluation Suite | **You** | Measure Context Recall, Context Precision, Faithfulness, MRR, Hits@K. |
| **TASK-E7** | Synthetic Bug Generator | **You** | Auto-generate 100+ benchmark test cases with golden ground truths. |
| **TASK-E8** | Dynamic Multi-Model Router | **You** | Dynamically route queries between fast models & deep reasoning models (DeepSeek-R1). |
| **TASK-E9** | Human-in-the-Loop Hard Negative Store | **You** | Save user accept/reject feedback into ChromaDB hard-negatives to improve retrieval. |
| **TASK-FS1**| FastAPI Backend & WebSockets | **Friend** | Build REST endpoints (`/api/v1/analyze`) and WebSocket streams (`/ws/graph-stream`). |
| **TASK-FS2**| React Web Frontend | **You** | Live LangGraph Canvas, Monaco Code Editor, Diff Viewer, Eval Dashboard. |
| **TASK-FS3**| Docker & Cloud Deployment | **Friend** | Dockerize setup and deploy to free tiers (Vercel + Render/Railway). |
| **TASK-FS4**| GitHub PR Webhook & GitHub Action | **You** | Auto-comment AI reviews directly on real GitHub Pull Requests. |
| **TASK-FS5**| OpenTelemetry & Agent Tracing | **You** | Trace latency breakdown and token usage with Arize Phoenix telemetry. |
| **TASK-FS6**| Supabase / Postgres Database (SQLAlchemy)| **Friend** | Persist repos, analysis runs, evaluation trends, and feedback audit logs. |

---

# 👤 PART 1: YOUR FRIEND'S ROADMAP (LLM Retrieval Engineer)

### 🔹 TASK-R1: Multi-Language AST Chunker
- **Context:** Expand `src/indexing/chunker.py` beyond Python.
- **Implementation:** Integrate `tree-sitter` grammars for Python (`.py`), JavaScript/TypeScript (`.js`, `.ts`), Java (`.java`), and Go (`.go`).
- **Goal:** Extract clean function, class, and method nodes regardless of language.

### 🔹 TASK-R2: Parent-Child & Enclosing Scope Context Windowing
- **Context:** Pure code chunks lose context like imports or enclosing class names.
- **Implementation:** Attach file-level import statements and parent class signatures to every retrieved function chunk before passing to the LLM.
- **Goal:** Provide complete, compilable context to the prompt.

### 🔹 TASK-R3: Hybrid Search Engine (Vector + BM25 + RRF)
- **Context:** Vector search alone misses exact variable/function names.
- **Implementation:** Build a dual-index search in `src/retrieval/`:
  1. Dense Vector Search (`sentence-transformers/all-MiniLM-L6-v2` in ChromaDB).
  2. Sparse Keyword Search (`rank_bm25` over AST code tokens).
  3. Combine ranks using Reciprocal Rank Fusion: $\text{RRF}(d) = \sum \frac{1}{60 + r(d)}$.
- **Goal:** Achieve high recall for both semantic queries and exact identifier names.

### 🔹 TASK-R4: Cross-Encoder Re-Ranking Pipeline
- **Context:** Top-20 search results contain noisy/irrelevant code.
- **Implementation:** Pass top 20 candidates through `cross-encoder/ms-marco-MiniLM-L-6-v2` to compute query-code cross-attention scores and pick top 3-5 chunks.
- **Goal:** Maximize precision and cut context window bloat.

### 🔹 TASK-R5: Feature D - Incremental Git Indexing Engine
- **Context:** Re-indexing a 100,000-line repo takes too long.
- **Implementation:** Use Git python bindings (`gitpython`) or `.git` diffs to detect changed/added files, updating only those chunks in ChromaDB.
- **Goal:** Sub-second incremental re-indexing latency.

### 🔹 TASK-R6: Feature A (Part 1) - Docstring Context Formatter & Doc Agent
- **Context:** Un-documented functions make code maintenance hard.
- **Implementation:** Build an agent that takes AST chunks missing documentation and generates Google-style docstrings or JSDoc comments using Groq LLM API.
- **Goal:** Auto-document whole codebases cleanly.

### 🔹 TASK-R7: Codebase GraphRAG (`NetworkX`)
- **Context:** Code relies heavily on file import graphs and class inheritance hierarchy.
- **Implementation:** Build a graph index using `NetworkX` parsing imports and class inheritance. Traverse graph nodes during retrieval to pull dependent classes.
- **Goal:** Graph-guided context expansion across multiple files.

---

# 👤 PART 2: YOUR ROADMAP (Review, Evaluation & Safety Lead)

### 🔸 TASK-E1: Line-Number & Code Grounding Verifier
- **Context:** LLMs frequently hallucinate fake line numbers (e.g., claiming a bug is on line 99 when file has 50 lines).
- **Implementation:** Build a verification guardrail in `src/agents/review_agent.py` that reads the original source file and checks if cited line numbers exist and contain the exact matching code.
- **Goal:** Zero hallucinated line numbers in agent responses.

### 🔸 TASK-E2: AST Code Syntax & Lint Validator
- **Context:** Suggested fixes must be 100% syntactically valid code.
- **Implementation:** Run any generated code fix through `ast.parse()` (for Python) or static checkers (`ruff`/`eslint`). If syntax fails, flag the response immediately.
- **Goal:** 100% syntactically valid code suggestions.

### 🔸 TASK-E3: Feature B - Self-Executing Unit Test Generator & Subprocess Sandbox
- **Context:** Generating tests is useless if they don't actually run and pass.
- **Implementation:**
  1. Build a Test Generator Agent generating `pytest` / `jest` code.
  2. Create a isolated subprocess execution sandbox (`subprocess.run(["pytest", ...])`).
  3. If tests fail, feed error stack traces back to the LLM to self-correct until tests pass.
- **Goal:** Proable 100% verified running unit tests.

### 🔸 TASK-E4: Feature C - SAST Security & Vulnerability Auditor Agent
- **Context:** Security issues like hardcoded secrets or SQL injection must be caught early.
- **Implementation:** Scan retrieved code chunks using AST rules and Groq LLM prompts against OWASP Top 10 security risks.
- **Goal:** Produce an automated Security Scorecard (Pass/Fail, Severity: Low/Med/High).

### 🔸 TASK-E5: Feature A (Part 2) - Docstring Accuracy Verifier
- **Context:** Generated documentation must match the actual code implementation.
- **Implementation:** Audit generated docstrings against function parameter types, default values, and return types.
- **Goal:** Eliminate docstring hallucinations.

### 🔸 TASK-E6: RAG Triad Evaluation Suite & Benchmark Runner
- **Context:** Need hard quantitative data for your resume.
- **Implementation:** Create `src/eval/eval_runner.py` computing:
  - **Context Recall**: Is the target bug chunk retrieved?
  - **Context Precision**: Ratio of useful vs useless context.
  - **Faithfulness**: Does the explanation use *only* retrieved code facts?
  - **MRR & Hits@K**: Retrieval quality metrics.
- **Goal:** Automated benchmark script outputting JSON/CSV performance reports.

### 🔸 TASK-E7: Synthetic Multi-Language Bug Generator
- **Context:** Need a large test set to evaluate your platform.
- **Implementation:** Parse open-source codebases (`psf/requests`, `flask`, `express`), inject or locate 100+ realistic code bugs, and build a benchmark JSON dataset with ground truths.
- **Goal:** 100+ golden benchmark evaluation pairs.

### 🔸 TASK-E8: Dynamic Multi-Model Router
- **Context:** Simple queries need fast models (Groq/Gemini), complex architectural reasoning needs deep reasoning models (DeepSeek-R1).
- **Implementation:** Implement a dynamic router that inspects query complexity and routes to the appropriate LLM provider with fallback retries.
- **Goal:** Optimal balance between speed (sub-second) and reasoning depth.

### 🔸 TASK-E9: Human-in-the-Loop (HITL) Hard Negative Store
- **Context:** User feedback (Accept/Reject fix) should improve retrieval precision.
- **Implementation:** Capture UI accept/reject events via `/api/v1/feedback` and store rejected code chunks as hard-negatives in ChromaDB to penalty-score them in future queries.
- **Goal:** Active learning feedback loop.

---

# 🌐 PART 3: SHARED ROADMAP (Full-Stack Web App & Deployment)

### 🔹 TASK-FS1: FastAPI Backend & WebSockets Stream Engine [Owner: Friend]
- Create REST endpoints: `/api/v1/analyze`, `/api/v1/retrieval/search`, `/api/v1/eval/run`.
- Add WebSocket endpoint (`/ws/graph-stream`) to stream live LangGraph execution logs to the frontend.

### 🔸 TASK-FS2: React Web Frontend (VS-Code & Dashboard Style) [Owner: You]
- **Live LangGraph Canvas:** Interactive visual graph where nodes light up live as agents run.
- **Monaco Code Editor & Diff Viewer:** Show source code and proposed fixes side-by-side like GitHub PRs.
- **Recharts Evaluation Dashboard:** Visual graphs showing RAG Triad scores, Hits@K, and Latency.

### 🔹 TASK-FS3: Docker & Cloud Deployment [Owner: Friend]
- Create `Dockerfile` and `docker-compose.yml` for backend, vector DB, and frontend.
- Deploy frontend to Vercel and backend to Render / Railway / Hugging Face Spaces (100% Free).
- Put live link + 15-second demo video on GitHub `README.md`.

### 🔸 TASK-FS4: GitHub PR Webhook & GitHub Action [Owner: You]
- **Implementation:** Build `/api/v1/github/webhook` listening to GitHub Pull Request events. Write a GitHub Action workflow file (`.github/workflows/ai-review.yml`).
- **Goal:** Post automated AI review comments directly onto real GitHub PRs!

### 🔸 TASK-FS5: OpenTelemetry & Agent Tracing (Arize Phoenix) [Owner: You]
- **Implementation:** Instrument FastAPI & LangGraph with `arize-phoenix` / `openinference` tracing.
- **Goal:** Provide a live telemetry dashboard for latency breakdowns and token usage.

### 🔹 TASK-FS6: Enterprise Database & Analytics Persistence (Supabase / Postgres + SQLAlchemy) [Owner: Friend]
- **Implementation:** Build database models using `SQLAlchemy` for `repositories`, `analysis_runs`, `eval_experiments`, and `user_feedback`. Connect to free Supabase PostgreSQL instance.
- **Goal:** Persist historical evaluation trends, codebase metadata, and audit logs.

---

## 📌 How We Will Work Together (Step-by-Step Execution Protocol)

1. You will pick a Task ID from this document (e.g., **"Let's do TASK-E1: Line-Number Grounding Verifier"**).
2. I will write the complete, clean, production-grade Python/React code for that task.
3. We will run and test the code together, ensuring you understand every single line for your interviews!
4. We check off the task and move to the next one until the project is **100% Complete & Deployed**!
