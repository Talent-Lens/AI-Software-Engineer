from __future__ import annotations

import os
from typing import Any, cast
import chromadb
from chromadb.utils import embedding_functions

DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
FALLBACK_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_PERSIST_PATH = os.getenv("CHROMA_PERSIST_PATH", "./chroma_db")


def get_collection(
    name: str = "code_snippets",
    persist_path: str = DEFAULT_PERSIST_PATH,
    reset: bool = False,
    model_name: str | None = None,
) -> Any:
    """
    Retrieves or creates a persistent ChromaDB collection with dense embeddings.
    Defaults to BAAI/bge-m3 with graceful fallback to all-MiniLM-L6-v2 / default EF.
    """
    client = chromadb.PersistentClient(path=persist_path)

    if reset:
        try:
            client.delete_collection(name)
        except Exception:
            pass  # collection didn't exist yet, fine

    chosen_model = model_name or DEFAULT_EMBEDDING_MODEL

    sentence_transformer_ef = None
    # 1. Try preferred model (e.g. BAAI/bge-m3)
    try:
        sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=chosen_model
        )
    except Exception:
        # 2. Fallback to lightweight model (all-MiniLM-L6-v2)
        try:
            sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=FALLBACK_EMBEDDING_MODEL
            )
        except Exception:
            # 3. Default ChromaDB ONNX / internal fallback
            sentence_transformer_ef = embedding_functions.DefaultEmbeddingFunction()

    return client.get_or_create_collection(
        name=name, embedding_function=cast(Any, sentence_transformer_ef)
    )