"""Threshold tuning for diff classification.

Loads a hand-labeled sample and grid-searches threshold values
to maximize separation between unchanged/minor/major classes.
"""

import json
import os


def load_labeled_pairs(path: str) -> list[dict]:
    """Load the labeled sample from a JSONL file."""
    pairs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))
    return pairs


def classify_with_thresholds(similarity: float, unchanged: float, minor: float) -> str:
    """Classify using given thresholds (0-1 scale)."""
    if similarity >= unchanged:
        return "unchanged"
    if similarity >= minor:
        return "modified_minor"
    if similarity >= 0.0:
        return "modified_major"
    return "modified_minor"


def evaluate_thresholds(labels: list[dict], unchanged_thresh: float, minor_thresh: float) -> dict:
    """Evaluate precision/recall/F1 for given threshold values."""
    from collections import defaultdict

    classes = ["unchanged", "modified_minor", "modified_major"]
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)

    for pair in labels:
        sim = pair.get("similarity", 0)
        predicted = classify_with_thresholds(sim, unchanged_thresh, minor_thresh)
        actual = pair.get("your_label", pair.get("classification", ""))

        for cls in classes:
            if predicted == cls and actual == cls:
                tp[cls] += 1
            elif predicted == cls and actual != cls:
                fp[cls] += 1
            elif predicted != cls and actual == cls:
                fn[cls] += 1

    metrics = {}
    total_tp = total_fp = total_fn = 0
    for cls in classes:
        total_tp += tp[cls]
        total_fp += fp[cls]
        total_fn += fn[cls]
        denom_p = tp[cls] + fp[cls]
        denom_r = tp[cls] + fn[cls]
        precision = tp[cls] / denom_p if denom_p > 0 else 0.0
        recall = tp[cls] / denom_r if denom_r > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        metrics[f"{cls}_precision"] = precision
        metrics[f"{cls}_recall"] = recall
        metrics[f"{cls}_f1"] = f1

    macro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    macro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    macro_f1 = 2 * macro_precision * macro_recall / (macro_precision + macro_recall) if (macro_precision + macro_recall) > 0 else 0.0
    metrics["macro_precision"] = macro_precision
    metrics["macro_recall"] = macro_recall
    metrics["macro_f1"] = macro_f1

    return metrics


