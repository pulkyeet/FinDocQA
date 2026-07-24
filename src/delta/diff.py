"""Stage 5: Deterministic diff classification, word deltas, and churn scoring."""

import difflib
import json
import os
import re

from config import (
    DELTA_DIFFS_DIR,
    DIFF_THRESHOLD_UNCHANGED,
    DIFF_THRESHOLD_MINOR,
    DIFF_THRESHOLD_MAJOR,
    NUMERIC_GUARD_PCT,
    NUMERIC_GUARD_MIN_VALUE,
    NUMERIC_GUARD_MAJOR_PCT,
    FINANCIAL_ANCHORS,
)
from scoring import extract_numbers


def classify_pair(similarity: float) -> str:
    """Classify similarity score into a change category.

    Returns: 'unchanged' | 'modified_minor' | 'modified_major'.
    """
    if similarity >= DIFF_THRESHOLD_UNCHANGED:
        return "unchanged"
    if similarity >= DIFF_THRESHOLD_MINOR:
        return "modified_minor"
    if similarity >= DIFF_THRESHOLD_MAJOR:
        return "modified_major"
    return "modified_minor"


# ---------------------------------------------------------------------------
# Numeric guard (fixes numeric-blindness)
#
# Embedding cosine scores a paragraph whose only change is a number ~0.99, so
# classify_pair calls it 'unchanged' and interpret.py never sees it. These
# helpers run ONLY on records cosine calls 'unchanged' and upgrade them when a
# material numeric move is detected — deterministic, model-free, auditable.
# ---------------------------------------------------------------------------


def _numbers_equal(old_nums: list[float], new_nums: list[float]) -> bool:
    """True if the two number multisets are identical (robust to reordering)."""
    return sorted(round(v, 2) for v in old_nums) == sorted(round(v, 2) for v in new_nums)


def numeric_change_signal(old_text: str, new_text: str,
                          threshold: float = NUMERIC_GUARD_PCT,
                          min_value: float = NUMERIC_GUARD_MIN_VALUE) -> dict | None:
    """Largest material relative numeric move between two near-identical texts.

    Returns {'source':'text','old':x,'new':y,'pct':p} where p is a fraction
    (0.20 == 20%), or None. Reuses scoring.extract_numbers (currency, scales,
    paren-negatives, percentages, year-skipping). Intended for records cosine
    already calls 'unchanged', so the two texts are near-identical in wording
    and their numbers line up positionally.
    """
    old_nums = [v for v in extract_numbers(old_text) if abs(v) >= min_value]
    new_nums = [v for v in extract_numbers(new_text) if abs(v) >= min_value]

    if not old_nums or not new_nums:
        return None
    if _numbers_equal(old_nums, new_nums):
        return None

    # Positional pairing when counts match (near-identical text); otherwise
    # greedy nearest-value pairing to estimate the move magnitude.
    if len(old_nums) == len(new_nums):
        pairs = list(zip(old_nums, new_nums))
    else:
        pairs = [(ov, min(new_nums, key=lambda x: abs(x - ov))) for ov in old_nums]

    best = None
    for ov, nv in pairs:
        if ov == 0:
            continue
        pct = abs(nv - ov) / abs(ov)
        if best is None or pct > best[2]:
            best = (ov, nv, pct)

    if best is None or best[2] < threshold:
        return None
    return {"source": "text", "old": best[0], "new": best[1], "pct": round(best[2], 4)}


def xbrl_change_signal(anchor: str, year_pair: tuple[str, str], xbrl_deltas: dict,
                       threshold: float = NUMERIC_GUARD_PCT) -> dict | None:
    """Largest material XBRL tag move for a section's year-pair, or None.

    pct is normalized to a fraction (compute_yoy_deltas stores pct_change as a
    percent). Returns {'source':'xbrl','tag':t,'old':x,'new':y,'pct':p}.
    """
    from delta.xbrl_delta import deltas_for_section

    sec = deltas_for_section(xbrl_deltas, anchor)
    yp_key = f"{year_pair[0]}-{year_pair[1]}"
    best = None
    for tag, yp_deltas in sec.items():
        d = yp_deltas.get(yp_key)
        if not d or d.get("pct_change") is None:
            continue
        pct = abs(d["pct_change"]) / 100.0
        if pct >= threshold and (best is None or pct > best["pct"]):
            best = {"source": "xbrl", "tag": tag,
                    "old": d.get("old"), "new": d.get("new"), "pct": round(pct, 4)}
    return best


