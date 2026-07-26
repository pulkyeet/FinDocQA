"""Stage 3-4: Section and paragraph alignment for Delta pipeline.

Stage 3: align sections by anchor equality.
Stage 4: embed paragraphs and greedy-match between years.
"""

import json
import os

import numpy as np
from sentence_transformers import SentenceTransformer

from config import CHUNKS_DIR, ALIGN_SIMILARITY_FLOOR
from embed import doc_prefix

_model_cache: dict[str, SentenceTransformer] = {}


def _get_model(model_name: str) -> SentenceTransformer:
    if model_name not in _model_cache:
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def split_into_paragraphs(text: str) -> list[str]:
    """Split chunk text on double newlines into paragraphs.

    Filters empty and whitespace-only paragraphs.
    """
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def load_chunks_for_year(ticker: str, fiscal_year: str, strategy: str = "sectionaware") -> list[dict]:
    """Load chunks for a specific ticker + fiscal year."""
    path = f"{CHUNKS_DIR}/{ticker}_{fiscal_year}_{strategy}.json"
    with open(path) as f:
        return json.load(f)


def group_by_anchor(chunks: list[dict]) -> dict[str, list[dict]]:
    """Group chunks by their anchor field.

    Returns {anchor: [chunks]}.
    """
    groups: dict[str, list[dict]] = {}
    for c in chunks:
        anchor = c.get("anchor") or "unknown"
        groups.setdefault(anchor, []).append(c)
    return groups


def align_sections(old_chunks: list[dict], new_chunks: list[dict]) -> list[tuple[str, list[dict], list[dict]]]:
    """Stage 3: pair sections by anchor equality.

    Returns [(anchor, old_chunks, new_chunks), ...].
    Sections only in old are flagged with empty new_chunks (removal).
    Sections only in new are flagged with empty old_chunks (addition).
    """
    old_groups = group_by_anchor(old_chunks)
    new_groups = group_by_anchor(new_chunks)

    all_anchors = set(old_groups.keys()) | set(new_groups.keys())
    pairs = []
    for anchor in sorted(all_anchors):
        pairs.append((anchor, old_groups.get(anchor, []), new_groups.get(anchor, [])))
    return pairs


def embed_paragraphs(paragraphs: list[str], model_key: str = "bge-small") -> np.ndarray:
    """Embed a list of paragraph texts using a SentenceTransformer.

    Applies the model-appropriate document prefix (E5: 'passage: ').
    """
    from config import EMBEDDING_MODELS

    model_name = EMBEDDING_MODELS.get(model_key)
    if model_name is None:
        raise ValueError(f"Unknown model key: {model_key}")
    model = _get_model(model_name)
    prefix = doc_prefix(model_key)
    texts = [prefix + p for p in paragraphs]
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
    return embeddings


def match_paragraphs(
    old_paras: list[str],
    new_paras: list[str],
    old_embs: np.ndarray,
    new_embs: np.ndarray,
    similarity_floor: float = ALIGN_SIMILARITY_FLOOR,
) -> dict:
    """Stage 4: greedy best-match paragraph alignment via cosine similarity.

    Sorts all (old, new) pairs by similarity descending, assigns without
    reuse. Pairs below similarity_floor are left unmatched.

    Returns dict with keys:
      - matches: [{old_idx, new_idx, similarity}, ...]
      - added: [new_idx, ...]
      - removed: [old_idx, ...]
    """
    if len(old_embs) == 0 and len(new_embs) == 0:
        return {"matches": [], "added": [], "removed": []}

    if len(old_embs) == 0:
        return {"matches": [], "added": list(range(len(new_paras))), "removed": []}

    if len(new_embs) == 0:
        return {"matches": [], "added": [], "removed": list(range(len(old_paras)))}

    sim_matrix = np.dot(old_embs, new_embs.T)

    pairs = []
    for i in range(len(old_paras)):
        for j in range(len(new_paras)):
            pairs.append((sim_matrix[i, j], i, j))

    pairs.sort(key=lambda x: x[0], reverse=True)

    old_used = set()
    new_used = set()
    matches = []

    for sim, oi, nj in pairs:
        if sim < similarity_floor:
            break
        if oi not in old_used and nj not in new_used:
            matches.append({"old_idx": oi, "new_idx": nj, "similarity": float(sim)})
            old_used.add(oi)
            new_used.add(nj)

    added = [j for j in range(len(new_paras)) if j not in new_used]
    removed = [i for i in range(len(old_paras)) if i not in old_used]

    return {"matches": matches, "added": added, "removed": removed}


def align_section_pair(
    old_chunks: list[dict],
    new_chunks: list[dict],
    model_key: str = "bge-small",
) -> dict:
    """Full alignment for one section pair.

    Reconstructs section text from chunks, splits into paragraphs,
    embeds, and matches.

    Returns {anchor, old_paras, new_paras, matches, added, removed}.
    """
    anchor = None
    if old_chunks:
        anchor = old_chunks[0].get("anchor")
    elif new_chunks:
        anchor = new_chunks[0].get("anchor")

    old_text = "\n\n".join(c["text"] for c in old_chunks) if old_chunks else ""
    new_text = "\n\n".join(c["text"] for c in new_chunks) if new_chunks else ""

    old_paras = split_into_paragraphs(old_text) if old_text else []
    new_paras = split_into_paragraphs(new_text) if new_text else []

    old_embs = embed_paragraphs(old_paras, model_key) if old_paras else np.array([])
    new_embs = embed_paragraphs(new_paras, model_key) if new_paras else np.array([])

    result = match_paragraphs(old_paras, new_paras, old_embs, new_embs)
    result["anchor"] = anchor
    result["old_paras"] = old_paras
    result["new_paras"] = new_paras

    return result
