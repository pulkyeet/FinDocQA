# Phase 05 — Web App + Deploy

> **This is the original plan, retained as the execution record. Four things
> changed in what shipped — see `../DEPLOY.md` for the current procedure:**
>
> 1. **Build:** `Dockerfile` + `requirements-web.txt`, not the Paketo buildpack in
>    the `fly.toml` snippet below. No torch/chromadb in the image (~200MB).
> 2. **Machine:** `fly.toml` pins `[[vm]]` to `shared-cpu-1x`/`256mb` and runs
>    always-on (`min_machines_running = 1`, `auto_stop_machines = false`). Fly has
>    no free tier but doesn't collect invoices under $5/mo, and 256mb always-on is
>    ~$2.02/mo — so this is effectively free *and* has no cold start. The
>    `fly launch` default of 1GB is $5.92/mo and would be billed in full.
> 3. **`/api/trigger` is inert (`501`).** The "stretch goal" framing below resolved
>    to *dropped*, not deferred: live generation needs the full pipeline image,
>    secrets, a volume, and a job runner, and would break the cost invariant.
> 4. **Report content:** phase 06 replaced the per-paragraph change cards and
>    materiality pills described below with chaptered analyst prose (`narrate.py`)
>    and per-chapter evidence drawers.
>
> The static-serving decision recorded in deliverable 5 was the right call and is
> what shipped.

## Objective
Wrap the report in a FastAPI web app with two pages: a hero/query index page (sells the project, accepts ticker input) and a report page (displays the Delta change report). Deploy to Fly.io (Tier 1: ~$5/mo, serves pre-built reports + trigger endpoint for cached tickers).

## Context
Read first:
- `docs/plan/00-ARCHITECTURE.md` §3.10 (web app contracts), §4 (API routes), §5 (cross-cutting policies)
- `DESIGN.md` (full design system — the hero page is the primary DESIGN.md surface)
- `../delta_master_blueprint.md` Part II web application section, deployment section
- `docs/plan/phase-04-report-render.md` (you built the templates + CSS here)
- `src/web/templates/base.html`, `report.html` (from phase 04)
- `src/web/static/css/tokens.css` (from phase 04)

## Deliverables

### 1. `src/web/__init__.py` (new — empty package marker)

### 2. `src/web/app.py` (new — FastAPI app factory)
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

def create_app() -> FastAPI:
    app = FastAPI(title="FinDocQA Delta")
    # Static files (CSS, JS, images)
    app.mount("/static", StaticFiles(directory="src/web/static"), name="static")
    # Templates
    templates = Jinja2Templates(directory="src/web/templates")
    app.state.templates = templates
    # Routes
    from web.routes import register_routes
    register_routes(app, templates)
    return app

app = create_app()
```

### 3. `src/web/routes.py` (new — route handlers)
Implement per ARCHITECTURE §3.10 and §4:

```python
async def index(request: Request):
    """Hero page + ticker input.
    - Lists available pre-built reports (scan data/reports/*.html)
    - Ticker input form (text input + years selector, default 5, max 5)
    - Form POSTs to /report/{ticker} (or /api/trigger/{ticker} if not pre-built)
    """

async def report(request: Request, ticker: str):
    """Report page.
    - If data/reports/{ticker}.html exists: serve it (or render live from diffs)
    - If not: show 'not yet generated' with a trigger button
    - Render report.html template with the report data (load from diffs + interpretations)
    """

async def trigger(ticker: str, years: int = 5):
    """Trigger background batch for a cached ticker.
    - Validate ticker is in TICKERS (the 7 cached tickers)
    - Validate years <= DELTA_YEARS_MAX
    - Run delta.py as a subprocess (or call the pipeline function directly)
    - Return {"status": "started", "ticker": ticker}
    - Note: for Tier 1, this is a synchronous call (takes minutes).
      For a better UX, run in a background thread and poll /api/status.
    """

async def status(ticker: str):
    """Check if report exists / is generating.
    - {"ready": bool, "generating": bool, "report_path": str | null}
    """
```

### 4. `src/web/templates/index.html` (new — hero + ticker input)
Extends `base.html`. The primary DESIGN.md surface. Structure:

```
[hero-band]
  [eyebrow-mono] FILING CHANGE INTELLIGENCE
  [display-xl]  Understand what changed between 10-K filings.
  [body-lg]     Delta analyzes five years of SEC filings, surfaces material
                changes, and explains why they matter — with quotes from both years.
  [code-inline-chip] $ python delta.py AAPL --years 5

[content-band: ticker input]
  [display-md] Analyze a ticker
  [text-input form]
    Ticker: [___________]    Years: [5 ▼]    [button-primary: Generate Report]
  [body-sm] Available: AAPL · MSFT · NVDA · GOOGL · AMZN · META · TSLA

[content-band: how it works]
  [display-lg] How it works
  [3-up card grid]
    [card-feature] Deterministic diff — anchor alignment + embedding similarity
    [card-feature] LLM interpretation — explains, never detects
    [card-feature] XBRL numeric context — structured data, not prose extraction