def _guard_classification(pct: float) -> str:
    """Map a guard's relative move to a change classification."""
    return "modified_major" if pct >= NUMERIC_GUARD_MAJOR_PCT else "modified_minor"


WORD_RE = re.compile(r"\w+|[^\w\s]+", re.UNICODE)


def word_delta(old_text: str, new_text: str) -> dict:
    """Compute word-level additions and removals between two texts.

    Returns {'added': [words], 'removed': [words]}.
    """
    old_words = WORD_RE.findall(old_text)
    new_words = WORD_RE.findall(new_text)

    differ = difflib.ndiff(old_words, new_words)

    added = []
    removed = []
    for token in differ:
        if token.startswith("+ "):
            added.append(token[2:])
        elif token.startswith("- "):
            removed.append(token[2:])

    return {"added": added, "removed": removed}


def make_diff_record(ticker, anchor, year_pair, classification,
                     similarity, old_para_idx, new_para_idx,
                     old_text, new_text) -> dict:
    """Construct a diff record per the schema."""
    year_old, year_new = year_pair
    wd = word_delta(old_text, new_text)
    return {
        "ticker": ticker,
        "anchor": anchor,
        "year_pair": [year_old, year_new],
        "change_id": f"{ticker}-{anchor}-{year_old}-{year_new}",
        "classification": classification,
        "similarity": similarity,
        "old_para_idx": old_para_idx,
        "new_para_idx": new_para_idx,
        "old_text": old_text,
        "new_text": new_text,
        "word_delta": wd,
    }


def compute_churn_score(paras: list[dict], classifications: list[str]) -> float:
    """Fraction of paragraph text classified as changed, weighted by length.

    Returns 0.0 (no change) to 1.0 (everything changed).
    paras: list of dicts with 'old_text','new_text','classification'.
    classifications: list of classification strings, one per match.
    """
    total_chars = 0
    changed_chars = 0
    for para, cls in zip(paras, classifications):
        text_len = max(len(para.get("old_text", "")), len(para.get("new_text", "")))
        total_chars += text_len
        if cls != "unchanged":
            changed_chars += text_len
    if total_chars == 0:
        return 0.0
    return changed_chars / total_chars


def diff_section_pair(alignment: dict, ticker: str, anchor: str,
                      year_pair: tuple[str, str],
                      xbrl_deltas: dict | None = None) -> list[dict]:
    """Stage 5 for one section pair: classify all matched pairs + structural changes.

    Applies the numeric guard (text + XBRL corroboration) so paragraphs whose
    only change is a number are not silently classified 'unchanged'.

    Returns list of diff records.
    """
    records = []
    old_paras = alignment.get("old_paras", [])
    new_paras = alignment.get("new_paras", [])

    seq = 0

    for m in alignment.get("matches", []):
        oi = m["old_idx"]
        nj = m["new_idx"]
        sim = m["similarity"]
        old_text = old_paras[oi] if oi < len(old_paras) else ""
        new_text = new_paras[nj] if nj < len(new_paras) else ""

        cls = classify_pair(sim)
        guard = None
        if cls == "unchanged":
            guard = numeric_change_signal(old_text, new_text)
            if guard:
                cls = _guard_classification(guard["pct"])

        record = make_diff_record(
            ticker, anchor, year_pair, cls, sim, oi, nj, old_text, new_text
        )
        if guard:
            record["numeric_guard"] = guard
        if cls != "unchanged":
            record["change_id"] = f"{ticker}-{anchor}-{year_pair[0]}-{year_pair[1]}-{seq:03d}"
            seq += 1
        records.append(record)

    for nj in alignment.get("added", []):
        new_text = new_paras[nj] if nj < len(new_paras) else ""
        record = make_diff_record(
            ticker, anchor, year_pair, "added", 0.0, -1, nj, "", new_text
        )
        record["change_id"] = f"{ticker}-{anchor}-{year_pair[0]}-{year_pair[1]}-{seq:03d}"
        seq += 1
        records.append(record)

    for oi in alignment.get("removed", []):
        old_text = old_paras[oi] if oi < len(old_paras) else ""
        record = make_diff_record(
            ticker, anchor, year_pair, "removed", 0.0, oi, -1, old_text, ""
        )
        record["change_id"] = f"{ticker}-{anchor}-{year_pair[0]}-{year_pair[1]}-{seq:03d}"
        seq += 1
        records.append(record)

    # XBRL corroboration: a financially-loaded section whose audited headline
    # metric moved but where nothing surfaced (e.g. the number survived only in
    # a mangled table cell). Flag the most number-dense unchanged paragraph so
    # the metric reaches the LLM.
    if xbrl_deltas and anchor in FINANCIAL_ANCHORS:
        if not any(r["classification"] != "unchanged" for r in records):
            sig = xbrl_change_signal(anchor, year_pair, xbrl_deltas)
            if sig:
                candidates = [r for r in records if r["classification"] == "unchanged"]
                dense = max(
                    candidates,
                    key=lambda r: len(extract_numbers(r.get("new_text", ""))),
                    default=None,
                )
                if dense is not None and extract_numbers(dense.get("new_text", "")):
                    dense["classification"] = _guard_classification(sig["pct"])
                    dense["numeric_guard"] = sig
                    dense["change_id"] = f"{ticker}-{anchor}-{year_pair[0]}-{year_pair[1]}-{seq:03d}"
                    seq += 1

    return records


