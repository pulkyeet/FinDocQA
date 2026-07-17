"""Run the full 8-config x 56-question eval and write results.csv.

8 configs = 2 chunking strategies x 2 embedding models x rerank on/off.
For each config and question:
  1. Retrieve top-20 from the Chroma collection.
  2. (If rerank on) Rerank to top-5 with the cross-encoder; else take top-5.
  3. Call the generation model (opencode chat agent) with the chunks.
  4. Score: numeric_match, retrieval precision/recall, routing 3-way, joint.

Writes a long-form results.csv keyed by config + question, and prints a
summary table (numeric match rate, retrieval recall, abstention accuracy by
config, and a diff vs the previous results.csv if present).
"""

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import chromadb
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    CHROMA_DIR,
    CHUNK_STRATEGIES,
    EMBEDDING_MODELS,
    EVAL_DIR,
    FAITHFULNESS_JUDGE,
    OPENCODE_AGENT,
    OPENCODE_ATTACH,
    TOP_K_FINAL,
    TOP_K_RETRIEVE,
    sanitize_prompt,
)
from embed import collection_name, query_prefix
from rerank import Reranker
from scoring import numeric_match, retrieval_score, routing_score
from web_search import is_abstention, build_web_prompt

QUESTIONS_PATH = f"{EVAL_DIR}/questions.jsonl"
RESULTS_PATH = f"{EVAL_DIR}/results.csv"
PREVIOUS_PATH = f"{EVAL_DIR}/results_prev.csv"


def config_hash(strategy, model_key, rerank):
    s = f"{strategy}|{model_key}|{rerank}"
    return hashlib.sha1(s.encode()).hexdigest()[:10]


def load_questions():
    with open(QUESTIONS_PATH) as f:
        return [json.loads(l) for l in f]


def build_prompt(question, hits):
    blocks = []
    for h in hits:
        m = h["meta"]
        blocks.append(
            f"[chunk_id={h['chunk_id']} ticker={m.get('ticker','?')} anchor={m.get('anchor','?')}]\n{h['text']}"
        )
    ctx = "\n\n-----\n\n".join(blocks)
    return (
        "Answer the question using ONLY the context below. Cite the exact "
        "chunk_id(s) you used. If the answer is not in the context, say "
        "\"Not found in corpus\" — do not guess.\n\n"
        f"Context:\n{ctx}\n\nQuestion: {question}\n\n"
        "Answer (end with \"Citations: [chunk_id, ...]\"):"
    )


def call_llm(prompt):
    prompt = sanitize_prompt(prompt)
    try:
        base_cmd = ["opencode", "run", "--agent", OPENCODE_AGENT]
        if OPENCODE_ATTACH:
            base_cmd += ["--attach", OPENCODE_ATTACH]
        r = subprocess.run(
            base_cmd + [prompt],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    if r.returncode != 0:
        return f"[ERROR: {r.stderr[:200]}]"
    out = re.sub(r"^\x1b\[.*?m", "", r.stdout, flags=re.MULTILINE)
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("> ")]
    return "\n".join(lines).strip()


def score_question(question, hits, answer_text, provenance="rag"):
    """Return a dict of metric values for one question."""
    rec = retrieval_score(hits, question.get("gold_chunks") or [],
                          question.get("gold_spans") or [])
    route = routing_score(answer_text, question.get("expected_route", "corpus"))

    # cited chunk metas (for table_scale threading into extract_numbers)
    cited_metas = [h["meta"] for h in hits[:3]]  # use top-3 as cited context

    num_match = None
    if question.get("type") == "numerical" and question.get("answer", {}).get("value") is not None:
        num_match = numeric_match(answer_text, float(question["answer"]["value"]),
                                   cited_metas=cited_metas)

    # Joint correctness (Plan §11 §8)
    expected = question.get("expected_route", "corpus")
    joint = None
    if expected in ("web", "abstain"):
        # Web/abstain: correctness = routing (retrieval/numeric are N/A)
        joint = (route == "correct")
    elif question.get("type") == "numerical":
        joint = bool(num_match) and bool(rec["retrieval_hit"])
    else:
        joint = rec["retrieval_hit"]

    return {
        "precision": rec["precision"],
        "recall": rec["recall"],
        "retrieval_hit": rec["retrieval_hit"],
        "route": route,
        "numeric_match": num_match,
        "joint": joint,
    }


