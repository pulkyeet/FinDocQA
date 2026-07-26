# Phase 03 — XBRL + Interpretation

> **Stage 8 changed after this phase.** The per-section trend synthesis built here
> was superseded by per-*chapter* narrative composition (`delta/narrate.py`, phase
> 06) — correct but unreadable output: ~27 longitudinal paragraphs with no
> editorial hierarchy. Stage 6 (XBRL) and stage 7 (interpretation + verbatim quote
> validation) are unchanged and remain load-bearing.

## Objective

Add the XBRL numeric backbone (stage 6) and the LLM interpretation + trend
synthesis (stages 7-8). By the end, `python delta.py AAPL --years 5` produces
a complete report data structure: diff records + XBRL deltas + LLM
interpretations + trend narratives per section.

**Status: ✅ COMPLETE**

## What shipped vs what was planned

### LLM backend: OpenRouter replaces opencode subprocess

The original plan called for `opencode run --agent chatter` via subprocess.
In practice, subprocess overhead made the pipeline unbearably slow — 50+
process spawns per ticker, each taking 30-120s just for OS fork + model load.

**Actual implementation:** `call_llm()` in `interpret.py` branches on
`OPENROUTER_API_KEY`:
- Key present → HTTP POST to `openrouter.ai/api/v1/chat/completions`
  (2-5s per call, clean JSON response)
- No key → falls back to `opencode run --agent paid-chatter` subprocess

Default model: `deepseek/deepseek-v4-flash`. Cost: ~$0.02/ticker.

### Batched prompts + text truncation

Two regressions discovered during build:
1. **34-entry prompts produce malformed JSON.** When all changed records for
   a section are sent in one LLM call, the model skips entries, paraphrases
   quotes, and produces invalid JSON arrays.
2. **2000-char texts balloon prompts.** Financial table chunks with full
   table text exceed 10K tokens per batch.

**Fixes:**
- `BATCH_SIZE = 5` — each LLM call gets at most 5 change entries
- `old_text[:500]` / `new_text[:500]` truncation before prompt assembly
- Retry-per-batch: only failed interpretations in a batch get retried

### Validation rate

With OpenRouter + batched prompts + text truncation:
- **63/79 (80%)** overall validated
- **100%** on prose sections (item1a_risk, item7_mdna, item1_business)
- Lower on financial tables (item8_financials: 33/34) — the model struggles
  with verbatim quoting from dense table text

## Resolved gap: numeric-blindness ✅

The cosine-similarity classifier was blind to numeric value changes: a paragraph
where only dollar amounts change (e.g. revenue $100M → $489M) scores ~0.99 and
was classified `unchanged` — the LLM never saw it.

**Fixed (Hybrid text + XBRL numeric guard).** A deterministic guard in `diff.py`
runs only on records cosine calls `unchanged`. A text guard
(`numeric_change_signal`, reusing `scoring.extract_numbers`) upgrades any pair with
a ≥20% relative numeric move; XBRL corroboration (`xbrl_change_signal`) surfaces the
most number-dense paragraph when an audited financial-section tag moved but text
didn't catch it. XBRL deltas are now computed before the diff loop and threaded
through `diff_section_pair`/`diff_all_sections`. See `../tracker.md` for details.

## Deliverables

### 1. `src/delta/xbrl_delta.py` ✅
- `load_companyfacts(ticker)` — load companyfacts JSON
- `get_xbrl_values(companyfacts, tag)` — extract filed values, derive FY from `end`
- `fiscal_year_value(values, fiscal_year)` — prefers 10-K (annual) entries over quarterly
- `compute_yoy_deltas(companyfacts, tags, year_range)` — structured YoY deltas with pct_change
- `deltas_for_section(xbrl_deltas, anchor)` — filter by XBRL_TAG_TO_ANCHOR
- `format_xbrl_context(deltas)` — human-readable text for LLM prompt

### 2. `src/delta/prompts.py` ✅
- `INTERPRETATION_PROMPT` — with explicit JSON output example and quote precision rules
- `SYNTHESIS_PROMPT` — longitudinal narrative template

### 3. `src/delta/interpret.py` ✅
- `call_llm(prompt, timeout=60)` — branches on OpenRouter vs opencode
- `_call_openrouter(prompt, timeout)` — HTTP POST to OpenRouter, system prompt for precision
- `_call_opencode(prompt, timeout)` — subprocess fallback with `Popen` + timeout kill
- `validate_interpretation(record, diff_record)` — change_id, quote-verbatim, enum checks
- `interpret_section_pair(...)` — batch → prompt → validate → retry per batch
- `synthesize_trend(...)` — one LLM call per section with all validated interpretations
- `_parse_json_from_response(response)` — JSON extraction with markdown block and regex fallback

### 4. `src/delta.py` — full pipeline ✅
- Full pipeline: fetch → chunk → align → diff → XBRL → interpret → synthesize → CLI summary
- `--no-llm` flag preserved for fast diff-only runs
- Per-section progress prints at every stage

### 5. `tests/test_xbrl_delta.py` ✅
- 9 tests covering all xbrl_delta functions with real AAPL companyfacts data

## Constraints status

| Constraint | Status |
|---|---|
| Do not modify contracts in 00-ARCHITECTURE.md | ✅ respected |
| Do not implement report rendering or web app | ✅ out of scope |
| Do not change anchor vocabulary or scoring.py | ✅ unchanged |
| LLM never sees unchanged diff records | ✅ filtered in `interpret_section_pair` |
| Quote-verbatim check with retry | ✅ implemented, 80% validation rate |
| XBRL numbers from companyfacts, not prose | ✅ structured data only |
| Agent must be no-tools (not `build`) | ✅ `paid-chatter` (system agent, no tools) |

## Acceptance

1. ✅ `python delta.py AAPL --years 2` runs full pipeline → CLI summary with churn + material changes
2. ✅ CLI lists material changes with summary, why_it_matters, and verbatim quotes
3. ✅ Quote-verbatim validation (80% pass; failures flagged `[unvalidated]`)
4. ✅ XBRL deltas for ResearchAndDevelopmentExpense, NetIncomeLoss, and 13 other tags
5. ✅ Trend narratives for 6 sections
6. ✅ All 100 tests pass (including test_xbrl_delta.py)
7. ✅ `--no-llm` still works (returns diff records + churn, no LLM calls)
