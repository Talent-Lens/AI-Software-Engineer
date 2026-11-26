"""
Fast multi-threaded downloader for CodeQL bundle.
Downloads in 4MB chunks across 24 concurrent threads to bypass single-stream ISP/CDN rate limits.
Supports automatic resume of already downloaded chunks.
"""
import os
import sys
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "https://github.com/github/codeql-action/releases/download/codeql-bundle-v2.16.2/codeql-bundle-win64.tar.gz"
TOOLS_DIR = Path("tools")
CHUNKS_DIR = TOOLS_DIR / "chunks"
TARGET_ARCHIVE = TOOLS_DIR / "codeql-bundle-win64.tar.gz"
CODEQL_EXE = TOOLS_DIR / "codeql" / "codeql.exe"
CHUNK_SIZE = 1 * 1024 * 1024  # 1 MB
NUM_WORKERS = 32


def main():
    if CODEQL_EXE.exists():
        print(f"CodeQL already extracted at {CODEQL_EXE}")
        return

    TOOLS_DIR.mkdir(exist_ok=True)
    CHUNKS_DIR.mkdir(exist_ok=True)

    print("Resolving download URL and file size...", flush=True)
    head_resp = requests.head(URL, allow_redirects=True, timeout=30)
    if head_resp.status_code != 200:
        print(f"Failed to resolve head: {head_resp.status_code}", flush=True)
        sys.exit(1)

    direct_url = head_resp.url
    total_size = int(head_resp.headers.get("Content-Length", 0))
    print(f"Direct URL obtained. Total size: {total_size / (1024*1024):.2f} MB ({total_size} bytes)", flush=True)

    chunks = []
    start = 0
    idx = 0
    while start < total_size:
        end = min(start + CHUNK_SIZE - 1, total_size - 1)
        expected_len = end - start + 1
        chunk_file = CHUNKS_DIR / f"chunk_{idx:04d}.bin"
        chunks.append((idx, start, end, expected_len, chunk_file))
        start = end + 1
        idx += 1

    total_chunks = len(chunks)
    print(f"Total chunks: {total_chunks} of {CHUNK_SIZE/(1024*1024):.1f} MB each.", flush=True)

    def download_chunk(item):
        c_idx, c_start, c_end, c_expected, c_path = item
        if c_path.exists() and c_path.stat().st_size == c_expected:
            return c_idx, c_expected, True  # already downloaded

        headers = {"Range": f"bytes={c_start}-{c_end}", "User-Agent": "CodeQL-Downloader/1.0"}
        for attempt in range(5):
            try:
                resp = requests.get(direct_url, headers=headers, timeout=90)
                if resp.status_code in (200, 206) and len(resp.content) == c_expected:
                    c_path.write_bytes(resp.content)
                    return c_idx, c_expected, False
            except Exception as e:
                time.sleep(1 + attempt)
        raise RuntimeError(f"Failed to download chunk {c_idx} ({c_start}-{c_end}) after 5 attempts")

    t0 = time.time()
    completed_bytes = 0
    cached_chunks = 0
    new_chunks = 0

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {executor.submit(download_chunk, item): item for item in chunks}
        for future in as_completed(futures):
            c_idx, b_len, was_cached = future.result()
            completed_bytes += b_len
            if was_cached:
                cached_chunks += 1
            else:
                new_chunks += 1
            percent = (completed_bytes / total_size) * 100
            elapsed = time.time() - t0
            speed = (completed_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
            if (new_chunks + cached_chunks) % 10 == 0 or (new_chunks + cached_chunks) == total_chunks:
                print(
                    f"[{percent:5.1f}%] {new_chunks + cached_chunks}/{total_chunks} chunks "
                    f"({completed_bytes/(1024*1024):.1f} MB) at {speed:.2f} MB/s",
                    flush=True,
                )

    print(f"All chunks downloaded successfully in {time.time()-t0:.1f}s!", flush=True)
    print("Assembling chunks into archive...", flush=True)
    with open(TARGET_ARCHIVE, "wb") as outfile:
        for _, _, _, _, c_path in chunks:
            with open(c_path, "rb") as infile:
                while True:
                    buf = infile.read(64 * 1024)
                    if not buf:
                        break
                    outfile.write(buf)

    print(f"Archive assembled: {TARGET_ARCHIVE.stat().st_size} bytes.", flush=True)

    print("Extracting CodeQL bundle with tar...", flush=True)
    import subprocess
    subprocess.run(["tar", "-xzf", str(TARGET_ARCHIVE), "-C", str(TOOLS_DIR)], check=True)
    print("Extraction complete!", flush=True)

    # Clean up chunks and archive to save disk space
    import shutil
    shutil.rmtree(CHUNKS_DIR, ignore_errors=True)
    if TARGET_ARCHIVE.exists():
        TARGET_ARCHIVE.unlink()
    print("Cleaned up temporary chunk files and archive.", flush=True)
    print(f"CodeQL executable verified: {CODEQL_EXE.exists()}", flush=True)


if __name__ == "__main__":
    main()