def run_one_config(strategy, model_key, rerank_on, questions, chroma_client):
    """Run all questions for one config. Returns list of result rows."""
    model_name = EMBEDDING_MODELS[model_key]
    print(f"\n=== config: strategy={strategy} model={model_key} rerank={rerank_on} ===")
    embed_model = SentenceTransformer(model_name)
    col = chroma_client.get_collection(collection_name(strategy, model_key))
    reranker = Reranker() if rerank_on else None

    rows = []
    t_cfg = time.time()
    for i, q in enumerate(questions):
        qprefix = query_prefix(model_key)
        qtext = qprefix + q["question"]
        q_emb = embed_model.encode([qtext], normalize_embeddings=True).tolist()
        res = col.query(query_embeddings=q_emb, n_results=TOP_K_RETRIEVE)
        hits = []
        for j in range(len(res["ids"][0])):
            hits.append({
                "chunk_id": res["ids"][0][j],
                "text": res["documents"][0][j],
                "meta": res["metadatas"][0][j],
                "distance": res["distances"][0][j],
            })

        if reranker:
            hits = reranker.rerank(q["question"], hits, top_k=TOP_K_FINAL)
        else:
            hits = hits[:TOP_K_FINAL]

        prompt = build_prompt(q["question"], hits)
        ans = call_llm(prompt)
        provenance = "rag"

        # Web fallback (Plan §11): if question expects web and RAG abstains
        if q["expected_route"] == "web" and is_abstention(ans):
            web_prompt = build_web_prompt(q["question"])
            ans = call_llm(web_prompt)
            provenance = "web"
            if "source: web" not in ans.lower():
                ans = ans.rstrip() + " [source: web]"

        m = score_question(q, hits, ans, provenance=provenance)

        faithful = None
        faithful_disagree = None
        if FAITHFULNESS_JUDGE and m["route"].startswith("correct"):
            # Run judge on correctly-routed questions (Plan §8)
            faithful, faithful_disagree = judge_faithfulness(
                q["question"], ans, hits
            )

        row = {
            "config": f"{strategy}__{model_key}__rerank={'on' if rerank_on else 'off'}",
            "config_hash": config_hash(strategy, model_key, "on" if rerank_on else "off"),
            "question_id": q["id"],
            "question_type": q["type"],
            "expected_route": q["expected_route"],
            "route_result": m["route"],
            "retrieval_precision": round(m["precision"], 3),
            "retrieval_recall": round(m["recall"], 3),
            "retrieval_hit": m["retrieval_hit"],
            "numeric_match": m["numeric_match"],
            "joint_correct": m["joint"],
            "provenance": provenance,
            "faithful": faithful,
            "faithfulness_disagreement": faithful_disagree,
            "answer_preview": ans[:200].replace("\n", " "),
            "config_latency_s": round(time.time() - t_cfg, 1),
        }
        row["failure_bucket"] = classify_failure(row)
        rows.append(row)
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(questions)}] done")
    elapsed = time.time() - t_cfg
    print(f"  config total: {elapsed:.0f}s  per-question: {elapsed/len(questions):.1f}s")
    return rows


