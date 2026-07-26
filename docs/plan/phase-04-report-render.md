# Phase 04 — Report Render

> **Superseded in part by phase 06 (Report v2).** This phase built the evidence
> layer — per-paragraph change cards, materiality pills, per-change churn, trend
> narratives per section. Phase 06 replaced that surface with chaptered analyst
> prose (`delta/narrate.py`) plus a per-chapter evidence drawer; the cards, pills,
> and per-change churn were deliberately dropped. The CSS token layer, `base.html`,
> and `report.py`'s assembly/persistence split all still stand. Tier 0
> (Actions + Pages) was not pursued — see `DEPLOY.md`.

## Objective
Render the Delta change report as HTML (Jinja2) styled to DESIGN.md, plus the CLI summary. Build the CSS token layer from DESIGN.md's design system. Run the batch job for all 7 tickers. Set up Tier 0 deployment (static HTML via GitHub Actions + Pages).

## Context
Read first:
- `docs/plan/00-ARCHITECTURE.md` §3.8 (report contracts), §2.5-2.6 (report data schemas)
- `DESIGN.md` (the full design system — colors, typography, components, spacing, rounded, do's/don'ts)
- `delta_master_blueprint.md` Part II stage 9, deployment section
- `src/delta/interpret.py` (your phase 03 output — produces the report data)

## Deliverables

### 1. `src/web/static/css/tokens.css` (new — DESIGN.md → CSS)
Translate DESIGN.md's YAML tokens to CSS custom properties. This is the single source of truth for all styling:

```css
:root {
  /* Colors */
  --color-primary: #00d992;
  --color-primary-soft: #2fd6a1;
  --color-primary-deep: #10b981;
  --color-on-primary: #101010;
  --color-ink: #f2f2f2;
  --color-ink-strong: #ffffff;
  --color-body: #bdbdbd;
  --color-mute: #8b949e;
  --color-hairline: #3d3a39;
  --color-hairline-soft: #b8b3b0;
  --color-canvas: #101010;
  --color-canvas-soft: #1a1a1a;
  --color-canvas-text-soft: #f5f6f7;

  /* Typography */
  --font-sans: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  --font-mono: SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace;

  /* Font sizes (from DESIGN.md typography hierarchy) */
  --text-display-xl: 60px;
  --text-display-lg: 36px;
  --text-display-md: 24px;
  --text-display-sm: 20px;
  --text-body-lg: 18px;
  --text-body-md: 16px;
  --text-body-sm: 14px;
  --text-caption: 12px;
  --text-code: 13px;

  /* Spacing */
  --space-xxs: 2px; --space-xs: 4px; --space-sm: 8px; --space-md: 12px;
  --space-lg: 16px; --space-xl: 20px; --space-2xl: 24px; --space-3xl: 32px;
  --space-4xl: 40px; --space-5xl: 48px; --space-6xl: 64px;

  /* Rounded */
  --radius-xs: 4px; --radius-sm: 6px; --radius-md: 8px; --radius-pill: 9999px;
}

/* Component classes per DESIGN.md */
.card-feature { background: var(--color-canvas); color: var(--color-ink);
  border: 1px solid var(--color-hairline); border-radius: var(--radius-md);
  padding: var(--space-2xl); }
.code-mockup { background: var(--color-canvas); color: var(--color-ink);
  border: 1px solid var(--color-hairline); border-radius: var(--radius-md);
  padding: var(--space-xl); font-family: var(--font-mono); font-size: var(--text-code); }
/* ... all component classes from DESIGN.md ... */
```

Include ALL component classes from DESIGN.md: `button-primary`, `button-outline-on-dark`, `button-ghost-green`, `button-pill-tag`, `card-feature`, `card-feature-emphasized`, `code-mockup`, `code-inline-chip`, `text-input`, `nav-bar`, `nav-link`, `footer`, `hero-band`, `content-band`, `green-divider-band`.

### 2. `src/delta/report.py` (new — stage 9)
Implement per ARCHITECTURE §3.8:
- `build_report_data(ticker, year_range) -> dict`:
  - Load all diff records from `data/diffs/{ticker}/FY{yyyy}_FY{yyyy}.jsonl` for each year pair.
  - Load all interpretation records (stored alongside diff records, or re-run interpretation — decide: store interpretation records in `data/diffs/{ticker}/FY{yyyy}_FY{yyyy}_interpretations.jsonl`).
  - Load XBRL deltas.
  - Compute churn scores per section per year pair.
  - Assemble the full report dict per ARCHITECTURE §2.6.
- `render_html(report_data, template_dir) -> str`:
  - Load Jinja2 templates from `src/web/templates/`.
  - Render `report.html` with the report data.
  - Return HTML string.
- `render_cli_summary(report_data) -> str`:
  - Format the CLI summary (churn scores table, material changes list, counts).
- `write_report(ticker, html)`:
  - Write to `data/reports/{ticker}.html`.

### 3. `src/web/templates/base.html` (new — DESIGN.md chrome)
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}FinDocQA Delta{% endblock %}</title>
  <link rel="stylesheet" href="/static/css/tokens.css">
  {% block head %}{% endblock %}
