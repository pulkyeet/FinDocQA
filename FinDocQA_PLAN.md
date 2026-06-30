# FinDocQA: RAG Eval Harness for Financial Documents

**One-line pitch:** A QA system over SEC 10-K filings with a built-in, deterministic eval suite that measures and compares chunking / embedding / reranking strategies. The eval harness is the project, not the chatbot.

**Thesis (the headline):** Naive fixed-size chunking shreds tabular numeric data (income-statement tables), orphaning numbers from their labels. Section/table-aware chunking recovers it. The harness proves this with deterministic retrieval and numeric-correctness metrics, plus an abstention test (a finance system that invents a number is worse than useless).

---

## 1. Corpus + sourcing

- **Corpus:** Magnificent 7 FY2025 10-Ks (Apple, Microsoft, Nvidia, Alphabet, Amazon, Meta, Tesla). All 7 ingested.
- **Source:** `data.sec.gov`. Free, no API key, no auth.
  - `companyfacts/CIK{id}.json` -> every XBRL-tagged fact ever filed, as JSON. Powers numeric gold answers + auto-gen eval pairs.
  - The filing's inline-XBRL HTML (the 10-K document) -> prose chunks (MD&A, risk factors) with tables intact.
- **Access constraints (enforce in code):**
  - 10 req/sec cap across all SEC domains. Target 8/sec.
  - Mandatory header: `User-Agent: name email`. Missing = 403.
  - No daily limit.

**Fiscal-year caveat (do not skip):** FY2025 is NOT one calendar window across these companies. Microsoft FY ends Jun 2025, Apple ~Sep 2025, Nvidia FY2025 ended Jan 2025. Cross-company comparisons silently compare different time windows. Record the actual period-end on every cross-filing eval pair. Confirm each filing exists/period when pulled.

### Why all 7 if only 3 are hand-labeled (see sec 7)
The 4 unlabeled filings are not idle:
- They sit in the **corpus** as realistic **retrieval distractors**. Seven "R&D expense" lines forces the retriever to discriminate (a query for Apple's R&D must not return Nvidia's chunk = wrong-entity retrieval, a real production failure mode). Free, raises eval difficulty honestly.
- They feed the **auto-genned numeric eval** (free from XBRL).
- README claim "evaluated across all Magnificent 7" stays true.

**Cost model to keep in mind:** machine work scales to 7 because it's free; human labeling caps at 3 because its signal saturates and its cost does not.

---

## 2. Storage / caching (three local layers)

| Layer | Path | Contents | Invalidates when |
|---|---|---|---|
| Raw | `/data/raw/` | Fetched HTML + companyfacts JSON, keyed by accession number | Never (filings immutable) |
| Processed | `/data/chunks/` | Chunked text + metadata | You change chunking strategy |
| Vectors | Chroma (persisted) | Embeddings, keyed by `(chunk_strategy, embedding_model)` | You change chunking or embedding |

The **raw layer is what makes the eval reproducible**: same cached inputs, swap one config, diff the numbers. Re-fetching each run lets inputs drift and the comparison becomes worthless.

---

## 3. Pipeline (linear, raw Python, no graph framework)

```
chunk -> embed -> Chroma -> retrieve top-20 -> rerank top-5 -> generate -> answer + citations
```

- Raw Python on purpose. The pipeline is linear; LangGraph/LangChain add nothing here. "Knew when not to reach for a framework" is itself good hiring signal.
- **Citations from day one.** Every answer cites chunk + filing + page. Mandatory in finance, and it makes faithfulness eval trivial (check the cited chunk actually supports the claim).

