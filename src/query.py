"""Retrieve top-K chunks for a (strategy, model, rerank) config and generate an answer.

The 8 configs = 2 chunking strategies (fixedsize, sectionaware) x 2 embedding
models (bge-small, e5-small) x rerank on/off. Generation model is frozen in
.opencode/agent/chat.md and is NOT part of the config (plan sec 3).
"""

import argparse
import re
import subprocess

import chromadb
from sentence_transformers import SentenceTransformer

from config import (
    CHROMA_DIR,
    CHUNK_STRATEGIES,
    EMBEDDING_MODELS,
    OPENCODE_AGENT,
    TOP_K_FINAL,
    TOP_K_RETRIEVE,
)
from embed import collection_name, query_prefix
from rerank import Reranker


def parse_args():
    p = argparse.ArgumentParser(
        description="RAG query over a (strategy, model, rerank) config."
    )
    p.add_argument("question", help="The question to ask")
    p.add_argument(
        "--strategy",
        choices=CHUNK_STRATEGIES,
        default="sectionaware",
        help="Chunking strategy (default: sectionaware)",
    )
    p.add_argument(
        "--model",
        choices=list(EMBEDDING_MODELS),
        default="bge-small",
        help="Embedding model key (default: bge-small)",
    )
    p.add_argument(
        "--rerank",
        choices=["on", "off"],
        default="off",
        help="Cross-encoder rerank on/off (default: off)",
    )
    p.add_argument("--top-k-retrieve", type=int, default=TOP_K_RETRIEVE)
    p.add_argument("--top-k-final", type=int, default=TOP_K_FINAL)
    return p.parse_args()


def retrieve(question, model, collection, k, query_pfx):
    q_text = query_pfx + question
    q_emb = model.encode([q_text], normalize_embeddings=True).tolist()
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
            f"[chunk_id={h['chunk_id']} ticker={m['ticker']} anchor={m.get('anchor', '?')}]\n{h['text']}"
        )
    context = "\n\n-----\n\n".join(context_blocks)
    return f"""Answer the question using ONLY the context below. Cite the exact chunk_id(s) you used.
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


def main():
    args = parse_args()
    model_name = EMBEDDING_MODELS[args.model]
    print(
        f"[config] strategy={args.strategy} model={args.model} rerank={args.rerank}"
    )

    model = SentenceTransformer(model_name)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_collection(collection_name(args.strategy, args.model))

    hits = retrieve(
        args.question, model, col, args.top_k_retrieve, query_prefix(args.model)
    )
    print(f"[retrieved] {len(hits)} chunks (top distance={hits[0]['distance']:.3f})")

    if args.rerank == "on":
        reranker = Reranker()
        hits = reranker.rerank(args.question, hits, top_k=args.top_k_final)
        print(f"[reranked] top {len(hits)}")
    else:
        hits = hits[: args.top_k_final]

    print("[sent to LLM] anchors:", [h["meta"].get("anchor", "?") for h in hits])

    prompt = build_prompt(args.question, hits)
    answer = generate(prompt)
    print()
    print(answer)


if __name__ == "__main__":
    main()
