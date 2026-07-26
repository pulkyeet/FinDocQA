# CRITICAL RULES

> **READ `docs/working_knowledge.md` FIRST.** It has operational habits
> (`opencode serve` shortcut, data/gitignore layout, recurring gotchas
> like Chroma batch limit, E5 prefixes, v2 file naming, chunking fixes,
> interpretation quote validation). This file is project config;
> `docs/working_knowledge.md` is the session bootstrap.

# FinDocQA agent notes

## Two-part system

FinDocQA is now a two-part system:
1. **v1 (COMPLETE): RAG eval harness** — QA over SEC 10-K filings with deterministic eval suite. The credibility floor.
2. **v2 (IN PROGRESS): Delta** — filing change-intelligence engine. Five-year YoY diff with LLM interpretation. The product.

**`docs/delta_master_blueprint.md` is the design source of truth** (merged from the old v1 plan + Delta upgrade report). If something here conflicts with the blueprint, the blueprint wins. For build-ready specs, read `docs/plan/00-ARCHITECTURE.md` and the phase files in `docs/plan/`.

## Run it

All Python scripts use **relative paths** (`data/raw`, `data/chunks`, `data/chroma`, `data/eval`, `data/diffs`, `data/reports`).
Data lives in `src/data/`, so always `cd src` before running.

### v2 (Delta) — the product

```bash
cd src
python fetch.py --years 5                    # multi-year fetch (7 tickers × 5 years)
python chunk.py --strategy sectionaware      # chunk all fetched filings
python delta.py AAPL --years 5               # full pipeline: fetch→chunk→diff→interpret→report
python delta.py AAPL --years 5 --no-llm      # diff only, no LLM (fast, deterministic)
python delta.py --all --years 5              # batch all 7 tickers
```

Or from repo root:
```bash
make delta-batch    # all 7 tickers → data/reports/*.html
make web            # FastAPI server at localhost:8000
make rerender-all   # rebuild HTML from persisted output — NO LLM calls (template/CSS work)
make narrate-all    # recompose chapter prose (~6 LLM calls/ticker), then render (prompt work)
make deploy         # rerender-all, then flyctl deploy (see docs/DEPLOY.md)
```

**Never re-run the full pipeline to check a template change** — `make rerender`
costs nothing. Both stage-7 (`_interpretations.jsonl`) and stage-8
(`_narrative.json`) output are persisted for exactly this reason.

### v1 (eval harness) — the foundation

```bash
cd src
python fetch.py                     # SEC 10-Ks + companyfacts (cached)
python chunk.py                     # 2 strategies → data/chunks/
python embed.py                     # 2 strategies x 2 models = 4 Chroma collections
python -m eval.build_questions      # rebuilds data/eval/questions.jsonl
python query.py "What was Apple R&D expense in FY2025?" \
    --strategy sectionaware --model bge-small --rerank on
```

Or from repo root:
```bash
make fetch
make chunk
make embed
make eval          # 56 questions x 8 configs = 448 calls → results.csv
make test          # unit tests
```

Deps are in `requirements.txt` (v1: chromadb, sentence-transformers, beautifulsoup4, lxml,
python-dotenv, duckduckgo-search, streamlit, pandas, torch; v2 adds: fastapi, uvicorn, jinja2).

## Layout (non-obvious parts only)

