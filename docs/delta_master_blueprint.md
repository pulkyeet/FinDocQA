# FinDocQA Delta: Filing Change Intelligence Engine

**One-line pitch:** Type a ticker, get a five-year change-intelligence report — churn scores per section, material changes surfaced and explained with side-by-side quotes, numeric deltas sourced from XBRL, and a longitudinal narrative per section. Every claim traces to a deterministic diff record.

**Two-part system:**
1. **The product (Delta):** filing change-intelligence engine. Deterministic detection, generative interpretation, structured-data numbers.
2. **The foundation (v1 eval harness):** the measurement infrastructure that validated the retrieval and chunking stack Delta is built on. Retained as a regression check.

---

## Part I — The Foundation: RAG Eval Harness (v1, COMPLETE)

### Thesis

Naive fixed-size chunking shreds tabular numeric data, orphaning numbers from their labels. Section/table-aware chunking recovers it. The harness proves this with deterministic retrieval and numeric-correctness metrics, plus an abstention test.

### Corpus + sourcing

- **Corpus:** Magnificent 7 FY2025 10-Ks (AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA). All 7 ingested.
- **Source:** `data.sec.gov`. Free, no API key, no auth.
  - `companyfacts/CIK{id}.json` → every XBRL-tagged fact ever filed. Powers numeric gold answers + auto-gen eval pairs.
  - Inline-XBRL HTML (the 10-K document) → prose chunks with tables intact.
- **Access constraints:** 10 req/sec cap (target 8/sec). Mandatory `User-Agent` header. No daily limit.
- **Fiscal-year caveat:** FY2025 is NOT one calendar window across these companies. Microsoft FY ends Jun 2025, Apple ~Sep 2025, Nvidia FY2025 ended Jan 2025. Record actual period-end on every cross-filing eval pair. NVDA uses `TICKER_10K_OFFSET = {"NVDA": 1}` to fetch the prior 10-K.

### Storage / caching (three local layers)

| Layer | Path | Contents | Invalidates when |
|---|---|---|---|
| Raw | `data/raw/` | Fetched HTML + companyfacts JSON | Never (filings immutable) |
| Processed | `data/chunks/` | Chunked text + metadata | Chunking strategy changes |
| Vectors | Chroma (persisted) | Embeddings, keyed by `(strategy, model)` | Chunking or embedding changes |

The **raw layer makes the eval reproducible**: same cached inputs, swap one config, diff the numbers.

### Pipeline (linear, raw Python, no graph framework)

```
chunk -> embed -> Chroma -> retrieve top-20 -> rerank top-5 -> generate -> answer + citations
```

Raw Python on purpose. The pipeline is linear; LangGraph/LangChain add nothing. Citations from day one.

### 8-config matrix (3 axes)

| Axis | Variants |
|---|---|
| Chunking | fixed-size / section-aware |
| Embedding | bge-small / e5-small |
| Rerank | on (bge-reranker-base) / off |

**HARD RULE:** hold the generation model constant across all 8 configs. One hidden variable poisons the comparison.

### Section-aware policy (FROZEN)

1. **Boundaries:** split on the 10-K's own Item headers.
2. **Size cap + overflow:** cap ~500 tokens (v2 fix — was 800, caused 38% truncation at the 512-token embedding limit). Section over cap → recursively split on sub-headers then paragraphs.
3. **Tables (load-bearing):** each `<table>` is its own ATOMIC chunk, never split mid-table. Prefix with context (section heading + scale line + introducing sentence). Tag `type=table`, `table_scale`.
4. **Small-section merge:** min floor ~100 tokens; below it, merge into next section.
5. **Metadata per chunk:** `anchor`, `section/item`, `page`, `type` (prose|table), `table_scale`, `char_span`.

### Anchor scheme

- `chunk_id`: `{ticker}-{form}-{fy}-{strategy}-{NNNN}`. Display/debug only.
- `anchor`: stable label for the source region, e.g. `income_statement`, `item7_mdna`, `item1a_risk`. **Stable across chunking strategies AND across years** — this is the property Delta exploits for cross-year alignment.

**Label gold_chunks with ANCHORS, never chunk_ids.** Anchors are stable = one shared answer key = legitimate comparison.

