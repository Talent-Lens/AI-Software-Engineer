"""
Docstring Generator Agent & Context Formatter — Production Enterprise Edition.
Task: TASK-R6 (Docstring Generator Agent & Context Formatter)

Inspects AST code chunks for missing documentation and generates language-specific
docstrings (Google-style for Python, JSDoc for JS/TS, JavaDoc for Java, GoDoc for Go).
Supports Groq Cloud API, Ollama local endpoints, and mock LLM testing clients.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Sequence

import requests
from src.indexing.chunker import chunk_file
from src.schema import AgentResponse, Chunk

logger = logging.getLogger("ai_engineer.agents.documentation")


def detect_docstring_style(file_path: str) -> str:
    """
    Detects docstring convention based on file extension.
    Returns: 'google' | 'jsdoc' | 'javadoc' | 'godoc'
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".py":
        return "google"
    elif ext in (".js", ".jsx", ".ts", ".tsx"):
        return "jsdoc"
    elif ext == ".java":
        return "javadoc"
    elif ext == ".go":
        return "godoc"
    return "google"


def has_docstring(chunk: Chunk) -> bool:
    """
    Determines if a Chunk (function, method, class) already has a docstring or comment header.
    """
    if not chunk or not chunk.code:
        return False

    code = chunk.code.strip()
    style = detect_docstring_style(chunk.file_path or "file.py")

    if style == "google":
        # Python: check if lines after signature contain triple quotes (""" or ''')
        lines = [line.strip() for line in code.splitlines()]
        if len(lines) > 1:
            body_start = "\n".join(lines[1:])
            if body_start.startswith('"""') or body_start.startswith("'''"):
                return True
            # Also check if docstring is on same line or immediate next lines
            if '"""' in body_start[:100] or "'''" in body_start[:100]:
                return True
        return False

    elif style in ("jsdoc", "javadoc"):
        # JS/TS/Java: check if code or preceding comments contain /** ... */
        if code.startswith("/**") or "/**" in code[:150]:
            return True
        return False

    elif style == "godoc":
        # Go: check if comment begins with // FunctionName
        func_name = chunk.name
        if code.startswith(f"// {func_name}") or f"// {func_name}" in code[:100]:
            return True
        return False

    return False


def identify_undocumented_chunks(chunks: Sequence[Chunk]) -> list[Chunk]:
    """
    Filters a sequence of Chunks down to functions, methods, and classes missing docstrings.
    Prioritizes functions and methods to avoid container overlap.
    """
    func_method_chunks = [
        c for c in chunks if c.type in ("function", "method") and not has_docstring(c)
    ]
    class_chunks = [
        c for c in chunks if c.type in ("class", "struct", "interface") and not has_docstring(c)
    ]

    undocumented = list(func_method_chunks)
    for cls in class_chunks:
        # Only add class chunk if none of its methods are being separately documented
        has_child = any(m.parent_name == cls.name for m in func_method_chunks)
        if not has_child:
            undocumented.append(cls)

    return undocumented


