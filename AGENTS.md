# CRITICAL RULES

> **READ `working_knowledge.md` FIRST.** It has the operational habits
> (e.g. the `opencode serve` shortcut that cuts eval time by ~30 min,
> the data/gitignore layout, recurring gotchas). This file is the
> project-specific config; `working_knowledge.md` is the session
> bootstrap.

## RESPONSES
- Keep responses concise and to the point, unless the user asks for more information.

## PLANNING MODE
- Always ask clarifying questions.
- Never assume design, tech stack or features.
- Always break a project into decent sized modules/chunks which are meaningful.
- Use deep dive sub-agents to assist with research.
- Use deep dive sub-agents to review different aspects of your plan before presenting to the user.

## CHANGE / EDIT MODE
- Never implement changes yourself when possible, use sub-agents.
- Identify and implement changes in parallel when possible. Read from the plan to figure this out.
- Use/recommend the best models for tasks. For planning, a large premium model, when executing, a decent/large model and smaller models for benign tasks.

## TESTING
- Always test each module/chunk after completion. Thorough testing unless specified otherwise.
- Never assume the changes made to work. ALWAYS TEST.

# FinDocQA agent notes

## Run it

All Python scripts use **relative paths** (`data/raw`, `data/chunks`, `data/chroma`, `data/eval`).
Data lives in `src/data/`, so always `cd src` before running.

```bash
cd src
python fetch.py     # pulls SEC 10-Ks + companyfacts (cached after first run)
python chunk.py     # 2 strategies -> data/chunks/{TICKER}_{fixedsize,sectionaware}.json
python embed.py     # 2 strategies x 2 models = 4 Chroma collections
python -m eval.build_questions   # rebuilds data/eval/questions.jsonl + review doc
python query.py "What was Apple research and development expense in FY2025?" \
    --strategy sectionaware --model bge-small --rerank on
```

The eval harness (W2):
```bash
make eval          # runs 56 questions x 8 configs = 448 calls -> data/eval/results.csv
```

No `requirements.txt` — read imports to see deps (chromadb, sentence-transformers, beautifulsoup4, lxml, python-dotenv). No lint, no typecheck config. Tests = `make eval` plus eyeballing `data/eval/questions_review.md` (per the plan §7 human-in-the-loop step).

## Layout

```
FinDocQA/
├── Makefile                    # make eval / fetch / chunk / embed
├── FinDocQA_PLAN.md            # design source of truth (read this first)
├── src/
│   ├── config.py               # paths, 7 tickers, CHUNK_STRATEGIES, EMBEDDING_MODELS, RERANKER_MODEL
│   ├── fetch.py                # SEC throttled fetcher (raw layer, immutable); offset param for prior 10-Ks
│   ├── chunk.py                # 2 strategies: fixedsize (W1 baseline) + sectionaware (plan §5)
│   ├── anchors.py              # anchor vocabulary, item_header_to_anchor, table_heading_to_anchor, XBRL_TAG_TO_ANCHOR
│   ├── embed.py                # 2x2 matrix -> 4 Chroma collections; E5 doc/query prefixes
│   ├── rerank.py               # CrossEncoder Reranker (bge-reranker-base)
│   ├── query.py                # 8-config CLI: --strategy --model --rerank; top-20 -> optional rerank-5
│   ├── scoring.py              # extract_numbers, numeric_match, retrieval_score, routing_score
│   ├── run_eval.py             # 8 configs x 56 questions -> results.csv + summary + diff vs previous
│   ├── eval/
│   │   ├── xbrl_autogen.py     # 20 numerical questions from companyfacts (form=10-K, fp=FY, end=period_end)
│   │   ├── hand_drafted.py     # 10 factual + 8 multihop + 8 cross_filing + 6 abstain + 4 web
│   │   └── build_questions.py  # combines both -> questions.jsonl + questions_review.md
│   └── data/                   # gitignored: raw/, chunks/, chroma/, eval/
└── .opencode/agent/chat.md     # pinned generation model + no-tools system prompt (FROZEN)
```

The 8-config matrix: 2 chunking strategies (fixedsize, sectionaware) x 2 embedding models (bge-small, e5-small) x rerank on/off. All share the generation model in `.opencode/agent/chat.md`.

## Generation model: where it lives

**Pinned in `.opencode/agent/chat.md:4` (`model: opencode-go/minimax-m3`).** NOT in `src/config.py`.
Per the plan (sec 3), this is intentionally a single source of truth — the 8-config matrix
swaps chunking/embedding/rerank but never this line. If you grep `config.py` for the model
name, you will find nothing; that's correct.