### Eval set (56 questions)

| Type | Count | Route | Label source |
|---|---|---|---|
| Numerical | 20 | corpus | XBRL auto-gen |
| Factual | 10 | corpus | semi-auto |
| Multihop | 8 | corpus | hand |
| Cross-filing | 8 | corpus | hand |
| Unanswerable | 6 | abstain | hand |
| Out-of-corpus | 4 | web | hand |

**Hand-labeled bucket = 26** on 3 filings of maximum contrast. Labels are the ruler, not the thing measured. **Never LLM-label gold_chunks.**

### Scoring

| Metric | Method | Trust |
|---|---|---|
| Retrieval precision/recall | Anchor set membership vs gold_chunks | Deterministic gold |
| Routing | 3-way classification vs expected_route | Deterministic |
| Numeric correctness | Normalize-and-compare, 5% tolerance | Deterministic |
| Faithfulness | LLM judge 3x, majority + disagreement | Noisy, prose only |

### Known results (baseline)

| Config | Joint | Retrieval | Numeric | Route |
|---|---|---|---|---|
| sectionaware + bge-small + rerank=off | 28/56 | 20/56 | 9/20 | 31/56 |
| sectionaware + e5-small + rerank=off | 27/56 | 18/56 | 13/20 | 36/56 |
| fixedsize + * (any config) | 9-10/56 | 0-1/56 | — | 28-32/56 |

Key regression: sectionaware + e5-small with rerank ON drops numeric_match 13/20 → 6/20. The reranker prefers MD&A prose over number-dense table chunks.

### Web fallback (gated, provenance-tagged)

RAG runs first; web fires ONLY when RAG abstains. Tag provenance always. Exclude web answers from RAG metrics.

---

## Part II — The Delta Upgrade: Filing Change Intelligence (v2)

### Why this upgrade

FinDocQA v1 answers questions about a single fiscal year. **Delta** extends the corpus to five fiscal years per ticker and adds a change-intelligence layer: given a ticker, fetch its last five 10-Ks, align them section by section, compute a deterministic diff, enrich with XBRL numeric deltas, and produce an LLM-interpreted report that separates material changes from boilerplate churn.

**Core design principle: the LLM never finds the diff; it only explains it.** Detection is deterministic Python (anchor alignment, embedding similarity, text diff). Interpretation is the only generative step, operating on small pre-verified change sets. This keeps the system cheap, auditable, and hard to hallucinate with.

### Market validation

- **Tier 1, mechanical redlining: BamSEC** (~$69/mo). Side-by-side filing redlines. Acquired by Tegus → AlphaSense (~$930M deal). Exact but uninterpreted.
- **Tier 2, AI summarization: Fintool Feed.** Feed-style summarization of new filings. Strong at "what does this filing say," weaker as rigorous YoY comparison.
- **Tier 3, dumb monitors: Visualping, PageCrawl.** Detect that a filing appeared, not what changed.

**Delta's position: Tier 1 rigor with Tier 2 readability.** Deterministic diff + interpretation layer that triages by materiality. No low-cost product occupies this intersection.

**Academic anchor:** *Lazy Prices* (Cohen, Malloy, Nguyen) found firms whose filings change the most subsequently underperform — the market fails to read diffs. The signal is documented; the bottleneck is human reading capacity, which this automates.

### How it builds on v1

| Existing asset | Role in Delta |
|---|---|
| `fetch.py` (throttled EDGAR fetcher) | Extended from 1 to 5 fiscal years per ticker |
| `chunk.py` section-aware + `anchors.py` | The alignment primitive. Cross-year pairing = anchor equality. Free by construction. |
| `embed.py` models, prefix helpers | Reused verbatim for paragraph-level matching (stage 4) |
| XBRL companyfacts + `scoring.py` numeric normalization | Becomes the numeric backbone of stage 6 |
| opencode agent + `opencode serve` batching | Stage 7-8 generation calls, same no-tools agent |
| 8-config eval harness | Recedes to supporting role: validated the retrieval stack Delta reuses; remains as regression check |

### The pipeline (9 stages)

