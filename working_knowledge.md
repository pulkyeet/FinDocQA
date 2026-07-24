# Working Knowledge

> **Process this file FIRST before doing anything else.** It contains the
> operational habits and shortcuts that make this project fast. The agent
> should re-read it on every new session.

## Always-on habits

### 1. OpenRouter is the primary LLM backend (replaces opencode serve)

`interpret.py:call_llm()` branches on `OPENROUTER_API_KEY`:

- **Key present** → calls `https://openrouter.ai/api/v1/chat/completions` via HTTP POST.
  One request per batch, 2–5s latency, no subprocess overhead.
- **No key** → falls back to `opencode run --agent paid-chatter` as a subprocess.
  Slower (~30s per call due to process spawn) but works without API key.

**Setup:**
```bash
# Add to src/.env:
OPENROUTER_API_KEY=sk-or-v1-your-key-here
# Optional: override model
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
```

Default model is `deepseek/deepseek-v4-flash`. Cost is ~$0.02 per ticker with
gpt-4o-mini. The `.env` file is loaded by `config.py` via `python-dotenv`.

### 2. The LLM generation agent is `paid-chatter`

`config.py:OPENCODE_AGENT = "paid-chatter"` — a system agent with no tools.
Only used when OpenRouter is unavailable (fallback path). Never use `build` —
it has bash/read/write tools and will try to call them instead of answering.

### 3. Data layer is gitignored

`data/raw/`, `data/chunks/`, `data/chroma/`, `data/eval/results.csv`,
`data/diffs/`, `data/reports/` are all gitignored. Re-running
`python fetch.py` / `chunk.py` / `embed.py` / `delta.py` rebuilds them
from scratch (raw fetches are cached by file existence; chunk/embed/delta
always overwrite). The raw layer is the single source of truth for
reproducibility — never edit a 10-K by hand.

### 4. All scripts run from `src/`

```bash
cd src
python fetch.py --years 5          # v2: multi-year fetch
python chunk.py --strategy sectionaware  # chunk all fetched filings
python delta.py AAPL --years 5     # v2: full Delta pipeline
python delta.py AAPL --years 5 --no-llm  # v2: diff only, no LLM
python delta.py --all --years 5    # v2: batch all 7 tickers
python query.py "..." --strategy ... --model ... --rerank ...  # v1 RAG
make eval      # from repo root, runs v1 eval
make delta-batch  # from repo root, runs v2 batch
make web       # from repo root, starts FastAPI server
```

The `Makefile` lives at the repo root and `cd src` for you.

## Key environment facts

- **Python**: 3.11.9 at `~/.pyenv/versions/3.11.9/`. Deps in `requirements.txt`
  (v1: chromadb, sentence-transformers, beautifulsoup4, lxml, python-dotenv,
  duckduckgo-search, streamlit, pandas, torch; v2 adds: fastapi, uvicorn, jinja2, requests).
- **Models cached at**: `~/.cache/huggingface/` (HuggingFace download cache;
  first run downloads, subsequent runs are fast).
- **HF token**: Set in `src/.env` as `HF_TOKEN=hf_...`. Silences rate-limit warnings
  and speeds up model downloads.
- **OpenRouter key**: Set in `src/.env` as `OPENROUTER_API_KEY=sk-or-v1-...`.
  If unset, Delta falls back to `opencode run` subprocess calls.

## v2 file naming convention (IMPORTANT)

v2 uses year-suffixed file names for multi-year support:
- Raw: `{ticker}_FY{yyyy}_10k.html` (was `{ticker}_10k.html`)
- Chunks: `{ticker}_FY{yyyy}_sectionaware.json` (was `{ticker}_sectionaware.json`)
- Diffs: `data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl`
- Reports: `data/reports/{ticker}.html`

The fiscal year label comes from `fiscal_year_label(period_end)` in `fetch.py`.
Example: `period_end="2025-09-27"` → `"FY2025"`.

## v2 chunking fixes (IMPORTANT)

Three fixes to `chunk.py` in phase 00:
1. **HTML cleaning:** strip `ix:hidden`, `ix:resources`, `ix:header` from DOM
   before `get_text()`. Add `_strip_xbrl_noise()` text filter with 8 noise patterns.
