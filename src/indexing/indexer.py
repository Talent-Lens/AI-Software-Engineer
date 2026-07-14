import os

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

from indexing.vector_store import get_collection

def index_repository(folder_path):
    collection = get_collection(name="repo_index")
    py_files = get_python_files(folder_path)

    documents = []
    ids = []
    metadatas = []

    for path in py_files:
        content = read_file(path)
        if content.strip():  # skip empty files
            documents.append(content)
            ids.append(path)                    # file path as unique ID
            metadatas.append({"filepath": path}) # useful for later (Bug Detection needs "which line/file")

    collection.add(documents=documents, ids=ids, metadatas=metadatas)
    print(f"Indexed {len(documents)} files.")
    return collection

def search(collection, query, n_results=3):
    results = collection.query(query_texts=[query], n_results=n_results)
    for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
        print(f"\n[{meta['filepath']}] (distance={dist:.3f})")
        print(doc[:200], "...")  # preview only

if __name__ == "__main__":
    collection = index_repository("path/to/some/repo")
    search(collection, "Where is JWT implemented?")