def insert_docstring(code: str, docstring: str, style: str = "google", base_indent: int = 0) -> str:
    """
    Inserts a formatted docstring into a raw code snippet cleanly.
    """
    if not code or not docstring:
        return code

    lines = code.splitlines()
    if not lines:
        return code

    clean_docstr = docstring.strip()

    if style == "google":
        # Find header definition line (e.g. def foo(): or class Bar:)
        def_idx = -1
        indent = " " * (base_indent + 4)
        for idx, line in enumerate(lines):
            if line.strip().startswith(("def ", "class ", "async def ")):
                def_idx = idx
                leading_ws = base_indent + (len(line) - len(line.lstrip()))
                indent = " " * (leading_ws + 4)
                break

        if def_idx != -1 and def_idx < len(lines):
            # Format docstring lines
            doc_lines = clean_docstr.splitlines()
            formatted_doc = []
            if not clean_docstr.startswith('"""'):
                formatted_doc.append(f'{indent}"""')
                for d_line in doc_lines:
                    formatted_doc.append(f"{indent}{d_line}" if d_line else "")
                formatted_doc.append(f'{indent}"""')
            else:
                for d_line in doc_lines:
                    formatted_doc.append(f"{indent}{d_line}" if d_line else "")

            # Insert docstrings right after definition header
            return "\n".join(lines[: def_idx + 1] + formatted_doc + lines[def_idx + 1 :])

    elif style in ("jsdoc", "javadoc"):
        # Format JSDoc/JavaDoc above definition or first line
        leading_ws = len(lines[0]) - len(lines[0].lstrip())
        indent = " " * leading_ws

        doc_lines = clean_docstr.splitlines()
        formatted_doc = []
        if not clean_docstr.startswith("/**"):
            formatted_doc.append(f"{indent}/**")
            for d_line in doc_lines:
                clean_l = d_line.lstrip("* ").strip()
                formatted_doc.append(f"{indent} * {clean_l}" if clean_l else f"{indent} *")
            formatted_doc.append(f"{indent} */")
        else:
            formatted_doc.extend([f"{indent}{d_line}" for d_line in doc_lines])

        return "\n".join(formatted_doc + lines)

    elif style == "godoc":
        # GoDoc format above function definition
        leading_ws = len(lines[0]) - len(lines[0].lstrip())
        indent = " " * leading_ws
        doc_lines = clean_docstr.splitlines()
        formatted_doc = []
        for d_line in doc_lines:
            clean_l = d_line.lstrip("/ ").strip()
            formatted_doc.append(f"{indent}// {clean_l}")

        return "\n".join(formatted_doc + lines)

    return code


class MockLLMClient:
    """Mock LLM client for rapid offline unit testing."""

    def generate(self, prompt: str) -> str:
        if "google" in prompt.lower() or "python" in prompt.lower():
            return '"""Auto-generated docstring.\n\nArgs:\n    param: Input description.\nReturns:\n    Result value.\n"""'
        elif "jsdoc" in prompt.lower():
            return "/**\n * Auto-generated JSDoc description.\n * @param {any} param\n * @returns {any}\n */"
        return "Auto-generated documentation summary."


