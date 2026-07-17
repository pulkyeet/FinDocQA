# Phase 02 — Diff Engine (Full)

## Objective
Build the full diff engine: complete paragraph alignment with greedy matching, diff classification with word-level deltas, churn score computation, and the 50-pair labeled sample for threshold tuning. By the end, `python delta.py AAPL --years 5 --no-llm` produces a complete, tuned diff record set for all sections across all year pairs.

## Context
Read first:
- `docs/plan/00-ARCHITECTURE.md` §3.4 (align), §3.5 (diff), §2.3 (diff record schema)
- `docs/plan/phase-00-walking-skeleton.md` (you built the minimal align + diff here)
- `delta_master_blueprint.md` Part II stage 5 (classification table), threshold tuning section
- `src/delta/align.py`, `src/delta/diff.py` (your phase 00 implementations)

## Deliverables

### 1. `src/delta/align.py` (modify — full implementation)
- `match_paragraphs()`: implement the greedy best-match algorithm fully:
  - Compute all pairwise cosine similarities between old and new paragraph embeddings.
  - Sort all (old_idx, new_idx, similarity) triples by similarity descending.
  - Greedily assign: take the highest unassigned pair, mark both indices as used, repeat.
  - Pairs below `ALIGN_SIMILARITY_FLOOR` (0.50) are not matched → their new_idx goes to `added`, old_idx to `removed`.
  - Return `{matches: [{old_idx, new_idx, similarity}], added: [new_idx], removed: [old_idx]}`.
- `align_section_pair()`: reconstruct the full section text by concatenating all chunks for that anchor (in chunk order), then `split_into_paragraphs()`. This gives the complete paragraph list for the section, not per-chunk.
- Add a `match_paragraphs_hungarian()` function (using `scipy.optimize.linear_sum_assignment`) as a fallback, but do NOT wire it in yet — it's a fallback if the labeled sample shows greedy is insufficient. Just have it ready.

### 2. `src/delta/diff.py` (modify — full implementation)
- `word_delta()`: use `difflib.ndiff` on whitespace-split word lists. Return `{'added': [words], 'removed': [words]}`. Only include words that are genuinely added/removed (ignore changed punctuation).
- `compute_churn_score()`: for a section pair, churn = sum(len(para) for para in changed_paras) / sum(len(para) for all_paras). "Changed" = classification != "unchanged". Weighted by paragraph character length.
- `diff_section_pair()`: for each matched pair, classify and create a diff record. For added paragraphs, create `added` records. For removed, create `removed` records. Return all records.
- `make_diff_record()`: ensure `change_id` is unique within a section pair. Format: `{TICKER}-{anchor}-{FY_old}-{FY_new}-{NNN}` where NNN is a zero-padded 3-digit sequence.
- Add `diff_all_sections(old_chunks, new_chunks, ticker, year_pair, model_key) -> list[dict]`: run align + diff for every section pair, collect all records.

### 3. `src/delta.py` (modify — full --no-llm pipeline)
- The `--no-llm` path now: fetch → chunk → for each year pair → diff all sections → write diff records → print churn scores per section per year pair.
- Print a summary table:
```
AAPL: FY2021 -> FY2025 Change Report (no-LLM)
================================================
Churn scores (fraction of section text changed YoY):
  Risk Factors (1A):   FY22: 0.11  FY23: 0.09  FY24: 0.31  FY25: 0.14
  MD&A (7):            FY22: 0.42  FY23: 0.38  FY24: 0.45  FY25: 0.40
  ...
Changes: 4 year-pairs × N sections = M total diff records
  modified_major: X | modified_minor: Y | added: Z | removed: W
```

### 4. 50-pair labeled sample (manual + code)
- Pick one ticker (AAPL) and one section (item1a_risk).
- Run the diff engine on AAPL FY2024→FY2025 for that section.
- From the output, select ~50 paragraph pairs spanning the similarity range (some unchanged >0.95, some minor 0.80-0.95, some major 0.60-0.80, some added/removed).
- Create `data/eval/diff_labels.jsonl` with one record per pair:
```json
{
  "change_id": "AAPL-item1a_risk-FY2024-FY2025-017",
  "similarity": 0.71,
  "your_label": "modified_major",
  "notes": "AI risk expanded with litigation language"
}
```
- Hand-label each pair: `unchanged | modified_minor | modified_major | added | removed`.
- This takes an afternoon. You're reading 50 short paragraph pairs and tagging each.

### 5. `src/delta/tune_thresholds.py` (new — threshold tuning)
```python
def load_labeled_pairs(path: str) -> list[dict]:
    """Load the 50-pair labeled sample."""

def evaluate_thresholds(labels: list[dict], unchanged_thresh, minor_thresh, major_thresh) -> dict:
    """For each labeled pair, predict classification using the given thresholds.
    Return {precision, recall, f1} per class + confusion matrix."""

def tune(labels: list[dict]) -> dict:
    """Grid search over threshold values. Find thresholds that maximize
    separation between classes on the labeled set.
    Hold out 10 pairs for final precision/recall reporting.
    Return {unchanged, minor, major, held_out_precision, held_out_recall}."""

if __name__ == "__main__":
    labels = load_labeled_pairs("data/eval/diff_labels.jsonl")
    results = tune(labels)
    print(f"Tuned thresholds: {results}")
    print(f"Held-out precision: {results['held_out_precision']:.2f}")
    print(f"Held-out recall: {results['held_out_recall']:.2f}")
```

### 6. Update `src/config.py` with tuned thresholds
After running `tune_thresholds.py`, update `DIFF_THRESHOLD_UNCHANGED`, `DIFF_THRESHOLD_MINOR`, `DIFF_THRESHOLD_MAJOR` in `config.py` with the tuned values. Record the precision/recall in a comment.

### 7. `tests/test_diff.py` (modify — add tuning tests)
- Test `evaluate_thresholds` with known labels and thresholds.
- Test `compute_churn_score` with mixed classifications.
- Test `word_delta` with complex additions/removals.

## Constraints
- Do not modify contracts defined in 00-ARCHITECTURE.md.
- Do not implement XBRL deltas, LLM interpretation, report rendering, or web app (phases 03-05).
- Do not change the anchor vocabulary.
- Do not wire in the Hungarian matching — it's a fallback, not the default. Only use it if the labeled sample shows greedy is insufficient (document this decision in `tracker.md` if it happens).
- The 50-pair labeled sample is hand-labeled by YOU, not an LLM. Same rule as v1 gold_chunks: the label must come from a source more trustworthy than the system under test.

## Acceptance
1. `cd src && python delta.py AAPL --years 5 --no-llm` produces 4 year-pair diff files for AAPL, each containing diff records for all sections. Churn scores printed to CLI.
2. `cd src && python -m delta.tune_thresholds` runs, prints tuned thresholds + held-out precision/recall.
3. Tuned thresholds are written to `config.py` with precision/recall in a comment.
4. `data/eval/diff_labels.jsonl` exists with 50 labeled pairs.
5. `cd src && python delta.py AAPL --years 5 --no-llm` runs with tuned thresholds and produces a summary table.
6. `cd src && python -m unittest discover -s ../tests -v` passes.
7. Diff records are valid JSON matching the schema in ARCHITECTURE §2.3. Verify: load each `.jsonl` file, parse every line, check required fields present.

## Out of scope
- XBRL delta join (phase 03)
- LLM interpretation (phase 03)
- Report rendering (phase 04)
- Web app (phase 05)
- Running the full 7-ticker diff (that's a batch job in phase 04)