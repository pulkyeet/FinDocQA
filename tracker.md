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

### Phase 05 — Web app + deploy  🔜
- [ ] `web/app.py`, `routes.py` — FastAPI app
- [ ] `index.html` — hero + ticker input (primary DESIGN.md surface)
- [ ] Serve pre-built reports at `/report/{ticker}`
- [ ] `requirements.txt` — add fastapi, uvicorn, jinja2
- [ ] `fly.toml` — Fly.io deployment config
- [ ] Tier 1: deploy to Fly.io (~$5/mo)

### Future work — Numeric-blindness gap
The embedding similarity classifier is blind to numeric value changes. A paragraph
where only dollar amounts change (e.g. revenue $100M → $489M) scores cosine ~0.99
and is classified `unchanged` — the LLM never sees it.

**Planned fix (Option A — XBRL guard):** For financially-loaded sections
(`income_statement`, `balance_sheet`, `cash_flow`), after diff classification,
check XBRL deltas. If any mapped tag shows >20% YoY change, override
`unchanged` records to `modified_minor` so the LLM sees them.

## Env & config tweaks (incidental)
- [x] `.opencode/opencode.json` — model config
- [x] `.opencode/agent/chatter.md` — deleted; `paid-chatter` used instead
- [x] `config.py:OPENCODE_AGENT` — `"paid-chatter"` (system agent, no local file)
- [x] `config.py` — OpenRouter constants (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`)
- [x] `src/.env` — `HF_TOKEN` + `OPENROUTER_API_KEY` (user-provided)
- [x] `interpret.py` — `call_llm` branches on `OPENROUTER_API_KEY` presence: OpenRouter HTTP API vs opencode subprocess fallback
- [x] `interpret.py` — model cache (`_model_cache`) in `align.py` to avoid repeated SentenceTransformer loads