```
fetch (5 yrs) → parse + anchor → align sections (anchor equality)
    → align paragraphs (embeddings) → deterministic diff classification
    → XBRL numeric deltas joined → LLM interpretation (changed pairs only)
    → narrative composition (chapters) → report render
```

**Stage 1: Fetch.** EDGAR submissions API lists full filing history; extend the throttled fetcher to loop over the last N 10-K accession numbers. Companyfacts (already cached) contains all historical XBRL values.

**Stage 2: Parse and anchor.** Section-aware chunker runs per filing year, tagging sections with the anchor vocabulary. Anchors are stable across years = the alignment primitive.

**Stage 3: Cross-year section alignment.** Free: `item1a_risk(FY24)` pairs with `item1a_risk(FY25)`. Sections that appear/disappear are flagged as structural changes.

**Stage 4: Paragraph-level alignment.** Within a section pair, each FY(n+1) paragraph is matched to its most similar FY(n) paragraph via embedding cosine similarity. Greedy best-match with a similarity floor; unmatched paragraphs become additions/removals. The chunk is the storage container; Delta splits it into paragraphs (the working unit) via `split_into_paragraphs()`.

**Stage 5: Deterministic diff classification.** Per matched pair, cosine similarity buckets the change:

| Similarity | Classification | Downstream |
|---|---|---|
| > 0.95 | unchanged | dropped |
| 0.80–0.95 | modified (minor) | difflib word-level delta |
| 0.60–0.80 | modified (major) | difflib delta, always sent to LLM |
| unmatched (new) | added | sent to LLM |
| unmatched (old) | removed | sent to LLM |

Output: a machine-readable **diff record** per change. Churn score per section per year = fraction of paragraphs classified as changed, weighted by length.

**Numeric guard (augments Stage 5).** Cosine is blind to value-only changes — a paragraph whose only difference is a number (revenue $100M → $489M) scores ~0.99 and would be dropped as `unchanged`. A deterministic guard runs *only* on `unchanged` records and upgrades them: a **text guard** (`numeric_change_signal`, reusing `scoring.extract_numbers`) fires on a ≥20% relative move on any section (→ `modified_minor`, or `modified_major` for ≥100%), and **XBRL corroboration** (`xbrl_change_signal`) flags the most number-dense paragraph when an audited financial-section tag moved but the text guard stayed silent. It runs before Stage 6's join by computing XBRL deltas up front. Orthogonal to the thresholds above; every upgrade carries an auditable `numeric_guard` field, surfaced in the report as a `Δ NNN%` badge.

**Stage 6: XBRL join.** For financially-loaded sections (Item 7, Item 8), YoY deltas for relevant XBRL tags are computed from companyfacts and attached as context. The LLM receives numbers from structured data, never extracts from prose.

**Stage 7: LLM interpretation.** Changed records (only changed) go to the generation model with a strict JSON-output prompt. The model classifies each change (`added/removed/expanded/softened/strengthened/reworded`), assigns materiality (`boilerplate/notable/material`), writes a one-line summary, and for notable+ changes, one line on why it matters with verbatim quotes from each year.

**Stage 8: Narrative composition (`delta/narrate.py`).** The readability layer, and the reason the report is a product rather than a diff dump. One LLM call **per chapter** (not per section) over that chapter's material/notable interpretations produces 600–900 words of analyst prose. Uses `SYSTEM_PROSE`; sending stage 7's `SYSTEM_JSON` here visibly degrades output.

Traceability survives the prose via short evidence labels (`E1`, `E2`…) the narrator cites inline as `[E7]`. `resolve_citations()` renumbers them by first appearance, renders `<sup>` links into the chapter's evidence drawer, and **silently drops any label not in the pool** — the same fail-safe as an unvalidated quote. HTML-escaping happens *before* citation substitution, so model-emitted markup can never become live HTML.

*Supersedes the original per-section trend synthesis*, which produced correct but unreadable output: a longitudinal paragraph per section, ~27 of them, with no editorial hierarchy. Chapters are **data, not template logic** (`config.py:REPORT_CHAPTERS`), so re-cutting the report is a config edit.

