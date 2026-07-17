# Phase 03 — XBRL + Interpretation

## Objective
Add the XBRL numeric backbone (stage 6) and the LLM interpretation + trend synthesis (stages 7-8). By the end, `python delta.py AAPL --years 5` produces a complete report data structure: diff records + XBRL deltas + LLM interpretations + trend narratives per section.

## Context
Read first:
- `docs/plan/00-ARCHITECTURE.md` §3.6 (xbrl_delta), §3.7 (interpret), §2.4 (interpretation record schema)
- `delta_master_blueprint.md` Part II stages 6-8, interpretation prompt (§5.5), data model invariants
- `src/scoring.py` (`extract_numbers`, `numeric_match` — the numeric normalization reused by xbrl_delta)
- `src/anchors.py` (`XBRL_TAG_TO_ANCHOR` — maps XBRL tags to section anchors)
- `src/query.py` (`generate()` function — the opencode call pattern to reuse)
- `src/run_eval.py` (`call_llm()` — the batch LLM call pattern with timeout/error handling)
- `src/delta/diff.py` (your phase 02 output — the diff records you're interpreting)

## Deliverables

### 1. `src/delta/xbrl_delta.py` (new — stage 6)
Implement per ARCHITECTURE §3.6:
- `load_companyfacts(ticker) -> dict`: load `{ticker}_companyfacts.json`.
- `get_xbrl_values(companyfacts, tag, concept_type="us-gaap") -> list[dict]`: extract all filed values for a tag from the companyfacts JSON structure. The companyfacts format: `data["facts"]["us-gaap"]["{tag}"]["units"]["USD"][{value, end, start, ...}]`. Return list of `{end, val, unit, fy}` where `fy` is derived from `end` via `fiscal_year_label()`.
- `fiscal_year_value(values, fiscal_year) -> float | None`: find the value whose `fy` matches. Handle fiscal year alignment (a company's FY2025 may end 2025-09-27 or 2025-06-30 — match by the FY label, not exact date).
- `compute_yoy_deltas(companyfacts, tags, year_range) -> dict`: for each tag, get the value for each year in the range, compute YoY deltas. Return `{tag: {"FY2024-FY2025": {old, new, abs_change, pct_change}}}`. `pct_change = (new - old) / abs(old) * 100` (guard division by zero).
- `deltas_for_section(xbrl_deltas, anchor) -> dict`: filter to tags whose `XBRL_TAG_TO_ANCHOR` maps to the given anchor. Used to attach relevant numeric context to a section's interpretation prompt.

### 2. `src/delta/prompts.py` (new — prompt templates)
```python
INTERPRETATION_PROMPT = """You are analyzing changes in {ticker}'s 10-K, section {section_name},
FY{y1} vs FY{y2}. Below are passage pairs a deterministic diff engine flagged as changed,
plus whole-passage additions and removals. Numeric context from XBRL: {xbrl_deltas}.

For each change_id, output a JSON object:
- change_type: added | removed | expanded | softened | strengthened | reworded
- materiality: boilerplate | notable | material
- summary: one sentence stating what changed
- why_it_matters: one sentence, ONLY for notable/material; else null
- old_quote / new_quote: shortest exact excerpts evidencing the change
  (must be verbatim substrings of the provided text)

Rules:
- Judge ONLY from the provided text and XBRL context. Do not use outside
  knowledge of the company. Do not infer changes not shown.
- Date rolls, fiscal-period updates, repagination, and pure restyling are
  boilerplate.
- "Material" is reserved for changes a portfolio manager would want
  surfaced: new or removed risk factors, tone shifts on named business
  drivers, litigation/regulatory language changes, guidance-adjacent
  language, segment framing changes.
- If a flagged pair shows no substantive difference, classify it
  boilerplate with summary "no substantive change".
Output: a JSON array, nothing else.

Changes:
{changes_json}
"""

SYNTHESIS_PROMPT = """You are writing a longitudinal narrative for {ticker}'s {section_name}
section across {year_range}. Below are the interpreted changes for each year pair.

Write a 3-to-6 sentence narrative tracing how this section evolved over time.
Reference specific changes, their timing, and their direction (appeared, expanded, softened, removed).

Rules:
- Use ONLY the provided interpretation records. Do not infer changes not shown.
- Do not use outside knowledge of the company.
- Be specific: name what changed and when, not vague generalities.

Interpretations:
{interpretations_json}
"""
```

### 3. `src/delta/interpret.py` (new — stages 7-8)
Implement per ARCHITECTURE §3.7:
- `call_llm(prompt, timeout=180) -> str`: reuse the pattern from `run_eval.py:call_llm`. Use `opencode run --agent chatter`, `OPENCODE_ATTACH` for serve mode, `sanitize_prompt()`, strip ANSI codes, filter `> ` lines.
- `validate_interpretation(record, diff_record) -> (bool, str)`:
  - Check `change_id` matches `diff_record["change_id"]`.
  - Check `record["old_quote"]` is a substring of `diff_record["old_text"]` (literal `in` test, case-sensitive).
  - Check `record["new_quote"]` is a substring of `diff_record["new_text"]`.
  - Check `change_type` in the valid enum.
  - Check `materiality` in the valid enum.
  - Return `(True, "")` or `(False, error_message)`.
- `interpret_section_pair(diff_records, xbrl_context, ticker, anchor, year_pair) -> list[dict]`:
  - Filter to changed records only (skip `unchanged`).
  - Build the prompt using `INTERPRETATION_PROMPT` with the changed records + XBRL context.
  - Call LLM, parse JSON array.
  - For each interpretation, find its diff record by `change_id`, validate.
  - On validation failure: retry the entire LLM call once with a "your previous response had invalid quotes, please fix" prefix. If still failing, render the record with the diff but no interpretation, flagged `[unvalidated]`.
  - Return list of interpretation records (validated + unvalidated-flagged).
- `synthesize_trend(interpretations, anchor, year_pairs) -> str`:
  - Build prompt using `SYNTHESIS_PROMPT` with all interpretation records for this section across all year pairs.
  - Call LLM, return the narrative string.

### 4. `src/delta.py` (modify — full pipeline with LLM)
- Remove `--no-llm` as the default. The full pipeline now:
  1. fetch → chunk (if not cached)
  2. for each year pair: align → diff → write diff records
  3. compute XBRL deltas for the full year range
  4. for each year pair × section: interpret (LLM)
  5. for each section: synthesize trend (LLM)
  6. assemble report data structure (in-memory)
  7. print CLI summary (churn scores + material changes count + top 5 material changes)
- Keep `--no-llm` flag for quick diff-only runs (skips steps 3-5).
- Add `--tickers` and `--years` args (already from phase 01).

### 5. `tests/test_xbrl_delta.py` (new)
- Test `get_xbrl_values` with a known tag (e.g., `ResearchAndDevelopmentExpense`) from AAPL companyfacts.
- Test `fiscal_year_value` matching.
- Test `compute_yoy_deltas` with a 3-year range.
- Test `deltas_for_section` filtering by anchor.

### 6. `tests/test_diff.py` (modify — add interpretation validation test)
- Test `validate_interpretation` with valid quotes, invalid quotes (not substring), wrong change_id, invalid enums.

## Constraints
- Do not modify contracts defined in 00-ARCHITECTURE.md.
- Do not implement report rendering or web app (phases 04-05).
- Do not change the anchor vocabulary or `scoring.py`.
- The LLM never sees unchanged diff records — only changed ones. Enforce this in `interpret_section_pair`.
- Every interpretation must pass the quote-verbatim check. Failures are retried once, then flagged `[unvalidated]` — never silently accepted.
- XBRL numbers come from `companyfacts.json` (structured data), never extracted from prose by the LLM.
- Use `opencode run --agent chatter` for all LLM calls. Never use the default `build` agent (it has tools and will try to call bash instead of answering).
- For batch runs (all 7 tickers), remind the user to start `opencode serve --port 4096` first (per `working_knowledge.md`).

## Acceptance
1. `cd src && python delta.py AAPL --years 5` runs the full pipeline (fetch → chunk → diff → XBRL → interpret → synthesize) and prints a CLI summary with churn scores + material changes.
2. The CLI summary lists at least 1 material change with a summary, why_it_matters, and quotes from both years.
3. All interpretation records pass the quote-verbatim validation (or are flagged `[unvalidated]`).
4. XBRL deltas are computed for at least `Revenues`, `ResearchAndDevelopmentExpense`, `NetIncomeLoss` across the 5-year range.
5. Trend narratives are generated for at least `item1a_risk` and `item7_mdna`.
6. `cd src && python -m unittest discover -s ../tests -v` passes (including new test_xbrl_delta.py).
7. Run with `--no-llm` still works (produces diff records + churn scores, no interpretations).

## Out of scope
- Report rendering to HTML (phase 04)
- Web app (phase 05)
- Batch run for all 7 tickers (phase 04)
- Deployment (phase 05)
- Faithfulness judge for interpretations (the quote-verbatim check IS the faithfulness enforcement)