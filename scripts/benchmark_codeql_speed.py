import tempfile
import time
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.benchmarks.runners.codeql_runner import CodeQLRunner

runner = CodeQLRunner()

with tempfile.TemporaryDirectory() as tmp:
    src_dir = Path(tmp) / "src"
    src_dir.mkdir()
    code = (
        "import os\n"
        "import sqlite3\n"
        "import tempfile\n\n"
        "def f(user_id):\n"
        "    query = f\"SELECT * FROM users WHERE id = '{user_id}'\"\n"
        "    filename = tempfile.mktemp()\n"
        "    return filename\n"
    )
    (src_dir / "app.py").write_text(code, encoding="utf-8")
    db_dir = Path(tmp) / "db"

    t0 = time.time()
    create_res = subprocess.run(
        [
            runner.executable,
            "database",
            "create",
            str(db_dir),
            "--language=python",
            f"--source-root={src_dir}",
            "--overwrite",
            "--threads=0",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    t_create = time.time() - t0
    print(f"DB created in {t_create:.2f}s", flush=True)

    sarif = Path(tmp) / "out.sarif"
    suite = "codeql/python-queries:codeql-suites/python-security-extended.qls"
    t1 = time.time()
    res = subprocess.run(
        [
            runner.executable,
            "database",
            "analyze",
            str(db_dir),
            suite,
            "--threads=0",
            "--format=sarif-latest",
            f"--output={sarif}",
        ],
        capture_output=True,
        text=True,
    )
    t_analyze = time.time() - t1
    print(f"Analyze exit code: {res.returncode} in {t_analyze:.2f}s", flush=True)
    if sarif.exists():
        findings = runner.parse_sarif(sarif.read_text(encoding="utf-8"))
        print(f"Parsed {len(findings)} findings:", flush=True)
        for f in findings:
            print(f"  {f.file_path}:{f.line_start} [{f.cwe}] {f.rule_id} - {f.title}", flush=True)
    else:
        print("Stderr:", res.stderr[:500], flush=True)
