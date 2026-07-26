# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read these first

This repo carries dense project documentation. Before non-trivial work, read:

- **`working_knowledge.md`** — session bootstrap: operational habits, env setup, and every recurring gotcha (Chroma batch limit, E5 prefixes, v2 file naming, chunking fixes, quote validation, thresholds). The single most useful file.
- **`AGENTS.md`** — project config / agent notes (mirrors much of this file with more run detail).
- **`delta_master_blueprint.md`** — design source of truth (v1 + v2 merged). Wins over other docs on conflict.
- **`docs/plan/00-ARCHITECTURE.md`** + `docs/plan/phase-0X-*.md` — build-ready contracts, schemas, and per-phase execution units.
- **`DESIGN.md`** — UI design system (dark canvas, Voltagent-inspired) that the web report renders to.

Re-read the blueprint (Delta stages 1–9, data-model invariants) and ARCHITECTURE §3 (contracts) before changing the Delta pipeline, chunking, or evaluation.

## The two-part system

FinDocQA is two systems sharing one corpus and ingest layer:

1. **v1 — RAG eval harness (COMPLETE).** Deterministic eval suite over SEC 10-Ks that measures chunking × embedding × rerank configs. The credibility floor. The eval harness *is* the deliverable, not the chatbot. See README.md for the results narrative (fixedsize 9–10/56 vs sectionaware 24–28/56; the "rerank trap" numeric regression).
2. **v2 — Delta (the product).** Five-year YoY 10-K change-intelligence engine: deterministic diff + LLM interpretation, **composed into a readable ~15-min analyst report** and served by a FastAPI web app. The deliverable is the *report a human reads*, not the diff — the diff is the evidence layer beneath it. The product is branded **Delta** (never "FinDocQA" in any user-facing surface).

## Commands

All Python scripts use **relative paths** and data lives in `src/data/`, so **`cd src` before running** any script directly. The `Makefile` (repo root) does the `cd` for you.

```bash
# ── v2 Delta (the product) ──
cd src
python delta.py AAPL --years 5            # full pipeline: fetch→chunk→align→diff→XBRL→interpret→narrate→report
python delta.py AAPL --years 5 --no-llm   # diff-only: fast, deterministic, no LLM calls (prefer for pipeline checks)
python delta.py --all --years 5           # batch all 7 tickers
# from repo root:
make delta / make delta-batch / make delta-no-llm   # TICKER=AAPL YEARS=5 overridable
make web                                  # FastAPI report server at localhost:8000
make rerender / make rerender-all         # re-render HTML from persisted output — NO LLM calls (template/CSS changes)
make narrate  / make narrate-all          # recompose chapter prose (~6 LLM calls/ticker), then render (prompt changes)

# ── v1 eval harness ──
cd src
python fetch.py                           # SEC 10-Ks + companyfacts (cached by file existence)
python chunk.py                           # 2 strategies → data/chunks/
python embed.py                           # 2 models × 2 strategies → 4 Chroma collections
python -m eval.build_questions            # rebuild data/eval/questions.jsonl (56 questions)
python query.py "..." --strategy sectionaware --model e5-small --rerank on
# from repo root:
make fetch / make chunk / make embed / make eval   # eval = 56 q × 8 configs = 448 LLM calls
streamlit run src/dashboard.py            # 4-tab config comparison

# ── tests ──
make test                                 # cd src && PYTHONPATH=. python3 -m unittest discover -s ../tests -v
cd src && PYTHONPATH=. python3 -m unittest tests.test_diff -v   # single module (run from src)
```

Python 3.11.9. Deps in `requirements.txt`. Secrets in `src/.env`: `OPENROUTER_API_KEY`, `HF_TOKEN` (and optional `OPENROUTER_MODEL`, `SEC_USER_AGENT`, `OPENCODE_ATTACH`, `FAITHFULNESS_JUDGE`).

## Architecture — the core principles

**Detection is deterministic; only interpretation is generative.** In Delta the LLM never *finds* a diff — Python does, via embedding-cosine classification. The LLM only *explains* pre-verified change pairs, and every claim traces to a diff record with verbatim quotes from both years. This is the whole thesis; do not let the LLM into the detection path.

