# CodeGuardian Benchmark Methodology

## 1. Unified Source-Scope Policy (`src/benchmarks/scope.py`)

To guarantee fair, apples-to-apples comparisons across **CodeGuardian**, **Semgrep OSS**, **GitHub CodeQL**, **SonarQube Community**, and **Bandit**, every tool is executed against the **exact same filtered source copy** of each commit (`build_filtered_source_copy`). We do not rely on per-tool exclude flags.

### Default Exclusions
- **Excluded Directories:** `test`, `tests`, `testing`, `spec`, `specs`, `doc`, `docs`, `documentation`, `example`, `examples`, `sample`, `samples`, `tools`, `tool`, `vendor`, `third_party`, `node_modules`, `.github`, `.git`, `build`, `dist`, `migrations`, `fixtures`, `venv`, `.venv`, `__pycache__`.
- **Excluded File Patterns (tests, generated & minified):** `test_*.py`, `*_test.py`, `*.min.js`, `*.min.css`, `*_pb2.py`, `*_pb2_grpc.py`, `*.generated.*`, `*.g.cs`, `*.pb.go`.
- **Excluded Non-Source Extensions & Files:** `.md`, `.rst`, `.txt`, `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.lock`, `.svg`, `.png`, `.jpg`, `.gif`, `.ico`, `.html`, `.css`, `.scss`, `.less`, `.sh`, `.bat`, `.ps1`, `.cmd`, plus `LICENSE`, `README`, `CHANGELOG`, `package-lock.json`, `yarn.lock`, `poetry.lock`, etc.
- **Included Source Extensions:** `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.go`, `.c`, `.cpp`, `.cs`, `.rb`, `.php`.

### Per-Repo Override & Fail-Loud Guard
- Repositories may specify a `scope_override` JSON object (`extra_exclude_dirs`, `include_dirs`, `include_paths`, `extra_exclude_globs`).
- Before scanning, `validate_ground_truth_in_scope` verifies that every labeled ground-truth file is in scope. If a labeled file would be excluded, the pipeline **fails loudly** (`ScopeExclusionError`) rather than silently dropping it.