**Stage 9: Report render.** Jinja2 HTML report per ticker + CLI summary. Chapters lead; churn survives at section level only (`CHURN_MIN_RECORDS = 8` hides stubs that would score a meaningless 1.00). Stage-7 and stage-8 output are both persisted (`_interpretations.jsonl`, `_narrative.json`) so `rerender.py` rebuilds the HTML with zero LLM calls.

### Why the LLM-explains-but-never-detects split matters

Three failure modes of the naive approach (feed two 10-Ks to a long-context model, ask "what changed"):

1. **Cost:** 10-K = 50K-100K tokens. Two per section pair per year pair per ticker = millions of tokens. Delta's LLM sees only changed passages: 2K-8K per section pair, 10x cheaper.
2. **Hallucinated changes:** long-context models invent differences. In Delta, every claim links to a diff record. If the LLM asserts a change with no underlying record, the renderer drops it. Faithfulness is enforced structurally.
3. **Missed changes:** recall is a property of the deterministic layer (measurable, tunable), not at the mercy of a model's attention over 200K tokens.

### Data model

**Diff record** (stage 5 output, the atomic unit):
```json
{
  "ticker": "AAPL",
  "anchor": "item1a_risk",
  "year_pair": ["FY2024", "FY2025"],
  "change_id": "AAPL-1a-24-25-017",
  "classification": "modified_major",
  "similarity": 0.71,
  "old_text": "...",
  "new_text": "...",
  "word_delta": {"added": [...], "removed": [...]}
}
```

**Interpretation record** (stage 7 output, JSON-schema-validated):
```json
{
  "change_id": "AAPL-1a-24-25-017",
  "change_type": "expanded",
  "materiality": "material",
  "summary": "AI competition risk expanded...",
  "why_it_matters": "First litigation-specific framing...",
  "old_quote": "competition in machine learning",
  "new_quote": "litigation relating to training data provenance"
}
```

**Two invariants enforced in code:**
1. Every interpretation must reference an existing `change_id` (no invented changes).
2. Both quotes must be verbatim substrings of the corresponding diff record's text (literal `in` test; failures trigger one retry, then render with diff but without interpretation, visibly flagged).

### Chunking fixes (v2, mandatory)

Three changes to `chunk.py`, discovered during v2 planning:

1. **HTML cleaning (mandatory):** Current chunks contain XBRL metadata garbage (1,924 us-gaap tag refs, 625 entity IDs, FASB namespace URIs across 7 tickers). Strip `ix:hidden`, `ix:resources`, `ix:header` from DOM before `get_text()`. Add text-level post-filter for residual noise (standalone entity IDs, FASB URIs, us-gaap tags).

2. **Size fix (mandatory):** 38% of chunks (710/1868) exceed the 512-token embedding model limit, causing silent truncation. Lower `SA_MAX_TOKENS` 800→500, `SA_TARGET_TOKENS` 600→350. Every chunk now fits the model window.

