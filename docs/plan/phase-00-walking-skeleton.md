# Phase 00 — Walking Skeleton

## Objective
Create the thinnest end-to-end Delta slice: fetch 2 years of 1 ticker, chunk with the fixed chunker, align sections by anchor, align paragraphs by embedding, classify diffs, print churn scores to CLI. No LLM, no XBRL, no report render. Proves the pipeline shape works before scaling.

## Context
Read first:
- `delta_master_blueprint.md` Part II (stages 1-5, chunking fixes)
- `docs/plan/00-ARCHITECTURE.md` §2 (data model), §3.1-3.5 (config, fetch, chunk, align, diff contracts)
- `src/chunk.py` (current section-aware chunker — you're modifying this)
- `src/embed.py` (`doc_prefix`, `query_prefix`, `collection_name` — reused by align.py)
- `src/config.py` (you're extending this)

## Deliverables

### 1. `src/config.py` (modify — add v2 constants)
Add the constants listed in ARCHITECTURE §3.1 under "New (v2)": `DELTA_YEARS_DEFAULT`, `DELTA_YEARS_MAX`, `DELTA_DIFFS_DIR`, `DELTA_REPORTS_DIR`, diff thresholds, alignment floor, chunk size fix (`SA_TARGET_TOKENS=350`, `SA_MAX_TOKENS=500`), `XBRL_DELTA_TAGS`. Import `SA_TARGET_TOKENS`/`SA_MAX_TOKENS` from config in `chunk.py` instead of hardcoding.

### 2. `src/chunk.py` (modify — 3 fixes)
**Fix A — HTML cleaning:** In `chunk_sectionaware()` and `html_to_text()`, add XBRL metadata elements to the DOM strip list:
```python
for tag in soup(["script", "style", "ix:hidden", "ix:resources", "ix:header"]):
    tag.decompose()
```
Add `_strip_xbrl_noise(text)` function using `XBRL_NOISE_PATTERNS` (see ARCHITECTURE §3.3). Call it after `get_text()` in both `html_to_text()` and the segment extraction in `chunk_sectionaware()`.

**Fix B — Size:** Replace hardcoded `SA_TARGET_TOKENS=600`/`SA_MAX_TOKENS=800` with imports from `config.py` (350/500). Update `SA_TARGET_CHARS` and `SA_MAX_CHARS` accordingly.

**Fix C — File naming:** Change output path from `{ticker}_{strategy}.json` to `{ticker}_{fy}_{strategy}.json` where `fy` comes from the 10-K meta's `period_end` via `fiscal_year_label()`. Import `fiscal_year_label` from `fetch.py`.

### 3. `src/fetch.py` (modify — minimal multi-year)
Add `fiscal_year_label(period_end: str) -> str` (extract 4-digit year from period_end date string, return `"FY{year}"`).

Add `find_n_recent_10ks(ticker, cik, n) -> list[dict]`: use the submissions API (already called in `find_latest_10k`), filter `form == "10-K"`, take first N, return list of `{accession_no, doc_filename, period_end, entity_name, fiscal_year}`.

Add `fetch_10k_html_for_year(ticker, cik, accession_no, doc_filename, period_end, entity_name, fiscal_year) -> (path, meta)`: same as `fetch_10k_html` but with year-suffixed file naming (`{ticker}_{fy}_10k.html`).

Update `__main__` to accept `--years N` and `--tickers` args. Default: years=1 (v1 behavior), all tickers.

### 4. `src/delta/__init__.py` (new — empty package marker)

### 5. `src/delta/align.py` (new — stages 3-4, minimal)
Implement per ARCHITECTURE §3.4:
- `split_into_paragraphs(text) -> list[str]`: split on `\n\n`, strip whitespace, filter empty.
- `load_chunks_for_year(ticker, fiscal_year, strategy) -> list[dict]`: load `{ticker}_{fy}_{strategy}.json`.
- `group_by_anchor(chunks) -> dict[str, list[dict]]`.
- `align_sections(old_chunks, new_chunks) -> list[tuple]`: pair by anchor set intersection. Flag structural add/remove.
- `embed_paragraphs(paragraphs, model_key) -> np.ndarray`: use `SentenceTransformer` with `doc_prefix(model_key)`.
- `match_paragraphs(old_paras, new_paras, old_embs, new_embs, similarity_floor) -> dict`: greedy best-match. Sort all pairwise cosines desc, assign without reuse, below floor = unmatched.
- `align_section_pair(old_chunks, new_chunks, model_key) -> dict`: reconstruct section text from chunks, split into paragraphs, embed, match.

### 6. `src/delta/diff.py` (new — stage 5, minimal)
Implement per ARCHITECTURE §3.5:
- `classify_pair(similarity) -> str`: use thresholds from config.
- `word_delta(old_text, new_text) -> dict`: `difflib.ndiff` on word lists.
- `make_diff_record(...) -> dict`: per schema §2.3.
- `compute_churn_score(paras, classifications) -> float`: weighted by paragraph length.
- `diff_section_pair(alignment, ticker, anchor, year_pair) -> list[dict]`.
- `write_diff_records(records, ticker, year_pair)`: write to `data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl`.

### 7. `src/delta.py` (new — CLI entrypoint, minimal)
```python
# python delta.py AAPL --years 2 --no-llm
# 1. fetch 2 years (AAPL FY2024, FY2025)
# 2. chunk each year
# 3. for the year pair:
#    a. align sections (anchor equality)
#    b. for each section pair: align paragraphs, diff classify
#    c. write diff records
# 4. print churn scores per section to CLI
```

### 8. `tests/test_align.py` (new)
Test `split_into_paragraphs` (multi-paragraph, empty, single), `group_by_anchor`, `align_sections` (matching, structural add, structural remove), `match_paragraphs` (greedy assignment, floor cutoff).

### 9. `tests/test_diff.py` (new)
Test `classify_pair` at boundary values (0.94, 0.95, 0.80, 0.79, 0.60, 0.59), `word_delta` (additions, removals, both), `compute_churn_score` (all unchanged = 0, all changed = 1.0).

### 10. Rename existing FY2025 files
Rename `data/raw/{ticker}_10k.html` → `{ticker}_FY2025_10k.html` (and meta). Rename `data/chunks/{ticker}_sectionaware.json` → `{ticker}_FY2025_sectionaware.json` (and fixedsize). Update `embed.py:load_chunks` to glob `{ticker}_FY*_{strategy}.json` and load the latest FY.

## Constraints
- Do not modify contracts defined in 00-ARCHITECTURE.md. If a contract cannot be implemented as specified, stop and report.
- Do not implement LLM calls, XBRL deltas, report rendering, or web app — those are phases 03-05.
- Do not touch `anchors.py`, `scoring.py`, `query.py`, `run_eval.py`, `rerank.py`, `web_search.py`, `dashboard.py`, `eval/`.
- Do not change the anchor vocabulary.
- Keep `embed.py`'s public API stable (`doc_prefix`, `query_prefix`, `collection_name` unchanged).

## Acceptance
1. `cd src && python delta.py AAPL --years 2 --no-llm` runs without error and prints churn scores for at least 5 sections.
2. `data/diffs/AAPL/FY2024_FY2025.jsonl` exists and contains valid JSON records with the schema from ARCHITECTURE §2.3.
3. `data/raw/AAPL_FY2024_10k.html` and `data/raw/AAPL_FY2025_10k.html` both exist.
4. `data/chunks/AAPL_FY2024_sectionaware.json` and `AAPL_FY2025_sectionaware.json` both exist.
5. No chunk in either file exceeds 500 tokens (2000 chars). Verify: `python -c "import json; c=json.load(open('data/chunks/AAPL_FY2025_sectionaware.json')); print(max(len(x['text']) for x in c))"` → ≤ 2000.
6. No XBRL metadata garbage in chunk text. Verify: grep for `us-gaap:` in chunk files → 0 matches.
7. `cd src && python -m unittest discover -s ../tests -v` passes (including new test_align.py, test_diff.py).
8. Anchor coverage: `item1a_risk` and `item7_mdna` both present in AAPL FY2024 and FY2025 chunk anchors.

## Out of scope
- 7 tickers × 5 years (phase 01)
- Threshold tuning / 50-pair labeled sample (phase 02)
- XBRL delta join (phase 03)
- LLM interpretation (phase 03)
- Report rendering (phase 04)
- Web app (phase 05)
- Chunker hardening for pre-2022 formats (phase 01)