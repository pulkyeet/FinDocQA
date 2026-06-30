"""Embed chunks into ChromaDB with collection name = (chunk_stragey, embedding_model)"""

import json
import chromadb

from sentence_transformers import SentenceTransformer
from config import CHUNKS_DIR, CHROMA_DIR, TICKERS, EMBEDDING_MODEL

STRATEGY = "fixedsize"
COLLECTION_NAME = f"{STRATEGY}__{EMBEDDING_MODEL.replace('/', '-')}"


def load_all_chunks():
    all_chunks = []
    for ticker in TICKERS:
        path = f"{CHUNKS_DIR}/{ticker}_{STRATEGY}.json"
        with open(path) as f:
            chunks = json.load(f)
        for c in chunks:
            c["ticker"] = ticker
        all_chunks.extend(chunks)
    return all_chunks


def main():
    chunks = load_all_chunks()
    print(f"Loaded {len(chunks)} chunks across {len(TICKERS)} tickers")

    model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    texts = [c["text"] for c in chunks]
    embeddings = model.encode(
        texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True
    )

    collection.add(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=[
            {
                "ticker": c["ticker"],
                "type": c["type"],
                "anchor": c["anchor"] or "none",
                "char_span_start": c["char_span"][0],
                "char_span_end": c["char_span"][1],
            }
            for c in chunks
        ],
    )
    print(f"[embdedded] {len(chunks)} chunks -> Chroma collection '{COLLECTION_NAME}'")


if __name__ == "__main__":
    main()