3. **Paragraph bridge:** Add `split_into_paragraphs(chunk_text) -> list[str]` in `delta/align.py`. Splits on `\n\n`. The explicit bridge from "chunk" (storage) to "paragraph" (Delta's working unit).

**Why not bigger chunks + bigger model?** Bigger chunks hurt retrieval precision. The industry skipped the middle (512→8192, no 1024/2048 models). Delta works at paragraph level (50-200 tokens) — the model's max_seq_length is irrelevant for Delta's core pipeline. Keep bge-small.

**Why not section-wise chunking (one big chunk per section)?** 20% of sections exceed 8192 tokens (max: META Item 1 = 135,222 tokens). No model handles that. But it doesn't matter — Delta splits chunks into paragraphs anyway. The chunk is a storage container, not the working unit.

**Why not line-item chunks?** Loses table context, doesn't help Delta (tables align by anchor + XBRL), multiplies chunk count for no gain. Tables stay atomic.

### Threshold tuning (50-pair labeled sample)

Hand-label ~50 paragraph pairs from one ticker (changed vs unchanged vs materially changed) with their similarity scores. Tune the 0.95/0.80/0.60 thresholds against them. Hold out 10 pairs for precision/recall. Produces one honest README sentence: "thresholds tuned on a 50-pair labeled sample, precision/recall X/Y on held-out pairs."

### Model usage and cost

Generation model: the existing frozen opencode model. Per-ticker budget for a full 5-year run: 4 year-pairs × ~8 sections × one interpretation call (2-8K tokens) + 8 synthesis calls = ~40-50 LLM calls, 150-300K input tokens. All 7 tickers fit in an evening batch through `opencode serve`. Embedding cost is local and negligible.

### Web application

**Stack:** FastAPI + Jinja2 (server-rendered). DESIGN.md's colors/typography/components become CSS variables and classes. No JS framework.

**Two pages:**
1. **Index/hero page (`/`):** Sells the project (Voltagent-inspired dark canvas, electric-green accent, Inter + SF Mono, hairline cards). Contains a ticker input section (text input + years selector, default 5, max 5).
2. **Report page (`/report/{ticker}`):** Renders the Delta change report as chaptered analyst prose with an evidence drawer per chapter — financial tables (every year's value + YoY %), section churn, and change statistics. Per-paragraph change cards were deliberately dropped in Report v2: the deliverable is the report a human reads, and the diff is the evidence layer beneath it.

**Interaction model:** Submit ticker → serve the pre-built report if it exists, else a "not published" page. There is no live generation path — see Deployment.

### Deployment

**SHIPPED: Tier 1 static (Fly.io, effectively $0/mo).** FastAPI serves pre-built reports from a slim image; the pipeline runs offline and reports are baked in at build time. Details in `DEPLOY.md`.

Two decisions here supersede the original plan below:

- **`/api/trigger` is inert (returns `501`).** Live generation was dropped, not deferred-with-intent. It would require the full pipeline image (torch, chromadb), runtime secrets, a volume, and an async job runner — and would break the cost invariant. The endpoint remains only to report readiness. Adding a ticker means running the pipeline locally and redeploying.
- **Cost invariant: Fly has no free tier but does not collect invoices under $5/mo.** `fly.toml` pins `[[vm]]` to `shared-cpu-1x`/`256mb` (~$2.02/mo always-on) to stay under that line; the `fly launch` default of 1GB is $5.92/mo and would be billed in full. Never attach a volume, Postgres, or Redis — those bill regardless of machine state. This is what makes the original "~$5/mo" estimate come out at ~$0 in practice.

*Original tiering, retained for context:*

**Tier 0 (static reports, $0):** GitHub Actions runs the batch monthly, commits `data/reports/*.html`, GitHub Pages serves them. — *Not pursued; Fly + baked reports achieves the same cost with the real routes. Note that a CI-based deploy would ship an empty reports directory, since `src/data/` is gitignored.*

**Tier 1 (small live service, ~$5/mo):** FastAPI app serves pre-built reports + `/api/trigger/{ticker}` endpoint for fresh runs on the 7 cached tickers. Fly.io or Railway. — *Shipped, minus the trigger.*

**Tier 2 (any-ticker, ~$5-15/mo):** Deferred. Accept arbitrary tickers with job queue + progress page.

### Risks and scope control

- **Parser drift on older filings** (top risk): mitigated by starting at 3×3, anchor-coverage assertions per filing (fail loudly if anchor doesn't resolve), raw-layer caching for free re-parsing.
- **Alignment quality in restructured sections:** greedy matching may degrade; Hungarian-style assignment as fallback if the labeled sample shows it's needed.
- **LLM materiality is subjective:** presented as AI triage aid, never ground truth. The deterministic diff beneath is the ground truth.
- **Scope creep toward finance product:** no price data, no signals, no backtesting. Lazy Prices is framing, not a claim to replicate.

### Out of scope

- LangGraph/LangChain orchestration (pipeline is linear)
- Long-context LLM does the whole diff (the architecture's central thesis rejects this)
- Text-to-SQL over XBRL (deferred — strong runner-up but replaces rather than builds on the RAG pipeline)
- Line-item-based chunking (loses table context, doesn't help Delta)
- Bigger embedding models (unnecessary for Delta's paragraph-level work)
- SPA frontend (DESIGN.md is expressible in CSS; the report is a document, not an app)
- Streamlit for v2 UI (incompatible with DESIGN.md component system)
- Price data, signals, backtesting (not an investment tool)
