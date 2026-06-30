"""Takes an embedded question and retreives 20 chunks with citations"""

import re
import subprocess
import sys

import chromadb
from sentence_transformers import SentenceTransformer

from config import (
    CHROMA_DIR,
    EMBEDDING_MODEL,
    OPENCODE_AGENT,
    TOP_K_RETRIEVE,
)
from embed import COLLECTION_NAME


def retrieve(question, model, collection, k=TOP_K_RETRIEVE):
    q_emb = model.encode([question], normalize_embeddings=True).tolist()
    results = collection.query(query_embeddings=q_emb, n_results=k)
    hits = []
    for i in range(len(results["ids"][0])):
        hits.append(
            {
                "chunk_id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "meta": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
        )
    return hits


def build_prompt(question, hits):
    context_blocks = []
    for h in hits:
        m = h["meta"]
        context_blocks.append(
            f"[chunk_id={h['chunk_id']} ticker={m['ticker']}]\n{h['text']}"
        )
    context = "\n\n-----\n\n".join(context_blocks)
    return f"""Answer the question using ONLY the context below. After your answer, cite the exact chunk_id(s) you used.
If the answer is not in the context, say "Not found in corpus" — do not guess.
 
Context:
{context}
 
Question: {question}
 
Answer (end with "Citations: [chunk_id, ...]"):"""


def generate(prompt):
    result = subprocess.run(
        ["opencode", "run", "--agent", OPENCODE_AGENT, prompt],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"opencode run failed: {result.stderr}")
    out = result.stdout
    out = re.sub(r"^\x1b\[.*?m", "", out, flags=re.MULTILINE)
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("> ")]
    return "\n".join(lines).strip()


def main(question):
    model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection(COLLECTION_NAME)

    hits = retrieve(question, model, collection)
    print(f"[retrived] {len(hits)} chunks (top distance={hits[0]['distance']:.3f})\n")

    prompt = build_prompt(question, hits)
    answer = generate(prompt)
    print(answer)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python query.py "your question"')
        sys.exit(1)
    main(sys.argv[1])
