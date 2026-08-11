# src/indexing/chunker.py
"""
Multi-Language AST Chunker — Parses Python, JavaScript, TypeScript, Java, and Go
source files using Tree-Sitter to extract semantically complete code chunks
(functions, methods, classes, structs, interfaces).
"""

from __future__ import annotations
import os
from typing import Optional

from tree_sitter import Language, Parser, Node
from src.schema import Chunk

# ---------------------------------------------------------------------------
# Tree-Sitter Language Parsers Setup
# ---------------------------------------------------------------------------
_LANGUAGES = {}
_PARSERS = {}

try:
    import tree_sitter_python as tspython
    _LANGUAGES["python"] = Language(tspython.language())
except ImportError:
    pass

try:
    import tree_sitter_javascript as tsjavascript
    _LANGUAGES["javascript"] = Language(tsjavascript.language())
except ImportError:
    pass

try:
    import tree_sitter_typescript as tstypescript
    _LANGUAGES["typescript"] = Language(tstypescript.language_typescript())
    _LANGUAGES["tsx"] = Language(tstypescript.language_tsx())
except ImportError:
    pass

try:
    import tree_sitter_java as tsjava
    _LANGUAGES["java"] = Language(tsjava.language())
except ImportError:
    pass

try:
    import tree_sitter_go as tsgo
    _LANGUAGES["go"] = Language(tsgo.language())
except ImportError:
    pass


def _get_parser_for_lang(lang_key: str) -> Optional[Parser]:
    if lang_key not in _LANGUAGES:
        return None
    if lang_key not in _PARSERS:
        parser = Parser(_LANGUAGES[lang_key])
        _PARSERS[lang_key] = parser
    return _PARSERS[lang_key]


# ---------------------------------------------------------------------------
# Language Configuration Matrix
# ---------------------------------------------------------------------------
# Extension -> (language_key, class_node_types, function_node_types)
EXTENSION_CONFIG: dict[str, tuple[str, set[str], set[str]]] = {
    ".py": (
        "python",
        {"class_definition"},
        {"function_definition"},
    ),
    ".js": (
        "javascript",
        {"class_declaration", "class"},
        {"function_declaration", "generator_function_declaration", "method_definition", "arrow_function"},
    ),
    ".jsx": (
        "javascript",
        {"class_declaration", "class"},
        {"function_declaration", "generator_function_declaration", "method_definition", "arrow_function"},
    ),
    ".ts": (
        "typescript",
        {"class_declaration", "interface_declaration", "enum_declaration", "type_alias_declaration"},
        {"function_declaration", "generator_function_declaration", "method_definition", "arrow_function"},
    ),
    ".tsx": (
        "tsx",
        {"class_declaration", "interface_declaration", "enum_declaration", "type_alias_declaration"},
        {"function_declaration", "generator_function_declaration", "method_definition", "arrow_function"},
    ),
    ".java": (
        "java",
        {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"},
        {"method_declaration", "constructor_declaration"},
    ),
    ".go": (
        "go",
        {"type_spec", "type_declaration"},
        {"function_declaration", "method_declaration"},
    ),
}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def _get_node_identifier(node: Node, source_bytes: bytes) -> str:
    """Extract node identifier (name) based on AST node structure across languages."""
    # 1. Try field 'name'
    name_node = node.child_by_field_name("name")
    if name_node and name_node.text:
        return name_node.text.decode("utf-8", errors="ignore")

    # 2. Walk children for identifier node types
    for child in node.children:
        if child.type in ("identifier", "property_identifier", "field_identifier", "type_identifier"):
            if child.text:
                return child.text.decode("utf-8", errors="ignore")

    # 3. Handle variable assignment of arrow functions (e.g. const foo = () => {})
    if node.type == "arrow_function" and node.parent:
        if node.parent.type == "variable_declarator":
            declarator_name = node.parent.child_by_field_name("name")
            if declarator_name and declarator_name.text:
                return declarator_name.text.decode("utf-8", errors="ignore")

    return "anonymous"


def _is_inside_class_or_struct(node: Node, class_types: set[str]) -> bool:
    """Check if function is enclosed within a class, struct, or interface."""
    parent = node.parent
    while parent is not None:
        if parent.type in class_types:
            return True
        parent = parent.parent
    return False


def _line_fallback_chunker(file_path: str, source: str, chunk_lines: int = 35, overlap: int = 5) -> list[Chunk]:
    """Fallback chunker splitting long source files into line-range windows."""
    lines = source.splitlines()
    if not lines:
        return []

    chunks = []
    total_lines = len(lines)
    step = max(1, chunk_lines - overlap)

    for start_idx in range(0, total_lines, step):
        end_idx = min(total_lines, start_idx + chunk_lines)
        code_slice = "\n".join(lines[start_idx:end_idx])
        start_line = start_idx + 1
        end_line = end_idx
        chunk_id = f"{file_path}::block::{start_line}"

        chunks.append(
            Chunk(
                id=chunk_id,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                type="code_block",
                name=f"lines_{start_line}_{end_line}",
                code=code_slice,
            )
        )
        if end_idx >= total_lines:
            break

    return chunks


# ---------------------------------------------------------------------------
# Public Entry Point
# ---------------------------------------------------------------------------
def chunk_file(file_path: str) -> list[Chunk]:
    """
    Parses a source code file using Tree-Sitter (if language is supported) or falls back
    to line-based chunking. Returns a list of structured Chunk objects.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []

    if not source.strip():
        return []

    ext = os.path.splitext(file_path)[1].lower()

    # If extension is not configured, use fallback line chunker
    if ext not in EXTENSION_CONFIG:
        return _line_fallback_chunker(file_path, source)

    lang_key, class_types, func_types = EXTENSION_CONFIG[ext]
    parser = _get_parser_for_lang(lang_key)

    if parser is None:
        return _line_fallback_chunker(file_path, source)

    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    chunks: list[Chunk] = []

    def walk(node: Node):
        if node.type in class_types or node.type in func_types:
            name = _get_node_identifier(node, source_bytes)
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            code = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

            if node.type in class_types:
                node_type = "class"
            elif _is_inside_class_or_struct(node, class_types) or node.type in ("method_definition", "method_declaration"):
                node_type = "method"
            else:
                node_type = "function"

            chunk_id = f"{file_path}::{name}::{start_line}"

            chunks.append(
                Chunk(
                    id=chunk_id,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    type=node_type,
                    name=name,
                    code=code,
                )
            )

        for child in node.children:
            walk(child)

    walk(root)

    # Fall back if tree-sitter found no structural nodes
    if not chunks:
        return _line_fallback_chunker(file_path, source)

    return chunks