# INDEX.md — Phase Plan

| Phase | Name | Status | Depends on | Parallelizable with |
|---|---|---|---|---|
| 00 | Walking skeleton | ✅ complete | — | — |
| 01 | Multi-year corpus | ✅ complete | 00 | — |
| 02 | Diff engine (full) | ✅ complete | 01 | — |
| 03 | XBRL + interpretation | ✅ complete | 02 | — |
| 04 | Report render | ✅ complete | 03 | — |
| 05 | Web app + deploy | ✅ complete | 04 | — |

## Dependency notes

- **Strict linear order.** Each phase consumes the output of the previous.
- Phase 00 produced the thinnest end-to-end slice (1 ticker, 2 years, diff → CLI, no LLM).
- Phase 01 expanded the corpus (30 filings across 7 tickers) and hardened the chunker for older formats and non-standard heading styles.
- Phase 02 built the full diff engine + tuned thresholds on a 48-pair labeled sample across 5 sections and 2 year pairs.
- Phase 03 added the XBRL numeric backbone + OpenRouter-powered LLM interpretation + trend synthesis. 63/79 (80%) validation rate with batched prompts.
- Phase 04 renders the report to DESIGN.md spec (Jinja2 + CSS tokens).
- Phase 05 wraps the report in a FastAPI web app (hero/query + report pages) and deploys.

## What changed from the original plan

| Area | Planned | Actual |
|---|---|---|
| LLM backend | opencode subprocess | OpenRouter HTTP API (primary), opencode fallback |
| LLM agent | `chatter` | `paid-chatter` (system agent) |
| Labeled sample | 50 pairs from 1 section | 48 pairs from 5 sections × 2 year pairs |
| Thresholds | expected to shift significantly | validated defaults (0.95/0.81/0.60) |
| Chunker hardening | regex tweaks | keyword+table heading detection, anchor fallback, merge guard |

## Resolved gap: numeric-blindness ✅

The cosine-similarity classifier was blind to numeric value changes: a paragraph
where only dollar amounts change (e.g. revenue $100M → $489M) scores ~0.99 and
was classified unchanged — the LLM never saw it.

**Fixed (Hybrid text + XBRL numeric guard).** A deterministic guard runs only on
records cosine calls `unchanged` and upgrades them when a material numeric move is
detected: a text guard (`diff.py:numeric_change_signal`, reusing
`scoring.extract_numbers`) catches ≥20% moves on any section, and XBRL
corroboration (`xbrl_change_signal`) flags the most number-dense paragraph when an
audited financial-section tag moved but text didn't surface it. Orthogonal to the
tuned thresholds; every upgrade carries an auditable `numeric_guard` reason. See
`tracker.md` for details and verification.

## What "done" looks like (end of phase 05)

`python delta.py AAPL --years 5` produces a full change report. A user visits
the web app, enters a ticker, and views the rendered report with churn scores,
material changes, side-by-side quotes, XBRL deltas, and trend narratives — all
traceable to deterministic diff records.
