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
