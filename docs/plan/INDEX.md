# INDEX.md — Phase Plan

| Phase | Name | Status | Depends on | Parallelizable with |
|---|---|---|---|---|
| 00 | Walking skeleton | pending | — | — |
| 01 | Multi-year corpus | pending | 00 | — |
| 02 | Diff engine (full) | pending | 01 | — |
| 03 | XBRL + interpretation | pending | 02 | — |
| 04 | Report render | pending | 03 | — |
| 05 | Web app + deploy | pending | 04 | — |

## Dependency notes

- **Strict linear order.** Each phase consumes the output of the previous.
- Phase 00 produces the thinnest end-to-end slice (1 ticker, 2 years, diff → CLI, no LLM).
- Phase 01 expands the corpus (3×3 → 7×5) and hardens the chunker for older formats.
- Phase 02 builds the full diff engine + tunes thresholds on the 50-pair labeled sample.
- Phase 03 adds the XBRL numeric backbone + LLM interpretation + trend synthesis.
- Phase 04 renders the report to DESIGN.md spec (Jinja2 + CSS tokens).
- Phase 05 wraps the report in a FastAPI web app (hero/query + report pages) and deploys.

## What "done" looks like (end of phase 05)

`python delta.py AAPL --years 5` produces a full change report. A user visits the web app, enters a ticker, and views the rendered report with churn scores, material changes, side-by-side quotes, XBRL deltas, and trend narratives — all traceable to deterministic diff records.