[content-band: market context]
  [display-lg] Why this matters
  [body-md] The Lazy Prices research found firms whose filings change the most
            subsequently underperform. Analysts don't read diffs. Delta does.

[footer]
```

Follow DESIGN.md strictly:
- `hero-band`: canvas bg, 48px padding, display-xl headline at weight 400, eyebrow-mono above
- Cards: 1px hairline border, 8px radius, 24px padding, no shadow
- Green accent only on the CTA button and the code chip
- Inter for all text, SF Mono for the code chip

### 5. `src/web/templates/report.html` (modify — adapt for live rendering)
The phase 04 `report.html` was designed for static rendering. Adapt it to work with Jinja2Templates (FastAPI's template rendering):
- Ensure it extends `base.html` and receives `report_data` from the route handler.
- The route handler loads diff records + interpretations from `data/diffs/` and assembles the report data, then passes it to the template.
- Alternatively (simpler): the route handler reads the pre-built `data/reports/{ticker}.html` and serves it directly. This avoids re-rendering. Use this approach for Tier 1 — the report is pre-built by the batch job, the web app just serves it.

**Decision: serve pre-built HTML.** The route handler for `/report/{ticker}` reads `data/reports/{ticker}.html` and returns it as `HTMLResponse`. If the file doesn't exist, render a "not yet generated" page with a trigger button. This is the simplest approach and matches the Tier 1 model (pre-built reports + trigger for fresh runs).

### 6. `requirements.txt` (modify — add web deps)
```
fastapi==0.116.1
uvicorn==0.35.0
jinja2==3.1.6
```

### 7. `Makefile` (modify — add web target)
Already added in phase 04. Verify `make web` runs `uvicorn web.app:app --reload --port 8000`.

### 8. Fly.io deployment config
- `fly.toml` (new):
```toml
app = "delta"
primary_region = "sjc"

[build]
  builder = "paketobuildpacks/builder:base"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true

[processes]
  app = "uvicorn web.app:app --host 0.0.0.0 --port 8000"
```

- `.dockerignore` (new): exclude `data/raw/`, `data/chunks/`, `data/chroma/`, `data/eval/`, `data/diffs/` (keep `data/reports/` — the pre-built HTML is served).
- The deployed app needs: Python 3.11, the `src/` code, `data/reports/` (pre-built), and the opencode binary for the trigger endpoint.
- For Tier 1, the trigger endpoint runs `python delta.py {ticker} --years 5` as a subprocess. This requires the full pipeline (fetch, chunk, embed, LLM) to work on the server. Alternatively, pre-build all reports locally and deploy only the static serving. **Recommended: pre-build locally, deploy static serving only.** The trigger endpoint is a stretch goal.

### 9. `AGENTS.md` (modify — update for v2)
Update the agent notes to reflect the v2 structure: `delta.py` CLI, `delta/` package, `web/` app, new Makefile targets, new data directories.

## Constraints
- Do not modify contracts defined in 00-ARCHITECTURE.md.
- Do not implement Tier 2 (any-ticker mode with job queue). The trigger endpoint only works for the 7 cached tickers.
- Do not use a JS framework. Pure HTML + CSS + minimal JS.
- Follow DESIGN.md strictly (dark canvas, green accent, hairline cards, Inter + SF Mono).
- The hero page is the primary DESIGN.md surface — it must look polished, not templated.
- The report page serves pre-built HTML (from phase 04's batch job). Do not re-render from diffs on every request (too slow for a live service).
- The trigger endpoint is optional for Tier 1. If it complicates deployment, ship static-serving only and add the trigger later.

## Acceptance
1. `cd src && uvicorn web.app:app --port 8000` starts the server without error.
2. Visit `http://localhost:8000/` — the hero page renders with DESIGN.md styling (dark canvas, green accent, hairline cards, Inter + SF Mono). Ticker input form is visible and functional.
3. Visit `http://localhost:8000/report/AAPL` — the AAPL change report renders (served from `data/reports/AAPL.html`).
4. Visit `http://localhost:8000/report/INVALID` — shows a "not yet generated" or "ticker not available" page (graceful handling).
5. The ticker input form: entering "AAPL" and clicking "Generate Report" navigates to `/report/AAPL`.
6. `make web` starts the server.
7. `fly deploy` (if Fly.io CLI is set up) deploys the app. The deployed app serves the hero page and pre-built reports.
8. `cd src && python -m unittest discover -s ../tests -v` passes.

## Out of scope
- Tier 2 deployment (any-ticker mode, job queue, progress page)
- User accounts / authentication
- RSS/email digest
- Churn-score comparison table across tickers
- Interactive report features (search, filter, sort within the report)
- Re-rendering reports on every request (pre-built HTML only)
- The trigger endpoint as a required feature (stretch goal; static serving is the MVP)