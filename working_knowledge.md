# Working Knowledge

> **Process this file FIRST before doing anything else.** It contains the
> operational habits and shortcuts that make this project fast. The agent
> should re-read it on every new session.

## Always-on habits

### 1. The `opencode serve` shortcut (cut LLM cold start from ~5s to ~1s)

`opencode run` by default spawns a new process and loads the model each
call (3–5s cold start). For batch jobs (eval, Delta interpretation,
any test sweep), start the server once in a separate terminal and use
`--attach`:

```bash
# Terminal A — leave running
opencode serve --port 4096

# Terminal B — your actual work
cd /home/pulkyeet/findocQA/FinDocQA
# (The agent should remind you to start the server in another
# terminal before running make eval, make delta-batch, or any batch LLM sweep.)
```

`opencode run` then accepts `--attach http://localhost:4096` and skips
the model load. Saves ~3–4s per LLM call. For the 448-call v1 eval this
shaves ~20–30 minutes. For Delta's ~40-50 LLM calls per ticker × 7
tickers, it shaves ~15-20 minutes off a full batch.

**If the agent is about to run `make eval`, `make delta-batch`, or any
batch LLM test sweep, it should pause and ask: "Is `opencode serve
--port 4096` running in another terminal? If not, start it there
before I proceed."**

### 2. Data layer is gitignored

`data/raw/`, `data/chunks/`, `data/chroma/`, `data/eval/results.csv`,
`data/diffs/`, `data/reports/` are all gitignored. Re-running
`python fetch.py` / `chunk.py` / `embed.py` / `delta.py` rebuilds them
from scratch (raw fetches are cached by file existence; chunk/embed/delta
always overwrite). The raw layer is the single source of truth for
reproducibility — never edit a 10-K by hand.

### 3. All scripts run from `src/`

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
  duckduckgo-search, streamlit, pandas, torch; v2 adds: fastapi, uvicorn, jinja2).
- **Models cached at**: `~/.cache/huggingface/` (HuggingFace download cache;
  first run downloads, subsequent runs are fast).
- **Auth**: `~/.local/share/opencode/auth.json` (shared opencode-go key).
  No env var, no `.env`. If it expires: `opencode auth login` (interactive).
- **HF rate-limit warning**: you'll see *"You are sending unauthenticated
  requests to the HF Hub. Please set a HF_TOKEN to enable higher rate
  limits."* on first model load. It still works without the token; the
  warning is informational. Set `HF_TOKEN` in your shell to silence it.

## v2 file naming convention (IMPORTANT)

v2 uses year-suffixed file names for multi-year support:
- Raw: `{ticker}_FY{yyyy}_10k.html` (was `{ticker}_10k.html`)
- Chunks: `{ticker}_FY{yyyy}_sectionaware.json` (was `{ticker}_sectionaware.json`)
- Diffs: `data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl`
- Reports: `data/reports/{ticker}.html`

The fiscal year label comes from `fiscal_year_label(period_end)` in `fetch.py`.
Example: `period_end="2025-09-27"` → `"FY2025"`.

Existing v1 files (FY2025) are renamed to include the `FY2025` suffix in
phase 00. `embed.py:load_chunks` is updated to glob `{ticker}_FY*_{strategy}.json`.

## v2 chunking fixes (IMPORTANT — discovered during planning)

Three fixes to `chunk.py` in phase 00:
1. **HTML cleaning:** strip `ix:hidden`, `ix:resources`, `ix:header` from DOM
   before `get_text()`. Add `_strip_xbrl_noise()` text filter. Current chunks
   contain 1,924 us-gaap tag refs + 625 entity IDs = garbage.
2. **Size fix:** `SA_MAX_TOKENS` 800→500, `SA_TARGET_TOKENS` 600→350. The
   embedding models (bge-small, e5-small) cap at 512 tokens; 38% of v1 chunks
   were silently truncated.
3. **Paragraph bridge:** `split_into_paragraphs()` in `delta/align.py` splits
   chunk text on `\n\n` into paragraphs. Delta works at paragraph level, not
   chunk level. The chunk is just storage.

## Recurring gotchas

- **`opencode run` agent must be a no-tools agent, not `build`.** The default
  `build` agent has bash/read/write tools and will try to call them
  instead of answering. The generation agent (`chatter`) is set in
  `config.py:OPENCODE_AGENT`. Both v1 (`query.py`, `run_eval.py`) and v2
  (`delta/interpret.py`) use this agent.
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

## Quick verification commands

```bash
# v1: Is the corpus complete? (all 7 filings cached)
ls data/raw/*_10k.html | wc -l   # expect 7 (v1 naming) or 35 (v2 naming)

# v2: Is the multi-year corpus complete?
ls data/raw/*_FY*_10k.html | wc -l   # expect 35 (7 tickers × 5 years)

# v2: Are chunks built for all years?
ls data/chunks/*_FY*_sectionaware.json | wc -l   # expect 35

# v2: Are diff records built?
ls data/diffs/AAPL/   # expect 4 year-pair .jsonl files

# v2: Are reports built?
ls data/reports/*.html   # expect 7 (one per ticker)

# v1: Are the 4 Chroma collections built?
python -c "import chromadb; c=chromadb.PersistentClient('data/chroma'); print([x.name for x in c.list_collections()])"

# v1: Is the eval set built?
wc -l data/eval/questions.jsonl   # expect 56

# v2: Run the full Delta pipeline for one ticker
cd src && python delta.py AAPL --years 5

# v2: Run diff-only (no LLM, fast)
cd src && python delta.py AAPL --years 5 --no-llm

# v2: Batch all tickers
make delta-batch

# v2: Start the web app
make web   # then visit http://localhost:8000

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
3. **Full pipeline** (`python delta.py AAPL --years 5`): includes LLM
   interpretation. Slow (~40-50 LLM calls per ticker). Only when the user
   explicitly wants generated interpretations.

If the user is about to run a **batch** LLM test (more than ~5 calls),
remind them: *"Start `opencode serve --port 4096` in a separate
terminal first — it'll cut per-call latency by ~4x."*