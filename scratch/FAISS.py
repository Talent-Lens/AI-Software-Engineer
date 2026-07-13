import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

corpus = [
    "def login(user, password): validate_jwt(token)",
    "def get_price(product_id): return db.query(product_id)",
    "def hash_password(pw): return bcrypt.hash(pw)",
    "The cat sat on the mat.",
    "Authentication uses JSON Web Tokens.",
]

embeddings = model.encode(corpus)
embeddings = np.array(embeddings).astype("float32")  # FAISS requires float32

# Build the index
dimension = embeddings.shape[1]  # 384 for this model
index = faiss.IndexFlatL2(dimension)  # simplest index: exact search, L2 distance
index.add(embeddings)

print(f"Number of vectors in index: {index.ntotal}")

# Search
query = "Where is JWT implemented?"
query_embedding = model.encode([query]).astype("float32")

k = 3  # top 3 results
distances, indices = index.search(query_embedding, k)

print("Top results:")
for rank, idx in enumerate(indices[0]):
    print(f"{rank+1}. (distance={distances[0][rank]:.3f}) {corpus[idx]}")