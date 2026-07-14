import chromadb
from chromadb.utils import embedding_functions

def get_collection(name="code_snippets", persist_path="./chroma_db"):
    client = chromadb.PersistentClient(path=persist_path)
    
    sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    
    collection = client.get_or_create_collection(
        name=name,
        embedding_function=sentence_transformer_ef
    )
    return collection