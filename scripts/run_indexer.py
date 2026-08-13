from src.indexing.indexer import index_repository, search

collection = index_repository("src")
search(collection, "How does basic authentication work?")