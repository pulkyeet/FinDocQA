"""Combine auto-gen numerical questions and hand-drafted questions into
data/eval/questions.jsonl, and write questions_review.md with justifications
for the hand-drafted subset (the human-in-the-loop review step per plan §7).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.hand_drafted import HAND_QUESTIONS
from eval.xbrl_autogen import generate_numerical

EVAL_DIR = "data/eval"
QUESTIONS_PATH = f"{EVAL_DIR}/questions.jsonl"
REVIEW_PATH = f"{EVAL_DIR}/questions_review.md"


def _strip_internal(q):
    return {k: v for k, v in q.items() if not k.startswith("_")}


def build():
    os.makedirs(EVAL_DIR, exist_ok=True)
    numerical = generate_numerical()
    all_q = numerical + [_strip_internal(q) for q in HAND_QUESTIONS]

    with open(QUESTIONS_PATH, "w") as f:
        for q in all_q:
            f.write(json.dumps(q) + "\n")

    from collections import Counter

    types = Counter(q["type"] for q in all_q)
    routes = Counter(q["expected_route"] for q in all_q)
    print(f"Wrote {len(all_q)} questions to {QUESTIONS_PATH}")
    print(f"  Types:  {dict(types)}")
    print(f"  Routes: {dict(routes)}")
    return all_q


def write_review(all_q):
    numerical = [q for q in all_q if q["type"] == "numerical"]
    hand = HAND_QUESTIONS
    lines = []
    lines.append("# Eval Question Review")
    lines.append("")
    lines.append(
        "Per plan §7, **never LLM-label `gold_chunks`**. The 20 numerical "
        "questions are auto-generated from XBRL (deterministic). The 36 "
        "hand-drafted questions below have proposed `gold_chunks` (anchors) "
        "and a one-line justification. **You verify/correct the gold_chunks** "
        "and add `gold_spans` for cross-filing / multihop if you want "
        "span-overlap scoring (the plan §6 fallback works without spans, "
        "using anchor matching only)."
    )
    lines.append("")
    lines.append("Route distribution target (plan §7): corpus 46 / abstain 6 / web 4.")
    lines.append("")

    lines.append("## Numerical (20) — auto-gen from XBRL")
    lines.append("")
    lines.append("| ID | Question | Anchor | Gold answer |")
    lines.append("|---|---|---|---|")
    for q in numerical:
        lines.append(
            f"| `{q['id']}` | {q['question']} | `{q['gold_chunks'][0]}` | {q['answer']['text']} |"
        )
    lines.append("")

    for section_title, filter_types in [
        ("## Factual (10) — semi-auto", ["factual"]),
        ("## Multihop (8) — hand", ["multihop"]),
        ("## Cross-filing (8) — hand", ["cross_filing"]),
        ("## Unanswerable / Abstain (6) — hand", ["unanswerable"]),
        ("## Out-of-corpus / Web (4) — hand", ["out_of_corpus"]),
    ]:
        lines.append(section_title)
        lines.append("")
        for q in hand:
            if q["type"] not in filter_types:
                continue
            gc = ", ".join(f"`{a}`" for a in q["gold_chunks"]) or "(none)"
            lines.append(f"### `{q['id']}`")
            lines.append(f"**Question:** {q['question']}")
            lines.append(f"**Type:** {q['type']}  |  **Route:** {q['expected_route']}")
            lines.append(f"**Proposed gold_chunks:** {gc}")
            lines.append(f"**Justification:** {q.get('_justification', '')}")
            lines.append("")

    with open(REVIEW_PATH, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote review to {REVIEW_PATH}")


if __name__ == "__main__":
    all_q = build()
    write_review(all_q)
