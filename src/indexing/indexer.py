import os
from schema import Chunk
from indexing.vector_store import get_collection


def get_python_files(folder_path):
    py_files = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    return py_files


def read_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def index_repository(folder_path):
    collection = get_collection(name="repo_index")
    py_files = get_python_files(folder_path)

    chunks = []
    for path in py_files:
        content = read_file(path)
        if content.strip():
            chunk = Chunk(
                id=path,
                file_path=path,
                start_line=1,
                end_line=len(content.splitlines()),
                type="file",  # placeholder until Tree-sitter chunking (Day 10-14)
                name=os.path.basename(path),
                code=content,
            )
            chunks.append(chunk)

    collection.add(
        documents=[c.code for c in chunks],
        ids=[c.id for c in chunks],
        metadatas=[
            {
                "file_path": c.file_path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "type": c.type,
                "name": c.name,
            }
            for c in chunks
        ],
    )
    print(f"Indexed {len(chunks)} files.")
    return collection


def search(collection, query, n_results=3):
    results = collection.query(query_texts=[query], n_results=n_results)
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        print(f"\n[{meta['file_path']}] (distance={dist:.3f})")
        print(doc[:200], "...")