```
FinDocQA/
├── DESIGN.md                    # UI design system (Voltagent-inspired, dark canvas)
├── docs/
│   ├── delta_master_blueprint.md  # design source of truth (v1+v2) — read this first
│   ├── working_knowledge.md       # session bootstrap — read this first too
│   ├── DEPLOY.md                  # Fly.io static deploy + cost invariant
│   ├── tracker.md                 # progress tracker
│   └── plan/                      # build-ready architecture + phase files
│       ├── 00-ARCHITECTURE.md     # contracts, schemas, directory tree, decision log
│       ├── INDEX.md               # phase index + dependencies
│       └── phase-00..05-*.md      # one file per execution phase
├── Dockerfile / fly.toml        # slim static deploy (no torch) — see docs/DEPLOY.md
├── requirements-web.txt         # deployed runtime deps only
├── Makefile                     # fetch / chunk / embed / eval / delta / web / deploy / test
├── src/
│   ├── config.py               # paths, tickers, v2 constants (thresholds, chunk sizes, DELTA_* dirs)
│   ├── fetch.py                # SEC throttled fetcher; v2: --years N, fiscal_year_label()
│   ├── chunk.py                # 2 strategies; v2: HTML cleaning, size fix (500 tok), year-suffixed naming
│   ├── anchors.py              # anchor vocabulary (UNCHANGED — the alignment primitive)
│   ├── embed.py                # 2x2 → 4 Chroma collections; v2: load_chunks globs year-suffixed files
│   ├── rerank.py               # CrossEncoder Reranker (v1 only)
│   ├── query.py                # v1 8-config CLI
│   ├── scoring.py              # extract_numbers, numeric_match (reused by v2 xbrl_delta)
│   ├── run_eval.py             # v1 full 8x56 sweep
│   ├── web_search.py           # DuckDuckGo fallback (v1 W3)
│   ├── dashboard.py            # v1 Streamlit 4-tab comparison
│   ├── delta.py                # v2 CLI entrypoint: python delta.py TICKER --years 5
│   ├── rerender.py             # rebuild report HTML from persisted output (no LLM)
│   ├── delta/                  # v2 Delta pipeline package
│   │   ├── align.py            # stage 3-4: section + paragraph alignment
│   │   ├── diff.py             # stage 5: classification, word deltas, churn, numeric guard
│   │   ├── xbrl_delta.py       # stage 6: YoY deltas + metric series from companyfacts
│   │   ├── interpret.py        # stage 7: LLM calls, JSON validation, quote-verbatim check
│   │   ├── narrate.py          # stage 8: chapter prose + citation resolution
│   │   ├── report.py           # stage 9: chapter assembly, HTML + CLI rendering (Jinja2)
│   │   └── prompts.py          # SYSTEM_JSON (stage 7) + SYSTEM_PROSE (stage 8) templates
│   ├── web/                    # v2 FastAPI web app
│   │   ├── app.py              # FastAPI app factory
│   │   ├── routes.py           # /, /report/{ticker}, /api/trigger|status/{ticker}
│   │   ├── templates/          # base, index (hero), report, report_index, not_found
│   │   └── static/             # css/tokens.css (DESIGN.md → CSS vars) + img/delta.png
│   └── eval/                   # v1 eval set builders (unchanged)
└── tests/                      # 9 modules, 180 tests
    ├── test_anchors.py         # v1
    ├── test_scoring.py         # v1
    ├── test_align.py           # v2
    ├── test_diff.py            # v2
    ├── test_xbrl_delta.py      # v2
    ├── test_interpret.py       # v2
    ├── test_narrate.py         # v2
    └── test_report.py          # v2
```

## v2 Delta pipeline (9 stages)

```
fetch (5 yrs) → parse + anchor → align sections (anchor equality)
    → align paragraphs (embeddings) → deterministic diff classification
    → numeric guard (rescues value-only changes cosine calls "unchanged")
    → XBRL numeric deltas joined → LLM interpretation (changed pairs only)
    → narrative composition (chapters, stage 8) → report render
```

**Stage 8 (`delta/narrate.py`) is the readability layer** — one LLM call per
chapter over that chapter's material/notable interpretations, producing 600–900
words of analyst prose. The deliverable is the *report a human reads*, not the
diff; the diff is the evidence layer beneath it. Traceability survives the prose
via short evidence labels (`E1`, `E7`) that `resolve_citations()` renumbers into
`<sup>` links in the chapter's evidence drawer, silently dropping any label not
in the pool. Chapters are **data, not template logic** (`config.py:REPORT_CHAPTERS`).

The **numeric guard** (`diff.py:numeric_change_signal` + `xbrl_change_signal`) fixes
cosine's numeric-blindness: it runs only on `unchanged` records and upgrades any with
a ≥20% numeric move (text) or a moved audited financial-section XBRL tag. XBRL deltas
are computed before the diff loop; upgrades carry a `numeric_guard` field. See
`docs/working_knowledge.md`.

**Core principle: the LLM never finds the diff; it only explains it.** Detection is
deterministic Python. Interpretation is the only generative step, on small pre-verified
change sets. Every LLM claim traces to a diff record with verbatim quotes from both years.

## v2 chunking fixes (phase 00 — mandatory)

1. **HTML cleaning:** strip `ix:hidden`, `ix:resources`, `ix:header` from DOM + text-level
   noise filter. Current chunks contain XBRL metadata garbage (1,924 us-gaap tags, 625 entity IDs).
2. **Size fix:** `SA_MAX_TOKENS` 800→500, `SA_TARGET_TOKENS` 600→350. Embedding models cap at
   512 tokens; 38% of v1 chunks were silently truncated.
3. **Paragraph bridge:** `split_into_paragraphs()` in `delta/align.py`. Delta works at paragraph
   level (50-200 tok), not chunk level. The chunk is just storage.

## v2 file naming (IMPORTANT)

- Raw: `{ticker}_FY{yyyy}_10k.html` (was `{ticker}_10k.html`)
- Chunks: `{ticker}_FY{yyyy}_sectionaware.json` (was `{ticker}_sectionaware.json`)
- Diffs: `data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl`
- Interpretations (stage 7, expensive): `data/diffs/{ticker}/_interpretations.jsonl`
- Composed narrative (stage 8): `data/diffs/{ticker}/_narrative.json`
- Reports: `data/reports/{ticker}.html`

