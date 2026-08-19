# CodeGuardian — Autonomous AI Code Security & Verification Engine

CodeGuardian is an autonomous multi-agent code analysis and repair platform. It combines Tree-Sitter AST parsing, hybrid dense-sparse code retrieval, SAST vulnerability scanning (OWASP Top 10), and an isolated subprocess sandbox to automatically detect software bugs, eliminate hallucinated line citations in AI explanations, verify proposed code fixes with automated unit tests, and post review comments to GitHub Pull Requests.

---

## Architecture & Pipeline

CodeGuardian executes code analysis through a structured multi-stage verification pipeline:

```mermaid
flowchart TD
    A["Source Code / Repository"] --> B["Multi-Language AST Chunker<br/>(Tree-Sitter: Python, JS, TS, Go, Java)"]
    B --> C["Hybrid Vector & Lexical Index<br/>(ChromaDB Dense + BM25 Sparse)"]
    C --> D["Reciprocal Rank Fusion (k=60)<br/>+ Cross-Encoder Re-Ranker"]
    D --> E["LangGraph StateGraph Pipeline"]
    
    subgraph E ["LangGraph 3-Node StateGraph"]
        E1["1. Bug Detection Agent<br/>(AST pattern scan + LLM analysis)"] --> E2["2. Review & Grounding Agent<br/>(Verifies line citations against AST)"]
        E2 -- "Rejected (attempts < 3)" --> E1
        E2 -- "Approved" --> E3["3. SAST Security Auditor<br/>(OWASP AST rule scanner)"]
    end
    
    E --> F["Isolated Pytest Sandbox<br/>(Temporary directory execution)"]
    F --> G["Verified Patch & GitHub PR Webhook"]
```

### Pipeline Execution Stages

1. **AST Chunking**: Parses source code using Tree-Sitter grammars (Python, JavaScript, TypeScript, Go, Java) into function/class-level AST blocks with parent-child hierarchical context.
2. **Hybrid Retrieval**: Combines semantic embeddings (ChromaDB with `all-MiniLM-L6-v2`) and keyword scoring (Rank-BM25) using Reciprocal Rank Fusion ($k=60$), followed by Cross-Encoder re-ranking (`ms-marco-MiniLM-L-6-v2`).
3. **LangGraph StateGraph Execution**:
   - **`detect`**: Identifies AST defects (bare excepts, unhandled `None`, missing return types) and proposes patches.
   - **`review`**: Verifies that line number citations in the LLM's explanation strictly match genuine AST line boundaries, rejecting hallucinated line references.
   - **`security`**: Audits the file against SAST security rules (SQL injection, command injection, path traversal, unsafe deserialization/pickle, hardcoded secrets, SSRF).
4. **Pytest Subprocess Sandbox**: Runs generated unit test suites in an isolated temporary directory with process timeout enforcement and exit-code validation.
5. **Interactive UI / PR Automation**: Live React workbench with Monaco side-by-side diff viewer and automated GitHub PR webhook integration.

---

## Installation & Setup

### Prerequisites
- **Python**: `3.9` or `3.10` (tested on 3.9.13 and 3.10)
- **Node.js**: `18.x` or `20.x` with `npm`
- **Git**
- *(Optional)* **Ollama**: For 100% offline local LLM inference

---

### 1. Backend Setup

```bash
# Clone repository
git clone https://github.com/Talent-Lens/AI-Software-Engineer.git
cd AI-Software-Engineer

# Create and activate Python virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 2. Frontend Setup

```bash
cd frontend
npm install
cd ..
```

---

### 3. Environment Variables Configuration

Create a `.env` file in the project root based on [`.env.example`](.env.example):

```env
# Database Configuration (Supabase PostgreSQL or fallback to local SQLite)
SUPABASE_DB_URL=postgresql://postgres:your_password@your_db_host:5432/postgres

# Cloud LLM API Keys (Required for cloud deployments; optional if running Ollama locally)
# Get free Groq key: https://console.groq.com/keys
GROQ_API_KEY=gsk_...
# Get free Gemini key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIzaSy...

# Local Ollama Settings (Optional for offline local development)
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_LLM_MODEL=qwen2.5-coder:7b

# GitHub Integration (Optional for PR review bot)
GITHUB_TOKEN=ghp_...
GITHUB_WEBHOOK_SECRET=your_secret_key
```

> **LLM Provider Note**:
> - **Local Development**: If you have Ollama running locally (`ollama run qwen2.5:3b`), the system operates completely offline without external API keys.
> - **Cloud Deployment (Render / Docker)**: Free cloud containers do not run Ollama. Set a `GROQ_API_KEY` (recommended for fast inference) or `GEMINI_API_KEY` in your hosting environment variables.

---

### 4. Running the Platform

#### Start Backend API Server
```bash
# From project root:
python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
```
Swagger UI will be accessible at `http://localhost:8000/docs`.

#### Start Frontend UI
```bash
# In a separate terminal:
cd frontend
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## Usage Examples

### 1. Programmatic Pipeline Execution (Python)

```python
from graph import run_pipeline

result = run_pipeline("src/agents/bug_detection.py")