### Models
- **Generation:** free OpenRouter / Gemini Flash-class. Fine, because we measure retrieval, not LLM prose.
- **HARD RULE: hold the generation model constant across all 8 configs.** Swap the LLM mid-matrix and a metric change can't be attributed to chunking/embedding/rerank. One hidden variable poisons the whole comparison.
- **Faithfulness judge:** use your single most reliable available model (small spend OK, it runs on few questions). Run it 3x, report disagreement. Never present judge output as ground truth.
- Long-context note: Flash has ~1M context, so you *could* stuff a whole filing and skip retrieval. Don't. (1) The project is about retrieval. (2) 7 filings overflow anyway. (3) "Lost in the middle" means retrieval often beats stuffing on accuracy. Optional bonus baseline: RAG vs full-context stuffing.

---

## 4. Toggles (3 axes = 8 configs)

| Axis | Variants |
|---|---|
| Chunking | fixed-size / section-aware |
| Embedding | 2 models (e.g. OpenAI vs BGE/local) |
| Rerank | on (cross-encoder, e.g. bge-reranker, local/free) / off |

Cap at 3 toggles. More combos = noise. Reranking (retrieve top-20 -> rerank to top-5) is a cheap, high-impact lever that signals knowledge of the modern stack.

---

## 5. Section-aware policy (FROZEN before W1)

This is the headline's independent variable. If it's fuzzy, "section-aware won" is unattributable. Freeze all five:

1. **Boundaries:** split on the 10-K's own Item headers (Item 1 Business, 1A Risk Factors, 7 MD&A, 8 Financial Statements). inline-XBRL HTML marks these, so boundaries are reliable not guessed.
2. **Size cap + overflow:** cap ~512-800 tokens. Section over cap -> recursively split on sub-headers then paragraphs. Keeps chunks in the band where embeddings discriminate.
3. **Tables (load-bearing):** each `<table>` is its own ATOMIC chunk, never split mid-table. Prefix with context (section heading + the "in millions" scale line + the introducing sentence). Tag `type=table`, `table_scale=1e6` (or whatever the header says). This is the headline: fixed-size chunking slices the income statement so "Research and development" and "29,915" land in different chunks. Atomic tables keep the row intact and feed extract_numbers its scale.
4. **Small-section merge:** min floor ~100 tokens; below it, merge into next section. Fewer junk vectors in top-k.
5. **Metadata per chunk:** `anchor`, `section/item`, `page`, `type` (prose|table), `table_scale`, `char_span`. One metadata set powers three things: gold-chunk scoring (anchor), citations (page), numeric normalization (table_scale). Emit from day one; backfill is painful.

---

## 6. Chunk ID / anchor scheme

Two fields per chunk:
- `chunk_id`: `{ticker}-{form}-{fy}-{strategy}-{NNNN}` e.g. `aapl-10k-2025-sectionaware-0042`. Unique per chunk per strategy. Display/debug only.
- `anchor`: stable label for the source region, e.g. `income_statement`, `item7_mdna`, `item1a_risk`.

