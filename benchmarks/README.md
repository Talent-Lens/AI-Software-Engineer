# CodeGuardian Research-Grade Benchmark Platform

An independent, ground-truth-backed benchmarking system comparing **CodeGuardian** against **Semgrep OSS**, **GitHub CodeQL**, **SonarQube Community Edition**, and an optional **Bandit** reference line across six standardized metrics.

---

## 1. One-Step Automated Research Repository Ingestion

Adding a new research benchmark repository is a single-click, zero-human-intervention pipeline:
1. **Input**: In the Admin UI (**Benchmarks** $\to$ **Add Research Repo**), enter:
   - **GitHub URL**: `https://github.com/<owner>/<repo>`
   - **Identifier**: A CVE ID (e.g. `CVE-2018-18074`) or a fix commit SHA (e.g. `d71912f2c8d281313cae74fecaeae8ce8f4118f6`).
2. **Commit Resolution**: The system automatically queries GitHub Advisory / REST API to resolve:
   - The **Clean Commit** ($N$, the security fix)
   - The **Vulnerable Commit** ($N-1$, the parent commit before the fix)
   - The advisory CWE classification (if documented).
3. **Safe Isolated Cloning & Diff Extraction**:
   - Clones safely into a temporary sandbox. Dependencies are **never installed**; tests and scripts are **never executed**.
   - Runs `git diff -U0 <parent_sha> <fix_sha>` in memory.
   - Applies strict **noise filtering** to eliminate non-code changes (see Section 2).
   - Generates a version-controlled manifest in `benchmarks/ground_truth/<slug>.json`.
4. **Dual-Commit Static Scanning**:
   - Runs all static analysis tools on the **vulnerable commit** to measure True Positives and False Positives.
   - Runs all static analysis tools on the **clean commit** to measure False Alarms on post-fix code.
5. **Deterministic Metrics Computation**:
   - Computes Precision, Recall, Clean FPR/kLOC, $\pm 3$ lines localization %, and CWE classification %.
   - Persists all results into isolated database tables (`research_repos`, `benchmark_runs`, `benchmark_findings`, `benchmark_metrics`).
   - The repository automatically enters the general averages.

---

## 2. Noise Filtering Rules

Developer fix commits often combine security changes with unrelated formatting, tests, or documentation. The automatic diff extractor filters out candidate lines that match any of the following:

- **Excluded Directories**: `tests/`, `test/`, `spec/`, `docs/`, `vendor/`, `third_party/`, `.github/`, `node_modules/`, `migrations/`.
- **Excluded Extensions**: `.md`, `.rst`, `.txt`, `.json`, `.yaml`, `.yml`, `.toml`, `.lock`, `.svg`, `.png`, `.html`, `.css`, `.sh`, `.bat`.
- **Excluded File Names**: `LICENSE`, `README`, `CHANGELOG`, `package-lock.json`, `yarn.lock`, `Cargo.lock`, `poetry.lock`.
- **Trivial Content**: Pure comments (`#`, `//`, `/*`), imports (`import ...`, `from ... import ...`), or whitespace/indentation adjustments.
- **Transparency**: All filtered lines are retained in an `ignored_candidates` log accessible from the per-repo inspection view.
- **Needs Attention Rule**: If noise filtering reduces the candidate line count to zero, the repo is marked `needs_attention` and excluded from averages until reviewed.

---

## 3. Provisional vs Verified Ground Truth

- **Provisional (Default)**: Repositories created via automated CVE diff extraction start as `provisional`. Because post-fix code may contain pre-existing unrelated vulnerabilities, the False Positive Rate on provisional repos is explicitly labeled as an **Upper Bound**.
- **Verified Upgrade Path**:
  1. From the per-repo drilldown view, click **Export Blind Triage** to download a JSON file with tool names anonymized (`Tool-Alpha`, `Tool-Beta`, etc.).
  2. Mark each candidate finding as `true_positive` or `false_positive`.
  3. Click **Import Verified Labels** to upload the decisions. The repo status upgrades to `verified`, and metrics are re-calculated without re-running scans.
- **Verified Only Filter**: The General Averages tab includes a "Verified Only" toggle to filter out provisional noise.

---

## 4. End-to-End Verification Checklist

Run this checklist to verify an automated repository ingestion:

```powershell
# 1. Run all unit test suites (URL resolver, diff extractor, metrics evaluator, API router)
venv/Scripts/python -m pytest tests/test_cve_resolver.py tests/test_diff_extractor.py tests/test_benchmark_evaluator.py tests/test_benchmark_router.py -v

# 2. Verify frontend compilation
npm --prefix frontend run build

# 3. Test adding a real CVE repo via API:
curl -X POST http://localhost:7860/api/v1/benchmarks/repos `
  -H "Content-Type: application/json" `
  -d '{"repo_url": "https://github.com/pallets/flask", "identifier": "CVE-2018-18074"}'

# 4. Check status & live progress:
curl http://localhost:7860/api/v1/benchmarks/repos
```
