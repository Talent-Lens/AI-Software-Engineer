# src/indexing/chunker.py
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
from src.schema import Chunk

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

def _get_name(node, source_bytes):
    """Extract the identifier (name) of a function/class node."""
    for child in node.children:
        if child.type == "identifier":
            return source_bytes[child.start_byte:child.end_byte].decode()
    return "unknown"


def _is_inside_class(node):
    """Walk up parents to check if this function is actually a method."""
    parent = node.parent
    while parent is not None:
        if parent.type == "class_definition":
            return True
        parent = parent.parent
    return False


def chunk_file(file_path):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source = f.read()
    source_bytes = source.encode("utf-8")

    tree = parser.parse(source_bytes)
    root = tree.root_node

    chunks = []

    def walk(node):
        if node.type in ("function_definition", "class_definition"):
            name = _get_name(node, source_bytes)
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            code = source_bytes[node.start_byte:node.end_byte].decode()

            if node.type == "class_definition":
                node_type = "class"
            elif _is_inside_class(node):
                node_type = "method"
            else:
                node_type = "function"

            chunk_id = f"{file_path}::{name}::{start_line}"

            chunks.append(Chunk(
                id=chunk_id,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                type=node_type,
                name=name,
                code=code,
            ))

        for child in node.children:
            walk(child)

    walk(root)
    return chunks