</head>
<body style="background: var(--color-canvas); color: var(--color-ink); margin: 0;
             font-family: var(--font-sans); font-size: var(--text-body-md); line-height: 1.65;">
  <nav class="nav-bar" style="...">
    <!-- nav-bar per DESIGN.md: sticky top, canvas bg, hairline bottom border -->
    <span style="color: var(--color-primary); font-weight: 600;">FinDocQA Delta</span>
    <!-- nav links -->
  </nav>
  {% block content %}{% endblock %}
  <footer class="footer" style="...">
    <!-- footer per DESIGN.md -->
  </footer>
</body>
</html>
```

### 4. `src/web/templates/report.html` (new — the Delta report)
Extends `base.html`. Renders the full change report:
- **Header:** ticker, entity name, year range, generated-at timestamp.
- **Churn scores table:** per section per year pair. Use `ex-data-table-cell` styling (mono-caps header, body-sm rows, hairline row borders).
- **XBRL deltas summary:** key metrics (revenue, R&D, net income) with YoY % changes. Use `code-inline-chip` for numbers.
- **Material changes section:** for each material change:
  - `card-feature` container
  - Change type pill (`button-pill-tag`), materiality indicator (green for material)
  - Summary line
  - Why it matters
  - Side-by-side quotes: old (left) and new (right), in `code-mockup` style blocks
  - XBRL context (if applicable)
  - Year pair + anchor label
- **Notable changes section:** same format, collapsed by default (`<details>`).
- **Boilerplate count:** "N boilerplate changes suppressed. [Show all]" link.
- **Trend narratives:** per section, in `content-band` style.

### 5. `src/delta.py` (modify — add report render step)
After interpretation + synthesis, call `build_report_data()` → `render_html()` → `write_report()`. Also print `render_cli_summary()`.

### 6. Batch job
- `python delta.py --all --years 5`: run the full pipeline for all 7 tickers, write reports to `data/reports/`.
- Add `make delta-batch` target to Makefile: `cd src && python delta.py --all --years 5`.

### 7. Tier 0 deployment (GitHub Actions + Pages)
- `.github/workflows/delta-reports.yml`: on schedule (monthly) or manual trigger:
  1. Checkout repo
  2. Install Python deps
  3. `cd src && python fetch.py --years 5 && python chunk.py --strategy sectionaware && python delta.py --all --years 5`
  4. Commit `data/reports/*.html` to `gh-pages` branch
  5. GitHub Pages serves them
- Add a simple `data/reports/index.html` that lists all 7 tickers with links to their reports.

### 8. `Makefile` (modify — add targets)
```makefile
delta:
	cd src && $(PY) delta.py $(TICKER) --years $(YEARS)

delta-batch:
	cd src && $(PY) delta.py --all --years 5

delta-no-llm:
	cd src && $(PY) delta.py $(TICKER) --years $(YEARS) --no-llm

web:
	cd src && uvicorn web.app:app --reload --port 8000
```

## Constraints
- Do not modify contracts defined in 00-ARCHITECTURE.md.
- Do not implement the FastAPI web app routes (phase 05) — only the templates and static CSS.
- Do not use any JS framework. Pure HTML + CSS + minimal inline JS (only for `<details>` toggles if needed).
- Follow DESIGN.md do's and don'ts strictly:
  - Dark canvas only (no light mode)
  - Electric green (`--color-primary`) for CTAs and status indicators only, NOT body text
  - Hairline borders on cards, no shadows
  - Inter for narrative, SF Mono for code/numbers
  - Hero headline at weight 400 (calm, not bold)
  - 6px radius for buttons, 8px for cards, pill only for status tags
- Every LLM claim in the report must trace to a diff record. If an interpretation is `[unvalidated]`, render it with a visible flag (e.g., amber border or `[unvalidated]` tag).
- The report must be readable as a standalone HTML file (no server needed for Tier 0). Inline the CSS or link it relatively.

## Acceptance
1. `cd src && python delta.py AAPL --years 5` produces `data/reports/AAPL.html`.
2. Open `data/reports/AAPL.html` in a browser — it renders with DESIGN.md styling (dark canvas, green accents, hairline cards, Inter + SF Mono).
3. The report shows: churn scores table, XBRL deltas, material changes with side-by-side quotes, trend narratives.
4. `make delta-batch` produces reports for all 7 tickers in `data/reports/`.
5. `data/reports/index.html` lists all 7 tickers with clickable links.
6. The CLI summary prints to terminal with churn scores + material change count.
7. No LLM claim in the HTML lacks a traceable diff record. Verify: spot-check 3 material changes — each has old_quote and new_quote that are verbatim substrings of the diff record text.
8. `cd src && python -m unittest discover -s ../tests -v` passes.

## Out of scope
- FastAPI web app with routes (phase 05)
- Tier 1 deployment (phase 05)
- Interactive features (search, filter, sort) — the report is a static document
- RSS/email digest (future extension)
- Churn-score comparison table across tickers (future extension)