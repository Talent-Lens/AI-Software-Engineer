"""
Codebase GraphRAG Module — Production Enterprise Edition.
Task: TASK-R7 (Codebase GraphRAG via NetworkX)

Builds directed code dependency graphs (imports, class inheritance hierarchy, call graphs)
using NetworkX and performs graph-guided context expansion for multi-file retrieval.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Sequence, cast

import networkx as nx
from src.retrieval.retriever import HybridRetriever
from src.schema import Chunk, RetrievalResult

logger = logging.getLogger("ai_engineer.retrieval.graph_rag")


RELATION_PRIORITY: dict[str, int] = {
    "INHERITS_FROM": 1,
    "EXTENDED_BY": 2,
    "CONTAINS": 3,
    "BELONGS_TO": 4,
    "CALLS": 5,
    "CALLED_BY": 6,
    "IMPORTS": 7,
}


def parse_class_inheritance(chunk: Chunk) -> list[str]:
    """
    Parses parent class names from class chunk header or code.
    Example: class User(BaseModel, AuthMixin): -> ['BaseModel', 'AuthMixin']
    """
    if chunk.type not in ("class", "struct", "interface"):
        return []

    code = chunk.code
    first_line = code.splitlines()[0] if code else ""

    # Python class Inheritance: class Child(Parent1, Parent2):
    py_match = re.search(r"class\s+\w+\s*\(([^)]+)\)", first_line)
    if py_match:
        parents = [p.strip() for p in py_match.group(1).split(",") if p.strip()]
        return [p for p in parents if p not in ("object", "type")]

    # Java / TS extends: class Child extends Parent implements Interface
    extends_match = re.search(r"extends\s+([A-Za-z0-9_]+)", first_line)
    if extends_match:
        return [extends_match.group(1).strip()]

    return []


def parse_symbol_calls(chunk: Chunk, known_symbols: set[str]) -> list[str]:
    """
    Identifies references to known codebase symbols within a chunk's code body.
    """
    if not chunk.code or not known_symbols:
        return []

    calls = []
    code = chunk.code
    for sym in known_symbols:
        if sym != chunk.name and re.search(r"\b" + re.escape(sym) + r"\b", code):
            calls.append(sym)
    return calls


class CodebaseGraph:
    """
    Directed Graph representation of a codebase using NetworkX.
    Nodes: Chunks, Files, and Classes.
    Edges: IMPORTS, INHERITS_FROM, CONTAINS, CALLS.
    """

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self._chunk_map: dict[str, Chunk] = {}
        self._name_to_chunk_id: dict[str, str] = {}

    def add_relation_edge(self, u: str, v: str, relation: str) -> None:
        """
        Adds or updates a directed edge from node u to node v.
        Preserves all relations in a set and sets primary relation based on priority.
        """
        if self.graph.has_edge(u, v):
            edge_data = self.graph.edges[u, v]
            relations = edge_data.get("relations")
            if not isinstance(relations, set):
                relations = set(relations) if relations else set()
            relations.add(relation)
            edge_data["relations"] = relations

            curr_rel = edge_data.get("relation", relation)
            cur_p = RELATION_PRIORITY.get(curr_rel, 99)
            new_p = RELATION_PRIORITY.get(relation, 99)
            if new_p < cur_p:
                edge_data["relation"] = relation
        else:
            self.graph.add_edge(u, v, relation=relation, relations={relation})

    def add_chunk(self, chunk: Chunk) -> None:
        """Adds a single Chunk node to the graph and indexes its name."""
        node_id = chunk.id
        self._chunk_map[node_id] = chunk
        if chunk.name:
            self._name_to_chunk_id[chunk.name] = node_id

        self.graph.add_node(
            node_id,
            id=node_id,
            name=chunk.name,
            type=chunk.type,
            file_path=chunk.file_path,
            parent_name=chunk.parent_name or "",
            chunk=chunk,
        )

        # 1. Connect parent scope (CONTAINS edge)
        if chunk.parent_name:
            parent_id = self._name_to_chunk_id.get(chunk.parent_name)
            if parent_id and self.graph.has_node(parent_id):
                self.add_relation_edge(parent_id, node_id, relation="CONTAINS")
                self.add_relation_edge(node_id, parent_id, relation="BELONGS_TO")

        # 2. Connect imports (IMPORTS edge)
        if chunk.imports:
            for imp in chunk.imports:
                imp_clean = imp.split(" import ")[-1].strip()
                self.graph.add_node(f"import::{imp_clean}", type="import", name=imp_clean)
                self.add_relation_edge(node_id, f"import::{imp_clean}", relation="IMPORTS")

                # Connect directly to target chunk if imported symbol is indexed
                target_id = self._name_to_chunk_id.get(imp_clean)
                if target_id and target_id != node_id:
                    self.add_relation_edge(node_id, target_id, relation="IMPORTS")

    def build_from_chunks(self, chunks: Sequence[Chunk]) -> None:
        """
        Populates the complete directed graph from a sequence of Chunks.
        Builds inheritance, container, import, and function call edges.
        """
        logger.info("Building Codebase Graph from %d chunks...", len(chunks))

        # First pass: add nodes
        for c in chunks:
            self.add_chunk(c)

        known_symbols = set(self._name_to_chunk_id.keys())

        # Second pass: connect inheritance and call edges
        for c in chunks:
            node_id = c.id

            # Parse class inheritance
            parents = parse_class_inheritance(c)
            for parent in parents:
                parent_node_id = self._name_to_chunk_id.get(parent)
                if parent_node_id:
                    self.add_relation_edge(node_id, parent_node_id, relation="INHERITS_FROM")
                    self.add_relation_edge(parent_node_id, node_id, relation="EXTENDED_BY")
                else:
                    # External or unindexed parent class
                    ext_id = f"class::{parent}"
                    self.graph.add_node(ext_id, type="class", name=parent)
                    self.add_relation_edge(node_id, ext_id, relation="INHERITS_FROM")

            # Parse function/symbol calls
            calls = parse_symbol_calls(c, known_symbols)
            for called_sym in calls:
                target_id = self._name_to_chunk_id.get(called_sym)
                if target_id and target_id != node_id:
                    self.add_relation_edge(node_id, target_id, relation="CALLS")
                    self.add_relation_edge(target_id, node_id, relation="CALLED_BY")

        logger.info(
            "Graph construction complete: %d nodes, %d edges.",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )

    def expand_context_with_distance(
        self,
        seed_chunks: Sequence[Chunk],
        max_depth: int = 1,
        max_expanded: int = 5,
    ) -> list[tuple[Chunk, int]]:
        """
        Performs graph-guided context expansion, returning tuples of (Chunk, distance_hops).
        """
        if not seed_chunks:
            return []

        seed_ids = {c.id for c in seed_chunks if c.id}
        visited_distances: dict[str, int] = {sid: 0 for sid in seed_ids}
        expanded: list[tuple[Chunk, int]] = []

        from collections import deque
        queue = deque((sid, 0) for sid in seed_ids if self.graph.has_node(sid))

        while queue and len(expanded) < max_expanded:
            curr_id, dist = queue.popleft()
            if dist >= max_depth:
                continue

            # Traversal across directed graph neighbors (outgoing & incoming relations)
            successors = set(self.graph.successors(curr_id)) if self.graph.has_node(curr_id) else set()
            predecessors = set(self.graph.predecessors(curr_id)) if self.graph.has_node(curr_id) else set()
            neighbors = successors.union(predecessors)

            for nbr in neighbors:
                if nbr not in visited_distances:
                    next_dist = dist + 1
                    visited_distances[nbr] = next_dist
                    if nbr in self._chunk_map:
                        expanded.append((self._chunk_map[nbr], next_dist))
                        if len(expanded) >= max_expanded:
                            break
                    queue.append((nbr, next_dist))

        return expanded

    def expand_context(
        self,
        seed_chunks: Sequence[Chunk],
        max_depth: int = 1,
        max_expanded: int = 5,
    ) -> list[Chunk]:
        """
        Performs graph-guided context expansion starting from initial seed chunks.
        Traverses network edges up to max_depth hops to retrieve dependent/parent chunks.

        Returns list of expanded Chunk objects (seed + graph expanded dependencies).
        """
        if not seed_chunks:
            return []

        expanded_tuples = self.expand_context_with_distance(
            seed_chunks=seed_chunks, max_depth=max_depth, max_expanded=max_expanded
        )
        expanded_chunks = list(seed_chunks)
        seed_ids = {c.id for c in seed_chunks}
        for chunk, _ in expanded_tuples:
            if chunk.id not in seed_ids:
                expanded_chunks.append(chunk)

        return expanded_chunks


class GraphRetriever:
    """
    GraphRAG Retriever combining Hybrid Search with Graph-Guided Context Expansion.
    """

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        codebase_graph: CodebaseGraph | None = None,
    ) -> None:
        self.hybrid_retriever = hybrid_retriever

        if codebase_graph is not None:
            self.codebase_graph = codebase_graph
        else:
            self.codebase_graph = CodebaseGraph()
            # Automatically build graph if chunks are available in BM25 indexer
            if hasattr(hybrid_retriever.bm25_indexer, "chunks") and hybrid_retriever.bm25_indexer.chunks:
                self.codebase_graph.build_from_chunks(hybrid_retriever.bm25_indexer.chunks)

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        enable_graph_expansion: bool = True,
        max_hops: int = 1,
        rerank: bool = False,
    ) -> list[RetrievalResult]:
        """
        Performs retrieval using Hybrid Search and expands retrieved results using GraphRAG.
        """
        # Step 1: Hybrid candidate retrieval (+ optional cross-encoder reranking)
        seed_results = self.hybrid_retriever.retrieve(query=query, top_k=top_k, rerank=rerank)
        if not enable_graph_expansion or not seed_results:
            return seed_results

        seed_chunks = [r.chunk for r in seed_results]

        # Step 2: Perform graph context expansion with hop distance tracking
        expanded_tuples = self.codebase_graph.expand_context_with_distance(
            seed_chunks=seed_chunks, max_depth=max_hops, max_expanded=5
        )

        # Step 3: Package expanded chunks into RetrievalResults with distance-decayed scoring
        final_results: list[RetrievalResult] = list(seed_results)
        seed_id_set = {c.id for c in seed_chunks}

        for chunk, dist in expanded_tuples:
            if chunk.id not in seed_id_set:
                score = max(0.2, 0.85 - (0.25 * dist))
                final_results.append(
                    RetrievalResult(chunk=chunk, score=score, query=query)
                )

        return final_results


def build_codebase_graph(chunks: Sequence[Chunk]) -> CodebaseGraph:
    """Helper function to build and return a CodebaseGraph instance from chunks."""
    graph = CodebaseGraph()
    graph.build_from_chunks(chunks)
    return graph


__all__ = [
    "CodebaseGraph",
    "GraphRetriever",
    "build_codebase_graph",
    "parse_class_inheritance",
    "parse_symbol_calls",
]

