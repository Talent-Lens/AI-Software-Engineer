sentences = [
    "The cat sat on the mat.",
    "A dog was sleeping on the rug.",
    "def login(user, password): validate_jwt(token)",
    "Authentication uses JSON Web Tokens.",
    "def get_price(product_id): return db.query(product_id)",
    "The database stores product prices.",
    "I love pizza on Friday nights.",
    "Python is a popular programming language.",
    "The stock market crashed yesterday.",
    "def hash_password(pw): return bcrypt.hash(pw)",
]
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = model.encode(sentences)

import numpy as np

def cosine_similarity(a, b):
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    return dot_product / (norm_a * norm_b)

# Compare sentence 0 (cat) vs sentence 1 (dog) — should be fairly similar
print(cosine_similarity(embeddings[0], embeddings[1]))

# Compare sentence 2 (login/JWT code) vs sentence 3 (JWT auth description) — should be HIGH
print(cosine_similarity(embeddings[2], embeddings[3]))

# Compare sentence 0 (cat) vs sentence 2 (login code) — should be LOW
print(cosine_similarity(embeddings[0], embeddings[2]))

n = len(sentences)
matrix = np.zeros((n, n))

for i in range(n):
    for j in range(n):
        matrix[i][j] = cosine_similarity(embeddings[i], embeddings[j])

print(matrix.round(2))