"""Route handlers for FinDocQA Delta web server.

Static deployment: reports are pre-built offline (`make delta-batch`) and served
as static HTML. Live generation is intentionally disabled — the deploy image has
no pipeline dependencies (see Dockerfile / requirements-web.txt).
"""

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from config import TICKERS, DELTA_YEARS_MAX, DELTA_REPORTS_DIR

ENTITY_NAMES = {
    "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "TSLA": "Tesla, Inc.",
}

def _reports_dir(src_dir: str) -> str:
    return os.path.join(src_dir, DELTA_REPORTS_DIR)


def _available_tickers(src_dir: str) -> list[str]:
    """Return tickers that have a pre-built report HTML."""
    reports = _reports_dir(src_dir)
    available = []
    for ticker in TICKERS:
        if os.path.isfile(os.path.join(reports, f"{ticker}.html")):
            available.append(ticker)
    return available


def register_routes(app: FastAPI, templates, src_dir: str):
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        available = _available_tickers(src_dir)
        return templates.TemplateResponse(request, "index.html", {
            "tickers": TICKERS,
            "available": available,
            "entity_names": ENTITY_NAMES,
            "years_max": DELTA_YEARS_MAX,
        })

    @app.get("/report/{ticker}", response_class=HTMLResponse)
    async def report(request: Request, ticker: str):
        ticker = ticker.upper()
        report_path = os.path.join(_reports_dir(src_dir), f"{ticker}.html")

        if os.path.isfile(report_path):
            with open(report_path) as f:
                html = f.read()
            return HTMLResponse(html)

        if ticker not in TICKERS:
            return templates.TemplateResponse(request, "not_found.html", {
                "ticker": ticker,
                "reason": "unknown_ticker",
            }, status_code=404)

        return templates.TemplateResponse(request, "not_found.html", {
            "ticker": ticker,
            "reason": "not_generated",
        })

    @app.post("/api/trigger/{ticker}")
    async def trigger(ticker: str):
        # Live generation is disabled in the static deploy. Reports are built
        # offline via `make delta-batch`; this endpoint only reports readiness.
        ticker = ticker.upper()
        if ticker not in TICKERS:
            return JSONResponse({"error": f"Unknown ticker: {ticker}"}, status_code=400)

        ready = os.path.isfile(os.path.join(_reports_dir(src_dir), f"{ticker}.html"))
        return JSONResponse(
            {
                "status": "static",
                "ticker": ticker,
                "ready": ready,
                "detail": "Reports are generated offline and served statically.",
            },
            status_code=200 if ready else 501,
        )

    @app.get("/api/status/{ticker}")
    async def status(ticker: str):
        ticker = ticker.upper()
        if ticker not in TICKERS:
            return JSONResponse({"error": f"Unknown ticker: {ticker}"}, status_code=400)

        report_path = os.path.join(_reports_dir(src_dir), f"{ticker}.html")
        return JSONResponse({
            "ready": os.path.isfile(report_path),
            "generating": False,
            "ticker": ticker,
        })

    return app
