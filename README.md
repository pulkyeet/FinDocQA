# FinDocQA — SEC filing intelligence

Two systems over one corpus of SEC 10-K filings:

1. **Delta** (`src/delta/`) — a five-year year-over-year change-intelligence
   engine. Deterministic diff + LLM interpretation, composed into a ~15-minute
   analyst report. **This is the product.**
2. **The RAG eval harness** (`src/run_eval.py`) — a deterministic suite that
   measures chunking × embedding × rerank configurations against XBRL ground
   truth. **This is the credibility floor**, and it came first: it's what
   establishes that the retrieval layer underneath Delta actually works.

Corpus: the Magnificent 7 (AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA), ~30
filings across five fiscal years, fetched from SEC EDGAR and cached immutably.

---

# Part I — Delta

**The problem.** A 10-K is 100+ pages, and roughly 95% of it is copied verbatim
from last year. The signal is in the 5% that changed — and nobody reads two
filings side by side to find it. Academic work on filing changes ("Lazy Prices")
found that firms whose filings change the most subsequently underperform. Delta
is framing that as a reading problem, not a trading signal.

**The core principle: detection is deterministic; only interpretation is
generative.**

The LLM never *finds* a change. Python does, by aligning paragraphs across years
and classifying them by embedding cosine similarity. The LLM only *explains*
pre-verified change pairs, and every claim it makes traces back to a diff record
with verbatim quotes from both years. If a generated quote isn't a literal
substring of the source, it's rejected — one retry, then it's excluded from the
report entirely.

This is the whole thesis. An LLM asked to "find what changed" will hallucinate
changes; one handed a verified diff and asked "why does this matter" cannot.

## The pipeline (9 stages)

```
fetch (N years) → parse + anchor → align sections (anchor equality)
  → align paragraphs (embeddings) → deterministic diff classification
  → XBRL numeric deltas → LLM interpretation (changed pairs only)
  → narrative composition (chapters) → report render
```

**Anchors are the alignment primitive.** `anchors.py` defines a stable semantic
vocabulary — `income_statement`, `item1a_risk`, `item7_mdna`, `cash_flow`.
Sections align across years by anchor *equality*, then paragraphs align by
embedding similarity within a section. Anchor coverage is asserted at ingest: if
`item1a_risk`, `item7_mdna`, or `item8_financials` fails to resolve for any
filing, the chunker raises rather than silently misaligning.

**Diff thresholds**, tuned on a 48-pair hand-labeled sample (5 sections × 2 year
pairs):

| Classification | Cosine |
|---|---|
| `unchanged` | ≥ 0.95 |
| `modified_minor` | ≥ 0.81 |
| `modified_major` | ≥ 0.60 |

Held-out performance (10 pairs): precision 0.300, recall 1.000, F1 0.462. The
high recall is deliberate — over-flagging and letting the LLM downgrade
something to boilerplate is much cheaper than missing a real change.

## The numeric guard

The most interesting failure this project hit. Cosine similarity is **blind to
value-only changes**: a revenue line moving from $100M to $489M is a ~0.99
similarity score, classified `unchanged`, and the LLM never sees it. The
detection layer was structurally incapable of noticing the numbers.

The fix is deterministic and runs *only* on records cosine already called
`unchanged`, so it's orthogonal to the tuned thresholds and needs no retuning:

- **Text guard** — compares extracted numbers on both sides of a matched pair;
  a relative move ≥ 20% upgrades to `modified_minor`, ≥ 100% to `modified_major`.
- **XBRL corroboration** — on financial sections, if an audited XBRL tag moved
  but no paragraph got text-flagged, the most number-dense paragraph is
  surfaced. This catches figures that survive only in a mangled table cell.

Every upgrade carries an auditable `numeric_guard` reason and renders as a
`Δ NNN%` badge. On a single MSFT year-pair the guard rescued **92 changes, all
at cosine ≥ 0.95** — i.e. 100% invisible to the classifier before it.

## What the reader actually gets

Not a diff dump. A chaptered report: Executive Summary → Financial Performance →
The Business → Risk Landscape → Management's Discussion → Legal & Regulatory →
What the Engine Found → Methodology.

Each chapter is 600–900 words of composed prose with an **evidence drawer** —
the narrator cites evidence labels inline, which resolve to the underlying diff
records with both years' quotes. Financial tables carry every year's absolute
value with its YoY percentage. Read time is computed from narrative length.