def classify_failure(row: dict) -> str:
    """Classify a failed question into a failure bucket (Plan §9)."""
    if row["joint_correct"]:
        return ""
    qtype = row["question_type"]
    expected = row["expected_route"]
    route_ok = row["route_result"] == "correct"
    rec_hit = row["retrieval_hit"]
    num_ok = row["numeric_match"]

    if expected == "abstain":
        return "false_positive"  # answered when should have abstained
    if expected == "web":
        return "web_search_miss" if route_ok else "wrong_routing"
    # Corpus questions
    if not rec_hit:
        return "retrieval_miss"
    if qtype == "numerical" and num_ok is False:
        return "table_mangle"  # retrieved right chunk but number extraction failed
    if not route_ok:
        return "wrong_abstention"  # LLM abstained despite having right context
    return "generation_error"


def judge_faithfulness(question: str, answer: str, hits: list, n_rounds: int = 3) -> tuple:
    """LLM judge: does the answer faithfully follow from the cited chunks?

    Returns (faithful: bool, disagreement: bool) where faithful is majority
    verdict and disagreement is True when not all 3 rounds agree.
    (Plan §8, §13 — run 3x, report disagreement, never ground truth.)
    """
    context_blocks = []
    for h in hits:
        m = h["meta"]
        context_blocks.append(
            f"[chunk_id={h['chunk_id']} ticker={m.get('ticker','?')} "
            f"anchor={m.get('anchor','?')}]\n{h['text'][:2000]}"
        )
    ctx = "\n\n-----\n\n".join(context_blocks)
    judge_prompt = (
        "You are a faithfulness judge. Determine if the ANSWER faithfully "
        "follows from the provided CONTEXT.\n\n"
        "A faithful answer: (1) only makes claims directly supported by the "
        "context, (2) cites chunk_ids that actually contain the claimed "
        "information, (3) does not contradict the context.\n"
        "An unfaithful answer: (1) invents numbers or facts not in the "
        "context, (2) misattributes information to the wrong company/year, "
        "(3) cites chunks that do not support the claim.\n\n"
        f"CONTEXT:\n{ctx}\n\n"
        f"QUESTION: {question}\n\n"
        f"ANSWER: {answer}\n\n"
        "Output exactly:\n"
        "FAITHFUL: Yes\n"
        "REASON: <one sentence>\n"
        "or\n"
        "FAITHFUL: No\n"
        "REASON: <one sentence>"
    )
    verdicts = []
    for _ in range(n_rounds):
        raw = call_llm(judge_prompt)
        if "FAITHFUL: Yes" in raw or "FAITHFUL: YES" in raw or "faithful: yes" in raw:
            verdicts.append(True)
        else:
            verdicts.append(False)
    majority = sum(verdicts) > n_rounds / 2
    disagreement = len(set(verdicts)) > 1
    return majority, disagreement


