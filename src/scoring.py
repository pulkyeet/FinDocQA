"""Deterministic scoring functions for the FinDocQA eval harness.

Implements plan §6, §7, §8:
- extract_numbers: robust number extraction from answer text (currency, scales,
  paren-negatives, sign context for losses, percentages, citation-block strip,
  year-token skip).
- numeric_match: normalize-and-compare with 5% tolerance and near-zero guard.
- retrieval_score: anchor set membership (primary) + span-overlap (fallback
  for fixed-size chunks that have anchor=None).
- routing_score: 3-way classification (corpus / abstain / web).

These are pure functions; no I/O.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# extract_numbers
# ---------------------------------------------------------------------------

CITE_BLOCK_RE = re.compile(
    r"citations?\s*:\s*\[.*?\]", re.IGNORECASE | re.DOTALL
)
# Also strip a trailing citations line like "Citations: chunk_id" (no brackets)
CITE_LINE_RE = re.compile(
    r"\n?\s*citations?\s*:.*$", re.IGNORECASE | re.DOTALL
)

WORD_SCALE = {
    "billion": 1e9, "millions": 1e6, "million": 1e6, "thousand": 1e3,
    "thousands": 1e3, "trillion": 1e12,
}
ABBR_SCALE = {"b": 1e9, "m": 1e6, "k": 1e3, "t": 1e12}

NEG_CONTEXTS = ["loss", "deficit", "decrease", "decline", "negative"]

# A "number with optional unit" pattern.
# Group 1: the number body (with optional commas, decimal, parens, leading $)
# Group 2: optional trailing unit/word (%, percent, billion, million, B, M, K, ...)
NUM_RE = re.compile(
    r"("
    r"\$\s*\(\s*-?\s*[\d,]+(?:\.\d+)?\s*\)"
    r"|"
    r"\(\s*\$?\s*-?\s*[\d,]+(?:\.\d+)?\s*\)"
    r"|"
    r"-?\s*[\d,]+(?:\.\d+)?"
    r")"
    r"(?:\s*(percent|percentage|%|billion|million|thousand|trillion|[bmkt]))?(?![\w])",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def extract_numbers(text: str, cited_metas: Optional[list] = None) -> list:
    """Extract candidate numeric values (in BASE units) from answer text.

    - Strips the "Citations: [...]" block to avoid chunk-id false positives.
    - Strips a trailing "Citations: ..." line.
    - Inline magnitude words ("billion", "million") win over table_scale.
    - table_scale from cited chunk metadata applies to bare numbers.
    - Paren-negatives and leading-minus produce negative values.
    - Keyword context ("net loss of $X") flips sign of a positive $X.
    - Percentages emit both raw (e.g. 9.2) and decimal (0.092) forms.
    - 4-digit year tokens (1900-2099) with no $ and no unit are skipped.
    """
    if not text:
        return []
    # Strip citation blocks
    text = CITE_BLOCK_RE.sub("", text)
    text = CITE_LINE_RE.sub("", text)

    # table_scale from cited chunks
    table_scale = None
    if cited_metas:
        for m in cited_metas:
            if not isinstance(m, dict):
                continue
            ts = m.get("table_scale")
            if ts:
                table_scale = float(ts)
                break

    out = []
    for m in NUM_RE.finditer(text):
        body = m.group(1)
        unit = (m.group(2) or "").lower()
        full_match = m.group(0)

        # Strip $ for parsing (it can appear outside or inside the paren form)
        s = body.strip()
        has_dollar = "$" in s
        s = s.replace("$", "").strip()
        is_paren = s.startswith("(") and s.endswith(")")
        inner = s.strip("()").lstrip("-").replace(",", "").strip()
        raw_digits = inner.split(".")[0]
        try:
            v = float(inner)
        except ValueError:
            continue

        # Percentage: emit both raw and decimal
        if unit in ("percent", "percentage", "%"):
            out.append(v)        # e.g. 9.2
            out.append(v / 100)  # e.g. 0.092
            continue

        # Scale
        scale = 1.0
        has_inline_scale = False
        if unit in WORD_SCALE:
            scale = WORD_SCALE[unit]
            has_inline_scale = True
        elif unit in ABBR_SCALE:
            scale = ABBR_SCALE[unit]
            has_inline_scale = True
        if not has_inline_scale and table_scale:
            scale = table_scale

        base = v * scale

        # Sign
        if is_paren:
            base = -abs(base)
        # Keyword context: look back ~50 chars for "loss"/"deficit"/etc.
        pre = text[max(0, m.start() - 50): m.start()].lower()
        if any(ctx in pre for ctx in NEG_CONTEXTS) and base > 0:
            base = -base

        # Year skip: pure 4-digit year token, no $, no unit
        if (
            not has_inline_scale
            and not has_dollar
            and raw_digits.isdigit()
            and YEAR_RE.match(raw_digits)
        ):
            continue
        # "chunk NNNN" context skip (chunk-id false positives)
        pre_window = text[max(0, m.start() - 10): m.start()].lower()
        if "chunk" in pre_window:
            continue

        out.append(base)

    return out


# ---------------------------------------------------------------------------
# numeric_match (plan §8)
# ---------------------------------------------------------------------------


def numeric_match(answer_text: str, gold_value: float, tol: float = 0.05,
                  cited_metas: Optional[list] = None) -> bool:
    """Return True if any extracted number matches gold_value within tolerance."""
    for n in extract_numbers(answer_text, cited_metas):
        if abs(gold_value) < 1:
            if abs(n - gold_value) < 0.01:
                return True
        else:
            if abs(n - gold_value) / abs(gold_value) <= tol:
                return True
    return False


# ---------------------------------------------------------------------------
# retrieval_score (plan §6, §8)
# ---------------------------------------------------------------------------


def retrieval_score(retrieved: list, gold_chunks: list, gold_spans: Optional[list] = None
                    ) -> dict:
    """Compute retrieval precision/recall vs gold_chunks anchors and gold_spans.

    Retrieved chunks: list of dicts each with 'meta' (dict containing 'anchor',
    'char_span_start', 'char_span_end').

    Primary metric (plan §8): anchor set membership.
    Fallback: span overlap for chunks with anchor=None (fixed-size) when
    gold_spans is provided.
    """
    gold_anchors = set(a for a in (gold_chunks or []) if a and a != "unknown")
    gold_span_ranges = [tuple(s) for s in (gold_spans or []) if s and len(s) == 2]

    retrieved_anchors = set()
    n_span_hits = 0
    n_retrieved = len(retrieved)
    n_anchor_hits = 0

    for c in retrieved:
        m = c.get("meta", {}) or {}
        a = m.get("anchor")
        if a and a not in ("none", "unknown", None, ""):
            retrieved_anchors.add(a)
        if a and a in gold_anchors:
            n_anchor_hits += 1
            continue
        # Span overlap fallback
        if gold_span_ranges:
            cs = m.get("char_span_start")
            ce = m.get("char_span_end")
            if cs is not None and ce is not None:
                for gs, ge in gold_span_ranges:
                    if cs < ge and gs < ce:
                        n_span_hits += 1
                        break

    # Recall: anchor coverage (primary)
    if gold_anchors:
        recall_anchor = len(retrieved_anchors & gold_anchors) / len(gold_anchors)
        recall = recall_anchor
    elif gold_span_ranges:
        # span coverage
        covered = set()
        for c in retrieved:
            m = c.get("meta", {}) or {}
            cs = m.get("char_span_start")
            ce = m.get("char_span_end")
            if cs is None:
                continue
            for i, (gs, ge) in enumerate(gold_span_ranges):
                if cs < ge and gs < ce:
                    covered.add(i)
        recall = len(covered) / len(gold_span_ranges)
    else:
        recall = 0.0

    # Precision: fraction of retrieved that are hits (anchor or span)
    n_matched = n_anchor_hits + n_span_hits
    precision = n_matched / n_retrieved if n_retrieved else 0.0

    retrieval_hit = (n_anchor_hits > 0) or (n_span_hits > 0) or (
        recall > 0
    )

    return {
        "precision": precision,
        "recall": recall,
        "n_matched": n_matched,
        "n_retrieved": n_retrieved,
        "n_anchor_hits": n_anchor_hits,
        "n_span_hits": n_span_hits,
        "retrieval_hit": retrieval_hit,
    }


# ---------------------------------------------------------------------------
# routing_score
# ---------------------------------------------------------------------------

ABSTAIN_PHRASES = [
    "not found in corpus",
    "cannot be found",
    "cannot find",
    "does not contain",
    "not available",
    "no information",
    "context does not",
    "not in the provided context",
    "i cannot find",
    "is not provided",
    "not mentioned",
]

WEB_TAGS = ["source: web", "[web]", "(web)"]


def routing_score(answer_text: str, expected_route: str) -> str:
    """Classify the model's answer into corpus / abstain / web and compare.

    Heuristics: web tag checked FIRST (provenance overrides abstention phrasing);
    then abstention phrases; otherwise corpus. Compare to expected_route.
    """
    if not answer_text:
        return "wrong"
    t = answer_text.lower()
    if any(w in t for w in WEB_TAGS):
        predicted = "web"
    elif any(p in t for p in ABSTAIN_PHRASES):
        predicted = "abstain"
    else:
        predicted = "corpus"
    return "correct" if predicted == expected_route else f"wrong({predicted}->{expected_route})"