def tune(labels: list[dict]) -> dict:
    """Grid search over threshold values. Hold out 10 pairs for final eval.

    Returns best thresholds + held-out metrics.
    """
    import random
    random.seed(42)

    if len(labels) < 20:
        print(f"[warn] only {len(labels)} labeled pairs, need at least 20")
        return {"unchanged": 0.95, "minor": 0.80, "held_out_precision": 0.0, "held_out_recall": 0.0}

    shuffled = list(labels)
    random.shuffle(shuffled)
    split = max(10, len(labels) // 5)
    train = shuffled[split:]
    test = shuffled[:split]

    best_f1 = 0
    best_result = {"unchanged": 0.94, "minor": 0.80}

    for unchanged in [round(x * 0.01, 2) for x in range(85, 100, 2)]:
        for minor in [round(x * 0.01, 2) for x in range(65, 95, 2)]:
            if minor >= unchanged:
                continue
            metrics = evaluate_thresholds(train, unchanged, minor)
            f1 = metrics.get("macro_f1", 0)
            if f1 > best_f1:
                best_f1 = f1
                best_result = {**metrics, "unchanged": unchanged, "minor": minor}

    test_metrics = evaluate_thresholds(test, best_result["unchanged"], best_result["minor"])
    best_result["held_out_precision"] = test_metrics.get("macro_precision", 0)
    best_result["held_out_recall"] = test_metrics.get("macro_recall", 0)
    best_result["held_out_f1"] = test_metrics.get("macro_f1", 0)

    return best_result


def generate_sample(
    ticker="AAPL",
    year_pairs=None,
    sections=None,
    output_jsonl="data/eval/diff_labels.jsonl",
    output_md="data/eval/diff_labels.md",
    target_total=50,
):
    """Generate candidate diff pairs for hand-labeling across multiple sections and year pairs.

    Samples ~target_total pairs stratified across section x year-pair combinations
    covering unchanged/minor/major/added/removed classes. Writes both JSONL (machine)
    and Markdown (human-readable) output files.
    """
    import random
    random.seed(42)

    from config import DELTA_DIFFS_DIR

    if year_pairs is None:
        year_pairs = [("FY2021", "FY2022"), ("FY2024", "FY2025")]
    if sections is None:
        sections = ["item1a_risk", "item7_mdna", "item8_financials", "item1_business", "income_statement"]

    combos = [(ticker, sec, y0, y1) for sec in sections for (y0, y1) in year_pairs]
    pairs_per_combo = max(1, target_total // len(combos))

    sample = []

    for tk, sec, y0, y1 in combos:
        diff_path = f"{DELTA_DIFFS_DIR}/{tk}/{y0}_{y1}.jsonl"
        if not os.path.exists(diff_path):
            print(f"[warn] diff file not found: {diff_path}")
            continue

        records = []
        with open(diff_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if r.get("anchor") == sec:
                        records.append(r)

        if not records:
            print(f"[warn] no records for {tk}/{sec} in {y0}-{y1}")
            continue

        unchanged = [r for r in records if r["classification"] == "unchanged"]
        changed = [r for r in records if r["classification"] != "unchanged"]
        major = [r for r in changed if r.get("similarity", 0) < 0.80]
        minor = [r for r in changed if 0.80 <= r.get("similarity", 0) < 0.95]
        added = [r for r in changed if r["classification"] == "added"]
        removed = [r for r in changed if r["classification"] == "removed"]

        buckets = {
            "unchanged": unchanged,
            "modified_minor": minor,
            "modified_major": major,
            "added": added,
            "removed": removed,
        }

        n_buckets = sum(1 for v in buckets.values() if v)
        per_bucket = max(1, pairs_per_combo // n_buckets) if n_buckets else 0

        combo_sample = []
        for cls, bucket in buckets.items():
            if not bucket:
                continue
            n = min(per_bucket, len(bucket))
            combo_sample.extend(random.sample(bucket, n))

        leftover = pairs_per_combo - len(combo_sample)
        if leftover > 0 and changed:
            extra = random.sample(changed, min(leftover, len(changed)))
            combo_sample.extend(extra)

        sample.extend(combo_sample)
        print(f"  [{tk}/{sec} {y0}->{y1}] {len(combo_sample)} pairs ({len(records)} available)")

    random.shuffle(sample)

    if len(sample) > target_total:
        sample = sample[:target_total]

    os.makedirs(os.path.dirname(output_jsonl), exist_ok=True)

    with open(output_jsonl, "w") as f:
        for r in sample:
            yp = r.get("year_pair", ["?", "?"])
            old = (r.get("old_text") or "")[:300]
            new = (r.get("new_text") or "")[:300]
            entry = {
                "change_id": r["change_id"],
                "ticker": r.get("ticker", ticker),
                "anchor": r.get("anchor", ""),
                "year_old": yp[0],
                "year_new": yp[1],
                "similarity": r.get("similarity", 0),
                "old_text": old,
                "new_text": new,
                "classification": r["classification"],
                "your_label": "",
                "notes": "",
            }
            f.write(json.dumps(entry) + "\n")

    with open(output_md, "w") as f:
        f.write("# Diff Labeling Sample\n\n")
        f.write(f"Generated from **{ticker}** across "
                f"{len(sections)} sections and {len(year_pairs)} year pairs.\n\n")
        f.write(f"Total pairs: **{len(sample)}**\n\n")
        f.write("---\n\n")
        for i, r in enumerate(sample, 1):
            yp = r.get("year_pair", ["?", "?"])
            sim = r.get("similarity", 0)
            cls = r["classification"]
            old_text = r.get("old_text") or ""
            new_text = r.get("new_text") or ""
            f.write(f"## Pair #{i}\n")
            f.write(f"- **Ticker:** {r.get('ticker', ticker)}\n")
            f.write(f"- **Section:** {r.get('anchor', '')}\n")
            f.write(f"- **Year pair:** {yp[0]} → {yp[1]}\n")
            f.write(f"- **Similarity:** {sim:.4f}\n")
            f.write(f"- **Classifier says:** {cls}\n")
            f.write(f"- **Your label:**\n")
            f.write(f"- **Notes:**\n\n")
            f.write("**OLD text:**\n")
            f.write("```\n")
            f.write(old_text)
            if not old_text.endswith("\n"):
                f.write("\n")
            f.write("```\n\n")
            f.write("**NEW text:**\n")
            f.write("```\n")
            f.write(new_text)
            if not new_text.endswith("\n"):
                f.write("\n")
            f.write("```\n\n")
            f.write("---\n\n")

    print(f"[generated] {len(sample)} pairs -> {output_jsonl}")
    print(f"[generated] {len(sample)} pairs -> {output_md}")
    print("Hand-label each pair in the JSONL: your_label = unchanged | modified_minor | modified_major | added | removed")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        generate_sample()
    elif len(sys.argv) > 1 and sys.argv[1] == "tune":
        labels_path = "data/eval/diff_labels.jsonl"
        if len(sys.argv) > 2:
            labels_path = sys.argv[2]
        if not os.path.exists(labels_path):
            print(f"[error] labeled sample not found: {labels_path}")
            print("Run 'python -m delta.tune_thresholds generate' first")
            sys.exit(1)
        labels = load_labeled_pairs(labels_path)
        unlabeled = [p for p in labels if not p.get("your_label") and not p.get("notes")]
        if unlabeled:
            print(f"[warn] {len(unlabeled)} pairs still need hand-labeling. Set 'your_label' field.")
        results = tune(labels)
        print(f"\nTuned thresholds:")
        print(f"  DIFF_THRESHOLD_UNCHANGED = {results.get('unchanged', 0.95)}")
        print(f"  DIFF_THRESHOLD_MINOR = {results.get('minor', 0.80)}")
        print(f"  DIFF_THRESHOLD_MAJOR = 0.60")
        print(f"Held-out macro F1: {results.get('held_out_f1', 0):.3f}")
        print(f"  precision: {results.get('held_out_precision', 0):.3f}")
        print(f"  recall: {results.get('held_out_recall', 0):.3f}")
    else:
        print("Usage: python -m delta.tune_thresholds [generate|tune]")