2. **Size fix:** `SA_MAX_TOKENS` 800→500, `SA_TARGET_TOKENS` 600→350. The
   embedding models (bge-small, e5-small) cap at 512 tokens; 38% of v1 chunks
   were silently truncated. Includes char-level fallback split for oversized
   single-line text, and merge-across-anchors guard to prevent section boundary
   corruption.
3. **Paragraph bridge:** `split_into_paragraphs()` in `delta/align.py` splits
   chunk text on `\n\n` into paragraphs. Delta works at paragraph level, not
   chunk level. The chunk is just storage.

## v2 chunking gotchas discovered during build

- **Heading detection:** AMZN and similar filings put section headings inside
  TABLE elements (mini-TOC dividers), not prose. `_split_prose_at_items()` now
  checks table segments for heading text.
- **Keyword-based fallback:** For filings that don't use "Item X." format in
  body headings, `SECTION_HEADING_PATTERNS` in `chunk.py` matches section names
  like "Risk Factors" → `item1a_risk`.
- **MSFT split headers:** Some MSFT filings split headings across lines (e.g.,
  "ITEM 1A. RIS" / "K FACTORS"). Fallback mapping `_ITEM_FALLBACK_ANCHOR` resolves
  `item1a_unknown` → `item1a_risk`.
- **Merge guard:** `_merge_small_prose_chunks` does NOT merge across anchor
  boundaries, preventing NVDA's Item 8 intro text from being swallowed into
  neighboring sections.

## Recurring gotchas

- **`opencode run` agent must be a no-tools agent, not `build`.** The default
  `build` agent has bash/read/write tools and will try to call them
  instead of answering. `config.py:OPENCODE_AGENT = "paid-chatter"` is a
  system agent with no tools. Both v1 (`query.py`, `run_eval.py`) and v2
  (`delta/interpret.py`) use this agent as the fallback path.
- **Chroma batch limit is 5461.** `embed.py` chunks `collection.add()`
  into ≤5000-row batches for this reason.
- **E5 models need instruction prefixes.** E5 query strings need
  `"query: "` prefix, document strings need `"passage: "`. BGE does
  not. `embed.py` and `query.py` handle this via `doc_prefix()` /
  `query_prefix()` helpers. `delta/align.py:embed_paragraphs()` must
  also use `doc_prefix()` — paragraphs are documents, not queries.
- **CrossEncoder reranker is `BAAI/bge-reranker-base`**, not the
  same as the BGE bi-encoder. Different model, loaded on demand in
  `rerank.py:Reranker`. (v1 only; v2 Delta does not use reranking.)
- **The collection name encodes strategy + model**, e.g.
  `sectionaware__bge-small`. Use `embed.collection_name(strategy, key)`
  to build it. Don't hardcode. (v1 only; v2 Delta embeds paragraphs
  directly, not via Chroma collections.)
- **Retrieval sends top-5 to the LLM** (`TOP_K_FINAL = 5`) regardless
  of rerank toggle. (v1 only.)
- **Web fallback (v1 W3) needs `duckduckgo-search`.** `web_search.py` uses
  `ddgs.DDGS`. Install with `pip install duckduckgo-search`.
- **Faithfulness judge (v1) is off by default.** Set `FAITHFULNESS_JUDGE=1`
  env var to enable.
- **NVDA fiscal offset:** NVDA's latest 10-K is FY2026 (period_end 2026-01-25);
  v1 targets FY2025, so `TICKER_10K_OFFSET = {"NVDA": 1}` fetches the prior 10-K.
  For v2 multi-year, the offset is implicit in the submissions API accession list
  (the N most recent 10-Ks are fetched regardless of fiscal-year labeling).
- **Anchor coverage assertions (v2):** if `item1a_risk`, `item7_mdna`, or
  `item8_financials` fails to resolve for any filing, the chunker raises
  `RuntimeError` at ingest. Never silently mis-align. This is the top-risk
  mitigation from the Delta blueprint (§8 Risks).
- **Interpretation quote validation (v2):** every LLM interpretation's
  `old_quote` and `new_quote` must be verbatim substrings of the diff
  record's `old_text` and `new_text` (literal `in` test). Failures trigger
  one retry, then render with diff but without interpretation, flagged
  `[unvalidated]`.
