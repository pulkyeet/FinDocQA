# FinDocQA — Progress Tracker

## v1 (COMPLETE) — RAG Eval Harness

### W1 (Linear pipeline)
- [x] Fetch SEC 10-Ks + companyfacts (7 tickers)
- [x] Chunk (fixedsize + sectionaware) with anchors
- [x] Embed (bge-small + e5-small) → 4 Chroma collections
- [x] Retrieve + generate with citations (query.py)

### W2 (Eval harness)
- [x] All 7 filings ingested (NVDA offset for FY2025)
- [x] Eval set: 56 questions (20 XBRL auto + 10 factual + 8 multihop + 8 cross-filing + 6 abstain + 4 web)
- [x] 8-config matrix (2 strategies × 2 models × rerank on/off) = 448 calls
- [x] Deterministic scoring: retrieval, routing, numeric_match, joint
- [x] Headline: fixedsize 9-10/56 vs sectionaware 24-28/56
- [x] Fixed joint scoring for abstain questions (Plan §8)

### W3 (Advanced eval) — COMPLETE
- [x] Web fallback (DuckDuckGo behind abstention gate, provenance tag)
- [x] Faithfulness judge (LLM 3x, majority + disagreement, gated behind FAITHFULNESS_JUDGE)
- [x] Failure taxonomy (7 buckets)
- [x] Streamlit dashboard (4-tab comparison view)
- [x] Cost/latency per config tracked

### W4 (Polish & narrative)
- [x] README + regression narrative
- [x] Joint scoring fix for abstain questions
- [ ] MCP wrapper — Droppable

## v2 (Delta) — Filing Change Intelligence

### Phase 00 — Walking skeleton  ✅
- [x] `src/config.py` — v2 constants (DELTA_* paths, thresholds, chunk size fix)
- [x] `src/chunk.py` — HTML cleaning (strip XBRL metadata), size fix (500 tok), year-suffixed naming
- [x] `src/fetch.py` — `fiscal_year_label()`, `find_n_recent_10ks()`, `fetch_10k_html_for_year()`
- [x] `src/delta/__init__.py`, `align.py`, `diff.py` — minimal stage 3-5
- [x] `src/delta.py` — CLI: `python delta.py AAPL --years 2 --no-llm`
- [x] `tests/test_align.py`, `tests/test_diff.py`
- [x] Rename existing FY2025 files to year-suffixed naming
- [x] Update `embed.py:load_chunks` for new naming

### Phase 01 — Multi-year corpus  ✅
- [x] `fetch.py --years 5` for all 7 tickers (3×3 narrow start, then 7×5)
- [x] `chunk.py` hardening: keyword-based heading detection, table-cell heading extraction, split-header handling (MSFT), AMZN TOC detection, anchor fallback mapping
- [x] Anchor coverage assertions (`item1a_risk`, `item7_mdna`, `item8_financials`)
- [x] Full corpus: 30 filings fetched + chunked (GOOGL 3 yrs, META 2 yrs due to CIK history)
- [x] `test_align.py` — multi-year anchor alignment test
- [x] Chunk size ≤ 2000 chars verified across all 30 files; XBRL noise eliminated

### Phase 02 — Diff engine (full)  ✅
- [x] `align.py` — full greedy paragraph matching, Hungarian fallback added (not wired)
- [x] `diff.py` — classification, word deltas, churn score, `diff_all_sections`, `churn_summary`, `classification_counts`
- [x] 48-pair labeled sample (`data/eval/diff_labels.jsonl` + `diff_labels.md`) across 5 sections × 2 year pairs
- [x] `tune_thresholds.py` — grid search, held-out eval, sample generator
- [x] Tuned thresholds: unchanged=0.95, minor=0.81, major=0.60 (held-out F1=0.462)
- [x] Per-section progress prints in `diff_all_sections` (`[1/27] balance_sheet -> 0 changed`)

### Phase 03 — XBRL + interpretation  ✅
- [x] `xbrl_delta.py` — YoY metric deltas from companyfacts (10-K annual preference, multi-unit handling)
- [x] `prompts.py` — interpretation + synthesis prompt templates with JSON output example
- [x] `interpret.py` — LLM calls (OpenRouter API primary, opencode subprocess fallback), JSON parsing, quote-verbatim validation, one retry, batched prompts (BATCH_SIZE=5)
- [x] Trend synthesis per section (≥2 valid interpretations required)
- [x] `delta.py` full pipeline: fetch → chunk → align → diff → XBRL → interpret → synthesize → CLI summary
- [x] `--no-llm` flag preserved for fast diff-only runs
- [x] `tests/test_xbrl_delta.py` (11 tests)
- [x] Validation rate: 63/79 (80%) with OpenRouter; 100% on non-table sections

