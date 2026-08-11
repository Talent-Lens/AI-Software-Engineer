from typing import Any, cast
import chromadb
from chromadb.utils import embedding_functions

def get_collection(name="code_snippets", persist_path="./chroma_db", reset=False):
    client = chromadb.PersistentClient(path=persist_path)
    
    if reset:
        try:
            client.delete_collection(name)
        except Exception:
            pass  # collection didn't exist yet, fine

    sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    return client.get_or_create_collection(name=name, embedding_function=cast(Any, sentence_transformer_ef))