`query.py:generate()` and `run_eval.py:call_llm()` call `opencode run --agent chat <prompt>` as
a subprocess. The default `build` agent has bash/read/write tools and will try to call bash
instead of answering — always specify `--agent chat`.

For batch eval (56 questions x 8 configs = 448 calls), cold start per call is ~3-5s. Total eval
runtime is ~75 minutes without a server. Reuse a server: `opencode serve --port 4096` in one
terminal, then add `--attach http://localhost:4096` to the `opencode run` invocation in
`query.py` and `run_eval.py` to cut cold start.

Auth is in `~/.local/share/opencode/auth.json` (single shared opencode-go key). No env var, no
.env. If it expires, `opencode auth login` (interactive).

## The W2 headline (now measurable)

The W1 thesis ("fixed-size severs the label from the number; section-aware recovers it") is
now quantified. Joint correctness (retrieval_hit AND numeric_match for numerical, retrieval_hit
for others) across the 8 configs in `data/eval/results.csv`:

- **fixedsize: 0-1/56** — fixed-size chunks have `anchor=None`, so retrieval_hit is False for
  every corpus question. This is the attributable cost: fixed-size cannot produce anchors.
- **sectionaware: 14-18/56** — semantic anchors (income_statement, item7_mdna, etc.) let the
  bi-encoder and the joint metric align. The headline is visible in the matrix.

Read `data/eval/results.csv` and the per-config summary printed at the end of `make eval`.

The abstention test ("What was Apple's crypto trading revenue in FY2025?") still returns
"Not found in corpus" with empty citations — the prompt's abstention path is exercised and the
routing metric (5-6/6 abstain correct) confirms it.

## SEC access

`src/config.py:13-14`: `USER_AGENT` (mandatory) and `SEC_RATE_LIMIT = 8` (req/sec).
SEC returns 403 without the User-Agent; 429 above 10 req/sec. Both are non-negotiable per
the plan (sec 1). The throttle lives in `fetch.py:_throttled_get`.

NVDA's "latest" 10-K is FY2026 (period_end 2026-01-26); this project targets FY2025, so
`TICKER_10K_OFFSET = {"NVDA": 1}` fetches the prior 10-K (period_end 2025-01-26). See plan
sec 1 (fiscal-year caveat).

## Eval set composition (56 questions, per plan sec 7)

`src/eval/questions.jsonl` (regenerate with `python -m eval.build_questions`):

| Type | Count | Label source | Notes |
|---|---|---|---|
| Numerical | 20 | XBRL auto-gen | form=10-K, fp=FY, end=period_end; gold_span in raw text from heading search |
| Factual | 10 | semi-auto | I draft, human verifies gold_chunks |
| Multihop | 8 | hand | Two anchors (table number + MD&A reason) |
| Cross-filing | 8 | hand | Comparative across companies |
| Unanswerable | 6 | hand | Must abstain |
| Out-of-corpus | 4 | hand | Web fallback path (not yet implemented in W2) |
| **Total** | **56** | | 26 hand-labeled; 30 auto/semi-auto |

Route distribution: corpus 46 / abstain 6 / web 4.

`src/eval/questions_review.md` has the per-question justifications for the 36 hand/semi-auto
questions. **Never LLM-label `gold_chunks`** (plan §7). Review the review doc, correct anchors,
optionally add `gold_spans` for cross-filing/multihop if you want span-overlap scoring
(anchor-only matching works without spans per plan §6).

## What's intentionally not here yet (W3+)

- **Web fallback for out-of-corpus questions** (W3). Plan §11. The 4 `out_of_corpus` questions
  currently score 0/4 on routing because no web path is wired. Add a web-fetch step behind the
  abstention gate, tag provenance, exclude from RAG metrics.
- **Faithfulness judge** (W3). Run 3x, report disagreement, never present as ground truth.
- **Streamlit comparison view** (W3). Config x metric x question-type matrix.
- **Failure taxonomy** (W3). Bucket every miss: retrieval / table mangle / generation /
  wrong abstention / wrong-entity retrieval.
- **README + regression story** (W4). The plan's "one concrete bug the harness caught" framing.
- **MCP wrapper** (W4, droppable). Plumbing, not signal.

## The plan

`FinDocQA_PLAN.md` is the design source of truth. If something here conflicts with the plan,
the plan wins. Re-read sec 1 (fiscal-year caveat), sec 3 (frozen generation model), sec 5
(section-aware policy — frozen before W1 was the goal), sec 6 (anchor scheme), and sec 8
(scoring) before making changes that touch chunking, retrieval, or evaluation.