def write_diff_records(records: list[dict], ticker: str, year_old: str, year_new: str):
    """Write diff records to data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl."""
    output_dir = f"{DELTA_DIFFS_DIR}/{ticker}"
    os.makedirs(output_dir, exist_ok=True)
    path = f"{output_dir}/{year_old}_{year_new}.jsonl"
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def diff_all_sections(old_chunks, new_chunks, ticker, year_pair, model_key="bge-small",
                      xbrl_deltas: dict | None = None) -> list[dict]:
    """Run align + diff for every section pair, collect all records."""
    from delta.align import align_sections, align_section_pair

    section_pairs = align_sections(old_chunks, new_chunks)
    all_records = []
    n_total = len(section_pairs)
    for i, (anchor, old_c, new_c) in enumerate(section_pairs):
        if len(old_c) == 0 and len(new_c) == 0:
            continue
        print(f"    [{i+1}/{n_total}] {anchor}", end=" ", flush=True)
        alignment = align_section_pair(old_c, new_c, model_key)
        records = diff_section_pair(alignment, ticker, anchor, year_pair, xbrl_deltas)
        n_changed = sum(1 for r in records if r["classification"] != "unchanged")
        print(f"-> {n_changed} changed")
        all_records.extend(records)
    return all_records


def classification_counts(records: list[dict]) -> dict[str, int]:
    """Count records by classification."""
    counts = {}
    for r in records:
        cls = r.get("classification", "unknown")
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def churn_summary(ticker: str, records_by_year: dict[tuple, list[dict]], anchor_names: dict[str, str] | None = None) -> str:
    """Build a formatted churn summary table for the CLI.

    anchor_names maps anchor keys to display names (e.g. 'item1a_risk' -> 'Risk Factors (1A)').
    """
    if anchor_names is None:
        anchor_names = {}

    lines = [f"\n{ticker}: Change Report"]
    lines.append("=" * 50)
    lines.append("Churn scores (fraction of section text changed YoY):")

    all_anchors = set()
    for records in records_by_year.values():
        for r in records:
            a = r.get("anchor")
            if a:
                all_anchors.add(a)

    for anchor in sorted(all_anchors):
        display = anchor_names.get(anchor, anchor)
        parts = [f"  {display}:"]
        for yp, records in sorted(records_by_year.items()):
            sec_recs = [r for r in records if r.get("anchor") == anchor]
            changed = [r for r in sec_recs if r.get("classification") != "unchanged"]
            matched = [r for r in sec_recs if r.get("classification") not in ("added", "removed")]
            classifications = [r["classification"] for r in matched]
            score = compute_churn_score(
                matched if matched else [{"old_text": "", "new_text": ""}],
                classifications if classifications else ["unchanged"]
            )
            parts.append(f"  {yp[1]}: {score:.2f}")
        lines.append("".join(parts))

    total = sum(len(records) for records in records_by_year.values())
    all_recs = [r for records in records_by_year.values() for r in records]
    counts = classification_counts([r for r in all_recs if r.get("classification") != "unchanged"])
    lines.append(f"\nChanges: {len(records_by_year)} year-pairs, {total} total diff records")
    cls_parts = [f"  {k}: {v}" for k, v in sorted(counts.items())]
    lines.append(" | ".join(cls_parts))

    return "\n".join(lines)