**Anchors are the alignment primitive.** `anchors.py` defines a stable semantic vocabulary (`income_statement`, `item7_mdna`, `item1a_risk`, …). In v1, `gold_chunks` are anchor names (never chunk IDs), so all 8 configs share one answer key — **never LLM-label gold_chunks**. In v2, sections align by anchor *equality* across years, then paragraphs align by embeddings within a section.

**The generation model is frozen** so every v1 metric change is attributable to a chunking/embedding/rerank toggle, not the LLM. v2 LLM backend branches in `interpret.py:call_llm()`: OpenRouter HTTP API when `OPENROUTER_API_KEY` is set (primary), else `opencode run --agent paid-chatter` subprocess fallback (`paid-chatter` is a no-tools agent — never `build`).

### v2 Delta pipeline (9 stages, `src/delta/`)

```
fetch (N yrs) → parse+anchor → align sections (anchor eq) → align paragraphs (embeddings)
  → deterministic diff classify → XBRL numeric deltas → LLM interpret (changed pairs only)
  → narrative composition (chapters) → report render
```

- `delta.py` — CLI entrypoint / stage orchestration
- `align.py` — section + paragraph alignment; `split_into_paragraphs()` (Delta works at paragraph level, not chunk level); caches the SentenceTransformer model (loading per-section made the pipeline appear to hang)
- `diff.py` — cosine classification into unchanged / modified_minor / modified_major, word deltas, churn score
- `xbrl_delta.py` — `compute_yoy_deltas()` (year-*pair* keyed, drives the numeric guard) + `build_metric_series()` (year keyed, drives the report's financial tables: every year's absolute value with its YoY % in brackets)
- `interpret.py` — stage 7 only. Batched LLM calls (`BATCH_SIZE=5`), JSON parse + **verbatim quote validation** (each `old_quote`/`new_quote` must be a literal substring of the diff record; failure → one retry → flagged `_unvalidated` and **excluded from the report prose entirely**). `call_llm()` takes `system=` — `SYSTEM_JSON` for stage 7, `SYSTEM_PROSE` for stage 8; sending the JSON system prompt to the narrative stage visibly degrades it.
- `narrate.py` — **stage 8, the readability layer.** One LLM call per chapter over that chapter's material/notable interpretations, producing 600–900 words of analyst prose. Traceability survives the prose via short evidence labels (`E1`, `E2`…) the narrator cites as `[E7]`; `resolve_citations()` renumbers them by first appearance, renders `<sup>` links into the chapter's evidence drawer, and **silently drops any label not in the pool** — the same fail-safe as an unvalidated quote. HTML-escape happens *before* citation substitution so model-emitted markup can never become live HTML.
- `report.py` + `prompts.py` — chapter assembly, financial tables, change statistics, Jinja2 HTML render (to DESIGN.md spec), CLI summary, and persistence of both interpretations and composed narrative.

**Diff thresholds** (tuned, in `config.py`): unchanged ≥ 0.95, minor ≥ 0.81, major ≥ 0.60. High recall is intentional — over-flag and let the LLM downgrade to boilerplate rather than miss changes.

**Numeric guard (fixes numeric-blindness):** cosine alone is blind to value-only changes (revenue $100M→$489M scores ~0.99 → would be `unchanged`). A deterministic guard in `diff.py` runs *only* on `unchanged` records and upgrades them — `numeric_change_signal` (text, reuses `scoring.extract_numbers`, ≥20% moves) plus `xbrl_change_signal` (corroborates audited financial-section tags). XBRL deltas are computed before the diff loop and threaded through `diff_section_pair`/`diff_all_sections`; upgraded records carry a `numeric_guard` field surfaced as a `Δ NNN%` badge. Orthogonal to the tuned thresholds. Config: `NUMERIC_GUARD_*`, `FINANCIAL_ANCHORS`.

### Report structure (what the reader actually gets)

Chapters are **data, not template logic** — `REPORT_CHAPTERS` in `config.py` maps chapter → anchor list, so re-cutting the report is a config edit. Order: Executive Summary → Financial Performance (narrative + three XBRL tables) → The Business → Risk Landscape → Management's Discussion → Legal & Regulatory → *What the Engine Found* (classification counts + section churn) → Methodology (~500 words).