print("Review Status:", result["review"]["approved"])
print("Security Score:", result["security_response"]["details"]["scorecard"]["score"])
print("Summary:", result["agent_response"]["summary"])
```

---

### 2. Live REST API Calls

#### Run Code Analysis & Verification
```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"filepath": "src/api/server.py"}'
```

#### Run RAG Triad Live Benchmark Suite
```bash
curl -X POST http://localhost:8000/api/v1/eval/run \
  -H "Content-Type: application/json" \
  -d '{}'
```

#### Context-Aware Code Q&A
```bash
curl -X POST http://localhost:8000/api/v1/chat/code \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Where are Bare Except handlers detected?",
    "filepath": "src/agents/bug_detection.py",
    "model": "qwen-2.5-coder-32b"
  }'
```

#### SAST Security Audit
```bash
curl -X POST http://localhost:8000/api/v1/security/audit \
  -H "Content-Type: application/json" \
  -d '{"filepath": "src/agents/security_auditor.py"}'
```

---

### 3. CLI Benchmark Runner

```bash
python src/eval/eval_runner.py
```
Exports `eval_report.json` and `eval_report.csv`.

---

## Evaluation & Benchmarks

The retrieval and grounding pipeline is evaluated against a **25-case golden benchmark dataset** (`GOLDEN_BENCHMARK_DATASET` in `src/eval/eval_runner.py`), consisting of curated technical queries mapped to ground-truth AST target chunks, file paths, semantic keywords, and expected answers across the codebase.

### Current Performance Metrics ($n = 25$ Golden Test Cases)

| Metric | Measured Score | Evaluation Methodology |
| :--- | :---: | :--- |
| **Context Recall** | **`96.0%`** | 60% chunk ID / AST symbol presence + 40% ground-truth keyword coverage. |
| **Context Precision (MAP)** | **`78.0%`** | Mean Average Precision of relevant AST chunks in ranked retrieval results. |
| **Harmonic F1 Score** | **`83.3%`** | Harmonic mean of Precision ($0.78$) and Recall ($0.96$). |
| **Faithfulness (Grounding)** | **`96.0%`** | Claim-level token grounding verifying technical statements against retrieved context. |
| **Mean Reciprocal Rank (MRR)** | **`0.780`** | Reciprocal rank of first relevant chunk across test queries. |
| **Hits@1 Rate** | **`64.0%`** | Target chunk retrieved as top-1 result (16 of 25 cases). |
| **Hits@3 Rate** | **`96.0%`** | Target chunk present in top-3 results (24 of 25 cases). |
| **Hits@5 Rate** | **`100.0%`** | Target chunk present in top-5 results (25 of 25 cases). |
| **Hits@10 Rate** | **`100.0%`** | Target chunk present in top-10 results (25 of 25 cases). |
| **Benchmark Execution Latency** | **`~415ms – 1200ms`** | Complete in-memory evaluation of all 25 cases. |

---

## Testing

The test suite includes 22 test modules covering schema validation, AST chunking, LangGraph execution, SAST security rules, hybrid retrieval, database persistence, and API endpoints.

```bash
# Run unit & integration tests
pytest tests/test_all.py -v

# Run full test suite
pytest tests/
```

### Verified Test Categories
- `tests/test_all.py`: Core LangGraph pipeline, AST chunker, bug detection, review agent, test generation, and sandbox execution (31 passing unit tests).
- `tests/test_eval_runner.py` & `tests/test_eval_suite.py`: Evaluation runner metrics calculation and `/api/v1/eval/run` endpoint contracts.
- `tests/test_security_auditor.py`: OWASP AST security rule matching and vulnerability remediations.
- `tests/test_hybrid_retriever.py` & `tests/test_reranker.py`: Dense + BM25 RRF fusion and Cross-Encoder re-ranking.
- `tests/test_db_persistence.py`: SQLAlchemy session lifecycle and Supabase audit persistence.
- `tests/test_github_webhook.py`: GitHub PR webhook HMAC signature verification and review automation.

---

## Known Limitations

1. **Benchmark Sample Size ($n=25$)**: The current benchmark suite contains 25 curated golden test cases. While representative of the repository's core components, it is a focused evaluation suite rather than an exhaustive multi-thousand repository benchmark.
2. **Context Precision vs. Recall Trade-Off**: Context Precision ($78.0\%$) reflects the intentional inclusion of parent/sibling AST scope context during retrieval (to give the LLM surrounding function context), which slightly lowers strict Mean Average Precision while keeping Recall high ($96.0\%$).
3. **Cloud Container LLM Dependencies**: The backend requires an external cloud LLM API key (`GROQ_API_KEY` or `GEMINI_API_KEY`) when deployed to cloud environments like Render, as local Ollama instances are not available inside serverless/containerized free tiers.
4. **Sandbox Isolation Level**: The current test execution sandbox uses temporary directory isolation and subprocess execution with process timeouts. For untrusted third-party code in multi-tenant environments, containerized execution (e.g., Docker or gVisor sandbox) should be enabled.

---

## Production Deployment (Render)

The project includes a multi-service blueprint configuration in [`render.yaml`](render.yaml):

1. **Backend Web Service (`ai-software-engineer-backend`)**: Python 3.10 service running `uvicorn src.api.server:app --host 0.0.0.0 --port $PORT`.
2. **Frontend Static Site (`ai-software-engineer-frontend`)**: Static React build (`npm run build`) served over global CDN.
3. Configure `GROQ_API_KEY` and `SUPABASE_DB_URL` under Environment Variables in the Render dashboard.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.