def write_csv(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def summarize(rows):
    from collections import defaultdict
    by_config = defaultdict(list)
    for r in rows:
        by_config[r["config"]].append(r)

    print(f"\n{'config':<45} {'N':<4} {'num_match':<10} {'rec_hit':<8} {'route_ok':<8} {'joint':<6}")
    print("-" * 90)
    for cfg, rs in sorted(by_config.items()):
        n = len(rs)
        n_num = sum(1 for r in rs if r["numeric_match"] is True)
        n_num_total = sum(1 for r in rs if r["numeric_match"] is not None)
        n_rec = sum(1 for r in rs if r["retrieval_hit"])
        n_route_ok = sum(1 for r in rs if r["route_result"] == "correct")
        n_joint = sum(1 for r in rs if r["joint_correct"])
        nm = f"{n_num}/{n_num_total}" if n_num_total else "-"
        print(f"{cfg:<45} {n:<4} {nm:<10} {n_rec:<8} {n_route_ok:<8} {n_joint:<6}")

    # Per-type numeric match
    print("\nNumeric match by config x question_type:")
    by_cfg_type = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["numeric_match"] is not None:
            by_cfg_type[r["config"]][r["question_type"]].append(r["numeric_match"])
    types = sorted({r["question_type"] for r in rows})
    header = f"{'config':<45} " + " ".join(f"{t[:8]:<9}" for t in types)
    print(header)
    for cfg in sorted(by_cfg_type):
        line = f"{cfg:<45} "
        for t in types:
            vals = by_cfg_type[cfg].get(t, [])
            if vals:
                line += f"{sum(vals)}/{len(vals):<8} "
            else:
                line += f"{'-':<9} "
        print(line)


def report_faithfulness(rows):
    """Print faithfulness summary (run 3x, report disagreement, not ground truth)."""
    judged = [r for r in rows if r.get("faithful") is not None]
    if not judged:
        return
    from collections import Counter
    n_ok = sum(1 for r in judged if r["faithful"])
    n_disagree = sum(1 for r in judged if r["faithfulness_disagreement"])
    print(f"\n=== Faithfulness judge (Plan §8) — {len(judged)} questions judged ===")
    print(f"  Faithful: {n_ok}/{len(judged)}  Disagreement rate: {n_disagree}/{len(judged)}")


def report_failure_taxonomy(rows):
    """Print failure bucket breakdown per config (Plan §9)."""
    from collections import defaultdict, Counter
    by_cfg = defaultdict(list)
    for r in rows:
        by_cfg[r["config"]].append(r)
    print("\n=== Failure taxonomy (Plan §9) ===")
    bucket_order = ["retrieval_miss", "table_mangle", "wrong_abstention",
                    "false_positive", "web_search_miss", "wrong_routing", "generation_error"]
    header = f"{'config':<45} " + " ".join(f"{b[:12]:<13}" for b in bucket_order) + "joint_ok/total"
    print(header)
    print("-" * 45 + " " + "-" * (13 * len(bucket_order) + 15))
    for cfg in sorted(by_cfg):
        rs = by_cfg[cfg]
        joint_ok = sum(1 for r in rs if r["joint_correct"])
        counts = Counter(r["failure_bucket"] for r in rs if r["failure_bucket"])
        line = f"{cfg:<45} "
        for b in bucket_order:
            line += f"{counts.get(b, 0):<13} "
        line += f"{joint_ok}/{len(rs)}"
        print(line)


def diff_vs_previous(current_rows):
    if not os.path.exists(PREVIOUS_PATH):
        return
    with open(PREVIOUS_PATH) as f:
        prev = list(csv.DictReader(f))
    prev_by_key = {(r["config"], r["question_id"]): r for r in prev}
    diffs = []
    for r in current_rows:
        p = prev_by_key.get((r["config"], r["question_id"]))
        if not p:
            continue
        if p.get("joint_correct") != r.get("joint_correct"):
            diffs.append((r["config"], r["question_id"], p["joint_correct"], r["joint_correct"]))
    if diffs:
        print(f"\n=== Diff vs previous run ({len(diffs)} joint_correct changes) ===")
        for cfg, qid, prev_v, new_v in diffs[:20]:
            print(f"  {cfg} {qid}: {prev_v} -> {new_v}")
    else:
        print("\nNo joint_correct changes vs previous run.")


def main():
    # Rotate previous results for diff
    if os.path.exists(RESULTS_PATH):
        os.replace(RESULTS_PATH, PREVIOUS_PATH)

    questions = load_questions()
    print(f"Loaded {len(questions)} questions from {QUESTIONS_PATH}")

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    all_rows = []
    t0 = time.time()
    for strategy in CHUNK_STRATEGIES:
        for model_key in EMBEDDING_MODELS:
            for rerank_on in [False, True]:
                rows = run_one_config(strategy, model_key, rerank_on, questions, client)
                all_rows.extend(rows)
    print(f"\nTotal time: {time.time()-t0:.1f}s")

    write_csv(all_rows, RESULTS_PATH)
    print(f"\nWrote {len(all_rows)} rows to {RESULTS_PATH}")
    summarize(all_rows)
    report_failure_taxonomy(all_rows)
    report_faithfulness(all_rows)
    diff_vs_previous(all_rows)


if __name__ == "__main__":
    main()
