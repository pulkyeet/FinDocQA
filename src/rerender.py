"""Re-render Delta report HTML from persisted diff + interpretation data — no LLM.

After a template or report.py change, rebuild the HTML for tickers that already
have persisted pipeline output (data/diffs/{ticker}/) without re-running the
expensive LLM interpretation.

Usage:
  python rerender.py                # all tickers with persisted diffs
  python rerender.py MSFT AAPL      # specific tickers
"""

import glob
import json
import os
import sys

from config import TICKERS, XBRL_DELTA_TAGS
from delta.report import (
    build_report_data, render_html, write_report,
    load_interpretations, build_report_index,
    DELTA_DIFFS_DIR, DELTA_REPORTS_DIR,
)
from delta.xbrl_delta import load_companyfacts, compute_yoy_deltas

ENTITY_NAMES = {
    "AAPL": "Apple Inc.", "AMZN": "Amazon.com, Inc.", "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.", "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation", "TSLA": "Tesla, Inc.",
}


def load_records_by_year(ticker: str) -> dict:
    """Reconstruct {(y_old, y_new): [diff_records]} from persisted jsonl files."""
    records_by_year = {}
    pattern = os.path.join(DELTA_DIFFS_DIR, ticker, "FY*_FY*.jsonl")
    for path in sorted(glob.glob(pattern)):
        base = os.path.basename(path)[:-6]  # strip ".jsonl"
        y_old, y_new = base.split("_")
        with open(path) as f:
            records_by_year[(y_old, y_new)] = [json.loads(ln) for ln in f if ln.strip()]
    return records_by_year


def rerender(ticker: str) -> bool:
    records_by_year = load_records_by_year(ticker)
    if not records_by_year:
        print(f"[skip] {ticker}: no persisted diff records")
        return False

    interpretations, trends = load_interpretations(ticker)

    try:
        cf = load_companyfacts(ticker)
        fys = sorted({y for yp in records_by_year for y in yp})
        xbrl_deltas = compute_yoy_deltas(cf, XBRL_DELTA_TAGS, fys)
    except FileNotFoundError:
        xbrl_deltas = {}

    report = build_report_data(
        ticker, records_by_year, interpretations, trends,
        xbrl_deltas, ENTITY_NAMES.get(ticker, ticker),
    )
    path = write_report(ticker, render_html(report))
    s = report["summary"]
    print(f"[ok] {ticker}: {path}  ({s['material']} material, {s['notable']} notable, "
          f"{s['guard']} guard, {s['sections_with_content']} sections)")
    return True


def main():
    args = [t.upper() for t in sys.argv[1:]] or list(TICKERS.keys())
    done = [t for t in args if rerender(t)]

    have_reports = [t for t in TICKERS if os.path.isfile(os.path.join(DELTA_REPORTS_DIR, f"{t}.html"))]
    if have_reports:
        os.makedirs(DELTA_REPORTS_DIR, exist_ok=True)
        with open(os.path.join(DELTA_REPORTS_DIR, "index.html"), "w") as f:
            f.write(build_report_index(have_reports))
        print(f"[index] {len(have_reports)} reports: {', '.join(sorted(have_reports))}")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")
    main()