### In-Scope LOC Normalization & Latency Basis
- Repository `loc`, **Clean FPR** (`clean_fp / in_scope_kLOC`), and **Scan Latency** (`vuln_duration_s / vuln_in_scope_kLOC`) are all computed strictly against the **in-scope LOC** of the filtered source copy.
- **Precision vs. Fix-Labeled Lines (Lower Bound):** Precision (`TP / (TP + FP)`) is evaluated strictly against fix-commit diff hunks; findings outside fix hunks are counted as `FP`, which yields a **lower bound** whenever a repo contains real pre-existing vulnerabilities.
- **Scan Latency Basis:** `duration_s` and `scan_latency` measure the **vulnerable commit only** (divided by the vulnerable commit's in-scope kLOC). This keeps latency directly comparable between dual-commit `cve_fix` repos and single-commit `intentionally_vulnerable` repos. Clean-commit scan duration (`clean_duration_s`) and combined wall time (`total_duration_s`) are recorded separately in `BenchmarkRun.run_metadata`.
- **Isolated Sequential Latency Fairness:** All tools reported in latency comparisons are executed **sequentially in isolation** (`latency_measurement_mode: "isolated_sequential"`), never concurrently competing for CPU or disk I/O. Per-stage timings (clone/fetch, filtered source copy, per-tool vuln/clean scans, CodeQL DB build vs. analysis, Semgrep container startup vs. scan, and evaluator) are persisted in `stage_timings`.

---

## 2. Security-Only Rule Policy

Only security vulnerability rules are counted; code-style, OOP, and assertion lints are excluded across all tools, with the exact ruleset/version recorded in `BenchmarkRun.run_metadata`:
- **CodeGuardian (`2.1.1-research`):** `SecurityASTScanner` (`SAST-*` AST security rules; `llm_calls: 0` in AST benchmark mode). *Changelog (2026-11-26):* Bumped from `2.1.0-research` to `2.1.1-research` to fix `SAST-001` `eval()`/`exec()` CWE tag from `CWE-78` to `CWE-95` (tag-only fix; no detection logic changed). Stored runs predating `2.1.1-research` (`aiohttp` `v1–v5`, `joblib` `v1–v2`, `setuptools` `v1`) are preserved as `is_superseded=True`, with subsequent active versions recomputed under `2.1.1-research`.
- **Semgrep OSS (`1.74.0`):** Pinned local security ruleset `benchmarks/rules/semgrep/python-security/` extracted from `semgrep/semgrep-rules` at commit `a5ad1714f00c9f7fde980cab0ea1d6dc6d414fd2` (304 rules: 254 `python/**/security` rules + 50 `generic/secrets/security` rules; `rules_commit` and `rules_sha256` recorded per run; `--metrics=off`, `--network none`, zero network at scan time). Licensed under **Semgrep Rules License v1.0** (`https://semgrep.dev/legal/rules-license`).
- **GitHub CodeQL (`2.16.2`):** `codeql/python-queries@0.9.8` suite `codeql/python-queries:codeql-suites/python-security-extended.qls` (security queries only, excluding `python-security-and-quality.qls` style rules).
- **Bandit (`1.8.6`):** Security checks only with `-s B101` (`assert_used` excluded) and non-CWE findings filtered out.
- **SonarQube Community (`10.4`):** `VULNERABILITY` and `SECURITY_HOTSPOT` issue types only (`CODE_SMELL` and `BUG` excluded).

---

## 3. Matching Rules & Ground-Truth Label Revision Disclosure

### Matching Rules (`src/benchmarks/evaluator.py`)
- **Detection Window (`max_detection_window = 10`):** A tool finding matches a labeled ground-truth hunk if it is in the same file and within `±10` lines of `[line_start, line_end]`.
- **Localization Window (`±3` lines):** Among matched true positives, `Localization Accuracy` counts the fraction within `±3` lines (`dist <= 3`) of the ground-truth span.
- **Per-Hunk Precision vs. Per-Label Recall:** **Recall** counts each ground-truth label at most once (`matched_gt_ids`), while **Precision** counts every finding falling within the `±10`-line detection window of a labeled hunk (`precision_tp`) as a true positive so multiple genuine sinks inside one hunk (e.g. `setuptools` lines `907` and `911` inside `906–919`) are not penalized as false positives.

### Label Version History & Revision Disclosure
*Disclosure: Ground-truth labels for `joblib` and `setuptools` were revised after initial benchmark results were observed; for `setuptools`, the 10-hunk review occurred after initial tool results were visible, but keep/remove decisions were made strictly by reading the parent and fix source code.*

| Repository | Version / File | Date (`mtime`) | Summary of Revision |
| :--- | :--- | :--- | :--- |
| `joblib/joblib` | `joblib_joblib_b90f10ef.json` (`v1`, 2 labels) | `2026-11-25 23:21` | Auto-extracted from `b90f10ef`; included docstring hunk (`line 507`) and malformed URL CWE. |
| `joblib/joblib` | `joblib_joblib_b90f10ef.v2.json` (`v2`, 1 label) | `2026-11-26 09:21` | AST/`tokenize` noise filter dropped docstring-only hunk (`507`); CWE set to `CWE-94` via `GHSA-6hrg-qmvc-2xh8` & NVD `CVE-2022-21797`. |
| `pypa/setuptools` | `pypa_setuptools_88807c70.json` (`v1`, 11 labels) | `2026-11-26 00:01` | Auto-extracted from `88807c70` (`cwe: "unknown"`). |
| `pypa/setuptools` | `pypa_setuptools_88807c70.v2.json` (`v2`, 10 labels) | `2026-11-26 09:44` | Re-extracted after AST/`tokenize` filter dropped `import subprocess` hunk (`line 3`). |
| `pypa/setuptools` | `pypa_setuptools_88807c70.v3.json` (`v3`, 2 labels) | `2026-11-26 10:24` | Kept only the 2 `os.system()` sink hunks (`872–898`, `906–919`), marked 8 refactor/helper/rename hunks as noise, and set `CWE-94` via `GHSA-cx63-2mw6-8hw5` (`CVE-2024-6345`). |

---

## 4. Sampled-Precision Audit Workflow (`src/benchmarks/sampled_precision.py`)

Because fix-labeled precision (`TP / (TP + FP)`) is a strict lower bound (unmatched findings may be real pre-existing vulnerabilities), we support a blinded sampled-precision audit:

- **Sampling Method:** Deterministic (`seed = 42`), repo-stratified random sample of up to `30` unmatched (`FP`) findings per tool across active repositories. Pooled findings are deduplicated across tools when they share the same repository, file path, normalized CWE, and line within `±3`, so each cluster is labeled once and applied to every tool that reported it. Tool names and rule IDs are stripped from the exported CSV and stored only in a separate import-time mapping file.
- **Labeling Rubric (Judged from Code Alone):** Each item is judged strictly from the `~15`-line surrounding source code context, never from tool identity or rule names:
  - `true_vuln`: Clearly exploitable or unsafe security sink/pattern on untrusted or insufficiently validated input.
  - `false_alarm`: Benign, dead/test-only, properly sanitized, or non-security pattern in context.
  - `uncertain`: Insufficient local context to determine exploitability without full inter-procedural dataflow; excluded from the `true_vuln / (true_vuln + false_alarm)` denominator and reported separately.
- **Statistical Reporting & Annotator Disclosure:** Per-tool sampled precision `true_vuln / (true_vuln + false_alarm)` is reported alongside its **95% Wilson score confidence interval** and sample size `n`, and remains hidden in the UI until an import exists. **Disclosure:** All sampled-precision items were labeled directly by the project author/user (`labeled_by = "user"`).

