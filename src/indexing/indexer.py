import os
import json
from src.indexing.chunker import chunk_file
from src.indexing.vector_store import get_collection

SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go"}


def get_repository_files(folder_path):
    repo_files = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                repo_files.append(os.path.join(root, f))
    return repo_files


def index_repository(folder_path, reset=True):
    collection = get_collection(name="repo_index", reset=reset)
    repo_files = get_repository_files(folder_path)

    all_chunks = []
    for path in repo_files:
        try:
            chunks = chunk_file(path)
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"Skipped {path}: {e}")

    if not all_chunks:
        print("No chunks found.")
        return collection

    collection.add(
        documents=[c.code for c in all_chunks],
        ids=[c.id for c in all_chunks],
        metadatas=[
            {
                "file_path": c.file_path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "type": c.type,
                "name": c.name,
                "parent_name": c.parent_name or "",
                "imports": json.dumps(c.imports),
            }
            for c in all_chunks
        ],
    )
    print(f"Indexed {len(all_chunks)} chunks from {len(repo_files)} files.")
    return collection


def search(collection, query, n_results=5):
    results = collection.query(query_texts=[query], n_results=n_results)
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        parent_info = f" (in {meta['parent_name']})" if meta.get("parent_name") else ""
        print(f"\n[{meta['type']}] {meta['name']}{parent_info} — {meta['file_path']} "
              f"(lines {meta['start_line']}-{meta['end_line']}, distance={dist:.3f})")
        print(doc[:200], "...")