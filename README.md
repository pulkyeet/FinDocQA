# FinDocQA: RAG Eval Harness for Financial Documents

A QA system over SEC 10-K filings with a deterministic eval suite that measures
and compares chunking, embedding, and reranking strategies. The eval harness is
the project, not the chatbot.

## The thesis

Financial tables are the hardest test for RAG. A single income-statement row
carries both a label ("Research and development") and a number ("$29,915").
Naive fixed-size chunking severs them — "Research and development" lands in one
chunk, "$29,915" in another, and the number is orphaned from its label.

Section-aware chunking keeps tables atomic and tags each chunk with a semantic
**anchor** (`income_statement`, `item7_mdna`, `cash_flow`). The anchor is
stable across all chunking strategies, so every config shares one answer key.

**In hard numbers:** fixedsize configs score 9-10/56 joint correct vs
section-aware configs scoring 24-28/56. The difference is entirely attributable
to retrieval — fixedsize has `retrieval_hit = 0-1/56` because it cannot produce
anchors.

## The regression the harness caught

*The reranker, intended to boost relevance, systematically hurts numerical
accuracy — and only the harness can prove it.*

Under the section-aware strategy with e5-small embeddings, turning cross-encoder
rerank ON causes `numeric_match` to drop from **13/20 to 6/20** (a 54% relative
decline). The reranker pulls chunks that *sound* relevant (MD&A prose discussing
trends) over chunks that *contain* the actual dollar figures (income statement
tables). The bi-encoder alone is better at surfacing number-dense table chunks.

This is why deterministic scoring matters. Without XBRL gold values, both
outputs look plausible — "R&D was ~$29.9 billion" vs "R&D increased 10%." The
harness compares each answer against the ground-truth XBRL number, flags the
drop, and attributes it to one toggle. That 7-question gap is invisible without
the harness.

A smaller but similarly clean regression: switching from e5-small to bge-small
(section-aware, no rerank) drops numeric_match from **13/20 to 9/20**.

## The 8-config matrix

56 questions, 7 Magnificent 7 tickers, 2 chunking strategies × 2 embedding
models × rerank on/off = 448 scored answers.

| Config | Joint | Retrieval hit | Numeric match | Route ok |
|---|---|---|---|---|
| fixedsize + bge-small + rerank=off | 10/56 | 0/56 | 7/20 | 31/56 |
| fixedsize + bge-small + rerank=on | 9/56 | 0/56 | 9/20 | 30/56 |
| fixedsize + e5-small + rerank=off | 10/56 | 1/56 | 12/20 | 32/56 |
| fixedsize + e5-small + rerank=on | 9/56 | 1/56 | 8/20 | 28/56 |
| **sectionaware + bge-small + rerank=off** | **28/56** | 20/56 | 9/20 | 31/56 |
| sectionaware + bge-small + rerank=on | 24/56 | 14/56 | 7/20 | 30/56 |
| **sectionaware + e5-small + rerank=off** | **27/56** | 18/56 | **13/20** | **36/56** |
| sectionaware + e5-small + rerank=on | 25/56 | 15/56 | 6/20 | 25/56 |

**The thesis gap:** fixedsize (9-10/56) vs section-aware (24-28/56). Retrieval
hit at 0-1/56 vs 14-20/56. The anchor system works.

**The rerank trap (section-aware, e5):** numeric_match 13/20 → 6/20. The
key regression story.

**Per-type breakdown** (section-aware + e5-small, rerank=off — best config for
numerical):

| Type | Joint correct | Notes |
|---|---|---|
| Numerical | 3/20 | XBRL auto-gen; hardest category |
| Factual | 5/10 | Semi-auto; factual lookups |
| Multihop | 7/8 | Two-anchor retrieval |
| Cross-filing | 3/8 | Multi-entity still hard |
| Unanswerable | 5/6 | Routing correctly abstains |
| Out-of-corpus | 4/4 | Web fallback routed correctly |

## How it works

```
chunk → embed → Chroma → retrieve top-20 → (rerank top-5) → generate
```

**Three toggles** (8 configs):
- **Chunking:** fixed-size (600 tokens, 50 overlap) or section-aware (splits on
  Item headers, atomic tables, merges small sections)
- **Embedding:** BAAI/bge-small-en-v1.5 or intfloat/e5-small-v2
- **Rerank:** on (BAAI/bge-reranker-base cross-encoder, top-20→top-5) or off
  (just top-5)

