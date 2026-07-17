# Phase 01 — Multi-Year Corpus

## Objective
Scale the fetcher from 2 years of 1 ticker to 5 years of all 7 tickers. Harden the chunker for older filing formats (FY2021-2023) where EDGAR HTML formatting drifts. Add anchor-coverage assertions that fail loudly when a critical anchor doesn't resolve.

## Context
Read first:
- `docs/plan/00-ARCHITECTURE.md` §3.2 (fetch contracts), §3.3 (chunk contracts)
- `docs/plan/phase-00-walking-skeleton.md` (you built the minimal fetch + chunk here)
- `src/fetch.py` (you extended this in phase 00)
- `src/chunk.py` (you fixed HTML cleaning + size in phase 00)
- `src/anchors.py` (the anchor vocabulary — unchanged, but you're asserting coverage)

## Deliverables

### 1. `src/fetch.py` (modify — full multi-year)
- `find_n_recent_10ks(ticker, cik, n)`: already implemented in phase 00. Verify it handles edge cases: fewer than N 10-Ks available (return what exists, warn), NVDA fiscal offset (the `TICKER_10K_OFFSET` may need extension for multi-year — NVDA's offset applies to the "latest" 10-K only; for historical, the offset is implicit in the accession list).
- `fetch_10k_html_for_year()`: already implemented in phase 00. Add retry logic for older filings that may have different URL patterns.
- Update `__main__` CLI: `python fetch.py --years 5` fetches all 7 tickers × 5 years. `--years 5 --tickers AAPL,MSFT,NVDA` for the 3×3 narrow start.
- Add a `fetch_all_for_delta(tickers, years)` function that loops: for each ticker, get N recent 10-Ks, fetch each, skip if cached.

### 2. `src/chunk.py` (modify — hardening for older formats)
- Test the chunker on FY2021-2023 filings. Older 10-Ks may have:
  - Different HTML structure (older inline-XBRL versions, or non-inline-XBRL)
  - Item headers in different formats (e.g., "ITEM 1A" vs "Item 1A", headers in `<b>` tags vs `<span>`)
  - Tables with different caption/sibling structures
- Harden `_is_item_header()` regex to handle case variations and tag wrapping.
- Harden `_find_table_caption()` to handle older DOM structures.
- If a filing's HTML is not inline-XBRL (no `ix:` elements), the chunker should still work — it just won't have XBRL metadata to strip.
- Add `_assert_anchor_coverage(chunks, ticker, fiscal_year)`: check that at least these critical anchors are present: `item1a_risk`, `item7_mdna`, `item8_financials`. If any missing, raise `RuntimeError` with a clear message: `"Anchor coverage failed for {ticker} {fy}: missing {anchor}. Parser may need hardening."` This is the "fail loudly at ingest" mitigation from the blueprint's risk section.

### 3. `src/delta.py` (modify — support all tickers)
- Update CLI to accept `--tickers` arg (comma-separated, default: all 7).
- Add `--years` arg (default: 5, max: 5 per `DELTA_YEARS_MAX`).

### 4. Run the full corpus build
```bash
cd src
python fetch.py --years 5 --tickers AAPL,MSFT,NVDA   # 3×3 narrow start
# Verify anchor coverage passes for all 9 filings
python chunk.py --strategy sectionaware              # chunk all fetched
# Verify: no chunk > 2000 chars, no XBRL noise, anchor coverage passes
python fetch.py --years 5                             # expand to 7×5
python chunk.py --strategy sectionaware
```

### 5. `tests/test_align.py` (modify — add multi-year test)
Add a test that loads 2 years of AAPL chunks, runs `align_sections`, and verifies all expected anchors are paired.

## Constraints
- Do not modify contracts defined in 00-ARCHITECTURE.md.
- Do not change the anchor vocabulary in `anchors.py`.
- Do not implement diff classification tuning, XBRL deltas, LLM, report, or web (phases 02-05).
- Do not touch `scoring.py`, `query.py`, `run_eval.py`, `rerank.py`, `web_search.py`, `dashboard.py`, `eval/`.
- If a pre-2022 filing's HTML format is fundamentally incompatible with the chunker (anchor coverage fails and can't be fixed with regex hardening), stop and report — do not silently skip the filing.

## Acceptance
1. `cd src && python fetch.py --years 5` fetches all 7 tickers × 5 years = 35 10-Ks. All cached in `data/raw/` with year-suffixed naming.
2. `cd src && python chunk.py --strategy sectionaware` chunks all 35 filings. All cached in `data/chunks/` with year-suffixed naming.
3. Anchor coverage assertion passes for all 35 filings: `item1a_risk`, `item7_mdna`, `item8_financials` present in every filing's chunk anchors.
4. No chunk exceeds 2000 chars (500 tokens). Verify across all 35 files.
5. No XBRL metadata garbage in any chunk. Verify: `grep -r "us-gaap:" data/chunks/` → 0 matches.
6. `cd src && python delta.py AAPL --years 5 --no-llm` runs and produces 4 year-pair diff files in `data/diffs/AAPL/`.
7. `cd src && python -m unittest discover -s ../tests -v` passes.

## Out of scope
- Threshold tuning / 50-pair labeled sample (phase 02)
- XBRL delta join (phase 03)
- LLM interpretation (phase 03)
- Report rendering (phase 04)
- Web app (phase 05)
- Re-embedding for v1 eval (v1 eval is a regression check, not a deliverable)