Chapters are **data, not template logic** (`REPORT_CHAPTERS` in `config.py`), so
re-cutting the report is a config edit rather than a template rewrite.

Deliberately *not* in the report: per-paragraph change cards, materiality pills,
and the thin anchors (Properties, Exhibits, Compensation) that carry no surfaced
change. The diff is the evidence layer beneath the report, not the report.

---

# Part II — The eval harness

*The eval harness is the project, not the chatbot.*

## The thesis

Financial tables are the hardest test for RAG. A single income-statement row
carries both a label ("Research and development") and a number ("$29,915").
Naive fixed-size chunking severs them — the label lands in one chunk, the number
in another, and the number is orphaned.

Section-aware chunking keeps tables atomic and tags each chunk with a semantic
anchor. Because gold answers are recorded as *anchors* rather than chunk IDs,
all eight configurations share one answer key.

**In hard numbers:** fixed-size configs score 9–10/56 joint correct; section-aware
configs score 24–28/56. The gap is almost entirely retrieval — fixed-size scores
`retrieval_hit` at 0–1/56 because it cannot produce anchors at all.

## The regression the harness caught

*The reranker, intended to boost relevance, systematically hurts numerical
accuracy — and only the harness can prove it.*

Under section-aware chunking with e5-small embeddings, turning cross-encoder
rerank ON drops `numeric_match` from **13/20 to 6/20** — a 54% relative decline.
The reranker prefers chunks that *sound* relevant (MD&A prose discussing trends)
over chunks that *contain* the dollar figures (income statement tables).

This is why deterministic scoring matters. Without XBRL gold values both answers
look plausible — "R&D was ~$29.9 billion" versus "R&D increased 10%." The harness
compares each answer to the ground-truth XBRL number, flags the drop, and
attributes it to exactly one toggle.

## The 8-config matrix

56 questions × 2 chunking strategies × 2 embedding models × rerank on/off = 448
scored answers.

| Config | Joint | Retrieval hit | Numeric match | Route ok |
|---|---|---|---|---|
| fixedsize + bge-small + rerank=off | 10/56 | 0/56 | 7/20 | 31/56 |
| fixedsize + bge-small + rerank=on | 9/56 | 0/56 | 9/20 | 30/56 |
| fixedsize + e5-small + rerank=off | 10/56 | 1/56 | 12/20 | 32/56 |
| fixedsize + e5-small + rerank=on | 9/56 | 1/56 | 8/20 | 28/56 |
| **sectionaware + bge-small + rerank=off** | **28/56** | 20/56 | 9/20 | 31/56 |
| sectionaware + bge-small + rerank=on | 24/56 | 14/56 | 7/20 | 30/56 |
| **sectionaware + e5-small + rerank=off** | **27/56** | 18/56 | **13/20** | **36/56** |
| sectionaware + e5-small + rerank=on | 25/56 | 15/56 | 6/20 | 25/56 |

**The generation model is frozen** across all eight configs, so every metric
change is attributable to a chunking, embedding, or rerank toggle — never to the
LLM.

**Eval set: 56 questions** — 20 numerical (XBRL auto-generated), 10 factual,
8 multihop, 8 cross-filing, 6 unanswerable (expect abstention), 4 out-of-corpus
(expect web routing). All seven filings sit in the corpus as retrieval
distractors; three are hand-labeled for gold anchors.

**Scoring is deterministic** except the optional faithfulness judge: retrieval by
anchor-set membership, routing by 3-way classification, numeric by
normalize-and-compare at 5% tolerance against XBRL gold values.

---

## Quick start

Python 3.11.9. Scripts use relative paths and data lives in `src/data/`, so
`cd src` first — or use the `Makefile` at the repo root, which does it for you.

```bash
pip install -r requirements.txt
```

Secrets go in `src/.env`: `OPENROUTER_API_KEY`, `HF_TOKEN`, and `SEC_USER_AGENT`
(SEC asks for a descriptive user agent and may rate-limit generic ones).

**Delta — the product:**

```bash
make delta TICKER=AAPL YEARS=5
```

```bash
make delta-no-llm TICKER=AAPL
```