- **Interpretation batching (v2):** `BATCH_SIZE = 5` in `interpret.py`. Smaller
  batches produce a 100% validation rate but more API calls. Larger batches
  produce malformed JSON from the LLM.
- **Text truncation (v2):** `old_text`/`new_text` truncated to 500 chars before
  sending to LLM. The original 2000-char chunks balloon prompts beyond what the
  model can handle in structured JSON format.
- **Model cache (v2):** `align.py` caches the SentenceTransformer model.
  Loading the model per section (20+ times per year pair) was the original
  cause of the pipeline appearing to hang at stage 3-5.
- **Numeric guard (v2) — fixes numeric-blindness:** cosine scores a paragraph
  whose only change is a number ~0.99 → would be classified `unchanged` → LLM
  never sees it. The guard in `diff.py` runs ONLY on `unchanged` records and
  upgrades them: `numeric_change_signal` (text, reuses `scoring.extract_numbers`,
  fires on ≥20% moves — `NUMERIC_GUARD_PCT`) and `xbrl_change_signal` (flags the
  most number-dense paragraph when an audited financial-section tag moved but
  text didn't). Upgraded records carry an auditable `numeric_guard` field and a
  `Δ NNN%` badge in the report. XBRL deltas are computed BEFORE the diff loop
  (`delta.py`) and passed through `diff_section_pair`/`diff_all_sections`, so the
  guard also runs under `--no-llm`. Orthogonal to the tuned thresholds — no
  re-tuning. Config: `NUMERIC_GUARD_PCT` / `NUMERIC_GUARD_MIN_VALUE` /
  `NUMERIC_GUARD_MAJOR_PCT` / `FINANCIAL_ANCHORS`.
- **Fiscal year matching in companyfacts:** AAPL's `Revenues` tag has data
  only through FY2018 (old revenue standard). Current tag is
  `RevenueFromContractWithCustomerExcludingAssessedTax` (ASC 606).
  `fiscal_year_value()` prefers 10-K (annual) entries over quarterly ones.

## Diff classification thresholds

Tuned on 48-pair labeled sample (5 sections × 2 year pairs from AAPL):

| Threshold | Value | Meaning |
|---|---|---|
| `DIFF_THRESHOLD_UNCHANGED` | 0.95 | Cosine ≥ 0.95 → unchanged |
| `DIFF_THRESHOLD_MINOR` | 0.81 | Cosine ≥ 0.81 → modified_minor |
| `DIFF_THRESHOLD_MAJOR` | 0.60 | Cosine ≥ 0.60 → modified_major |

Held-out (10 pairs): precision=0.300, recall=1.000, F1=0.462.
High recall is intentional — we'd rather over-flag changes and let the
LLM classify them as boilerplate than miss real changes.

## Quick verification commands

```bash
# v2: Is the multi-year corpus complete?
ls data/raw/*_FY*_10k.html | wc -l   # expect ~30 (varies by ticker history)

# v2: Are chunks built for all years?
ls data/chunks/*_FY*_sectionaware.json | wc -l   # expect ~30

# v2: Are diff records built?
ls data/diffs/AAPL/   # expect year-pair .jsonl files

# v2: Run diff-only (no LLM, instant)
cd src && python delta.py AAPL --years 2 --no-llm

# v2: Run full pipeline with OpenRouter
cd src && python delta.py AAPL --years 2

# v2: Batch all tickers
make delta-batch

# v1: Streamlit dashboard
streamlit run src/dashboard.py

# Check progress
cat tracker.md
```

## When the user asks for a test / verification

Always prefer the cheapest check first:
1. **Diff-only** (`--no-llm`): fetch + chunk + align + diff. No LLM calls.
   Fast, deterministic. Use for verifying the pipeline shape.
2. **Retrieval-only** (v1: Python embedding + chroma, no LLM): for v1 RAG checks.
3. **Full pipeline** (`python delta.py AAPL --years 2`): includes OpenRouter
   LLM interpretation. ~1-2 min per ticker. Only when the user
   explicitly wants generated interpretations.
