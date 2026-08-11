from src.indexing.vector_store import get_collection
from src.retrieval.rag import rag_query

collection = get_collection(name="repo_index")
answer = rag_query(collection, "Where is authentication handled in this repo?")
print(answer)