Deliberately **not** in the report: per-paragraph change cards, materiality pills, per-change churn, and the ~15 thin anchors (Properties, Exhibits, Compensation…) that carry no surfaced change. Anchors absent from every chapter are dropped, not rendered empty.

- **Churn survives at section level only** (user decision). `CHURN_MIN_RECORDS` (8) hides stub sections — a section with one paragraph per year scores a meaningless 1.00 and crowds out real signal.
- `FINANCIALS_NARRATIVE_ANCHORS` folds material Item 8 / statement changes into the Financial Performance chapter. Empty list = variant B. A/B via `rerender.py --no-item8 --suffix _variantB`.
- Read time = narrative words ÷ `WORDS_PER_MINUTE` (220). Length knob is `NARRATIVE_MIN_WORDS` / `NARRATIVE_MAX_WORDS`.

### v2 web app (`src/web/`, FastAPI)

`app.py` app factory; `routes.py`: `/` (hero), `/report/{ticker}` (serves pre-built `data/reports/{ticker}.html` or a not-found page), `/api/trigger/{ticker}` + `/api/status/{ticker}`. `/static` and `/reports` are mounted directly — the latter so A/B variant filenames are reachable without a route each. Reports are generated offline by `delta.py` and served as static HTML — the web app does not run the pipeline synchronously on request.

Templates extend `base.html` (nav + footer carry the `delta.png` mark). `report_index.html` builds `data/reports/index.html`.

### Deploy (Fly.io, `make deploy`)

`Dockerfile` builds a slim image from `requirements-web.txt` (fastapi, uvicorn, jinja2, python-dotenv — **no torch/chromadb**; `config.py` only needs `os` + `dotenv`, which is what keeps the runtime dep set this small). `src/` and the pre-built `data/reports/*.html` are baked in; `.dockerignore` drops raw/chunks/chroma/eval/diffs and the `_variant*` A/B reports (`/reports` is a public mount, so anything shipped is fetchable). Fly builds remotely — **no local Docker daemon needed**.

`make deploy` runs `rerender-all` first: reports live in the image, so a stale `data/reports/` ships a stale site. Adding a ticker means re-running the pipeline, then redeploying — there is no live generation path in the deployed app by design.

**Cost invariant — do not change without reading this.** Fly has no free tier but does not collect invoices under $5/mo. `fly.toml` pins `[[vm]]` to `shared-cpu-1x` / `256mb` (~$2.02/mo always-on) which stays under that line; the `fly launch` default of 1GB is $5.92/mo and *would* be billed in full. `min_machines_running = 1` with `auto_stop_machines = false` is deliberate — always-on is free at this size and avoids a cold start on the first visit. Never attach a volume or Postgres: those bill regardless of machine state.

## File naming (v2, year-suffixed — IMPORTANT)

- Raw: `data/raw/{ticker}_FY{yyyy}_10k.html`
- Chunks: `data/chunks/{ticker}_FY{yyyy}_sectionaware.json`
- Diffs: `data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl`
- Interpretations (stage 7 output, expensive — hundreds of LLM calls): `data/diffs/{ticker}/_interpretations.jsonl`
- Composed narrative (stage 8 output): `data/diffs/{ticker}/_narrative.json`
- Reports: `data/reports/{ticker}.html`

Both stage-7 and stage-8 output are persisted so `rerender.py` can rebuild the HTML without re-running either. **Never re-run the full pipeline to check a template change** — `make rerender` costs nothing.

Fiscal-year label comes from `fetch.py:fiscal_year_label(period_end)` (e.g. `2025-09-27` → `FY2025`).

## Data layer

`src/data/` is entirely gitignored (raw, chunks, chroma, eval results, diffs, reports). Re-running the scripts rebuilds it: raw fetches are cached by file existence; chunk/embed/delta always overwrite. **The raw layer is the single source of truth for reproducibility — never hand-edit a 10-K.** A missing `data/raw/` means you must `fetch` before anything else works.

## When verifying a change

Prefer the cheapest check first: `--no-llm` diff-only (deterministic, no LLM) → v1 retrieval-only → full `delta.py` with LLM (~1–2 min/ticker, only when generated interpretations are explicitly wanted). Anchor coverage is asserted at ingest — the chunker raises `RuntimeError` if `item1a_risk`, `item7_mdna`, or `item8_financials` fails to resolve, so alignment never silently drifts.
