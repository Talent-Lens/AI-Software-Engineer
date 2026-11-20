"""
Unit tests for Independent Benchmark Router (src/api/routers/benchmark.py)
"""
import pytest
from pathlib import Path
from src.api.routers.benchmark import _normalize_rel, _extract_json_data

def test_extract_json_data_with_noisy_stdout():
    raw_output = 'Working... ---------------------------------------- 100% 0:00:08\n{\n  "results": [{"issue_text": "sample"}]\n}'
    data = _extract_json_data(raw_output)
    assert "results" in data
    assert len(data["results"]) == 1
    assert data["results"][0]["issue_text"] == "sample"

def test_extract_json_data_clean():
    data = _extract_json_data('{"status": "ok"}')
    assert data == {"status": "ok"}

def test_normalize_rel_cross_platform():
    base = Path("C:/Users/test/temp_repo")
    abs_win = "C:\\\\Users\\\\test\\\\temp_repo\\\\app\\\\server.py"
    rel_win = "app\\\\server.py"
    rel_posix = "app/server.py"
    dot_rel = "./app/server.py"

    assert _normalize_rel(abs_win, base) == "app/server.py"
    assert _normalize_rel(rel_win, base) == "app/server.py"
    assert _normalize_rel(rel_posix, base) == "app/server.py"
    assert _normalize_rel(dot_rel, base) == "app/server.py"


def test_find_cached_benchmark_corpora():
    from src.api.routers.benchmark import _find_cached_benchmark

    dsss_1 = _find_cached_benchmark("https://github.com/stamparm/DSSS/")
    assert dsss_1 is not None and "stamparm_DSSS" in dsss_1.name

    dsss_2 = _find_cached_benchmark("stamparm/DSSS")
    assert dsss_2 is not None and "stamparm_DSSS" in dsss_2.name

    flask_app = _find_cached_benchmark("https://github.com/we45/Vulnerable-Flask-App")
    assert flask_app is not None and "we45_Vulnerable-Flask-App" in flask_app.name

    req_app = _find_cached_benchmark("psf/requests")
    assert req_app is not None and "psf_requests" in req_app.name


def test_prepare_benchmark_repo_offline_fallback(monkeypatch, tmp_path):
    import subprocess
    from src.api.routers.benchmark import _prepare_benchmark_repo, _robust_rmtree

    def mock_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            128, "git",
            output="",
            stderr="fatal: unable to access 'https://github.com/stamparm/DSSS/': Could not resolve host: github.com"
        )

    monkeypatch.setattr(subprocess, "run", mock_run)

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    # Even with git failing due to 'Could not resolve host: github.com', the cached snapshot is used
    res = _prepare_benchmark_repo("https://github.com/stamparm/DSSS/", sandbox)
    assert "Pre-cached snapshot" in res
    assert (sandbox / "dsss.py").is_file()

    _robust_rmtree(sandbox)


def test_prepare_benchmark_repo_local_dir(tmp_path):
    from src.api.routers.benchmark import _prepare_benchmark_repo, _robust_rmtree

    dummy_repo = tmp_path / "dummy_local"
    dummy_repo.mkdir()
    (dummy_repo / "main.py").write_text("print('hello')", encoding="utf-8")

    sandbox = tmp_path / "sandbox_local"
    sandbox.mkdir()

    res = _prepare_benchmark_repo(str(dummy_repo), sandbox)
    assert (sandbox / "main.py").is_file()
    assert (sandbox / "main.py").read_text(encoding="utf-8") == "print('hello')"

    _robust_rmtree(dummy_repo)
    _robust_rmtree(sandbox)

