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
)


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
                      year_pair: tuple[str, str]) -> list[dict]:
    """Stage 5 for one section pair: classify all matched pairs + structural changes.

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
        cls = classify_pair(sim)
        old_text = old_paras[oi] if oi < len(old_paras) else ""
        new_text = new_paras[nj] if nj < len(new_paras) else ""

        record = make_diff_record(
            ticker, anchor, year_pair, cls, sim, oi, nj, old_text, new_text
        )
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

    return records


def write_diff_records(records: list[dict], ticker: str, year_old: str, year_new: str):
    """Write diff records to data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl."""
    output_dir = f"{DELTA_DIFFS_DIR}/{ticker}"
    os.makedirs(output_dir, exist_ok=True)
    path = f"{output_dir}/{year_old}_{year_new}.jsonl"
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def diff_all_sections(old_chunks, new_chunks, ticker, year_pair, model_key="bge-small") -> list[dict]:
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
        records = diff_section_pair(alignment, ticker, anchor, year_pair)
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