The `--no-llm` path runs fetch → chunk → align → diff with zero LLM calls. It's
fast, fully deterministic, and the right way to verify pipeline changes.

```bash
make web
```

Serves the report app at `localhost:8000`. Reports are pre-built and served as
static HTML — the app never runs the pipeline on request.

Because both the interpretation and narrative stages are persisted to disk,
template and prompt changes never require re-running the pipeline:

```bash
make rerender-all
```

Rebuilds every report's HTML from persisted output at **zero LLM cost**. Use
`make narrate-all` (~6 calls/ticker) when the prose prompts change.

**The eval harness:**

```bash
make fetch && make chunk && make embed
```

```bash
make eval
```

448 LLM calls. `streamlit run src/dashboard.py` opens a 4-tab config comparison.

**Tests:**

```bash
make test
```

180 tests across 9 modules.

## Deployment

Deployed to Fly.io as a slim static image: reports are built offline and baked
in, so the runtime carries no torch, no chromadb, and no secrets.

```bash
make deploy
```

Rerenders all reports, then deploys. Full procedure and the **cost invariant** —
which keeps this running at effectively $0/month — are in
[docs/DEPLOY.md](docs/DEPLOY.md). Read it before touching `fly.toml`.

## Project structure

```
FinDocQA/
├── README.md · DESIGN.md · LICENSE
├── AGENTS.md · CLAUDE.md          # agent notes
├── Makefile                       # fetch/chunk/embed/eval · delta/rerender/narrate/web/deploy
├── Dockerfile · fly.toml · requirements-web.txt   # slim static deploy
├── docs/
│   ├── delta_master_blueprint.md  # design source of truth
│   ├── DEPLOY.md                  # Fly.io deploy + cost invariant
│   ├── working_knowledge.md       # operational habits + recurring gotchas
│   ├── tracker.md                 # progress log
│   └── plan/                      # architecture contracts + phase specs
├── src/
│   ├── config.py                  # paths, tickers, thresholds, REPORT_CHAPTERS
│   ├── fetch.py · chunk.py · anchors.py    # shared ingest layer
│   ├── delta.py · rerender.py     # v2 CLI entrypoints
│   ├── delta/                     # the Delta pipeline
│   │   ├── align.py               # section + paragraph alignment
│   │   ├── diff.py                # classification, churn, numeric guard
│   │   ├── xbrl_delta.py          # YoY deltas + metric series
│   │   ├── interpret.py           # stage 7: interpretation + quote validation
│   │   ├── narrate.py             # stage 8: chapter prose + citations
│   │   ├── report.py · prompts.py # assembly, render, persistence
│   ├── web/                       # FastAPI app (serves pre-built reports)
│   ├── embed.py · rerank.py · query.py · run_eval.py · scoring.py   # v1 harness
│   ├── web_search.py · dashboard.py
│   └── eval/                      # question generation
├── tests/                         # 9 modules, 180 tests
└── src/data/                      # gitignored: raw, chunks, chroma, eval, diffs, reports
```

`src/data/` is entirely gitignored and rebuilt by re-running the pipeline. Raw
filings are cached by file existence and never edited by hand — the raw layer is
the single source of truth for reproducibility.

## Limitations

**Delta:**

- **Materiality is an LLM judgment**, presented as a triage aid, never as ground
  truth. The deterministic diff beneath it is the ground truth.
- **Interpretation quality degrades on heavily restructured sections.** Greedy
  paragraph alignment can mismatch when a company rewrites a section wholesale.
- **No price data, no signals, no backtesting.** "Lazy Prices" is framing, not a
  claim to replicate.
- **Coverage is 7 tickers.** Adding one is a local pipeline run plus a redeploy;
  there is no live generation path in production by design.

**The eval harness:**

- **Per-type slices are small-n** (6–20 questions) — directional, not conclusive.
  The aggregate (56) and the numerical bucket (20) carry the weight.
- **Only 3 filings are hand-labeled.** The other 4 act as retrieval distractors,
  essential for entity discrimination but not individually scored.
- **Web fallback uses DuckDuckGo** — noisy for financial precision. Provenance is
  tagged and excluded from RAG metrics.
- **The faithfulness judge is an LLM** (3× majority, disagreement reported), off
  by default and never presented as ground truth.

## License

MIT — see [LICENSE](LICENSE).
