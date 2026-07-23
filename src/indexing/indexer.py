import os
from indexing.chunker import chunk_file
from indexing.vector_store import get_collection


def get_python_files(folder_path):
    py_files = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    return py_files


def index_repository(folder_path, reset=True):
    collection = get_collection(name="repo_index", reset=reset)
    py_files = get_python_files(folder_path)

    all_chunks = []
    for path in py_files:
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
            }
            for c in all_chunks
        ],
    )
    print(f"Indexed {len(all_chunks)} chunks from {len(py_files)} files.")
    return collection


def search(collection, query, n_results=5):
    results = collection.query(query_texts=[query], n_results=n_results)
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        print(f"\n[{meta['type']}] {meta['name']} — {meta['file_path']} "
              f"(lines {meta['start_line']}-{meta['end_line']}, distance={dist:.3f})")
        print(doc[:200], "...")