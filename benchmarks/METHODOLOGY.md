# CodeGuardian Research Benchmark Methodology

## 1. Objective & Scientific Foundation
The CodeGuardian Research Benchmark provides an empirical, reproducible, and tool-independent methodology for evaluating static code security analysis tools. 

Unlike conventional benchmarking approaches that designate a single scanner (such as Bandit or Flake8) as the "judge", this benchmark relies on **strictly independent ground truth**:
1. **Pre/Post CVE Fix Commits:** Vulnerable lines derived from bug-fixing commits prior to resolution, with post-fix clean snapshots providing negative controls.
2. **Documented Vulnerable Repositories:** Industry testbeds (e.g., OWASP Benchmark, SecRepo, and intentionally vulnerable reference applications) with author-verified findings.
3. **Pooled Manual Triage:** The union of candidate findings across all evaluated static analysis tools, manually triaged and verified by human analysts.

---

## 2. The Six Evaluation Metrics

| Metric | Exact Mathematical Definition | Interpretation & Baseline Unit |
| :--- | :--- | :--- |
| **1. Precision** | $$\frac{TP}{TP + FP}$$ | Computed over the vulnerable snapshot. Measures the signal-to-noise ratio of flagged alerts. |
| **2. Recall** | $$\frac{TP}{TP + FN}$$ | Percentage of labeled ground-truth vulnerabilities detected. Labeled as *"Recall vs Verified Pool"* when evaluating pooled triage. |
| **3. False Positive Rate (FPR)** | $$\frac{\text{Clean-FPs}}{\text{kLOC}}$$ | False alarms per **1,000 lines of clean code** (kLOC) evaluated on the post-fix (clean) commit snapshot. |
| **4. Line-Level Localization** | $$\frac{TP_{[\pm 3\text{ lines}]}}{TP}$$ | Share of true positive detections whose reported line number is within **$\pm 3$ lines** of the labeled ground truth line. |
| **5. Vulnerability Classification** | $$\frac{TP_{[\text{CWE Match}]}}{TP}$$ | Share of true positive detections whose reported CWE matches the labeled CWE directly or via the standardized CWE Equivalence Map. |
| **6. Scan Latency** | $$\frac{\text{Wall-Clock Seconds}}{\text{kLOC}}$$ | Throughput measured with warmed-up tools on the same hardware. For CodeQL, includes database build time. |

---

## 3. Matching & Localization Rules
- **Line Window ($\pm 3$ Lines):** A tool finding is localized as a True Positive if its flagged range $[L_{start}, L_{end}]$ intersects $[L_{gt} - 3, L_{gt} + 3]$ in the target file. Flagging an entire file or a 200-line function without pinpointing the vulnerable statement does not qualify as localized.
- **CWE Equivalence Map:** Security scanners frequently report issues at varying hierarchy depths (e.g., specific vs general CWEs). We apply a formalized parent-child taxonomy mapping:
  - **SQL Injection:** CWE-89, CWE-564 (Hibernate SQLi), CWE-943 (NoSQLi).
  - **Command Injection:** CWE-78 (OS Command), CWE-77 (Command Injection).
  - **Insecure Deserialization:** CWE-502 (Pickle / YAML / Java deserialization).
  - **Hardcoded Secrets:** CWE-798 (Hardcoded Credentials), CWE-259, CWE-321.
  - **Path Traversal:** CWE-22, CWE-23, CWE-36.
  - **XSS:** CWE-79, CWE-80, CWE-83.
  - **Insecure Cryptography / Hash:** CWE-327, CWE-328 (MD5/SHA1), CWE-330 (Weak PRNG).

---

## 4. Ground-Truth Data Format
Ground-truth manifests are maintained in version-controlled JSON files under `benchmarks/ground_truth/{repo_name}.json`.

```json
{
  "repo_name": "we45/Vulnerable-Flask-App",
  "url": "https://github.com/we45/Vulnerable-Flask-App",
  "language": "python",
  "loc": 1420,
  "vulnerable_commit": "a1b2c3d4e5f6...",
  "clean_commit": "f6e5d4c3b2a1...",
  "findings": [
    {
      "id": "GT-VFA-01",
      "file_path": "app.py",
      "line_number": 28,
      "cwe": "CWE-502",
      "severity": "HIGH",
      "label": "vulnerable",
      "source": "documented-vuln",
      "notes": "Untrusted pickle deserialization loading model weights without validation"
    }
  ]
}
```

---

## 5. Tool Versions & Environments
All competitor comparisons run offline on identical hardware under pinned commit SHAs:
- **CodeGuardian:** v1.0.0 (AST + OWASP SAST Rules + Qwen-2.5 Coder 32B Semantic Verifier)
- **Semgrep OSS:** Container image `semgrep/semgrep:1.74.0` executed in isolated Docker runtime (`--network none`, `--metrics=off`, read-only repo mount at `/src:ro`). Pinned local ruleset: `benchmarks/rules/semgrep/pinned_rules.yaml` (rules: `python-sqli-formatted-string` for CWE-89, `python-hardcoded-secret-key` for CWE-798, and `python-insecure-tempfile-mktemp` for CWE-377). Timing measures exclusively internal scan execution time (`data["time"]["total_time"]`), excluding container startup and mount overhead.
- **CodeQL CLI:** v2.16.0+ (python-security-and-quality suite)
- **SonarQube Community:** v10.4+ (Sonar Way Default Profile via sonar-scanner CLI)
- **Bandit (Reference Line Only):** v1.7.8 (Included purely as a baseline comparison, never as the ground-truth judge)

---

## 6. Known Limitations
1. **Relative Nature of Pooled Recall:** For repositories lacking formal CVE proofs, recall is measured against the pooled findings of all participating tools. This represents *relative recall* ($\text{Union}(T_1, \dots, T_n)$), not absolute theoretical recall.
2. **Tool Failure Transparency:** If a competitor fails to execute or does not support a given language/framework, its status is explicitly reported as `unsupported_platform` or `tool_failed` rather than silently distorting averages with synthetic zeros.
