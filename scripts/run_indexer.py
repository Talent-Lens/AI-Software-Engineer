from indexing.indexer import index_repository, search

collection = index_repository("test_repo/src")
search(collection, "How does basic authentication work?")