## Deploy (Fly.io, static) — `make deploy`

Full procedure in `docs/DEPLOY.md`; gotchas in `docs/working_knowledge.md`. The essentials:

Reports are built **offline** and baked into the image. The deployed app serves
pre-built HTML and has **no live generation path** — `/api/trigger` returns `501`,
and the image carries no pipeline deps. Adding a ticker means running the pipeline
locally and redeploying. Fly builds remotely, so no local Docker daemon is needed
(Docker Desktop's WSL integration is off on this machine anyway).

Two things to not break:

1. **`config.py` must stay import-light** (`os` + `dotenv` only).
   `requirements-web.txt` is sized to it — fastapi, uvicorn, jinja2,
   python-dotenv. If the `web.app` → `config` import chain reaches torch or
   chromadb, the container dies on boot while `make web` stays green, because
   `make web` runs against the full dev env. Verify with a throwaway venv built
   from `requirements-web.txt` alone (see `docs/DEPLOY.md`).
2. **The `fly.toml` cost invariant.** Fly has no free tier but doesn't collect
   invoices under $5/mo. `[[vm]]` is pinned to `shared-cpu-1x`/`256mb`
   (~$2.02/mo always-on) to stay under it; the `fly launch` default of 1GB is
   $5.92/mo and gets billed in full. Never attach a volume/Postgres/Redis —
   those bill regardless of machine state.

`make deploy` runs `rerender-all` first because reports live in the image and a
stale `data/reports/` would ship a stale site.

## Generation model & agent

The generation model is in `.opencode/opencode.json` (`model` field). The agent is `chatter`
(per `config.py:OPENCODE_AGENT`), a **system agent** — there is no local file for it.

`query.py:generate()`, `run_eval.py:call_llm()`, and `delta/interpret.py:call_llm()` all call
`opencode run --agent chatter <prompt>`. The default `build` agent has bash/read/write tools
and will try to call bash instead of answering — always specify `--agent chatter`.

For batch runs (v1 eval, v2 delta-batch), cold start per call is ~3-5s. Use
`opencode serve --port 4096` in a separate terminal, plus `OPENCODE_ATTACH=http://localhost:4096`
env var to cut per-call latency ~4x. Full details in `docs/working_knowledge.md`.

## SEC access

`src/config.py`: `USER_AGENT` (mandatory) and `SEC_RATE_LIMIT = 8` (req/sec).
SEC returns 403 without User-Agent; 429 above 10 req/sec. The throttle lives in
`fetch.py:_throttled_get`.

NVDA's "latest" 10-K is FY2026 (period_end 2026-01-25); v1 targets FY2025, so
`TICKER_10K_OFFSET = {"NVDA": 1}` fetches the prior 10-K. For v2 multi-year, the
offset is implicit in the submissions API accession list.

## v1 Eval set (56 questions) — retained as regression check

`src/eval/questions.jsonl` (regenerate with `python -m eval.build_questions`):

| Type | Count | Source | Route
|---|---|---|---|
| Numerical | 20 | XBRL auto-gen | corpus
| Factual | 10 | Semi-auto, human-verified | corpus
| Multihop | 8 | Hand (2 anchors each) | corpus
| Cross-filing | 8 | Hand | corpus
| Unanswerable | 6 | Hand | abstain
| Out-of-corpus | 4 | Hand | web

**Never LLM-label `gold_chunks`.** `gold_chunks` use anchor names (e.g. `income_statement`),
not chunk IDs, so every strategy shares one answer key.

## v1 Known results (baseline for regression)

| Config | Joint | Retrieval | Numeric | Route
|---|---|---|---|---|
| sectionaware + bge-small + rerank=off | 28/56 | 20/56 | 9/20 | 31/56
| sectionaware + e5-small + rerank=off | 27/56 | 18/56 | 13/20 | 36/56
| fixedsize + * (any config) | 9-10/56 | 0-1/56 | — | 28-32/56

Key regression: sectionaware + e5-small with rerank ON drops numeric_match from 13/20 → 6/20.
The reranker prefers MD&A prose over number-dense table chunks.

## The plan

`docs/delta_master_blueprint.md` is the design source of truth. `docs/plan/00-ARCHITECTURE.md` is
the build-ready spec. Phase files in `docs/plan/phase-XX-*.md` are the execution units. If
something here conflicts with the blueprint or architecture, those win. Re-read the blueprint
Part II (Delta stages 1-9, chunking fixes, data model invariants) and ARCHITECTURE §3 (contracts)
before changing the Delta pipeline, chunking, or evaluation.