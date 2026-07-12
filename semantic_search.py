from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer("all-MiniLM-L6-v2")

corpus = [
    "def login(user, password): validate_jwt(token)",
    "def get_price(product_id): return db.query(product_id)",
    "def hash_password(pw): return bcrypt.hash(pw)",
]

query = "Where is JWT implemented?"

corpus_embeddings = model.encode(corpus)
query_embedding = model.encode(query)

scores = util.cos_sim(query_embedding, corpus_embeddings)[0]

for score, text in sorted(zip(scores, corpus), reverse=True):
    print(f"{score:.3f}  {text}")