class DocstringAgent:
    """
    Docstring Generator Agent supporting Groq Cloud API, Ollama local server, and Mock clients.
    """

    def __init__(
        self,
        model: str = "qwen-2.5-coder-32b",
        provider: str = "auto",
        llm_client: Any | None = None,
        timeout: int = 60,
    ) -> None:
        self.model = model
        self.provider = provider
        self.llm_client = llm_client
        self.timeout = timeout
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")

    def _call_llm(self, prompt: str) -> str:
        """Invokes configured LLM backend (Groq, Ollama, or Mock)."""
        if self.llm_client is not None:
            if hasattr(self.llm_client, "generate"):
                return self.llm_client.generate(prompt)
            elif callable(self.llm_client):
                return self.llm_client(prompt)

        # 1. Groq Cloud API
        if (self.provider in ("groq", "auto")) and self.groq_api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self.model if "coder" in self.model else "qwen-2.5-coder-32b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                }
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as err:
                logger.warning("Groq API call failed: %s. Falling back to Ollama.", err)

        # 2. Ollama Local Endpoint Fallback
        try:
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "qwen2.5:3b" if self.model == "qwen-2.5-coder-32b" else self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as err:
            logger.error("Ollama API call failed: %s", err)
            raise RuntimeError(f"Failed to query LLM provider: {err}")

    def generate_docstring_for_chunk(self, chunk: Chunk, style: str | None = None) -> str:
        """
        Generates a clean docstring for a single code Chunk.
        """
        target_style = style or detect_docstring_style(chunk.file_path or "code.py")
        prompt = f"""You are an expert AI software engineer. Generate a clear, concise docstring for the following {chunk.type}.

Style Requirement: {target_style.upper()}
Function/Class Name: {chunk.name}
Language File: {chunk.file_path}

Code:
```
{chunk.code}
```

Instructions:
1. Respond ONLY with the docstring text itself.
2. Do not wrap in markdown code blocks.
3. Include parameter types, return descriptions, and any raised exceptions.
"""
        raw_response = self._call_llm(prompt)

        # Clean markdown code fences if LLM included them
        clean_resp = re.sub(r"^```[a-zA-Z]*\n", "", raw_response.strip())
        clean_resp = re.sub(r"\n```$", "", clean_resp).strip()
        return clean_resp

    def generate_docs_for_file(
        self,
        file_path: str,
        only_missing: bool = True,
        style: str | None = None,
    ) -> AgentResponse:
        """
        Generates docstring explanations for all functions/classes in a file.
        Returns a structured AgentResponse object.
        """
        try:
            chunks = chunk_file(file_path)
            target_chunks = (
                identify_undocumented_chunks(chunks) if only_missing else chunks
            )
            target_chunks = [c for c in target_chunks if c.type in ("function", "method", "class")]

            if not target_chunks:
                return AgentResponse(
                    agent_name="documentation_agent",
                    summary=f"All {len(chunks)} code units in '{file_path}' are already documented.",
                    details={"file_path": file_path, "function_docs": {}, "status": "no_action_needed"},
                    confidence=1.0,
                )

            target_style = style or detect_docstring_style(file_path)
            doc_map: dict[str, str] = {}

            for c in target_chunks:
                docstr = self.generate_docstring_for_chunk(c, style=target_style)
                doc_map[c.name] = docstr

            return AgentResponse(
                agent_name="documentation_agent",
                summary=f"Generated {len(doc_map)} {target_style.upper()} docstrings for '{file_path}'.",
                details={
                    "file_path": file_path,
                    "style": target_style,
                    "function_docs": doc_map,
                    "undocumented_count": len(target_chunks),
                },
                confidence=0.95,
            )

        except Exception as err:
            logger.error("Docstring generation failed for '%s': %s", file_path, err)
            return AgentResponse(
                agent_name="documentation_agent",
                summary=f"Failed to generate documentation for '{file_path}': {err}",
                details={"error": str(err)},
                confidence=0.0,
            )

    def auto_document_file(
        self,
        file_path: str,
        output_path: str | None = None,
        only_missing: bool = True,
    ) -> str:
        """
        Reads source file, generates docstrings for missing chunks, and inserts them cleanly into the source code.
        """
        path_obj = Path(file_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        source_code = path_obj.read_text(encoding="utf-8")
        chunks = chunk_file(file_path)
        target_chunks = identify_undocumented_chunks(chunks) if only_missing else chunks
        target_chunks = [c for c in target_chunks if c.type in ("function", "method", "class")]

        if not target_chunks:
            return source_code

        target_style = detect_docstring_style(file_path)
        updated_code = source_code

        # Sort chunks in reverse order by start_line to avoid offset shifting during replacement
        sorted_target = sorted(target_chunks, key=lambda c: c.start_line, reverse=True)

        for c in sorted_target:
            docstr = self.generate_docstring_for_chunk(c, style=target_style)
            base_indent = 4 if (c.parent_name or c.type == "method") else 0
            updated_chunk_code = insert_docstring(c.code, docstr, style=target_style, base_indent=base_indent)
            updated_code = updated_code.replace(c.code, updated_chunk_code, 1)

        if output_path:
            Path(output_path).write_text(updated_code, encoding="utf-8")
            logger.info("Saved auto-documented file to '%s'.", output_path)

        return updated_code


def generate_docs(file_path: str, model: str = "qwen2.5:3b") -> AgentResponse:
    """
    Backward-compatible entry point for documentation agent.
    """
    agent = DocstringAgent(model=model)
    return agent.generate_docs_for_file(file_path)


__all__ = [
    "DocstringAgent",
    "generate_docs",
    "has_docstring",
    "identify_undocumented_chunks",
    "detect_docstring_style",
    "insert_docstring",
    "MockLLMClient",
]