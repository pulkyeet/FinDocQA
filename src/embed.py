"""Embed chunks into ChromaDB for the 2x2 matrix: 2 strategies x 2 embedding models.

Collection name = "{strategy}__{model_key}" (e.g. "sectionaware__bge-small").
The rerank toggle is runtime, not a separate collection.

Some models (E5) expect instruction prefixes on the input text. We apply a
document prefix when encoding chunks and expose a query prefix for query.py.
"""

import json

import chromadb
from sentence_transformers import SentenceTransformer

from config import (
    CHROMA_DIR,
    CHUNKS_DIR,
    CHUNK_STRATEGIES,
    EMBEDDING_MODELS,
    TICKERS,
)


def doc_prefix(model_key: str) -> str:
    """Prefix prepended to each chunk text when embedding (E5 needs 'passage: ')."""
    return "passage: " if model_key.startswith("e5") else ""


def query_prefix(model_key: str) -> str:
    """Prefix prepended to the query text when embedding (E5 needs 'query: ')."""
    return "query: " if model_key.startswith("e5") else ""


def collection_name(strategy: str, model_key: str) -> str:
    return f"{strategy}__{model_key}"


def load_chunks(strategy: str):
    all_chunks = []
    for ticker in TICKERS:
        path = f"{CHUNKS_DIR}/{ticker}_{strategy}.json"
        with open(path) as f:
            chunks = json.load(f)
        for c in chunks:
            c["ticker"] = ticker
        all_chunks.extend(chunks)
    return all_chunks


def build_metadata(c) -> dict:
    m = {
        "ticker": c["ticker"],
        "type": c["type"],
        "anchor": c.get("anchor") or "none",
        "char_span_start": c["char_span"][0],
        "char_span_end": c["char_span"][1],
    }
    if c.get("item"):
        m["item"] = c["item"]
    if c.get("table_scale") is not None:
        m["table_scale"] = float(c["table_scale"])
    if c.get("page") is not None:
        m["page"] = int(c["page"])
    return m


def embed_collection(strategy: str, model_key: str, model_name: str, client) -> tuple:
    name = collection_name(strategy, model_key)
    print(f"\n=== Building collection: {name} ===")
    try:
        client.delete_collection(name)
    except Exception:
        pass
    collection = client.create_collection(name)

    chunks = load_chunks(strategy)
    print(f"Loaded {len(chunks)} {strategy} chunks across {len(TICKERS)} tickers")

    model = SentenceTransformer(model_name)
    prefix = doc_prefix(model_key)
    docs = [c["text"] for c in chunks]
    texts_for_embed = [prefix + d for d in docs]
    embeddings = model.encode(
        texts_for_embed, batch_size=32, show_progress_bar=True, normalize_embeddings=True
    )

    ids = [c["chunk_id"] for c in chunks]
    emb_list = embeddings.tolist()
    metas = [build_metadata(c) for c in chunks]
    batch_size = 5000
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i : i + batch_size],
            embeddings=emb_list[i : i + batch_size],
            documents=docs[i : i + batch_size],
            metadatas=metas[i : i + batch_size],
        )
    print(f"[embedded] {len(chunks)} chunks -> {name}")
    return name, len(chunks)


def main():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    results = []
    for strategy in CHUNK_STRATEGIES:
        for model_key, model_name in EMBEDDING_MODELS.items():
            name, n = embed_collection(strategy, model_key, model_name, client)
            results.append((name, n))
    print("\n=== Summary ===")
    for name, n in results:
        print(f"  {name}: {n} chunks")
    print()
    print("Collections on disk:", [c.name for c in client.list_collections()])


if __name__ == "__main__":
    main()
