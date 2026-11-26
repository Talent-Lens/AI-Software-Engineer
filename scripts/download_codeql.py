import subprocess
import sys
from pathlib import Path

tools_dir = Path("tools")
tools_dir.mkdir(exist_ok=True)
archive = tools_dir / "codeql-bundle-win64.tar.gz"
codeql_exe = tools_dir / "codeql" / "codeql.exe"

if codeql_exe.exists():
    print("CodeQL executable already present:", codeql_exe)
    sys.exit(0)

url = "https://github.com/github/codeql-action/releases/download/codeql-bundle-v2.16.2/codeql-bundle-win64.tar.gz"

cmd = [
    "curl.exe",
    "-C", "-",
    "--retry", "50",
    "--retry-delay", "3",
    "--retry-all-errors",
    "-L",
    "-o", str(archive),
    url,
]

print("Starting/resuming CodeQL bundle download...", flush=True)
res = subprocess.run(cmd)
if res.returncode == 0:
    print("Download finished. Extracting archive...", flush=True)
    subprocess.run(["tar", "-xzf", str(archive), "-C", str(tools_dir)], check=True)
    if archive.exists():
        archive.unlink()
    print("CodeQL extracted successfully!", flush=True)
else:
    print(f"Download failed with returncode {res.returncode}", flush=True)
