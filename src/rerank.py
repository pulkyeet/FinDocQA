"""Cross-encoder reranker: rerank a candidate pool to top-K by relevance.

Used to narrow the initial retrieve-20 down to a tighter top-K for the LLM
context. The model is held constant across all 8 configs.
"""

from sentence_transformers import CrossEncoder

from config import RERANKER_MODEL, RERANK_TOP_K


class Reranker:
    def __init__(self, model_name=RERANKER_MODEL):
        print(f"[reranker] loading {model_name}")
        self.model = CrossEncoder(model_name)

    def rerank(self, query, hits, top_k=RERANK_TOP_K):
        """Return top_k hits from `hits`, reranked by the cross-encoder score."""
        pairs = [(query, h["text"]) for h in hits]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(scores, hits), key=lambda x: -x[0])
        return [h for _, h in ranked[:top_k]]
