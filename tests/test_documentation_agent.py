"""
Unit & Integration Tests for TASK-R6 (Docstring Generator Agent & Context Formatter)
"""
from __future__ import annotations

import pytest
from pathlib import Path
from src.schema import Chunk, AgentResponse
from src.agents.documentation_agent import (
    DocstringAgent,
    MockLLMClient,
    detect_docstring_style,
    has_docstring,
    identify_undocumented_chunks,
    insert_docstring,
    generate_docs,
)


def test_detect_docstring_style():
    assert detect_docstring_style("src/auth.py") == "google"
    assert detect_docstring_style("components/Header.tsx") == "jsdoc"
    assert detect_docstring_style("service/UserService.java") == "javadoc"
    assert detect_docstring_style("main.go") == "godoc"


def test_has_docstring_python():
    documented = Chunk(
        id="c1",
        file_path="math.py",
        start_line=1,
        end_line=5,
        type="function",
        name="square",
        code='def square(x):\n    """Calculates the square of x."""\n    return x * x',
    )
    undocumented = Chunk(
        id="c2",
        file_path="math.py",
        start_line=6,
        end_line=10,
        type="function",
        name="cube",
        code="def cube(x):\n    return x * x * x",
    )

    assert has_docstring(documented) is True
    assert has_docstring(undocumented) is False


def test_has_docstring_js_and_go():
    js_doc = Chunk(
        id="c3",
        file_path="app.js",
        start_line=1,
        end_line=5,
        type="function",
        name="fetchData",
        code="/**\n * Fetches remote data.\n */\nfunction fetchData() { return fetch('/api'); }",
    )
    js_undoc = Chunk(
        id="c4",
        file_path="app.js",
        start_line=6,
        end_line=10,
        type="function",
        name="render",
        code="function render() { return null; }",
    )

    go_doc = Chunk(
        id="c5",
        file_path="main.go",
        start_line=1,
        end_line=5,
        type="function",
        name="CalculateTotal",
        code="// CalculateTotal sums line items\nfunc CalculateTotal() int { return 0 }",
    )

    assert has_docstring(js_doc) is True
    assert has_docstring(js_undoc) is False
    assert has_docstring(go_doc) is True


def test_identify_undocumented_chunks():
    c1 = Chunk(id="1", file_path="a.py", start_line=1, end_line=5, type="function", name="f1", code='def f1():\n    """Doc."""\n    pass')
    c2 = Chunk(id="2", file_path="a.py", start_line=6, end_line=10, type="function", name="f2", code="def f2():\n    pass")

    undoc = identify_undocumented_chunks([c1, c2])
    assert len(undoc) == 1
    assert undoc[0].name == "f2"


def test_insert_docstring_google_style():
    py_code = "def calculate_tax(amount, rate):\n    return amount * rate"
    docstr = "Calculates total tax amount.\n\nArgs:\n    amount: Base amount.\n    rate: Tax rate percentage."

    updated = insert_docstring(py_code, docstr, style="google")
    assert '"""' in updated
    assert "Calculates total tax amount." in updated
    assert "def calculate_tax(amount, rate):" in updated.splitlines()[0]


def test_insert_docstring_jsdoc_style():
    js_code = "function processPayment(cardToken) {\n    return true;\n}"
    docstr = "Processes credit card transaction.\n@param {string} cardToken\n@returns {boolean}"

    updated = insert_docstring(js_code, docstr, style="jsdoc")
    assert "/**" in updated
    assert " * Processes credit card transaction." in updated
    assert "function processPayment(cardToken)" in updated


def test_docstring_agent_with_mock_client(tmp_path: Path):
    sample_file = tmp_path / "sample.py"
    sample_file.write_text("def multiply(a, b):\n    return a * b\n", encoding="utf-8")

    agent = DocstringAgent(llm_client=MockLLMClient())
    response = agent.generate_docs_for_file(str(sample_file))

    assert isinstance(response, AgentResponse)
    assert response.agent_name == "documentation_agent"
    assert "multiply" in response.details["function_docs"]
    assert '"""' in response.details["function_docs"]["multiply"]


def test_auto_document_file_workflow(tmp_path: Path):
    target_file = tmp_path / "utils.py"
    target_file.write_text(
        "def compute_discount(price, percent):\n"
        "    return price * (percent / 100.0)\n",
        encoding="utf-8",
    )

    agent = DocstringAgent(llm_client=MockLLMClient())
    documented_code = agent.auto_document_file(str(target_file))

    assert "def compute_discount(price, percent):" in documented_code
    assert '"""Auto-generated docstring.' in documented_code