### Phase 04 — Report render  ✅
- [x] `tokens.css` — full DESIGN.md → CSS custom properties (colors, typography, spacing, rounded + all component classes)
- [x] `base.html` — Jinja2 base template with nav-bar, footer, Inter + SF Mono typography, dark canvas background
- [x] `report.html` — full report template: summary stats, XBRL metrics table, churn scores with bar visualization, material/notable/boilerplate changes with side-by-side quotes, section navigation, trend narratives, unvalidated flagging
- [x] `report.py` — `build_report_data()` assembles §2.6 report dict; `render_html()` Jinja2 rendering; `render_cli_summary()` terminal output; `write_report()` to disk; `write_interpretations()` / `load_interpretations()` persistence; `build_report_index()` static index page
- [x] `delta.py` — stage 9 integrated: report rendering + interpretation persistence + index generation after batch
- [x] `test_report.py` — 28 tests covering build_report_data, render_html, render_cli_summary, write/load interpretations, report index
- [x] `Makefile` — added `delta`, `delta-batch`, `delta-no-llm`, `web` targets
- [x] All 121 tests pass (93 pre-existing + 28 new)

### Phase 05 — Web app + deploy  ✅
- [x] `web/app.py` — FastAPI app factory with static files mount and Jinja2Templates
- [x] `web/routes.py` — `/` (hero index), `/report/{ticker}` (serve pre-built HTML or not-found page), `/api/trigger/{ticker}` (run delta pipeline async), `/api/status/{ticker}` (check report readiness)
- [x] `web/templates/index.html` — DESIGN.md hero page: eyebrow, headline (weight 400), body copy, code chip, ticker input form, 3-up how-it-works cards, Lazy Prices context
- [x] `web/templates/not_found.html` — graceful handling for unknown tickers (404) and not-yet-generated valid tickers (200)
- [x] `report.html` — verified serving pre-built HTML works (MSFT report with 146 changes, XBRL metrics, churn bars, material/notable changes, side-by-side quotes, trend narratives, boilerplate `<details>` toggles, unvalidated flags)
- [x] `interpret.py` — trend synthesis response cleaned (handles LLM JSON-wrapping with `_clean_trend_response`)
- [x] `requirements.txt` — added fastapi, uvicorn, jinja2
- [x] `Makefile` — `make web` target verified (`cd src && uvicorn web.app:app --reload --port 8000`)
- [x] `fly.toml` — Fly.io deployment config (internal_port 8000, Paketo buildpacks, SJC region)
- [x] `.dockerignore` — excludes raw/chunks/chroma/eval/diffs, keeps reports/
- [x] All 121 tests pass

### Numeric-blindness gap — RESOLVED ✅
The embedding similarity classifier was blind to numeric value changes: a paragraph
where only dollar amounts change (e.g. revenue $100M → $489M) scores cosine ~0.99
and was classified `unchanged` — the LLM never saw it.

**Fix shipped (Hybrid text + XBRL guard, deterministic).** Runs only on records
cosine calls `unchanged`, so it is orthogonal to the tuned thresholds (no
re-tuning risk). Every upgrade stamps an auditable `numeric_guard` reason.
- **Text guard (`diff.py:numeric_change_signal`):** reuses `scoring.extract_numbers`
  to compare numbers on both sides of a matched pair; a relative move ≥ 20%
  (`NUMERIC_GUARD_PCT`) upgrades `unchanged` → `modified_minor`, or
  `modified_major` for moves ≥ 100% (`NUMERIC_GUARD_MAJOR_PCT`). Works on every
  section (MD&A, risk factors, tables), paragraph-precise.
- **XBRL corroboration (`diff.py:xbrl_change_signal`):** on financial sections
  (`FINANCIAL_ANCHORS`), if an audited tag moved ≥ threshold but no paragraph got
  text-flagged, the most number-dense unchanged paragraph is surfaced (catches
  numbers that survive only in a mangled table cell).
- **Wiring:** `diff_section_pair`/`diff_all_sections` take `xbrl_deltas`; XBRL
  deltas are now computed *before* the diff loop in `delta.py` (also benefits
  `--no-llm`). Report joins `numeric_guard` onto interpretations by `change_id`
  and shows a `Δ NNN%` badge (`report.py` + `report.html`).
- **Verification:** 9 new tests in `test_diff.py` (130 total pass). On
  `MSFT --years 2 --no-llm`, the guard rescued **92** changes, **all** at cosine
  ≥ 0.95 (100% invisible before) — e.g. a balance-sheet lease line `1197 → 2349`
  at cosine 1.000.
- **Config:** `NUMERIC_GUARD_PCT=0.20`, `NUMERIC_GUARD_MIN_VALUE=1.0`,
  `NUMERIC_GUARD_MAJOR_PCT=1.00`, `FINANCIAL_ANCHORS` in `config.py`.

## Env & config tweaks (incidental)
- [x] `.opencode/opencode.json` — model config
- [x] `.opencode/agent/chatter.md` — deleted; `paid-chatter` used instead
- [x] `config.py:OPENCODE_AGENT` — `"paid-chatter"` (system agent, no local file)
- [x] `config.py` — OpenRouter constants (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`)
- [x] `src/.env` — `HF_TOKEN` + `OPENROUTER_API_KEY` (user-provided)
- [x] `interpret.py` — `call_llm` branches on `OPENROUTER_API_KEY` presence: OpenRouter HTTP API vs opencode subprocess fallback
- [x] `interpret.py` — model cache (`_model_cache`) in `align.py` to avoid repeated SentenceTransformer loads