**Generation model is frozen** across all 8 configs (opencode-go/deepseek-v4-flash
via a no-tools opencode agent). The model is held constant so every metric
change is attributable to chunking, embedding, or rerank — not the LLM.

**Scoring** (all deterministic except faithfulness):
- **Retrieval:** anchor set membership (plan §6). Gold_chunks use anchors like
  `income_statement`, not chunk_ids, so every strategy shares one answer key.
- **Routing:** 3-way classification (corpus / abstain / web) vs expected_route.
- **Numeric:** normalize-and-compare with 5% tolerance against XBRL gold values
  (plan §8). Handles currency, scales, paren-negatives, and table_scale from
  chunk metadata.
- **Joint:** retrieval_hit AND numeric_match (numerical); retrieval_hit
  (corpus non-numerical); routing correct (abstain/web).
- **Faithfulness:** LLM judge, run 3x, majority verdict, disagreement reported.
  Gated behind `FAITHFULNESS_JUDGE=1` env var (off by default). Never ground
  truth.

**Eval set: 56 questions** across 7 types:

| Type | Count | Source | Route |
|---|---|---|---|
| Numerical | 20 | XBRL auto-gen (plan §7) | corpus |
| Factual | 10 | Semi-auto with human review | corpus |
| Multihop | 8 | Hand-labeled (2 anchors each) | corpus |
| Cross-filing | 8 | Hand-labeled | corpus |
| Unanswerable | 6 | Hand-labeled | abstain |
| Out-of-corpus | 4 | Hand-labeled | web |

All 7 filings (AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA) sit in the corpus as
realistic retrieval distractors. 3 are hand-labeled for gold_chunks (plan §7 —
signal saturates at 3).

## Quick start

```bash
cd src

# Pipeline
python fetch.py                  # SEC 10-Ks + companyfacts (cached)
python chunk.py                  # 2 strategies → data/chunks/
python embed.py                  # 2 models × 2 strategies → 4 Chroma collections
python -m eval.build_questions   # 56 eval questions → data/eval/

# Single query
python query.py "What was Apple R&D in FY2025?" \
    --strategy sectionaware --model e5-small --rerank on

# Full eval sweep (448 LLM calls — start opencode serve --port 4096 first)
make eval

# Interactive dashboard
streamlit run src/dashboard.py
```

## Limitations

- **Per-type slices are small-n** (6-20 questions). Directional, not
  conclusive. The aggregate (56) and numerical bucket (20) carry the weight.
- **Joint metric doesn't capture routing-only correctness.** Abstain and
  web questions score via routing, not retrieval — joint reflects that design.
  The routing column in the matrix is the metric for these.
- **Only 3 filings hand-labeled** (AAPL, MSFT, NVDA). The other 4 act as
  retrieval distractors — essential for entity-discrimination testing but not
  individually scored.
- **Web fallback uses DuckDuckGo search** — noisy for financial precision.
  Provenance is tagged `[source: web]` and excluded from RAG metrics.
- **Faithfulness judge is an LLM** (3x majority, disagreement reported). Never
  presented as ground truth.

## Project structure

```
FinDocQA/
├── README.md
├── Makefile                    # make eval / fetch / chunk / embed
├── tracker.md                  # W1-W4 progress
├── FinDocQA_PLAN.md            # Design source of truth
├── .opencode/                  # opencode config
│   ├── opencode.json           # Model defaults + per-agent overrides
│   └── agent/chatter.md        # No-tools generation agent
├── src/
│   ├── config.py               # Paths, tickers, model keys
│   ├── fetch.py                # SEC throttled fetcher
│   ├── chunk.py                # 2 strategies (fixedsize, sectionaware)
│   ├── anchors.py              # Anchor vocabulary
│   ├── embed.py                # 2×2 Chroma builder
│   ├── rerank.py               # CrossEncoder reranker
│   ├── query.py                # 8-config CLI query
│   ├── run_eval.py             # Full 448-call eval sweep
│   ├── scoring.py              # Metrics (numeric, retrieval, routing)
│   ├── web_search.py           # DuckDuckGo fallback
│   ├── dashboard.py            # Streamlit comparison view
│   └── eval/
│       ├── xbrl_autogen.py     # 20 numerical auto-gen questions
│       ├── hand_drafted.py     # 36 hand-labeled questions
│       └── build_questions.py  # Combines → questions.jsonl
└── src/data/                   # gitignored: raw, chunks, chroma, eval
```
