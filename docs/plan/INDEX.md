# INDEX.md — Phase Plan

| Phase | Name | Status | Depends on | Parallelizable with |
|---|---|---|---|---|
| 00 | Walking skeleton | ✅ complete | — | — |
| 01 | Multi-year corpus | ✅ complete | 00 | — |
| 02 | Diff engine (full) | ✅ complete | 01 | — |
| 03 | XBRL + interpretation | ✅ complete | 02 | — |
| 04 | Report render | ✅ complete | 03 | — |
| 05 | Web app + deploy | ✅ complete | 04 | — |
| 06 | Report v2 (readability layer) | ✅ complete | 05 | — |
| — | Deploy prep (Fly.io static) | ✅ complete | 06 | — |

## Dependency notes

- **Strict linear order.** Each phase consumes the output of the previous.
- Phase 00 produced the thinnest end-to-end slice (1 ticker, 2 years, diff → CLI, no LLM).
- Phase 01 expanded the corpus (30 filings across 7 tickers) and hardened the chunker for older formats and non-standard heading styles.
- Phase 02 built the full diff engine + tuned thresholds on a 48-pair labeled sample across 5 sections and 2 year pairs.
- Phase 03 added the XBRL numeric backbone + OpenRouter-powered LLM interpretation + trend synthesis. 63/79 (80%) validation rate with batched prompts.
- Phase 04 renders the report to DESIGN.md spec (Jinja2 + CSS tokens).
- Phase 05 wraps the report in a FastAPI web app (hero/query + report pages) and deploys.
- Phase 06 (added after 05) recomposes the report from a diff viewer into a ~15-minute
  chaptered analyst read — stage 8 `narrate.py`, evidence drawers, citation resolution.
  Phases 04/05 shipped the evidence layer; 06 shipped the thing a human actually reads.
- Deploy prep hardened phase 05's config into a shippable, effectively-free Fly.io
  deploy (slim image, cost invariant, `make deploy`). See `DEPLOY.md`.

## What changed from the original plan

| Area | Planned | Actual |
|---|---|---|
| LLM backend | opencode subprocess | OpenRouter HTTP API (primary), opencode fallback |
| LLM agent | `chatter` | `paid-chatter` (system agent) |
| Labeled sample | 50 pairs from 1 section | 48 pairs from 5 sections × 2 year pairs |
| Thresholds | expected to shift significantly | validated defaults (0.95/0.81/0.60) |
| Chunker hardening | regex tweaks | keyword+table heading detection, anchor fallback, merge guard |
| Report shape | per-paragraph change cards + materiality pills | chaptered analyst prose (stage 8) + per-chapter evidence drawers; cards and pills dropped |
| Trend synthesis | per-section synthesis (phase 03) | superseded by per-chapter narrative composition (`narrate.py`) |
| Fly build | Paketo buildpack | `Dockerfile` + `requirements-web.txt` (no torch → ~200MB image) |
| Machine sizing | unspecified | `[[vm]]` pinned `shared-cpu-1x`/`256mb`, always-on — keeps the bill under Fly's $5 non-collection threshold |
| `/api/trigger` | background pipeline run | inert (`501`); live generation dropped, not deferred |
| Deploy cost | ~$5/mo | ~$2/mo of usage → under Fly's collection threshold → effectively $0 |

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

## What "done" looks like (current)

`python delta.py AAPL --years 5` produces a full change report. A user visits the
deployed app, picks a ticker, and reads a ~15-minute chaptered analyst report —
narrative prose with an evidence drawer per chapter, financial tables carrying
every year's value and YoY %, and section churn — every claim traceable to a
deterministic diff record with verbatim quotes from both years.

The app is deployed to Fly.io serving pre-built reports from a slim image, at
~$2/mo of usage which falls under Fly's $5 non-collection threshold. There is no
live generation in production by design; adding a ticker is a local pipeline run
plus `make deploy`.