**Label gold_chunks with ANCHORS, never chunk_ids.** The chunk is the thing the strategies vary, so chunk-level labels would force a different answer key per config and make the comparison meaningless (you'd score two configs against two different keys). Anchors are stable across all chunking strategies = one shared key = legitimate comparison. Scoring: a retrieved chunk is a hit if its anchor matches a gold anchor (or its source span overlaps the gold span).

**gold_chunk defined:** the label saying "the answer lives here." A stable pointer to the source region a correct system must retrieve. Assigned once when the question is written. At eval time: did the retriever return that anchor? Hit / miss. Pure set membership, no LLM.

---

## 7. Eval set

### Composition (56 questions)

| Type | Count | Route | Label source | Cost |
|---|---|---|---|---|
| Numerical | 20 | corpus | XBRL auto-gen | ~free |
| Factual | 10 | corpus | semi-auto | low |
| Multihop | 8 | corpus | hand | high |
| Cross-filing | 8 | corpus | hand | high |
| Unanswerable | 6 | abstain | hand | low |
| Out-of-corpus | 4 | web | hand | low |
| **Total** | **56** | | | |

**Route distribution:** corpus 46 / abstain 6 / web 4 (the router's 3-way classification test).

**Hand-labeled bucket = 26** (multihop 8 + cross-filing 8 + unanswerable 6 + web 4). This is the real W2 work, ~2-3 days. Anchor hand-labeling on **3 filings** of maximum contrast (e.g. Apple hardware / Microsoft software / Nvidia chips). 3 covers every comparison shape (cross-company, cross-sector, wrong-entity); a 4th adds a distractor not a new kind of test, and signal saturates.

**Question type definitions:**
- **Single-hop / factual:** one lookup. "Apple FY2025 R&D?" -> one chunk.
- **Multihop:** chained lookups combined. "R&D vs buybacks, which bigger?" -> income_statement + cash_flow (two anchors). Richest variant: "gross margin change AND why per mgmt" -> table (number) + MD&A (prose reason), two different chunk types must both retrieve. Tests whether retrieval finds ALL needed regions, not just one.
- **Cross-filing:** "Apple vs Nvidia R&D % of revenue" -> two filings' income_statements.
- **Unanswerable:** "Apple's crypto trading revenue" (does not exist) -> must abstain.

### Eval-set JSON schema

```json
{
  "id": "aapl-fy25-rnd",
  "question": "What was Apple's R&D expense in FY2025?",
  "type": "numerical",
  "expected_route": "corpus",
  "gold_chunks": ["income_statement"],
  "answer": {
    "value": 29915000000,
    "unit": "USD",
    "text": "$29.9 billion"
  },
  "source": "xbrl:us-gaap:ResearchAndDevelopmentExpense",
  "period_end": "2025-09-27"
}
```
- `gold_chunks` (anchors) -> retrieval precision/recall, deterministic.
- `expected_route` -> router scored 3-way, deterministic.
- `type` -> dashboard slices by this (where each config wins/loses).
- `answer.value` -> numeric correctness without an LLM.
- `source` (XBRL tag) -> the auto-gen hook: numerical pairs generate from the XBRL loop (tag gives value+unit, the section it sits in gives gold_chunk, type always numerical, route always corpus).
- `period_end` -> guards the cross-company fiscal-year drift.

### What can / cannot be automated
- **Auto (free, no LLM):** numerical pairs from XBRL.
- **Semi-auto:** question *drafting* (let an LLM propose candidates, you verify/assign gold_chunks). Speeds writing, you still own the labels.
- **Hand only:** gold_chunks for multihop / cross-filing / unanswerable. Nothing trustworthy can auto-label these; if a model could reliably produce the right answer location you wouldn't need to test whether the system finds it. The label must come from a source more trustworthy than the system under test = you.
- **DO NOT** use an LLM to generate gold_chunks. That makes ground truth a noisy LLM guess, destroys the deterministic-metric credibility that differentiates the project, and can be circularly wrong if labeler and retriever share a blind spot.

**Mental model:** labels are the ruler, not the thing measured. Carve the ruler by hand once (slow, can't automate the hard parts), then measure all 8 configs x N reruns instantly (fully automated). The pipeline generalizes to new user questions at runtime; the scoring does not (no gold_chunk = ran but can't be graded).

---

## 8. Scoring

| Metric | Method | Trust |
|---|---|---|
| Retrieval precision/recall | Anchor set membership vs gold_chunks | Deterministic gold |
| Routing | 3-way classification vs expected_route | Deterministic |
| Numeric correctness | Normalize-and-compare (below) | Deterministic |
| Faithfulness / relevance | LLM judge, run 3x, report disagreement | Noisy, prose only |

### Numeric correctness: normalize-then-compare (NOT regex)
The same fact wears different clothes: answer says "$29.9 billion", chunk says "29,915" (header "in millions"), XBRL says 29915000000. Extract candidate numbers, normalize to base units, compare against `answer.value` with tolerance.

```python
def numeric_match(answer_text, gold_value, tol=0.05):
    for n in extract_numbers(answer_text):
        if abs(gold_value) < 1:                    # near-zero: exact-ish, not ratio
            if abs(n - gold_value) < 0.01:
                return True
        elif abs(n - gold_value) / abs(gold_value) <= tol:
            return True
    return False
```
- 5% tolerance absorbs legit rounding ("29.9B" vs 29.915B = 0.05% off). Hallucinated numbers are usually wrong by tens of percent.
- Near-zero guard stops divide-by-tiny misbehaving on counts/ratios.
- The real work lives in `extract_numbers` (currency, commas, billion/million/thousand words, "in millions" table_scale, parens-as-negative). `table_scale` and inline word are mutually exclusive: inline word wins, scale applies only to bare numbers. Detect table_scale at ingest from the chunk header, store as metadata, do not re-derive at match time.
- Honest limit: this verifies "answer states a number equal to X", not that the number means the right line item / fiscal year. The cited gold_chunk carries that semantic load: right number from the right chunk = strong evidence; right number from wrong chunk = a flag the taxonomy should catch.

---

## 9. Failure taxonomy (minor post-step, ~30 lines)

After each run, bucket every miss by reading the results you already produced. No new infra.
Buckets: retrieval miss / table mangle / generation error / wrong abstention / wrong-entity retrieval.
Report e.g. "Of 14 failures: 8 retrieval, 4 table, 2 hallucination." Averages hide where the system breaks; reviewers value real error analysis.

---

## 10. Eval as a gate (not a notebook)

`make eval`:
1. Loads every config.
2. Runs the full set.
3. Writes `results.csv` keyed by config hash.
4. Prints a diff vs last run.

This is the literal meaning of "eval-first" and what makes the regression story TRUE: the harness ran, flagged the drop, you saw it. A notebook run once does not prove that.

---

## 11. Web fallback (gated, provenance-tagged)

Kept, with guardrails so it doesn't muddy the eval:
1. **Gate behind abstention.** RAG runs first; web fires ONLY when RAG abstains ("not in corpus"). Never blend in one answer.
2. **Tag provenance always.** `source: filing (high)` vs `source: web (low, unverified)`.
3. **Exclude web answers from RAG metrics.** Precision/recall/faithfulness measure your retrieval; contaminating them kills the story.
4. **Bonus:** each eval question now has a correct route, scored as the 3-way classification above.

---

## 12. Out / droppable

- **OUT:** LangGraph / LangChain orchestration. React dashboard (use Streamlit, gets the comparison view in a day).
- **DROPPABLE:** MCP wrapper. It's plumbing, not ML signal, and "nobody has it" is a fashion moat that decays. If W1-3 land clean, add one README paragraph ("also exposed via MCP, drops into Claude Desktop"). If not, nobody misses it. Do not anchor the project identity on it.

---

## 13. Week plan

- **W1:** 2-3 filings, one linear pipeline end to end, citations from day one. Get ugly answers out.
- **W2 (the big rock):** ingest all 7. Build the eval set (XBRL auto-gen numeric + hand-label the 26). Deterministic retrieval/routing/numeric metrics. Wire the 3 toggles.
- **W3:** faithfulness + abstention eval. Streamlit comparison view (config x metric x question-type). Cost/latency per config. Failure taxonomy.
- **W4:** README + the one-bug regression narrative. MCP only if W1-3 landed on time.

---

## 14. README story

Make it real and attributable to ONE lever. Best framing: a concrete bug the harness caught, e.g. "the harness flagged a regression where embedding model X dropped numerical-question recall 18%." That proves the harness does its job, worth more than the whole matrix.

**Reporting honesty:** per-type slices are small-n. Report counts ("section-aware 7/8 vs fixed 5/8 on multihop"), not fake-precise percentages ("87.5%"). Aggregate (56) + the deterministic numeric bucket (20) carry credibility. Don't oversell a 2-question slice difference as proof.
